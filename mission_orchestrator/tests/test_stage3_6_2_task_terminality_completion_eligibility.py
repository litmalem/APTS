from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskTerminalityEligibilityConflict,
    MissionTaskTerminalityEligibilityGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_terminality import (
    TASK_TERMINALITY_AUTHORITY,
    TASK_TERMINALITY_CONTRACT_SCHEMA_VERSION,
    TASK_TERMINALITY_GATE_STATUS,
    TASK_TERMINALITY_ID_PREFIX,
    TASK_TERMINALITY_MODE,
    TASK_TERMINALITY_STAGE_SCHEMA_VERSION,
    TERMINALITY_BY_SOURCE_STATUS,
    classify_task_terminality_and_completion_eligibility,
    verify_task_terminality_eligibility_contract,
)
from tests.test_stage3_6_1_canonical_task_outcome_contract_identity import materialize


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR = "stage3.6.2-task-terminality-completion-eligibility"
EVENT_TYPE = "MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED"


def eligibility_request(service, mission_id, active, task_outcome, key: str, **extra):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"task-terminality-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_outcome_id": task_outcome["task_outcome_id"],
        "expected_task_outcome_sha256": task_outcome["canonical_sha256"],
        "evaluated_by": "stage3.6.2-pytest",
        "reason": "derive terminality and completion eligibility from immutable Stage-3.6.1 outcome",
        "metadata": {"stage": "3.6.2", "key": key},
    }
    body.update(extra)
    return body


def evaluate(tmp_path: Path, key: str):
    materialized = materialize(tmp_path, key)
    service, governance, runtime, mission_id, active = materialized[:5]
    task_outcome = materialized[-1]
    body = eligibility_request(service, mission_id, active, task_outcome, key)
    created = service.evaluate_task_terminality_completion_eligibility(mission_id, body)
    return (*materialized, body, created)


@pytest.fixture(scope="module")
def source_context(tmp_path_factory):
    root = tmp_path_factory.mktemp("stage362-source")
    materialized = materialize(root, "shared-source362")
    service, governance, runtime, mission_id, active = materialized[:5]
    task_outcome = materialized[-1]
    body = eligibility_request(service, mission_id, active, task_outcome, "shared-source362")
    return {
        "root": root,
        "materialized": materialized,
        "service": service,
        "governance": governance,
        "runtime": runtime,
        "mission_id": mission_id,
        "active": active,
        "task_outcome": task_outcome,
        "body": body,
    }


@pytest.fixture(scope="module")
def evaluated_context(tmp_path_factory):
    root = tmp_path_factory.mktemp("stage362-evaluated")
    materialized = materialize(root, "shared-evaluated362")
    service, governance, runtime, mission_id, active = materialized[:5]
    task_outcome = materialized[-1]
    body = eligibility_request(service, mission_id, active, task_outcome, "shared-evaluated362")
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    created = service.evaluate_task_terminality_completion_eligibility(mission_id, body)
    gov_after = governance.evaluate_calls
    runtime_after = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    return {
        "root": root,
        "materialized": materialized,
        "service": service,
        "governance": governance,
        "runtime": runtime,
        "mission_id": mission_id,
        "active": active,
        "task_outcome": task_outcome,
        "body": body,
        "created": created,
        "gov_before": gov_before,
        "gov_after": gov_after,
        "runtime_before": runtime_before,
        "runtime_after": runtime_after,
    }


def test_01_health_activates_stage362_migration37_and_durable_store(source_context):
    health = source_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == ["stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_task_terminality_eligibility_gates" in REPOSITORY_STORES
    assert health["task_terminality_stage_schema_version"] == TASK_TERMINALITY_STAGE_SCHEMA_VERSION
    assert health["task_terminality_contract_schema_version"] == TASK_TERMINALITY_CONTRACT_SCHEMA_VERSION
    assert health["task_terminality_identity_prefix"] == TASK_TERMINALITY_ID_PREFIX
    assert health["task_terminality_mode"] == TASK_TERMINALITY_MODE
    assert health["task_terminality_authority"] == TASK_TERMINALITY_AUTHORITY
    assert health["task_terminality_gate_status"] == TASK_TERMINALITY_GATE_STATUS
    assert health["task_terminality_database_migration_level"] == 37
    assert health["task_terminality_persistence_store"] == "mission_task_terminality_eligibility_gates"


def test_02_definition_declares_deterministic_gate_and_reserves_completion_for_363(source_context):
    service, mission_id = source_context["service"], source_context["mission_id"]
    definition = service.get_task_terminality_completion_eligibility_definition(mission_id)[
        "task_terminality_completion_eligibility_definition"
    ]
    assert definition["schema_version"] == TASK_TERMINALITY_CONTRACT_SCHEMA_VERSION
    assert definition["requires_stage361_task_outcome_identity"] is True
    assert definition["requires_active_plan_version"] is True
    assert definition["one_eligibility_gate_per_task_outcome"] is True
    assert definition["terminality_confirmed_from_immutable_source"] is True
    assert definition["completion_eligible_only_for_verified_completed"] is True
    assert definition["task_outcome_acceptance_performed"] is False
    assert definition["task_completion_commit_performed"] is False
    assert definition["dependency_release_performed"] is False
    assert definition["plan_progression_performed"] is False
    assert definition["next_stage"] == "3.6.3"


def test_03_verified_completed_outcome_is_terminal_and_completion_eligible(evaluated_context):
    created = evaluated_context["created"]
    assert created["eligibility_gate_id"].startswith(TASK_TERMINALITY_ID_PREFIX)
    assert created["gate_status"] == TASK_TERMINALITY_GATE_STATUS
    assert created["terminality_confirmed"] is True
    assert created["terminality_status"] == "TERMINAL_SUCCESS"
    assert created["completion_eligibility_status"] == "ELIGIBLE_FOR_COMPLETION_EVALUATION"
    assert created["completion_eligible"] is True
    assert created["eligibility_reason_code"] == "VERIFIED_COMPLETED_OUTCOME"
    assert verify_task_terminality_eligibility_contract(created["task_terminality_eligibility_contract"])


def test_04_contract_is_immutably_bound_to_stage361_outcome_and_active_plan(evaluated_context):
    created = evaluated_context["created"]
    outcome = evaluated_context["task_outcome"]
    active = evaluated_context["active"]
    contract = created["task_terminality_eligibility_contract"]
    identity = contract["identity"]
    source = contract["source_bindings"]
    assert identity["mission_id"] == evaluated_context["mission_id"]
    assert identity["plan_version_record_id"] == active["plan_version_record_id"]
    assert identity["task_outcome_id"] == outcome["task_outcome_id"]
    assert source["active_plan_sha256"] == active["canonical_sha256"]
    assert source["task_outcome_sha256"] == outcome["canonical_sha256"]
    assert source["source_task_outcome_status"] == "VERIFIED_COMPLETED"
    assert source["outcome_classification"] == outcome["outcome_classification"]


def test_05_eligibility_is_not_acceptance_completion_release_or_progression(evaluated_context):
    created = evaluated_context["created"]
    contract = created["task_terminality_eligibility_contract"]
    eligibility = contract["completion_eligibility"]
    boundary = contract["authority_boundary"]
    assert eligibility["eligibility_is_completion_commit"] is False
    assert eligibility["eligibility_is_acceptance_decision"] is False
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
        assert eligibility[key] is False
        assert created[key] is False
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
        assert created[key] is False


def test_06_stale_mission_version_vector_is_rejected(source_context):
    body = deepcopy(source_context["body"])
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        source_context["service"].evaluate_task_terminality_completion_eligibility(source_context["mission_id"], body)


def test_07_stale_active_plan_hash_is_rejected(source_context):
    body = deepcopy(source_context["body"])
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        source_context["service"].evaluate_task_terminality_completion_eligibility(source_context["mission_id"], body)


def test_08_stale_task_outcome_hash_is_rejected(source_context):
    body = deepcopy(source_context["body"])
    body["expected_task_outcome_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="task outcome SHA-256"):
        source_context["service"].evaluate_task_terminality_completion_eligibility(source_context["mission_id"], body)


def test_09_missing_stage361_task_outcome_fails_closed(source_context):
    body = deepcopy(source_context["body"])
    body["expected_task_outcome_id"] = "toutcome-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionTaskTerminalityEligibilityGuardRejected, match="task outcome is missing"):
        source_context["service"].evaluate_task_terminality_completion_eligibility(source_context["mission_id"], body)


def test_10_caller_supplied_terminality_completion_or_side_effect_fields_are_forbidden(source_context):
    forbidden = [
        ("terminality_status", "TERMINAL_SUCCESS"),
        ("completion_eligible", True),
        ("task_outcome_accepted", True),
        ("task_completed", True),
        ("dependency_release", True),
        ("mission_completed", True),
        ("runtime_action", "resume"),
        ("governance_decision", "ALLOW"),
    ]
    for idx, (field, value) in enumerate(forbidden):
        body = deepcopy(source_context["body"])
        body["idempotency_key"] = f"terminality-forbidden362-{idx}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported task terminality/completion eligibility field"):
            source_context["service"].evaluate_task_terminality_completion_eligibility(source_context["mission_id"], body)


def test_11_same_request_is_idempotent_without_duplicate_gate_or_event(evaluated_context):
    service, mission_id = evaluated_context["service"], evaluated_context["mission_id"]
    first = evaluated_context["created"]
    replay = service.evaluate_task_terminality_completion_eligibility(mission_id, deepcopy(evaluated_context["body"]))
    assert replay["idempotent_replay"] is True
    assert replay["eligibility_gate_id"] == first["eligibility_gate_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_task_terminality_completion_eligibility_history(mission_id)["eligibility_gate_count"] == 1
    events = service.get_mission_events(mission_id)["events"]
    assert len([e for e in events if e["event_type"] == EVENT_TYPE]) == 1


def test_12_same_idempotency_key_with_different_request_conflicts(evaluated_context):
    changed = deepcopy(evaluated_context["body"])
    changed["reason"] = "different canonical request"
    with pytest.raises(MissionTaskTerminalityEligibilityConflict, match="idempotency_key"):
        evaluated_context["service"].evaluate_task_terminality_completion_eligibility(
            evaluated_context["mission_id"], changed
        )


def test_13_only_one_immutable_gate_is_allowed_per_stage361_outcome(evaluated_context):
    second = deepcopy(evaluated_context["body"])
    second["idempotency_key"] = "terminality-single-gate362-b"
    second["reason"] = "second gate attempt for same immutable task outcome"
    with pytest.raises(MissionTaskTerminalityEligibilityConflict, match="already has an immutable"):
        evaluated_context["service"].evaluate_task_terminality_completion_eligibility(
            evaluated_context["mission_id"], second
        )


def test_14_evaluation_and_replay_do_not_contact_runtime_or_governance(evaluated_context):
    service = evaluated_context["service"]
    governance = evaluated_context["governance"]
    runtime = evaluated_context["runtime"]
    assert evaluated_context["gov_after"] == evaluated_context["gov_before"]
    assert evaluated_context["runtime_after"] == evaluated_context["runtime_before"]
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    replay = service.evaluate_task_terminality_completion_eligibility(
        evaluated_context["mission_id"], deepcopy(evaluated_context["body"])
    )
    assert governance.evaluate_calls == gov_before
    assert (runtime.health_calls, runtime.result_calls, runtime.control_calls) == runtime_before
    assert replay["governance_query_performed"] is False
    assert replay["runtime_query_performed"] is False
    assert replay["runtime_control_io_performed"] is False
    assert replay["external_network_io_performed"] is False
    assert replay["target_actuation"] is False


def test_15_restart_reads_same_immutable_gate_from_durable_repository(evaluated_context):
    service, mission_id, created = (
        evaluated_context["service"], evaluated_context["mission_id"], evaluated_context["created"]
    )
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=service.repository.sqlite_path))
    fetched = restarted.get_task_terminality_completion_eligibility(mission_id, created["eligibility_gate_id"])
    assert fetched["eligibility_gate_id"] == created["eligibility_gate_id"]
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert verify_task_terminality_eligibility_contract(fetched["task_terminality_eligibility_contract"])
    assert fetched["completion_eligible"] is True
    assert fetched["task_completion_commit_performed"] is False


def test_16_lineage_event_is_exactly_once_and_causally_bound_to_gate(evaluated_context):
    service, mission_id, created = (
        evaluated_context["service"], evaluated_context["mission_id"], evaluated_context["created"]
    )
    events = service.get_mission_events(mission_id)["events"]
    selected = [e for e in events if e["event_type"] == EVENT_TYPE]
    assert len(selected) == 1
    event = selected[0]
    assert event["causation_id"] == created["eligibility_gate_id"]
    assert event["payload"]["eligibility_gate_id"] == created["eligibility_gate_id"]
    assert event["payload"]["task_outcome_id"] == created["task_outcome_id"]
    assert event["payload"]["canonical_sha256"] == created["canonical_sha256"]
    assert event["payload"]["completion_eligible"] is True
    assert event["payload"]["task_completion_commit_performed"] is False
    assert event["payload"]["dependency_release_performed"] is False


def test_17_repository_projection_persists_gate_and_passes_integrity(evaluated_context):
    service, mission_id, created = (
        evaluated_context["service"], evaluated_context["mission_id"], evaluated_context["created"]
    )
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_task_terminality_eligibility_gates"] == 1
    manifest = repo["persistence_manifest"]
    gates = manifest["task_terminality_completion_eligibility_store"]["gates"]
    assert gates[0]["eligibility_gate_id"] == created["eligibility_gate_id"]
    assert gates[0]["task_outcome_id"] == created["task_outcome_id"]
    checks = {item["check"]: item for item in repo["integrity_checks"]}
    assert checks["task_terminality_completion_eligibility_store"]["status"] == "PASS"


def test_18_persisted_gate_tampering_breaks_repository_integrity(tmp_path):
    result = evaluate(tmp_path, "tamper362")
    service, mission_id, created = result[0], result[3], result[-1]
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute(
            "UPDATE mission_task_terminality_eligibility_gates SET completion_eligible=? WHERE eligibility_gate_id=?",
            (0, created["eligibility_gate_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_19_api_routes_migration_definition_and_history_are_registered(evaluated_context):
    service, mission_id, created = (
        evaluated_context["service"], evaluated_context["mission_id"], evaluated_context["created"]
    )
    fetched = service.get_task_terminality_completion_eligibility(mission_id, created["eligibility_gate_id"])
    history = service.get_task_terminality_completion_eligibility_history(mission_id)
    definition = service.get_task_terminality_completion_eligibility_definition(mission_id)
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert history["eligibility_gate_count"] == 1
    assert definition["registered_eligibility_gate_count"] == 1
    api_source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert "task-terminality-eligibility" in api_source
    assert "task-terminality-eligibility-definition" in api_source
    migration = Path("migrations/037_stage3_6_2_task_terminality_completion_eligibility.sql")
    assert migration.is_file()
    migration_text = migration.read_text(encoding="utf-8")
    assert "mission_task_terminality_eligibility_gates" in migration_text
    assert "UNIQUE" in migration_text.upper()


def test_20_terminal_classification_matrix_is_complete_deterministic_and_fail_closed():
    expected = {
        "VERIFIED_COMPLETED": ("TERMINAL_SUCCESS", "ELIGIBLE_FOR_COMPLETION_EVALUATION", True),
        "VERIFIED_FAILED": ("TERMINAL_FAILURE", "NOT_ELIGIBLE_FOR_COMPLETION", False),
        "VERIFIED_CANCELLED": ("TERMINAL_CANCELLED", "NOT_ELIGIBLE_FOR_COMPLETION", False),
        "VERIFIED_TIMED_OUT": ("TERMINAL_TIMED_OUT", "NOT_ELIGIBLE_FOR_COMPLETION", False),
    }
    assert set(TERMINALITY_BY_SOURCE_STATUS) == set(expected)
    for source_status, (terminality, eligibility, eligible) in expected.items():
        first = classify_task_terminality_and_completion_eligibility(source_status)
        second = classify_task_terminality_and_completion_eligibility(source_status)
        assert first == second
        assert first["terminality_status"] == terminality
        assert first["completion_eligibility_status"] == eligibility
        assert first["completion_eligible"] is eligible
    with pytest.raises(MissionValidationError, match="not a canonical terminal"):
        classify_task_terminality_and_completion_eligibility("RUNNING")
