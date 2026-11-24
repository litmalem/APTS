from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_orchestrator.canonical import HASH_DOMAIN, canonical_json, sha256_hex, verify_envelope
from mission_orchestrator.errors import MissionIdempotencyConflict, MissionValidationError
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


def payload(key="stage311-001"):
    return {
        "idempotency_key": key,
        "source_system": "OPERATOR_API",
        "created_by": "acceptance-runner",
        "client_request_id": f"client-{key}",
        "client_mission_ref": f"legacy-{key}",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "lab-target-01"},
        "success_criteria": [{"metric": "authorized_goal_complete", "expected": True}],
        "budgets": {"time_seconds": 1800, "max_actions": 20, "risk_ceiling": "MEDIUM"},
        "required_subsystems": ["cti", "pentest", "cti"],
        "scope_contract_id": "scope-stage311-001",
        "scope_version": 1,
        "roe_version": "1",
        "pip_id": "pip-stage311-001",
        "pip_version": "1",
        "policy_version": "1",
        "metadata": {"environment": "LAB"},
    }


def service(tmp_path: Path):
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo)


def test_create_assigns_authoritative_identity_and_envelope(tmp_path):
    result = service(tmp_path).create_mission(payload())
    identity = result["canonical_identity"]
    assert result["status"] == "registered"
    assert result["idempotent_replay"] is False
    assert identity["mission_id"].startswith("mission-gmo-")
    assert identity["envelope_id"].startswith("menv-")
    assert identity["envelope_version"] == 1
    assert result["envelope"]["identity"]["mission_id"] == identity["mission_id"]
    assert result["envelope"]["mission"]["required_subsystems"] == ["CTI", "PENTEST"]
    assert result["envelope"]["bindings"]["scope"]["scope_snapshot_id"] == "scope-stage311-001@v1"
    assert verify_envelope(result["envelope"])


def test_integrity_hash_has_explicit_domain_and_is_recomputable(tmp_path):
    result = service(tmp_path).create_mission(payload("stage311-hash"))
    envelope = result["envelope"]
    integrity = envelope["integrity"]
    core = dict(envelope)
    core.pop("integrity")
    expected = sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})
    assert integrity["hash_domain"] == HASH_DOMAIN
    assert integrity["canonical_sha256"] == expected
    assert len(expected) == 64


def test_identical_retry_is_idempotent_and_preserves_identity(tmp_path):
    svc = service(tmp_path)
    first = svc.create_mission(payload("stage311-replay"))
    second = svc.create_mission(payload("stage311-replay"))
    assert second["idempotent_replay"] is True
    assert second["canonical_identity"] == first["canonical_identity"]
    assert second["envelope"] == first["envelope"]


def test_idempotency_key_cannot_alias_different_mission_contract(tmp_path):
    svc = service(tmp_path)
    original = payload("stage311-conflict")
    svc.create_mission(original)
    changed = payload("stage311-conflict")
    changed["objective"] = {"type": "SECURITY_VALIDATION", "target_ref": "different-target"}
    with pytest.raises(MissionIdempotencyConflict):
        svc.create_mission(changed)


def test_reopen_repository_preserves_canonical_identity(tmp_path):
    db = tmp_path / "persistent.db"
    first_service = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    created = first_service.create_mission(payload("stage311-persist"))
    mission_id = created["canonical_identity"]["mission_id"]

    second_service = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)))
    mission = second_service.get_mission(mission_id)
    envelope = second_service.get_envelope(mission_id)
    assert mission["mission"]["mission_id"] == mission_id
    assert envelope["envelope"] == created["envelope"]


def test_unknown_top_level_fields_are_rejected_not_silently_accepted(tmp_path):
    bad = payload("stage311-unknown")
    bad["uncontrolled_execution"] = True
    with pytest.raises(MissionValidationError, match="unsupported top-level"):
        service(tmp_path).create_mission(bad)


def test_authority_boundary_is_identity_only_no_dispatch_or_actuation(tmp_path):
    health = service(tmp_path).health()
    assert health["mission_identity_authority"] == "GLOBAL_MISSION_ORCHESTRATOR"
    assert health["dispatch_enabled"] is False
    assert health["target_actuation"] is False
    assert not hasattr(service(tmp_path), "dispatch_task")
