from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionOutcomeRecoveryConflict,
    MissionOutcomeRecoveryGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.outcome_lineage import (
    OUTCOME_EVENT_LINEAGE_MODE,
    OUTCOME_EVENT_LINEAGE_SCHEMA_VERSION,
    OUTCOME_EVENT_REPLAY_SCHEMA_VERSION,
    OUTCOME_EVENT_TYPES,
    OUTCOME_RECOVERY_ALLOWED_STATES,
    OUTCOME_RECOVERY_CHECKPOINT_ID_PREFIX,
    OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
    OUTCOME_RECOVERY_EVENT_TYPE,
    OUTCOME_RECOVERY_MODE,
    OUTCOME_REPLAY_MODE,
    verify_outcome_recovery_checkpoint_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_6_8_verified_completion_declaration_lifecycle_handoff import provision_ready_source


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR = "stage3.6.9-outcome-lineage-replay-recovery"


def recovery_request(service, mission_id: str, active: dict, declaration: dict, key: str, **extra) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    replay = service.get_outcome_event_replay(mission_id)["replay"]
    body = {
        "idempotency_key": f"outcome-recovery-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_declaration_id": declaration["declaration_id"],
        "expected_declaration_sha256": declaration["canonical_sha256"],
        "expected_outcome_event_count": int(replay["outcome_event_count"]),
        "expected_outcome_event_tip_sha256": replay["outcome_event_tip_sha256"],
        "created_by": "stage3.6.9-pytest",
        "reason": "checkpoint canonical outcome lineage for deterministic restart recovery",
        "metadata": {"stage": "3.6.9", "key": key},
    }
    body.update(extra)
    return body


def provision_completed_source(tmp_path: Path, key: str) -> dict:
    ctx = provision_ready_source(tmp_path, key)
    declaration = ctx["service"].declare_verified_completion(ctx["mission_id"], deepcopy(ctx["body"]))
    request = recovery_request(ctx["service"], ctx["mission_id"], ctx["active"], declaration, key)
    return {**ctx, "declaration": declaration, "recovery_body": request}


@pytest.fixture(scope="module")
def completed_context(tmp_path_factory):
    return provision_completed_source(tmp_path_factory.mktemp("stage369-completed"), "shared-completed369")


@pytest.fixture(scope="module")
def checkpoint_context(completed_context):
    service = completed_context["service"]
    governance_before = completed_context["governance"].evaluate_calls
    runtime_before = (
        completed_context["runtime"].health_calls,
        completed_context["runtime"].result_calls,
        completed_context["runtime"].control_calls,
    )
    created = service.create_outcome_recovery_checkpoint(
        completed_context["mission_id"], deepcopy(completed_context["recovery_body"])
    )
    runtime_after = (
        completed_context["runtime"].health_calls,
        completed_context["runtime"].result_calls,
        completed_context["runtime"].control_calls,
    )
    return {
        **completed_context,
        "created": created,
        "governance_before": governance_before,
        "governance_after": completed_context["governance"].evaluate_calls,
        "runtime_before": runtime_before,
        "runtime_after": runtime_after,
    }


def test_01_health_activates_stage369_migration44_and_durable_store(completed_context):
    health = completed_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == ["stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_outcome_recovery_checkpoints" in REPOSITORY_STORES
    assert health["outcome_event_lineage_schema_version"] == OUTCOME_EVENT_LINEAGE_SCHEMA_VERSION
    assert health["outcome_event_replay_schema_version"] == OUTCOME_EVENT_REPLAY_SCHEMA_VERSION
    assert health["outcome_recovery_checkpoint_schema_version"] == OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert health["outcome_recovery_checkpoint_identity_prefix"] == OUTCOME_RECOVERY_CHECKPOINT_ID_PREFIX
    assert health["outcome_recovery_database_migration_level"] == 44


def test_02_definition_declares_read_only_replay_and_next_stage_3610(completed_context):
    definition = completed_context["service"].get_outcome_event_lineage_definition(completed_context["mission_id"])[
        "outcome_lineage_definition"
    ]
    assert definition["lineage_schema_version"] == OUTCOME_EVENT_LINEAGE_SCHEMA_VERSION
    assert definition["replay_schema_version"] == OUTCOME_EVENT_REPLAY_SCHEMA_VERSION
    assert definition["recovery_checkpoint_schema_version"] == OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert definition["lineage_mode"] == OUTCOME_EVENT_LINEAGE_MODE
    assert definition["replay_mode"] == OUTCOME_REPLAY_MODE
    assert definition["recovery_mode"] == OUTCOME_RECOVERY_MODE
    assert definition["outcome_event_types"] == list(OUTCOME_EVENT_TYPES)
    assert definition["next_stage"] == "3.6.10"


def test_03_outcome_replay_is_deterministic_read_only_and_contains_complete_precheckpoint_chain(completed_context):
    first = completed_context["service"].get_outcome_event_replay(completed_context["mission_id"])
    second = completed_context["service"].get_outcome_event_replay(completed_context["mission_id"])
    assert first["replay"] == second["replay"]
    assert first["read_only"] is True and first["side_effects_performed"] is False
    assert first["replay_is_execution"] is False
    assert first["replay"]["outcome_event_count"] == 9
    observed = [event["event_type"] for event in first["replay"]["events"]]
    assert observed == list(OUTCOME_EVENT_TYPES[:-1])


def test_04_checkpoint_is_immutable_self_verifying_and_orecover_identified(checkpoint_context):
    created = checkpoint_context["created"]
    contract = created["outcome_recovery_checkpoint"]
    assert created["checkpoint_id"].startswith(OUTCOME_RECOVERY_CHECKPOINT_ID_PREFIX)
    assert contract["schema_version"] == OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert verify_outcome_recovery_checkpoint_contract(contract)
    assert created["canonical_sha256"] == contract["integrity"]["canonical_sha256"]


def test_05_checkpoint_binds_exact_stage361_through_stage368_chain(checkpoint_context):
    source = checkpoint_context["created"]["outcome_recovery_checkpoint"]["source_bindings"]
    assert source["verified_completion_declaration"]["id"] == checkpoint_context["declaration"]["declaration_id"]
    assert source["completion_readiness"]["id"] == checkpoint_context["readiness"]["readiness_id"]
    assert source["success_criteria_evaluation"]["id"] == checkpoint_context["evaluation"]["evaluation_id"]
    assert source["mission_outcome_aggregation"]["id"] == checkpoint_context["aggregation"]["aggregation_id"]
    assert source["task_lineage_count"] == 1
    task = source["task_lineage"][0]
    assert task["task_outcome"]["id"] == checkpoint_context["task_outcome"]["task_outcome_id"]
    assert task["terminality_eligibility"]["id"] == checkpoint_context["eligibility"]["eligibility_gate_id"]
    assert task["evidence_binding"]["id"] == checkpoint_context["evidence_binding"]["verification_id"]
    assert task["task_completion"]["id"] == checkpoint_context["task_completion"]["task_completion_id"]


def test_06_recovered_outcome_state_is_verified_completed_success(checkpoint_context):
    state = checkpoint_context["created"]["recovery_state"]
    assert state["mission_state"] == "COMPLETED"
    assert state["mission_success_verified"] is True
    assert state["all_tasks_terminal"] is True
    assert state["all_tasks_verified_complete"] is True
    assert state["terminal_non_success_present"] is False
    assert state["success_criteria_satisfied"] is True
    assert state["completion_ready"] is True
    assert state["completion_blocker_count"] == 0
    assert state["outcome_trajectory_reconstructed"] is True


def test_07_same_request_is_idempotent_and_does_not_duplicate_checkpoint_event(checkpoint_context):
    replay = checkpoint_context["service"].create_outcome_recovery_checkpoint(
        checkpoint_context["mission_id"], deepcopy(checkpoint_context["recovery_body"])
    )
    assert replay["idempotent_replay"] is True
    assert replay["checkpoint_id"] == checkpoint_context["created"]["checkpoint_id"]
    assert checkpoint_context["service"].get_outcome_recovery_history(checkpoint_context["mission_id"])["checkpoint_count"] == 1
    events = checkpoint_context["service"].get_mission_events(checkpoint_context["mission_id"])["events"]
    assert len([e for e in events if e["event_type"] == OUTCOME_RECOVERY_EVENT_TYPE]) == 1


def test_08_idempotency_key_with_changed_canonical_request_conflicts(checkpoint_context):
    body = deepcopy(checkpoint_context["recovery_body"])
    body["reason"] = "different canonical request"
    with pytest.raises(MissionOutcomeRecoveryConflict):
        checkpoint_context["service"].create_outcome_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_09_stale_expected_version_is_rejected_before_duplicate_declaration_guard(checkpoint_context):
    body = deepcopy(checkpoint_context["recovery_body"])
    body["idempotency_key"] = "stage369-stale-version"
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="expected_version_sha256"):
        checkpoint_context["service"].create_outcome_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_10_stale_expected_state_version_is_rejected(checkpoint_context):
    body = deepcopy(checkpoint_context["recovery_body"])
    body["idempotency_key"] = "stage369-stale-state"
    body["expected_state_version"] += 1
    with pytest.raises(MissionConcurrencyConflict, match="expected_state_version"):
        checkpoint_context["service"].create_outcome_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_11_stale_active_plan_hash_is_rejected(checkpoint_context):
    body = deepcopy(checkpoint_context["recovery_body"])
    body["idempotency_key"] = "stage369-stale-plan"
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        checkpoint_context["service"].create_outcome_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_12_wrong_stage368_declaration_hash_is_rejected(checkpoint_context):
    body = deepcopy(checkpoint_context["recovery_body"])
    body["idempotency_key"] = "stage369-wrong-declaration"
    body["expected_declaration_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="declaration hash"):
        checkpoint_context["service"].create_outcome_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_13_caller_supplied_outcome_runtime_governance_dispatch_or_action_fields_are_forbidden(completed_context):
    forbidden = [
        ("outcome_state", "SUCCESS"),
        ("task_results", []),
        ("governance_decision", "ALLOW"),
        ("runtime_action", "resume"),
        ("dispatch_command", "REDISPATCH"),
        ("target_action", "apply"),
        ("lifecycle_command", "COMPLETE"),
    ]
    for index, (field, value) in enumerate(forbidden):
        body = deepcopy(completed_context["recovery_body"])
        body["idempotency_key"] = f"stage369-forbidden-{index}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported outcome recovery checkpoint field"):
            completed_context["service"].create_outcome_recovery_checkpoint(completed_context["mission_id"], body)


def test_14_changed_outcome_event_count_is_rejected(checkpoint_context):
    body = deepcopy(checkpoint_context["recovery_body"])
    body["idempotency_key"] = "stage369-event-count"
    current = checkpoint_context["service"].get_outcome_event_replay(checkpoint_context["mission_id"])["replay"]
    body["expected_outcome_event_count"] = int(current["outcome_event_count"]) + 1
    body["expected_outcome_event_tip_sha256"] = current["outcome_event_tip_sha256"]
    with pytest.raises(MissionConcurrencyConflict, match="outcome event count"):
        checkpoint_context["service"].create_outcome_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_15_changed_outcome_event_tip_hash_is_rejected(checkpoint_context):
    body = deepcopy(checkpoint_context["recovery_body"])
    body["idempotency_key"] = "stage369-event-tip"
    current = checkpoint_context["service"].get_outcome_event_replay(checkpoint_context["mission_id"])["replay"]
    body["expected_outcome_event_count"] = int(current["outcome_event_count"])
    body["expected_outcome_event_tip_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="outcome event tip"):
        checkpoint_context["service"].create_outcome_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_16_missing_stage368_handoff_event_fails_closed(tmp_path):
    ctx = provision_completed_source(tmp_path, "missing-handoff369")
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as connection:
        connection.execute(
            "DELETE FROM mission_events WHERE mission_id=? AND event_type=? AND causation_id=?",
            (ctx["mission_id"], "MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED", ctx["declaration"]["declaration_id"]),
        )
        connection.commit()
    with pytest.raises((MissionOutcomeRecoveryGuardRejected, MissionRepositoryIntegrityError)):
        ctx["service"].create_outcome_recovery_checkpoint(ctx["mission_id"], deepcopy(ctx["recovery_body"]))


def test_17_restart_reconstructs_checkpoint_from_durable_repository_without_runtime_or_governance_calls(checkpoint_context):
    restarted = CanonicalMissionService(
        repository=MissionRepository(sqlite_path=checkpoint_context["service"].repository.sqlite_path)
    )
    recovered = restarted.get_outcome_recovery(checkpoint_context["mission_id"])
    assert recovered["checkpoint_id"] == checkpoint_context["created"]["checkpoint_id"]
    assert recovered["canonical_sha256"] == checkpoint_context["created"]["canonical_sha256"]
    assert recovered["durable_repository_is_source_of_truth"] is True
    assert recovered["runtime_query_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert recovered["dispatch_redelivery_performed"] is False


def test_18_api_routes_are_registered():
    text = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    for route in (
        "outcome-lineage",
        "outcome-replay",
        "outcome-recovery",
        "outcome-recovery-checkpoints",
        "outcome-lineage-definition",
    ):
        assert route in text
    assert "create_outcome_recovery_checkpoint" in text


def test_19_repository_projection_integrity_includes_stage369_store(checkpoint_context):
    repository = checkpoint_context["service"].get_mission_repository(checkpoint_context["mission_id"])
    assert repository["integrity_status"] == "PASS"
    assert repository["record_counts"]["mission_outcome_recovery_checkpoints"] == 1
    manifest = repository["persistence_manifest"]["outcome_lineage_replay_recovery_store"]
    assert manifest["checkpoints"][0]["checkpoint_id"] == checkpoint_context["created"]["checkpoint_id"]


def test_20_persisted_checkpoint_tampering_breaks_repository_integrity(tmp_path):
    ctx = provision_completed_source(tmp_path, "tamper369")
    created = ctx["service"].create_outcome_recovery_checkpoint(ctx["mission_id"], deepcopy(ctx["recovery_body"]))
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as connection:
        connection.execute(
            "UPDATE mission_outcome_recovery_checkpoints SET canonical_sha256=? WHERE checkpoint_id=?",
            ("0" * 64, created["checkpoint_id"]),
        )
        connection.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        ctx["service"].get_mission_repository(ctx["mission_id"])


def test_21_checkpoint_event_has_exact_causation_and_cardinality(checkpoint_context):
    events = checkpoint_context["service"].get_mission_events(checkpoint_context["mission_id"])["events"]
    checkpoint_id = checkpoint_context["created"]["checkpoint_id"]
    recovery_events = [e for e in events if e["event_type"] == OUTCOME_RECOVERY_EVENT_TYPE]
    assert len(recovery_events) == 1
    assert recovery_events[0]["causation_id"] == checkpoint_id
    assert recovery_events[0]["payload"]["canonical_sha256"] == checkpoint_context["created"]["canonical_sha256"]


def test_22_authority_and_side_effect_boundaries_are_explicit_and_zero(checkpoint_context):
    created = checkpoint_context["created"]
    assert checkpoint_context["governance_after"] == checkpoint_context["governance_before"]
    assert checkpoint_context["runtime_after"] == checkpoint_context["runtime_before"]
    for key in (
        "replay_is_execution",
        "recovery_is_execution",
        "recovery_is_dispatch",
        "recovery_is_runtime_resumption",
        "recovery_is_governance_authorization",
        "recovery_is_lifecycle_transition",
        "llm_reinterpretation_performed",
        "runtime_query_performed",
        "runtime_control_io_performed",
        "governance_query_performed",
        "external_network_io_performed",
        "dispatch_redelivery_performed",
        "new_execution_attempt_created",
        "new_target_action_dispatch_performed",
        "mission_state_transition_performed",
        "mission_success_completion_authority_exercised",
        "target_actuation",
    ):
        assert created[key] is False
    assert set(OUTCOME_RECOVERY_ALLOWED_STATES) == {"COMPLETED"}
