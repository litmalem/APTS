"""Stage 5.4 attack-chain provenance (#3): entry="CWE" weakness seeds (design §2.1).

CVE-less lab targets (Juice Shop / DVWA Broken Access Control) enter the chain from a
CWE seed: the CAPEC->ATT&CK tail is filled when VulnDesk resolves it, and tail_truncated
is honest (no fabricated mapping) when it does not.
"""
from __future__ import annotations

import io
import json

from pentest_subsystem import cti_hypothesis_adapter as adapter
from pentest_subsystem.cti_attack_chain import verify_attack_chain
from pentest_subsystem.vulnerability_hypothesis import _normalize_knowledge_item


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _opener(routes):
    def opener(request, timeout=None):
        path = request.full_url.split("8765", 1)[-1] if "8765" in request.full_url else request.full_url
        for key, payload in routes.items():
            if key in path:
                return _FakeResp(json.dumps(payload).encode("utf-8"))
        return _FakeResp(json.dumps({}).encode("utf-8"))
    return opener


_SEEDS = [{
    "cwe": "CWE-639", "capec": "CAPEC-122", "technology": "Juice Shop",
    "title": "IDOR / Broken Access Control",
    "match": {"technologies": ["Juice Shop"], "endpoints": ["/api/BasketItems"]},
    "confidence": 0.5, "estimated_impact": "MEDIUM",
}]


def test_cwe_seed_gets_attack_tail(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")
    routes = {"/api/pentest/map-attack": {"attack_context": [
        {"attack_id": "T1190", "tactic_name": "Initial Access", "capec_id": "CAPEC-122",
         "cwe_id": "CWE-639", "mapping_level": "capec_to_attack", "mapping_source": "capec", "confidence": 0.7}]}}
    items = adapter.build_weakness_knowledge_items(None, _SEEDS, opener=_opener(routes))
    assert len(items) == 1
    item = items[0]
    assert item["knowledge_type"] == "WEAKNESS_PATTERN"
    assert item["attack_chain"]["entry"] == "CWE"
    assert item["attack_chain"]["completeness"]["reached_attack"] is True
    assert verify_attack_chain(item["attack_chain"])
    # It normalizes & seals as a valid Stage-5.4 knowledge_item.
    assert "attack_chain" in _normalize_knowledge_item(item, 0)


def test_empty_mapping_is_honest_tail_truncated(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")
    # map-attack returns no techniques -> no chain attached (fetch is fail-open/None),
    # but the weakness item itself is still emitted (no fabricated mapping).
    items = adapter.build_weakness_knowledge_items(None, _SEEDS, opener=_opener(
        {"/api/pentest/map-attack": {"attack_context": []}}))
    assert len(items) == 1
    assert "attack_chain" not in items[0]
    assert _normalize_knowledge_item(items[0], 0)["knowledge_type"] == "WEAKNESS_PATTERN"


def test_enumeration_scoping_skips_unconfirmed_tech(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")
    enumeration_run = {"output": {"technology_identifications": [{"technology": "DVWA"}],
                                  "enumerated_assets": []}}
    # Seed declares technology "Juice Shop" which the enumeration did not confirm -> skipped.
    items = adapter.build_weakness_knowledge_items(enumeration_run, _SEEDS, opener=_opener({}))
    assert items == []
