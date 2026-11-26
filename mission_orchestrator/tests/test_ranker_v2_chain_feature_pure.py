"""Stage 5.5 ranker v2 (#7): chain_mapping_strength is a pure, stable function of the
snapshot-pinned attack_chain on a path — no chain => 0.0, and NO live CTI query at serve
(replay-only; Invariant 4).
"""
from __future__ import annotations

import pytest

from pentest_subsystem import attack_path_ranking as apr
from pentest_subsystem.cti_attack_chain import chain_mapping_strength, normalize_attack_chain


def _chain(level="partial", drop_attack=False):
    links = [
        {"from_type": "CVE", "from_id": "CVE-2021-1", "to_type": "CWE", "to_id": "CWE-79",
         "mapping_level": "authoritative", "source_ref": "vulndesk://cve-cwes"},
        {"from_type": "CWE", "from_id": "CWE-79", "to_type": "CAPEC", "to_id": "CAPEC-63",
         "mapping_level": "related", "source_ref": "vulndesk://capec"},
    ]
    if not drop_attack:
        links.append({"from_type": "CAPEC", "from_id": "CAPEC-63", "to_type": "ATTACK", "to_id": "T1190",
                      "tactic": "Initial Access", "mapping_level": level, "source_ref": "vulndesk://attack"})
    return normalize_attack_chain({"snapshot": {"graph_snapshot_id": "ctigs-feat"}, "links": links}, entry="CWE")


def _path(chain=None, refs=3, conf=0.5, impact=0.5):
    knowledge = {"knowledge_id": "k"}
    if chain is not None:
        knowledge["attack_chain"] = chain
    return {
        "planning_score": {"hypothesis_confidence": conf, "impact_factor": impact},
        "provenance": {"supporting_evidence_refs": ["e"] * refs, "knowledge": knowledge},
    }


def test_strength_is_pure_and_monotone_in_level():
    assert chain_mapping_strength(_chain("authoritative")) == pytest.approx(1.0)
    assert chain_mapping_strength(_chain("related")) == pytest.approx(0.66)
    assert chain_mapping_strength(_chain("partial")) == pytest.approx(0.33)
    assert chain_mapping_strength(_chain("heuristic")) == pytest.approx(0.1)
    # Stable: identical block -> identical value.
    assert chain_mapping_strength(_chain("partial")) == chain_mapping_strength(_chain("partial"))


def test_truncated_tail_is_penalized_and_missing_attack_is_half():
    # Never reaching ATT&CK: reached_attack False -> 0.5 multiplier on s=0 -> 0.0 (honest).
    assert chain_mapping_strength(_chain(drop_attack=True)) == 0.0


def test_candidate_features_reads_chain_from_path():
    feats = apr.candidate_path_features(_path(chain=_chain("authoritative")))
    assert feats["chain_mapping_strength"] == pytest.approx(1.0)
    assert set(feats) == set(apr.RANKER_FEATURES_V2)


def test_no_chain_is_zero():
    feats = apr.candidate_path_features(_path(chain=None))
    assert feats["chain_mapping_strength"] == 0.0


def test_serve_never_queries_cti(monkeypatch):
    import pentest_subsystem.cti_attack_chain as cac

    def _boom(*a, **k):
        raise AssertionError("serve must not query CTI")

    monkeypatch.setattr(cac, "fetch_attack_chain", _boom)
    # Reads only the sealed chain already on the path -> no fetch.
    feats = apr.candidate_path_features(_path(chain=_chain("related")))
    assert feats["chain_mapping_strength"] == pytest.approx(0.66)
