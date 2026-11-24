from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import MissionConcurrencyConflict, MissionIllegalTransition, MissionLifecycleGuardRejected
from mission_orchestrator.lifecycle_acceptance_gate import (
    LIFECYCLE_ACCEPTANCE_GATE_BASELINE,
    LIFECYCLE_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
    LIFECYCLE_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    LIFECYCLE_ACCEPTANCE_GATE_MODE,
    LIFECYCLE_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
    LIFECYCLE_ACCEPTANCE_GATE_SCHEMA_VERSION,
    REQUIRED_LIFECYCLE_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_2_CONTROLS,
    lifecycle_acceptance_gate_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoExternalClient:
    base_url = "disabled://stage3.2.10"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.2.10 acceptance closure must remain local-only: unexpected call {name}")


def make_service(db: Path) -> CanonicalMissionService:
    client = NoExternalClient()
    return CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=client,
        cti_client=client,
    )


def mission_payload(key: str, *, criteria_count: int = 2) -> dict:
    return {
        "idempotency_key": f"stage3210-{key}",
        "source_system": "PYTEST_STAGE3210",
        "created_by": "stage3.2.10-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage3210-lab"},
        "success_criteria": [
            {"metric": f"criterion_{idx}", "expected": True} for idx in range(criteria_count)
        ],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-{key}",
        "pip_version": "14",
        "metadata": {"environment": "LAB", "stage": "3.2.10"},
    }


def create_mission(service: CanonicalMissionService, key: str, *, criteria_count: int = 2) -> str:
    return service.create_mission(mission_payload(key, criteria_count=criteria_count))["canonical_identity"]["mission_id"]


def lifecycle_request(
    service: CanonicalMissionService,
    mission_id: str,
    command: str,
    token: str,
    *,
    target_state: str | None = None,
    evidence_refs: list[str] | None = None,
    metadata: dict | None = None,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "command_id": f"lc-3210-{token}",
        "idempotency_key": f"idem-lc-3210-{token}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.10-pytest",
        "reason_code": f"STAGE3210_{command}",
        "reason": f"Stage 3.2.10 acceptance probe {command}",
        "evidence_refs": list(evidence_refs if evidence_refs is not None else [f"evidence:stage3210:{token}"]),
        "metadata": dict(metadata or {"stage": "3.2.10", "token": token}),
    }
    if target_state is not None:
        body["target_state"] = target_state
    return body


def execute(service: CanonicalMissionService, mission_id: str, command: str, token: str, **kwargs):
    return service.execute_mission_lifecycle_command(
        mission_id,
        lifecycle_request(service, mission_id, command, token, **kwargs),
    )


def activate_running(service: CanonicalMissionService, mission_id: str) -> None:
    execute(service, mission_id, "BIND_PIP", "bind")
    execute(service, mission_id, "START_PLANNING", "planning")
    execute(service, mission_id, "START", "running")


def wait_metadata(kind: str, dependency_id: str) -> dict:
    return {
        "stage": "3.2.10",
        "dependency": {
            "dependency_id": dependency_id,
            "kind": kind,
            "description": f"Stage 3.2.10 {kind.lower()} dependency",
        },
    }


def resolution_metadata(dependency_id: str) -> dict:
    return {
        "stage": "3.2.10",
        "dependency_resolution": {
            "dependency_id": dependency_id,
            "status": "SATISFIED",
            "resolved_by": "stage3.2.10-pytest",
        },
    }


def valid_completion_bundle(criteria_count: int = 2, prefix: str = "closure") -> tuple[list[str], dict]:
    objective_ref = f"evidence:objective:{prefix}"
    criterion_refs = [f"evidence:criterion:{idx}:{prefix}" for idx in range(criteria_count)]
    cleanup_ref = f"evidence:cleanup:{prefix}"
    refs = [objective_ref, *criterion_refs, cleanup_ref]
    return refs, {
        "stage": "3.2.10",
        "completion": {
            "verification_status": "VERIFIED",
            "objective_status": "SATISFIED",
            "objective_evidence_refs": [objective_ref],
            "success_criteria_status": "SATISFIED",
            "criteria_results": [
                {"criterion_index": idx, "status": "SATISFIED", "evidence_refs": [ref]}
                for idx, ref in enumerate(criterion_refs)
            ],
            "cleanup_status": "VERIFIED",
            "cleanup_checks": [
                {"check_id": "CONTROLLED_CLEANUP_VERIFIED", "status": "PASS", "evidence_refs": [cleanup_ref]}
            ],
            "outstanding_critical_dependencies": 0,
        },
    }


def event_request(service: CanonicalMissionService, mission_id: str, event_type: str, token: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "event_id": f"stage3210-event-{token}",
        "event_type": event_type,
        "source_component": "STAGE3210-ACCEPTANCE-SOURCE",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "observed_state": state["state"],
        "observed_state_version": state["state_version"],
        "observed_version_sha256": vector["version_sha256"],
        "actor": "stage3.2.10-event-adapter",
        "reason_code": f"STAGE3210_{event_type}",
        "reason": f"Stage 3.2.10 event probe {event_type}",
        "evidence_refs": [],
        "metadata": {"stage": "3.2.10"},
    }


def test_stage3210_health_declares_closure_without_runtime_authority_or_migration_expansion(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][10:30] == [*REQUIRED_STAGE3_2_CONTROLS, "stage3.2.10-lifecycle-acceptance-regression-gate", "stage3.3.1-canonical-plan-contract-identity", "stage3.3.2-planner-input-snapshot-context-binding", "stage3.3.3-canonical-task-decomposition-contract", "stage3.3.4-task-dependency-graph-structural-validation", "stage3.3.5-planner-invocation-plan-generation", "stage3.3.6-plan-validation-feasibility-gate", "stage3.3.7-plan-versioning-replanning-supersession", "stage3.3.8-task-readiness-scheduling-projection", "stage3.3.9-planning-event-lineage-replay-recovery", "stage3.3.10-planning-acceptance-regression-gate"]
    assert health["stage3_2_lifecycle_acceptance_gate_schema_version"] == LIFECYCLE_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert health["stage3_2_lifecycle_acceptance_gate_mode"] == LIFECYCLE_ACCEPTANCE_GATE_MODE
    assert health["stage3_2_lifecycle_acceptance_gate_baseline"] == LIFECYCLE_ACCEPTANCE_GATE_BASELINE
    assert health["stage3_2_lifecycle_acceptance_gate_runtime_change_mode"] == LIFECYCLE_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE
    assert health["stage3_2_lifecycle_acceptance_gate_database_change_mode"] == LIFECYCLE_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE
    assert health["stage3_2_lifecycle_acceptance_gate_expected_migration_level"] == 8
    assert health["stage3_2_lifecycle_acceptance_gate_declared_only"] is True
    assert health["stage3_2_lifecycle_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_2_lifecycle_acceptance_gate_external_execution_required"] is True
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["mission_repository_migration_level"] == 53
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_stage3210_static_contract_requires_all_prior_lifecycle_controls_and_external_acceptance():
    contract = lifecycle_acceptance_gate_contract()
    assert contract["schema_version"] == LIFECYCLE_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert contract["baseline"] == "STAGE_3_2_1_THROUGH_3_2_9"
    assert contract["required_prior_controls"] == list(REQUIRED_STAGE3_2_CONTROLS)
    assert contract["required_gates"] == list(REQUIRED_LIFECYCLE_ACCEPTANCE_GATES)
    assert contract["expected_repository_migration_level"] == LIFECYCLE_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert contract["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert contract["planner_invocation_added"] is False
    assert contract["target_action_dispatch_added"] is False
    assert contract["target_actuation_added"] is False
    assert contract["external_event_delivery_added"] is False


def test_stage3210_activation_chain_and_guarded_command_replay_close_stages_321_to_324(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "activation")
    bind = lifecycle_request(service, mission_id, "BIND_PIP", "activation-bind")
    first = service.execute_mission_lifecycle_command(mission_id, bind)
    replay = service.execute_mission_lifecycle_command(mission_id, bind)
    assert first["mission_state"]["state"] == "PIP_BOUND"
    assert replay["idempotent_replay"] is True
    execute(service, mission_id, "START_PLANNING", "activation-plan")
    running = execute(service, mission_id, "START", "activation-run")
    assert running["mission_state"]["state"] == "RUNNING"
    assert running["planning_run_activation"]["planning_activation_proof"]["valid"] is True


def test_stage3210_waiting_evidence_and_approval_dependencies_both_resolve_back_to_running(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "waiting")
    activate_running(service, mission_id)

    evidence_id = "dep-stage3210-evidence"
    waited = execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait-evidence", metadata=wait_metadata("EVIDENCE", evidence_id))
    assert waited["mission_state"]["state"] == "WAITING_EVIDENCE"
    resumed = execute(service, mission_id, "START", "resolve-evidence", metadata=resolution_metadata(evidence_id), evidence_refs=["evidence:resolved:evidence"])
    assert resumed["mission_state"]["state"] == "RUNNING"

    approval_id = "dep-stage3210-approval"
    waited = execute(service, mission_id, "WAIT_FOR_APPROVAL", "wait-approval", metadata=wait_metadata("APPROVAL", approval_id))
    assert waited["mission_state"]["state"] == "WAITING_APPROVAL"
    resumed = execute(service, mission_id, "START", "resolve-approval", metadata=resolution_metadata(approval_id), evidence_refs=["evidence:resolved:approval"])
    assert resumed["mission_state"]["state"] == "RUNNING"
    assert resumed["waiting_dependency_resolution"]["approval_dependency_is_governance_authorization"] is False


def test_stage3210_pause_resume_and_replanning_require_preserved_lineage_and_readiness(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "pause-replan")
    activate_running(service, mission_id)
    paused = execute(service, mission_id, "PAUSE", "pause")
    resumed = execute(service, mission_id, "RESUME", "resume", target_state="RUNNING")
    assert resumed["resume_control"]["pause_id"] == paused["pause_control"]["pause_id"]
    replan = execute(service, mission_id, "REPLAN", "replan")
    assert replan["mission_state"]["state"] == "REPLANNING"
    with pytest.raises(MissionLifecycleGuardRejected, match="REPLAN_READINESS_EVIDENCE_FOR_RETURN"):
        execute(service, mission_id, "START", "replan-not-ready", evidence_refs=[])
    ready = execute(service, mission_id, "START", "replan-ready", evidence_refs=["evidence:plan:ready:v2"])
    assert ready["mission_state"]["state"] == "RUNNING"
    assert ready["replan_resolution"]["readiness_ready"] is True


@pytest.mark.parametrize(("command", "terminal"), [("ABORT", "ABORTED"), ("FAIL", "FAILED"), ("EXPIRE", "EXPIRED")])
def test_stage3210_terminal_semantics_are_distinct_and_final(tmp_path, command, terminal):
    service = make_service(tmp_path / f"{command.lower()}.db")
    mission_id = create_mission(service, command.lower())
    activate_running(service, mission_id)
    result = execute(service, mission_id, command, command.lower())
    assert result["mission_state"]["state"] == terminal
    assert result["terminal_control"]["terminal_state"] == terminal
    with pytest.raises(MissionIllegalTransition):
        execute(service, mission_id, "PAUSE", f"after-{command.lower()}")


def test_stage3210_cleanup_verified_completion_requires_full_evidence_and_produces_verified_terminal(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "completion", criteria_count=2)
    activate_running(service, mission_id)
    cleaning = execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    assert cleaning["mission_state"]["state"] == "CLEANING_UP"
    with pytest.raises(MissionLifecycleGuardRejected):
        execute(service, mission_id, "COMPLETE", "complete-missing")
    refs, metadata = valid_completion_bundle(2)
    completed = execute(service, mission_id, "COMPLETE", "complete", evidence_refs=refs, metadata=metadata)
    assert completed["mission_state"]["state"] == "COMPLETED"
    assert completed["completion_verification"]["verified_completion_claimed"] is True
    assert completed["completion_verification"]["outstanding_critical_dependencies"] == 0


def test_stage3210_event_automation_replay_is_side_effect_free_and_stale_event_fails_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "events")
    event = event_request(service, mission_id, "PIP_BIND_REQUESTED", "bind")
    first = service.process_mission_lifecycle_event(mission_id, event)
    transition_count = service.get_mission_state_history(mission_id)["transition_count"]
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.process_mission_lifecycle_event(mission_id, event)
    assert first["automation_status"] == "APPLIED"
    assert replay["idempotent_replay"] is True
    assert service.get_mission_state_history(mission_id)["transition_count"] == transition_count
    assert service.get_mission_events(mission_id)["event_count"] == event_count

    stale = event_request(service, mission_id, "PLANNING_START_REQUESTED", "stale")
    stale["observed_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict):
        service.process_mission_lifecycle_event(mission_id, stale)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PIP_BOUND"


def test_stage3210_lineage_repository_integrity_and_restart_reconstruction_remain_local(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id = create_mission(service, "restart")
    activate_running(service, mission_id)
    execute(service, mission_id, "PAUSE", "restart-pause")

    before_events = service.get_mission_events(mission_id)
    before_repo = service.get_mission_repository(mission_id)
    assert before_events["integrity_status"] == "PASS"
    assert before_repo["integrity_status"] == "PASS"

    restarted = make_service(db)
    state = restarted.get_mission_state(mission_id)["mission_state"]
    lineage = restarted.get_mission_lineage(mission_id)
    repository = restarted.get_mission_repository(mission_id)
    assert state["state"] == "PAUSED"
    assert lineage["integrity_status"] == "PASS"
    assert repository["integrity_status"] == "PASS"
    assert repository["repository_sha256"] == before_repo["repository_sha256"]
    assert repository["record_counts"]["mission_events"] == before_events["event_count"]


def test_stage3210_baseline_migration_remains_008_and_stage331_adds_009():
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert LIFECYCLE_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 8
    assert len(migrations) == 53
    assert migrations[7].name == "008_stage3_1_9_mission_event_lineage_foundation.sql"
    assert [m.name for m in migrations[8:]] == [
        "009_stage3_3_1_canonical_plan_contract_identity.sql",
        "010_stage3_3_2_planner_input_snapshot_context_binding.sql",
        "011_stage3_3_3_canonical_task_decomposition_contract.sql",
        "012_stage3_3_4_task_dependency_graph_structural_validation.sql",
        "013_stage3_3_5_planner_invocation_plan_generation.sql",
        "014_stage3_3_6_plan_validation_feasibility_gate.sql",
        "015_stage3_3_7_plan_versioning_replanning_supersession.sql",
        "016_stage3_3_8_task_readiness_scheduling_projection.sql",
        "017_stage3_3_9_planning_event_lineage_replay_recovery.sql",
        "018_stage3_4_1_canonical_subsystem_registry_capability_contract.sql",
        "019_stage3_4_2_task_routing_intent_candidate_resolution.sql",
        "020_stage3_4_3_routing_eligibility_compatibility_gate.sql",
        "021_stage3_4_4_deterministic_route_selection_decision_record.sql",
        "022_stage3_4_5_governance_bound_delegation_authorization.sql",
        "023_stage3_4_6_canonical_delegation_contract_handoff_envelope.sql",
        "024_stage3_4_7_delegation_delivery_acknowledgement_ownership.sql",
        "025_stage3_4_8_retry_fallback_reassignment_conflict_control.sql",
        "026_stage3_4_9_routing_delegation_event_lineage_replay_recovery.sql",
        "027_stage3_5_1_canonical_execution_dispatch_contract_identity.sql",
        "028_stage3_5_2_dispatch_eligibility_execution_preconditions.sql",
        "029_stage3_5_3_authoritative_pre_dispatch_governance_revalidation.sql",
        "030_stage3_5_4_idempotent_dispatch_execution_attempt_identity.sql",
        "031_stage3_5_5_dispatch_delivery_execution_acknowledgement.sql",
        "032_stage3_5_6_running_execution_state_heartbeat_projection.sql",
        "033_stage3_5_7_execution_result_evidence_artifact_capture.sql",
        "034_stage3_5_8_timeout_cancellation_abort_failure_propagation.sql",
        "035_stage3_5_9_execution_event_lineage_replay_recovery.sql",
        "036_stage3_6_1_canonical_task_outcome_contract_identity.sql",
        "037_stage3_6_2_task_terminality_completion_eligibility.sql",
        "038_stage3_6_3_evidence_binding_verification.sql",
        "039_stage3_6_4_dependency_aware_task_completion.sql",
        "040_stage3_6_5_mission_outcome_aggregation.sql",
        "041_stage3_6_6_mission_success_criteria_evaluation.sql",
        "042_stage3_6_7_completion_readiness_blockers.sql",
        "043_stage3_6_8_verified_completion_declaration_lifecycle_handoff.sql",
        "044_stage3_6_9_outcome_lineage_replay_recovery.sql",
        "045_stage3_7_1_canonical_adaptation_replan_contract_identity.sql",
        "046_stage3_7_2_adaptation_trigger_detection_classification.sql",
        "047_stage3_7_3_replan_eligibility_governance_gate.sql",
        "048_stage3_7_4_canonical_replan_snapshot_context_binding.sql",
        "049_stage3_7_5_deterministic_replan_candidate_generation.sql",
        "050_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.sql",
        "051_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.sql",
        "052_stage3_7_8_atomic_replan_commit_supersession_handoff.sql",
        "053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql",
    ]
