"""P4 acceptance tests: reactive arbitration actually changes dispatch.

A reactive HALT (R1) must stop the dispatch; a reactive DEGRADE (R2) must redirect it
to the gentler probed capability (tighten-only); R3 lets the deliberative intention
stand. A preempted intention is never counted as enacted. Tampered arbitration is
ignored fail-safe.
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from pentest_subsystem.orchestration import deliberative_dispatcher as dd
from pentest_subsystem.orchestration.deliberation import CAPABILITY_SEQUENCE
from pentest_subsystem.orchestration.reactive import arbitrate


def _delib(cap="enumeration"):
    return {"cycle": 1, "status": "INTENTION_SELECTED", "record_sha256": "d" * 64,
            "options": [{"capability_id": cap, "sequence_index": CAPABILITY_SEQUENCE.index(cap),
                         "utility": 0.9}],
            "intention": {"capability_id": cap}}


def _halt_arbitration(cap="enumeration"):
    return arbitrate(_delib(cap), {"decision_class": "DEFER_TO_STAGE6"})


def _degrade_arbitration(cap="enumeration", restart="reconnaissance"):
    return arbitrate(_delib(cap), {
        "decision_class": "REPLAN_LOCAL", "restart_capability": restart,
        "degraded_proposal": {"technique": "PASSIVE_DISCOVERY", "rate_cost": 1, "active_concurrency": 1},
        "pacing_hint": {"cooldown_seconds": 5}})


def _stands_arbitration(cap="enumeration"):
    return arbitrate(_delib(cap), None)  # NO_CHANGE -> R3


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

    def deliberate(self, oid, **kwargs):
        return {"deliberation": self._deliberation}


@pytest.fixture(autouse=True)
def _no_bdi_migration(monkeypatch):
    monkeypatch.setattr(dd, "ensure_bdi_store", lambda repo: None)


def _runtime(tmp_path, cap="enumeration"):
    repo = _FakeRepo(tmp_path / "d.db")
    return _StubRuntime(repo, _delib(cap)), repo


# ---------------------------------------------------------------------------
# 1. R1 HALT stops the dispatch; the driver is never invoked.
# ---------------------------------------------------------------------------
def test_reactive_halt_blocks_dispatch(tmp_path):
    runtime, _ = _runtime(tmp_path)
    calls = []
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"enumeration": lambda s, o: calls.append(o) or {"status": "ok"}},
                           reactive_arbitration=_halt_arbitration())["dispatch"]
    assert calls == []
    assert rec["dispatched"] is False
    assert rec["enacted"] is False
    assert rec["outcome"]["status"] == "REACTIVE_HALT"
    assert rec["reactive_arbitration"]["preemption_kind"] == "HALT"
    assert dd.verify_dispatch_decision(rec)


# ---------------------------------------------------------------------------
# 2. R2 DEGRADE redirects the dispatch to the gentler probed capability.
# ---------------------------------------------------------------------------
def test_reactive_degrade_redirects_dispatch(tmp_path):
    runtime, _ = _runtime(tmp_path, cap="enumeration")
    seen = []
    registry = {"enumeration": lambda s, o: seen.append("enumeration") or {"status": "ok"},
                "reconnaissance": lambda s, o: seen.append("reconnaissance") or {"status": "ok"}}
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True, registry=registry,
                           reactive_arbitration=_degrade_arbitration(restart="reconnaissance"))["dispatch"]
    assert seen == ["reconnaissance"]  # redirected away from the enumeration intention
    assert rec["dispatched"] is True
    assert rec["dispatched_capability_id"] == "reconnaissance"
    assert rec["enacted"] is False  # the intention was preempted
    assert rec["outcome"]["status"] == "DISPATCHED_DEGRADED"
    assert rec["reactive_arbitration"]["preemption_kind"] == "DEGRADE"


# ---------------------------------------------------------------------------
# 3. R3 lets the deliberative intention stand (no preemption).
# ---------------------------------------------------------------------------
def test_reactive_no_change_lets_intention_stand(tmp_path):
    runtime, _ = _runtime(tmp_path)
    calls = []
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"enumeration": lambda s, o: calls.append(o) or {"status": "ok"}},
                           reactive_arbitration=_stands_arbitration())["dispatch"]
    assert calls == ["paorch-1"]
    assert rec["dispatched"] is True
    assert rec["enacted"] is True
    assert rec["reactive_arbitration"]["preempted"] is False


# ---------------------------------------------------------------------------
# 4. honor_reactive reads the latest stored arbitration from the repo.
# ---------------------------------------------------------------------------
def test_latest_stored_arbitration_is_honored(tmp_path):
    runtime, repo = _runtime(tmp_path)
    halt = _halt_arbitration()
    with repo._connect() as conn:
        conn.execute("CREATE TABLE pentest_arbitration_records (arbitration_id TEXT, orchestration_id TEXT,"
                     " record_json TEXT, created_at TEXT)")
        conn.execute("INSERT INTO pentest_arbitration_records VALUES (?,?,?,?)",
                     ("parb-1", "paorch-1", json.dumps(halt), "2026-11-20T00:00:00Z"))
        conn.commit()
    calls = []
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"enumeration": lambda s, o: calls.append(o) or {"status": "ok"}})["dispatch"]
    assert calls == []
    assert rec["outcome"]["status"] == "REACTIVE_HALT"


# ---------------------------------------------------------------------------
# 5. A tampered arbitration record cannot preempt (fail-safe ignore).
# ---------------------------------------------------------------------------
def test_tampered_arbitration_is_ignored(tmp_path):
    runtime, _ = _runtime(tmp_path)
    halt = dict(_halt_arbitration())
    halt["rule"] = "R3_DELIBERATIVE_STANDS"  # breaks the sealed hash
    calls = []
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True,
                           registry={"enumeration": lambda s, o: calls.append(o) or {"status": "ok"}},
                           reactive_arbitration=halt)["dispatch"]
    assert calls == ["paorch-1"]  # tampered HALT ignored -> dispatch proceeds
    assert rec["dispatched"] is True
    assert rec["reactive_arbitration"] is None
