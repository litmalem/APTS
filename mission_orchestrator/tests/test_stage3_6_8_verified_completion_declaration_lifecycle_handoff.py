from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionValidationError,
    MissionVerifiedCompletionConflict,
    MissionVerifiedCompletionGuardRejected,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.verified_completion import (
    LIFECYCLE_HANDOFF_COMMANDS,
    VERIFIED_COMPLETION_AUTHORITY,
    VERIFIED_COMPLETION_CONTRACT_SCHEMA_VERSION,
    VERIFIED_COMPLETION_FINAL_STATE,
    VERIFIED_COMPLETION_ID_PREFIX,
    VERIFIED_COMPLETION_MODE,
    VERIFIED_COMPLETION_STAGE_SCHEMA_VERSION,
    VERIFIED_COMPLETION_STATUS,
    completion_evidence_refs,
    verify_verified_completion_contract,
)
from tests.test_stage3_5_10_execution_dispatch_acceptance_regression_gate import close_success
from tests.test_stage3_6_1_canonical_task_outcome_contract_identity import outcome_request
from tests.test_stage3_6_2_task_terminality_completion_eligibility import eligibility_request
from tests.test_stage3_6_3_evidence_binding_verification import binding_request
from tests.test_stage3_6_4_dependency_aware_task_completion import completion_request
from tests.test_stage3_6_5_mission_outcome_aggregation import aggregation_request
from tests.test_stage3_6_6_mission_success_criteria_evaluation import evaluation_request
from tests.test_stage3_6_7_completion_readiness_blockers import readiness_request, provision_readiness_source
import tests.test_stage3_3_4_task_dependency_graph_structural_validation as t334
import tests.test_stage3_3_5_planner_invocation_plan_generation as t335


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR = "stage3.6.9-outcome-lineage-replay-recovery"
DECLARED_EVENT = "MISSION_VERIFIED_COMPLETION_DECLARED"
HANDOFF_EVENT = "MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED"

_ORIGINAL_MISSION_PAYLOAD = t334.mission_payload
_ORIGINAL_TASK_SPECS = t334.task_specs
_ORIGINAL_GRAPH_REQUEST = t334.graph_request


def _one_task_mission_payload(key: str) -> dict:
    payload = deepcopy(_ORIGINAL_MISSION_PAYLOAD(key))
    payload["success_criteria"] = [
        {"metric": "all_tasks_terminal", "expected": True},
        {"metric": "all_tasks_verified_complete", "expected": True},
        {"metric": "terminal_non_success_present", "expected": False},
    ]
    payload["metadata"] = {**payload.get("metadata", {}), "stage368_fixture": True}
    return payload


def _one_task_specs() -> list[dict]:
    return [deepcopy(_ORIGINAL_TASK_SPECS()[0])]


def _no_edge_graph_request(service, mission_id: str, key: str, *, edges=None) -> dict:
    return _ORIGINAL_GRAPH_REQUEST(service, mission_id, key, edges=[])


def verified_completion_request(service, mission_id: str, active: dict, readiness: dict, key: str, **extra) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"verified-completion-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_readiness_id": readiness["readiness_id"],
        "expected_readiness_sha256": readiness["canonical_sha256"],
        "declared_by": "stage3.6.8-pytest",
        "reason": "declare verified Mission completion and hand off through canonical Stage-3.2 lifecycle commands",
        "metadata": {"stage": "3.6.8", "key": key},
    }
    body.update(extra)
    return body


def provision_ready_source(tmp_path: Path, key: str) -> dict:
    # The normal regression fixture has three planned tasks but executes one task. For
    # Stage 3.6.8 we need a legitimate READY predecessor, so provision exactly one task
    # and an edgeless graph; every active-Plan task can then reach VERIFIED_COMPLETE.
    with (
        patch.object(t334, "mission_payload", _one_task_mission_payload),
        patch.object(t334, "task_specs", _one_task_specs),
        patch.object(t335, "graph_request", _no_edge_graph_request),
    ):
        (
            service,
            governance,
            runtime,
            mission_id,
            active,
            attempt,
            delivery,
            running,
            result,
            propagation,
            checkpoint,
        ) = close_success(tmp_path, key)

    task_outcome = service.create_task_outcome(
        mission_id,
        outcome_request(service, mission_id, active, attempt, result, propagation, checkpoint, key),
    )
    eligibility = service.evaluate_task_terminality_completion_eligibility(
        mission_id, eligibility_request(service, mission_id, active, task_outcome, key)
    )
    evidence_binding = service.verify_task_evidence_binding(
        mission_id, binding_request(service, mission_id, active, task_outcome, eligibility, result, key)
    )
    task_completion = service.commit_dependency_aware_task_completion(
        mission_id, completion_request(service, mission_id, active, evidence_binding, key)
    )
    aggregation = service.aggregate_mission_outcome(
        mission_id, aggregation_request(service, mission_id, active, key)
    )
    evaluation = service.evaluate_mission_success_criteria(
        mission_id, evaluation_request(service, mission_id, active, aggregation, key)
    )
    readiness = service.evaluate_completion_readiness(
        mission_id, readiness_request(service, mission_id, active, evaluation, key)
    )
    assert aggregation["all_tasks_terminal"] is True
    assert aggregation["all_tasks_verified_complete"] is True
    assert aggregation["terminal_non_success_present"] is False
    assert evaluation["overall_result"] == "SUCCESS_CRITERIA_SATISFIED"
    assert readiness["readiness_result"] == "READY"
    assert readiness["blocker_count"] == 0
    body = verified_completion_request(service, mission_id, active, readiness, key)
    return {
        "service": service,
        "governance": governance,
        "runtime": runtime,
        "mission_id": mission_id,
        "active": active,
        "attempt": attempt,
        "delivery": delivery,
        "running": running,
        "result": result,
        "propagation": propagation,
        "checkpoint": checkpoint,
        "task_outcome": task_outcome,
        "eligibility": eligibility,
        "evidence_binding": evidence_binding,
        "task_completion": task_completion,
        "aggregation": aggregation,
        "evaluation": evaluation,
        "readiness": readiness,
        "body": body,
    }


@pytest.fixture(scope="module")
def ready_context(tmp_path_factory):
    return provision_ready_source(tmp_path_factory.mktemp("stage368-ready"), "shared-ready368")


@pytest.fixture(scope="module")
def completed_context(tmp_path_factory):
    ctx = provision_ready_source(tmp_path_factory.mktemp("stage368-completed"), "shared-completed368")
    gov_before = ctx["governance"].evaluate_calls
    runtime_before = (ctx["runtime"].health_calls, ctx["runtime"].result_calls, ctx["runtime"].control_calls)
    created = ctx["service"].declare_verified_completion(ctx["mission_id"], deepcopy(ctx["body"]))
    return {
        **ctx,
        "created": created,
        "gov_before": gov_before,
        "gov_after": ctx["governance"].evaluate_calls,
        "runtime_before": runtime_before,
        "runtime_after": (ctx["runtime"].health_calls, ctx["runtime"].result_calls, ctx["runtime"].control_calls),
    }


def test_01_health_activates_stage368_migration43_and_durable_store(ready_context):
    health = ready_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == ["stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_verified_completion_declarations" in REPOSITORY_STORES
    assert health["verified_completion_stage_schema_version"] == VERIFIED_COMPLETION_STAGE_SCHEMA_VERSION
    assert health["verified_completion_contract_schema_version"] == VERIFIED_COMPLETION_CONTRACT_SCHEMA_VERSION
    assert health["verified_completion_identity_prefix"] == VERIFIED_COMPLETION_ID_PREFIX
    assert health["verified_completion_mode"] == VERIFIED_COMPLETION_MODE
    assert health["verified_completion_authority"] == VERIFIED_COMPLETION_AUTHORITY
    assert health["verified_completion_status"] == VERIFIED_COMPLETION_STATUS
    assert health["verified_completion_database_migration_level"] == 43


def test_02_definition_consumes_ready_chain_and_requires_canonical_stage32_handoff(ready_context):
    definition = ready_context["service"].get_verified_completion_definition(ready_context["mission_id"])[
        "verified_completion_definition"
    ]
    assert definition["schema_version"] == VERIFIED_COMPLETION_CONTRACT_SCHEMA_VERSION
    assert definition["consumes_stage367_completion_readiness"] is True
    assert definition["revalidates_stage366_success_criteria_evaluation"] is True
    assert definition["revalidates_stage365_all_tasks_terminal_and_verified_complete"] is True
    assert definition["persists_declaration_before_lifecycle_handoff"] is True
    assert definition["lifecycle_handoff_commands"] == list(LIFECYCLE_HANDOFF_COMMANDS)
    assert definition["uses_canonical_stage32_lifecycle_command_path"] is True
    assert definition["direct_state_transition_bypass_used"] is False
    assert definition["restart_safe_partial_handoff_resume"] is True
    assert definition["next_stage"] == "3.6.9"


def test_03_declaration_contract_is_immutable_self_verifying_and_source_bound(completed_context):
    created = completed_context["created"]
    contract = created["verified_completion_contract"]
    assert created["declaration_id"].startswith(VERIFIED_COMPLETION_ID_PREFIX)
    assert created["declaration_status"] == VERIFIED_COMPLETION_STATUS
    assert created["verification_status"] == "VERIFIED"
    assert verify_verified_completion_contract(contract)
    assert contract["source_bindings"]["readiness_id"] == completed_context["readiness"]["readiness_id"]
    assert contract["source_bindings"]["evaluation_id"] == completed_context["evaluation"]["evaluation_id"]
    assert contract["source_bindings"]["aggregation_id"] == completed_context["aggregation"]["aggregation_id"]


def test_04_verified_declaration_hands_off_through_begin_cleanup_then_complete(completed_context):
    created = completed_context["created"]
    assert created["status"] == "completed"
    assert created["lifecycle_handoff_performed"] is True
    assert created["stage32_lifecycle_command_path_used"] is True
    assert created["lifecycle_handoff_commands"] == ["BEGIN_CLEANUP", "COMPLETE"]
    assert created["cleanup_command"]["status"] == "COMPLETED"
    assert created["cleanup_command"]["operation"] == "LIFECYCLE_COMMAND"
    assert created["cleanup_command"]["transition"]["to_state"] == "CLEANING_UP"
    assert created["complete_command"]["status"] == "COMPLETED"
    assert created["complete_command"]["operation"] == "LIFECYCLE_COMMAND"
    assert created["complete_command"]["transition"]["to_state"] == "COMPLETED"
    assert created["final_mission_state"]["state"] == VERIFIED_COMPLETION_FINAL_STATE == "COMPLETED"


def test_05_stage328_completion_evidence_is_exact_and_verified(completed_context):
    created = completed_context["created"]
    evidence = completion_evidence_refs(created["verified_completion_contract"])
    verification = created["complete_command"]["completion_verification"]
    assert verification["verified_completion_claimed"] is True
    assert verification["to_state"] == "COMPLETED"
    completion = evidence["completion"]
    assert completion["verification_status"] == "VERIFIED"
    assert completion["objective_status"] == "SATISFIED"
    assert completion["success_criteria_status"] == "SATISFIED"
    assert len(completion["criteria_results"]) == created["success_criteria_count"]
    assert all(x["status"] == "SATISFIED" and x["evidence_refs"] for x in completion["criteria_results"])
    assert completion["cleanup_status"] == "VERIFIED"
    assert completion["cleanup_checks"][0]["status"] == "PASS"
    assert completion["outstanding_critical_dependencies"] == 0


def test_06_stale_mission_version_is_rejected(ready_context):
    body = deepcopy(ready_context["body"])
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="expected_version_sha256"):
        ready_context["service"].declare_verified_completion(ready_context["mission_id"], body)


def test_07_stale_active_plan_hash_is_rejected(ready_context):
    body = deepcopy(ready_context["body"])
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        ready_context["service"].declare_verified_completion(ready_context["mission_id"], body)


def test_08_wrong_readiness_hash_is_rejected(ready_context):
    body = deepcopy(ready_context["body"])
    body["expected_readiness_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="readiness hash"):
        ready_context["service"].declare_verified_completion(ready_context["mission_id"], body)


def test_09_non_ready_stage367_decision_fails_closed(tmp_path):
    blocked = provision_readiness_source(tmp_path, "blocked368")
    readiness = blocked["service"].evaluate_completion_readiness(
        blocked["mission_id"], deepcopy(blocked["readiness_body"])
    )
    assert readiness["completion_ready"] is False
    body = verified_completion_request(blocked["service"], blocked["mission_id"], blocked["active"], readiness, "blocked368")
    with pytest.raises(MissionVerifiedCompletionGuardRejected):
        blocked["service"].declare_verified_completion(blocked["mission_id"], body)


def test_10_caller_supplied_completion_lifecycle_or_authority_fields_are_forbidden(ready_context):
    forbidden = [
        ("completion_status", "VERIFIED"),
        ("final_state", "COMPLETED"),
        ("lifecycle_command", "COMPLETE"),
        ("cleanup_status", "VERIFIED"),
        ("success_criteria_status", "SATISFIED"),
        ("governance_decision", "ALLOW"),
        ("runtime_action", "complete"),
        ("target_actuation", True),
    ]
    for index, (field, value) in enumerate(forbidden):
        body = deepcopy(ready_context["body"])
        body["idempotency_key"] = f"forbidden368-{index}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported verified completion field"):
            ready_context["service"].declare_verified_completion(ready_context["mission_id"], body)


def test_11_same_request_is_idempotent_after_completed_handoff(completed_context):
    replay = completed_context["service"].declare_verified_completion(
        completed_context["mission_id"], deepcopy(completed_context["body"])
    )
    assert replay["idempotent_replay"] is True
    assert replay["declaration_id"] == completed_context["created"]["declaration_id"]
    assert replay["canonical_sha256"] == completed_context["created"]["canonical_sha256"]
    assert replay["final_mission_state"]["state"] == "COMPLETED"
    assert completed_context["service"].get_verified_completion_history(completed_context["mission_id"])["declaration_count"] == 1


def test_12_idempotency_key_with_changed_request_conflicts(completed_context):
    body = deepcopy(completed_context["body"])
    body["reason"] = "different canonical request"
    with pytest.raises(MissionVerifiedCompletionConflict):
        completed_context["service"].declare_verified_completion(completed_context["mission_id"], body)


def test_13_stage368_performs_no_governance_or_target_runtime_io(completed_context):
    assert completed_context["gov_after"] == completed_context["gov_before"]
    assert completed_context["runtime_after"] == completed_context["runtime_before"]
    created = completed_context["created"]
    assert created["governance_query_performed"] is False
    assert created["runtime_query_performed"] is False
    assert created["runtime_control_io_performed"] is False
    assert created["dispatch_performed"] is False
    assert created["external_network_io_performed"] is False
    assert created["target_actuation"] is False


def test_14_restart_reconstructs_declaration_and_completed_handoff(completed_context):
    restarted = CanonicalMissionService(
        repository=MissionRepository(sqlite_path=completed_context["service"].repository.sqlite_path)
    )
    reconstructed = restarted.get_verified_completion_declaration(
        completed_context["mission_id"], completed_context["created"]["declaration_id"]
    )
    assert reconstructed["canonical_sha256"] == completed_context["created"]["canonical_sha256"]
    assert reconstructed["lifecycle_handoff_performed"] is True
    assert reconstructed["final_mission_state"]["state"] == "COMPLETED"


def test_15_lineage_records_exactly_one_declaration_and_one_handoff_event(completed_context):
    events = completed_context["service"].get_mission_events(completed_context["mission_id"])["events"]
    declaration_id = completed_context["created"]["declaration_id"]
    declared = [e for e in events if e["event_type"] == DECLARED_EVENT]
    handed = [e for e in events if e["event_type"] == HANDOFF_EVENT]
    assert len(declared) == 1 and declared[0]["causation_id"] == declaration_id
    assert len(handed) == 1 and handed[0]["causation_id"] == declaration_id


def test_16_repository_projection_integrity_includes_stage368_store(completed_context):
    repository = completed_context["service"].get_mission_repository(completed_context["mission_id"])
    assert repository["integrity_status"] == "PASS"
    assert repository["record_counts"]["mission_verified_completion_declarations"] == 1
    manifest = repository["persistence_manifest"]["mission_verified_completion_declaration_store"]
    assert manifest["declarations"][0]["declaration_id"] == completed_context["created"]["declaration_id"]


def test_17_persisted_declaration_tampering_breaks_repository_integrity(tmp_path):
    ctx = provision_ready_source(tmp_path, "tamper368")
    created = ctx["service"].declare_verified_completion(ctx["mission_id"], deepcopy(ctx["body"]))
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as connection:
        connection.execute(
            "UPDATE mission_verified_completion_declarations SET canonical_sha256=? WHERE declaration_id=?",
            ("0" * 64, created["declaration_id"]),
        )
        connection.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        ctx["service"].get_mission_repository(ctx["mission_id"])


def test_18_api_routes_are_registered():
    text = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "verified-completion-declarations" in text
    assert "verified-completion-definition" in text
    assert "declare_verified_completion" in text


def test_19_authority_boundary_is_explicit_and_direct_state_bypass_is_forbidden(completed_context):
    created = completed_context["created"]
    assert created["verified_completion_declaration_performed"] is True
    assert created["mission_success_completion_authority_exercised"] is True
    assert created["stage32_lifecycle_handoff_required"] is True
    assert created["direct_state_transition_bypass_used"] is False
    assert created["mission_state_transition_performed"] is True
    assert created["stage32_lifecycle_command_path_used"] is True


def test_20_partial_handoff_crash_after_begin_cleanup_is_restart_safe(tmp_path):
    ctx = provision_ready_source(tmp_path, "resume368")
    service = ctx["service"]
    original_execute = service.execute_mission_lifecycle_command

    def crash_after_begin_cleanup(mission_id: str, payload: dict):
        result = original_execute(mission_id, payload)
        if payload.get("command") == "BEGIN_CLEANUP":
            raise RuntimeError("simulated process crash after durable BEGIN_CLEANUP")
        return result

    with patch.object(service, "execute_mission_lifecycle_command", side_effect=crash_after_begin_cleanup):
        with pytest.raises(RuntimeError, match="simulated process crash"):
            service.declare_verified_completion(ctx["mission_id"], deepcopy(ctx["body"]))

    assert service.get_mission_state(ctx["mission_id"])["mission_state"]["state"] == "CLEANING_UP"
    assert service.get_verified_completion_history(ctx["mission_id"])["declaration_count"] == 1

    replay = service.declare_verified_completion(ctx["mission_id"], deepcopy(ctx["body"]))
    assert replay["idempotent_replay"] is True
    assert replay["lifecycle_handoff_performed"] is True
    assert replay["final_mission_state"]["state"] == "COMPLETED"
    events = service.get_mission_events(ctx["mission_id"])["events"]
    assert len([e for e in events if e["event_type"] == DECLARED_EVENT]) == 1
    assert len([e for e in events if e["event_type"] == HANDOFF_EVENT]) == 1
