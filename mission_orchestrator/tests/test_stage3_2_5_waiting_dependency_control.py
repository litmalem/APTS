from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionLifecycleGuardRejected
from mission_orchestrator.mission_lifecycle import (
    LIFECYCLE_COMMAND_OPERATION,
    WAITING_DEPENDENCY_MODE,
    WAITING_DEPENDENCY_SCHEMA_VERSION,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage325-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.2.5 waiting dependency control must remain local-only: unexpected call {name}")


def make_service(tmp_path: Path) -> CanonicalMissionService:
    no_call = NoCallExternal()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str) -> dict:
    return {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE325",
        "created_by": "stage3.2.5-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage325-lab"},
        "success_criteria": [{"metric": "waiting_dependency_control", "expected": True}],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-{key}",
        "pip_version": "10",
        "metadata": {"environment": "LAB", "stage": "3.2.5"},
    }


def create_mission(service: CanonicalMissionService, key: str) -> str:
    return service.create_mission(mission_payload(key))["canonical_identity"]["mission_id"]


def lifecycle_request(
    service: CanonicalMissionService,
    mission_id: str,
    command: str,
    idx: str,
    *,
    dependency_id: str | None = None,
    dependency_kind: str | None = None,
    resolution_id: str | None = None,
    resolution_status: str = "SATISFIED",
    resolved_by: str = "stage3.2.5-pytest",
    evidence_refs: list[str] | None = None,
    include_dependency: bool = True,
    include_resolution: bool = True,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "command_id": f"lc-325-{idx}",
        "idempotency_key": f"idem-lc-325-{idx}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.5-pytest",
        "reason_code": f"STAGE325_{command}",
        "reason": f"Stage 3.2.5 lifecycle command {command}",
        "evidence_refs": list(evidence_refs if evidence_refs is not None else ["evidence:test:stage325"]),
        "metadata": {"stage": "3.2.5", "idx": idx},
    }
    if command in {"WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"} and include_dependency:
        body["metadata"]["dependency"] = {
            "dependency_id": dependency_id or f"dep-325-{idx}",
            "kind": dependency_kind or ("EVIDENCE" if command == "WAIT_FOR_EVIDENCE" else "APPROVAL"),
            "description": f"Stage 3.2.5 dependency for {idx}",
        }
    if command == "START" and state["state"] in {"WAITING_EVIDENCE", "WAITING_APPROVAL"} and include_resolution:
        active = service.get_mission_waiting_dependency_contract(mission_id)["waiting_dependency"]["active_dependency"]
        body["metadata"]["dependency_resolution"] = {
            "dependency_id": resolution_id or active["dependency_id"],
            "status": resolution_status,
            "resolved_by": resolved_by,
        }
    return body


def execute(service, mission_id: str, command: str, idx: str, **kwargs):
    return service.execute_mission_lifecycle_command(
        mission_id,
        lifecycle_request(service, mission_id, command, idx, **kwargs),
    )


def activate_running(service: CanonicalMissionService, mission_id: str) -> None:
    execute(service, mission_id, "BIND_PIP", "bind")
    execute(service, mission_id, "START_PLANNING", "plan")
    execute(service, mission_id, "START", "run")


def direct_transition(service, mission_id: str, to_state: str, idx: str):
    state = service.get_mission_state(mission_id)["mission_state"]
    return service.transition_mission_state(
        mission_id,
        {
            "expected_state_version": state["state_version"],
            "to_state": to_state,
            "actor": "stage3.2.5-legacy-test",
            "reason_code": f"LEGACY_{idx}",
            "reason": "Exercise preserved Stage-3.1 direct state transition API",
            "evidence_refs": [],
            "metadata": {"legacy_test": True, "stage": "3.2.5"},
        },
    )


def test_health_declares_stage325_without_migration_or_authority_expansion(tmp_path):
    health = make_service(tmp_path).health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][14:30] == [
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
    assert health["mission_repository_migration_level"] == 53
    assert health["mission_waiting_dependency_schema_version"] == WAITING_DEPENDENCY_SCHEMA_VERSION
    assert health["mission_waiting_dependency_mode"] == WAITING_DEPENDENCY_MODE
    assert health["mission_waiting_dependency_wait_commands"] == ["WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"]
    assert health["mission_waiting_dependency_return_command"] == "START"
    assert health["mission_waiting_dependency_resolution_status_required"] == "SATISFIED"
    assert health["mission_waiting_dependency_evidence_refs_required_for_return"] is True
    assert health["mission_waiting_approval_is_governance_authorization"] is False
    assert health["mission_waiting_dependency_external_queries"] is False
    assert health["mission_lifecycle_stage3_2_5_dependency_resolution_enabled"] is True
    assert health["mission_lifecycle_stage3_2_6_pause_resume_replan_enabled"] is True
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_waiting_contract_at_running_has_no_active_dependency_and_is_local_only(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "contract-running")
    activate_running(service, mission_id)
    view = service.get_mission_waiting_dependency_contract(mission_id)["waiting_dependency"]
    assert view["schema_version"] == WAITING_DEPENDENCY_SCHEMA_VERSION
    assert view["current_state"] == "RUNNING"
    assert view["active_dependency"] is None
    assert view["wait_commands"]["WAIT_FOR_EVIDENCE"]["target_state"] == "WAITING_EVIDENCE"
    assert view["wait_commands"]["WAIT_FOR_APPROVAL"]["target_state"] == "WAITING_APPROVAL"
    assert view["approval_dependency_is_governance_authorization"] is False
    assert view["governance_authorization_query_performed"] is False


def test_wait_for_evidence_requires_explicit_dependency_declaration(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "missing-declaration")
    activate_running(service, mission_id)
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_DECLARATION_FOR_WAIT"):
        execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait-missing", include_dependency=False)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"


def test_wait_for_approval_rejects_dependency_kind_mismatch(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "kind-mismatch")
    activate_running(service, mission_id)
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_DECLARATION_FOR_WAIT"):
        execute(
            service,
            mission_id,
            "WAIT_FOR_APPROVAL",
            "wait-kind-mismatch",
            dependency_kind="EVIDENCE",
        )
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"


def test_wait_for_evidence_records_durable_typed_dependency_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "evidence-wait")
    activate_running(service, mission_id)
    result = execute(service, mission_id, "WAIT_FOR_EVIDENCE", "evidence", dependency_id="dep-evidence-1")
    assert result["mission_state"]["state"] == "WAITING_EVIDENCE"
    dep = result["waiting_dependency"]
    assert dep["schema_version"] == WAITING_DEPENDENCY_SCHEMA_VERSION
    assert dep["dependency_id"] == "dep-evidence-1"
    assert dep["kind"] == "EVIDENCE"
    assert dep["dependency_declared"] is True
    assert dep["approval_dependency_is_governance_authorization"] is False
    assert dep["authorization_granted"] is False
    assert result["transition"]["metadata"]["mission_waiting_dependency"] == dep
    view = service.get_mission_waiting_dependency_contract(mission_id)["waiting_dependency"]
    assert view["active_dependency"]["valid"] is True
    assert view["active_dependency"]["dependency_id"] == "dep-evidence-1"


def test_wait_for_approval_records_workflow_dependency_not_governance_authorization(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "approval-wait")
    activate_running(service, mission_id)
    result = execute(service, mission_id, "WAIT_FOR_APPROVAL", "approval", dependency_id="dep-approval-1")
    dep = result["waiting_dependency"]
    assert result["mission_state"]["state"] == "WAITING_APPROVAL"
    assert dep["kind"] == "APPROVAL"
    assert dep["approval_dependency_is_governance_authorization"] is False
    assert dep["governance_authorization_query_performed"] is False
    assert dep["authorization_granted"] is False
    assert dep["execution_authorized"] is False


def test_start_from_waiting_evidence_fails_without_resolution_metadata(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "return-missing-resolution")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait")
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN"):
        execute(service, mission_id, "START", "return", include_resolution=False)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "WAITING_EVIDENCE"


def test_start_from_waiting_rejects_resolution_for_wrong_dependency_id(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "wrong-resolution-id")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_APPROVAL", "wait", dependency_id="dep-correct")
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN"):
        execute(service, mission_id, "START", "return", resolution_id="dep-wrong")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "WAITING_APPROVAL"


def test_start_from_waiting_rejects_non_satisfied_resolution(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "not-satisfied")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait")
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN"):
        execute(service, mission_id, "START", "return", resolution_status="PENDING")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "WAITING_EVIDENCE"


def test_start_from_waiting_requires_non_empty_resolution_evidence_refs(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "missing-resolution-evidence")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait")
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_RESOLUTION_EVIDENCE_FOR_RETURN"):
        execute(service, mission_id, "START", "return", evidence_refs=[])
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "WAITING_EVIDENCE"


def test_valid_evidence_resolution_returns_to_running_with_durable_resolution_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "valid-evidence-return")
    activate_running(service, mission_id)
    wait = execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait", dependency_id="dep-evidence-return")
    result = execute(service, mission_id, "START", "return", evidence_refs=["evidence:artifact:42"])
    assert result["mission_state"]["state"] == "RUNNING"
    resolution = result["waiting_dependency_resolution"]
    assert resolution["resolution_ready"] is True
    assert resolution["dependency_id"] == "dep-evidence-return"
    assert resolution["kind"] == "EVIDENCE"
    assert resolution["wait_transition_id"] == wait["transition"]["transition_id"]
    assert resolution["resolution_status"] == "SATISFIED"
    assert resolution["resolution_evidence_refs"] == ["evidence:artifact:42"]
    assert resolution["authorization_granted"] is False
    assert result["transition"]["metadata"]["mission_waiting_dependency_resolution"] == resolution


def test_valid_approval_resolution_returns_to_running_without_authorization_semantics(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "valid-approval-return")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_APPROVAL", "wait", dependency_id="dep-approval-return")
    result = execute(service, mission_id, "START", "return", evidence_refs=["approval:ticket:77"])
    resolution = result["waiting_dependency_resolution"]
    assert result["mission_state"]["state"] == "RUNNING"
    assert resolution["kind"] == "APPROVAL"
    assert resolution["approval_dependency_is_governance_authorization"] is False
    assert resolution["governance_authorization_query_performed"] is False
    assert resolution["authorization_granted"] is False
    assert resolution["execution_authorized"] is False
    assert result["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"


def test_legacy_direct_waiting_state_cannot_bypass_dependency_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-waiting")
    activate_running(service, mission_id)
    direct_transition(service, mission_id, "WAITING_EVIDENCE", "waiting-evidence")
    view = service.get_mission_lifecycle_command_contract(mission_id)
    evaluation = next(x for x in view["guard_evaluations"] if x["command"] == "START")
    assert "WAITING_DEPENDENCY_LINEAGE_FOR_RETURN" in evaluation["failed_guard_ids"]
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_LINEAGE_FOR_RETURN"):
        execute(service, mission_id, "START", "legacy-return", resolution_id="dep-any")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "WAITING_EVIDENCE"


def test_exact_wait_and_resolution_replays_do_not_duplicate_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replay")
    activate_running(service, mission_id)
    wait_request = lifecycle_request(service, mission_id, "WAIT_FOR_EVIDENCE", "wait-replay")
    first_wait = service.execute_mission_lifecycle_command(mission_id, wait_request)
    t1 = service.get_mission_state_history(mission_id)["transition_count"]
    e1 = service.get_mission_events(mission_id)["event_count"]
    replay_wait = service.execute_mission_lifecycle_command(mission_id, wait_request)
    assert replay_wait["idempotent_replay"] is True
    assert replay_wait["waiting_dependency"] == first_wait["waiting_dependency"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == t1
    assert service.get_mission_events(mission_id)["event_count"] == e1

    return_request = lifecycle_request(service, mission_id, "START", "return-replay", evidence_refs=["evidence:replay:ok"])
    first_return = service.execute_mission_lifecycle_command(mission_id, return_request)
    t2 = service.get_mission_state_history(mission_id)["transition_count"]
    e2 = service.get_mission_events(mission_id)["event_count"]
    replay_return = service.execute_mission_lifecycle_command(mission_id, return_request)
    assert replay_return["idempotent_replay"] is True
    assert replay_return["waiting_dependency_resolution"] == first_return["waiting_dependency_resolution"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == t2
    assert service.get_mission_events(mission_id)["event_count"] == e2


def test_generic_command_gate_cannot_bypass_waiting_resolution_guards(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic-bypass")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    generic = {
        "command_id": "cmd-325-generic-return",
        "idempotency_key": "idem-cmd-325-generic-return",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": vector["version_sha256"],
        "payload": {
            "command": "START",
            "expected_state_version": state["state_version"],
            "actor": "stage3.2.5-pytest",
            "reason_code": "GENERIC_RETURN",
            "evidence_refs": ["evidence:generic"],
            "metadata": {},
        },
        "submitted_by": "stage3.2.5-pytest",
        "metadata": {},
    }
    with pytest.raises(MissionLifecycleGuardRejected, match="WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN"):
        service.execute_mission_command(mission_id, generic)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "WAITING_EVIDENCE"


def test_replan_remains_available_from_waiting_without_claiming_dependency_satisfaction(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replan")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_APPROVAL", "wait")
    result = execute(service, mission_id, "REPLAN", "replan")
    assert result["mission_state"]["state"] == "REPLANNING"
    assert result["waiting_dependency_resolution"] is None
    assert result["lifecycle_guard"]["allowed"] is True
