from copy import deepcopy
import json

import pytest

from pentest_subsystem.symbolic_planner import compile_problem, plan, action_mask, normalize_model, verify
from pentest_subsystem.masked_ppo import MaskedPPO
from pentest_subsystem.attack_path_workspace import create_plan, history
from pentest_subsystem.attack_path_planning import AttackPathPlanningAgentService, _objective_projection
from tests.test_stage5_5_attack_path_planning_agent import _start_repo
from tests.test_stage5_4_vulnerability_hypothesis_agent import knowledge_item
from pentest_subsystem.web_ui import PentestWebMixin, ASSETS
from unittest.mock import patch


def scenario():
    def action(name, pre, effects, cost=1):
        return {"action_id": name, "hypothesis_id": name, "label": name, "preconditions": pre,
                "effects": effects, "cost": cost, "impact": 0, "confidence": .9,
                "belief": "UNKNOWN", "feedback_refs": []}
    return {"initial_facts": ["observed:web"], "goal_predicates": ["goal:assessed"],
            "actions": [action("entry", ["observed:web"], ["access:web"]),
                        action("objective", ["access:web"], ["goal:assessed"]),
                        action("direct", ["observed:web"], ["goal:assessed"], 5)]}


def test_causal_chain_and_cost_ranked_alternatives():
    p = plan(scenario())
    assert [a["action_id"] for a in p["paths"][0]["steps"]] == ["entry", "objective"]
    assert p["paths"][0]["cost"] < p["paths"][1]["cost"]
    assert {"from": "entry", "to": "objective", "predicate": "access:web"} in p["dependency_edges"]
    assert verify(p) and p["semantics"]["mission_achieved"] is False


def test_mask_never_selects_unmet_or_conflicting_actions():
    p = scenario()
    assert action_mask(p["actions"], p["initial_facts"]) == [True, False, True]
    p["actions"][0]["belief"] = "CONFLICTING"
    assert action_mask(p["actions"], p["initial_facts"]) == [False, False, True]
    for path in plan(p)["paths"]:
        assert "entry" not in [a["action_id"] for a in path["steps"]]


def test_cycles_and_missing_prerequisites_are_not_assumed_true():
    p = scenario()
    p["actions"] = p["actions"][:2]
    p["actions"][0]["preconditions"] = ["goal:assessed"]
    result = plan(p)
    assert result["status"] == "NO_FEASIBLE_PLAN"
    assert result["unreachable_goals"] == ["goal:assessed"]
    assert len(result["gaps"]) == 2


def test_limits_and_deterministic_replay():
    p = scenario()
    assert plan(p) == plan(p)
    result = plan(p, max_expansions=1)
    assert result["search_limited"] and not result["paths"]
    assert len(plan(p, max_paths=1)["paths"]) == 1


@pytest.mark.parametrize("model", [
    {"effects": []}, {"effects": ["shell; command"]}, {"effects": ["ok"], "command": "x"},
    {"effects": ["ok"], "cost": float("nan")}, {"effects": ["ok"], "cost": True},
])
def test_invalid_symbolic_contracts_fail_closed(model):
    with pytest.raises(ValueError):
        normalize_model(model)


def test_hypothesis_contract_propagates_effects_and_objective(tmp_path):
    knowledge = knowledge_item()
    knowledge["planning_model"] = {"preconditions": [], "effects": ["goal:assessed"], "cost": 2}
    repo, _, task, orch, _, _, hyp, *_ = _start_repo(tmp_path, knowledge_items=[knowledge])
    task = {"task": deepcopy(task)}
    task["task"]["objective"]["goal_predicates"] = ["goal:assessed"]
    p = compile_problem(task, hyp)
    assert p["goal_basis"] == "MISSION_PREDICATES"
    assert p["actions"][0]["model_basis"] == "CTI_SYMBOLIC_CONTRACT"
    assert plan(p)["paths"]
    assert _objective_projection(task) == task["task"]["objective"]


def test_versioned_snapshots_idempotency_lineage_and_tamper(tmp_path):
    repo, _, _, orch, _, _, _, *_ = _start_repo(tmp_path)
    service = AttackPathPlanningAgentService(repo)
    payload = {"orchestration_id": orch["orchestration_id"]}
    first = create_plan(service, payload)
    assert first["created"]
    assert not create_plan(service, payload)["created"]
    second = create_plan(service, {**payload, "max_paths": 3})["record"]
    assert second["revision"] == 2
    assert second["previous_sha256"] == first["record"]["integrity"]["canonical_sha256"]
    assert len(history(repo, orch["orchestration_id"])) == 2
    with repo._connect() as conn:
        data = deepcopy(second)
        data["mission_id"] = "other"
        conn.execute("UPDATE pentest_symbolic_plan_revisions SET record_json=? WHERE revision=2", (json.dumps(data),))
    with pytest.raises(ValueError, match="integrity"):
        history(repo, orch["orchestration_id"])


def test_authoritative_feedback_holds_affected_candidate(tmp_path):
    repo, _, task, orch, _, _, hyp, *_ = _start_repo(tmp_path)
    hid = hyp["output"]["vulnerability_hypotheses"][0]["hypothesis_id"]
    record = {"feedback_id": "fb-1", "orchestration_id": orch["orchestration_id"],
              "feedback_type": "CONFLICTING_EVIDENCE", "subject_capability_id": "attack_path_analysis",
              "evidence_refs": ["evidence-1"], "metadata": {"hypothesis_ids": [hid]},
              "integrity": {"canonical_sha256": "a" * 64}}
    p = plan(compile_problem(task, hyp, [record]))
    assert not p["paths"] and p["gaps"][0]["belief"] == "CONFLICTING"
    record["orchestration_id"] = "other"
    with pytest.raises(ValueError, match="mismatch"):
        compile_problem(task, hyp, [record])


def test_ppo_trains_offline_restores_and_obeys_masks():
    p = scenario()
    policy = MaskedPPO()
    before = list(policy.weights)
    stats = policy.train([p], episodes=80)
    assert stats["successes"] > 0 and policy.weights != before
    restored = MaskedPPO.restore(policy.export())
    mask = action_mask(p["actions"], p["initial_facts"])
    probs = restored.probabilities(p["actions"], p["initial_facts"], p["goal_predicates"], mask)
    assert probs[1] == 0 and sum(probs) == pytest.approx(1)
    assert restored.probabilities(p["actions"], [], [], [False]*3) == [0,0,0]
    assert plan(p, policy=restored)["policy"] == "MASKED_PPO_EXPANSION_ORDER"
    with pytest.raises(ValueError):
        MaskedPPO.restore(MaskedPPO().export())


def test_ui_payload_cannot_inject_observations_or_actions(tmp_path):
    repo, _, _, orch, *_ = _start_repo(tmp_path)
    with pytest.raises(ValueError):
        create_plan(AttackPathPlanningAgentService(repo), {"orchestration_id": orch["orchestration_id"], "effects": ["access:root"]})


def test_ui_routes_post_get_origin_and_validation_without_sockets(tmp_path):
    repo, _, _, orch, *_ = _start_repo(tmp_path)
    class Handler(PentestWebMixin):
        service = AttackPathPlanningAgentService(repo)
        path = "/api/pentest/ui/attack-path-planning/run"
        headers = {"Host": "localhost:8790", "Origin": "http://localhost:8790"}
        def _read_json(self):
            return {"orchestration_id": orch["orchestration_id"]}
        def _send_json(self, status, body):
            self.status, self.body = status, body
    h = Handler()
    assert h.handle_pentest_ui_post() and h.status == 201
    assert h.handle_pentest_ui_post() and h.status == 200
    h.headers = {"Host": "localhost:8790", "Origin": "https://untrusted.example"}
    assert h.handle_pentest_ui_post() and h.status == 403
    h.path = "/api/pentest/ui/attack-path-planning/workspace?limit=10"
    with patch("pentest_subsystem.attack_path_workspace.workspace", return_value={"contexts": []}) as projected:
        assert h.handle_pentest_ui_get() and h.status == 200
        projected.assert_called_once_with(h.service, limit=10)
    h.path += "&limit=20"
    assert h.handle_pentest_ui_get() and h.status == 400
    assert ASSETS["/pentest/attack-path-planning/"][0] == "planning.html"


def test_workspace_keeps_contexts_and_revisions_isolated(tmp_path):
    from pentest_subsystem.attack_path_workspace import workspace
    repo, _, _, orch, *_ = _start_repo(tmp_path)
    service = AttackPathPlanningAgentService(repo)
    create_plan(service, {"orchestration_id": orch["orchestration_id"]})
    contexts = [{"context_id": "enum-a", "orchestration_id": orch["orchestration_id"],
                 "correlation": {"status": "COMPLETED"}, "hypothesis_run": {"id": "a"}, "hypotheses": [1]},
                {"context_id": "enum-b", "orchestration_id": "paorch-missing", "correlation": {"status": "AWAITING_CTI"}}]
    with patch("pentest_subsystem.vulnerability_hypothesis_workspace.workspace", return_value={"contexts": contexts}):
        result = workspace(service)
    assert len(result["contexts"][0]["revisions"]) == 1
    assert result["contexts"][1]["revisions"] == []
    assert not result["contexts"][1]["can_plan"]
