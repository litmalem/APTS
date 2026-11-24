"""Fase 1 (Rancangan Learning Sejati, section 4.1) - Stage 5.4 confidence calibration.

Covers the OVVI integration: a version-pinned, offline-trained, deterministic calibrator replaces the fixed
`min(knowledge, evidence)` aggregation ONLY when a TRAINED + verified model is promoted; otherwise the symbolic
MIN path is byte-identical to the pre-learning system. Also covers the calibration metrics and the leave-one-
mission-out (LOMO) promotion gate, and that the learned path never changes governance/finding semantics.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from pentest_subsystem import hypothesis_scoring as hs
from pentest_subsystem import learning_dataset as ld
from pentest_subsystem import vulnerability_hypothesis_calibration as cal
from pentest_subsystem.boundary_contract import sha256_hex
from pentest_subsystem.vulnerability_hypothesis import (
    verify_vulnerability_hypothesis_model,
    verify_vulnerability_hypothesis_output,
    VulnerabilityHypothesisAgentValidationError,
)

from tests.test_stage5_4_vulnerability_hypothesis_agent import _start_repo, hypothesis_request


# ---- helpers ----------------------------------------------------------------------------------

def _features(evidence_conf: float, knowledge_conf: float = 0.8, dims: float = 2.0, version: float = 1.0) -> dict:
    return {"dims_count": dims, "version_dim": version, "cpe_dim": 0.0, "knowledge_conf": knowledge_conf,
            "evidence_conf": evidence_conf, "name_similarity": 0.4, "cve_age_norm": 0.2}


def _trained_model():
    """A deterministic TRAINED calibrator: label follows evidence_conf, two classes, >= MIN_TRAIN_SAMPLES."""
    samples = []
    for i in range(40):
        ev = 0.9 if i % 2 == 0 else 0.1
        samples.append({"features": _features(ev), "label": 1 if ev >= 0.6 else 0})
    model = hs.fit(samples)
    assert model["status"] == "TRAINED" and hs.verify_model(model)
    return model


def _label_record(entity_id: str, mission: str, label: int, evidence_conf: float, symbolic: float) -> dict:
    core = {
        "schema_version": ld.DATASET_SCHEMA_VERSION, "entity_kind": ld.KIND_HYPOTHESIS, "entity_id": entity_id,
        "mission_id": mission, "orchestration_id": "paorch-" + mission, "features": _features(evidence_conf),
        "descriptors": {"symbolic_confidence": symbolic}, "label": label,
        "relevance_grade": 2 if label == 1 else 0, "label_outcome": "CONFIRMED" if label == 1 else "REFUTED",
        "provenance": {"label_source": ld.LABEL_SOURCE},
    }
    sha = sha256_hex({"hash_domain": ld.DATASET_HASH_DOMAIN, "record": core})
    rec = {**core, "record_sha256": sha}
    assert ld.verify_record(rec)
    return rec


def _multi_mission_dataset() -> list[dict]:
    """Two missions, both classes in each, symbolic baseline deliberately miscalibrated (constant 0.5)."""
    records = []
    for mission in ("m-alpha", "m-beta"):
        for i in range(20):
            ev = 0.9 if i % 2 == 0 else 0.1
            label = 1 if ev >= 0.6 else 0
            records.append(_label_record(f"hyp-{mission}-{i}", mission, label, ev, symbolic=0.5))
    return records


# ---- aggregation fail-safe and calibrated path ------------------------------------------------

def test_aggregate_without_model_is_symbolic_min():
    overall, aggregation, block = cal.aggregate_confidence(
        knowledge={"confidence": 0.8, "title": "t", "summary": "s"},
        asset={"technologies": [], "versions": []},
        match={"evidence_confidence": 0.41, "matched_dimensions": ["product", "version"]},
        statement="x", symbolic_overall=0.41, model=None)
    assert overall == 0.41
    assert aggregation == cal.SYMBOLIC_AGGREGATION
    assert block is None


def test_prior_and_tampered_models_fall_back_to_symbolic():
    prior = hs.prior_model()
    assert not cal.model_is_usable(prior)  # PRIOR_UNTRAINED must never replace MIN
    overall, aggregation, block = cal.aggregate_confidence(
        knowledge={"confidence": 0.8, "title": "t", "summary": "s"},
        asset={"technologies": [], "versions": []},
        match={"evidence_confidence": 0.5, "matched_dimensions": ["product"]},
        statement="x", symbolic_overall=0.5, model=prior)
    assert aggregation == cal.SYMBOLIC_AGGREGATION and block is None

    tampered = deepcopy(_trained_model())
    tampered["bias"] = tampered["bias"] + 1.0  # breaks weights_sha256
    assert not cal.model_is_usable(tampered)


def test_calibrated_path_embeds_pinned_model_and_is_deterministic():
    model = _trained_model()
    args = dict(
        knowledge={"confidence": 0.8, "title": "Apache", "summary": "synthetic", "vulnerability_id": "CVE-2021-0001"},
        asset={"technologies": [{"technology": "Apache HTTP Server"}], "versions": [{"product": "Apache HTTP Server"}]},
        match={"evidence_confidence": 0.9, "matched_dimensions": ["product", "version"]},
        statement="Apache may apply", symbolic_overall=0.8, model=model)
    overall, aggregation, block = cal.aggregate_confidence(**args)
    assert 0.0 <= overall <= 1.0
    assert aggregation == cal.CALIBRATED_AGGREGATION
    assert block["model_sha256"] == model["weights_sha256"]
    assert block["model_id"] == model["model_version"]
    assert block["status"] == "TRAINED"
    assert block["feature_order"] == list(hs.FEATURES)
    assert block["symbolic_fallback_overall"] == 0.8
    # deterministic: same input -> same output
    assert cal.aggregate_confidence(**args) == (overall, aggregation, block)


# ---- metrics ----------------------------------------------------------------------------------

def test_brier_ece_precision_basic():
    perfect = [(1.0, 1), (0.0, 0), (1.0, 1), (0.0, 0)]
    assert cal.brier_score(perfect) == 0.0
    assert cal.expected_calibration_error(perfect) == 0.0
    assert cal.precision_at_k(perfect, 2) == 1.0
    worst = [(0.0, 1), (1.0, 0)]
    assert cal.brier_score(worst) == 1.0
    with pytest.raises(cal.CalibrationError):
        cal.brier_score([])


# ---- LOMO promotion gate ----------------------------------------------------------------------

def test_single_mission_is_not_promotable():
    records = [r for r in _multi_mission_dataset() if r["mission_id"] == "m-alpha"]
    result = cal.evaluate_calibration(records)
    assert result["evaluation"]["promotable"] is False
    assert result["model"] is None
    assert any("mission" in reason for reason in result["evaluation"]["not_promotable_reasons"])
    assert cal.verify_evaluation(result["evaluation"])


def test_multi_mission_well_separated_is_promotable():
    records = _multi_mission_dataset()
    result = cal.evaluate_calibration(records)
    ev = result["evaluation"]
    assert cal.verify_evaluation(ev)
    assert ev["mission_count"] == 2
    assert ev["promotable"] is True
    assert ev["lomo"]["brier"] <= ev["symbolic_baseline"]["brier"]
    model = cal.build_promoted_model(records)
    assert model is not None and cal.model_is_usable(model)


def test_tampered_label_record_is_rejected():
    rec = _label_record("hyp-x", "m-alpha", 1, 0.9, 0.5)
    rec["label"] = 0  # breaks record_sha256
    with pytest.raises(cal.CalibrationError):
        cal.training_samples([rec])


# ---- end-to-end integration through the agent -------------------------------------------------

def test_default_run_keeps_symbolic_aggregation(tmp_path: Path):
    repo, boundary, _, orch, _, enum, _, _ = _start_repo(tmp_path, "caldefault")
    run, created = repo.run_vulnerability_hypothesis(orch["orchestration_id"], hypothesis_request(boundary, enum, "caldefault"))
    assert created is True
    conf = run["output"]["vulnerability_hypotheses"][0]["confidence"]
    assert conf["aggregation"] == cal.SYMBOLIC_AGGREGATION
    assert conf["overall"] == min(conf["knowledge"], conf["evidence"])
    assert "model" not in conf


def test_promoted_model_run_uses_calibrated_aggregation_and_preserves_semantics(tmp_path: Path):
    repo, boundary, _, orch, _, enum, _, _ = _start_repo(tmp_path, "calrun")
    model = _trained_model()
    repo.set_calibration_model(model)
    run, created = repo.run_vulnerability_hypothesis(orch["orchestration_id"], hypothesis_request(boundary, enum, "calrun"))
    assert created is True
    output = run["output"]
    # persistence read already re-verified integrity; assert again explicitly
    assert verify_vulnerability_hypothesis_output(output)
    hyp = output["vulnerability_hypotheses"][0]
    conf = hyp["confidence"]
    assert conf["aggregation"] == cal.CALIBRATED_AGGREGATION
    assert conf["model"]["model_sha256"] == model["weights_sha256"]
    assert 0.0 <= conf["overall"] <= 1.0
    # the raw symbolic inputs remain auditable alongside the learned output
    assert "knowledge" in conf and "evidence" in conf
    # governance / projection-only invariants are untouched
    assert hyp["semantics"]["confirmed_finding"] is False
    assert output["semantics"]["authorization_minted"] is False
    assert output["semantics"]["external_network_io_performed"] is False
    model_only = {k: v for k, v in hyp.items() if k != "lineage"}
    assert verify_vulnerability_hypothesis_model(model_only)


def test_set_calibration_model_rejects_untrained_and_tampered(tmp_path: Path):
    repo, _, _, _, _, _, _, _ = _start_repo(tmp_path, "calreject")
    with pytest.raises(VulnerabilityHypothesisAgentValidationError):
        repo.set_calibration_model(hs.prior_model())
    tampered = deepcopy(_trained_model())
    tampered["weights"]["evidence_conf"] += 0.5
    with pytest.raises(VulnerabilityHypothesisAgentValidationError):
        repo.set_calibration_model(tampered)
    repo.set_calibration_model(None)  # clearing is always allowed
    assert repo.calibration_model is None
