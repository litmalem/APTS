from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionCommandConflict,
    MissionLifecycleGuardRejected,
)
from mission_orchestrator.mission_lifecycle import (
    COMMAND_SOURCE_STATES,
    GUARD_MATRIX_APPLIES_TO,
    GUARD_MATRIX_MODE,
    GUARD_MATRIX_SCHEMA_VERSION,
    LIFECYCLE_COMMAND_OPERATION,
    PIP_REQUIRED_COMMANDS,
    lifecycle_guard_matrix_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage322-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.2.2 local lifecycle guard must not call external dependency: {name}")


def make_service(tmp_path: Path) -> CanonicalMissionService:
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    no_call = NoCallExternal()
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str, *, with_pip: bool) -> dict:
    body = {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE322",
        "created_by": "stage3.2.2-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage322-lab"},
        "success_criteria": [{"metric": "guard_matrix", "expected": True}],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "metadata": {"environment": "LAB", "stage": "3.2.2"},
    }
    if with_pip:
        body["pip_id"] = f"pip-{key}"
        body["pip_version"] = "1"
    return body


def create_mission(service: CanonicalMissionService, key: str, *, with_pip: bool) -> str:
    created = service.create_mission(mission_payload(key, with_pip=with_pip))
    return created["canonical_identity"]["mission_id"]


def lifecycle_request(
    service: CanonicalMissionService,
    mission_id: str,
    command: str,
    *,
    command_id: str,
    target_state: str | None = None,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "command_id": command_id,
        "idempotency_key": f"idem-{command_id}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.2-pytest",
        "reason_code": f"LC_{command}",
        "reason": f"Stage 3.2.2 lifecycle command {command}",
        "evidence_refs": ["evidence:test:stage322"],
        "metadata": {"stage": "3.2.2"},
    }
    if target_state is not None:
        body["target_state"] = target_state
    return body


def execute(service, mission_id, command, idx, *, target_state=None):
    return service.execute_mission_lifecycle_command(
        mission_id,
        lifecycle_request(
            service,
            mission_id,
            command,
            command_id=f"lc-322-{idx}",
            target_state=target_state,
        ),
    )


def direct_transition(service, mission_id, to_state: str, idx: int):
    state = service.get_mission_state(mission_id)["mission_state"]
    return service.transition_mission_state(
        mission_id,
        {
            "expected_state_version": state["state_version"],
            "to_state": to_state,
            "actor": "stage3.2.2-legacy-test",
            "reason_code": f"LEGACY_{idx}",
            "reason": "Exercise preserved Stage-3.1 transition API",
            "evidence_refs": [],
            "metadata": {"legacy_test": True},
        },
    )


def test_health_declares_stage322_guard_without_migration_or_authority_expansion(tmp_path):
    health = make_service(tmp_path).health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][12:30] == [
        "stage3.2.3-mission-pip-activation",
        "stage3.2.4-planning-run-activation",
        "stage3.2.5-waiting-dependency-control",
        "stage3.2.6-pause-resume-replanning-control",
        "stage3.2.7-abort-failure-expiration-semantics",
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
    assert "stage3.2.1-mission-lifecycle-command-contract" in health["supported_controls"]
    assert health["mission_repository_migration_level"] == 53
    assert health["mission_lifecycle_command_stage3_2_2_guard_matrix_enabled"] is True
    assert health["mission_lifecycle_guard_matrix_schema_version"] == GUARD_MATRIX_SCHEMA_VERSION
    assert health["mission_lifecycle_guard_matrix_mode"] == GUARD_MATRIX_MODE
    assert health["mission_lifecycle_guard_matrix_applies_to"] == GUARD_MATRIX_APPLIES_TO
    assert health["mission_lifecycle_guard_matrix_local_only"] is True
    assert health["mission_lifecycle_guard_matrix_external_authority_queries"] is False
    assert health["mission_lifecycle_legacy_state_transition_api_preserved"] is True
    assert health["mission_lifecycle_stage3_2_5_dependency_resolution_enabled"] is True
    assert health["mission_lifecycle_stage3_2_8_completion_gate_enabled"] is True
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_guard_matrix_contract_is_explicit_and_fail_safe_terminal_commands_remain_available():
    contract = lifecycle_guard_matrix_contract()
    assert contract["schema_version"] == GUARD_MATRIX_SCHEMA_VERSION
    assert contract["mode"] == GUARD_MATRIX_MODE
    assert contract["applies_to"] == LIFECYCLE_COMMAND_OPERATION
    assert set(contract["fail_safe_terminal_commands"]) == {"ABORT", "FAIL", "EXPIRE"}
    assert "PIP_BINDING_COMPLETE_WHEN_REQUIRED" in contract["checks"]
    assert set(PIP_REQUIRED_COMMANDS).issubset(set(contract["pip_required_commands"]))
    for command in ("ABORT", "FAIL", "EXPIRE"):
        assert set(COMMAND_SOURCE_STATES[command])


def test_contract_discovery_distinguishes_topology_from_guard_eligibility_when_pip_missing(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "missing-pip-discovery", with_pip=False)
    view = service.get_mission_lifecycle_command_contract(mission_id)

    assert "BIND_PIP" in view["topology_eligible_commands"]
    assert "BIND_PIP" not in view["guard_eligible_commands"]
    assert set(view["guard_eligible_commands"]) == {"PAUSE", "ABORT", "FAIL", "EXPIRE"}
    bind_eval = next(x for x in view["guard_evaluations"] if x["command"] == "BIND_PIP")
    assert bind_eval["allowed"] is False
    assert bind_eval["failed_guard_ids"] == ["PIP_BINDING_COMPLETE_WHEN_REQUIRED"]
    assert view["authority_query_performed"] is False
    assert "NOT_GOVERNANCE_AUTHORIZATION" in view["eligibility_semantics"]


def test_bind_pip_rejected_fail_closed_when_immutable_pip_binding_is_missing(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "missing-pip", with_pip=False)
    before_events = service.get_mission_events(mission_id)["event_count"]

    with pytest.raises(MissionLifecycleGuardRejected, match="PIP_BINDING_COMPLETE_WHEN_REQUIRED"):
        execute(service, mission_id, "BIND_PIP", 1)

    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"
    assert service.get_mission_state_history(mission_id)["transition_count"] == 0
    assert service.get_mission_events(mission_id)["event_count"] == before_events
    journal = service.get_mission_command_history(mission_id)["commands"]
    assert len(journal) == 1
    assert journal[0]["operation"] == LIFECYCLE_COMMAND_OPERATION
    assert journal[0]["command_status"] == "FAILED"
    assert "PIP_BINDING_COMPLETE_WHEN_REQUIRED" in journal[0]["last_error"]


def test_bind_pip_with_complete_immutable_pip_binding_passes_all_guards(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "complete-pip", with_pip=True)
    result = execute(service, mission_id, "BIND_PIP", 2)

    assert result["mission_state"]["state"] == "PIP_BOUND"
    assert result["lifecycle_guard"]["allowed"] is True
    assert result["lifecycle_guard"]["failed_guard_ids"] == []
    assert all(check["status"] == "PASS" for check in result["lifecycle_guard"]["checks"])
    assert result["lifecycle_guard"]["authority_query_performed"] is False


def test_start_planning_cannot_use_legacy_pip_bound_state_without_actual_pip_binding(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-state-no-pip", with_pip=False)
    direct_transition(service, mission_id, "PIP_BOUND", 1)

    with pytest.raises(MissionLifecycleGuardRejected, match="PIP_BINDING_COMPLETE_WHEN_REQUIRED"):
        execute(service, mission_id, "START_PLANNING", 3)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PIP_BOUND"


def test_semantic_source_guard_rejects_start_from_paused_even_though_target_topology_is_legal(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "paused-semantic", with_pip=True)
    execute(service, mission_id, "BIND_PIP", 4)
    execute(service, mission_id, "START_PLANNING", 5)
    execute(service, mission_id, "START", 6)
    execute(service, mission_id, "PAUSE", 7)

    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert "START" in view["topology_eligible_commands"]
    assert "START" not in view["guard_eligible_commands"]
    assert "RESUME" in view["guard_eligible_commands"]
    assert "RUNNING" in view["guard_eligible_resume_targets"]

    with pytest.raises(MissionLifecycleGuardRejected, match="SOURCE_STATE_ALLOWED_FOR_COMMAND"):
        execute(service, mission_id, "START", 8)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PAUSED"


def test_resume_is_the_semantic_command_for_paused_to_running(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "resume-semantic", with_pip=True)
    execute(service, mission_id, "BIND_PIP", 9)
    execute(service, mission_id, "START_PLANNING", 10)
    execute(service, mission_id, "START", 11)
    execute(service, mission_id, "PAUSE", 12)

    resumed = execute(service, mission_id, "RESUME", 13, target_state="RUNNING")
    assert resumed["mission_state"]["state"] == "RUNNING"
    assert resumed["lifecycle_guard"]["allowed"] is True
    assert resumed["transition"]["metadata"]["lifecycle_guard_matrix_schema_version"] == GUARD_MATRIX_SCHEMA_VERSION


@pytest.mark.parametrize("command,target", [("ABORT", "ABORTED"), ("FAIL", "FAILED"), ("EXPIRE", "EXPIRED")])
def test_fail_safe_terminal_exit_is_not_blocked_by_missing_pip(tmp_path, command, target):
    service = make_service(tmp_path)
    mission_id = create_mission(service, f"failsafe-{command.lower()}", with_pip=False)
    result = execute(service, mission_id, command, f"terminal-{command}")
    assert result["mission_state"]["state"] == target
    pip_check = next(x for x in result["lifecycle_guard"]["checks"] if x["guard_id"] == "PIP_BINDING_COMPLETE_WHEN_REQUIRED")
    assert pip_check["status"] == "PASS"
    assert pip_check["required"] == "NOT_REQUIRED"


def test_generic_guarded_command_api_cannot_bypass_stage322_guard_matrix(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic-guard", with_pip=False)
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    generic = {
        "command_id": "generic-stage322-bind",
        "idempotency_key": "idem-generic-stage322-bind",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": vector["version_sha256"],
        "payload": {
            "command": "BIND_PIP",
            "expected_state_version": state["state_version"],
            "actor": "stage3.2.2-pytest",
            "reason_code": "GENERIC_BIND",
            "evidence_refs": [],
            "metadata": {},
        },
        "submitted_by": "stage3.2.2-pytest",
        "metadata": {},
    }
    with pytest.raises(MissionLifecycleGuardRejected):
        service.execute_mission_command(mission_id, generic)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"


def test_guard_rejection_does_not_create_command_completed_event(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "guard-lineage", with_pip=False)
    initial_types = [x["event_type"] for x in service.get_mission_events(mission_id)["events"]]
    assert initial_types == ["MISSION_REGISTERED"]

    with pytest.raises(MissionLifecycleGuardRejected):
        execute(service, mission_id, "BIND_PIP", 14)

    types = [x["event_type"] for x in service.get_mission_events(mission_id)["events"]]
    assert types == ["MISSION_REGISTERED"]


def test_failed_guard_command_is_not_replayed_as_success(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "failed-replay", with_pip=False)
    request = lifecycle_request(service, mission_id, "BIND_PIP", command_id="lc-failed-replay")
    with pytest.raises(MissionLifecycleGuardRejected):
        service.execute_mission_lifecycle_command(mission_id, request)
    with pytest.raises(MissionCommandConflict, match="guard matrix"):
        service.execute_mission_lifecycle_command(mission_id, request)


def test_guard_matrix_reports_dependency_and_stage328_completion_guards_with_governance_still_deferred(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "deferred-guards", with_pip=True)
    view = service.get_mission_lifecycle_command_contract(mission_id)
    deferred = set(view["lifecycle_guard_matrix"]["deferred_guards"])
    assert "WAITING_EVIDENCE_DEPENDENCY_SATISFACTION_STAGE_3_2_5" not in deferred
    assert "WAITING_APPROVAL_DEPENDENCY_SATISFACTION_STAGE_3_2_5" not in deferred
    checks = set(view["lifecycle_guard_matrix"]["checks"])
    assert "WAITING_DEPENDENCY_DECLARATION_FOR_WAIT" in checks
    assert "WAITING_DEPENDENCY_LINEAGE_FOR_RETURN" in checks
    assert "WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN" in checks
    assert "WAITING_DEPENDENCY_RESOLUTION_EVIDENCE_FOR_RETURN" in checks
    assert "CLEANUP_VERIFICATION_AND_COMPLETION_CRITERIA_STAGE_3_2_8" not in deferred
    assert "CLEANUP_LINEAGE_FOR_COMPLETION" in checks
    assert "COMPLETION_SUCCESS_CRITERIA_COVERAGE" in checks
    assert "COMPLETION_CLEANUP_VERIFIED" in checks
    assert "COMPLETION_EVIDENCE_REFS_BOUND" in checks
    assert "GOVERNANCE_AUTHORIZATION_REMAINS_EXTERNAL_APTS_GSS" in deferred
    assert view["lifecycle_guard_matrix"]["external_authority_queries"] is False
    assert view["target_action_dispatch_enabled"] is False
    assert view["target_actuation"] is False
