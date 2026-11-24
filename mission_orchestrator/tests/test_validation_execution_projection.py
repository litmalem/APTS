"""Unit tests for the safe validation-stage execution-authority projection used by
the autonomous Mission governance binding. Pure function: no Mission/DB setup."""
from mission_orchestrator.governance_binding import (
    SAFE_VALIDATION_TECHNIQUES, project_validation_execution_authority)


def _validation_cap(techniques=SAFE_VALIDATION_TECHNIQUES, methods=("GET", "HEAD")):
    return {"capability_id": "pentest.validate", "action_class": "VULNERABILITY_VALIDATION",
            "authorization_mode": "REQUIRED", "requires_human_approval": False,
            "constraints": {"allowed_techniques": list(techniques), "allowed_methods": list(methods)}}


def _source_allow(techniques=SAFE_VALIDATION_TECHNIQUES, prohibited=()):
    return [{"action_class": "VULNERABILITY_VALIDATION", "action_name": "AUTHORIZE_TARGET_EXECUTION",
             "effect": "ALLOW", "requires_approval": False,
             "constraints": {"allowed_techniques": list(techniques), "prohibited_techniques": list(prohibited)}}]


def test_projects_authority_for_permitted_safe_techniques():
    rule = project_validation_execution_authority(_source_allow(), _validation_cap())
    assert rule["action_class"] == "VULNERABILITY_VALIDATION"
    assert rule["action_name"] == "AUTHORIZE_TARGET_EXECUTION"
    assert rule["effect"] == "ALLOW" and rule["requires_approval"] is False
    assert rule["max_risk_level"] == "MODERATE"
    assert rule["constraints"]["read_only"] is True
    assert set(rule["constraints"]["allowed_techniques"]) == set(SAFE_VALIDATION_TECHNIQUES)
    assert rule["constraints"]["allowed_methods"] == ["GET", "HEAD"]


def test_none_without_validation_capability():
    assert project_validation_execution_authority(_source_allow(), None) is None


def test_none_when_scope_has_no_validation_rule():
    # A recon-only scope (no VULNERABILITY_VALIDATION execution rule) grants nothing.
    recon_only = [{"action_class": "TARGET_RECON", "action_name": "AUTHORIZE_TARGET_EXECUTION",
                   "effect": "ALLOW", "constraints": {"allowed_techniques": ["WEB_TECHNOLOGY_FINGERPRINT"]}}]
    assert project_validation_execution_authority(recon_only, _validation_cap()) is None


def test_prohibited_technique_is_excluded():
    src = _source_allow(prohibited=["SAFE_VERSION_CONFIGURATION_CONFIRMATION"])
    rule = project_validation_execution_authority(src, _validation_cap())
    assert "SAFE_VERSION_CONFIGURATION_CONFIRMATION" not in rule["constraints"]["allowed_techniques"]
    assert "HTTP_HEADER_INSPECTION" in rule["constraints"]["allowed_techniques"]


def test_review_or_approval_blocks_projection():
    src = _source_allow()
    src[0]["requires_approval"] = True
    assert project_validation_execution_authority(src, _validation_cap()) is None


def test_unsafe_technique_request_is_never_authorized():
    # Even if a caller asks for a non-safe technique, only SAFE_VALIDATION_TECHNIQUES pass.
    cap = _validation_cap(techniques=["CONTROLLED_EXPLOIT_PRIMITIVE"])
    src = [{"action_class": "VULNERABILITY_VALIDATION", "action_name": "AUTHORIZE_TARGET_EXECUTION",
            "effect": "ALLOW", "requires_approval": False,
            "constraints": {"allowed_techniques": ["CONTROLLED_EXPLOIT_PRIMITIVE"]}}]
    assert project_validation_execution_authority(src, cap) is None


def test_scope_subset_narrows_requested_techniques():
    # Capability asks for all three; scope allows only one -> only that one is projected.
    src = _source_allow(techniques=["HTTP_HEADER_INSPECTION"])
    rule = project_validation_execution_authority(src, _validation_cap())
    assert rule["constraints"]["allowed_techniques"] == ["HTTP_HEADER_INSPECTION"]
