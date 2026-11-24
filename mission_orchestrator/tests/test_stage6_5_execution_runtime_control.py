from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from http.server import ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sqlite3
from threading import Event, Thread
import time
from uuid import uuid4

import pytest

from execution_subsystem.authorization_contract import parse_time
from execution_subsystem.adapter_contract import canonical_adapter_contract
from execution_subsystem.adapter_repository import ExecutionAdapterRepository
from execution_subsystem.adapter_service import ExecutionAdapterService
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.request_repository import ExecutionRequestRepository
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.execution_contract import (ExecutionRequestConflict, ExecutionRequestIntegrityError,
    ExecutionRequestValidationError, ExecutionSourceRejected, canonical_json, with_integrity)
from execution_subsystem.governance_client import ExecutionGovernanceClient
from execution_subsystem.request_repository import ExecutionRepositoryError
from execution_subsystem.runtime_api import ExecutionSubsystemStage65Handler, ROUTE, serve
from execution_subsystem.runtime_contract import (ATTEMPT_DOMAIN, CANCEL_SCHEMA, EVENT_DOMAIN,
    KILL_SCHEMA, MAX_ATTEMPTS, RETRY_SCHEMA, RUNTIME_CONTROL_VERSION, START_SCHEMA, TERMINAL,
    canonical_runtime_contract, normalize_command, normalize_start, verify_attempt, verify_event,
    verify_runtime_contract)
from execution_subsystem.runtime_control import RuntimeResources, RuntimeStopped
from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
from execution_subsystem.runtime_service import ExecutionRuntimeService
from execution_subsystem.target_broker import TargetBroker
from tests.test_stage6_1_canonical_execution_request_contract import intake_for, http
from tests.test_stage6_2_authoritative_execution_authorization import NOW
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority, authority_server
from tests.test_stage6_4_authorized_tool_adapters_sandboxing import adapter_seed, target_server


@pytest.fixture
def ctx(tmp_path, adapter_seed, target_server):
    pdb, mdb, run = adapter_seed
    pentest, mission = tmp_path / "pentest.db", tmp_path / "mission.db"
    shutil.copy2(pdb, pentest); shutil.copy2(mdb, mission)
    authority = UniqueAuthority()
    now = [NOW]
    service = ExecutionRuntimeService(ExecutionRuntimeRepository(tmp_path / "execution.db"),
        ExecutionAuthorizationProposalSource(pentest), MissionAuthorizationSource(mission), authority, clock=lambda:now[0])
    request = service.create_request(intake_for(run, "stage65"))
    intake = {"schema_version":START_SCHEMA, "invocation_request_id":"toolreq-stage65", "idempotency_key":"idem-stage65",
        "execution_id":request["execution_id"], "envelope_sha256":request["envelope"]["integrity"]["canonical_sha256"],
        "requested_by":"stage65-test"}
    target_server[2].update({"sleep":0, "redirect":False})
    target_server[1].clear()
    try:
        yield service, intake, authority, request, target_server, now
    finally:
        service.close()
        target_server[2].update({"sleep":0, "redirect":False})


def wait_for(service, identity, predicate=lambda x:x["state"] in TERMINAL, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = service.repository.get_attempt(identity)
        if item and predicate(item):
            return item
        time.sleep(0.02)
    raise AssertionError((service._failures, service.repository.get_attempt(identity)))


def cancellation(item):
    suffix = uuid4().hex
    return {"schema_version":CANCEL_SCHEMA, "command_request_id":"rtcmd-"+suffix,
        "idempotency_key":"idem-cancel-"+suffix, "requested_by":"local-test", "reason":"Operator stop",
        "attempt_id":item["attempt_id"], "attempt_sha256":item["record"]["integrity"]["canonical_sha256"]}


def kill_payload(ctx):
    suffix = uuid4().hex
    return {"schema_version":KILL_SCHEMA, "command_request_id":"rtcmd-"+suffix,
        "idempotency_key":"idem-kill-"+suffix, "requested_by":"local-test", "reason":"Emergency stop",
        "mission_id":ctx[3]["envelope"]["execution_request"]["mission_id"]}


def retry_payload(intake, item):
    suffix = uuid4().hex
    return {**intake, "schema_version":RETRY_SCHEMA, "invocation_request_id":"toolreq-retry-"+suffix,
        "idempotency_key":"idem-retry-"+suffix, "retry_of_attempt_id":item["attempt_id"],
        "expected_head_sha256":item["head_sha256"]}


@contextmanager
def server_for(service):
    handler = type("IsolatedStage65Handler", (ExecutionSubsystemStage65Handler,), {"service":service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


class BeforeIOFailure(TargetBroker):
    def pin(self, *args, **kwargs):
        raise OSError("isolated synthetic resolver failure")


def test_exact_predecessor_contract_and_no_self_certification():
    c = canonical_runtime_contract()
    assert c["predecessor"]["contract_sha256"] == canonical_adapter_contract()["integrity"]["canonical_sha256"]
    assert c["repository"]["migration_level"] == 5 and c["next_stage"] == "6.6"
    assert verify_runtime_contract(c)
    c["retry_policy"]["requires_proven_no_target_io"] = False
    assert not verify_runtime_contract(c)


def test_recon_retry_keeps_exact_stage63_admission_bound_to_request():
    repository = ExecutionRuntimeRepository(":memory:")
    request_sha = "a" * 64
    gate = {"gateway_id":"xgate-recon", "status":"ADMITTED", "request_sha256":request_sha}
    req = {"proposing_agent":{"role":"RECONNAISSANCE"},
           "integrity":{"canonical_sha256":request_sha}, "execution_id":"exec-recon"}
    prior_attempt = {"record":{"status":"RESERVED", "execution_id":"exec-recon"}}

    # Even when this is an explicit runtime retry, Recon must carry the same
    # exact Stage 6.3 admission into the next adapter reservation.
    assert repository._reservation_gateway(gate, [prior_attempt], req) is gate
    with pytest.raises(ExecutionSourceRejected, match="RECON_ACTION_REQUIRES_STAGE6_3_GATEWAY_ADMISSION"):
        repository._reservation_gateway(None, [prior_attempt], req)
    with pytest.raises(ExecutionSourceRejected, match="RECON_GATEWAY_ADMISSION_REQUEST_BINDING_MISMATCH"):
        repository._reservation_gateway({**gate, "request_sha256":"b" * 64}, [prior_attempt], req)

    # The existing non-Recon policy remains unchanged.
    ordinary = {**req, "proposing_agent":{"role":"EXPLOITATION"}}
    assert repository._reservation_gateway(gate, [prior_attempt], ordinary) is None


def test_native_success_lifecycle_and_atomic_terminal_result(ctx):
    service, intake, authority, _, target, _ = ctx
    out = service.start_execution(intake)
    assert out["created"] and out["state"] == "AUTHORIZED"
    item = wait_for(service, out["attempt_id"])
    assert item["state"] == "SUCCEEDED"
    assert [e["state_after"] for e in item["events"] if e["event_type"] != "HEARTBEAT"] == ["AUTHORIZED", "DISPATCHED", "RUNNING", "SUCCEEDED"]
    assert verify_attempt(item["record"]) and all(verify_event(e) for e in item["events"])
    assert item["events"][-1]["data"]["resources_closed"] is True
    assert item["invocation"]["result"]["semantics"]["target_network_io_performed"] is True
    assert len(target[1]) == 1 and len(authority.calls) >= 2
    assert not item["invocation"]["result"]["semantics"]["vulnerability_confirmed"]


def test_replay_get_never_dispatches_or_revalidates(ctx):
    service, intake, authority, _, target, _ = ctx
    item = wait_for(service, service.start_execution(intake)["attempt_id"])
    before = (len(target[1]), len(authority.calls))
    for _ in range(3):
        replay = service.start_execution(intake)
        read = service.get_attempt(item["attempt_id"])
        assert replay["created"] is False and read["target_network_io_performed"] is False
        assert read["head_sha256"] == item["head_sha256"]
    assert (len(target[1]), len(authority.calls)) == before


def test_heartbeat_server_owned_while_broker_waits(ctx):
    service, intake, _, _, target, _ = ctx
    target[2]["sleep"] = 1.3
    out = service.start_execution(intake)
    item = wait_for(service, out["attempt_id"])
    heartbeat = [e for e in item["events"] if e["event_type"] == "HEARTBEAT"]
    assert heartbeat and item["state"] == "SUCCEEDED"
    assert all(e["actor"] == service.owner_id for e in heartbeat)


def test_cancel_during_real_socket_read_stops_before_target_returns(ctx):
    service, intake, _, _, target, _ = ctx
    target[2]["sleep"] = 3
    out = service.start_execution(intake)
    item = wait_for(service, out["attempt_id"], lambda x:bool(target[1]))
    began = time.monotonic()
    command = service.control(cancellation(item))
    final = wait_for(service, out["attempt_id"])
    assert final["state"] == "CANCELLED" and time.monotonic()-began < 1.5
    assert final["events"][-1]["data"]["resources_closed"] and command["record"]["outcome"] == "STOP_REQUESTED"
    assert final["invocation"]["result"]["semantics"]["target_network_io_performed"] is True
    assert not service.repository.retryable(final)


def test_cancel_during_dns_no_target_io_and_worker_is_reaped(ctx):
    service, intake, _, _, target, _ = ctx
    entered, release = Event(), Event()
    original = service.broker.pin
    def held(*args, **kwargs):
        entered.set()
        while not release.wait(0.02):
            kwargs["runtime"].check()
        return original(*args, **kwargs)
    service.broker.pin = held
    out = service.start_execution(intake)
    assert entered.wait(3)
    item = service.repository.get_attempt(out["attempt_id"])
    service.control(cancellation(item))
    final = wait_for(service, out["attempt_id"])
    release.set()
    assert final["state"] == "CANCELLED" and not target[1]
    assert final["invocation"]["result"]["semantics"]["target_network_io_performed"] is False
    assert not service._handles


def test_emergency_kill_running_socket_and_latches_new_admission(ctx):
    service, intake, _, request, target, now = ctx
    target[2]["sleep"] = 3
    out = service.start_execution(intake)
    wait_for(service, out["attempt_id"], lambda x:bool(target[1]))
    command = service.control(kill_payload(ctx), kill=True)
    assert wait_for(service, out["attempt_id"])["state"] == "ABORTED"
    assert command["record"]["outcome"] == "KILL_LATCHED"
    now[0] += timedelta(seconds=2)
    source = {**request["envelope"]["intake"], "request_id":"ereq-new", "idempotency_key":"idem-new"}
    req = service.create_request(source)
    with pytest.raises(ExecutionSourceRejected, match="KILL_LATCHED"):
        service.start_execution({**intake, "invocation_request_id":"toolreq-new", "idempotency_key":"idem-newtool",
            "execution_id":req["execution_id"], "envelope_sha256":req["envelope"]["integrity"]["canonical_sha256"]})
    assert len(target[1]) == 1


def test_pre_io_failure_manual_retry_new_identity_fresh_authority_budget(ctx):
    service, intake, authority, _, target, now = ctx
    service.broker = BeforeIOFailure()
    one = wait_for(service, service.start_execution(intake)["attempt_id"])
    assert one["state"] == "FAILED" and service.repository.retryable(one)
    with service.repository._connect() as conn:
        assert service.repository._network_reservation_cost(one['invocation'], conn) == 0
    service.broker = TargetBroker()
    now[0] += timedelta(seconds=1.1)
    prior_calls = len(authority.calls)
    retry = retry_payload(intake, one)
    two = wait_for(service, service.start_execution(retry, retry=True)["attempt_id"])
    assert two["state"] == "SUCCEEDED" and two["record"]["attempt_number"] == 2
    with service.repository._connect() as conn:
        assert service.repository._network_reservation_cost(two['invocation'], conn) > 0
    assert two["attempt_id"] != one["attempt_id"] and two["record"]["retry_of_attempt_id"] == one["attempt_id"]
    assert two["invocation"]["record"]["budget_before"]["mission"] == 1
    assert len(authority.calls) >= prior_calls + 2 and len(target[1]) == 1
    assert service.start_execution(retry, retry=True)["created"] is False


def test_retry_bound_and_no_automatic_retry(ctx):
    service, intake, _, _, target, now = ctx
    service.broker = BeforeIOFailure()
    current = wait_for(service, service.start_execution(intake)["attempt_id"])
    for _ in range(MAX_ATTEMPTS-1):
        now[0] += timedelta(seconds=1.1)
        current = wait_for(service, service.start_execution(retry_payload(intake,current),retry=True)["attempt_id"])
    now[0] += timedelta(seconds=1.1)
    with pytest.raises(ExecutionSourceRejected, match="MAX_ATTEMPTS"):
        service.start_execution(retry_payload(intake,current), retry=True)
    assert len(service.repository.list_attempts(intake["execution_id"])) == MAX_ATTEMPTS and not target[1]


@pytest.mark.parametrize("state", ["SUCCEEDED", "CANCELLED", "ABORTED", "TIMEOUT"])
def test_retry_rejects_completed_or_possible_io(ctx, state):
    service, intake, _, _, target, now = ctx
    if state != "SUCCEEDED":
        target[2]["sleep"] = 3
    out = service.start_execution(intake)
    if state in {"CANCELLED", "ABORTED"}:
        active = wait_for(service, out["attempt_id"], lambda x:bool(target[1]))
        service.control(kill_payload(ctx) if state == "ABORTED" else cancellation(active), kill=state=="ABORTED")
    elif state == "TIMEOUT":
        # A short wall timer can expire during native startup without target I/O.
        # Wait for the real target request, then expire the persisted deadline
        # through the fixture clock so this case always tests timeout after I/O.
        active = wait_for(service, out["attempt_id"], lambda x:bool(target[1]))
        now[0] = parse_time(active["invocation"]["record"]["controls"]["deadline"], "deadline")
    item = wait_for(service, out["attempt_id"])
    assert item["state"] == state
    assert item["invocation"]["result"]["semantics"]["target_network_io_performed"] is True
    assert item["events"][-1]["data"]["resources_closed"] is True
    assert not service.repository.retryable(item)
    if state != "TIMEOUT":
        now[0] += timedelta(seconds=2)
    expected = "RETRY_REQUIRES_PROVEN_NO_TARGET_IO_FAILURE" if state == "TIMEOUT" else None
    with pytest.raises(ExecutionSourceRejected, match=expected):
        service.start_execution(retry_payload(intake,item),retry=True)
    assert len(service.repository.list_attempts(intake["execution_id"])) == 1


def test_forged_retry_head_does_not_launch(ctx):
    service, intake, _, _, target, now = ctx
    service.broker = BeforeIOFailure()
    first = wait_for(service, service.start_execution(intake)["attempt_id"])
    now[0] += timedelta(seconds=2)
    retry = {**retry_payload(intake,first), "expected_head_sha256":"0"*64}
    with pytest.raises(ExecutionSourceRejected, match="EXACT_LATEST"):
        service.start_execution(retry,retry=True)
    assert not target[1]


def test_duplicate_concurrent_start_one_attempt_one_io(ctx):
    service, intake, _, _, target, _ = ctx
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _:service.start_execution(intake), range(4)))
    assert sum(r["created"] for r in results) == 1
    final = wait_for(service, results[0]["attempt_id"])
    assert final["state"] == "SUCCEEDED" and len(target[1]) == 1


@pytest.mark.parametrize("field,value", [("decision","ALLOW"),("command","whoami"),("target","127.0.0.1"),
    ("adapter_id","custom"),("timeout",99),("heartbeat",True),("status","SUCCEEDED"),("owner_id","caller"),
    ("authorization_id","eauth-caller"),("max_attempts",99)])
def test_runtime_start_rejects_caller_authority_or_controls(ctx, field, value):
    with pytest.raises(ExecutionRequestValidationError):
        ctx[0].start_execution({**ctx[1], field:value})
    assert not ctx[4][1] and not ctx[2].calls


@pytest.mark.parametrize("decision", ["DENY", "REVIEW"])
def test_authority_denial_never_creates_runtime_or_target_io(ctx, decision):
    ctx[2].decision = decision
    with pytest.raises(ExecutionSourceRejected):
        ctx[0].start_execution(ctx[1])
    assert not ctx[0].repository.list_attempts(ctx[1]["execution_id"]) and not ctx[4][1]


def test_authority_revalidation_during_run_aborts(ctx):
    service, intake, authority, _, target, _ = ctx
    target[2]["sleep"] = 3
    out = service.start_execution(intake)
    wait_for(service,out["attempt_id"],lambda x:bool(target[1]))
    authority.decision = "DENY"
    final = wait_for(service,out["attempt_id"])
    assert final["state"] == "ABORTED" and final["events"][-1]["data"]["reason_code"] == "RUNTIME_GOVERNANCE_REVALIDATION_FAILED"


def test_terminal_cancel_noop_and_command_replay(ctx):
    service = ctx[0]
    final = wait_for(service,service.start_execution(ctx[1])["attempt_id"])
    command = cancellation(final)
    one = service.control(command)
    two = service.control(command)
    assert one["created"] and not two["created"] and one["record"] == two["record"]
    assert one["record"]["outcome"] == "TERMINAL_NOOP"
    assert service.repository.get_attempt(final["attempt_id"])["head_sha256"] == final["head_sha256"]
    with pytest.raises(ExecutionRequestConflict):
        service.control({**command, "reason":"changed"})


def test_owner_exclusive_and_historical_runner_refuses_v5(ctx):
    service = ctx[0]
    with pytest.raises(ExecutionRepositoryError, match="OWNER_ALREADY_ACTIVE"):
        ExecutionRuntimeService(ExecutionRuntimeRepository(service.repository.sqlite_path), service.proposal_source,
            service.mission_source, ctx[2], clock=lambda:NOW)
    with pytest.raises(ExecutionRepositoryError):
        ExecutionAdapterRepository(service.repository.sqlite_path).initialize()


def test_http_asynchronous_gateway_and_spoofed_heartbeat_rejected(ctx):
    service, intake, _, _, target, _ = ctx
    with server_for(service) as url:
        code, out, headers = http(url+ROUTE,intake)
        assert code == 202 and "APTSExecutionSubsystem/6.5" in headers["Server"]
        final = wait_for(service,out["attempt_id"])
        code, read, _ = http(url+ROUTE+"/"+final["attempt_id"])
        assert code == 200 and read["state"] == "SUCCEEDED" and not read["target_network_io_performed"]
        for path in ["heartbeats","results","transitions"]:
            code, result, _ = http(url+"/api/execution/runtime/"+path,{"status":"SUCCEEDED"})
            assert code == 409
        code, result, _ = http(url+ROUTE+"?execution_id="+intake["execution_id"])
        assert code == 200 and result["count"] == 1
        assert len(target[1]) == 1


def test_real_external_authority_http_native_loopback_runtime(ctx):
    service, intake, authority, _, target, _ = ctx
    with authority_server(authority) as authority_url:
        service.governance_client = ExecutionGovernanceClient(authority_url)
        final = wait_for(service,service.start_execution(intake)["attempt_id"])
    assert final["state"] == "SUCCEEDED" and len(target[1]) == 1


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "example.com"])
def test_remote_control_plane_bind_rejected(host):
    with pytest.raises(ExecutionRequestValidationError):
        serve(host,0)


@pytest.mark.parametrize("table", ["execution_runtime_attempts", "execution_runtime_events", "execution_runtime_commands"])
def test_runtime_append_only_sql_guards(ctx, table):
    service = ctx[0]
    item = wait_for(service,service.start_execution(ctx[1])["attempt_id"])
    service.control(cancellation(item))
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM "+table)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE "+table+" SET record_sha256=record_sha256")


def test_corrupted_event_index_and_hash_rejected(ctx):
    service = ctx[0]
    item = wait_for(service,service.start_execution(ctx[1])["attempt_id"])
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_runtime_events_no_update")
        conn.execute("UPDATE execution_runtime_events SET state_after='FAILED' WHERE event_id=?", (item["events"][-1]["event_id"],))
    with pytest.raises(ExecutionRequestIntegrityError):
        service.repository.get_attempt(item["attempt_id"])


def test_recovery_orphan_abort_without_redispatch(ctx):
    service, intake, _, _, target, _ = ctx
    # Simulate crash after atomic authorization/reservation, before dispatch.
    auth = service._fresh_authorization({**intake,"schema_version":"apts-execution-adapter-intake-v1"})
    invocation, _ = service.repository.reserve_adapter({**intake,"schema_version":"apts-execution-adapter-intake-v1"},
        auth["authorization_id"], final_check=lambda a:service._final_admission_check(ctx[3]["envelope"],a),
        runtime_context={"runtime_intake":intake,"owner_id":service.owner_id})
    identity = service.repository.list_attempts(intake["execution_id"])[0]["attempt_id"]
    service.close()
    reopened = ExecutionRuntimeService(ExecutionRuntimeRepository(service.repository.sqlite_path), service.proposal_source,
        service.mission_source, ctx[2], clock=lambda:NOW)
    try:
        item = reopened.repository.get_attempt(identity)
        assert item["state"] == "ABORTED" and item["target_io_uncertain"] and item["invocation"]["result"] is None
        assert reopened.start_execution(intake)["created"] is False and not target[1]
        assert not reopened.repository.retryable(item)
        assert reopened.recovered_attempts == [identity]
    finally:
        reopened.close()


def test_runtime_resources_stop_closes_registered_handles_immediately():
    calls=[]
    guard=RuntimeResources(time.monotonic()+10)
    with guard.attach(lambda:calls.append("closed")):
        guard.stop("CANCELLED","test-cancel")
        assert calls == ["closed"]
        with pytest.raises(RuntimeStopped):
            guard.check()
    assert not guard._closers


def test_retry_history_survives_restart_and_predecessor_replay(ctx):
    service, intake, authority, _, target, now = ctx
    service.broker = BeforeIOFailure()
    one = wait_for(service,service.start_execution(intake)["attempt_id"])
    now[0] += timedelta(seconds=1.1)
    retry = retry_payload(intake,one)
    service.broker = TargetBroker()
    two = wait_for(service,service.start_execution(retry,retry=True)["attempt_id"])
    before = len(target[1])
    service.close()
    reopened = ExecutionRuntimeService(ExecutionRuntimeRepository(service.repository.sqlite_path), service.proposal_source,
        service.mission_source, authority, clock=lambda:now[0])
    try:
        assert reopened.repository.get_attempt(two["attempt_id"])["head_sha256"] == two["head_sha256"]
        assert reopened.start_execution(retry,retry=True)["created"] is False
        assert reopened.start_execution(intake)["created"] is False and len(target[1]) == before
        assert not reopened.recovered_attempts
    finally:
        reopened.close()


def test_kill_latch_survives_restart_without_target_action(ctx):
    service, intake, authority, _, target, now = ctx
    command = service.control(kill_payload(ctx),kill=True)
    service.close()
    reopened = ExecutionRuntimeService(ExecutionRuntimeRepository(service.repository.sqlite_path),service.proposal_source,
        service.mission_source,authority,clock=lambda:now[0])
    try:
        with pytest.raises(ExecutionSourceRejected,match="KILL_LATCHED"):
            reopened.start_execution(intake)
        assert not target[1]
        assert command["record"]["target_attempts"] == []
    finally:
        reopened.close()


def test_cancel_invalid_attempt_hash_rejected_no_side_effect(ctx):
    service = ctx[0]
    item = wait_for(service,service.start_execution(ctx[1])["attempt_id"])
    with pytest.raises(ExecutionRequestIntegrityError):
        service.control({**cancellation(item),"attempt_sha256":"0"*64})
    assert service.repository.get_attempt(item["attempt_id"])["head_sha256"] == item["head_sha256"]


def test_blocked_dns_deadline_reaps_native_worker_and_can_retry(ctx):
    service, intake, _, _, target, now = ctx
    entered = Event()
    original = service.broker.pin
    def slow_pin(*args,**kwargs):
        entered.set()
        while True:
            kwargs["runtime"].check()
            time.sleep(0.01)
    service.broker.pin = slow_pin
    out = service.start_execution(intake)
    assert entered.wait(5), "native worker did not reach the blocked DNS phase"
    active = service.repository.get_attempt(out["attempt_id"])
    now[0] = parse_time(active["invocation"]["record"]["controls"]["deadline"], "deadline")
    item = wait_for(service,out["attempt_id"])
    assert item["state"] == "TIMEOUT" and not target[1]
    assert item["invocation"]["result"]["semantics"]["target_network_io_performed"] is False
    assert item["events"][-1]["data"]["resources_closed"] is True
    assert service.repository.retryable(item)
    pid = next(e["data"]["worker_pid"] for e in item["events"] if e["event_type"] == "RUNNING")
    if os.name != "nt":
        with pytest.raises(ProcessLookupError):
            os.kill(pid,0)
    # Reaching the persisted deadline already advances past the rate window.
    service.broker.pin = original
    successor = wait_for(service,service.start_execution(retry_payload(intake,item),retry=True)["attempt_id"])
    assert successor["state"] == "SUCCEEDED"


def test_cancel_interrupts_slow_external_boundary_authority(ctx):
    service, intake, authority, _, target, _ = ctx
    original = authority.evaluate_authorization
    entered, release = Event(), Event()
    calls = [0]
    def slow(payload):
        calls[0] += 1
        if calls[0] > 1:
            entered.set(); release.wait(5)
        return original(payload)
    authority.evaluate_authorization = slow
    out = service.start_execution(intake)
    assert entered.wait(3)
    item = service.repository.get_attempt(out["attempt_id"])
    began = time.monotonic()
    service.control(cancellation(item))
    final = wait_for(service,out["attempt_id"])
    release.set()
    assert final["state"] == "CANCELLED" and not target[1] and time.monotonic()-began < 1.5


def test_mission_terminal_change_aborts_running_io(ctx):
    service, intake, _, request, target, _ = ctx
    target[2]["sleep"] = 3
    out = service.start_execution(intake)
    wait_for(service,out["attempt_id"],lambda x:bool(target[1]))
    with sqlite3.connect(service.mission_source.sqlite_path) as conn:
        conn.execute("UPDATE mission_states SET state='ABORTED',terminal=1,state_version=state_version+1 WHERE mission_id=?",
            (request["envelope"]["execution_request"]["mission_id"],))
    final = wait_for(service,out["attempt_id"])
    assert final["state"] == "ABORTED" and len(target[1]) == 1


def test_lost_supervisor_heartbeat_watchdog_aborts_and_closes_socket(ctx):
    service, intake, _, _, target, _ = ctx
    target[2]["sleep"] = 3
    service._supervise = lambda identity,guard,claim,envelope:guard.done.wait(5)
    began = time.monotonic()
    final = wait_for(service,service.start_execution(intake)["attempt_id"])
    assert final["state"] == "ABORTED" and time.monotonic()-began < 3
    assert final["events"][-1]["data"]["reason_code"] == "RUNTIME_HEARTBEAT_LOST"
    assert final["events"][-1]["data"]["resources_closed"]


def test_retry_charges_budget_without_refund(ctx):
    service, intake, authority, _, target, now = ctx
    authority.mutate = lambda result:result.update({"constraints":{"max_actions":1}})
    service.broker = BeforeIOFailure()
    item = wait_for(service,service.start_execution(intake)["attempt_id"])
    now[0] += timedelta(seconds=1.1)
    with pytest.raises(ExecutionSourceRejected,match="ACTION_BUDGET"):
        service.start_execution(retry_payload(intake,item),retry=True)
    assert not target[1] and len(service.repository.list_attempts(intake["execution_id"])) == 1


def test_concurrency_slot_released_after_cancel_resources_closed(ctx):
    service, intake, _, request, target, now = ctx
    target[2]["sleep"] = 3
    out = service.start_execution(intake)
    active = wait_for(service,out["attempt_id"],lambda x:bool(target[1]))
    service.control(cancellation(active))
    wait_for(service,out["attempt_id"])
    now[0] += timedelta(seconds=1.1)
    target[2]["sleep"] = 0
    req=service.create_request({**request["envelope"]["intake"],"request_id":"ereq-successor","idempotency_key":"idem-successor"})
    next_intake={**intake,"invocation_request_id":"toolreq-successor","idempotency_key":"idem-successor-tool",
        "execution_id":req["execution_id"],"envelope_sha256":req["envelope"]["integrity"]["canonical_sha256"]}
    final=wait_for(service,service.start_execution(next_intake)["attempt_id"])
    assert final["state"] == "SUCCEEDED" and final["invocation"]["record"]["budget_before"]["mission"] == 1


def test_shutdown_aborts_active_and_releases_owner_after_cleanup(ctx):
    service, intake, authority, _, target, _ = ctx
    target[2]["sleep"] = 3
    out=service.start_execution(intake)
    wait_for(service,out["attempt_id"],lambda x:bool(target[1]))
    service.close()
    final=service.repository.get_attempt(out["attempt_id"])
    assert final["state"] == "ABORTED" and final["events"][-1]["data"]["reason_code"] == "RUNTIME_SHUTDOWN"
    reopened=ExecutionRuntimeService(ExecutionRuntimeRepository(service.repository.sqlite_path),service.proposal_source,
        service.mission_source,authority,clock=lambda:NOW)
    reopened.close()


@pytest.mark.parametrize("table,column", [("execution_runtime_attempts","record_sha256"),
    ("execution_runtime_attempts","owner_id"),("execution_runtime_events","record_sha256"),
    ("execution_runtime_events","event_sequence")])
def test_runtime_projection_tamper_rejected(ctx,table,column):
    service=ctx[0]
    item=wait_for(service,service.start_execution(ctx[1])["attempt_id"])
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER "+table+"_no_update")
        if column == "event_sequence":
            conn.execute("UPDATE "+table+" SET event_sequence=99 WHERE event_id=?",(item["events"][-1]["event_id"],))
        else:
            conn.execute("UPDATE "+table+" SET "+column+"=? WHERE attempt_id=?",("0"*64 if column == "record_sha256" else "tampered",item["attempt_id"]))
    with pytest.raises(ExecutionRequestIntegrityError):
        service.repository.get_attempt(item["attempt_id"])


def test_hard_link_database_cannot_bypass_exclusive_owner(ctx,tmp_path):
    alias=tmp_path/"hardlinked.db"
    os.link(ctx[0].repository.sqlite_path,alias)
    with pytest.raises(ExecutionRepositoryError,match="HARD_LINKED"):
        ExecutionRuntimeService(ExecutionRuntimeRepository(alias),ctx[0].proposal_source,
            ctx[0].mission_source,ctx[2],clock=lambda:NOW)


@pytest.mark.parametrize("version", [6,99])
def test_future_or_invalid_repository_version_not_mutated(tmp_path,version):
    path=tmp_path/"foreign.db"
    repo=ExecutionAdapterRepository(path); repo.initialize()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE execution_repository_meta SET migration_level=?",(version,))
    before=path.read_bytes()
    with pytest.raises(ExecutionRepositoryError):
        ExecutionRuntimeRepository(path).initialize()
    assert path.read_bytes() == before


@pytest.mark.parametrize("route", ["/api/execution/runtime/attempts?command=x",
    "/api/execution/runtime/attempts?execution_id=exec-a&execution_id=exec-b",
    "/api/execution/execution-runtime-contract?override=x"])
def test_http_query_override_rejected(ctx,route):
    with server_for(ctx[0]) as url:
        code,_,_=http(url+route)
        assert code == 400


def test_legacy_adapter_route_uses_runtime_attempt(ctx):
    service=ctx[0]
    with server_for(service) as url:
        code,out,_=http(url+"/api/execution/gateway/tool-invocations",
            {**ctx[1],"schema_version":"apts-execution-adapter-intake-v1"})
        assert code == 202
        final=wait_for(service,out["attempt_id"])
        assert final["state"] == "SUCCEEDED"
        code,audit,_=http(url+"/api/execution/gateway/tool-invocations/"+final["record"]["invocation_id"])
        assert code == 200 and not audit["target_network_io_performed"]


def child_runtime(paths,intake,channel,launch):
    service=ExecutionRuntimeService(ExecutionRuntimeRepository(paths[0]),ExecutionAuthorizationProposalSource(paths[1]),
        MissionAuthorizationSource(paths[2]),UniqueAuthority(),clock=lambda:NOW)
    if launch:
        out=service.start_execution(intake)
        channel.send(out["attempt_id"])
        while True:
            time.sleep(0.1)
    else:
        adapted={**intake,"schema_version":"apts-execution-adapter-intake-v1"}
        auth=service._fresh_authorization(adapted)
        envelope=service.repository.get(intake["execution_id"])["envelope"]
        service.repository.reserve_adapter(adapted,auth["authorization_id"],final_check=lambda a:service._final_admission_check(envelope,a),
            runtime_context={"runtime_intake":intake,"owner_id":service.owner_id})
        channel.send(service.repository.list_attempts(intake["execution_id"])[0]["attempt_id"])
        os._exit(17)


@pytest.mark.parametrize("launch", [False,True])
def test_real_process_crash_os_owner_fence_and_no_restart_dispatch(ctx,launch):
    service,intake,authority,_,target,_=ctx
    target[2]["sleep"]=3
    paths=[str(service.repository.sqlite_path),str(service.proposal_source.sqlite_path),str(service.mission_source.sqlite_path)]
    service.close()
    mp=multiprocessing.get_context("spawn")
    reader,writer=mp.Pipe(duplex=False)
    process=mp.Process(target=child_runtime,args=(paths,intake,writer,launch))
    process.start()
    try:
        assert reader.poll(15)
        identity=reader.recv()
        if launch:
            deadline=time.monotonic()+5
            while not target[1] and time.monotonic()<deadline:
                time.sleep(0.02)
            assert target[1]
            process.terminate()
        process.join(timeout=5)
        assert not process.is_alive() and process.exitcode != 0
        before=len(target[1])
        reopened=ExecutionRuntimeService(ExecutionRuntimeRepository(paths[0]),service.proposal_source,service.mission_source,
            authority,clock=lambda:NOW)
        try:
            final=reopened.repository.get_attempt(identity)
            assert final["state"] == "ABORTED" and final["target_io_uncertain"]
            assert reopened.start_execution(intake)["created"] is False
            assert len(target[1]) == before and not reopened.repository.retryable(final)
        finally:
            reopened.close()
    finally:
        if process.is_alive():
            process.terminate(); process.join(timeout=5)
        reader.close(); writer.close()


@pytest.mark.parametrize("repository_class", [ExecutionRequestRepository,ExecutionAuthorizationRepository,
    ExecutionGatewayRepository,ExecutionAdapterRepository])
def test_atomic_upgrade_all_supported_predecessor_levels(tmp_path,repository_class):
    path=tmp_path/"upgrade.db"
    repository_class(path).initialize()
    active=ExecutionRuntimeRepository(path)
    assert active.migration_level() == 5
    assert not active.live_attempts() and active.legacy_quarantined_count() == 0
    assert ExecutionRuntimeRepository(path).migration_level() == 5


def test_legacy_v4_orphan_retained_and_quarantined(ctx):
    service,intake,authority,request,target,_=ctx
    service.close()
    path=service.repository.sqlite_path
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER execution_adapter_invocations_v5_guard")
        for table in ["execution_runtime_commands","execution_runtime_events","execution_runtime_attempts"]:
            conn.execute("DROP TABLE "+table)
        conn.execute("UPDATE execution_repository_meta SET migration_level=4")
    legacy=ExecutionAdapterService(ExecutionAdapterRepository(path),service.proposal_source,service.mission_source,
        authority,clock=lambda:NOW)
    adapted={**intake,"schema_version":"apts-execution-adapter-intake-v1"}
    auth=legacy._fresh_authorization(adapted)
    claim,_=legacy.repository.reserve_adapter(adapted,auth["authorization_id"],final_check=lambda a:legacy._final_admission_check(request["envelope"],a))
    reopened=ExecutionRuntimeService(ExecutionRuntimeRepository(path),service.proposal_source,service.mission_source,
        authority,clock=lambda:NOW)
    try:
        assert reopened.health()["legacy_quarantined_invocations"] == 1
        assert reopened.repository.get_adapter_invocation(claim["invocation_id"])["record"] == claim["record"]
        assert not reopened.recovered_attempts and not target[1]
        with pytest.raises(ExecutionSourceRejected):
            reopened.start_execution(intake)
    finally:
        reopened.close()
