"""Fase 2 (Rancangan Learning Sejati, section 4.2) - Stage 5.5 attack-path learning-to-rank.

Covers the OVVI integration: a version-pinned, offline-trained linear ranker replaces the fixed
`0.8*confidence + 0.2*impact_factor` validation-priority score ONLY when a TRAINED + verified model passes the
leave-one-mission-out NDCG gate; otherwise the fixed-formula path is byte-identical to the pre-learning planner.
Also covers NDCG/MAP metrics and that the learned path keeps ranking a validation-priority heuristic (no actuation).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from pentest_subsystem import attack_path_ranking as apr
from pentest_subsystem import learning_dataset as ld
from pentest_subsystem.attack_path_planning import (
    AttackPathPlanningAgentValidationError,
    ATTACK_PATH_RANKING_POLICY,
    verify_attack_path_planning_output,
    verify_candidate_attack_path,
    verify_candidate_path_ranking,
)
from pentest_subsystem.boundary_contract import sha256_hex

from tests.test_stage5_4_vulnerability_hypothesis_agent import knowledge_item
from tests.test_stage5_5_attack_path_planning_agent import _start_repo, attack_path_request


# ---- helpers ----------------------------------------------------------------------------------

def _grade_for(refs: int) -> int:
    return 2 if refs >= 4 else (1 if refs >= 2 else 0)


def _fit_samples(missions=("m-a", "m-b", "m-c"), per=10):
    """Grade driven by evidence_ref_count (a feature the fixed 0.8/0.2 formula ignores) -> a learned ranker beats
    the fixed formula, so the model is promotable and demonstrably changes ordering."""
    samples = []
    for m in missions:
        for i in range(per):
            refs = i % 6
            samples.append({
                "features": apr.ranking_features(hypothesis_confidence=0.5, impact_factor=0.75, evidence_ref_count=refs),
                "grade": _grade_for(refs), "mission_id": m,
            })
    return samples


def _trained_ranker():
    model = apr.fit(_fit_samples())
    assert model["status"] == "TRAINED" and apr.verify_model(model)
    return model


def _attack_path_record(entity_id: str, mission: str, confidence: float, impact: float, refs: int, grade: int) -> dict:
    core = {
        "schema_version": ld.DATASET_SCHEMA_VERSION, "entity_kind": ld.KIND_ATTACK_PATH, "entity_id": entity_id,
        "mission_id": mission, "orchestration_id": "paorch-" + mission,
        "features": {"hypothesis_conf_max": confidence, "hypothesis_conf_min": confidence, "impact_factor": impact,
                     "evidence_ref_count": float(refs), "hypothesis_count": 1.0, "target_count": 1.0,
                     "signal_count": 1.0, "model_confidence": 0.0, "cost": 0.0, "length": 4.0},
        "descriptors": {"technique": "T", "validates": True, "hypothesis_ids": [entity_id]},
        "label": 1 if grade == 2 else (0 if grade == 0 else None), "relevance_grade": grade,
        "label_outcome": "CONFIRMED" if grade == 2 else ("REFUTED" if grade == 0 else "PARTIALLY_CONFIRMED"),
        "provenance": {"label_source": ld.LABEL_SOURCE},
    }
    sha = sha256_hex({"hash_domain": ld.DATASET_HASH_DOMAIN, "record": core})
    rec = {**core, "record_sha256": sha}
    assert ld.verify_record(rec)
    return rec


def _dataset(missions=("m-a", "m-b", "m-c"), per=10):
    records = []
    for m in missions:
        for i in range(per):
            refs = i % 6
            records.append(_attack_path_record(f"p-{m}-{i}", m, 0.5, 0.75, refs, _grade_for(refs)))
    return records


# ---- fixed-formula reproduction and fail-safe -------------------------------------------------

def test_prior_ranker_reproduces_fixed_formula():
    prior = apr.prior_model()
    assert not apr.model_is_usable(prior)
    for conf, impact in [(0.9, 1.0), (0.4, 0.5), (0.83, 0.75)]:
        feats = apr.ranking_features(hypothesis_confidence=conf, impact_factor=impact, evidence_ref_count=3)
        assert apr.score(prior, feats) == round(0.8 * conf + 0.2 * impact, 6)


def test_planning_score_block_without_model_is_fixed_formula():
    block = apr.planning_score_block(hypothesis_confidence=0.9, estimated_impact="LOW", impact_factor=1.0,
                                     evidence_ref_count=2, model=None, symbolic_score=round(0.8 * 0.9 + 0.2 * 1.0, 6))
    assert block["formula"] == apr.SYMBOLIC_FORMULA
    assert block["score"] == round(0.8 * 0.9 + 0.2 * 1.0, 6)
    assert "model" not in block
    assert block["meaning"] == apr.PRIORITY_MEANING


def test_prior_and_tampered_models_fall_back_to_fixed_formula():
    block = apr.planning_score_block(hypothesis_confidence=0.9, estimated_impact="LOW", impact_factor=1.0,
                                     evidence_ref_count=2, model=apr.prior_model(), symbolic_score=0.98)
    assert block["formula"] == apr.SYMBOLIC_FORMULA and "model" not in block
    tampered = deepcopy(_trained_ranker())
    tampered["bias"] += 1.0
    assert not apr.model_is_usable(tampered)


def test_learned_block_embeds_pinned_model_and_is_deterministic():
    model = _trained_ranker()
    kwargs = dict(hypothesis_confidence=0.5, estimated_impact="MEDIUM", impact_factor=0.75,
                  evidence_ref_count=5, model=model, symbolic_score=round(0.8 * 0.5 + 0.2 * 0.75, 6))
    block = apr.planning_score_block(**kwargs)
    assert block["formula"] == apr.LEARNED_FORMULA
    assert 0.0 <= block["score"] <= 1.0
    assert block["model"]["model_sha256"] == model["weights_sha256"]
    assert block["model"]["model_id"] == model["model_version"]
    assert block["model"]["feature_order"] == list(apr.RANKER_FEATURES)
    assert block["model"]["symbolic_fallback_score"] == round(0.8 * 0.5 + 0.2 * 0.75, 6)
    assert block["meaning"] == apr.PRIORITY_MEANING  # still a validation-priority heuristic
    assert apr.planning_score_block(**kwargs) == block


# ---- metrics ----------------------------------------------------------------------------------

def test_ndcg_map_basics():
    perfect = [(0.9, 2), (0.8, 1), (0.1, 0)]
    assert apr.ndcg_at_k(perfect, 3) == 1.0
    assert apr.average_precision([(0.9, 1), (0.8, 1), (0.1, 0)]) == 1.0
    worst = [(0.9, 0), (0.1, 2)]
    assert apr.ndcg_at_k(worst, 2) < 1.0
    with pytest.raises(apr.AttackPathRankerError):
        apr.ndcg_at_k([], 3)


# ---- LOMO promotion gate ----------------------------------------------------------------------

def test_single_mission_is_not_promotable():
    records = [r for r in _dataset() if r["mission_id"] == "m-a"]
    result = apr.evaluate_ranking(records)
    assert result["evaluation"]["promotable"] is False
    assert result["model"] is None
    assert any("mission" in reason for reason in result["evaluation"]["not_promotable_reasons"])
    assert apr.verify_evaluation(result["evaluation"])


def test_multi_mission_learned_ranker_is_promotable():
    records = _dataset()
    result = apr.evaluate_ranking(records)
    ev = result["evaluation"]
    assert apr.verify_evaluation(ev)
    assert ev["mission_count"] == 3
    assert ev["promotable"] is True
    assert ev["lomo"]["ndcg_at_k"] >= ev["fixed_formula_baseline"]["ndcg_at_k"]
    model = apr.build_promoted_model(records)
    assert model is not None and apr.model_is_usable(model)


def test_tampered_label_record_is_rejected():
    rec = _attack_path_record("p-x", "m-a", 0.5, 0.75, 5, 2)
    rec["relevance_grade"] = 0
    with pytest.raises(apr.AttackPathRankerError):
        apr.training_samples([rec])


# ---- end-to-end integration through the agent -------------------------------------------------

def test_default_run_keeps_fixed_formula(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "rankdefault")
    run, created = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "rankdefault"))
    assert created is True
    path = run["output"]["candidate_paths"][0]
    assert path["planning_score"]["formula"] == apr.SYMBOLIC_FORMULA
    assert "model" not in path["planning_score"]
    assert verify_candidate_attack_path(path)


def test_promoted_ranker_run_uses_learned_formula_and_preserves_semantics(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "rankrun")
    model = _trained_ranker()
    repo.set_attack_path_ranker_model(model)
    run, created = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "rankrun"))
    assert created is True
    output = run["output"]
    assert verify_attack_path_planning_output(output)
    path = output["candidate_paths"][0]
    ps = path["planning_score"]
    assert ps["formula"] == apr.LEARNED_FORMULA
    assert ps["model"]["model_sha256"] == model["weights_sha256"]
    assert 0.0 <= ps["score"] <= 1.0
    # integrity + projection-only governance invariants intact
    assert verify_candidate_attack_path(path)
    assert path["semantics"]["candidate_only"] is True
    assert path["semantics"]["authorization_minted"] is False
    assert path["semantics"]["path_executed"] is False
    # ranking stays a validation-priority heuristic; policy label unchanged
    ranking = output["candidate_path_ranking"]
    assert ranking["ranking_policy"] == ATTACK_PATH_RANKING_POLICY
    assert ranking["semantics"]["ranking_is_validation_priority_heuristic"] is True
    assert ranking["semantics"]["ranking_is_exploit_success_probability"] is False
    assert verify_candidate_path_ranking(ranking)


def test_set_ranker_model_rejects_untrained_and_tampered(tmp_path: Path):
    repo, _, _, _, _, _, _, _, _ = _start_repo(tmp_path, "rankreject")
    with pytest.raises(AttackPathPlanningAgentValidationError):
        repo.set_attack_path_ranker_model(apr.prior_model())
    tampered = deepcopy(_trained_ranker())
    tampered["weights"]["evidence_ref_count_norm"] += 0.5
    with pytest.raises(AttackPathPlanningAgentValidationError):
        repo.set_attack_path_ranker_model(tampered)
    repo.set_attack_path_ranker_model(None)
    assert repo.attack_path_ranker_model is None
