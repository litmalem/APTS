"""Stage 5.4 attack-chain provenance (#1): deterministic normalization, sealing and
fan-out pruning of the CPE->CVE->CWE->CAPEC->ATT&CK chain, plus loopback fetch shaping.

Mirrors the STAGE_X_Y acceptance pattern: a sealed, replayable provenance block with
honest completeness flags and no causal/edge leakage.
"""
from __future__ import annotations

import io
import json

import pytest

from pentest_subsystem import cti_attack_chain as cac
from pentest_subsystem.cti_attack_chain import (
    ATTACK_CHAIN_SCHEMA_VERSION,
    TOPK_PER_LEVEL,
    AttackChainError,
    normalize_attack_chain,
    verify_attack_chain,
)


def _raw_full():
    return {
        "snapshot": {"source": "vulndesk", "graph_snapshot_id": "ctigs-abc123",
                     "nvd_version": "2026.11", "cwe_version": "4.14",
                     "capec_version": "3.9", "attack_version": "15.1"},
        "links": [
            {"from_type": "CPE", "from_id": "cpe:2.3:a:vendor:product:1.0:*", "to_type": "CVE",
             "to_id": "CVE-2021-1234", "mapping_level": "authoritative", "source_ref": "vulndesk://cpe_matches"},
            {"from_type": "CVE", "from_id": "CVE-2021-1234", "to_type": "CWE", "to_id": "CWE-639",
             "mapping_level": "authoritative", "source_ref": "vulndesk://cve-cwes"},
            {"from_type": "CWE", "from_id": "CWE-639", "to_type": "CAPEC", "to_id": "CAPEC-122",
             "mapping_level": "related", "source_ref": "vulndesk://capec_cwe_mappings"},
            {"from_type": "CAPEC", "from_id": "CAPEC-122", "to_type": "ATTACK", "to_id": "T1190",
             "tactic": "Initial Access", "mapping_level": "partial", "source_ref": "vulndesk://capec_attack_mappings"},
        ],
    }


def test_normalize_is_deterministic_and_sealed():
    block_a = normalize_attack_chain(_raw_full(), entry="CPE")
    block_b = normalize_attack_chain(_raw_full(), entry="CPE")
    assert block_a == block_b
    assert json.dumps(block_a, sort_keys=True) == json.dumps(block_b, sort_keys=True)
    assert block_a["schema_version"] == ATTACK_CHAIN_SCHEMA_VERSION
    assert block_a["entry"] == "CPE"
    assert verify_attack_chain(block_a)
    # The seal is content-bound: mutating any core field must break verification.
    tampered = json.loads(json.dumps(block_a))
    tampered["completeness"]["fanout_pruned"] = 999
    assert not verify_attack_chain(tampered)


def test_completeness_flags_are_honest():
    block = normalize_attack_chain(_raw_full(), entry="CPE")
    assert block["completeness"]["reached_attack"] is True
    assert block["completeness"]["tail_truncated"] is False
    assert block["attack_techniques"] == [
        {"technique_id": "T1190", "tactic": "Initial Access", "mapping_level": "partial", "is_causal": False}
    ]


def test_tail_truncated_when_attack_missing():
    raw = _raw_full()
    raw["links"] = raw["links"][:3]  # drop the CAPEC->ATTACK hop
    block = normalize_attack_chain(raw, entry="CPE")
    assert block["completeness"]["reached_attack"] is False
    assert block["completeness"]["tail_truncated"] is True
    assert block["attack_techniques"] == []


def test_fanout_pruning_is_deterministic_and_counted():
    raw = _raw_full()
    # 10 distinct CAPEC->ATTACK edges of equal (partial) weight -> keep TOPK, prune the rest.
    raw["links"] = raw["links"][:3] + [
        {"from_type": "CAPEC", "from_id": f"CAPEC-{200 + i}", "to_type": "ATTACK",
         "to_id": f"T19{i:02d}", "tactic": "Execution", "mapping_level": "partial",
         "source_ref": "vulndesk://capec_attack_mappings"}
        for i in range(10)
    ]
    block = normalize_attack_chain(raw, entry="CPE")
    attack_links = [l for l in block["links"] if l["to_type"] == "ATTACK"]
    assert len(attack_links) == TOPK_PER_LEVEL
    assert block["completeness"]["fanout_pruned"] == 2
    # Stable selection: strongest-then-id order keeps the lexicographically first ids.
    kept_ids = sorted(l["to_id"] for l in attack_links)
    assert kept_ids == [f"T19{i:02d}" for i in range(TOPK_PER_LEVEL)]
    # Re-running yields the identical seal (replayable).
    assert normalize_attack_chain(raw, entry="CPE") == block


def test_higher_weight_edges_win_dedupe():
    raw = _raw_full()
    raw["links"].append({
        "from_type": "CAPEC", "from_id": "CAPEC-122", "to_type": "ATTACK", "to_id": "T1190",
        "tactic": "Initial Access", "mapping_level": "authoritative", "source_ref": "vulndesk://x"})
    block = normalize_attack_chain(raw, entry="CPE")
    attack_links = [l for l in block["links"] if l["to_id"] == "T1190"]
    assert len(attack_links) == 1
    assert attack_links[0]["mapping_level"] == "authoritative"


def test_rejects_bad_entry_and_bad_technique_and_causal():
    with pytest.raises(AttackChainError):
        normalize_attack_chain(_raw_full(), entry="CVE")
    bad = _raw_full()
    bad["links"][-1]["to_id"] = "NOT-A-TECHNIQUE"
    with pytest.raises(AttackChainError):
        normalize_attack_chain(bad, entry="CPE")
    bad_level = _raw_full()
    bad_level["links"][-1]["mapping_level"] = "totally-made-up"
    with pytest.raises(AttackChainError):
        normalize_attack_chain(bad_level, entry="CPE")


def test_entry_cwe_without_cpe_hop():
    raw = _raw_full()
    raw["links"] = raw["links"][1:]  # start at CVE->CWE (no CPE hop); entry=CWE
    block = normalize_attack_chain(raw, entry="CWE")
    assert block["entry"] == "CWE"
    assert block["completeness"]["reached_attack"] is True
    assert block["completeness"]["tail_truncated"] is False


# ---- fetch shaping (loopback, fail-open) -------------------------------------------------------

class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _fake_opener(routes):
    def opener(request, timeout=None):
        path = request.full_url.split("8765", 1)[-1] if "8765" in request.full_url else request.full_url
        for key, payload in routes.items():
            if key in path:
                return _FakeResp(json.dumps(payload).encode("utf-8"))
        return _FakeResp(json.dumps({}).encode("utf-8"))
    return opener


def test_fetch_shapes_vulndesk_responses(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")
    routes = {
        "/api/pentest/cve-cwes": {"status": "completed", "results": [
            {"cve_id": "CVE-2021-1234", "cwe_id": "CWE-639", "cwe_name": "Authorization Bypass"}]},
        "/api/pentest/map-attack": {"status": "completed", "attack_context": [
            {"attack_id": "T1190", "tactic_name": "Initial Access", "capec_id": "CAPEC-122",
             "cwe_id": "CWE-639", "mapping_level": "capec_to_attack", "mapping_source": "capec", "confidence": 0.8}]},
    }
    raw = cac.fetch_attack_chain(cve="CVE-2021-1234", cpe="cpe:2.3:a:v:p:1.0:*",
                                 opener=_fake_opener(routes))
    assert raw is not None
    block = normalize_attack_chain(raw, entry="CPE")
    assert verify_attack_chain(block)
    assert block["completeness"]["reached_attack"] is True
    assert {l["to_type"] for l in block["links"]} >= {"CVE", "CWE", "CAPEC", "ATTACK"}


def test_fetch_fail_open_returns_none(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")

    def boom(request, timeout=None):
        raise OSError("connection refused")

    assert cac.fetch_attack_chain(cve="CVE-2021-1234", opener=boom) is None
    assert cac.fetch_attack_chain(cve=None, opener=boom) is None
