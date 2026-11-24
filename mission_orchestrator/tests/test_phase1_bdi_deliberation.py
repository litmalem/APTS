from __future__ import annotations

from copy import deepcopy
import sqlite3

import pytest

from pentest_subsystem.orchestration.deliberation import (
    DeliberationValidationError,
    deliberate,
    verify_deliberation_record,
)
from pentest_subsystem.orchestration.deliberation_store import DeliberativeOrchestratorRepository
from pentest_subsystem.orchestration.task_graph import CAPABILITY_SEQUENCE
from tests.test_stage5_1_full_agentic_pentest_workflow_orchestrator import start_payload
from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import materialize


def _graph(repo_graph: dict | None = None) -> dict:
    if repo_graph is not None:
        return deepcopy(repo_graph)
    return {
        "orchestration_id": "paorch-test", "plan_version": 1,
        "nodes": [{"capability_id": c, "subtask_id": f"st-{c}", "status": "PENDING"} for c in CAPABILITY_SEQUENCE],
    }


def _simulate(assets: int, hypotheses: int, start: dict | None = None, budget: int = 20, blocked=()):
    """Closed loop: deliberate, apply the intended capability's effect to a toy world, repeat."""
    graph = _graph()
    world = {"in_scope_assets": 0, "enumerated_assets": 0, "open_hypotheses": 0, "candidate_paths": 0,
             "validated_paths": 0, "rejected_paths": 0, "proposed_paths": 0, "impact_assessed_paths": 0}
    world.update(start or {})
    for node in graph["nodes"]:
        if node["capability_id"] == "vulnerability_analysis" and (start or {}).get("_vuln_done"):
            node["status"] = "SUCCEEDED"
    world.pop("_vuln_done", None)
    order, final = [], None
    for cycle in range(1, 15):
        record = deliberate(graph, {**world, "budget_remaining": budget, "blocked_capabilities": list(blocked)},
                            cycle=cycle)
        assert verify_deliberation_record(record)
        if record["intention"] is None:
            final = record["status"]
            break
        cap = record["intention"]["capability_id"]
        order.append(cap)
        budget -= 1
        next(n for n in graph["nodes"] if n["capability_id"] == cap)["status"] = "SUCCEEDED"
        if cap == "reconnaissance":
            world["in_scope_assets"] = assets
        elif cap == "enumeration":
            world["enumerated_assets"] = world["in_scope_assets"]
        elif cap == "vulnerability_analysis":
            world["open_hypotheses"] = hypotheses
        elif cap == "attack_path_analysis":
            world["candidate_paths"] = world["open_hypotheses"]
        elif cap == "validation":
            world["validated_paths"], world["open_hypotheses"] = world["candidate_paths"], 0
        elif cap == "exploitation":
            world["proposed_paths"] = world["validated_paths"]
        elif cap == "impact_analysis":
            world["impact_assessed_paths"] = world["proposed_paths"]
    return order, final


def test_non_fixed_plan_different_evidence_gives_different_intention_order():
    clean, status_clean = _simulate(assets=2, hypotheses=0)
    vulnerable, status_vuln = _simulate(assets=2, hypotheses=3)
    assert clean != vulnerable
    assert "exploitation" not in clean and "validation" not in clean
    assert vulnerable == ["reconnaissance", "enumeration", "vulnerability_analysis",
                          "attack_path_analysis", "validation", "exploitation", "impact_analysis"]
    assert status_clean == status_vuln == "GOALS_SATISFIED"


def test_prior_evidence_skips_completed_work():
    order, status = _simulate(
        assets=2, hypotheses=2,
        start={"in_scope_assets": 2, "enumerated_assets": 2, "open_hypotheses": 2, "_vuln_done": True},
    )
    assert order[0] == "attack_path_analysis"
    assert "reconnaissance" not in order and "enumeration" not in order
    assert status == "GOALS_SATISFIED"


def test_stops_on_goal_satisfaction_not_end_of_sequence():
    order, status = _simulate(assets=1, hypotheses=0)
    assert status == "GOALS_SATISFIED"
    assert len(order) < len(CAPABILITY_SEQUENCE)


def test_budget_exhaustion_stops_loop():
    order, status = _simulate(assets=2, hypotheses=2, budget=2)
    assert len(order) == 2 and status == "BUDGET_EXHAUSTED"


def test_governance_block_removes_option_and_never_selects_it():
    order, status = _simulate(assets=2, hypotheses=2, blocked=("exploitation",))
    assert "exploitation" not in order
    assert status == "NO_FEASIBLE_OPTION"


def test_record_carries_explanation_and_non_execution_authority():
    record = deliberate(_graph(), {"budget_remaining": 5}, cycle=1)
    assert record["intention"]["capability_id"] == "reconnaissance"
    assert record["authority"] == {"executes": False, "mints_authorization": False,
                                   "mutates_task_graph": False, "execution_authority": "STAGE6"}
    assert len(record["options"]) == len(CAPABILITY_SEQUENCE)
    assert record["intention"]["dispatch_mode"] == "REQUIRES_PLAN_REORDER"  # no READY node in synthetic graph
    tampered = deepcopy(record)
    tampered["intention"]["capability_id"] = "exploitation"
    assert not verify_deliberation_record(tampered)


def test_policy_gated_capabilities_are_flagged_and_penalised():
    record = deliberate(_graph(), {"in_scope_assets": 1, "enumerated_assets": 1, "candidate_paths": 1,
                                   "open_hypotheses": 1, "budget_remaining": 3,
                                   "blocked_capabilities": []}, cycle=1)
    by_cap = {o["capability_id"]: o for o in record["options"]}
    assert by_cap["validation"]["requires_policy_approval"] is True
    assert by_cap["enumeration"]["requires_policy_approval"] is False


@pytest.mark.parametrize("bad", [{"budget_remaining": -1}, {"in_scope_assets": True},
                                 {"unknown": 1}, {"blocked_capabilities": ["nope"]}])
def test_invalid_observations_fail_closed(bad):
    with pytest.raises(DeliberationValidationError):
        deliberate(_graph(), bad, cycle=1)


def _repo(tmp_path):
    repo = DeliberativeOrchestratorRepository(tmp_path / "pentest.db")
    _, _, task, _, _ = materialize(repo)
    orch, *_ = repo.start_orchestration(task["pentest_task_id"], start_payload())
    return repo, orch


def test_store_persists_goals_intentions_records_and_replays_idempotently(tmp_path):
    repo, orch = _repo(tmp_path)
    oid = orch["orchestration_id"]
    record, created = repo.run_deliberation_cycle(oid, {"budget_remaining": 10})
    assert created and record["intention"]["capability_id"] == "reconnaissance"
    assert record["intention"]["dispatch_mode"] == "DEFAULT_SEQUENCE_COMPATIBLE"  # recon node is READY
    replay, created2 = repo.run_deliberation_cycle(oid, {"budget_remaining": 10})
    assert created2 is False and replay["cycle"] == record["cycle"]
    nxt, created3 = repo.run_deliberation_cycle(oid, {"budget_remaining": 9, "in_scope_assets": 2})
    assert created3 and nxt["cycle"] == 2 and nxt["intention"]["capability_id"] == "enumeration"
    assert [r["cycle"] for r in repo.list_deliberations(oid)] == [1, 2]
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pentest_agent_goals").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM pentest_agent_intentions").fetchone()[0] == 2


def test_store_is_append_only_and_does_not_mutate_task_graph(tmp_path):
    repo, orch = _repo(tmp_path)
    oid = orch["orchestration_id"]
    repo.run_deliberation_cycle(oid, {"budget_remaining": 10})
    assert repo.get_orchestration(oid)["task_graph_sha256"] == orch["task_graph_sha256"]
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        for sql in ("UPDATE pentest_agent_goals SET satisfied=1", "DELETE FROM pentest_agent_intentions",
                    "UPDATE pentest_deliberation_records SET status='X'",
                    "DELETE FROM pentest_deliberation_records"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)


def test_stage51_contract_is_unchanged_by_phase1():
    from pentest_subsystem.orchestration.orchestrator import (
        canonical_agentic_pentest_orchestrator_contract, verify_agentic_pentest_orchestrator_contract)
    assert verify_agentic_pentest_orchestrator_contract(canonical_agentic_pentest_orchestrator_contract())
