from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.delegation_recovery import ACTION_FREEZE_OWNERSHIP_CONFLICT
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionDelegationDeliveryNotFound,
    MissionExecutionDispatchConflict,
    MissionExecutionDispatchGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.execution_dispatch import (
    EXECUTION_AUTHORIZATION_STATUS,
    EXECUTION_DISPATCH_CONTRACT_SCHEMA_VERSION,
    EXECUTION_DISPATCH_ID_PREFIX,
    EXECUTION_DISPATCH_MODE,
    EXECUTION_DISPATCH_STATUS,
    canonical_execution_dispatch_definition,
    verify_execution_dispatch_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_4_7_delegation_delivery_acknowledgement_ownership import make_service
from tests.test_stage3_4_8_retry_fallback_reassignment_conflict_control import provision_owned, recovery_request

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR_CONTROL = "stage3.5.1-canonical-execution-dispatch-contract-identity"


def provision_running_owned(service, key: str):
    mission_id, active, route, authorization, delegation, delivery = provision_owned(service, key)
    execute(service, mission_id, "START", f"stage351-start-{key}")
    return mission_id, active, route, authorization, delegation, delivery


def dispatch_request(service, mission_id: str, active: dict, delivery: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage351-dispatch-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_delivery_receipt_id": delivery["delivery_receipt_id"],
        "expected_delivery_receipt_sha256": delivery["canonical_sha256"],
        "planned_task_id": delivery["planned_task_id"],
        "created_by": "stage3.5.1-pytest",
        "reason": "Materialize canonical execution dispatch identity only; do not dispatch or execute",
        "metadata": {"stage": "3.5.1", "key": key},
    }
    body.update(overrides)
    return body


def materialize(service, key: str):
    mission_id, active, route, authorization, delegation, delivery = provision_running_owned(service, key)
    result = service.create_execution_dispatch_contract(
        mission_id, dispatch_request(service, mission_id, active, delivery, key)
    )
    return mission_id, active, route, authorization, delegation, delivery, result


def test_01_health_activates_stage351_and_preserves_stage3410_as_predecessor(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][40:50] == [PREDECESSOR_CONTROL, "stage3.5.2-dispatch-eligibility-execution-preconditions", "stage3.5.3-authoritative-pre-dispatch-governance-revalidation", "stage3.5.4-idempotent-dispatch-execution-attempt-identity", "stage3.5.5-dispatch-delivery-execution-acknowledgement", "stage3.5.6-running-execution-state-heartbeat-projection", "stage3.5.7-execution-result-evidence-artifact-capture", "stage3.5.8-timeout-cancellation-abort-failure-propagation", "stage3.5.9-execution-event-lineage-replay-recovery", "stage3.5.10-execution-dispatch-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["execution_dispatch_contract_schema_version"] == EXECUTION_DISPATCH_CONTRACT_SCHEMA_VERSION
    assert health["execution_dispatch_contract_mode"] == EXECUTION_DISPATCH_MODE
    assert health["execution_dispatch_contract_status"] == EXECUTION_DISPATCH_STATUS
    assert health["execution_dispatch_contract_identity_prefix"] == EXECUTION_DISPATCH_ID_PREFIX
    assert health["execution_dispatch_persistence_store"] == "mission_execution_dispatch_contracts"
    assert "mission_execution_dispatch_contracts" in REPOSITORY_STORES
    assert health["execution_dispatch_pre_dispatch_governance_revalidation_required"] is True
    assert health["execution_dispatch_dispatch_performed"] is False
    assert health["execution_dispatch_target_actuation"] is False


def test_02_definition_is_identity_only_and_requires_later_governance_revalidation(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_ = provision_owned(service, "definition")
    result = service.get_execution_dispatch_definition(mission_id)
    definition = result["execution_dispatch_contract_definition"]
    assert definition == canonical_execution_dispatch_definition()
    assert definition["allowed_source_states"] == ["RUNNING"]
    assert definition["execution_authorization_status"] == EXECUTION_AUTHORIZATION_STATUS
    assert definition["ownership_is_execution_authority"] is False
    assert definition["dispatch_contract_is_dispatch"] is False
    assert definition["dispatch_identity_is_execution_authorization"] is False
    assert definition["pre_dispatch_governance_revalidation_required"] is True
    assert definition["governance_query_performed"] is False
    assert definition["dispatch_performed"] is False
    assert definition["target_actuation"] is False


def test_03_materializes_immutable_xdispatch_bound_to_owned_handoff(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization, delegation, delivery, result = materialize(service, "happy")
    assert result["execution_dispatch_id"].startswith(EXECUTION_DISPATCH_ID_PREFIX)
    assert result["dispatch_status"] == EXECUTION_DISPATCH_STATUS
    assert result["plan_version_record_id"] == active["plan_version_record_id"]
    assert result["planned_task_id"] == delivery["planned_task_id"]
    assert result["delivery_receipt_id"] == delivery["delivery_receipt_id"]
    assert result["delegation_id"] == delegation["delegation_id"]
    assert result["route_decision_id"] == route["route_decision_id"]
    assert result["delegation_authorization_id"] == authorization["delegation_authorization_id"]
    assert result["logical_target_only"] is True
    assert result["runtime_endpoint"] is None
    assert result["execution_authorized"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False
    contract = result["execution_dispatch_contract"]
    assert verify_execution_dispatch_contract(contract)
    assert contract["work_contract"]["work_context"] == delegation["handoff_envelope"]["work_context"]
    assert contract["dispatch_target"]["subsystem_id"] == delegation["handoff_envelope"]["recipient"]["subsystem_id"]


def test_04_planning_state_is_rejected_before_start(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_owned(service, "planning")
    with pytest.raises(MissionExecutionDispatchGuardRejected, match="RUNNING"):
        service.create_execution_dispatch_contract(
            mission_id, dispatch_request(service, mission_id, active, delivery, "planning")
        )


def test_05_stale_state_version_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "stale-state")
    body = dispatch_request(service, mission_id, active, delivery, "stale-state")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict, match="state_version"):
        service.create_execution_dispatch_contract(mission_id, body)


def test_06_stale_mission_version_vector_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "stale-vector")
    body = dispatch_request(service, mission_id, active, delivery, "stale-vector")
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        service.create_execution_dispatch_contract(mission_id, body)


def test_07_stale_active_plan_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "stale-plan")
    body = dispatch_request(service, mission_id, active, delivery, "stale-plan")
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active_plan_sha256"):
        service.create_execution_dispatch_contract(mission_id, body)


def test_08_unknown_delivery_receipt_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "unknown-receipt")
    body = dispatch_request(service, mission_id, active, delivery, "unknown-receipt")
    body["expected_delivery_receipt_id"] = "drecv-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionDelegationDeliveryNotFound):
        service.create_execution_dispatch_contract(mission_id, body)


def test_09_stale_delivery_receipt_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "stale-receipt")
    body = dispatch_request(service, mission_id, active, delivery, "stale-receipt")
    body["expected_delivery_receipt_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="delivery_receipt_sha256"):
        service.create_execution_dispatch_contract(mission_id, body)


def test_10_runtime_endpoint_is_forbidden_caller_input(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "endpoint")
    body = dispatch_request(service, mission_id, active, delivery, "endpoint", runtime_endpoint="http://worker")
    with pytest.raises(MissionValidationError, match="runtime endpoint"):
        service.create_execution_dispatch_contract(mission_id, body)


def test_11_execution_authority_and_dispatch_fields_are_forbidden(tmp_path):
    forbidden = [
        ("execution_payload", {"command": "run"}),
        ("execution_authorized", True),
        ("governance_decision", {"decision": "ALLOW"}),
        ("dispatch_performed", True),
        ("target_action", "execute"),
    ]
    for idx, (field, value) in enumerate(forbidden):
        service, _ = make_service(tmp_path / f"forbidden-{idx}.db")
        mission_id, active, _, _, _, delivery = provision_running_owned(service, f"forbidden-{idx}")
        body = dispatch_request(service, mission_id, active, delivery, f"forbidden-{idx}", **{field: value})
        with pytest.raises(MissionValidationError, match="unsupported execution dispatch-contract field"):
            service.create_execution_dispatch_contract(mission_id, body)


def test_12_same_request_is_idempotent_without_duplicate_contract_or_event(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "idem")
    body = dispatch_request(service, mission_id, active, delivery, "idem")
    first = service.create_execution_dispatch_contract(mission_id, body)
    replay = service.create_execution_dispatch_contract(mission_id, deepcopy(body))
    assert first["execution_dispatch_id"] == replay["execution_dispatch_id"]
    assert first["canonical_sha256"] == replay["canonical_sha256"]
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    history = service.get_execution_dispatch_history(mission_id)
    assert history["execution_dispatch_contract_count"] == 1
    events = service.get_mission_events(mission_id)["events"]
    dispatch_events = [e for e in events if e["event_type"] == "MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED"]
    assert len(dispatch_events) == 1


def test_13_same_idempotency_key_with_different_request_conflicts(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "idem-conflict")
    body = dispatch_request(service, mission_id, active, delivery, "idem-conflict")
    service.create_execution_dispatch_contract(mission_id, body)
    changed = deepcopy(body)
    changed["reason"] = "different canonical request"
    with pytest.raises(MissionExecutionDispatchConflict, match="idempotency_key"):
        service.create_execution_dispatch_contract(mission_id, changed)


def test_14_only_one_immutable_dispatch_identity_per_active_plan_task(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "single")
    service.create_execution_dispatch_contract(mission_id, dispatch_request(service, mission_id, active, delivery, "single-a"))
    second = dispatch_request(service, mission_id, active, delivery, "single-b")
    with pytest.raises(MissionExecutionDispatchConflict, match="already has an immutable"):
        service.create_execution_dispatch_contract(mission_id, second)


def test_15_materialization_does_not_query_governance_or_dispatch_network_action(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, delivery = provision_running_owned(service, "no-side-effect")
    before = gov.evaluate_calls
    result = service.create_execution_dispatch_contract(
        mission_id, dispatch_request(service, mission_id, active, delivery, "no-side-effect")
    )
    assert gov.evaluate_calls == before
    assert result["runtime_endpoint_resolution_performed"] is False
    assert result["runtime_health_probe_performed"] is False
    assert result["resource_assignment_performed"] is False
    assert result["execution_authorized"] is False
    assert result["dispatch_attempt_started"] is False
    assert result["dispatch_performed"] is False
    assert result["external_network_io_performed"] is False
    assert result["target_action_dispatch_enabled"] is False
    assert result["target_actuation"] is False


def test_16_conflict_frozen_stage348_ownership_fails_closed(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "frozen")
    service.control_task_delegation_recovery(
        mission_id,
        recovery_request(
            service, mission_id, active, route, delegation, delivery, "frozen",
            action=ACTION_FREEZE_OWNERSHIP_CONFLICT,
        ),
    )
    execute(service, mission_id, "START", "stage351-start-frozen")
    with pytest.raises(MissionExecutionDispatchGuardRejected, match="conflict-frozen"):
        service.create_execution_dispatch_contract(
            mission_id, dispatch_request(service, mission_id, active, delivery, "frozen")
        )


def test_17_repository_projection_persists_dispatch_store_and_lineage_event(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, _, _, _, _, _, result = materialize(service, "repository")
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    manifest = repo["persistence_manifest"]
    assert manifest["execution_dispatch_contract_store"]["contracts"]
    assert manifest["execution_dispatch_contract_store"]["contracts"][0]["execution_dispatch_id"] == result["execution_dispatch_id"]
    checks = {item["check"]: item for item in repo["integrity_checks"]}
    assert checks["canonical_execution_dispatch_contract_identity_store"]["status"] == "PASS"
    events = service.get_mission_events(mission_id)["events"]
    event = next(e for e in events if e["event_type"] == "MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED")
    assert event["causation_id"] == result["execution_dispatch_id"]
    assert event["payload"]["execution_dispatch_id"] == result["execution_dispatch_id"]
    assert event["payload"]["dispatch_performed"] is False
    assert event["payload"]["execution_authorization_performed"] is False


def test_18_persisted_dispatch_contract_tampering_breaks_repository_integrity(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, _, _, _, _, _, result = materialize(service, "tamper")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_execution_dispatch_contracts SET canonical_sha256=? WHERE execution_dispatch_id=?",
            ("0" * 64, result["execution_dispatch_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_19_api_routes_migration_and_history_get_are_registered(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, _, _, _, _, _, result = materialize(service, "api")
    fetched = service.get_execution_dispatch_contract(mission_id, result["execution_dispatch_id"])
    history = service.get_execution_dispatch_history(mission_id)
    assert fetched["canonical_sha256"] == result["canonical_sha256"]
    assert history["execution_dispatch_contract_count"] == 1
    api_source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "execution-dispatch-contracts" in api_source
    assert "execution-dispatch-contract-definition" in api_source
    migration = Path("migrations/027_stage3_5_1_canonical_execution_dispatch_contract_identity.sql")
    assert migration.is_file()
    migration_text = migration.read_text(encoding="utf-8")
    assert "mission_execution_dispatch_contracts" in migration_text
    assert "dispatch" in migration_text.lower()
