from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionOutcomeAggregationConflict,
    MissionOutcomeAggregationGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.mission_outcome_aggregation import (
    MISSION_OUTCOME_AGGREGATION_AUTHORITY,
    MISSION_OUTCOME_AGGREGATION_CONTRACT_SCHEMA_VERSION,
    MISSION_OUTCOME_AGGREGATION_ID_PREFIX,
    MISSION_OUTCOME_AGGREGATION_MODE,
    MISSION_OUTCOME_AGGREGATION_STAGE_SCHEMA_VERSION,
    MISSION_OUTCOME_AGGREGATION_STATUS,
    MISSION_OUTCOME_TASK_CLASSIFICATIONS,
    derive_mission_outcome_aggregation,
    verify_mission_outcome_aggregation_contract,
)
from tests.test_stage3_6_4_dependency_aware_task_completion import provision_completion_source

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR = "stage3.6.5-mission-outcome-aggregation"
EVENT_TYPE = "MISSION_OUTCOME_AGGREGATED"


def aggregation_request(service, mission_id, active, key: str, **extra):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"mission-outcome-aggregation-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "aggregated_by": "stage3.6.5-pytest",
        "reason": "aggregate active-Plan task outcomes without deciding Mission completion",
        "metadata": {"stage": "3.6.5", "key": key},
    }
    body.update(extra)
    return body


def provision_aggregation_source(tmp_path: Path, key: str, *, complete_root: bool = True):
    ctx = provision_completion_source(tmp_path, key)
    if complete_root:
        ctx["task_completion"] = ctx["service"].commit_dependency_aware_task_completion(
            ctx["mission_id"], deepcopy(ctx["completion_body"])
        )
    body = aggregation_request(ctx["service"], ctx["mission_id"], ctx["active"], key)
    return {**ctx, "aggregation_body": body}


@pytest.fixture(scope="module")
def source_context(tmp_path_factory):
    return provision_aggregation_source(tmp_path_factory.mktemp("stage365-source"), "shared-source365")


@pytest.fixture(scope="module")
def aggregated_context(tmp_path_factory):
    ctx = provision_aggregation_source(tmp_path_factory.mktemp("stage365-aggregated"), "shared-aggregated365")
    gov_before = ctx["governance"].evaluate_calls
    runtime_before = (ctx["runtime"].health_calls, ctx["runtime"].result_calls, ctx["runtime"].control_calls)
    created = ctx["service"].aggregate_mission_outcome(ctx["mission_id"], deepcopy(ctx["aggregation_body"]))
    ctx["created"] = created
    ctx["gov_before"] = gov_before
    ctx["gov_after"] = ctx["governance"].evaluate_calls
    ctx["runtime_before"] = runtime_before
    ctx["runtime_after"] = (ctx["runtime"].health_calls, ctx["runtime"].result_calls, ctx["runtime"].control_calls)
    return ctx


def test_01_health_activates_stage365_migration40_and_store(source_context):
    health = source_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == ["stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_outcome_aggregations" in REPOSITORY_STORES
    assert health["mission_outcome_aggregation_stage_schema_version"] == MISSION_OUTCOME_AGGREGATION_STAGE_SCHEMA_VERSION
    assert health["mission_outcome_aggregation_contract_schema_version"] == MISSION_OUTCOME_AGGREGATION_CONTRACT_SCHEMA_VERSION
    assert health["mission_outcome_aggregation_identity_prefix"] == MISSION_OUTCOME_AGGREGATION_ID_PREFIX
    assert health["mission_outcome_aggregation_mode"] == MISSION_OUTCOME_AGGREGATION_MODE
    assert health["mission_outcome_aggregation_authority"] == MISSION_OUTCOME_AGGREGATION_AUTHORITY
    assert health["mission_outcome_aggregation_status"] == MISSION_OUTCOME_AGGREGATION_STATUS
    assert health["mission_outcome_aggregation_database_migration_level"] == 40
    assert health["mission_outcome_aggregation_persistence_store"] == "mission_outcome_aggregations"


def test_02_definition_declares_aggregation_scope_and_reserves_criteria_for_366(source_context):
    definition = source_context["service"].get_mission_outcome_aggregation_definition(source_context["mission_id"])[
        "mission_outcome_aggregation_definition"
    ]
    assert definition["schema_version"] == MISSION_OUTCOME_AGGREGATION_CONTRACT_SCHEMA_VERSION
    assert definition["task_classifications"] == list(MISSION_OUTCOME_TASK_CLASSIFICATIONS)
    assert definition["consumes_stage361_task_outcomes"] is True
    assert definition["consumes_stage364_task_completions"] is True
    assert definition["active_plan_task_set_is_authoritative"] is True
    assert definition["success_criteria_evaluation_performed"] is False
    assert definition["mission_completion_readiness_decision_performed"] is False
    assert definition["next_stage"] == "3.6.6"


def test_03_aggregation_creates_immutable_active_plan_snapshot(aggregated_context):
    created = aggregated_context["created"]
    assert created["aggregation_id"].startswith(MISSION_OUTCOME_AGGREGATION_ID_PREFIX)
    assert created["aggregation_status"] == MISSION_OUTCOME_AGGREGATION_STATUS
    assert created["task_count"] >= 1
    assert created["verified_complete_count"] >= 1
    assert created["task_count"] == sum(created[f"{k}_count"] for k in ("verified_complete", "failed", "cancelled", "timed_out", "running", "blocked", "pending"))
    assert verify_mission_outcome_aggregation_contract(created["mission_outcome_aggregation_contract"])


def test_04_completed_task_is_classified_verified_complete_and_source_bound(aggregated_context):
    created = aggregated_context["created"]
    completion = aggregated_context["task_completion"]
    item = next(x for x in created["task_outcomes"] if x["planned_task_id"] == completion["planned_task_id"])
    assert item["classification"] == "VERIFIED_COMPLETE"
    assert item["source_kind"] == "STAGE3_6_4_TASK_COMPLETION"
    assert item["source_id"] == completion["task_completion_id"]
    assert item["source_sha256"] == completion["canonical_sha256"]
    assert item["terminal"] is True


def test_05_incomplete_dependents_are_aggregated_without_declaring_mission_completion(aggregated_context):
    created = aggregated_context["created"]
    assert created["all_tasks_verified_complete"] is False
    assert any(x["classification"] in {"BLOCKED", "PENDING", "RUNNING"} for x in created["task_outcomes"])
    assert created["success_criteria_evaluation_performed"] is False
    assert created["mission_completion_readiness_decision_performed"] is False
    assert created["mission_success_completion_authority_exercised"] is False
    assert created["mission_state_transition_performed"] is False


def test_06_stale_mission_vector_is_rejected(source_context):
    body = deepcopy(source_context["aggregation_body"])
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        source_context["service"].aggregate_mission_outcome(source_context["mission_id"], body)


def test_07_stale_plan_hash_is_rejected(source_context):
    body = deepcopy(source_context["aggregation_body"])
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        source_context["service"].aggregate_mission_outcome(source_context["mission_id"], body)


def test_08_caller_supplied_classification_or_completion_fields_are_forbidden(source_context):
    forbidden = [
        ("task_outcomes", []), ("classification", "VERIFIED_COMPLETE"), ("mission_completed", True),
        ("success_criteria_satisfied", True), ("completion_ready", True), ("dependency_release", True),
        ("readiness_recalculation", True), ("plan_progression", True), ("governance_decision", "ALLOW"),
        ("runtime_action", "resume"),
    ]
    for idx, (field, value) in enumerate(forbidden):
        body = deepcopy(source_context["aggregation_body"])
        body["idempotency_key"] = f"aggregation-forbidden-{idx}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported mission outcome aggregation field"):
            source_context["service"].aggregate_mission_outcome(source_context["mission_id"], body)


def test_09_same_request_is_idempotent_without_duplicate_snapshot_or_event(aggregated_context):
    service, mission_id = aggregated_context["service"], aggregated_context["mission_id"]
    first = aggregated_context["created"]
    replay = service.aggregate_mission_outcome(mission_id, deepcopy(aggregated_context["aggregation_body"]))
    assert replay["idempotent_replay"] is True
    assert replay["aggregation_id"] == first["aggregation_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_outcome_aggregation_history(mission_id)["aggregation_count"] == 1
    events = service.get_mission_events(mission_id)["events"]
    assert len([e for e in events if e["event_type"] == EVENT_TYPE]) == 1


def test_10_same_idempotency_key_with_different_request_conflicts(aggregated_context):
    body = deepcopy(aggregated_context["aggregation_body"])
    body["reason"] = "different canonical Stage-3.6.5 aggregation request"
    with pytest.raises(MissionOutcomeAggregationConflict, match="idempotency_key"):
        aggregated_context["service"].aggregate_mission_outcome(aggregated_context["mission_id"], body)


def test_11_aggregation_and_replay_do_not_contact_runtime_or_governance(aggregated_context):
    assert aggregated_context["gov_after"] == aggregated_context["gov_before"]
    assert aggregated_context["runtime_after"] == aggregated_context["runtime_before"]
    service, governance, runtime = aggregated_context["service"], aggregated_context["governance"], aggregated_context["runtime"]
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    replay = service.aggregate_mission_outcome(aggregated_context["mission_id"], deepcopy(aggregated_context["aggregation_body"]))
    assert governance.evaluate_calls == gov_before
    assert (runtime.health_calls, runtime.result_calls, runtime.control_calls) == runtime_before
    assert replay["external_network_io_performed"] is False
    assert replay["target_actuation"] is False


def test_12_restart_reconstructs_same_aggregation(aggregated_context):
    service, mission_id, created = aggregated_context["service"], aggregated_context["mission_id"], aggregated_context["created"]
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=service.repository.sqlite_path))
    fetched = restarted.get_mission_outcome_aggregation(mission_id, created["aggregation_id"])
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert fetched["source_snapshot_sha256"] == created["source_snapshot_sha256"]
    assert verify_mission_outcome_aggregation_contract(fetched["mission_outcome_aggregation_contract"])


def test_13_lineage_event_is_exactly_once_and_bound_to_aggregation(aggregated_context):
    service, mission_id, created = aggregated_context["service"], aggregated_context["mission_id"], aggregated_context["created"]
    selected = [e for e in service.get_mission_events(mission_id)["events"] if e["event_type"] == EVENT_TYPE]
    assert len(selected) == 1
    event = selected[0]
    assert event["causation_id"] == created["aggregation_id"]
    assert event["payload"]["aggregation_id"] == created["aggregation_id"]
    assert event["payload"]["canonical_sha256"] == created["canonical_sha256"]
    assert event["payload"]["success_criteria_evaluation_performed"] is False


def test_14_repository_projection_persists_aggregation_and_integrity_passes(aggregated_context):
    service, mission_id, created = aggregated_context["service"], aggregated_context["mission_id"], aggregated_context["created"]
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_outcome_aggregations"] == 1
    refs = repo["persistence_manifest"]["mission_outcome_aggregation_store"]["aggregations"]
    assert refs[0]["aggregation_id"] == created["aggregation_id"]
    assert refs[0]["source_snapshot_sha256"] == created["source_snapshot_sha256"]
    checks = {item["check"]: item for item in repo["integrity_checks"]}
    assert checks["mission_outcome_aggregation_store"]["status"] == "PASS"


def test_15_persisted_aggregation_tampering_breaks_repository_integrity(tmp_path):
    ctx = provision_aggregation_source(tmp_path, "tamper365")
    created = ctx["service"].aggregate_mission_outcome(ctx["mission_id"], deepcopy(ctx["aggregation_body"]))
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as conn:
        conn.execute("UPDATE mission_outcome_aggregations SET verified_complete_count=? WHERE aggregation_id=?", (999, created["aggregation_id"]))
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        ctx["service"].get_mission_repository(ctx["mission_id"])


def test_16_api_routes_migration_definition_and_history_are_registered(aggregated_context):
    service, mission_id, created = aggregated_context["service"], aggregated_context["mission_id"], aggregated_context["created"]
    fetched = service.get_mission_outcome_aggregation(mission_id, created["aggregation_id"])
    history = service.get_mission_outcome_aggregation_history(mission_id)
    definition = service.get_mission_outcome_aggregation_definition(mission_id)
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert history["aggregation_count"] == 1
    assert definition["registered_aggregation_count"] == 1
    api_source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "mission-outcome-aggregations" in api_source
    assert "mission-outcome-aggregation-definition" in api_source
    migration = Path("migrations/040_stage3_6_5_mission_outcome_aggregation.sql")
    assert migration.is_file()
    assert "mission_outcome_aggregations" in migration.read_text(encoding="utf-8")


def test_17_pure_derivation_classifies_pending_and_blocked_active_plan_tasks(source_context):
    active = source_context["active"]
    with patch("mission_orchestrator.mission_outcome_aggregation.verify_plan_version_contract", return_value=True):
        agg = derive_mission_outcome_aggregation(active_plan=active, task_outcomes=[], task_completions=[], running_projections=[])
    assert agg["task_count"] >= 1
    assert agg["verified_complete_count"] == 0
    assert agg["pending_count"] + agg["blocked_count"] == agg["task_count"]
    assert agg["all_tasks_terminal"] is False
    assert agg["all_tasks_verified_complete"] is False


def test_18_pure_derivation_rejects_stale_completion(source_context):
    active = source_context["active"]
    stale = deepcopy(source_context["task_completion"])
    stale["plan_version_record_id"] = "pver-00000000-0000-0000-0000-000000000000"
    with patch("mission_orchestrator.mission_outcome_aggregation.verify_plan_version_contract", return_value=True):
        with pytest.raises(MissionValidationError, match="stale/superseded Plan"):
            derive_mission_outcome_aggregation(active_plan=active, task_outcomes=[], task_completions=[stale], running_projections=[])


def test_19_source_snapshot_hash_is_stable_for_same_durable_inputs(source_context):
    active = source_context["active"]
    completions = [source_context["task_completion"]]
    with patch("mission_orchestrator.mission_outcome_aggregation.verify_plan_version_contract", return_value=True):
        first = derive_mission_outcome_aggregation(active_plan=active, task_outcomes=[], task_completions=completions, running_projections=[])
        second = derive_mission_outcome_aggregation(active_plan=active, task_outcomes=[], task_completions=completions, running_projections=[])
    assert first["source_snapshot_sha256"] == second["source_snapshot_sha256"]
    assert first["task_outcomes"] == second["task_outcomes"]


def test_20_stage365_does_not_mutate_mission_state_or_task_completion(aggregated_context):
    service, mission_id = aggregated_context["service"], aggregated_context["mission_id"]
    created = aggregated_context["created"]
    before_completion = service.get_task_completion_history(mission_id)["task_completion_count"]
    state = service.get_mission_state(mission_id)["mission_state"]
    assert created["active_plan_outcome_aggregation_performed"] is True
    assert created["mission_state_transition_performed"] is False
    assert service.get_mission_state(mission_id)["mission_state"] == state
    assert service.get_task_completion_history(mission_id)["task_completion_count"] == before_completion
