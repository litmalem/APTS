from __future__ import annotations

from pathlib import Path

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.execution_acceptance_gate import (
    EXECUTION_ACCEPTANCE_GATE_BASELINE,
    EXECUTION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
    EXECUTION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    EXECUTION_ACCEPTANCE_GATE_MODE,
    EXECUTION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
    EXECUTION_ACCEPTANCE_GATE_SCHEMA_VERSION,
    REQUIRED_EXECUTION_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_5_CONTROLS,
    execution_acceptance_gate_contract,
)
from mission_orchestrator.execution_lineage import EXECUTION_RECOVERY_EVENT_TYPE
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_8_timeout_cancellation_abort_failure_propagation import (
    ACTION_ABORT,
    capture_terminal,
    propagation_request,
    provision_358,
    termination_request,
)
from tests.test_stage3_5_9_execution_event_lineage_replay_recovery import (
    complete_success,
    recovery_request,
)


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE359 = "stage3.5.9-execution-event-lineage-replay-recovery"


def close_success(tmp_path, key: str):
    service, governance, runtime, mission_id, active, attempt, delivery, running, result, propagation = complete_success(
        tmp_path, key
    )
    checkpoint = service.create_execution_recovery_checkpoint(
        mission_id,
        recovery_request(
            service,
            mission_id,
            active,
            attempt,
            delivery,
            running,
            result,
            propagation,
            key,
        ),
    )
    return service, governance, runtime, mission_id, active, attempt, delivery, running, result, propagation, checkpoint


def test_01_health_activates_stage3510_closure_without_new_migration(tmp_path):
    service, *_ = provision_358(tmp_path, "health3510")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][40:50] == [*REQUIRED_STAGE3_5_CONTROLS, "stage3.5.10-execution-dispatch-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["stage3_5_execution_acceptance_gate_schema_version"] == EXECUTION_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert health["stage3_5_execution_acceptance_gate_mode"] == EXECUTION_ACCEPTANCE_GATE_MODE
    assert health["stage3_5_execution_acceptance_gate_baseline"] == EXECUTION_ACCEPTANCE_GATE_BASELINE
    assert health["stage3_5_execution_acceptance_gate_runtime_change_mode"] == EXECUTION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE
    assert health["stage3_5_execution_acceptance_gate_database_change_mode"] == EXECUTION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE
    assert health["stage3_5_execution_acceptance_gate_expected_migration_level"] == 35
    assert health["stage3_5_execution_acceptance_gate_declared_only"] is True
    assert health["stage3_5_execution_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_5_execution_acceptance_gate_external_execution_required"] is True


def test_02_static_contract_requires_complete_stage35_and_external_acceptance():
    contract = execution_acceptance_gate_contract()
    assert contract["schema_version"] == EXECUTION_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert contract["mode"] == EXECUTION_ACCEPTANCE_GATE_MODE
    assert contract["baseline"] == "STAGE_3_5_1_THROUGH_3_5_9"
    assert contract["required_prior_controls"] == list(REQUIRED_STAGE3_5_CONTROLS)
    assert contract["required_gates"] == list(REQUIRED_EXECUTION_ACCEPTANCE_GATES)
    assert len(contract["required_gates"]) == len(set(contract["required_gates"]))
    assert contract["expected_repository_migration_level"] == EXECUTION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 35
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert contract["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert contract["stage35_execution_authority_source"] == "STAGE_3_5_3_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE_ALLOW"
    assert contract["stage35_target_dispatch_boundary"] == "STAGE_3_5_5_RUNTIME_DELIVERY"
    assert contract["stage35_replay_recovery_boundary"] == "STAGE_3_5_9_READ_ONLY_DURABLE_RECONSTRUCTION"


def test_03_success_trajectory_materializes_complete_stage351_through_359_stack(tmp_path):
    service, _, _, mission_id, _, attempt, delivery, running, result, propagation, checkpoint = close_success(
        tmp_path, "stack3510"
    )
    assert service.get_execution_dispatch_history(mission_id)["execution_dispatch_contract_count"] == 1
    assert service.get_dispatch_eligibility_history(mission_id)["dispatch_eligibility_gate_count"] == 1
    assert service.get_pre_dispatch_revalidation_history(mission_id)["revalidation_count"] == 1
    assert service.get_execution_attempt_history(mission_id)["execution_attempt_count"] == 1
    assert service.get_execution_delivery_history(mission_id)["execution_delivery_count"] == 1
    assert service.get_execution_running_projection_history(mission_id)["running_projection_count"] == 1
    assert service.get_execution_result_capture_history(mission_id)["result_capture_count"] == 1
    assert service.get_execution_termination_control_history(mission_id)["termination_control_count"] == 0
    assert service.get_execution_outcome_propagation_history(mission_id)["outcome_propagation_count"] == 1
    assert service.get_execution_recovery_history(mission_id)["checkpoint_count"] == 1
    assert delivery["execution_attempt_id"] == attempt["execution_attempt_id"]
    assert running["execution_attempt_id"] == attempt["execution_attempt_id"]
    assert result["execution_attempt_id"] == attempt["execution_attempt_id"]
    assert propagation["execution_attempt_id"] == attempt["execution_attempt_id"]
    assert checkpoint["execution_attempt_id"] == attempt["execution_attempt_id"]
    assert checkpoint["outcome_propagation_id"] == propagation["outcome_propagation_id"]


def test_04_execution_lineage_replay_and_recovery_close_same_success_trajectory(tmp_path):
    service, _, _, mission_id, *_, checkpoint = close_success(tmp_path, "lineage3510")
    lineage = service.get_execution_event_lineage(mission_id)
    replay = service.get_execution_event_replay(mission_id)
    recovered = service.recover_execution_state(mission_id)
    assert lineage["integrity_status"] == "PASS"
    assert lineage["full_mission_event_chain_verified"] is True
    assert lineage["execution_event_count"] == 9
    assert lineage["execution_events"][-1]["event_type"] == EXECUTION_RECOVERY_EVENT_TYPE
    assert lineage["execution_events"][-1]["artifact_id"] == checkpoint["checkpoint_id"]
    assert replay["replay"]["execution_event_count"] == lineage["execution_event_count"]
    assert replay["replay"]["execution_event_tip_sha256"] == lineage["execution_event_tip_sha256"]
    assert replay["read_only"] is True
    assert replay["side_effects_performed"] is False
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["reconstructed_from_durable_repository"] is True


def test_05_replay_and_recovery_reads_do_not_mutate_repository_or_contact_runtime(tmp_path):
    service, _, runtime, mission_id, *rest = close_success(tmp_path, "readonly3510")
    repo_before = service.get_mission_repository(mission_id)
    events_before = service.get_mission_events(mission_id)["event_count"]
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    service.get_execution_event_replay(mission_id)
    service.recover_execution_state(mission_id)
    service.get_execution_event_replay(mission_id)
    service.recover_execution_state(mission_id)
    repo_after = service.get_mission_repository(mission_id)
    runtime_after = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    assert repo_after["repository_sha256"] == repo_before["repository_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == events_before
    assert runtime_after == runtime_before


def test_06_restart_reconstructs_terminal_execution_without_runtime_or_governance_work(tmp_path):
    service, governance, runtime, mission_id, *rest = close_success(tmp_path, "restart3510")
    checkpoint = rest[-1]
    db = service.repository.sqlite_path
    gov_before = governance.evaluate_calls
    runtime_before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=db))
    recovered = restarted.recover_execution_state(mission_id)
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["reconstructed_from_durable_repository"] is True
    assert recovered["runtime_health_probe_performed"] is False
    assert recovered["runtime_result_query_performed"] is False
    assert recovered["runtime_control_io_performed"] is False
    assert recovered["external_network_io_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert recovered["dispatch_redelivery_performed"] is False
    assert recovered["new_execution_attempt_created"] is False
    assert recovered["new_target_action_dispatch_performed"] is False
    assert recovered["target_actuation"] is False
    assert governance.evaluate_calls == gov_before
    assert (runtime.health_calls, runtime.result_calls, runtime.control_calls) == runtime_before


def test_07_abort_trajectory_closes_with_canonical_failure_semantics_and_recovery(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "abort3510")
    termination = service.control_running_execution(
        mission_id,
        termination_request(service, mission_id, active, attempt, delivery, running, "abort3510", ACTION_ABORT),
    )
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "abort3510", "CANCELLED")
    propagation = service.propagate_execution_outcome(
        mission_id,
        propagation_request(service, mission_id, active, attempt, result, "abort3510"),
    )
    checkpoint = service.create_execution_recovery_checkpoint(
        mission_id,
        recovery_request(
            service,
            mission_id,
            active,
            attempt,
            delivery,
            running,
            result,
            propagation,
            "abort3510",
            term_count=1,
        ),
    )
    recovered = service.recover_execution_state(mission_id)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "ABORTED"
    assert termination["termination_control_id"] == checkpoint["termination_control_id"]
    assert propagation["resulting_mission_state"] == "ABORTED"
    assert recovered["recovery_state"]["resulting_mission_state"] == "ABORTED"
    assert recovered["failure_propagation_performed"] is False
    assert recovered["mission_state_transition_performed"] is False


def test_08_stage35_authority_matrix_preserves_exact_dispatch_and_runtime_boundaries(tmp_path):
    health = provision_358(tmp_path, "matrix3510")[0].health()
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["execution_dispatch_contract_is_dispatch"] is False
    assert health["dispatch_eligibility_is_execution_authorization"] is False
    assert health["pre_dispatch_governance_allow_grants_execution_authorization"] is True
    assert health["pre_dispatch_governance_authorization_is_dispatch"] is False
    assert health["execution_attempt_durable_dispatch_commit_performed"] is True
    assert health["execution_attempt_target_delivery_performed"] is False
    assert health["execution_delivery_target_delivery_performed"] is True
    assert health["execution_delivery_target_action_dispatch_performed"] is True
    assert health["execution_delivery_target_actuation"] is False
    assert health["running_execution_projection_is_observation_not_execution_authority"] is True
    assert health["running_execution_dispatch_redelivery_performed"] is False
    assert health["execution_result_is_not_task_completion_authority"] is True
    assert health["execution_result_mission_state_transition_performed"] is False
    assert health["execution_outcome_success_does_not_imply_mission_completion"] is True
    assert health["execution_replay_is_execution"] is False
    assert health["execution_recovery_is_authorization"] is False
    assert health["execution_recovery_is_dispatch"] is False
    assert health["execution_recovery_is_runtime_resumption"] is False


def test_09_repository_manifest_closes_all_stage35_durable_stores_with_integrity_pass(tmp_path):
    service, _, _, mission_id, *rest = close_success(tmp_path, "repo3510")
    repo = service.get_mission_repository(mission_id)
    counts = repo["record_counts"]
    manifest = repo["persistence_manifest"]
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert counts["mission_execution_dispatch_contracts"] == 1
    assert counts["mission_execution_dispatch_eligibility_gates"] == 1
    assert counts["mission_pre_dispatch_governance_revalidations"] == 1
    assert counts["mission_execution_attempts"] == 1
    assert counts["mission_execution_deliveries"] == 1
    assert counts["mission_execution_running_projections"] == 1
    assert counts["mission_execution_result_captures"] == 1
    assert counts["mission_execution_termination_controls"] == 0
    assert counts["mission_execution_outcome_propagations"] == 1
    assert counts["mission_execution_recovery_checkpoints"] == 1
    for key in (
        "execution_dispatch_contract_store",
        "dispatch_eligibility_execution_preconditions_store",
        "authoritative_pre_dispatch_governance_revalidation_store",
        "idempotent_dispatch_execution_attempt_store",
        "dispatch_delivery_execution_acknowledgement_store",
        "running_execution_state_heartbeat_projection_store",
        "execution_result_evidence_artifact_capture_store",
        "execution_timeout_cancellation_abort_control_store",
        "execution_terminal_outcome_failure_propagation_store",
        "execution_event_lineage_replay_recovery_store",
    ):
        assert key in manifest


def test_10_stage3510_adds_no_migration_or_durable_store():
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert len(migrations) == 53
    assert migrations[34].name == "035_stage3_5_9_execution_event_lineage_replay_recovery.sql"
    assert migrations[35].name == "036_stage3_6_1_canonical_task_outcome_contract_identity.sql"
    assert migrations[36].name == "037_stage3_6_2_task_terminality_completion_eligibility.sql"
    assert migrations[37].name == "038_stage3_6_3_evidence_binding_verification.sql"
    assert migrations[38].name == "039_stage3_6_4_dependency_aware_task_completion.sql"
    assert migrations[39].name == "040_stage3_6_5_mission_outcome_aggregation.sql"
    assert migrations[40].name == "041_stage3_6_6_mission_success_criteria_evaluation.sql"
    assert migrations[41].name == "042_stage3_6_7_completion_readiness_blockers.sql"
    assert migrations[42].name == "043_stage3_6_8_verified_completion_declaration_lifecycle_handoff.sql"
    assert migrations[43].name == "044_stage3_6_9_outcome_lineage_replay_recovery.sql"
    assert migrations[44].name == "045_stage3_7_1_canonical_adaptation_replan_contract_identity.sql"
    assert migrations[45].name == "046_stage3_7_2_adaptation_trigger_detection_classification.sql"
    assert migrations[46].name == "047_stage3_7_3_replan_eligibility_governance_gate.sql"
    assert migrations[47].name == "048_stage3_7_4_canonical_replan_snapshot_context_binding.sql"
    assert not list(Path("migrations").glob("036_stage3_5_10_*.sql"))
    assert "mission_execution_recovery_checkpoints" in REPOSITORY_STORES
    contract = execution_acceptance_gate_contract()
    assert contract["new_durable_store_added"] is False
    assert contract["new_database_migration_added"] is False


def test_11_closure_gate_adds_no_new_execution_runtime_io_lifecycle_or_actuation_authority(tmp_path):
    health = provision_358(tmp_path, "nonew3510")[0].health()
    fields = (
        "stage3_5_execution_acceptance_gate_new_execution_authorization_authority_added",
        "stage3_5_execution_acceptance_gate_new_governance_query_added",
        "stage3_5_execution_acceptance_gate_new_execution_dispatch_contract_added",
        "stage3_5_execution_acceptance_gate_new_dispatch_eligibility_gate_added",
        "stage3_5_execution_acceptance_gate_new_execution_attempt_added",
        "stage3_5_execution_acceptance_gate_new_runtime_endpoint_resolution_added",
        "stage3_5_execution_acceptance_gate_new_runtime_health_probe_added",
        "stage3_5_execution_acceptance_gate_new_runtime_delivery_added",
        "stage3_5_execution_acceptance_gate_new_runtime_execution_state_query_added",
        "stage3_5_execution_acceptance_gate_new_runtime_result_query_added",
        "stage3_5_execution_acceptance_gate_new_runtime_control_io_added",
        "stage3_5_execution_acceptance_gate_new_external_network_io_added",
        "stage3_5_execution_acceptance_gate_new_dispatch_redelivery_added",
        "stage3_5_execution_acceptance_gate_new_runtime_resumption_added",
        "stage3_5_execution_acceptance_gate_new_target_action_dispatch_added",
        "stage3_5_execution_acceptance_gate_new_target_actuation_added",
        "stage3_5_execution_acceptance_gate_new_mission_state_transition_added",
        "stage3_5_execution_acceptance_gate_new_failure_propagation_added",
        "stage3_5_execution_acceptance_gate_new_mission_success_completion_authority_added",
        "stage3_5_execution_acceptance_gate_new_durable_store_added",
        "stage3_5_execution_acceptance_gate_new_database_migration_added",
        "stage3_5_execution_acceptance_gate_closure_gate_is_execution",
    )
    for field in fields:
        assert health[field] is False


def test_12_stage35_supported_control_tail_is_complete_ordered_and_closed(tmp_path):
    health = provision_358(tmp_path, "tail3510")[0].health()
    expected_tail = [
        *REQUIRED_STAGE3_5_CONTROLS,
        "stage3.5.10-execution-dispatch-acceptance-regression-gate",
        "stage3.6.1-canonical-task-outcome-contract-identity",
        "stage3.6.2-task-terminality-completion-eligibility",
        "stage3.6.3-evidence-binding-verification",
        "stage3.6.4-dependency-aware-task-completion",
        "stage3.6.5-mission-outcome-aggregation",
        "stage3.6.6-mission-success-criteria-evaluation",
        "stage3.6.7-completion-readiness-blockers",
        "stage3.6.8-verified-completion-declaration-lifecycle-handoff",
        "stage3.6.9-outcome-lineage-replay-recovery",
        "stage3.6.10-outcome-acceptance-regression-gate",
        "stage3.7.1-canonical-adaptation-replan-contract-identity",
        "stage3.7.2-adaptation-trigger-detection-classification",
        "stage3.7.3-replan-eligibility-governance-gate",
        "stage3.7.4-canonical-replan-snapshot-context-binding",
        "stage3.7.5-deterministic-replan-candidate-generation",
        "stage3.7.6-replan-candidate-validation-delta-feasibility-gate",
        "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization",
        "stage3.7.8-atomic-replan-commit-supersession-handoff",
        "stage3.7.9-adapt-replan-lineage-replay-recovery",
        "stage3.7.10-adapt-replan-acceptance-regression-gate",
        "stage3.8.1-canonical-observability-trace-identity-contract",
        "stage3.8.2-event-normalization-ingestion",
        "stage3.8.3-global-causal-lineage-graph",
        "stage3.8.4-live-mission-state-execution-projection",
        "stage3.8.5-decision-governance-evidence-trace",
        "stage3.8.6-deterministic-mission-timeline-reconstruction",
        "stage3.8.7-integrity-gap-consistency-diagnostics",
        "stage3.8.8-observability-metrics-health-operator-diagnostics",
        "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api",
        "stage3.8.10-observe-reconstruct-acceptance-regression-gate",
        "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract",
        "stage3.9.2-intake-lifecycle-e2e-segment-qualification",
        "stage3.9.3-planning-task-graph-dependency-verification",
        "stage3.9.4-routing-delegation-governance-continuity",
        "stage3.9.5-dispatch-execution-evidence-continuity",
        "stage3.9.6-task-completion-mission-outcome-closure",
        "stage3.9.7-adaptation-replanning-e2e-scenario",
        "stage3.9.8-restart-replay-recovery-e2e-verification",
        "stage3.9.9-global-observation-reconstruction-forensic-equivalence",
        CONTROL,
    ]
    tail = health["supported_controls"][-len(expected_tail):]
    assert tail == expected_tail
    assert tail[-42] == STAGE359
    assert tail[-41] == "stage3.5.10-execution-dispatch-acceptance-regression-gate"
    assert tail[-40] == "stage3.6.1-canonical-task-outcome-contract-identity"
    assert tail[-39] == "stage3.6.2-task-terminality-completion-eligibility"
    assert tail[-38] == "stage3.6.3-evidence-binding-verification"
    assert tail[-37] == "stage3.6.4-dependency-aware-task-completion"
    assert tail[-36] == "stage3.6.5-mission-outcome-aggregation"
    assert tail[-35] == "stage3.6.6-mission-success-criteria-evaluation"
    assert tail[-34] == "stage3.6.7-completion-readiness-blockers"
    assert tail[-33] == "stage3.6.8-verified-completion-declaration-lifecycle-handoff"
    assert tail[-32] == "stage3.6.9-outcome-lineage-replay-recovery"
    assert tail[-31] == "stage3.6.10-outcome-acceptance-regression-gate"
    assert tail[-30] == "stage3.7.1-canonical-adaptation-replan-contract-identity"
    assert tail[-29] == "stage3.7.2-adaptation-trigger-detection-classification"
    assert tail[-28] == "stage3.7.3-replan-eligibility-governance-gate"
    assert tail[-27] == "stage3.7.4-canonical-replan-snapshot-context-binding"
    assert tail[-26] == "stage3.7.5-deterministic-replan-candidate-generation"
    assert tail[-25] == "stage3.7.6-replan-candidate-validation-delta-feasibility-gate"
    assert tail[-24] == "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization"
    assert tail[-23] == "stage3.7.8-atomic-replan-commit-supersession-handoff"
    assert tail[-22] == "stage3.7.9-adapt-replan-lineage-replay-recovery"
    assert tail[-21] == "stage3.7.10-adapt-replan-acceptance-regression-gate"
    assert tail[-20] == "stage3.8.1-canonical-observability-trace-identity-contract"
    assert tail[-19] == "stage3.8.2-event-normalization-ingestion"
    assert tail[-18] == "stage3.8.3-global-causal-lineage-graph"
    assert tail[-17] == "stage3.8.4-live-mission-state-execution-projection"
    assert tail[-16] == "stage3.8.5-decision-governance-evidence-trace"
    assert tail[-15] == "stage3.8.6-deterministic-mission-timeline-reconstruction"
    assert tail[-14] == "stage3.8.7-integrity-gap-consistency-diagnostics"
    assert tail[-13] == "stage3.8.8-observability-metrics-health-operator-diagnostics"
    assert tail[-12] == "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api"
    assert tail[-11] == "stage3.8.10-observe-reconstruct-acceptance-regression-gate"
    assert tail[-10] == "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract"
    assert tail[-9] == "stage3.9.2-intake-lifecycle-e2e-segment-qualification"
    assert tail[-8] == "stage3.9.3-planning-task-graph-dependency-verification"
    assert tail[-7] == "stage3.9.4-routing-delegation-governance-continuity"
    assert tail[-6] == "stage3.9.5-dispatch-execution-evidence-continuity"
    assert tail[-5] == "stage3.9.6-task-completion-mission-outcome-closure"
    assert tail[-4] == "stage3.9.7-adaptation-replanning-e2e-scenario"
    assert tail[-3] == "stage3.9.8-restart-replay-recovery-e2e-verification"
    assert tail[-2] == "stage3.9.9-global-observation-reconstruction-forensic-equivalence"
    assert tail[-1] == CONTROL
    assert len(tail) == len(set(tail)) == len(expected_tail)
    contract = execution_acceptance_gate_contract()
    assert contract["dispatch_contract_is_dispatch"] is False
    assert contract["eligibility_is_execution_authorization"] is False
    assert contract["governance_authorization_is_dispatch"] is False
    assert contract["dispatch_commit_is_target_delivery"] is False
    assert contract["delivery_ack_is_running_state"] is False
    assert contract["running_projection_is_execution_authority"] is False
    assert contract["result_capture_is_task_completion_authority"] is False
    assert contract["successful_execution_is_mission_completion"] is False
    assert contract["replay_is_execution"] is False
    assert contract["recovery_is_authorization"] is False
    assert contract["recovery_is_dispatch"] is False
    assert contract["recovery_is_runtime_resumption"] is False
