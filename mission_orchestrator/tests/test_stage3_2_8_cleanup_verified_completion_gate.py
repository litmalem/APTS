from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionLifecycleGuardRejected
from mission_orchestrator.mission_lifecycle import (
    CLEANUP_CHECK_STATUS,
    CLEANUP_COMMAND,
    CLEANUP_COMPLETION_MODE,
    CLEANUP_COMPLETION_SCHEMA_VERSION,
    CLEANUP_STATE,
    CLEANUP_VERIFICATION_STATUS,
    COMPLETION_COMMAND,
    COMPLETION_STATE,
    COMPLETION_VERIFICATION_STATUS,
    LIFECYCLE_COMMAND_OPERATION,
    OBJECTIVE_COMPLETION_STATUS,
    SUCCESS_CRITERIA_COMPLETION_STATUS,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage328-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(
            f"Stage 3.2.8 cleanup/completion verification must remain local-only: unexpected call {name}"
        )


def make_service(tmp_path: Path) -> CanonicalMissionService:
    no_call = NoCallExternal()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str, *, criteria_count: int = 2) -> dict:
    return {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE328",
        "created_by": "stage3.2.8-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage328-lab"},
        "success_criteria": [
            {"metric": f"criterion_{idx}", "expected": True} for idx in range(criteria_count)
        ],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-{key}",
        "pip_version": "13",
        "metadata": {"environment": "LAB", "stage": "3.2.8"},
    }


def create_mission(service: CanonicalMissionService, key: str, *, criteria_count: int = 2) -> str:
    return service.create_mission(mission_payload(key, criteria_count=criteria_count))["canonical_identity"]["mission_id"]


def lifecycle_request(
    service: CanonicalMissionService,
    mission_id: str,
    command: str,
    idx: str,
    *,
    target_state: str | None = None,
    evidence_refs: list[str] | None = None,
    metadata: dict | None = None,
    dependency_id: str | None = None,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "command_id": f"lc-328-{idx}",
        "idempotency_key": f"idem-lc-328-{idx}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.8-pytest",
        "reason_code": f"STAGE328_{command}",
        "reason": f"Stage 3.2.8 lifecycle command {command}",
        "evidence_refs": list(evidence_refs if evidence_refs is not None else ["evidence:test:stage328"]),
        "metadata": dict(metadata or {"stage": "3.2.8", "idx": idx}),
    }
    if target_state is not None:
        body["target_state"] = target_state
    if command in {"WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"}:
        body["metadata"]["dependency"] = {
            "dependency_id": dependency_id or f"dep-328-{idx}",
            "kind": "EVIDENCE" if command == "WAIT_FOR_EVIDENCE" else "APPROVAL",
            "description": "Stage 3.2.8 completion-blocker dependency",
        }
    return body


def execute(service: CanonicalMissionService, mission_id: str, command: str, idx: str, **kwargs):
    return service.execute_mission_lifecycle_command(
        mission_id,
        lifecycle_request(service, mission_id, command, idx, **kwargs),
    )


def activate_running(service: CanonicalMissionService, mission_id: str) -> None:
    execute(service, mission_id, "BIND_PIP", "bind")
    execute(service, mission_id, "START_PLANNING", "plan")
    execute(service, mission_id, "START", "run")


def valid_completion_bundle(criteria_count: int = 2, *, prefix: str = "ok") -> tuple[list[str], dict]:
    objective_ref = f"evidence:objective:{prefix}"
    criterion_refs = [f"evidence:criterion:{idx}:{prefix}" for idx in range(criteria_count)]
    cleanup_ref = f"evidence:cleanup:{prefix}"
    refs = [objective_ref, *criterion_refs, cleanup_ref]
    metadata = {
        "stage": "3.2.8",
        "completion": {
            "verification_status": COMPLETION_VERIFICATION_STATUS,
            "objective_status": OBJECTIVE_COMPLETION_STATUS,
            "objective_evidence_refs": [objective_ref],
            "success_criteria_status": SUCCESS_CRITERIA_COMPLETION_STATUS,
            "criteria_results": [
                {
                    "criterion_index": idx,
                    "status": SUCCESS_CRITERIA_COMPLETION_STATUS,
                    "evidence_refs": [ref],
                }
                for idx, ref in enumerate(criterion_refs)
            ],
            "cleanup_status": CLEANUP_VERIFICATION_STATUS,
            "cleanup_checks": [
                {
                    "check_id": "CONTROLLED_CLEANUP_VERIFIED",
                    "status": CLEANUP_CHECK_STATUS,
                    "evidence_refs": [cleanup_ref],
                }
            ],
            "outstanding_critical_dependencies": 0,
        },
    }
    return refs, metadata


def direct_transition(service: CanonicalMissionService, mission_id: str, to_state: str, idx: str):
    state = service.get_mission_state(mission_id)["mission_state"]
    return service.transition_mission_state(
        mission_id,
        {
            "expected_state_version": state["state_version"],
            "to_state": to_state,
            "actor": "stage3.2.8-legacy-test",
            "reason_code": f"LEGACY_{idx}",
            "reason": "Exercise preserved Stage-3.1 direct state transition API",
            "evidence_refs": [],
            "metadata": {"legacy_test": True, "stage": "3.2.8"},
        },
    )


def test_health_declares_stage328_without_migration_or_authority_expansion(tmp_path):
    health = make_service(tmp_path).health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][17:30] == [
        "stage3.2.8-cleanup-verified-completion-gate",
        "stage3.2.9-event-driven-lifecycle-automation-reliability",
        "stage3.2.10-lifecycle-acceptance-regression-gate",
        "stage3.3.1-canonical-plan-contract-identity",
        "stage3.3.2-planner-input-snapshot-context-binding",
        "stage3.3.3-canonical-task-decomposition-contract",
        "stage3.3.4-task-dependency-graph-structural-validation",
        "stage3.3.5-planner-invocation-plan-generation",
        "stage3.3.6-plan-validation-feasibility-gate",
        "stage3.3.7-plan-versioning-replanning-supersession",
        "stage3.3.8-task-readiness-scheduling-projection",
        "stage3.3.9-planning-event-lineage-replay-recovery",
        "stage3.3.10-planning-acceptance-regression-gate",
    ]
    assert health["mission_repository_migration_level"] == 53
    assert health["mission_cleanup_completion_schema_version"] == CLEANUP_COMPLETION_SCHEMA_VERSION
    assert health["mission_cleanup_completion_mode"] == CLEANUP_COMPLETION_MODE
    assert health["mission_cleanup_command"] == CLEANUP_COMMAND
    assert health["mission_cleanup_state"] == CLEANUP_STATE
    assert health["mission_completion_command"] == COMPLETION_COMMAND
    assert health["mission_completion_state"] == COMPLETION_STATE
    assert health["mission_completion_verification_status"] == COMPLETION_VERIFICATION_STATUS
    assert health["mission_completion_exact_success_criteria_coverage_required"] is True
    assert health["mission_completion_cleanup_checks_required"] is True
    assert health["mission_completion_evidence_refs_required"] is True
    assert health["mission_completion_nested_evidence_binding_required"] is True
    assert health["mission_completion_outstanding_critical_dependencies_required"] == 0
    assert health["mission_completion_requires_stage3_2_4_run_lineage"] is True
    assert health["mission_completion_requires_stage3_2_8_cleanup_lineage"] is True
    assert health["mission_lifecycle_stage3_2_8_completion_gate_enabled"] is True
    assert health["mission_cleanup_action_performed_by_orchestrator"] is False
    assert health["mission_completion_governance_query_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_cleanup_contract_before_run_is_not_ready_and_exposes_request_contract(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "contract-before-run")
    view = service.get_mission_cleanup_completion_contract(mission_id)["cleanup_completion"]
    assert view["schema_version"] == CLEANUP_COMPLETION_SCHEMA_VERSION
    assert view["current_state"] == "CREATED"
    assert view["completion_prerequisites_ready"] is False
    assert view["run_activation_lineage"]["valid"] is False
    assert view["completion_request_contract"]["criteria_results_exact_coverage_required"] is True
    assert view["completion_request_contract"]["nested_evidence_refs_must_be_bound_to_command"] is True
    assert view["cleanup_action_performed_by_orchestrator"] is False


def test_begin_cleanup_from_running_records_durable_stage328_control_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "cleanup-running")
    activate_running(service, mission_id)
    result = execute(
        service,
        mission_id,
        "BEGIN_CLEANUP",
        "cleanup",
        metadata={"stage": "3.2.8", "cleanup": {"scope": "LOCAL_FINALIZATION"}},
    )
    control = result["cleanup_control"]
    assert result["mission_state"]["state"] == CLEANUP_STATE
    assert control["schema_version"] == CLEANUP_COMPLETION_SCHEMA_VERSION
    assert control["cleanup_id"].startswith(f"cleanup:{mission_id}:")
    assert control["from_state"] == "RUNNING"
    assert control["run_activation_proof"]["valid"] is True
    assert control["completion_blockers"] == []
    assert control["completion_prerequisites_ready"] is True
    assert control["cleanup_verified"] is False
    assert control["verified_completion_claimed"] is False
    assert control["cleanup_context"] == {"scope": "LOCAL_FINALIZATION"}
    assert result["transition"]["metadata"]["mission_cleanup_control"] == control


def test_begin_cleanup_from_pause_of_running_preserves_pause_but_has_no_completion_blocker(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "cleanup-paused-running")
    activate_running(service, mission_id)
    paused = execute(service, mission_id, "PAUSE", "pause")
    cleanup = execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    control = cleanup["cleanup_control"]
    assert control["from_state"] == "PAUSED"
    assert control["active_pause"]["pause_id"] == paused["pause_control"]["pause_id"]
    assert control["active_pause"]["paused_from_state"] == "RUNNING"
    assert control["completion_blockers"] == []
    assert control["completion_prerequisites_ready"] is True


def test_complete_happy_path_persists_verified_completion_and_terminal_projection(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "complete-happy", criteria_count=2)
    activate_running(service, mission_id)
    cleanup = execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs, metadata = valid_completion_bundle(2, prefix="happy")
    result = execute(
        service,
        mission_id,
        "COMPLETE",
        "complete",
        evidence_refs=refs,
        metadata=metadata,
    )
    verification = result["completion_verification"]
    assert result["mission_state"]["state"] == COMPLETION_STATE
    assert verification["schema_version"] == CLEANUP_COMPLETION_SCHEMA_VERSION
    assert verification["completion_id"].startswith(f"completion:{mission_id}:")
    assert verification["cleanup_id"] == cleanup["cleanup_control"]["cleanup_id"]
    assert verification["verification_status"] == COMPLETION_VERIFICATION_STATUS
    assert verification["objective_status"] == OBJECTIVE_COMPLETION_STATUS
    assert verification["success_criteria_count"] == 2
    assert len(verification["criteria_results"]) == 2
    assert verification["cleanup_status"] == CLEANUP_VERIFICATION_STATUS
    assert verification["outstanding_critical_dependencies"] == 0
    assert verification["verified_completion_claimed"] is True
    assert verification["cleanup_completion_gate_applied"] is True
    assert verification["completion_evidence_refs"] == refs
    assert result["transition"]["metadata"]["mission_completion_verification"] == verification

    terminal = service.get_mission_terminal_semantics_contract(mission_id)["terminal_semantics"]
    assert terminal["current_terminal_lineage"]["valid"] is True
    assert terminal["current_terminal_lineage"]["status"] == "VALID_VERIFIED_COMPLETION"
    assert terminal["verified_completion_claimed"] is True
    assert terminal["cleanup_completion_gate_applied"] is True


def test_cleanup_completion_discovery_marks_complete_eligible_but_request_evidence_required_at_execution(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "discovery")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert "COMPLETE" in view["topology_eligible_commands"]
    assert "COMPLETE" in view["guard_eligible_commands"]
    assert view["cleanup_completion"]["completion_prerequisites_ready"] is True
    assert view["cleanup_completion"]["completion_request_required_at_execution"] is True
    evaluation = next(x for x in view["guard_evaluations"] if x["command"] == "COMPLETE")
    declaration = next(x for x in evaluation["checks"] if x["guard_id"] == "COMPLETION_DECLARATION_VERIFIED")
    assert declaration["status"] == "PASS"
    assert declaration["observed"] == "REQUEST_REQUIRED_AT_EXECUTION"
    assert "COMPLETION_SUCCESS_CRITERIA_COVERAGE" in view["lifecycle_guard_matrix"]["checks"]


def test_complete_without_completion_declaration_fails_closed_without_state_transition(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "missing-declaration")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    t0 = service.get_mission_state_history(mission_id)["transition_count"]
    e0 = service.get_mission_events(mission_id)["event_count"]
    with pytest.raises(MissionLifecycleGuardRejected, match="COMPLETION_DECLARATION_VERIFIED"):
        execute(service, mission_id, "COMPLETE", "missing", evidence_refs=["evidence:unbound"])
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == CLEANUP_STATE
    assert service.get_mission_state_history(mission_id)["transition_count"] == t0
    assert service.get_mission_events(mission_id)["event_count"] == e0


def test_complete_requires_objective_satisfaction_with_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "objective-evidence")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs, metadata = valid_completion_bundle(2, prefix="objective")
    metadata["completion"]["objective_evidence_refs"] = []
    with pytest.raises(MissionLifecycleGuardRejected, match="COMPLETION_OBJECTIVE_SATISFIED"):
        execute(service, mission_id, "COMPLETE", "objective-fail", evidence_refs=refs, metadata=metadata)


def test_complete_requires_exact_success_criteria_coverage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "criteria-coverage", criteria_count=2)
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs, metadata = valid_completion_bundle(2, prefix="criteria")
    metadata["completion"]["criteria_results"] = metadata["completion"]["criteria_results"][:1]
    with pytest.raises(MissionLifecycleGuardRejected, match="COMPLETION_SUCCESS_CRITERIA_COVERAGE"):
        execute(service, mission_id, "COMPLETE", "criteria-fail", evidence_refs=refs, metadata=metadata)


def test_complete_requires_pass_cleanup_checks(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "cleanup-check")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs, metadata = valid_completion_bundle(2, prefix="cleanup-check")
    metadata["completion"]["cleanup_checks"][0]["status"] = "FAIL"
    with pytest.raises(MissionLifecycleGuardRejected, match="COMPLETION_CLEANUP_VERIFIED"):
        execute(service, mission_id, "COMPLETE", "cleanup-check-fail", evidence_refs=refs, metadata=metadata)


def test_complete_requires_zero_outstanding_critical_dependencies(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "critical-deps")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs, metadata = valid_completion_bundle(2, prefix="critical")
    metadata["completion"]["outstanding_critical_dependencies"] = 1
    with pytest.raises(MissionLifecycleGuardRejected, match="COMPLETION_CRITICAL_DEPENDENCIES_CLEAR"):
        execute(service, mission_id, "COMPLETE", "critical-fail", evidence_refs=refs, metadata=metadata)


def test_complete_requires_nested_evidence_refs_to_be_bound_to_command(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "evidence-binding")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs, metadata = valid_completion_bundle(2, prefix="binding")
    command_refs = refs[:-1]  # cleanup evidence is nested but deliberately omitted from command envelope
    with pytest.raises(MissionLifecycleGuardRejected, match="COMPLETION_EVIDENCE_REFS_BOUND"):
        execute(service, mission_id, "COMPLETE", "binding-fail", evidence_refs=command_refs, metadata=metadata)


def test_begin_cleanup_rejects_legacy_running_state_without_stage324_run_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-running")
    direct_transition(service, mission_id, "PIP_BOUND", "PIP_BOUND")
    direct_transition(service, mission_id, "PLANNING", "PLANNING")
    direct_transition(service, mission_id, "RUNNING", "RUNNING")
    with pytest.raises(MissionLifecycleGuardRejected, match="RUN_ACTIVATION_LINEAGE_FOR_CLEANUP"):
        execute(service, mission_id, "BEGIN_CLEANUP", "legacy-cleanup")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"


def test_pause_of_waiting_dependency_can_enter_cleanup_but_verified_completion_is_blocked(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "paused-waiting")
    activate_running(service, mission_id)
    wait = execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait", dependency_id="dep-stage328-blocked")
    assert wait["mission_state"]["state"] == "WAITING_EVIDENCE"
    execute(service, mission_id, "PAUSE", "pause")
    cleanup = execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    assert "UNRESOLVED_WAITING_DEPENDENCY" in cleanup["cleanup_control"]["completion_blockers"]
    refs, metadata = valid_completion_bundle(2, prefix="blocked-wait")
    with pytest.raises(MissionLifecycleGuardRejected, match="CLEANUP_COMPLETION_BLOCKERS_CLEAR"):
        execute(service, mission_id, "COMPLETE", "blocked-complete", evidence_refs=refs, metadata=metadata)
    view = service.get_mission_cleanup_completion_contract(mission_id)["cleanup_completion"]
    assert view["completion_prerequisites_ready"] is False


def test_generic_guarded_lifecycle_complete_also_generates_stage328_verification(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic-complete", criteria_count=1)
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    refs, metadata = valid_completion_bundle(1, prefix="generic")
    generic = {
        "command_id": "generic-stage328-complete",
        "idempotency_key": "generic-stage328-complete-idem",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": vector["version_sha256"],
        "payload": {
            "command": "COMPLETE",
            "expected_state_version": state["state_version"],
            "actor": "stage3.2.8-pytest",
            "reason_code": "GENERIC_STAGE328_COMPLETE",
            "reason": "Generic guarded lifecycle path must enforce Stage 3.2.8 completion semantics",
            "evidence_refs": refs,
            "metadata": metadata,
        },
        "submitted_by": "stage3.2.8-pytest",
        "metadata": {},
    }
    result = service.execute_mission_command(mission_id, generic)["result"]
    assert result["mission_state"]["state"] == "COMPLETED"
    assert result["completion_verification"]["verified_completion_claimed"] is True
    assert result["transition"]["metadata"]["mission_completion_verification"] == result["completion_verification"]


def test_exact_complete_command_replay_is_idempotent_without_duplicate_transition_or_event(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "completion-replay", criteria_count=1)
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs, metadata = valid_completion_bundle(1, prefix="replay")
    request = lifecycle_request(
        service,
        mission_id,
        "COMPLETE",
        "replay",
        evidence_refs=refs,
        metadata=metadata,
    )
    t0 = service.get_mission_state_history(mission_id)["transition_count"]
    events0 = service.get_mission_events(mission_id)
    e0 = events0["event_count"]
    first = service.execute_mission_lifecycle_command(mission_id, request)
    t1 = service.get_mission_state_history(mission_id)["transition_count"]
    events1 = service.get_mission_events(mission_id)
    e1 = events1["event_count"]
    assert t1 == t0 + 1
    assert e1 == e0 + 2
    appended = events1["events"][e0:]
    assert [event["event_type"] for event in appended] == [
        "MISSION_STATE_TRANSITIONED",
        "MISSION_COMMAND_COMPLETED",
    ]
    assert appended[0]["causation_id"] == first["transition"]["transition_id"]
    assert appended[0]["payload"]["to_state"] == "COMPLETED"
    assert appended[1]["causation_id"] == request["command_id"]
    assert appended[1]["payload"]["command_id"] == request["command_id"]
    assert appended[1]["parent_event_id"] == appended[0]["event_id"]
    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["completion_verification"] == first["completion_verification"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == t1
    assert service.get_mission_events(mission_id)["event_count"] == e1


def test_legacy_direct_completed_is_visible_but_not_accepted_as_verified_completion(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-completed")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    direct_transition(service, mission_id, "COMPLETED", "COMPLETE")
    terminal = service.get_mission_terminal_semantics_contract(mission_id)["terminal_semantics"]
    lineage = terminal["current_terminal_lineage"]
    assert lineage["valid"] is False
    assert lineage["status"] == "LEGACY_DIRECT_COMPLETED_NO_STAGE_3_2_8_EVIDENCE"
    assert terminal["verified_completion_claimed"] is False
    completion = service.get_mission_cleanup_completion_contract(mission_id)["cleanup_completion"]
    assert completion["verified_completion_claimed"] is False


def test_failure_during_cleanup_remains_failure_and_never_claims_verified_completion(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "cleanup-failure")
    activate_running(service, mission_id)
    cleanup = execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    failed = execute(service, mission_id, "FAIL", "fail")
    assert failed["mission_state"]["state"] == "FAILED"
    assert failed["terminal_control"]["from_state"] == CLEANUP_STATE
    assert failed["terminal_control"]["verified_completion_claimed"] is False
    assert failed["terminal_control"]["cleanup_completion_gate_applied"] is False
    terminal = service.get_mission_terminal_semantics_contract(mission_id)["terminal_semantics"]
    assert terminal["current_terminal_lineage"]["terminal_command"] == "FAIL"
    assert terminal["verified_completion_claimed"] is False
    assert cleanup["cleanup_control"]["verified_completion_claimed"] is False
