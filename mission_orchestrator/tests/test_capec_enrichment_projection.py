from unittest.mock import Mock, patch

from pentest_subsystem.enrichment import parse_attack, request_sha


def test_capec_support_survives_stronger_direct_attack_mapping():
    result = parse_attack({"attack_context": [{
        "attack_id": "T1189", "mapping_source": "analyst", "confidence": .9,
        "supporting_mappings": [
            {"capec_id": "CAPEC-63", "cwe_id": "CWE-79", "mapping_source": "capec",
             "source_dataset": "mitre-capec", "source_version": "CAPEC:3.9"},
            {"capec_id": "invalid"},
        ],
    }]})
    link, = result[0]["capec_mappings"]
    assert link["capec_id"] == "CAPEC-63"
    assert link["cwe_id"] == "CWE-79"
    assert link["source_dataset"] == "mitre-capec"
    assert parse_attack({"attack_context": [{"attack_id": "T1189"}]})[0]["capec_mappings"] == []


def test_capec_parser_change_refreshes_old_cache_keys():
    from pentest_subsystem.boundary_contract import sha256_hex
    request = {"candidate": {"cve_id": "CVE-2012-4360"}}
    old = sha256_hex({"schema": "apts-enrichment-cache-v1", "kind": "attack", "request": request,
                      "mapping_contract": "catalog-cwes-word-boundary-rce-v2"})
    assert request_sha("attack", request) != old


def test_workspace_exposes_chains_by_model_hash_without_changing_plan():
    from pentest_subsystem.attack_path_workspace import workspace
    service = Mock()
    chain = {"links": [{"from_type": "CWE", "from_id": "CWE-79",
                        "to_type": "CAPEC", "to_id": "CAPEC-63"}]}
    service.get_orchestration_vulnerability_hypothesis_run.return_value = {
        "output": {"vulnerability_hypotheses": [{"knowledge": {"attack_chain": chain},
                    "integrity": {"canonical_sha256": "model-sha"}}]}}
    source = {"contexts": [{"context_id": "ctx", "orchestration_id": "paorch-test",
                            "hypothesis_run": {"id": "hyp-run"},
                            "correlation": {"status": "COMPLETED"}}]}
    revision = {"plan": {"paths": []}}
    with patch("pentest_subsystem.vulnerability_hypothesis_workspace.workspace", return_value=source), \
         patch("pentest_subsystem.attack_path_workspace.ensure_plan"), \
         patch("pentest_subsystem.attack_path_workspace.history", return_value=[revision]):
        context = workspace(service)["contexts"][0]
    assert context["knowledge_chains"] == {"model-sha": chain}
    assert context["revisions"] == [revision]
from pentest_subsystem.boundary_contract import sha256_hex


def test_capec_support_survives_stronger_direct_mapping():
    support = {"capec_id": "CAPEC-66", "cwe_id": "CWE-89",
               "mapping_source": "capec", "source_dataset": "mitre-capec",
               "source_version": "CAPEC:3.9"}
    result = parse_attack({"attack_context": [{
        "attack_id": "T1190", "mapping_source": "analyst", "confidence": .9,
        "supporting_mappings": [support, support, {"capec_id": "bad"}],
    }]})
    assert result[0]["mapping_source"] == "analyst"
    assert len(result[0]["capec_mappings"]) == 1
    assert result[0]["capec_mappings"][0].items() >= support.items()
    assert parse_attack({"attack_context": [{"attack_id": "T1189"}]})[0]["capec_mappings"] == []
    assert parse_attack({"attack_context": [{"attack_id": "T1190", **support}]})[0]["capec_mappings"]


def test_capec_cache_contract_refetches_old_lossy_projection():
    request = {"candidate": {"cve_id": "CVE-2012-4360"}}
    old = sha256_hex({"schema": "apts-enrichment-cache-v1", "kind": "attack", "request": request,
                      "mapping_contract": "catalog-cwes-word-boundary-rce-v2"})
    assert request_sha("attack", request) != old
