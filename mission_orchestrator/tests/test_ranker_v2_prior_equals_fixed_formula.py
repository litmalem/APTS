"""Stage 5.5 ranker v2 (#6, #10): the untrained prior reproduces 0.8*conf + 0.2*impact
byte-identically (chain weight 0), and without a usable model the planning score ignores
the chain entirely — so an un-promoted system is identical to the pre-learning planner.
"""
from __future__ import annotations

import pytest

from pentest_subsystem import attack_path_ranking as apr


def test_prior_feature_space_is_v2_but_score_is_fixed_formula():
    prior = apr.prior_model()
    assert list(prior["features"]) == list(apr.RANKER_FEATURES_V2)
    assert "chain_mapping_strength" in prior["weights"]
    assert prior["weights"]["chain_mapping_strength"] == 0.0
    # PRIOR_UNTRAINED is never usable at serve (only TRAINED + verified + gated promotes).
    assert apr.model_is_usable(prior) is False
    assert apr.verify_model(prior) is True


@pytest.mark.parametrize("conf,impact,chain", [(0.9, 1.0, 0.0), (0.3, 0.25, 1.0), (0.75, 0.5, 0.66)])
def test_prior_score_equals_0_8_0_2_regardless_of_chain(conf, impact, chain):
    prior = apr.prior_model()
    feats = apr.ranking_features(hypothesis_confidence=conf, impact_factor=impact,
                                 evidence_ref_count=4, chain_mapping_strength=chain)
    assert apr.score(prior, feats) == round(0.8 * conf + 0.2 * impact, 6)


def test_planning_score_block_without_model_ignores_chain():
    kwargs = dict(hypothesis_confidence=0.9, estimated_impact="LOW", impact_factor=1.0,
                  evidence_ref_count=2, symbolic_score=0.98)
    no_chain = apr.planning_score_block(model=None, chain_mapping_strength=0.0, **kwargs)
    high_chain = apr.planning_score_block(model=None, chain_mapping_strength=1.0, **kwargs)
    # Fail-safe: the chain feature cannot change the score without a usable model.
    assert no_chain == high_chain
    assert no_chain["formula"] == apr.SYMBOLIC_FORMULA
    assert "model" not in no_chain
    assert no_chain["score"] == 0.98


def test_v1_model_is_not_usable_under_v2():
    # A legacy 3-feature model must fall back to the fixed formula (never silently reused).
    legacy = {"model_version": "apr-lin-old", "status": "TRAINED",
              "features": list(apr.RANKER_FEATURES_V1), "bias": 0.0,
              "weights": {f: 0.0 for f in apr.RANKER_FEATURES_V1},
              "training": {"samples": 20, "groups": 2, "epochs": 1, "l2": 0.0, "learning_rate": 0.1}}
    assert apr.model_is_usable(legacy) is False
    block = apr.planning_score_block(hypothesis_confidence=0.5, estimated_impact="LOW", impact_factor=1.0,
                                     evidence_ref_count=1, model=legacy, symbolic_score=0.6,
                                     chain_mapping_strength=1.0)
    assert block["formula"] == apr.SYMBOLIC_FORMULA
