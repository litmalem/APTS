from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.dispatch_eligibility import (
    DISPATCH_ELIGIBILITY_AUTHORITY,
    DISPATCH_ELIGIBILITY_GATE_PASSED,
    DISPATCH_ELIGIBILITY_ID_PREFIX,
    DISPATCH_ELIGIBILITY_MODE,
    DISPATCH_ELIGIBILITY_SCHEMA_VERSION,
    DISPATCH_ELIGIBILITY_STATUS,
    EXECUTION_PRECONDITION_STATUS,
    canonical_dispatch_eligibility_definition,
    evaluate_dispatch_execution_preconditions,
    verify_dispatch_eligibility_contract,
)
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionDispatchEligibilityConflict,
    MissionDispatchEligibilityGuardRejected,
    MissionExecutionDispatchNotFound,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_5_1_canonical_execution_dispatch_contract_identity import make_service, materialize

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR = "stage3.5.1-canonical-execution-dispatch-contract-identity"


def eligibility_request(service, mission_id: str, active: dict, dispatch: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    readiness = service.get_active_task_readiness_projection(mission_id)
    body = {
        "idempotency_key": f"stage352-eligibility-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_execution_dispatch_id": dispatch["execution_dispatch_id"],
        "expected_execution_dispatch_sha256": dispatch["canonical_sha256"],
        "expected_task_readiness_projection_id": readiness["projection_id"],
        "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
        "created_by": "stage3.5.2-pytest",
        "reason": "Evaluate static dispatch eligibility and execution preconditions only",
        "metadata": {"stage": "3.5.2", "key": key},
    }
    body.update(overrides)
    return body


def materialize_gate(service, key: str):
    mission_id, active, route, authorization, delegation, delivery, dispatch = materialize(service, key)
    body = eligibility_request(service, mission_id, active, dispatch, key)
    gate = service.create_dispatch_eligibility_gate(mission_id, body)
    return mission_id, active, route, authorization, delegation, delivery, dispatch, gate, body


def test_01_health_activates_stage352_and_preserves_stage351_predecessor(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][40:50] == [PREDECESSOR, "stage3.5.2-dispatch-eligibility-execution-preconditions", "stage3.5.3-authoritative-pre-dispatch-governance-revalidation", "stage3.5.4-idempotent-dispatch-execution-attempt-identity", "stage3.5.5-dispatch-delivery-execution-acknowledgement", "stage3.5.6-running-execution-state-heartbeat-projection", "stage3.5.7-execution-result-evidence-artifact-capture", "stage3.5.8-timeout-cancellation-abort-failure-propagation", "stage3.5.9-execution-event-lineage-replay-recovery", "stage3.5.10-execution-dispatch-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["dispatch_eligibility_schema_version"] == DISPATCH_ELIGIBILITY_SCHEMA_VERSION
    assert health["dispatch_eligibility_mode"] == DISPATCH_ELIGIBILITY_MODE
    assert health["dispatch_eligibility_gate_result"] == DISPATCH_ELIGIBILITY_GATE_PASSED
    assert health["dispatch_eligibility_status"] == DISPATCH_ELIGIBILITY_STATUS
    assert health["dispatch_eligibility_execution_precondition_status"] == EXECUTION_PRECONDITION_STATUS
    assert health["dispatch_eligibility_authority"] == DISPATCH_ELIGIBILITY_AUTHORITY
    assert health["dispatch_eligibility_database_migration_level"] == 28
    assert health["dispatch_eligibility_persistence_store"] == "mission_execution_dispatch_eligibility_gates"
    assert "mission_execution_dispatch_eligibility_gates" in REPOSITORY_STORES


def test_02_definition_is_static_precondition_gate_not_execution_authority(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = materialize(service, "definition")
    definition = service.get_dispatch_eligibility_definition(mission_id)[
        "dispatch_eligibility_execution_preconditions_definition"
    ]
    assert definition == canonical_dispatch_eligibility_definition()
    assert definition["allowed_source_states"] == ["RUNNING"]
    assert definition["requires_stage351_execution_dispatch_contract"] is True
    assert definition["eligible_for_pre_dispatch_governance_revalidation"] is True
    assert definition["eligibility_is_execution_authorization"] is False
    assert definition["preconditions_are_execution_authorization"] is False
    assert definition["eligible_for_execution"] is False
    assert definition["governance_query_performed"] is False
    assert definition["runtime_endpoint_resolution_performed"] is False
    assert definition["dispatch_performed"] is False
    assert definition["target_actuation"] is False


def test_03_materializes_passed_xelig_with_all_preconditions_satisfied(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, _, dispatch, gate, _ = materialize_gate(service, "happy")
    assert gate["dispatch_eligibility_id"].startswith(DISPATCH_ELIGIBILITY_ID_PREFIX)
    assert gate["execution_dispatch_id"] == dispatch["execution_dispatch_id"]
    assert gate["plan_version_record_id"] == active["plan_version_record_id"]
    assert gate["gate_result"] == DISPATCH_ELIGIBILITY_GATE_PASSED
    assert gate["eligibility_status"] == DISPATCH_ELIGIBILITY_STATUS
    assert gate["execution_precondition_status"] == EXECUTION_PRECONDITION_STATUS
    assert gate["precondition_count"] == 25
    assert gate["satisfied_precondition_count"] == gate["precondition_count"]
    assert gate["failed_precondition_count"] == 0
    assert gate["failed_preconditions"] == []
    assert all(gate["checks"].values())
    assert verify_dispatch_eligibility_contract(gate["dispatch_eligibility_contract"])
    assert gate["eligible_for_pre_dispatch_governance_revalidation"] is True
    assert gate["eligible_for_execution"] is False
    assert gate["execution_authorized"] is False
    assert gate["dispatch_performed"] is False
    assert gate["target_actuation"] is False


def test_04_non_running_mission_is_rejected_after_stage351_materialization(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, _, _, dispatch = materialize(service, "state")
    body = eligibility_request(service, mission_id, active, dispatch, "state")
    # PAUSE changes the canonical state after Stage-3.5.1 materialization.
    execute(service, mission_id, "PAUSE", "stage352-pause-state")
    with pytest.raises(MissionDispatchEligibilityGuardRejected, match="RUNNING"):
        service.create_dispatch_eligibility_gate(mission_id, body)


def test_05_stale_state_version_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "stale-state")
    body = eligibility_request(service, mission_id, active, dispatch, "stale-state")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict, match="state_version"):
        service.create_dispatch_eligibility_gate(mission_id, body)


def test_06_stale_version_vector_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "stale-vector")
    body = eligibility_request(service, mission_id, active, dispatch, "stale-vector")
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        service.create_dispatch_eligibility_gate(mission_id, body)


def test_07_stale_active_plan_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "stale-plan")
    body = eligibility_request(service, mission_id, active, dispatch, "stale-plan")
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active_plan_sha256"):
        service.create_dispatch_eligibility_gate(mission_id, body)


def test_08_unknown_stage351_execution_dispatch_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "unknown-dispatch")
    body = eligibility_request(service, mission_id, active, dispatch, "unknown-dispatch")
    body["expected_execution_dispatch_id"] = "xdispatch-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionExecutionDispatchNotFound):
        service.create_dispatch_eligibility_gate(mission_id, body)


def test_09_stale_stage351_execution_dispatch_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "stale-dispatch")
    body = eligibility_request(service, mission_id, active, dispatch, "stale-dispatch")
    body["expected_execution_dispatch_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="execution_dispatch_sha256"):
        service.create_dispatch_eligibility_gate(mission_id, body)


def test_10_stale_readiness_projection_hash_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "stale-readiness")
    body = eligibility_request(service, mission_id, active, dispatch, "stale-readiness")
    body["expected_task_readiness_projection_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="readiness_projection_sha256"):
        service.create_dispatch_eligibility_gate(mission_id, body)


def test_11_caller_cannot_supply_authority_runtime_or_dispatch_results(tmp_path):
    forbidden = [
        ("eligibility_status", "ELIGIBLE"),
        ("execution_authorized", True),
        ("governance_decision", {"decision": "ALLOW"}),
        ("runtime_endpoint", "http://worker"),
        ("health_result", {"status": "ok"}),
        ("resource_assignment", {"worker": "x"}),
        ("dispatch_performed", True),
        ("target_action", "execute"),
    ]
    service, _ = make_service(tmp_path / "forbidden.db")
    mission_id, active, *_, dispatch = materialize(service, "forbidden")
    for idx, (field, value) in enumerate(forbidden):
        body = eligibility_request(service, mission_id, active, dispatch, f"forbidden-{idx}", **{field: value})
        with pytest.raises(MissionValidationError, match="unsupported dispatch eligibility field"):
            service.create_dispatch_eligibility_gate(mission_id, body)


def test_12_same_request_is_idempotent_without_duplicate_gate_or_event(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "idem")
    body = eligibility_request(service, mission_id, active, dispatch, "idem")
    first = service.create_dispatch_eligibility_gate(mission_id, body)
    replay = service.create_dispatch_eligibility_gate(mission_id, deepcopy(body))
    assert first["dispatch_eligibility_id"] == replay["dispatch_eligibility_id"]
    assert first["canonical_sha256"] == replay["canonical_sha256"]
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    history = service.get_dispatch_eligibility_history(mission_id)
    assert history["dispatch_eligibility_gate_count"] == 1
    events = service.get_mission_events(mission_id)["events"]
    stage352_events = [e for e in events if e["event_type"] == "MISSION_DISPATCH_ELIGIBILITY_PRECONDITIONS_SATISFIED"]
    assert len(stage352_events) == 1


def test_13_same_idempotency_key_with_different_request_conflicts(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "idem-conflict")
    body = eligibility_request(service, mission_id, active, dispatch, "idem-conflict")
    service.create_dispatch_eligibility_gate(mission_id, body)
    changed = deepcopy(body)
    changed["reason"] = "different canonical request"
    with pytest.raises(MissionDispatchEligibilityConflict, match="idempotency_key"):
        service.create_dispatch_eligibility_gate(mission_id, changed)


def test_14_only_one_immutable_gate_per_stage351_dispatch(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "single")
    service.create_dispatch_eligibility_gate(mission_id, eligibility_request(service, mission_id, active, dispatch, "single-a"))
    with pytest.raises(MissionDispatchEligibilityConflict, match="already has an immutable"):
        service.create_dispatch_eligibility_gate(
            mission_id, eligibility_request(service, mission_id, active, dispatch, "single-b")
        )


def test_15_gate_does_not_call_governance_or_perform_runtime_side_effects(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "no-side-effects")
    before = gov.evaluate_calls
    result = service.create_dispatch_eligibility_gate(
        mission_id, eligibility_request(service, mission_id, active, dispatch, "no-side-effects")
    )
    assert gov.evaluate_calls == before
    for field in (
        "governance_query_performed",
        "runtime_endpoint_resolution_performed",
        "runtime_health_probe_performed",
        "resource_assignment_performed",
        "execution_authorization_performed",
        "execution_authorized",
        "dispatch_attempt_started",
        "dispatch_performed",
        "external_network_io_performed",
        "target_action_dispatch_enabled",
        "target_actuation",
        "eligible_for_execution",
    ):
        assert result[field] is False


def test_16_static_evaluator_fails_closed_when_target_capability_disabled(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, authorization, delegation, delivery, dispatch = materialize(service, "disabled")
    state = service.repository.get_state(mission_id)
    vector = service.get_mission_version_vector(mission_id)
    readiness = service.repository.get_task_readiness_projection_for_plan_version(mission_id, active["plan_version"])
    scope = service.repository.get_current_scope_contract(mission_id)
    governance = service.repository.get_current_governance_binding(mission_id)
    recovery = service.repository.list_delegation_recovery_controls(mission_id, delivery["delivery_receipt_id"])
    registry = deepcopy(service.repository.get_subsystem_registry_snapshot())
    target = dispatch["execution_dispatch_contract"]["dispatch_target"]
    capability = next(
        x for x in registry["capabilities"]
        if x["identity"]["subsystem_id"] == target["subsystem_id"]
        and x["identity"]["capability_id"] == target["capability_id"]
    )
    # Deliberate in-memory corruption should fail integrity and capability checks.
    capability["registration"]["enabled"] = False
    evaluation = evaluate_dispatch_execution_preconditions(
        state=state,
        version_vector=vector,
        active_plan=active,
        readiness_projection=readiness,
        execution_dispatch=service.repository.get_execution_dispatch_contract(mission_id, dispatch["execution_dispatch_id"]),
        delivery=service.repository.get_delegation_delivery(mission_id, delivery["delivery_receipt_id"]),
        delegation=service.repository.get_task_delegation(mission_id, delegation["delegation_id"]),
        route=service.repository.get_task_route_decision(mission_id, route["route_decision_id"]),
        delegation_authorization=service.repository.get_delegation_authorization(mission_id, authorization["delegation_authorization_id"]),
        scope_record=scope,
        governance_binding=governance,
        recovery_controls=recovery,
        registry_snapshot=registry,
    )
    assert evaluation["gate_result"] == "FAILED_CLOSED"
    assert evaluation["eligible_for_pre_dispatch_governance_revalidation"] is False
    assert evaluation["eligible_for_execution"] is False
    assert evaluation["failed_precondition_count"] >= 1


def test_17_repository_projection_persists_gate_and_lineage_event(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_, gate, _ = materialize_gate(service, "repository")
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    store = repo["persistence_manifest"]["dispatch_eligibility_execution_preconditions_store"]
    assert len(store["gates"]) == 1
    assert store["gates"][0]["dispatch_eligibility_id"] == gate["dispatch_eligibility_id"]
    checks = {item["check"]: item for item in repo["integrity_checks"]}
    assert checks["dispatch_eligibility_execution_preconditions_store"]["status"] == "PASS"
    events = service.get_mission_events(mission_id)["events"]
    event = next(e for e in events if e["event_type"] == "MISSION_DISPATCH_ELIGIBILITY_PRECONDITIONS_SATISFIED")
    assert event["causation_id"] == gate["dispatch_eligibility_id"]
    assert event["payload"]["gate_result"] == DISPATCH_ELIGIBILITY_GATE_PASSED
    assert event["payload"]["eligible_for_execution"] is False
    assert event["payload"]["dispatch_performed"] is False


def test_18_persisted_gate_tampering_breaks_repository_integrity(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, *_, gate, _ = materialize_gate(service, "tamper")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_execution_dispatch_eligibility_gates SET canonical_sha256=? WHERE dispatch_eligibility_id=?",
            ("0" * 64, gate["dispatch_eligibility_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_19_api_routes_migration_history_and_version_vector_boundary(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, *_, dispatch = materialize(service, "api")
    before = service.get_mission_version_vector(mission_id)["version_sha256"]
    gate = service.create_dispatch_eligibility_gate(
        mission_id, eligibility_request(service, mission_id, active, dispatch, "api")
    )
    after = service.get_mission_version_vector(mission_id)["version_sha256"]
    assert before == after
    fetched = service.get_dispatch_eligibility_gate(mission_id, gate["dispatch_eligibility_id"])
    history = service.get_dispatch_eligibility_history(mission_id)
    assert fetched["canonical_sha256"] == gate["canonical_sha256"]
    assert history["dispatch_eligibility_gate_count"] == 1
    api_source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "dispatch-eligibility-gates" in api_source
    assert "dispatch-eligibility-definition" in api_source
    migration = Path("migrations/028_stage3_5_2_dispatch_eligibility_execution_preconditions.sql")
    assert migration.is_file()
    text = migration.read_text(encoding="utf-8")
    assert "mission_execution_dispatch_eligibility_gates" in text
    assert "does NOT authorize execution" in text
