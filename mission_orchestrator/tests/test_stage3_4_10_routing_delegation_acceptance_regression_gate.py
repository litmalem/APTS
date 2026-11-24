from __future__ import annotations

from pathlib import Path

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.routing_delegation_acceptance_gate import (
    ROUTING_DELEGATION_ACCEPTANCE_GATE_BASELINE,
    ROUTING_DELEGATION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
    ROUTING_DELEGATION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    ROUTING_DELEGATION_ACCEPTANCE_GATE_MODE,
    ROUTING_DELEGATION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
    ROUTING_DELEGATION_ACCEPTANCE_GATE_SCHEMA_VERSION,
    REQUIRED_ROUTING_DELEGATION_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_4_CONTROLS,
    routing_delegation_acceptance_gate_contract,
)
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_4_8_retry_fallback_reassignment_conflict_control import (
    make_service,
    provision_owned,
    recovery_request,
)
from tests.test_stage3_4_9_routing_delegation_event_lineage_replay_recovery import checkpoint_request


STAGE3410_CONTROL = "stage3.4.10-routing-delegation-acceptance-regression-gate"
CURRENT_CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision_closed_routing_delegation(service, key: str):
    mission_id, active, route, authorization, delegation, delivery = provision_owned(service, key)
    recovery = service.control_task_delegation_recovery(
        mission_id,
        recovery_request(service, mission_id, active, route, delegation, delivery, key),
    )
    checkpoint = service.create_routing_delegation_recovery_checkpoint(
        mission_id,
        checkpoint_request(service, mission_id, route, delegation, delivery, key),
    )
    return mission_id, active, route, authorization, delegation, delivery, recovery, checkpoint


def test_stage3410_health_declares_stage34_closure_without_new_authority_or_migration(tmp_path):
    service, _ = make_service(tmp_path / "missions.db")
    health = service.health()
    assert health["control_version"] == CURRENT_CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][30:] == [*REQUIRED_STAGE3_4_CONTROLS, STAGE3410_CONTROL, "stage3.5.1-canonical-execution-dispatch-contract-identity", "stage3.5.2-dispatch-eligibility-execution-preconditions", "stage3.5.3-authoritative-pre-dispatch-governance-revalidation", "stage3.5.4-idempotent-dispatch-execution-attempt-identity", "stage3.5.5-dispatch-delivery-execution-acknowledgement", "stage3.5.6-running-execution-state-heartbeat-projection", "stage3.5.7-execution-result-evidence-artifact-capture", "stage3.5.8-timeout-cancellation-abort-failure-propagation", "stage3.5.9-execution-event-lineage-replay-recovery", "stage3.5.10-execution-dispatch-acceptance-regression-gate", "stage3.6.1-canonical-task-outcome-contract-identity", "stage3.6.2-task-terminality-completion-eligibility", "stage3.6.3-evidence-binding-verification", "stage3.6.4-dependency-aware-task-completion", "stage3.6.5-mission-outcome-aggregation", "stage3.6.6-mission-success-criteria-evaluation", "stage3.6.7-completion-readiness-blockers", "stage3.6.8-verified-completion-declaration-lifecycle-handoff", "stage3.6.9-outcome-lineage-replay-recovery", "stage3.6.10-outcome-acceptance-regression-gate", "stage3.7.1-canonical-adaptation-replan-contract-identity", "stage3.7.2-adaptation-trigger-detection-classification", "stage3.7.3-replan-eligibility-governance-gate", "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate", "stage3.8.1-canonical-observability-trace-identity-contract", "stage3.8.2-event-normalization-ingestion", "stage3.8.3-global-causal-lineage-graph", "stage3.8.4-live-mission-state-execution-projection", "stage3.8.5-decision-governance-evidence-trace", "stage3.8.6-deterministic-mission-timeline-reconstruction", "stage3.8.7-integrity-gap-consistency-diagnostics", "stage3.8.8-observability-metrics-health-operator-diagnostics", "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api", "stage3.8.10-observe-reconstruct-acceptance-regression-gate", "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract", "stage3.9.2-intake-lifecycle-e2e-segment-qualification", "stage3.9.3-planning-task-graph-dependency-verification", "stage3.9.4-routing-delegation-governance-continuity", "stage3.9.5-dispatch-execution-evidence-continuity", "stage3.9.6-task-completion-mission-outcome-closure", "stage3.9.7-adaptation-replanning-e2e-scenario", "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CURRENT_CONTROL]
    assert health["stage3_4_routing_delegation_acceptance_gate_schema_version"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert health["stage3_4_routing_delegation_acceptance_gate_mode"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_MODE
    assert health["stage3_4_routing_delegation_acceptance_gate_baseline"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_BASELINE
    assert health["stage3_4_routing_delegation_acceptance_gate_runtime_change_mode"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE
    assert health["stage3_4_routing_delegation_acceptance_gate_database_change_mode"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE
    assert health["stage3_4_routing_delegation_acceptance_gate_expected_migration_level"] == 26
    assert health["stage3_4_routing_delegation_acceptance_gate_declared_only"] is True
    assert health["stage3_4_routing_delegation_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_4_routing_delegation_acceptance_gate_external_execution_required"] is True
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["stage3_4_routing_delegation_acceptance_gate_new_task_dispatch_added"] is False
    assert health["stage3_4_routing_delegation_acceptance_gate_new_target_action_dispatch_added"] is False
    assert health["stage3_4_routing_delegation_acceptance_gate_new_target_actuation_added"] is False


def test_stage3410_static_contract_requires_all_stage34_controls_and_external_acceptance():
    contract = routing_delegation_acceptance_gate_contract()
    assert contract["schema_version"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert contract["mode"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_MODE
    assert contract["baseline"] == "STAGE_3_4_1_THROUGH_3_4_9"
    assert contract["required_prior_controls"] == list(REQUIRED_STAGE3_4_CONTROLS)
    assert contract["required_gates"] == list(REQUIRED_ROUTING_DELEGATION_ACCEPTANCE_GATES)
    assert len(contract["required_gates"]) == len(set(contract["required_gates"]))
    assert contract["expected_repository_migration_level"] == ROUTING_DELEGATION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 26
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert contract["new_route_selection_authority_added"] is False
    assert contract["new_governance_authorization_authority_added"] is False
    assert contract["new_delegation_authority_added"] is False
    assert contract["new_ownership_transfer_authority_added"] is False
    assert contract["new_task_dispatch_added"] is False
    assert contract["new_target_action_dispatch_added"] is False
    assert contract["new_target_actuation_added"] is False
    assert contract["new_durable_store_added"] is False
    assert contract["new_database_migration_added"] is False


def test_stage3410_end_to_end_stage341_through_349_materializes_complete_stack(tmp_path):
    service, _ = make_service(tmp_path / "missions.db")
    mission_id, _, route, authorization, delegation, delivery, recovery, checkpoint = provision_closed_routing_delegation(
        service, "stack3410"
    )

    assert service.get_task_routing_intent_history(mission_id)["intent_count"] == 1
    assert service.get_task_routing_eligibility_history(mission_id)["gate_count"] == 1
    assert service.get_task_route_selection_history(mission_id)["decision_count"] == 1
    assert service.get_task_delegation_authorization_history(mission_id)["authorization_count"] == 1
    assert service.get_task_delegation_history(mission_id)["delegation_count"] == 1
    assert service.get_delegation_delivery_history(mission_id)["delivery_count"] == 1
    assert service.get_delegation_recovery_control_history(mission_id)["control_count"] == 1
    assert service.get_routing_delegation_recovery_history(mission_id)["checkpoint_count"] == 1
    assert route["route_decision_id"] == checkpoint["route_decision_id"]
    assert authorization["route_decision_id"] == route["route_decision_id"]
    assert delegation["delegation_authorization_id"] == authorization["delegation_authorization_id"]
    assert delivery["delegation_id"] == delegation["delegation_id"]
    assert recovery["delivery_receipt_id"] == delivery["delivery_receipt_id"]
    assert checkpoint["delivery_receipt_id"] == delivery["delivery_receipt_id"]


def test_stage3410_lineage_replay_and_recovery_close_the_same_causal_trajectory(tmp_path):
    service, _ = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _, _, _, checkpoint = provision_closed_routing_delegation(service, "lineage3410")
    lineage = service.get_routing_delegation_event_lineage(mission_id)
    replay = service.get_routing_delegation_event_replay(mission_id)
    recovered = service.recover_routing_delegation_state(mission_id)

    assert lineage["integrity_status"] == "PASS"
    assert lineage["routing_delegation_event_count"] == 8
    assert replay["replay"]["routing_delegation_event_count"] == lineage["routing_delegation_event_count"]
    assert replay["replay"]["routing_delegation_event_tip_sha256"] == lineage["routing_delegation_event_tip_sha256"]
    assert replay["replay"]["read_only"] is True
    assert replay["replay"]["side_effects_performed"] is False
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["reconstructed_from_durable_repository"] is True
    assert recovered["external_network_io_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert recovered["dispatch_performed"] is False
    assert recovered["execution_authorized"] is False


def test_stage3410_replay_and_recovery_do_not_mutate_event_or_artifact_counts(tmp_path):
    service, _ = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_closed_routing_delegation(service, "readonly3410")
    events_before = service.get_mission_events(mission_id)["event_count"]
    repo_before = service.get_mission_repository(mission_id)["record_counts"].copy()
    service.get_routing_delegation_event_replay(mission_id)
    service.recover_routing_delegation_state(mission_id)
    service.get_routing_delegation_event_replay(mission_id)
    events_after = service.get_mission_events(mission_id)["event_count"]
    repo_after = service.get_mission_repository(mission_id)["record_counts"]
    assert events_after == events_before
    assert repo_after == repo_before


def test_stage3410_restart_recovers_closed_trajectory_without_new_governance_query(tmp_path):
    db = tmp_path / "missions.db"
    service, gov = make_service(db)
    mission_id, _, _, _, _, _, _, checkpoint = provision_closed_routing_delegation(service, "restart3410")
    calls_before = gov.evaluate_calls
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=str(db)), governance_client=gov)
    recovered = restarted.recover_routing_delegation_state(mission_id)
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["reconstructed_from_durable_repository"] is True
    assert recovered["external_network_io_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert gov.evaluate_calls == calls_before


def test_stage3410_repository_and_event_integrity_pass_for_closed_stack(tmp_path):
    service, _ = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_closed_routing_delegation(service, "integrity3410")
    repository = service.get_mission_repository(mission_id)
    events = service.get_mission_events(mission_id)
    assert repository["integrity_status"] == "PASS"
    assert events["integrity_status"] == "PASS"
    checks = {item["check"]: item["status"] for item in repository["integrity_checks"]}
    assert checks["routing_delegation_event_lineage_replay_recovery_store"] == "PASS"
    assert repository["record_counts"]["mission_task_routing_intents"] == 1
    assert repository["record_counts"]["mission_task_route_decisions"] == 1
    assert repository["record_counts"]["mission_delegation_authorizations"] == 1
    assert repository["record_counts"]["mission_task_delegations"] == 1
    assert repository["record_counts"]["mission_delegation_deliveries"] == 1
    assert repository["record_counts"]["mission_delegation_recovery_controls"] == 1
    assert repository["record_counts"]["mission_routing_delegation_recovery_checkpoints"] == 1


def test_stage3410_governance_authorization_remains_external_and_is_not_execution_grant(tmp_path):
    service, gov = make_service(tmp_path / "missions.db")
    mission_id, _, _, authorization, _, _, _, _ = provision_closed_routing_delegation(service, "gov3410")
    assert gov.evaluate_calls == 1
    auth = service.get_task_delegation_authorization(mission_id, authorization["delegation_authorization_id"])
    health = service.health()
    assert auth["authorization_status"] == "AUTHORIZED"
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["delegation_authorization_is_delegation"] is False
    assert health["task_delegation_execution_authorized"] is False
    assert health["delegation_delivery_execution_authorized"] is False
    assert health["delegation_recovery_control_execution_authorized"] is False
    assert health["routing_delegation_recovery_execution_authorized"] is False


def test_stage3410_preserves_no_dispatch_no_target_actuation_boundary(tmp_path):
    service, _ = make_service(tmp_path / "missions.db")
    health = service.health()
    false_fields = (
        "task_routing_dispatch_performed",
        "task_routing_target_action_dispatch_enabled",
        "task_routing_target_actuation",
        "task_delegation_dispatch_performed",
        "task_delegation_execution_authorized",
        "delegation_delivery_dispatch_performed",
        "delegation_delivery_execution_authorized",
        "delegation_recovery_control_dispatch_performed",
        "delegation_recovery_control_execution_authorized",
        "routing_delegation_recovery_dispatch_performed",
        "routing_delegation_recovery_execution_authorized",
        "routing_delegation_recovery_target_action_dispatch_enabled",
        "routing_delegation_recovery_target_actuation",
    )
    for field in false_fields:
        assert health[field] is False, field


def test_stage3410_adds_no_migration_027_and_keeps_repository_level_26():
    root = Path(__file__).resolve().parents[1]
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert not list((root / "migrations").glob("027_stage3_4_10*.sql"))
    assert routing_delegation_acceptance_gate_contract()["new_database_migration_added"] is False
    assert routing_delegation_acceptance_gate_contract()["new_durable_store_added"] is False


def test_stage3410_gate_is_declarative_and_cannot_self_certify_pass():
    contract = routing_delegation_acceptance_gate_contract()
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert "acceptance_status" not in contract
    assert "passed" not in contract


def test_stage3410_final_supported_control_tail_is_complete_and_ordered(tmp_path):
    service, _ = make_service(tmp_path / "missions.db")
    tail = service.health()["supported_controls"][30:]
    assert tail[:9] == list(REQUIRED_STAGE3_4_CONTROLS)
    assert tail[9] == STAGE3410_CONTROL
    assert tail[10] == "stage3.5.1-canonical-execution-dispatch-contract-identity"
    assert tail[11] == "stage3.5.2-dispatch-eligibility-execution-preconditions"
    assert tail[12] == "stage3.5.3-authoritative-pre-dispatch-governance-revalidation"
    assert tail[13] == "stage3.5.4-idempotent-dispatch-execution-attempt-identity"
    assert tail[14] == "stage3.5.5-dispatch-delivery-execution-acknowledgement"
    assert tail[15] == "stage3.5.6-running-execution-state-heartbeat-projection"
    assert tail[16] == "stage3.5.7-execution-result-evidence-artifact-capture"
    assert tail[17] == "stage3.5.8-timeout-cancellation-abort-failure-propagation"
    assert tail[18] == "stage3.5.9-execution-event-lineage-replay-recovery"
    assert tail[19] == "stage3.5.10-execution-dispatch-acceptance-regression-gate"
    assert tail[20] == "stage3.6.1-canonical-task-outcome-contract-identity"
    assert tail[21] == "stage3.6.2-task-terminality-completion-eligibility"
    assert tail[22] == "stage3.6.3-evidence-binding-verification"
    assert tail[23] == "stage3.6.4-dependency-aware-task-completion"
    assert tail[24] == "stage3.6.5-mission-outcome-aggregation"
    assert tail[25] == "stage3.6.6-mission-success-criteria-evaluation"
    assert tail[26] == "stage3.6.7-completion-readiness-blockers"
    assert tail[27] == "stage3.6.8-verified-completion-declaration-lifecycle-handoff"
    assert tail[28] == "stage3.6.9-outcome-lineage-replay-recovery"
    assert tail[29] == "stage3.6.10-outcome-acceptance-regression-gate"
    assert tail[30] == "stage3.7.1-canonical-adaptation-replan-contract-identity"
    assert tail[31] == "stage3.7.2-adaptation-trigger-detection-classification"
    assert tail[32] == "stage3.7.3-replan-eligibility-governance-gate"
    assert tail[33] == "stage3.7.4-canonical-replan-snapshot-context-binding"
    assert tail[34] == "stage3.7.5-deterministic-replan-candidate-generation"
    assert tail[35] == "stage3.7.6-replan-candidate-validation-delta-feasibility-gate"
    assert tail[36] == "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization"
    assert tail[37] == "stage3.7.8-atomic-replan-commit-supersession-handoff"
    assert tail[38] == "stage3.7.9-adapt-replan-lineage-replay-recovery"
    assert tail[39] == "stage3.7.10-adapt-replan-acceptance-regression-gate"
    assert tail[40] == "stage3.8.1-canonical-observability-trace-identity-contract"
    assert tail[41] == "stage3.8.2-event-normalization-ingestion"
    assert tail[42] == "stage3.8.3-global-causal-lineage-graph"
    assert tail[43] == "stage3.8.4-live-mission-state-execution-projection"
    assert tail[44] == "stage3.8.5-decision-governance-evidence-trace"
    assert tail[45] == "stage3.8.6-deterministic-mission-timeline-reconstruction"
    assert tail[46] == "stage3.8.7-integrity-gap-consistency-diagnostics"
    assert tail[47] == "stage3.8.8-observability-metrics-health-operator-diagnostics"
    assert tail[48] == "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api"
    assert tail[49] == "stage3.8.10-observe-reconstruct-acceptance-regression-gate"
    assert tail[50] == "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract"
    assert tail[51] == "stage3.9.2-intake-lifecycle-e2e-segment-qualification"
    assert tail[52] == "stage3.9.3-planning-task-graph-dependency-verification"
    assert tail[53] == "stage3.9.4-routing-delegation-governance-continuity"
    assert tail[54] == "stage3.9.5-dispatch-execution-evidence-continuity"
    assert tail[55] == "stage3.9.6-task-completion-mission-outcome-closure"
    assert tail[56] == "stage3.9.7-adaptation-replanning-e2e-scenario"
    assert tail[57] == "stage3.9.8-restart-replay-recovery-e2e-verification"
    assert tail[58] == "stage3.9.9-global-observation-reconstruction-forensic-equivalence"
    assert tail[59] == CURRENT_CONTROL
    assert len(tail) == len(set(tail)) == 60
