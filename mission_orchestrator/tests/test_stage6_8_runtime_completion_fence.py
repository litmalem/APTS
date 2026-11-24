"""Deterministic completion races, using isolated authority and loopback I/O."""
from threading import Event, Thread, current_thread
import sqlite3
import time

import pytest

import execution_subsystem.runtime_service as runtime_service
import execution_subsystem.runtime_control as runtime_control
from execution_subsystem.request_repository import ExecutionRepositoryError
from execution_subsystem.runtime_contract import TERMINAL
from execution_subsystem.runtime_control import RuntimeResources, RuntimeStopped
from tests.test_stage6_4_authorized_tool_adapters_sandboxing import adapter_seed, target_server
from tests.test_stage6_5_execution_runtime_control import wait_for, cancellation
from tests.test_stage6_7_vep_construction_integrity import ctx as vep_ctx, construction_payload
from tests.test_stage6_8_cleanup_rollback_post_action_verification import ctx as cleanup_ctx


@pytest.fixture(params=["vep_ctx", "cleanup_ctx"])
def ctx(request):
    return request.getfixturevalue(request.param)


def test_supervisor_held_before_probe_cannot_revalidate_after_terminal(ctx, monkeypatch):
    service, intake, authority, _, target, _ = ctx
    entered, release = Event(), Event()
    threads = []
    original_context = service._current_context
    original_run = service._run_reserved
    original_supervise = service._supervise

    def tracked_thread(*args, **kwargs):
        thread = Thread(*args, **kwargs)
        threads.append(thread)
        return thread

    def supervise(*args):
        current_thread().name = "completion-fence-supervisor"
        return original_supervise(*args)

    def context(envelope):
        value = original_context(envelope)
        if current_thread().name == "completion-fence-supervisor":
            entered.set()
            assert release.wait(5)
        return value

    def run(*args, **kwargs):
        value = original_run(*args, **kwargs)
        assert entered.wait(5)
        return value

    monkeypatch.setattr(runtime_service, "REVALIDATE_SECONDS", 0)
    monkeypatch.setattr(runtime_service, "Thread", tracked_thread)
    monkeypatch.setattr(service, "_supervise", supervise)
    monkeypatch.setattr(service, "_current_context", context)
    monkeypatch.setattr(service, "_run_reserved", run)
    try:
        item = wait_for(service, service.start_execution(intake)["attempt_id"])
        counts = len(authority.calls), len(target[1])
        with sqlite3.connect(service.repository.sqlite_path) as conn:
            conn.execute("CREATE TRIGGER vep_write_failure BEFORE INSERT ON execution_veps "
                         "BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END;")
        with pytest.raises(ExecutionRepositoryError):
            service.construct_vep(construction_payload(service, item))
        release.set()
        # A probe scheduled by the released monitor is also in this list.
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
        assert item["state"] == "SUCCEEDED" and len(target[1]) == 1
        assert service.list_veps(intake["execution_id"])["count"] == 0
        assert service.get_evidence(item["attempt_id"])["sealed"]
        assert counts == (len(authority.calls), len(target[1]))
        health = service.health()
        assert health["runtime_completion_fence_enabled"]
        assert health["runtime_authorization_quiescence_seconds"] == 2.0
    finally:
        release.set()


def test_probe_scheduled_before_completion_but_entered_after_terminal_is_fenced(ctx, monkeypatch):
    service, intake, authority, _, target, _ = ctx
    entered, release, finished = Event(), Event(), Event()
    original_probe = service._probe_authority
    original_run = service._run_reserved

    def probe(*args):
        entered.set()
        try:
            assert release.wait(5)
            return original_probe(*args)
        finally:
            finished.set()

    def run(*args, **kwargs):
        value = original_run(*args, **kwargs)
        assert entered.wait(5)
        return value

    monkeypatch.setattr(runtime_service, "REVALIDATE_SECONDS", 0)
    monkeypatch.setattr(service, "_probe_authority", probe)
    monkeypatch.setattr(service, "_run_reserved", run)
    try:
        item = wait_for(service, service.start_execution(intake)["attempt_id"])
        counts = len(authority.calls), len(target[1])
        release.set()
        assert finished.wait(5)
        assert item["state"] == "SUCCEEDED" and counts == (2, 1)
        assert counts == (len(authority.calls), len(target[1]))
    finally:
        release.set()


@pytest.mark.parametrize("phase", ["source_before_governance", "governance_in_flight"])
def test_completion_drains_admitted_probe_and_discards_late_authorization(ctx, monkeypatch, phase):
    service, intake, authority, _, target, _ = ctx
    run_completed, entered, release, probe_finished = Event(), Event(), Event(), Event()
    guards = []
    original_probe = service._probe_authority
    original_run = service._run_reserved
    original_context = service._current_context
    original_authority = authority.evaluate_authorization

    def probe(*args):
        current_thread().name = "completion-fence-admitted-probe"
        try:
            assert run_completed.wait(5)
            return original_probe(*args)
        finally:
            probe_finished.set()

    def run(*args, **kwargs):
        guards.append(kwargs["runtime"])
        value = original_run(*args, **kwargs)
        run_completed.set()
        assert entered.wait(5)
        return value

    def context(envelope):
        value = original_context(envelope)
        if phase == "source_before_governance" and current_thread().name == "completion-fence-admitted-probe":
            entered.set()
            assert release.wait(5)
        return value

    def evaluate(payload):
        if phase == "governance_in_flight" and current_thread().name == "completion-fence-admitted-probe":
            entered.set()
            assert release.wait(5)
        return original_authority(payload)

    monkeypatch.setattr(runtime_service, "REVALIDATE_SECONDS", 0)
    monkeypatch.setattr(service, "_probe_authority", probe)
    monkeypatch.setattr(service, "_run_reserved", run)
    monkeypatch.setattr(service, "_current_context", context)
    monkeypatch.setattr(authority, "evaluate_authorization", evaluate)
    try:
        out = service.start_execution(intake)
        assert entered.wait(5) and guards[0].done.wait(5)
        # Terminal publication must wait for this already admitted helper.
        assert service.repository.get_attempt(out["attempt_id"])["state"] not in TERMINAL
        assert len(authority.calls) == 2
        release.set()
        item = wait_for(service, out["attempt_id"])
        assert probe_finished.wait(5) and guards[0]._authorization_idle.is_set()
        expected_calls = 2 if phase == "source_before_governance" else 3
        assert item["state"] == "SUCCEEDED" and len(authority.calls) == expected_calls
        # A late response is not stored as a usable authorization record.
        with sqlite3.connect(service.repository.sqlite_path) as conn:
            assert conn.execute("SELECT count(*) FROM execution_authorizations").fetchone()[0] == 2
        counts = len(authority.calls), len(target[1])
        payload = construction_payload(service, item)
        service.construct_vep(payload)
        assert not service.construct_vep(payload)["created"]
        assert counts == (len(authority.calls), len(target[1])) == (expected_calls, 1)
        assert not service._failures
    finally:
        release.set()


def test_cancelled_boundary_waiting_for_authorization_lock_cannot_query_after_terminal(ctx, monkeypatch):
    service, intake, authority, _, target, _ = ctx
    entered = Event()
    helpers = []

    def tracked_thread(*args, **kwargs):
        action = kwargs["target"]
        def call():
            entered.set()
            action()
        thread = Thread(*args, **{**kwargs, "target":call})
        helpers.append(thread)
        return thread

    monkeypatch.setattr(runtime_service, "REVALIDATE_SECONDS", 60)
    monkeypatch.setattr(runtime_control, "Thread", tracked_thread)
    # Admission on this thread can use the RLock; the boundary helper must wait.
    with service._authorization_lock:
        out = service.start_execution(intake)
        assert entered.wait(5)
        began = time.monotonic()
        active = service.repository.get_attempt(out["attempt_id"])
        service.control(cancellation(active))
        item = wait_for(service, out["attempt_id"])
        assert item["state"] == "CANCELLED" and time.monotonic() - began < 1.5
        assert len(authority.calls) == 1 and not target[1]
    for helper in helpers:
        helper.join(timeout=5)
        assert not helper.is_alive()
    assert len(authority.calls) == 1 and not target[1]
    assert service.get_evidence(item["attempt_id"])["sealed"] and not service._failures


@pytest.mark.parametrize("limit", ["quiescence", "wall_deadline"])
def test_completion_wait_is_bounded_and_keeps_authorization_closed(monkeypatch, limit):
    if limit == "quiescence":
        monkeypatch.setattr(runtime_control, "HEARTBEAT_TIMEOUT_SECONDS", 0.08)
    guard = RuntimeResources(time.monotonic() + 5)
    entered, release = Event(), Event()

    def authority_work():
        with guard.authorization():
            entered.set()
            assert release.wait(5)

    helper = Thread(target=authority_work)
    helper.start()
    try:
        assert entered.wait(1)
        if limit == "wall_deadline":
            guard.tighten_deadline(time.monotonic() + 0.08)
        began = time.monotonic()
        guard.finish()
        assert time.monotonic() - began < 0.5 and guard.done.is_set()
        if limit == "quiescence":
            assert (guard.state, guard.reason) == ("ABORTED", "RUNTIME_AUTHORIZATION_QUIESCENCE_TIMEOUT")
        else:
            assert (guard.state, guard.reason) == ("TIMEOUT", "RUNTIME_WALL_DEADLINE")
        with pytest.raises(RuntimeStopped):
            with guard.authorization():
                pytest.fail("closed attempt admitted new authority work")
        guard.finish()
    finally:
        release.set()
        helper.join(timeout=5)
    assert not helper.is_alive() and guard._authorization_idle.is_set()
