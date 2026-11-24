from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskOutcomeConflict,
    MissionTaskOutcomeGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_outcome import (
    TASK_OUTCOME_AUTHORITY,
    TASK_OUTCOME_CONTRACT_SCHEMA_VERSION,
    TASK_OUTCOME_CONTRACT_STATUS,
    TASK_OUTCOME_ID_PREFIX,
    TASK_OUTCOME_MODE,
    TASK_OUTCOME_STAGE_SCHEMA_VERSION,
    verify_task_outcome_contract,
)
from tests.test_stage3_5_10_execution_dispatch_acceptance_regression_gate import close_success


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE361 = "stage3.6.1-canonical-task-outcome-contract-identity"


def provision_closed(tmp_path: Path, key: str):
    return close_success(tmp_path, key)


def outcome_request(service, mission_id, active, attempt, result, propagation, checkpoint, key: str, **extra):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"task-outcome-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_execution_attempt_id": attempt["execution_attempt_id"],
        "expected_execution_attempt_sha256": attempt["canonical_sha256"],
        "expected_result_capture_id": result["result_capture_id"],
        "expected_result_capture_sha256": result["canonical_sha256"],
        "expected_outcome_propagation_id": propagation["outcome_propagation_id"],
        "expected_outcome_propagation_sha256": propagation["canonical_sha256"],
        "expected_execution_recovery_checkpoint_id": checkpoint["checkpoint_id"],
        "expected_execution_recovery_checkpoint_sha256": checkpoint["canonical_sha256"],
        "created_by": "stage3.6.1-pytest",
        "reason": "materialize immutable canonical task outcome identity",
        "metadata": {"stage": "3.6.1", "key": key},
    }
    body.update(extra)
    return body


def materialize(tmp_path: Path, key: str):
    service, governance, runtime, mission_id, active, attempt, delivery, running, result, propagation, checkpoint = provision_closed(
        tmp_path, key
    )
    body = outcome_request(service, mission_id, active, attempt, result, propagation, checkpoint, key)
    created = service.create_task_outcome(mission_id, body)
    return service, governance, runtime, mission_id, active, attempt, delivery, running, result, propagation, checkpoint, body, created


@pytest.fixture(scope="module")
def closed_context(tmp_path_factory):
    root = tmp_path_factory.mktemp("stage361-closed")
    service, governance, runtime, mission_id, active, attempt, delivery, running, result, propagation, checkpoint = provision_closed(
        root, "shared-closed361"
    )
    body = outcome_request(service, mission_id, active, attempt, result, propagation, checkpoint, "shared-closed361")
    return {
        "root": root, "service": service, "governance": governance, "runtime": runtime, "mission_id": mission_id,
        "active": active, "attempt": attempt, "delivery": delivery, "running": running, "result": result,
        "propagation": propagation, "checkpoint": checkpoint, "body": body,
    }


@pytest.fixture(scope="module")
def materialized_context(tmp_path_factory):
    root = tmp_path_factory.mktemp("stage361-materialized")
    service, governance, runtime, mission_id, active, attempt, delivery, running, result, propagation, checkpoint = provision_closed(
        root, "shared-materialized361"
    )
    body = outcome_request(service, mission_id, active, attempt, result, propagation, checkpoint, "shared-materialized361")
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    created = service.create_task_outcome(mission_id, body)
    gov_after = governance.evaluate_calls
    runtime_after = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    return {
        "root": root, "service": service, "governance": governance, "runtime": runtime, "mission_id": mission_id,
        "active": active, "attempt": attempt, "delivery": delivery, "running": running, "result": result,
        "propagation": propagation, "checkpoint": checkpoint, "body": body, "created": created,
        "gov_before": gov_before, "gov_after": gov_after, "runtime_before": runtime_before, "runtime_after": runtime_after,
    }


def test_01_health_activates_stage361_and_migration36(closed_context):
    service = closed_context["service"]
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == ["stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_task_outcomes" in REPOSITORY_STORES
    assert health["task_outcome_stage_schema_version"] == TASK_OUTCOME_STAGE_SCHEMA_VERSION
    assert health["task_outcome_contract_schema_version"] == TASK_OUTCOME_CONTRACT_SCHEMA_VERSION
    assert health["task_outcome_identity_prefix"] == TASK_OUTCOME_ID_PREFIX
    assert health["task_outcome_mode"] == TASK_OUTCOME_MODE
    assert health["task_outcome_authority"] == TASK_OUTCOME_AUTHORITY
    assert health["task_outcome_database_migration_level"] == 36
    assert health["task_outcome_persistence_store"] == "mission_task_outcomes"


def test_02_definition_closes_identity_scope_and_reserves_acceptance_for_362(closed_context):
    service, mission_id = closed_context["service"], closed_context["mission_id"]
    definition = service.get_task_outcome_definition(mission_id)["task_outcome_definition"]
    assert definition["schema_version"] == TASK_OUTCOME_CONTRACT_SCHEMA_VERSION
    assert definition["contract_status"] == TASK_OUTCOME_CONTRACT_STATUS
    assert definition["requires_stage3510_closed_runtime_release"] is True
    assert definition["requires_stage359_execution_recovery_checkpoint"] is True
    assert definition["one_task_outcome_identity_per_plan_task"] is True
    assert definition["task_outcome_acceptance_performed"] is False
    assert definition["acceptance_criteria_evaluation_performed"] is False
    assert definition["task_completion_commit_performed"] is False
    assert definition["dependency_release_performed"] is False
    assert definition["mission_success_completion_authority_exercised"] is False
    assert definition["next_stage"] == "3.6.2"


def test_03_success_trajectory_materializes_immutable_task_outcome_identity(materialized_context):
    created = materialized_context["created"]
    assert created["task_outcome_id"].startswith(TASK_OUTCOME_ID_PREFIX)
    assert created["contract_status"] == TASK_OUTCOME_CONTRACT_STATUS
    assert created["execution_state"] == "SUCCEEDED"
    assert created["source_task_outcome_status"] == "VERIFIED_COMPLETED"
    assert created["outcome_classification"] == "VERIFIED_SUCCESS"
    assert created["task_outcome_identity_materialized"] is True
    assert verify_task_outcome_contract(created["task_outcome_contract"])


def test_04_contract_binds_exact_stage35_terminal_trajectory(materialized_context):
    mission_id = materialized_context["mission_id"]
    active = materialized_context["active"]
    attempt = materialized_context["attempt"]
    result = materialized_context["result"]
    propagation = materialized_context["propagation"]
    checkpoint = materialized_context["checkpoint"]
    created = materialized_context["created"]
    contract = created["task_outcome_contract"]
    identity = contract["identity"]
    source = contract["source_bindings"]
    assert identity["mission_id"] == mission_id
    assert identity["plan_version_record_id"] == active["plan_version_record_id"]
    assert identity["execution_attempt_id"] == attempt["execution_attempt_id"]
    assert identity["result_capture_id"] == result["result_capture_id"]
    assert identity["outcome_propagation_id"] == propagation["outcome_propagation_id"]
    assert identity["execution_recovery_checkpoint_id"] == checkpoint["checkpoint_id"]
    assert source["execution_attempt_sha256"] == attempt["canonical_sha256"]
    assert source["result_capture_sha256"] == result["canonical_sha256"]
    assert source["outcome_propagation_sha256"] == propagation["canonical_sha256"]
    assert source["execution_recovery_checkpoint_sha256"] == checkpoint["canonical_sha256"]


def test_05_materialization_does_not_accept_complete_release_or_advance(materialized_context):
    created = materialized_context["created"]
    outcome = created["task_outcome_contract"]["task_outcome"]
    boundary = created["task_outcome_contract"]["authority_boundary"]
    for key in (
        "task_outcome_acceptance_performed",
        "acceptance_criteria_evaluation_performed",
        "task_completion_commit_performed",
        "task_state_transition_performed",
        "dependency_release_performed",
        "readiness_recalculation_performed",
        "plan_progression_performed",
        "mission_success_completion_authority_exercised",
    ):
        assert outcome[key] is False
    for key in (
        "governance_query_performed",
        "runtime_query_performed",
        "runtime_control_io_performed",
        "dispatch_redelivery_performed",
        "new_execution_attempt_created",
        "new_target_action_dispatch_performed",
        "external_network_io_performed",
        "target_actuation",
        "mission_state_transition_performed",
    ):
        assert boundary[key] is False


def test_06_stale_mission_version_vector_is_rejected(closed_context):
    service, mission_id = closed_context["service"], closed_context["mission_id"]
    body = deepcopy(closed_context["body"])
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        service.create_task_outcome(mission_id, body)


def test_07_stale_active_plan_hash_is_rejected(closed_context):
    service, mission_id = closed_context["service"], closed_context["mission_id"]
    body = deepcopy(closed_context["body"])
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        service.create_task_outcome(mission_id, body)


def test_08_stale_terminal_artifact_hash_is_rejected(closed_context):
    service, mission_id = closed_context["service"], closed_context["mission_id"]
    body = deepcopy(closed_context["body"])
    body["expected_result_capture_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="result capture SHA-256"):
        service.create_task_outcome(mission_id, body)


def test_09_missing_recovery_checkpoint_fails_closed(closed_context):
    service, mission_id = closed_context["service"], closed_context["mission_id"]
    body = deepcopy(closed_context["body"])
    body["expected_execution_recovery_checkpoint_id"] = "xrecover-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionTaskOutcomeGuardRejected, match="recovery checkpoint"):
        service.create_task_outcome(mission_id, body)


def test_10_caller_supplied_acceptance_completion_and_side_effect_fields_are_forbidden(closed_context):
    forbidden = [
        ("task_outcome_status", "VERIFIED_COMPLETED"),
        ("task_outcome_accepted", True),
        ("task_completed", True),
        ("dependency_release", True),
        ("mission_completed", True),
        ("runtime_action", "resume"),
        ("governance_decision", "ALLOW"),
    ]
    service, mission_id = closed_context["service"], closed_context["mission_id"]
    for idx, (field, value) in enumerate(forbidden):
        body = deepcopy(closed_context["body"])
        body["idempotency_key"] = f"task-outcome-forbidden361-{idx}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported task outcome materialization field"):
            service.create_task_outcome(mission_id, body)


def test_11_same_request_is_idempotent_without_duplicate_outcome_or_event(materialized_context):
    service, mission_id = materialized_context["service"], materialized_context["mission_id"]
    body = materialized_context["body"]
    first = materialized_context["created"]
    replay = service.create_task_outcome(mission_id, deepcopy(body))
    assert first["task_outcome_id"] == replay["task_outcome_id"]
    assert first["canonical_sha256"] == replay["canonical_sha256"]
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert service.get_task_outcome_history(mission_id)["task_outcome_count"] == 1
    events = service.get_mission_events(mission_id)["events"]
    assert len([e for e in events if e["event_type"] == "MISSION_TASK_OUTCOME_MATERIALIZED"]) == 1


def test_12_same_idempotency_key_with_different_request_conflicts(materialized_context):
    service, mission_id = materialized_context["service"], materialized_context["mission_id"]
    body = materialized_context["body"]
    changed = deepcopy(body)
    changed["reason"] = "different canonical request"
    with pytest.raises(MissionTaskOutcomeConflict, match="idempotency_key"):
        service.create_task_outcome(mission_id, changed)


def test_13_only_one_immutable_outcome_identity_per_plan_task(materialized_context):
    service, mission_id = materialized_context["service"], materialized_context["mission_id"]
    second = deepcopy(materialized_context["body"])
    second["idempotency_key"] = "task-outcome-single361-b"
    second["reason"] = "second identity attempt for same plan task"
    with pytest.raises(MissionTaskOutcomeConflict, match="already has an immutable"):
        service.create_task_outcome(mission_id, second)


def test_14_materialization_and_replay_do_not_contact_runtime_or_governance(materialized_context):
    service = materialized_context["service"]
    governance = materialized_context["governance"]
    runtime = materialized_context["runtime"]
    mission_id = materialized_context["mission_id"]
    body = materialized_context["body"]
    first = materialized_context["created"]
    assert materialized_context["gov_after"] == materialized_context["gov_before"]
    assert materialized_context["runtime_after"] == materialized_context["runtime_before"]
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    replay = service.create_task_outcome(mission_id, deepcopy(body))
    assert governance.evaluate_calls == gov_before
    assert (runtime.health_calls, runtime.result_calls, runtime.control_calls) == runtime_before
    for result_obj in (first, replay):
        assert result_obj["governance_query_performed"] is False
        assert result_obj["runtime_query_performed"] is False
        assert result_obj["runtime_control_io_performed"] is False
        assert result_obj["external_network_io_performed"] is False
        assert result_obj["target_actuation"] is False


def test_15_restart_reads_same_immutable_task_outcome_from_durable_repository(materialized_context):
    service, mission_id, created = materialized_context["service"], materialized_context["mission_id"], materialized_context["created"]
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=service.repository.sqlite_path))
    fetched = restarted.get_task_outcome(mission_id, created["task_outcome_id"])
    assert fetched["task_outcome_id"] == created["task_outcome_id"]
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert verify_task_outcome_contract(fetched["task_outcome_contract"])
    assert fetched["task_completion_commit_performed"] is False


def test_16_lineage_event_is_exactly_once_and_causally_bound_to_outcome_identity(materialized_context):
    service, mission_id, created = materialized_context["service"], materialized_context["mission_id"], materialized_context["created"]
    events = service.get_mission_events(mission_id)["events"]
    selected = [e for e in events if e["event_type"] == "MISSION_TASK_OUTCOME_MATERIALIZED"]
    assert len(selected) == 1
    event = selected[0]
    assert event["causation_id"] == created["task_outcome_id"]
    assert event["payload"]["task_outcome_id"] == created["task_outcome_id"]
    assert event["payload"]["canonical_sha256"] == created["canonical_sha256"]
    assert event["payload"]["task_outcome_acceptance_performed"] is False
    assert event["payload"]["task_completion_commit_performed"] is False
    assert event["payload"]["dependency_release_performed"] is False


def test_17_repository_projection_persists_task_outcome_store_and_passes_integrity(materialized_context):
    service, mission_id, created = materialized_context["service"], materialized_context["mission_id"], materialized_context["created"]
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_task_outcomes"] == 1
    manifest = repo["persistence_manifest"]
    assert manifest["canonical_task_outcome_store"]["outcomes"][0]["task_outcome_id"] == created["task_outcome_id"]
    checks = {item["check"]: item for item in repo["integrity_checks"]}
    assert checks["canonical_task_outcome_store"]["status"] == "PASS"


def test_18_persisted_task_outcome_tampering_breaks_repository_integrity(tmp_path):
    service, _, _, mission_id, *_, created = materialize(tmp_path, "tamper361")
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute(
            "UPDATE mission_task_outcomes SET source_task_outcome_status=? WHERE task_outcome_id=?",
            ("VERIFIED_FAILED", created["task_outcome_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_19_api_routes_migration_definition_and_history_are_registered(materialized_context):
    service, mission_id, created = materialized_context["service"], materialized_context["mission_id"], materialized_context["created"]
    fetched = service.get_task_outcome(mission_id, created["task_outcome_id"])
    history = service.get_task_outcome_history(mission_id)
    definition = service.get_task_outcome_definition(mission_id)
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert history["task_outcome_count"] == 1
    assert definition["registered_task_outcome_count"] == 1
    api_source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "task-outcomes" in api_source
    assert "task-outcome-definition" in api_source
    migration = Path("migrations/036_stage3_6_1_canonical_task_outcome_contract_identity.sql")
    assert migration.is_file()
    migration_text = migration.read_text(encoding="utf-8")
    assert "mission_task_outcomes" in migration_text
    assert "UNIQUE" in migration_text.upper()
