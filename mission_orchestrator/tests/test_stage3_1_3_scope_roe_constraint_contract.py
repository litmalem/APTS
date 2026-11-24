from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionScopeContractConflict,
    MissionScopeContractNotFound,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.scope_contract import CONTRACT_HASH_DOMAIN, verify_contract
from mission_orchestrator.service import CanonicalMissionService


def mission_payload(key: str = "stage313-mission"):
    return {
        "idempotency_key": key,
        "source_system": "OPERATOR_API",
        "created_by": "stage3.1.3-test",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab-target-01"},
        "success_criteria": [{"metric": "authorized_goal_complete", "expected": True}],
        "budgets": {"time_seconds": 1800, "max_actions": 20, "risk_ceiling": "MEDIUM"},
        "required_subsystems": ["CTI", "PENTEST"],
        # Stage-3.1.1 compatibility reference. Stage 3.1.3 does not mutate it.
        "scope_contract_id": "scope-legacy-reference",
        "scope_version": 1,
        "roe_version": "1",
        "policy_version": "1",
        "metadata": {"environment": "LAB"},
    }


def contract_payload(key: str = "scope-op-1", expected: int = 0):
    return {
        "expected_contract_version": expected,
        "idempotency_key": key,
        "actor": "stage3.1.3-test",
        "scope": {
            "targets": [
                {
                    "target_type": "CIDR",
                    "target_value": "127.0.0.0/8",
                    "environment": "LAB",
                }
            ],
            "excluded_targets": [
                {
                    "target_type": "IP",
                    "target_value": "127.0.0.254",
                    "environment": "LAB",
                }
            ],
            "network_ranges": ["127.0.0.0/8"],
            "domains": ["lab.example.test"],
            "services": [
                {"name": "https", "protocol": "TCP", "port": 443, "target_ref": "lab.example.test"}
            ],
        },
        "roe": {
            "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION", "CREDENTIAL_USE"],
            "allowed_time_window": {
                "start_at": "2026-09-02T00:00:00Z",
                "end_at": "2026-09-03T00:00:00Z",
            },
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": ["VULNERABILITY_VALIDATION"],
        },
        "constraints": {
            "max_actions": 20,
            "max_duration": 1800,
            "risk_threshold": "MODERATE",
            "resource_budget": {"max_network_requests": 500, "max_parallel_targets": 2},
            "data_handling_policy": {
                "classification": "INTERNAL",
                "retention_days": 7,
                "export_allowed": False,
            },
        },
        "reason": "Initial authorized laboratory mission boundary",
        "metadata": {"environment": "LAB", "purpose": "acceptance"},
    }


def service(tmp_path: Path):
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo)


def create_mission(svc: CanonicalMissionService, key: str = "stage313-mission") -> str:
    return svc.create_mission(mission_payload(key))["canonical_identity"]["mission_id"]


def test_initial_contract_is_canonical_hashed_and_versioned(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc)
    result = svc.put_mission_scope_contract(mission_id, contract_payload())

    assert result["status"] == "contracted"
    assert result["idempotent_replay"] is False
    assert result["contract_version"] == 1
    assert result["mission_scope_contract_id"].startswith("mscope-")
    assert result["snapshot_id"].startswith("mscope-snap-")
    assert result["contract"]["identity"]["mission_id"] == mission_id
    assert result["contract"]["integrity"]["hash_domain"] == CONTRACT_HASH_DOMAIN
    assert result["contract"]["scope"]["network_ranges"] == ["127.0.0.0/8"]
    assert result["contract"]["roe"]["destructive_actions_allowed"] is False
    assert result["contract"]["constraints"]["risk_threshold"] == "MODERATE"
    assert verify_contract(result["contract"])


def test_identical_contract_retry_is_idempotent(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-replay-mission")
    payload = contract_payload("stage313-replay", 0)
    first = svc.put_mission_scope_contract(mission_id, payload)
    second = svc.put_mission_scope_contract(mission_id, payload)

    assert second["idempotent_replay"] is True
    assert second["mission_scope_contract_id"] == first["mission_scope_contract_id"]
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]


def test_contract_idempotency_key_cannot_alias_different_request(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-idem-conflict-mission")
    svc.put_mission_scope_contract(mission_id, contract_payload("same-key", 0))
    changed = contract_payload("same-key", 0)
    changed["constraints"]["max_actions"] = 99
    with pytest.raises(MissionScopeContractConflict, match="idempotency_key"):
        svc.put_mission_scope_contract(mission_id, changed)


def test_stale_expected_contract_version_is_rejected(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-stale-mission")
    svc.put_mission_scope_contract(mission_id, contract_payload("v1", 0))
    with pytest.raises(MissionScopeContractConflict, match="expected_contract_version"):
        svc.put_mission_scope_contract(mission_id, contract_payload("stale", 0))


def test_revision_is_append_only_and_preserves_contract_identity(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-revision-mission")
    first = svc.put_mission_scope_contract(mission_id, contract_payload("v1", 0))

    revised = contract_payload("v2", 1)
    revised["constraints"]["max_actions"] = 10
    revised["roe"]["maximum_concurrency"] = 1
    revised["reason"] = "Narrowed boundary after pre-mission review"
    second = svc.put_mission_scope_contract(mission_id, revised)

    history = svc.get_mission_scope_contract_history(mission_id)
    current = svc.get_mission_scope_contract(mission_id)

    assert second["contract_version"] == 2
    assert second["mission_scope_contract_id"] == first["mission_scope_contract_id"]
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["canonical_sha256"] != first["canonical_sha256"]
    assert history["version_count"] == 2
    assert [item["contract_version"] for item in history["versions"]] == [1, 2]
    assert history["versions"][0]["canonical_sha256"] == first["canonical_sha256"]
    assert history["versions"][0]["contract"]["constraints"]["max_actions"] == 20
    assert current["contract_version"] == 2
    assert current["contract"]["constraints"]["max_actions"] == 10


def test_action_class_cannot_be_both_allowed_and_prohibited(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-overlap-mission")
    bad = contract_payload("overlap", 0)
    bad["roe"]["prohibited_action_classes"].append("TARGET_RECON")
    with pytest.raises(MissionValidationError, match="both allowed and prohibited"):
        svc.put_mission_scope_contract(mission_id, bad)


def test_hard_safety_flags_cannot_contradict_allowed_actions(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-hard-deny-mission")

    destructive = contract_payload("destructive", 0)
    destructive["roe"]["allowed_action_classes"].append("DESTRUCTIVE_ACTION")
    destructive["roe"]["prohibited_action_classes"].remove("DESTRUCTIVE_ACTION")
    with pytest.raises(MissionValidationError, match="DESTRUCTIVE_ACTION"):
        svc.put_mission_scope_contract(mission_id, destructive)

    credential = contract_payload("credential", 0)
    credential["roe"]["allowed_action_classes"].append("CREDENTIAL_USE")
    credential["roe"]["prohibited_action_classes"].remove("CREDENTIAL_USE")
    with pytest.raises(MissionValidationError, match="CREDENTIAL_USE"):
        svc.put_mission_scope_contract(mission_id, credential)


def test_human_approval_set_must_be_subset_of_allowed_actions(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-approval-mission")
    bad = contract_payload("approval", 0)
    bad["roe"]["human_approval_required_for"].append("CONTROLLED_EXPLOITATION")
    with pytest.raises(MissionValidationError, match="subset"):
        svc.put_mission_scope_contract(mission_id, bad)


def test_scope_and_time_semantics_are_validated_before_persistence(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-semantic-mission")

    bad_cidr = contract_payload("bad-cidr", 0)
    bad_cidr["scope"]["network_ranges"] = ["999.999.0.0/16"]
    with pytest.raises(MissionValidationError, match="invalid CIDR"):
        svc.put_mission_scope_contract(mission_id, bad_cidr)

    bad_window = contract_payload("bad-window", 0)
    bad_window["roe"]["allowed_time_window"] = {
        "start_at": "2026-09-03T00:00:00Z",
        "end_at": "2026-09-02T00:00:00Z",
    }
    with pytest.raises(MissionValidationError, match="later than start_at"):
        svc.put_mission_scope_contract(mission_id, bad_window)

    assert svc.get_mission_scope_contract_history(mission_id)["version_count"] == 0


def test_missing_scope_contract_is_distinct_from_missing_mission(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-missing-contract")
    with pytest.raises(MissionScopeContractNotFound):
        svc.get_mission_scope_contract(mission_id)
    history = svc.get_mission_scope_contract_history(mission_id)
    assert history["current_contract_version"] == 0
    assert history["versions"] == []


def test_repository_reopen_preserves_contract_and_history(tmp_path):
    db = tmp_path / "persistent.db"
    first_service = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    mission_id = create_mission(first_service, "stage313-persist-mission")
    first = first_service.put_mission_scope_contract(mission_id, contract_payload("persist-v1", 0))

    second_service = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    current = second_service.get_mission_scope_contract(mission_id)
    history = second_service.get_mission_scope_contract_history(mission_id)
    assert current["canonical_sha256"] == first["canonical_sha256"]
    assert history["version_count"] == 1
    assert verify_contract(current["contract"])


def test_scope_contract_does_not_mutate_stage311_envelope(tmp_path):
    svc = service(tmp_path)
    mission_id = create_mission(svc, "stage313-envelope-mission")
    original = svc.get_envelope(mission_id)["envelope"]
    original_hash = original["integrity"]["canonical_sha256"]

    svc.put_mission_scope_contract(mission_id, contract_payload("envelope-v1", 0))
    revised = contract_payload("envelope-v2", 1)
    revised["constraints"]["max_actions"] = 5
    svc.put_mission_scope_contract(mission_id, revised)

    after = svc.get_envelope(mission_id)["envelope"]
    assert after == original
    assert after["integrity"]["canonical_sha256"] == original_hash


def test_health_declares_canonical_contract_authority_but_not_execution_authority(tmp_path):
    health = service(tmp_path).health()
    # Stage 3.1.3 remains a supported control after Stage 3.1.4 becomes current.
    assert "stage3.1.3-mission-scope-roe-constraint-contract" in health["supported_controls"]
    assert health["mission_scope_contract_mode"] == "IMMUTABLE_VERSIONED_HASHED_APPEND_ONLY"
    assert health["scope_contract_authority"] == "GLOBAL_MISSION_ORCHESTRATOR_CANONICAL_DEFINITION"
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["governance_binding_enabled"] is True
    assert health["dispatch_enabled"] is False
    assert health["target_actuation"] is False
