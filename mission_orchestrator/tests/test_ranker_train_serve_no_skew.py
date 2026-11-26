"""Stage 5.5 ranker v2 (#9): record_features (train) == candidate_path_features (serve)
for the same path, including chain_mapping_strength — no train/serve skew.
"""
from __future__ import annotations

from pentest_subsystem import attack_path_ranking as apr
from pentest_subsystem.cti_attack_chain import chain_mapping_strength, normalize_attack_chain


def _chain(level):
    links = [
        {"from_type": "CVE", "from_id": "CVE-9-9", "to_type": "CWE", "to_id": "CWE-79",
         "mapping_level": "authoritative", "source_ref": "vulndesk://cve-cwes"},
        {"from_type": "CWE", "from_id": "CWE-79", "to_type": "CAPEC", "to_id": "CAPEC-63",
         "mapping_level": "related", "source_ref": "vulndesk://capec"},
        {"from_type": "CAPEC", "from_id": "CAPEC-63", "to_type": "ATTACK", "to_id": "T1190",
         "tactic": "Initial Access", "mapping_level": level, "source_ref": "vulndesk://attack"},
    ]
    return normalize_attack_chain({"snapshot": {"graph_snapshot_id": "ctigs-skew"}, "links": links}, entry="CWE")


def test_no_train_serve_skew():
    chain = _chain("related")
    strength = chain_mapping_strength(chain)
    conf, impact, refs = 0.72, 0.5, 3

    # Serve path: features read from the sealed chain + planning_score + evidence refs.
    path = {
        "planning_score": {"hypothesis_confidence": conf, "impact_factor": impact},
        "provenance": {"supporting_evidence_refs": ["e"] * refs, "knowledge": {"attack_chain": chain}},
    }
    serve = apr.candidate_path_features(path)

    # Train record: the Fase 0 features block carries the SAME scalar chain_mapping_strength.
    features_block = {
        "hypothesis_conf_max": conf, "impact_factor": impact, "evidence_ref_count": float(refs),
        "chain_mapping_strength": strength,
    }
    train = apr.record_features(features_block)

    assert serve == train
    assert serve["chain_mapping_strength"] == train["chain_mapping_strength"] == round(strength, 6)
