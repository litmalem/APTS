"""P5 acceptance tests: cross-cycle intention commitment + agent-generated goals.

A committed intention is maintained across cycles (single-minded) until it is achieved
or becomes infeasible, instead of being recomputed from scratch; and the agent can
derive its own bounded, advisory goals from observations. The committed intention
steers the dispatcher when commitment is enabled.
"""
import sqlite3
from types import SimpleNamespace

import pytest

from pentest_subsystem.orchestration import deliberative_dispatcher as dd
from pentest_subsystem.orchestration import intention_commitment as ic
from pentest_subsystem.orchestration.deliberation import CAPABILITY_SEQUENCE


def _delib(intention_cap, options, *, cycle=1, completed=()):
    opts = [{"capability_id": c, "sequence_index": CAPABILITY_SEQUENCE.index(c), "utility": u,
             "precondition_met": pm, "goal_already_satisfied": sat, "governance_blocked": False}
            for (c, u, pm, sat) in options]
    return {"cycle": cycle, "status": "INTENTION_SELECTED", "record_sha256": "d" * 64,
            "options": opts, "beliefs": {"completed_capabilities": list(completed)},
            "intention": {"capability_id": intention_cap} if intention_cap else None}


class _FakeRepo:
    def __init__(self, db):
        self.sqlite_path = str(db)

    def initialize(self):
        pass

    def _connect(self):
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


# ---------------------------------------------------------------------------
# 1. reconsider() — single-minded commitment.
# ---------------------------------------------------------------------------
def test_adopt_when_no_prior_commitment():
    d = ic.reconsider(None, _delib("enumeration", [("enumeration", 0.9, True, False)]))
    assert d["commitment_status"] == ic.COMMIT_ADOPTED
    assert d["effective_committed_capability"] == "enumeration"


def test_maintain_commitment_against_a_new_intention():
    # Committed to validation (still feasible); the fresh cycle prefers vuln analysis.
    delib = _delib("vulnerability_analysis",
                   [("vulnerability_analysis", 0.74, True, False), ("validation", 0.46, True, False)])
    d = ic.reconsider("validation", delib)
    assert d["commitment_status"] == ic.COMMIT_MAINTAINED
    assert d["effective_committed_capability"] == "validation"  # not the new intention
    assert d["maintained_against_new_intention"] is True


def test_drop_when_committed_capability_achieved():
    delib = _delib("validation", [("validation", 0.46, True, False),
                                  ("vulnerability_analysis", 0.74, True, True)])  # satisfied
    d = ic.reconsider("vulnerability_analysis", delib)
    assert d["commitment_status"] == ic.COMMIT_DROPPED_ACHIEVED
    assert d["effective_committed_capability"] == "validation"


def test_drop_when_committed_capability_infeasible():
    delib = _delib("validation", [("validation", 0.46, True, False),
                                  ("enumeration", None, False, False)])  # infeasible
    d = ic.reconsider("enumeration", delib)
    assert d["commitment_status"] == ic.COMMIT_DROPPED_INFEASIBLE
    assert d["effective_committed_capability"] == "validation"


# ---------------------------------------------------------------------------
# 2. apply_commitment() — persistence across cycles.
# ---------------------------------------------------------------------------
def test_commitment_is_persisted_and_maintained_across_cycles(tmp_path):
    repo = _FakeRepo(tmp_path / "c.db")
    c1 = ic.apply_commitment(repo, "paorch-1", _delib("validation", [("validation", 0.46, True, False)], cycle=1))
    assert c1["committed_capability"] == "validation"
    assert c1["committed_since_cycle"] == 1
    assert ic.verify_commitment(c1["commitment"])

    # Cycle 2 prefers a different intention, but validation is still feasible.
    c2 = ic.apply_commitment(repo, "paorch-1", _delib(
        "vulnerability_analysis",
        [("vulnerability_analysis", 0.74, True, False), ("validation", 0.46, True, False)], cycle=2))
    assert c2["decision"]["commitment_status"] == ic.COMMIT_MAINTAINED
    assert c2["committed_capability"] == "validation"
    assert c2["committed_since_cycle"] == 1  # commitment age preserved

    assert ic.load_commitment(repo, "paorch-1")["committed_capability"] == "validation"


# ---------------------------------------------------------------------------
# 3. Agent-generated goals from observations.
# ---------------------------------------------------------------------------
def test_derive_agent_goal_from_observation():
    g = ic.derive_agent_goal({"type": "HIGH_VALUE_ASSET", "subject": "db-01"})
    assert g["goal_id"] == "SECURE_HIGH_VALUE_OBSERVATION"
    assert g["origin"] == "AGENT_GENERATED_FROM_OBSERVATION"
    assert g["authority"]["executes"] is False
    assert ic.verify_agent_goal(g)
    assert ic.derive_agent_goal({"type": "UNRECOGNISED"}) is None  # fail-safe: no goal


def test_record_and_list_agent_goals_idempotent(tmp_path):
    repo = _FakeRepo(tmp_path / "g.db")
    signals = [{"type": "HIGH_VALUE_ASSET", "subject": "db-01"},
               {"type": "ANOMALY", "subject": "svc-7"},
               {"type": "NOISE"}]  # ignored
    first = ic.record_agent_goals(repo, "paorch-1", signals)
    assert first["recorded_count"] == 2
    assert first["ignored_count"] == 1
    again = ic.record_agent_goals(repo, "paorch-1", signals)
    assert again["recorded_count"] == 0  # idempotent
    goals = ic.list_agent_goals(repo, "paorch-1")
    assert {g["goal_id"] for g in goals} == {"SECURE_HIGH_VALUE_OBSERVATION", "INVESTIGATE_OBSERVED_ANOMALY"}


# ---------------------------------------------------------------------------
# 4. Dispatcher integration: the committed intention steers dispatch.
# ---------------------------------------------------------------------------
class _StubRuntime:
    def __init__(self, repo):
        self.repo = repo
        self.service = SimpleNamespace(repository=repo)
        self.deliberation = None

    def deliberate(self, oid, **kwargs):
        return {"deliberation": self.deliberation}


@pytest.fixture(autouse=True)
def _no_bdi_migration(monkeypatch):
    monkeypatch.setattr(dd, "ensure_bdi_store", lambda repo: None)


def test_committed_intention_overrides_dispatch_selection(tmp_path):
    repo = _FakeRepo(tmp_path / "d.db")
    runtime = _StubRuntime(repo)
    seen = []
    registry = {"validation": lambda s, o: seen.append("validation") or {"status": "ok"},
                "vulnerability_analysis": lambda s, o: seen.append("vuln") or {"status": "ok"}}

    # Cycle 1: intention is validation -> commit to it.
    runtime.deliberation = _delib("validation", [("validation", 0.46, True, False)], cycle=1)
    dd.dispatch_next(runtime, "paorch-1", enabled=True, registry=registry, use_commitment=True)
    assert seen == ["validation"]

    # Cycle 2: the fresh intention prefers vuln analysis, but commitment maintains
    # validation (still feasible) -> the dispatcher pursues validation, not vuln.
    runtime.deliberation = _delib(
        "vulnerability_analysis",
        [("vulnerability_analysis", 0.74, True, False), ("validation", 0.46, True, False)], cycle=2)
    rec = dd.dispatch_next(runtime, "paorch-1", enabled=True, registry=registry,
                           use_commitment=True)["dispatch"]
    assert seen == ["validation", "validation"]  # not "vuln"
    assert rec["dispatched_capability_id"] == "validation"
    assert rec["intention_commitment"]["commitment_status"] == ic.COMMIT_MAINTAINED
    assert dd.verify_dispatch_decision(rec)
