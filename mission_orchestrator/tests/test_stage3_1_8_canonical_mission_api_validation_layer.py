from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionValidationPipelineError
from mission_orchestrator.mission_validation import (
    CANONICAL_MISSION_API_SCHEMA_VERSION,
    VALIDATION_MODE,
    VALIDATION_PIPELINE,
    VALIDATION_SCHEMA_VERSION,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallGovernance:
    base_url = "fake://governance-no-call"

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def fail(*args, **kwargs):
            self.calls += 1
            raise AssertionError(f"Stage 3.1.8 local validation/read projection must not call Governance: {name}")

        return fail


class NoCallCti:
    base_url = "fake://cti-no-call"

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def fail(*args, **kwargs):
            self.calls += 1
            raise AssertionError(f"Stage 3.1.8 local validation/read projection must not call CTI: {name}")

        return fail


def mission_payload(key: str = "stage318-mission"):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST",
        "created_by": "stage3.1.8-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab-target"},
        "success_criteria": [{"metric": "contract_valid", "expected": True}],
        "budgets": {"time_seconds": 1800},
        "required_subsystems": ["CTI", "PENTEST"],
        "metadata": {"environment": "LAB", "stage": "3.1.8"},
    }


def scope_payload(key: str = "stage318-scope", max_duration: int = 1800):
    return {
        "expected_contract_version": 0,
        "idempotency_key": key,
        "actor": "stage3.1.8-pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [],
            "network_ranges": ["127.0.0.0/8"],
            "domains": [],
            "services": [],
        },
        "roe": {
            "allowed_action_classes": ["INTERNAL_REASONING", "TARGET_RECON"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "allowed_time_window": {
                "start_at": "2026-09-01T00:00:00Z",
                "end_at": "2030-09-03T00:00:00Z",
            },
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": [],
        },
        "constraints": {
            "max_actions": 20,
            "max_duration": max_duration,
            "risk_threshold": "MODERATE",
            "resource_budget": {"max_network_requests": 500},
            "data_handling_policy": {
                "classification": "INTERNAL",
                "retention_days": 7,
                "export_allowed": False,
            },
        },
        "reason": "Stage 3.1.8 canonical validation",
        "metadata": {"environment": "LAB", "stage": "3.1.8"},
    }


def draft(key: str = "stage318-mission", scope_key: str = "stage318-scope"):
    return {"mission": mission_payload(key), "scope_contract": scope_payload(scope_key)}


def make_service(db_path: Path):
    gov = NoCallGovernance()
    cti = NoCallCti()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(db_path))
    return CanonicalMissionService(repo, governance_client=gov, cti_client=cti), gov, cti


def test_stage318_health_stabilizes_api_and_validation_without_execution_authority(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    health = svc.health()

    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert "stage3.1.7-mission-persistence-repository-model" in health["supported_controls"]
    assert health["canonical_mission_api_schema_version"] == CANONICAL_MISSION_API_SCHEMA_VERSION
    assert health["canonical_mission_api_stabilized"] is True
    assert health["canonical_mission_validation_schema_version"] == VALIDATION_SCHEMA_VERSION
    assert health["canonical_mission_validation_mode"] == VALIDATION_MODE
    assert health["canonical_mission_validation_pipeline"] == list(VALIDATION_PIPELINE)
    assert health["canonical_mission_preflight_enabled"] is True
    assert health["validation_external_authority_queries"] is False
    assert health["dispatch_enabled"] is False
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_valid_preflight_runs_all_layers_without_persistence_or_authority_calls(tmp_path):
    svc, gov, cti = make_service(tmp_path / "missions.db")
    report = svc.validate_canonical_mission(draft())

    assert report["valid"] is True
    assert report["status"] == "valid"
    assert report["validation_pipeline"] == ["SCHEMA", "SEMANTIC", "SCOPE", "CONSTRAINTS"]
    assert [check["phase"] for check in report["checks"]] == ["SCHEMA", "SEMANTIC", "SCOPE", "CONSTRAINTS"]
    assert all(check["status"] == "PASS" for check in report["checks"])
    assert len(report["mission_request_sha256"]) == 64
    assert len(report["scope_contract_request_sha256"]) == 64
    assert report["persistence_performed"] is False
    assert report["authority_query_performed"] is False
    assert report["planning_performed"] is False
    assert report["target_action_performed"] is False
    assert svc.repository.get_by_idempotency("PYTEST", "stage318-mission") is None
    assert gov.calls == 0
    assert cti.calls == 0


def test_schema_failure_is_phase_labeled_and_does_not_persist(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    payload = draft("schema-fail")
    payload["mission"]["unsupported_field"] = "reject-me"

    with pytest.raises(MissionValidationPipelineError) as exc:
        svc.validate_canonical_mission(payload)

    assert exc.value.phase == "SCHEMA"
    assert exc.value.check_id == "MISSION_CREATE_SCHEMA"
    assert svc.repository.get_by_idempotency("PYTEST", "schema-fail") is None


def test_semantic_failure_rejects_unknown_required_subsystem_before_persistence(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    payload = draft("semantic-fail")
    payload["mission"]["required_subsystems"] = ["CTI", "UNKNOWN-SUBSYSTEM"]

    with pytest.raises(MissionValidationPipelineError) as exc:
        svc.validate_canonical_mission(payload)

    assert exc.value.phase == "SEMANTIC"
    assert exc.value.check_id == "MISSION_SUBSYSTEM_SEMANTICS"
    assert svc.repository.get_by_idempotency("PYTEST", "semantic-fail") is None


def test_scope_failure_is_phase_labeled_and_does_not_persist(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    payload = draft("scope-fail")
    same = {"target_type": "IP", "target_value": "127.0.0.1", "environment": "LAB"}
    payload["scope_contract"]["scope"]["targets"] = [same]
    payload["scope_contract"]["scope"]["excluded_targets"] = [same]

    with pytest.raises(MissionValidationPipelineError) as exc:
        svc.validate_canonical_mission(payload)

    assert exc.value.phase == "SCOPE"
    assert exc.value.check_id == "SCOPE_ROE_CONTRACT"
    assert svc.repository.get_by_idempotency("PYTEST", "scope-fail") is None


def test_constraint_schema_failure_is_phase_labeled_and_does_not_persist(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    payload = draft("constraint-fail")
    payload["scope_contract"]["constraints"]["max_duration"] = 0

    with pytest.raises(MissionValidationPipelineError) as exc:
        svc.validate_canonical_mission(payload)

    assert exc.value.phase == "CONSTRAINTS"
    assert exc.value.check_id == "CONSTRAINT_CONTRACT"
    assert svc.repository.get_by_idempotency("PYTEST", "constraint-fail") is None


def test_cross_contract_duration_budget_alignment_fails_closed(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    payload = {"mission": mission_payload("budget-fail"), "scope_contract": scope_payload("budget-scope", 1801)}

    with pytest.raises(MissionValidationPipelineError) as exc:
        svc.validate_canonical_mission(payload)

    assert exc.value.phase == "CONSTRAINTS"
    assert exc.value.check_id == "MISSION_BUDGET_ALIGNMENT"
    assert "exceeds mission duration budget" in str(exc.value)
    assert svc.repository.get_by_idempotency("PYTEST", "budget-fail") is None


def test_validation_fingerprints_are_deterministic_for_same_canonical_draft(tmp_path):
    svc, _, _ = make_service(tmp_path / "missions.db")
    first = svc.validate_canonical_mission(draft("deterministic", "deterministic-scope"))
    second = svc.validate_canonical_mission(draft("deterministic", "deterministic-scope"))

    assert first["mission_request_sha256"] == second["mission_request_sha256"]
    assert first["scope_contract_request_sha256"] == second["scope_contract_request_sha256"]
    assert first["normalized"] == second["normalized"]


def test_canonical_contract_read_projection_is_local_and_becomes_scope_bound(tmp_path):
    svc, gov, cti = make_service(tmp_path / "missions.db")
    mission_id = svc.create_mission(mission_payload("contract-read"))["canonical_identity"]["mission_id"]

    initial = svc.get_canonical_mission_contract(mission_id)
    assert initial["schema_version"] == CANONICAL_MISSION_API_SCHEMA_VERSION
    assert initial["contract_status"] == "IDENTITY_STATE_ONLY"
    assert initial["contract_complete"] is False
    assert initial["mission_state"]["state"] == "CREATED"
    assert initial["scope_contract"] is None

    scope = svc.put_mission_scope_contract(mission_id, scope_payload("contract-read-scope"))
    bound = svc.get_canonical_mission_contract(mission_id)
    assert bound["contract_status"] == "SCOPE_BOUND"
    assert bound["contract_complete"] is True
    assert bound["scope_snapshot_id"] == scope["snapshot_id"]
    assert bound["scope_contract_version"] == 1
    assert bound["scope_contract"]["identity"]["mission_id"] == mission_id
    assert bound["external_authority_query_performed"] is False
    assert bound["target_action_dispatch_enabled"] is False
    assert bound["target_actuation"] is False
    assert gov.calls == 0
    assert cti.calls == 0
