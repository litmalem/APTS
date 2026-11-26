"""Stage 5.4 attack-chain provenance (#2): entry="CPE" wiring in cti_hypothesis_adapter.

A CVE knowledge_item gains a sealed attack_chain tail only when VulnDesk resolves it;
a resolution failure leaves the item byte-identical to the pre-chain behaviour (fail-open).
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


def _boom(request, timeout=None):
    raise OSError("connection refused")


_ROUTES = {
    "/api/pentest/cve-cwes": {"results": [{"cve_id": "CVE-2021-1234", "cwe_id": "CWE-639", "cwe_name": "Auth Bypass"}]},
    "/api/pentest/map-attack": {"attack_context": [
        {"attack_id": "T1190", "tactic_name": "Initial Access", "capec_id": "CAPEC-122",
         "cwe_id": "CWE-639", "mapping_level": "capec_to_attack", "mapping_source": "capec", "confidence": 0.8}]},
}

_CAND = {"cve_id": "CVE-2021-1234", "severity": "HIGH", "cvss_score": 7.5,
         "match_confidence": 0.7, "description": "Synthetic advisory"}
_MATCH = {"products": ["Product"], "versions": ["1.0.*"]}


def test_knowledge_item_gets_cpe_chain(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")
    item = adapter._knowledge_item("CVE-2021-1234", _CAND, match=_MATCH, subject="Product",
                                   cpe="cpe:2.3:a:v:p:1.0:*", opener=_opener(_ROUTES))
    assert "attack_chain" in item
    assert item["attack_chain"]["entry"] == "CPE"
    assert verify_attack_chain(item["attack_chain"])
    # End-to-end: the enriched item still normalizes & seals under Stage 5.4.
    normalized = _normalize_knowledge_item(item, 0)
    assert normalized["attack_chain"]["completeness"]["reached_attack"] is True


def test_resolution_failure_is_fail_open(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")
    enriched = adapter._knowledge_item("CVE-2021-1234", _CAND, match=_MATCH, subject="Product",
                                       cpe="cpe:2.3:a:v:p:1.0:*", opener=_boom)
    baseline = adapter._knowledge_item("CVE-2021-1234", _CAND, match=_MATCH, subject="Product",
                                       with_attack_chain=False)
    assert "attack_chain" not in enriched
    assert enriched == baseline  # byte-identical to pre-chain behaviour


def test_build_knowledge_items_threads_chain(monkeypatch):
    monkeypatch.setenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")
    routes = {
        "/api/pentest/resolve-cpe": {"results": [
            {"cve_id": "CVE-2021-1234", "official_cpe23_uri": "cpe:2.3:a:v:p:1.0:*",
             "technology_version": "1.0", "severity": "HIGH", "match_confidence": 0.8,
             "description": "adv"}]},
        **_ROUTES,
    }
    enumeration_run = {"output": {
        "cpe_candidates": [{"cpe23_uri": "cpe:2.3:a:v:p:1.0:*"}],
        "enumerated_assets": [{"versions": [{"product": "Product", "version": "1.0"}],
                               "technologies": [], "cpe_candidates": []}],
    }, "request": {}}
    items = adapter.build_knowledge_items(enumeration_run, opener=_opener(routes))
    assert items and items[0]["knowledge_type"] == "CVE"
    assert items[0]["attack_chain"]["entry"] == "CPE"
    # Fail-open at the batch level: no chain field, but CVE items still produced.
    items_no_chain = adapter.build_knowledge_items(enumeration_run, opener=_opener(
        {"/api/pentest/resolve-cpe": routes["/api/pentest/resolve-cpe"]}))
    assert items_no_chain and "attack_chain" not in items_no_chain[0]
