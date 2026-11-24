from __future__ import annotations

from copy import deepcopy
import sqlite3

import pytest

from pentest_subsystem.attack_path_workspace import ensure_plan
from pentest_subsystem.cross_agent_feedback import CrossAgentFeedbackService
from pentest_subsystem.hypothesis_scoring import (
    FEATURES,
    HypothesisScoringError,
    MIN_TRAIN_SAMPLES,
    best_matches,
    extract_features,
    fit,
    predict,
    prior_model,
    score_hypotheses,
    similarity,
    verify_model,
    verify_scoring,
)
from pentest_subsystem.orchestration.runtime_autonomy import AutonomyRuntime
from pentest_subsystem.plan_explanation import explain_plan, verify_explanation
from pentest_subsystem.symbolic_planner import plan
from tests.test_phase2_runtime_autonomy import _get, _post, _server
from tests.test_stage5_8_cross_agent_feedback_shared_state_replanning import _pipeline


# ---- P3: similarity ---------------------------------------------------------------------------

def test_similarity_handles_ambiguous_product_names_deterministically():
    close = similarity("Apache HTTP Server", "apache http_server")
    far = similarity("Apache HTTP Server", "Angular framework")
    assert close > 0.8 > far and similarity("nginx", "nginx") == pytest.approx(1.0, abs=1e-6)
    assert similarity("", "x") == 0.0
    assert similarity("Apache HTTP Server", "apache http_server") == close  # replayable


def test_best_matches_ranks_catalog_with_stable_ties():
    out = best_matches("apache httpd", ["Apache HTTP Server", "nginx", "Apache Tomcat", "Microsoft IIS"], top=2)
    assert out[0]["name"] == "Apache HTTP Server" and len(out) == 2
    assert best_matches("zzz", ["b", "a"], top=2) == best_matches("zzz", ["b", "a"], top=2)


# ---- P3: model --------------------------------------------------------------------------------

def _hyp(i, dims=("technology",), knowledge=0.65, evidence=0.5, year=2025):
    return {"hypothesis_id": f"hypmodel-{i:03d}", "asset_id": "enumasset-1", "vulnerability_id": f"CVE-{year}-{1000 + i}",
            "correlation": {"matched_dimensions": list(dims)},
            "confidence": {"knowledge": knowledge, "evidence": evidence, "overall": min(knowledge, evidence)},
            "knowledge": {"title": "Angular XSS", "summary": "Angular stored cross-site scripting"},
            "statement": "asset runs Angular", "integrity": {"canonical_sha256": f"{i:064x}"}}


def test_prior_model_is_honestly_labelled_hash_bound_and_tamper_evident():
    m = prior_model()
    assert m["status"] == "PRIOR_UNTRAINED" and verify_model(m)
    t = deepcopy(m); t["weights"]["version_dim"] = 9.0
    assert not verify_model(t)
    with pytest.raises(HypothesisScoringError):
        predict(t, {f: 0.0 for f in FEATURES})


def test_more_evidence_scores_higher_and_probabilities_are_bounded():
    m = prior_model()
    weak = predict(m, extract_features(_hyp(1)))
    strong = predict(m, extract_features(_hyp(2, dims=("technology", "version", "cpe"), knowledge=0.9, evidence=0.9)))
    assert 0 < weak < strong < 1


def test_fit_refuses_small_or_single_class_data():
    ok = {"features": extract_features(_hyp(1)), "label": 1}
    with pytest.raises(HypothesisScoringError, match="at least"):
        fit([ok] * (MIN_TRAIN_SAMPLES - 1))
    with pytest.raises(HypothesisScoringError, match="single class"):
        fit([ok] * MIN_TRAIN_SAMPLES)
    with pytest.raises(HypothesisScoringError):
        fit([{"features": ok["features"], "label": 2}] * MIN_TRAIN_SAMPLES)


def _samples():
    out = []
    for i in range(40):
        strong = i % 2 == 0
        h = _hyp(i, dims=("technology", "version") if strong else ("technology",),
                 evidence=0.9 if strong else 0.3)
        out.append({"features": extract_features(h), "label": 1 if strong else 0})
    return out


def test_fit_is_deterministic_learns_direction_and_is_labelled_trained():
    a, b = fit(_samples()), fit(_samples())
    assert a == b and a["status"] == "TRAINED" and verify_model(a) and a["training"]["samples"] == 40
    assert a["weights_sha256"] != prior_model()["weights_sha256"]
    p_strong = predict(a, extract_features(_hyp(100, dims=("technology", "version"), evidence=0.9)))
    p_weak = predict(a, extract_features(_hyp(101, evidence=0.3)))
    assert p_strong > 0.8 > 0.2 > p_weak or p_strong > p_weak


def test_scoring_is_advisory_never_modifies_hypotheses_and_labels_prior_honestly():
    hyps = [_hyp(1), _hyp(2, dims=("technology", "version"), evidence=0.9)]
    before = deepcopy(hyps)
    rec = score_hypotheses(hyps, assets={"enumasset-1": {"technologies": [{"technology": "Angular"}]}})
    assert hyps == before and verify_scoring(rec)
    assert rec["label_justification"] == "NEURO_SYMBOLIC_NOT_JUSTIFIED_PRIOR_MODEL"
    assert rec["semantics"]["symbolic_gate_unchanged"] is True and rec["semantics"]["score_is_exploit_probability"] is False
    assert [r["advisory_rank"] for r in rec["scores"]] == [1, 2] and rec["scores"][0]["hypothesis_id"] == "hypmodel-002"
    assert rec == score_hypotheses(hyps, assets={"enumasset-1": {"technologies": [{"technology": "Angular"}]}})
    trained = score_hypotheses(hyps, model=fit(_samples()))
    assert trained["label_justification"] == "STATISTICAL_LAYER_TRAINED_ON_VALIDATION_OUTCOMES"


# ---- P4: explanation --------------------------------------------------------------------------

def _action(aid, pre, eff, *, cost=1.0, impact=1, conf=0.8, belief="UNKNOWN"):
    return {"action_id": aid, "hypothesis_id": aid, "label": aid, "target": {}, "preconditions": pre, "effects": eff,
            "cost": cost, "impact": impact, "confidence": conf, "evidence_refs": ["evi-1"], "hypothesis_sha256": "a" * 64,
            "validation": {}, "model_basis": "CTI_SYMBOLIC_CONTRACT", "belief": belief, "feedback_refs": []}


def _problem(actions, goals):
    return {"objective": {}, "goal_predicates": goals, "goal_basis": "MISSION_PREDICATES",
            "initial_facts": ["observed:x"], "actions": actions, "hypothesis_context": {}, "feedback": []}


def test_causal_chain_is_explained_with_precondition_provenance_and_cost_breakdown():
    actions = [_action("foothold", ["observed:x"], ["access:user"], cost=1.0),
               _action("escalate", ["access:user"], ["access:root"], cost=2.0),
               _action("shortcut", ["observed:x"], ["access:root"], cost=9.0)]
    result = plan(_problem(actions, ["access:root"]))
    exp = explain_plan(result)
    assert verify_explanation(exp) and exp["diagnosis"]["structure"] == "MULTI_STEP_CAUSAL_PLAN"
    best = exp["paths"][0]
    assert [c["action_id"] for c in best["chain"]] == ["foothold", "escalate"]
    assert best["chain"][0]["needs"][0]["satisfied_by"] == "INITIAL_FACT"
    assert best["chain"][1]["needs"][0]["satisfied_by"] == "foothold"
    assert best["chain"][1]["cost"]["step_total"] == pytest.approx(2.0 + 0.25 * 1 + 0.2)
    assert "lowest total cost" in best["selection_reasons"][0]
    assert any(r["cost_delta_vs_this"] > 0 for r in exp["paths"][0]["rejected_alternatives"]) or len(exp["paths"]) == 1
    assert exp["semantics"]["executes"] is False and exp["semantics"]["new_facts_created"] is False


def test_validation_only_plan_is_diagnosed_as_prioritisation_not_attack_chain():
    actions = [_action(f"validate:h{i}", ["observed:x"], [f"validated:h{i}"], cost=1.0, conf=0.5 + i / 10) for i in range(3)]
    for a in actions:
        a["model_basis"] = "VALIDATION_ONLY"
    p = _problem(actions, [f"validated:h{i}" for i in range(3)])
    p["goal_basis"] = "HYPOTHESIS_VALIDATION_COVERAGE"
    exp = explain_plan(plan(p))
    assert exp["diagnosis"]["structure"] == "VALIDATION_PRIORITISATION_ONLY"
    assert "not an attack chain" in exp["diagnosis"]["note"]
    assert exp["paths"][0]["validates"] == "validated:h2"  # highest confidence = cheapest


def test_held_actions_and_tamper_are_reported():
    actions = [_action("a", ["observed:x"], ["g"]), _action("b", ["observed:x"], ["g"], belief="CONFLICTING")]
    exp = explain_plan(plan(_problem(actions, ["g"])))
    assert [h["action_id"] for h in exp["blocked_or_held_actions"]] == ["b"]
    t = deepcopy(exp); t["paths"][0]["rank"] = 7
    assert not verify_explanation(t)


# ---- runtime wiring ---------------------------------------------------------------------------

def test_runtime_scores_persist_idempotently_and_explain_real_plan(tmp_path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "p3rt")
    service = CrossAgentFeedbackService(repo)
    ensure_plan(service, oid)
    rt = AutonomyRuntime(service)
    first = rt.score_hypotheses(oid)
    assert first["created"] and first["scoring"]["model"]["status"] == "PRIOR_UNTRAINED"
    assert rt.score_hypotheses(oid)["created"] is False
    assert rt.latest_scoring(oid)["record_sha256"] == first["scoring"]["record_sha256"]
    ex = rt.explain_plan(oid)
    assert ex["revision"] >= 1 and verify_explanation(ex["explanation"])
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM pentest_hypothesis_score_records").fetchone()[0] == 1
        for sql in ("UPDATE pentest_hypothesis_score_records SET model_status='TRAINED'",
                    "DELETE FROM pentest_hypothesis_score_records"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)


def test_http_routes_for_scoring_and_explanation(tmp_path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "p3http")
    ensure_plan(CrossAgentFeedbackService(repo), oid)
    server, base = _server(repo)
    try:
        root = base + "/api/pentest/agentic-orchestrations/" + oid + "/autonomy"
        assert _get(root + "/hypothesis-scores")[0] == 404  # nothing computed yet
        status, body = _post(root + "/hypothesis-scores", {})
        assert status == 200 and body["created"] is True and body["execution_started"] is False
        status, _, body = _get(root + "/hypothesis-scores")
        assert status == 200 and body["scoring"]["semantics"]["hypotheses_modified"] is False
        status, _, body = _get(root + "/plan-explanation")
        assert status == 200 and body["explanation"]["semantics"]["executes"] is False
        assert _post(root + "/hypothesis-scores", {"model": "evil"})[0] == 400  # model is server-owned
    finally:
        server.shutdown()
