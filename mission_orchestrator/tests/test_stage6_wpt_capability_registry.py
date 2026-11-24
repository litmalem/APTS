from __future__ import annotations

import pytest

from execution_subsystem.execution_contract import ExecutionSourceRejected
from execution_subsystem.tool_registry import (
    ADAPTERS,
    select_adapter,
    wpt_capability_profile_definitions,
)
from execution_subsystem.adapter_contract import canonical_adapter_contract


def test_wpt_capabilities_are_registered_as_separate_fixed_contracts():
    profiles = wpt_capability_profile_definitions()
    assert [item["profile_id"] for item in profiles] == [
        "wpt.fingerprinting.v1", "wpt.bounded-enumeration.v1"
    ]
    assert [item["action"]["capability_id"] for item in profiles] == [
        "web_technology_fingerprinting", "web_surface_enumeration"
    ]
    assert [item["action"]["technique"] for item in profiles] == [
        "WEB_TECHNOLOGY_FINGERPRINT", "BOUNDED_WEB_SURFACE_ENUMERATION"
    ]
    assert all(item["action"]["action_class"] == "TARGET_RECON" for item in profiles)
    assert [item["execution_status"] for item in profiles] == ["EXECUTABLE", "EXECUTABLE"]
    assert profiles[0]["limits"] == {
        "max_requests": 6, "max_response_bytes": 393216, "max_concurrency": 1,
        "timeout_seconds": 15, "redirects": "SAME_ORIGIN_SCOPE_PREFIX_MAX_2",
    }
    assert profiles[1]["limits"] == {
        "max_requests": 9, "max_response_bytes": 262144, "max_concurrency": 1,
        "timeout_seconds": 30, "redirects": "DENY",
    }
    for profile in profiles:
        assert profile["request_schema"]["additionalProperties"] is False
        assert profile["result_schema"]["properties"]["mode"]["const"] in {
            "fingerprinting", "enumeration"
        }
        assert "scan_status" in profile["result_schema"]["properties"]["scan_metrics"]["required"]
        assert "sealed_stage6_evidence" in profile["required_evidence"]


def test_both_wpt_adapters_are_fixed_and_historical_contract_is_preserved():
    contract = canonical_adapter_contract()
    # The legacy base hash remains stable for historical sealed evidence.
    from execution_subsystem.adapter_contract import legacy_wpt_capability_profiles,bounded_web_profile_contract
    assert contract["registered_capability_profiles"] == legacy_wpt_capability_profiles()
    assert bounded_web_profile_contract()["max_requests"] == 6
    assert wpt_capability_profile_definitions()[0]["result_schema"]["properties"]["schema_version"]["const"] == "web-technology-observation-v4"
    profile, enumeration = contract["registered_capability_profiles"]
    assert profile["adapter_id"] in {adapter.adapter_id for adapter in ADAPTERS}
    selected = select_adapter({"action": profile["action"],
        "target": {"target_type": "URL", "target_value": "https://example.test/"},
        "parameters": {"estimated_impact": "LOW"}})
    assert selected.operation == "WEB_PROFILE_FINGERPRINT"
    assert enumeration['execution_status'] == 'REGISTERED_NOT_EXECUTABLE'
    assert enumeration['adapter_id'] not in {a['adapter_id'] for a in contract['adapters']}
    assert select_adapter({"action": enumeration["action"],
            "target": {"target_type": "URL", "target_value": "https://example.test/"},
            "parameters": {"estimated_impact": "LOW"}}).operation == 'WEB_PROFILE_ENUMERATION'

