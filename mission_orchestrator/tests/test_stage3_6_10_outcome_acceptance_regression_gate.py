from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.completion_readiness import derive_completion_readiness
from mission_orchestrator.outcome_acceptance_gate import (
    OUTCOME_ACCEPTANCE_GATE_BASELINE,
    OUTCOME_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
    OUTCOME_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    OUTCOME_ACCEPTANCE_GATE_MODE,
    OUTCOME_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
    OUTCOME_ACCEPTANCE_GATE_SCHEMA_VERSION,
    REQUIRED_OUTCOME_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_6_CONTROLS,
    outcome_acceptance_gate_contract,
)
from mission_orchestrator.outcome_lineage import OUTCOME_RECOVERY_EVENT_TYPE
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_6_9_outcome_lineage_replay_recovery import provision_completed_source


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE3610 = "stage3.6.10-outcome-acceptance-regression-gate"
STAGE369 = "stage3.6.9-outcome-lineage-replay-recovery"


@pytest.fixture(scope="module")
def closed_context(tmp_path_factory):
    ctx = provision_completed_source(tmp_path_factory.mktemp("stage3610-closed"), "shared-closed3610")
    governance_before = ctx["governance"].evaluate_calls
    runtime_before = (
        ctx["runtime"].health_calls,
        ctx["runtime"].result_calls,
        ctx["runtime"].control_calls,
    )
    checkpoint = ctx["service"].create_outcome_recovery_checkpoint(
        ctx["mission_id"], deepcopy(ctx["recovery_body"])
    )
    return {
        **ctx,
        "outcome_checkpoint": checkpoint,
        "governance_before": governance_before,
        "governance_after": ctx["governance"].evaluate_calls,
        "runtime_before": runtime_before,
        "runtime_after": (
            ctx["runtime"].health_calls,
            ctx["runtime"].result_calls,
            ctx["runtime"].control_calls,
        ),
    }


def test_01_health_activates_stage3610_closure_without_new_migration(closed_context):
    health = closed_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][59:70] == [STAGE3610, "stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["supported_controls"][-1] == CONTROL
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["stage3_6_outcome_acceptance_gate_schema_version"] == OUTCOME_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert health["stage3_6_outcome_acceptance_gate_mode"] == OUTCOME_ACCEPTANCE_GATE_MODE
    assert health["stage3_6_outcome_acceptance_gate_baseline"] == OUTCOME_ACCEPTANCE_GATE_BASELINE
    assert health["stage3_6_outcome_acceptance_gate_runtime_change_mode"] == OUTCOME_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE
    assert health["stage3_6_outcome_acceptance_gate_database_change_mode"] == OUTCOME_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE
    assert health["stage3_6_outcome_acceptance_gate_expected_migration_level"] == 44
    assert health["stage3_6_outcome_acceptance_gate_declared_only"] is True
    assert health["stage3_6_outcome_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_6_outcome_acceptance_gate_external_execution_required"] is True


def test_02_static_contract_requires_complete_stage36_and_external_acceptance():
    contract = outcome_acceptance_gate_contract()
    assert contract["schema_version"] == OUTCOME_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert contract["mode"] == OUTCOME_ACCEPTANCE_GATE_MODE
    assert contract["baseline"] == "STAGE_3_6_1_THROUGH_3_6_9"
    assert contract["required_prior_controls"] == list(REQUIRED_STAGE3_6_CONTROLS)
    assert contract["required_gates"] == list(REQUIRED_OUTCOME_ACCEPTANCE_GATES)
    assert len(contract["required_gates"]) == len(set(contract["required_gates"])) == 17
    assert contract["expected_repository_migration_level"] == OUTCOME_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 44
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert contract["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert contract["stage36_completion_authority_source"] == "STAGE_3_6_8_VERIFIED_COMPLETION_DECLARATION"
    assert contract["stage36_lifecycle_handoff_boundary"] == "STAGE_3_6_8_CANONICAL_STAGE3_2_LIFECYCLE_COMMAND_PATH"
    assert contract["stage36_replay_recovery_boundary"] == "STAGE_3_6_9_READ_ONLY_DURABLE_RECONSTRUCTION"


def test_03_success_trajectory_materializes_complete_stage361_through_369_stack(closed_context):
    service = closed_context["service"]
    mission_id = closed_context["mission_id"]
    assert service.get_task_outcome_history(mission_id)["task_outcome_count"] == 1
    assert service.get_task_terminality_completion_eligibility_history(mission_id)["eligibility_gate_count"] == 1
    assert service.get_task_evidence_binding_verification_history(mission_id)["verification_count"] == 1
    assert service.get_task_completion_history(mission_id)["task_completion_count"] == 1
    assert service.get_mission_outcome_aggregation_history(mission_id)["aggregation_count"] == 1
    assert service.get_mission_success_evaluation_history(mission_id)["evaluation_count"] == 1
    assert service.get_completion_readiness_history(mission_id)["decision_count"] == 1
    assert service.get_verified_completion_history(mission_id)["declaration_count"] == 1
    assert service.get_outcome_recovery_history(mission_id)["checkpoint_count"] == 1
    assert closed_context["declaration"]["final_mission_state"]["state"] == "COMPLETED"
    assert closed_context["outcome_checkpoint"]["recovery_state"]["mission_state"] == "COMPLETED"


def test_04_outcome_lineage_replay_and_recovery_close_same_completed_trajectory(closed_context):
    service = closed_context["service"]
    mission_id = closed_context["mission_id"]
    checkpoint = closed_context["outcome_checkpoint"]
    lineage = service.get_outcome_event_lineage(mission_id)
    replay = service.get_outcome_event_replay(mission_id)
    recovered = service.get_outcome_recovery(mission_id)
    assert lineage["integrity_status"] == "PASS"
    assert lineage["full_mission_event_chain_verified"] is True
    assert lineage["outcome_event_count"] == 10
    assert lineage["outcome_events"][-1]["event_type"] == OUTCOME_RECOVERY_EVENT_TYPE
    assert lineage["outcome_events"][-1]["artifact_id"] == checkpoint["checkpoint_id"]
    assert replay["replay"]["outcome_event_count"] == lineage["outcome_event_count"]
    assert replay["replay"]["outcome_event_tip_sha256"] == lineage["outcome_event_tip_sha256"]
    assert replay["read_only"] is True
    assert replay["side_effects_performed"] is False
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["durable_repository_is_source_of_truth"] is True


def test_05_replay_and_recovery_reads_do_not_mutate_repository_or_contact_runtime_or_governance(closed_context):
    service = closed_context["service"]
    mission_id = closed_context["mission_id"]
    repo_before = service.get_mission_repository(mission_id)
    events_before = service.get_mission_events(mission_id)["event_count"]
    gov_before = closed_context["governance"].evaluate_calls
    runtime_before = (
        closed_context["runtime"].health_calls,
        closed_context["runtime"].result_calls,
        closed_context["runtime"].control_calls,
    )
    service.get_outcome_event_replay(mission_id)
    service.get_outcome_recovery(mission_id)
    service.get_outcome_event_replay(mission_id)
    service.get_outcome_recovery(mission_id)
    repo_after = service.get_mission_repository(mission_id)
    assert repo_after["repository_sha256"] == repo_before["repository_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == events_before
    assert closed_context["governance"].evaluate_calls == gov_before
    assert (
        closed_context["runtime"].health_calls,
        closed_context["runtime"].result_calls,
        closed_context["runtime"].control_calls,
    ) == runtime_before


def test_06_restart_reconstructs_verified_completion_without_runtime_governance_redispatch_or_resumption(closed_context):
    restarted = CanonicalMissionService(
        repository=MissionRepository(sqlite_path=closed_context["service"].repository.sqlite_path)
    )
    recovered = restarted.get_outcome_recovery(closed_context["mission_id"])
    assert recovered["checkpoint_id"] == closed_context["outcome_checkpoint"]["checkpoint_id"]
    assert recovered["durable_repository_is_source_of_truth"] is True
    assert recovered["runtime_query_performed"] is False
    assert recovered["runtime_control_io_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert recovered["dispatch_redelivery_performed"] is False
    assert recovered["new_execution_attempt_created"] is False
    assert recovered["new_target_action_dispatch_performed"] is False
    assert recovered["mission_state_transition_performed"] is False
    assert recovered["mission_success_completion_authority_exercised"] is False
    assert recovered["target_actuation"] is False


def test_07_blocked_terminal_lifecycle_states_cannot_be_elevated_to_completion_ready(closed_context):
    evaluation = closed_context["evaluation"]
    for state in ("FAILED", "ABORTED"):
        decision = derive_completion_readiness(mission_state=state, evaluation=evaluation)
        assert decision["completion_ready"] is False
        assert decision["readiness_result"] == "BLOCKED"
        assert decision["blockers"][0]["code"] == "MISSION_STATE_NOT_RUNNING"


def test_08_stage36_authority_matrix_preserves_single_completion_authority_and_non_actuating_recovery(closed_context):
    health = closed_context["service"].health()
    assert health["task_outcome_acceptance_performed"] is False
    assert health["task_outcome_mission_success_completion_authority_exercised"] is False
    assert health["task_terminality_completion_commit_performed"] is False
    assert health["task_terminality_mission_success_completion_authority_exercised"] is False
    assert health["task_evidence_binding_task_completion_commit_performed"] is False
    assert health["task_evidence_binding_mission_success_completion_authority_exercised"] is False
    assert health["task_completion_task_completion_commit_performed"] is True
    assert health["task_completion_mission_success_completion_authority_exercised"] is False
    assert health["mission_outcome_aggregation_success_criteria_evaluation_performed"] is False
    assert health["mission_outcome_aggregation_mission_success_completion_authority_exercised"] is False
    assert health["mission_success_evaluation_performed"] is True
    assert health["mission_success_evaluation_mission_completion_readiness_decision_performed"] is False
    assert health["mission_success_evaluation_mission_success_completion_authority_exercised"] is False
    assert health["completion_readiness_decision_performed"] is True
    assert health["completion_readiness_mission_success_completion_authority_exercised"] is False
    assert health["verified_completion_mission_success_completion_authority_exercised"] is True
    assert health["verified_completion_direct_state_transition_bypass_used"] is False
    assert health["outcome_replay_read_only"] is True
    assert health["outcome_recovery_mission_success_completion_authority_exercised"] is False
    assert health["outcome_recovery_is_dispatch"] is False
    assert health["outcome_recovery_is_runtime_resumption"] is False
    assert health["outcome_recovery_is_lifecycle_transition"] is False


def test_09_repository_manifest_closes_every_stage36_durable_store_with_integrity_pass(closed_context):
    repo = closed_context["service"].get_mission_repository(closed_context["mission_id"])
    counts = repo["record_counts"]
    manifest = repo["persistence_manifest"]
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    expected_counts = {
        "mission_task_outcomes": 1,
        "mission_task_terminality_eligibility_gates": 1,
        "mission_task_evidence_binding_verifications": 1,
        "mission_task_completion_commits": 1,
        "mission_outcome_aggregations": 1,
        "mission_success_criteria_evaluations": 1,
        "mission_completion_readiness_decisions": 1,
        "mission_verified_completion_declarations": 1,
        "mission_outcome_recovery_checkpoints": 1,
    }
    for store, expected in expected_counts.items():
        assert counts[store] == expected
    for key in (
        "canonical_task_outcome_store",
        "task_terminality_completion_eligibility_store",
        "task_evidence_binding_verification_store",
        "dependency_aware_task_completion_store",
        "mission_outcome_aggregation_store",
        "mission_success_criteria_evaluation_store",
        "mission_completion_readiness_store",
        "mission_verified_completion_declaration_store",
        "outcome_lineage_replay_recovery_store",
    ):
        assert key in manifest


def test_10_stage3610_adds_no_migration_or_durable_store():
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert len(migrations) == 53
    assert migrations[-1].name == "053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql"
    assert not list(Path("migrations").glob("045_stage3_6_10_*.sql"))
    assert "mission_outcome_recovery_checkpoints" in REPOSITORY_STORES
    contract = outcome_acceptance_gate_contract()
    assert contract["new_durable_store_added"] is False
    assert contract["new_database_migration_added"] is False


def test_11_closure_gate_adds_no_new_outcome_authority_runtime_io_lifecycle_path_or_actuation(closed_context):
    health = closed_context["service"].health()
    false_fields = (
        "stage3_6_outcome_acceptance_gate_new_task_outcome_authority_added",
        "stage3_6_outcome_acceptance_gate_new_terminality_classification_authority_added",
        "stage3_6_outcome_acceptance_gate_new_evidence_verification_authority_added",
        "stage3_6_outcome_acceptance_gate_new_task_completion_authority_added",
        "stage3_6_outcome_acceptance_gate_new_mission_outcome_aggregation_added",
        "stage3_6_outcome_acceptance_gate_new_success_criteria_evaluation_added",
        "stage3_6_outcome_acceptance_gate_new_completion_readiness_decision_added",
        "stage3_6_outcome_acceptance_gate_new_mission_success_completion_authority_added",
        "stage3_6_outcome_acceptance_gate_new_lifecycle_transition_path_added",
        "stage3_6_outcome_acceptance_gate_new_governance_query_added",
        "stage3_6_outcome_acceptance_gate_new_runtime_query_added",
        "stage3_6_outcome_acceptance_gate_new_runtime_control_io_added",
        "stage3_6_outcome_acceptance_gate_new_external_network_io_added",
        "stage3_6_outcome_acceptance_gate_new_dispatch_redelivery_added",
        "stage3_6_outcome_acceptance_gate_new_execution_attempt_added",
        "stage3_6_outcome_acceptance_gate_new_target_action_dispatch_added",
        "stage3_6_outcome_acceptance_gate_new_target_actuation_added",
        "stage3_6_outcome_acceptance_gate_new_llm_reinterpretation_added",
        "stage3_6_outcome_acceptance_gate_new_durable_store_added",
        "stage3_6_outcome_acceptance_gate_new_database_migration_added",
        "stage3_6_outcome_acceptance_gate_task_outcome_is_task_completion",
        "stage3_6_outcome_acceptance_gate_terminality_is_task_acceptance",
        "stage3_6_outcome_acceptance_gate_evidence_verification_is_task_completion",
        "stage3_6_outcome_acceptance_gate_task_completion_is_mission_completion",
        "stage3_6_outcome_acceptance_gate_aggregation_is_success_evaluation",
        "stage3_6_outcome_acceptance_gate_success_evaluation_is_completion_authority",
        "stage3_6_outcome_acceptance_gate_readiness_is_completion_authority",
        "stage3_6_outcome_acceptance_gate_verified_completion_direct_state_transition_bypass_used",
        "stage3_6_outcome_acceptance_gate_replay_is_outcome_processing",
        "stage3_6_outcome_acceptance_gate_recovery_is_completion_authority",
        "stage3_6_outcome_acceptance_gate_recovery_is_dispatch",
        "stage3_6_outcome_acceptance_gate_recovery_is_runtime_resumption",
        "stage3_6_outcome_acceptance_gate_recovery_is_lifecycle_transition",
        "stage3_6_outcome_acceptance_gate_closure_gate_is_outcome_processing",
        "stage3_6_outcome_acceptance_gate_closure_gate_is_completion_authority",
    )
    for field in false_fields:
        assert health[field] is False, field
    assert health["stage3_6_outcome_acceptance_gate_verified_completion_is_mission_success_completion_authority"] is True


def test_12_stage36_supported_control_tail_is_complete_ordered_and_closure_cannot_self_certify(closed_context):
    health = closed_context["service"].health()
    expected_tail = [*REQUIRED_STAGE3_6_CONTROLS, STAGE3610]
    tail = health["supported_controls"][50:60]
    assert tail == expected_tail
    assert tail[-2] == STAGE369
    assert tail[-1] == STAGE3610
    assert health["supported_controls"][-1] == CONTROL
    assert len(tail) == len(set(tail)) == 10
    contract = outcome_acceptance_gate_contract()
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert "acceptance_status" not in contract
    assert "passed" not in contract
