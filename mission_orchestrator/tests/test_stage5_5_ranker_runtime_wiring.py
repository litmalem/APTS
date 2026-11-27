"""Fase 2 (Stage 5.5) — runtime wiring of the attack-path learning-to-rank ranker.

Covers the ADDITIVE collect -> promote -> persist -> load -> inject path (sidecar store + bootstrap),
WITHOUT touching the ranker/graph/dataset algorithms. The six cases mirror the design doc §4:
fail-safe regression, trained path, tampered store, gate-rejection CLI exit code, determinism, and
"startup never fails on ranker wiring". Dataset/fit fixtures are reused from the ranking suite.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pentest_subsystem import attack_path_ranking as apr
from pentest_subsystem import train_attack_path_ranker as cli
from pentest_subsystem.attack_path_planning import (
    AttackPathPlanningAgentRepository,
    AttackPathPlanningAgentService,
    verify_attack_path_planning_output,
)
from pentest_subsystem.attack_path_ranker_store import AttackPathRankerStore, AttackPathRankerStoreError
from pentest_subsystem.attack_path_ranker_training import train_promoted_ranker
from pentest_subsystem.boundary_contract import sha256_hex

from tests.test_stage5_5_attack_path_ranking import _dataset
from tests.test_stage5_5_attack_path_planning_agent import _start_repo, attack_path_request


# ---- helpers ----------------------------------------------------------------------------------

def _planning_output(tmp_path: Path, suffix: str, *, install_model=None):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, suffix)
    if install_model is not None:
        AttackPathRankerStore(repo.sqlite_path).save(install_model[0], install_model[1])
        assert repo.reload_attack_path_ranker_model() is True
    run, created = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, suffix))
    assert created is True
    return repo, run["output"]


def _promotable_model():
    result = apr.evaluate_ranking(_dataset())
    assert result["model"] is not None and result["evaluation"]["promotable"] is True
    return result["model"], result["evaluation"]


# ---- §4.1 regression fail-safe ----------------------------------------------------------------

def test_01_no_store_keeps_fixed_formula_byte_identical(tmp_path: Path):
    _, output_a = _planning_output(tmp_path / "a", "nostore55")
    score = output_a["candidate_paths"][0]["planning_score"]
    assert score["formula"] == apr.SYMBOLIC_FORMULA
    assert "model" not in score
    assert verify_attack_path_planning_output(output_a) is True
    # The fixed-formula planning_score is byte-identical across independent default builds (per-path ids differ,
    # but the score block the wiring would otherwise replace does not) — the pre-wiring behavior is preserved.
    _, output_b = _planning_output(tmp_path / "b", "nostore55")
    scores_a = [p["planning_score"] for p in output_a["candidate_paths"]]
    scores_b = [p["planning_score"] for p in output_b["candidate_paths"]]
    assert sha256_hex(scores_a) == sha256_hex(scores_b)
    assert all(s["formula"] == apr.SYMBOLIC_FORMULA and "model" not in s for s in scores_a)


# ---- §4.2 trained path ------------------------------------------------------------------------

def test_02_promoted_model_activates_learned_formula(tmp_path: Path):
    model, evaluation = _promotable_model()
    _, output = _planning_output(tmp_path, "trained55", install_model=(model, evaluation))
    score = output["candidate_paths"][0]["planning_score"]
    assert score["formula"] == apr.LEARNED_FORMULA
    assert "chain_mapping_strength" in score["model"]["features"]
    assert score["model"]["model_sha256"] == model["weights_sha256"]
    assert verify_attack_path_planning_output(output) is True


# ---- §4.3 tampered / corrupt store ------------------------------------------------------------

def test_03_tampered_store_falls_back_to_fixed_formula(tmp_path: Path):
    model, evaluation = _promotable_model()
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "tamper55")
    store = AttackPathRankerStore(repo.sqlite_path)
    store.save(model, evaluation)
    # Corrupt the seal: load() must return None and reload must not raise.
    envelope = json.loads(store.path.read_text(encoding="utf-8"))
    envelope["envelope_sha256"] = "0" * 64
    store.path.write_text(json.dumps(envelope), encoding="utf-8")
    assert store.load() is None
    assert repo.reload_attack_path_ranker_model() is False
    run, created = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "tamper55"))
    assert created is True
    score = run["output"]["candidate_paths"][0]["planning_score"]
    assert score["formula"] == apr.SYMBOLIC_FORMULA


# ---- §4.4 gate rejection via CLI --------------------------------------------------------------

def test_04_cli_install_on_non_promotable_exits_2_without_touching_store(tmp_path: Path):
    # A fresh repo has no verified Stage 6 runs -> collect yields 0 records -> gate rejects -> model None.
    repo_db = tmp_path / "pentest.db"
    rc = cli.main(["--repo", str(repo_db), "--install"])
    assert rc == 2
    assert AttackPathRankerStore(repo_db).load() is None


def test_04b_store_save_rejects_non_promotable_evaluation(tmp_path: Path):
    model, evaluation = _promotable_model()
    forged = dict(evaluation)
    forged["promotable"] = False  # breaks verify_evaluation too -> must be refused
    with pytest.raises(AttackPathRankerStoreError):
        AttackPathRankerStore(tmp_path / "pentest.db").save(model, forged)


# ---- §4.5 determinism -------------------------------------------------------------------------

def test_05_training_is_deterministic(tmp_path: Path):
    first = train_promoted_ranker(_dataset())["model"]
    second = train_promoted_ranker(_dataset())["model"]
    assert first is not None and second is not None
    assert first["weights_sha256"] == second["weights_sha256"]


# ---- §4.6 bootstrap never fails ---------------------------------------------------------------

def test_06_reload_never_fails_startup(monkeypatch, tmp_path: Path):
    from pentest_subsystem import attack_path_ranker_store as store_mod

    def _boom(self):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(store_mod.AttackPathRankerStore, "load", _boom)
    service = AttackPathPlanningAgentService(AttackPathPlanningAgentRepository(tmp_path / "pentest.db"))
    assert service.reload_attack_path_ranker_model() is False
    assert service.repository.attack_path_ranker_model is None
