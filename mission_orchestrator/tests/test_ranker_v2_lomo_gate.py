"""Stage 5.5 ranker v2 (#8): the LOMO-NDCG promotion gate is meaningful for the chain
feature. When relevance is driven by chain_mapping_strength (which the fixed 0.8/0.2
formula ignores), a learned v2 ranker beats the baseline and is promotable; a
single-grade / too-small / single-mission dataset is NOT promotable.

MACHINERY ONLY — no real model is promoted here (0 live ATTACK_PATH labels). Promotion on
real data stays a TODO until >=20 chain-bearing paths from >=2 missions are collected.
"""
from __future__ import annotations

from pentest_subsystem import attack_path_ranking as apr
from pentest_subsystem import learning_dataset as ld


def _record(mission, idx, *, conf, impact, refs, chain, grade):
    core = {
        "schema_version": ld.DATASET_SCHEMA_VERSION,
        "entity_kind": ld.KIND_ATTACK_PATH,
        "entity_id": f"p-{mission}-{idx}",
        "mission_id": mission,
        "orchestration_id": f"paorch-{mission}",
        "features": {"hypothesis_conf_max": conf, "impact_factor": impact,
                     "evidence_ref_count": float(refs), "chain_mapping_strength": chain,
                     "hypothesis_count": 1.0},
        "descriptors": {},
        "label": 1 if grade == 2 else (0 if grade == 0 else None),
        "relevance_grade": grade,
        "label_outcome": "CONFIRMED" if grade == 2 else ("REFUTED" if grade == 0 else "PARTIALLY_CONFIRMED"),
        "provenance": {"label_source": ld.LABEL_SOURCE},
    }
    return ld._seal({**core, "record_id": "plds-" + f"{mission}-{idx}"})


def _chain_driven_records(missions=("m-a", "m-b", "m-c"), per=10):
    """Grade is a step function of chain_mapping_strength; confidence/impact are constant,
    so the fixed 0.8/0.2 formula cannot separate the grades but a chain-aware ranker can."""
    records = []
    for m in missions:
        for i in range(per):
            chain = round((i % 5) / 4.0, 6)  # 0.0 .. 1.0
            grade = 2 if chain >= 0.75 else (1 if chain >= 0.5 else 0)
            records.append(_record(m, i, conf=0.6, impact=0.5, refs=2, chain=chain, grade=grade))
    return records


def test_chain_signal_makes_ranker_promotable():
    records = _chain_driven_records()
    result = apr.evaluate_ranking(records)
    ev = result["evaluation"]
    assert apr.verify_evaluation(ev)
    assert ev["promotable"] is True
    assert ev["not_promotable_reasons"] == []
    assert result["model"] is not None and result["model"]["status"] == "TRAINED"
    # The promoted model gives chain_mapping_strength a non-trivial weight.
    assert abs(result["model"]["weights"]["chain_mapping_strength"]) > 0.0
    # held-out NDCG must be >= the fixed-formula baseline (gate honored, not relaxed).
    assert ev["lomo"]["ndcg_at_k"] >= ev["fixed_formula_baseline"]["ndcg_at_k"] - apr.MAX_NDCG_REGRESSION


def test_single_grade_is_not_promotable():
    records = [_record("m-a", i, conf=0.6, impact=0.5, refs=2, chain=0.3, grade=2) for i in range(12)] + \
              [_record("m-b", i, conf=0.6, impact=0.5, refs=2, chain=0.3, grade=2) for i in range(12)]
    ev = apr.evaluate_ranking(records)["evaluation"]
    assert ev["promotable"] is False
    assert "single_grade" in ev["not_promotable_reasons"]


def test_single_mission_is_not_promotable():
    records = _chain_driven_records(missions=("m-only",), per=24)
    ev = apr.evaluate_ranking(records)["evaluation"]
    assert ev["promotable"] is False
    assert any("insufficient_missions" in r for r in ev["not_promotable_reasons"])


def test_build_promoted_model_returns_none_when_not_promotable():
    records = [_record("m-a", i, conf=0.6, impact=0.5, refs=2, chain=0.3, grade=2) for i in range(24)]
    assert apr.build_promoted_model(records) is None
