"""P1 acceptance tests: the Deliberative Dispatcher closes the decision->action loop.

The BDI ``intention`` must actually select which governed driver runs next (behind the
A/B flag), the deterministic sweep stays as the fallback, and every dispatch is sealed
and counted so the Decision Enactment Rate (P6) is measurable. The dispatcher executes
nothing itself.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from pentest_subsystem.orchestration import deliberative_dispatcher as dd
from pentest_subsystem.orchestration.deliberation import CAPABILITY_SEQUENCE, deliberate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _delib(options, intention, *, cycle=1, status="INTENTION_SELECTED"):
    return {"cycle": cycle, "status": status, "options": options,
            "intention": intention, "record_sha256": "d" * 64}


def _opt(cap, utility):
    return {"capability_id": cap, "sequence_index": CAPABILITY_SEQUENCE.index(cap), "utility": utility}


class _FakeRepo:
    def __init__(self, db):
        self.sqlite_path = str(db)

    def initialize(self):
        pass

    def _connect(self):
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


class _StubRuntime:
    def __init__(self, repo, deliberation):
        self.repo = repo
        self.service = SimpleNamespace(repository=repo)
        self._deliberation = deliberation
        self.deliberate_calls = []

    def deliberate(self, oid, **kwargs):
        self.deliberate_calls.append((oid, kwargs))
        return {"deliberation": self._deliberation}


@pytest.fixture(autouse=True)
def _no_bdi_migration(monkeypatch):
    # The dispatch side-table is created lazily; isolate from the BDI migration.
    monkeypatch.setattr(dd, "ensure_bdi_store", lambda repo: None)


# ---------------------------------------------------------------------------
# 1. Flag selects the policy: DELIBERATIVE follows the intention; SWEEP follows order.
# ---------------------------------------------------------------------------
def test_plan_dispatch_deliberative_follows_intention():
    # enumeration is first in sequence among candidates, but the intention wants
    # vulnerability_analysis — deliberative mode must follow the intention.
    options = [_opt("enumeration", 0.88), _opt("vulnerability_analysis", 0.74)]
    deliberation = _delib(options, {"capability_id": "vulnerability_analysis"})

    on = dd.plan_dispatch(deliberation, enabled=True, registered_capabilities={"vulnerability_analysis"})
    assert on["mode"] == dd.MODE_DELIBERATIVE
    assert on["selected_capability_id"] == "vulnerability_analysis"

    off = dd.plan_dispatch(deliberation, enabled=False, registered_capabilities={"enumeration"})
    assert off["mode"] == dd.MODE_SWEEP_FALLBACK
    assert off["selected_capability_id"] == "enumeration"  # deterministic sequence order


def test_plan_dispatch_stops_when_no_intention():
    deliberation = _delib([], None, status="GOALS_SATISFIED")
    plan = dd.plan_dispatch(deliberation, enabled=True, registered_capabilities=set())
    assert plan["selected_capability_id"] is None
    assert "GOALS_SATISFIED" in plan["selection_reason"]


def test_plan_dispatch_only_selects_feasible_candidates():
    # Only enumeration is feasible (non-null utility); recon has utility None.
    options = [{"capability_id": "reconnaissance", "sequence_index": 0, "utility": None},
               _opt("enumeration", 0.88)]
    deliberation = _delib(options, {"capability_id": "enumeration"})
    off = dd.plan_dispatch(deliberation, enabled=False, registered_capabilities={"enumeration"})
    assert off["candidate_capabilities"] == ["enumeration"]
    assert off["selected_capability_id"] == "enumeration"


# ---------------------------------------------------------------------------
# 2. Realistic deliberation record from the pure BDI layer drives selection.
# ---------------------------------------------------------------------------
def test_dispatch_uses_real_deliberation_intention():
    graph = {"orchestration_id": "paorch-1", "plan_version": 1,
             "nodes": [{"capability_id": c, "subtask_id": f"st-{c}", "status": "READY"}
                       for c in CAPABILITY_SEQUENCE]}
    # in_scope assets exist, nothing enumerated yet -> enumeration is the intention.
    observations = {"in_scope_assets": 2, "enumerated_assets": 0, "budget_remaining": 10}
    record = deliberate(graph, observations, cycle=1)
    assert record["intention"]["capability_id"] == "enumeration"

    plan = dd.plan_dispatch(record, enabled=True, registered_capabilities={"enumeration"})
    assert plan["selected_capability_id"] == "enumeration"
    assert plan["driver_registered"] is True


# ---------------------------------------------------------------------------
# 3. dispatch_next invokes the governed driver and seals an enacted decision.
# ---------------------------------------------------------------------------
def test_dispatch_next_enacts_intention_and_is_measurable(tmp_path):
    repo = _FakeRepo(tmp_path / "dispatch.db")
    deliberation = _delib([_opt("enumeration", 0.88)], {"capability_id": "enumeration"})
    runtime = _StubRuntime(repo, deliberation)

    calls = []

    def enumeration_driver(service, oid):
        calls.append(oid)
        return {"status": "ok", "created": True, "enumeration_run_id": "enum-1"}

    out = dd.dispatch_next(runtime, "paorch-1", enabled=True, registry={"enumeration": enumeration_driver})
    rec = out["dispatch"]

    assert calls == ["paorch-1"]
    assert rec["mode"] == dd.MODE_DELIBERATIVE
    assert rec["selected_capability_id"] == "enumeration"
    assert rec["dispatched"] is True
    assert rec["enacted"] is True
    assert rec["outcome"]["status"] == "DISPATCHED"
    assert rec["authority"]["executes"] is False
    assert dd.verify_dispatch_decision(rec)

    metric = dd.enactment_rate(repo, "paorch-1")
    assert metric["deliberations_with_intention"] == 1
    assert metric["intentions_enacted"] == 1
    assert metric["decision_enactment_rate"] == 1.0


def test_dispatch_next_without_driver_records_but_does_not_enact(tmp_path):
    repo = _FakeRepo(tmp_path / "dispatch.db")
    deliberation = _delib([_opt("enumeration", 0.88)], {"capability_id": "enumeration"})
    runtime = _StubRuntime(repo, deliberation)

    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True, registry={})["dispatch"]
    assert rec["dispatched"] is False
    assert rec["enacted"] is False
    assert rec["outcome"]["status"] == "NO_DRIVER_REGISTERED"

    metric = dd.enactment_rate(repo, "paorch-1")
    assert metric["intentions_enacted"] == 0
    assert metric["decision_enactment_rate"] == 0.0


def test_sweep_fallback_does_not_enact_a_differing_intention(tmp_path):
    repo = _FakeRepo(tmp_path / "dispatch.db")
    # Sweep picks enumeration (sequence-first) but the intention wanted
    # vulnerability_analysis -> the intention is NOT enacted.
    options = [_opt("enumeration", 0.88), _opt("vulnerability_analysis", 0.95)]
    deliberation = _delib(options, {"capability_id": "vulnerability_analysis"})
    runtime = _StubRuntime(repo, deliberation)

    driver = lambda service, oid: {"status": "ok"}
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=False,
                           registry={"enumeration": driver, "vulnerability_analysis": driver})["dispatch"]
    assert rec["mode"] == dd.MODE_SWEEP_FALLBACK
    assert rec["selected_capability_id"] == "enumeration"
    assert rec["dispatched"] is True
    assert rec["enacted"] is False  # dispatched capability != intention

    metric = dd.enactment_rate(repo, "paorch-1")
    assert metric["deliberations_with_intention"] == 1
    assert metric["intentions_enacted"] == 0


def test_driver_error_is_recorded_not_raised(tmp_path):
    repo = _FakeRepo(tmp_path / "dispatch.db")
    deliberation = _delib([_opt("enumeration", 0.88)], {"capability_id": "enumeration"})
    runtime = _StubRuntime(repo, deliberation)

    def boom(service, oid):
        raise RuntimeError("driver blew up")

    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True, registry={"enumeration": boom})["dispatch"]
    assert rec["dispatched"] is False
    assert rec["enacted"] is False
    assert rec["outcome"]["status"] == "DRIVER_ERROR"
    assert "driver blew up" in rec["outcome"]["error"]


# ---------------------------------------------------------------------------
# 4. Integrity + the A/B flag resolution.
# ---------------------------------------------------------------------------
def test_dispatch_decision_integrity_detects_tampering(tmp_path):
    repo = _FakeRepo(tmp_path / "dispatch.db")
    deliberation = _delib([_opt("enumeration", 0.88)], {"capability_id": "enumeration"})
    runtime = _StubRuntime(repo, deliberation)
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"enumeration": lambda s, o: {"status": "ok"}})["dispatch"]
    assert dd.verify_dispatch_decision(rec)
    rec["enacted"] = False
    assert not dd.verify_dispatch_decision(rec)


def test_flag_resolution(monkeypatch):
    monkeypatch.delenv(dd.DISPATCH_FLAG_ENV, raising=False)
    assert dd.dispatch_enabled() is False
    assert dd.dispatch_enabled(True) is True
    monkeypatch.setenv(dd.DISPATCH_FLAG_ENV, "on")
    assert dd.dispatch_enabled() is True
    assert dd.dispatch_enabled(False) is False  # explicit arg wins
