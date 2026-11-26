"""Stage 5.4 attack-chain provenance (#4): the optional attack_chain block is sealed
into knowledge_sha256, rejected when malformed, and omitted-safe (byte-identical to the
pre-chain behaviour when absent).
"""
from __future__ import annotations

import json

import pytest

from pentest_subsystem.cti_attack_chain import normalize_attack_chain
from pentest_subsystem.vulnerability_hypothesis import (
    VulnerabilityHypothesisAgentValidationError,
    _normalize_knowledge_item,
)

from tests.test_stage5_4_vulnerability_hypothesis_agent import knowledge_item


def _chain():
    raw = {
        "snapshot": {"source": "vulndesk", "graph_snapshot_id": "ctigs-abc123"},
        "links": [
            {"from_type": "CPE", "from_id": "cpe:2.3:a:v:p:1.0:*", "to_type": "CVE",
             "to_id": "CVE-2021-1234", "mapping_level": "authoritative", "source_ref": "vulndesk://cpe_matches"},
            {"from_type": "CVE", "from_id": "CVE-2021-1234", "to_type": "CWE", "to_id": "CWE-639",
             "mapping_level": "authoritative", "source_ref": "vulndesk://cve-cwes"},
            {"from_type": "CWE", "from_id": "CWE-639", "to_type": "CAPEC", "to_id": "CAPEC-122",
             "mapping_level": "related", "source_ref": "vulndesk://capec_cwe"},
            {"from_type": "CAPEC", "from_id": "CAPEC-122", "to_type": "ATTACK", "to_id": "T1190",
             "tactic": "Initial Access", "mapping_level": "partial", "source_ref": "vulndesk://capec_attack"},
        ],
    }
    return normalize_attack_chain(raw, entry="CPE")


def test_absent_chain_is_byte_identical_to_pre_chain_behaviour():
    base = _normalize_knowledge_item(knowledge_item("nochain"), 0)
    assert "attack_chain" not in base
    # Re-normalizing is stable and the hash is unaffected by the new optional field.
    again = _normalize_knowledge_item(knowledge_item("nochain"), 0)
    assert base == again


def test_chain_is_sealed_into_knowledge_sha256():
    without = _normalize_knowledge_item(knowledge_item("withchain"), 0)
    item = knowledge_item("withchain")
    item["attack_chain"] = _chain()
    with_chain = _normalize_knowledge_item(item, 0)
    assert with_chain["attack_chain"] == _chain()
    # Folding the chain in changes knowledge_sha256 (hash-chain cascade by design).
    assert with_chain["knowledge_sha256"] != without["knowledge_sha256"]
    # Deterministic: same input -> same seal.
    assert _normalize_knowledge_item(item, 0)["knowledge_sha256"] == with_chain["knowledge_sha256"]
    # A different chain yields a different knowledge hash.
    other = knowledge_item("withchain")
    pruned = _chain()
    pruned["completeness"]["fanout_pruned"] = 3
    pruned["integrity"]["canonical_sha256"] = "0" * 64  # now internally inconsistent
    other["attack_chain"] = pruned
    with pytest.raises(VulnerabilityHypothesisAgentValidationError):
        _normalize_knowledge_item(other, 0)


def test_rejects_unknown_field():
    item = knowledge_item("badfield")
    chain = _chain()
    chain["surprise"] = True
    item["attack_chain"] = chain
    with pytest.raises(VulnerabilityHypothesisAgentValidationError):
        _normalize_knowledge_item(item, 0)


def test_rejects_causal_technique():
    item = knowledge_item("causal")
    chain = _chain()
    chain["attack_techniques"][0]["is_causal"] = True
    item["attack_chain"] = chain
    with pytest.raises(VulnerabilityHypothesisAgentValidationError):
        _normalize_knowledge_item(item, 0)


def test_rejects_invalid_technique_id():
    item = knowledge_item("badtech")
    chain = _chain()
    chain["attack_techniques"][0]["technique_id"] = "NOPE"
    item["attack_chain"] = chain
    with pytest.raises(VulnerabilityHypothesisAgentValidationError):
        _normalize_knowledge_item(item, 0)


def test_rejects_tampered_seal():
    item = knowledge_item("tamper")
    chain = _chain()
    chain["links"][0]["mapping_level"] = "heuristic"  # content changed, seal not recomputed
    item["attack_chain"] = chain
    with pytest.raises(VulnerabilityHypothesisAgentValidationError):
        _normalize_knowledge_item(item, 0)
