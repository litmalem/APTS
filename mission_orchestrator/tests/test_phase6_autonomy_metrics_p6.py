"""P6 acceptance tests: autonomy metrics computed from the stored records.

Drives the dispatcher through representative outcomes (enacted, review-required,
reactive HALT, reactive DEGRADE self-recovery), seeds execution runs and agent goals,
then checks the metric aggregation the analysis asked for — Decision Enactment Rate,
governed-execution coverage, Autonomy Ratio, human-intervention rate, agent-goal ratio,
and self-recovery rate.
"""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from pentest_subsystem.orchestration import autonomy_metrics as am
from pentest_subsystem.orchestration import deliberative_dispatcher as dd
from pentest_subsystem.orchestration import intention_commitment as ic
from pentest_subsystem.orchestration.autonomy_envelope import build_autonomy_envelope
from pentest_subsystem.orchestration.deliberation import CAPABILITY_SEQUENCE
from pentest_subsystem.orchestration.reactive import arbitrate

NOW = "2026-01-01T00:00:00Z"


def _delib(intention_cap, caps, *, cycle):
    return {"cycle": cycle, "status": "INTENTION_SELECTED", "record_sha256": "d" * 64,
            "beliefs": {"completed_capabilities": []},
            "options": [{"capability_id": c, "sequence_index": CAPABILITY_SEQUENCE.index(c),
                         "utility": 0.9, "precondition_met": True, "goal_already_satisfied": False,
                         "governance_blocked": False} for c in caps],
            "intention": {"capability_id": intention_cap}}


def _envelope(level=2):
    return build_autonomy_envelope(
        envelope_id="env-1", mission_id="m1", orchestration_id="paorch-1", scope_contract_id="s1",
        authorized_level=level, approver="human:ciso", authorization_reference="a1",
        valid_from="2020-01-01T00:00:00Z", valid_until="2030-01-01T00:00:00Z")


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
    def __init__(self, repo):
        self.repo = repo
        self.service = SimpleNamespace(repository=repo)
        self.deliberation = None

    def deliberate(self, oid, **kwargs):
        return {"deliberation": self.deliberation}


@pytest.fixture(autouse=True)
def _no_bdi_migration(monkeypatch):
    monkeypatch.setattr(dd, "ensure_bdi_store", lambda repo: None)


def _seed_execution_runs(repo):
    with repo._connect() as conn:
        conn.execute("CREATE TABLE pentest_exploitation_execution_runs (orchestration_id TEXT,"
                     " attack_path_snapshot_sha256 TEXT, execution_run_id TEXT, record_json TEXT, created_at TEXT)")
        for i, enforced in enumerate([True, False]):  # 1 governed, 1 legacy -> 0.5 coverage
            rec = {"semantics": {"governance_gate_enforced": enforced}}
            conn.execute("INSERT INTO pentest_exploitation_execution_runs VALUES (?,?,?,?,?)",
                         ("paorch-1", "a" * 64, f"xplexec-{i}", json.dumps(rec), NOW))
        conn.commit()


def test_autonomy_report_aggregates_all_metrics(tmp_path):
    repo = _FakeRepo(tmp_path / "m.db")
    runtime = _StubRuntime(repo)
    drv = lambda s, o: {"status": "ok"}
    registry = {"enumeration": drv, "exploitation": drv, "reconnaissance": drv}

    # 1) enacted enumeration
    runtime.deliberation = _delib("enumeration", ["enumeration"], cycle=1)
    dd.dispatch_next(runtime, "paorch-1", enabled=True, registry=registry)

    # 2) exploitation above the L2 envelope -> REVIEW_REQUIRED (human intervention)
    runtime.deliberation = _delib("exploitation", ["exploitation"], cycle=2)
    dd.dispatch_next(runtime, "paorch-1", enabled=True, registry=registry,
                     envelope=_envelope(level=2), now=NOW)

    # 3) reactive HALT (human/safety intervention)
    runtime.deliberation = _delib("enumeration", ["enumeration"], cycle=3)
    halt = arbitrate({"intention": {"capability_id": "enumeration"}}, {"decision_class": "DEFER_TO_STAGE6"})
    dd.dispatch_next(runtime, "paorch-1", enabled=True, registry=registry, reactive_arbitration=halt)

    # 4) reactive DEGRADE -> redirected and dispatched = autonomous self-recovery
    runtime.deliberation = _delib("enumeration", ["enumeration"], cycle=4)
    degrade = arbitrate({"intention": {"capability_id": "enumeration"}}, {
        "decision_class": "REPLAN_LOCAL", "restart_capability": "reconnaissance",
        "degraded_proposal": {"technique": "PASSIVE_DISCOVERY", "rate_cost": 1, "active_concurrency": 1}})
    dd.dispatch_next(runtime, "paorch-1", enabled=True, registry=registry, reactive_arbitration=degrade)

    _seed_execution_runs(repo)
    ic.record_agent_goals(repo, "paorch-1",
                          [{"type": "HIGH_VALUE_ASSET", "subject": "db-1"},
                           {"type": "ANOMALY", "subject": "svc-1"}])

    report = am.autonomy_report(repo, "paorch-1")
    assert am.verify_autonomy_report(report)
    h = report["headline"]

    assert h["decision_enactment_rate"] == 0.25          # only #1 enacted of 4 intentions
    assert h["governed_execution_coverage"] == 0.5       # 1 of 2 runs governed
    assert h["autonomy_ratio"] == 0.5                    # #1 and #4 dispatched of 4 actionable
    assert h["human_intervention_rate"] == 0.5           # #2 review + #3 halt of 4
    assert report["metrics"]["human_intervention"]["mean_dispatches_between_interventions"] == 2.0
    assert h["agent_generated_goal_ratio"] == 0.4        # 2 of (3 fixed + 2)
    assert h["self_recovery_rate"] == 0.5                # 1 degrade recovered of 2 adverse events


def test_empty_orchestration_yields_zeroed_metrics(tmp_path):
    repo = _FakeRepo(tmp_path / "empty.db")
    report = am.autonomy_report(repo, "paorch-none")
    assert am.verify_autonomy_report(report)
    assert report["headline"]["decision_enactment_rate"] == 0.0
    assert report["headline"]["governed_execution_coverage"] == 0.0
    assert report["metrics"]["human_intervention"]["mean_dispatches_between_interventions"] is None


def test_report_integrity_detects_tampering(tmp_path):
    repo = _FakeRepo(tmp_path / "t.db")
    report = am.autonomy_report(repo, "paorch-1")
    assert am.verify_autonomy_report(report)
    report["headline"]["autonomy_ratio"] = 1.0
    assert not am.verify_autonomy_report(report)
