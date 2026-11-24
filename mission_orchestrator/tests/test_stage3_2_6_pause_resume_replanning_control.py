from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionLifecycleGuardRejected
from mission_orchestrator.mission_lifecycle import (
    LIFECYCLE_COMMAND_OPERATION,
    PAUSE_RESUME_REPLAN_MODE,
    PAUSE_RESUME_REPLAN_SCHEMA_VERSION,
    REPLAN_READINESS_STATUS,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage326-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.2.6 pause/resume/replan control must remain local-only: unexpected call {name}")


def make_service(tmp_path: Path) -> CanonicalMissionService:
    no_call = NoCallExternal()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str) -> dict:
    return {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE326",
        "created_by": "stage3.2.6-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage326-lab"},
        "success_criteria": [{"metric": "pause_resume_replan_control", "expected": True}],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-{key}",
        "pip_version": "11",
        "metadata": {"environment": "LAB", "stage": "3.2.6"},
    }


def create_mission(service: CanonicalMissionService, key: str) -> str:
    return service.create_mission(mission_payload(key))["canonical_identity"]["mission_id"]


def lifecycle_request(
    service: CanonicalMissionService,
    mission_id: str,
    command: str,
    idx: str,
    *,
    target_state: str | None = None,
    evidence_refs: list[str] | None = None,
    dependency_id: str | None = None,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "command_id": f"lc-326-{idx}",
        "idempotency_key": f"idem-lc-326-{idx}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.6-pytest",
        "reason_code": f"STAGE326_{command}",
        "reason": f"Stage 3.2.6 lifecycle command {command}",
        "evidence_refs": list(evidence_refs if evidence_refs is not None else ["evidence:test:stage326"]),
        "metadata": {"stage": "3.2.6", "idx": idx},
    }
    if target_state is not None:
        body["target_state"] = target_state
    if command in {"WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"}:
        body["metadata"]["dependency"] = {
            "dependency_id": dependency_id or f"dep-326-{idx}",
            "kind": "EVIDENCE" if command == "WAIT_FOR_EVIDENCE" else "APPROVAL",
            "description": "Stage 3.2.6 compatibility waiting dependency",
        }
    if command == "START" and state["state"] in {"WAITING_EVIDENCE", "WAITING_APPROVAL"}:
        active = service.get_mission_waiting_dependency_contract(mission_id)["waiting_dependency"]["active_dependency"]
        body["metadata"]["dependency_resolution"] = {
            "dependency_id": active["dependency_id"],
            "status": "SATISFIED",
            "resolved_by": "stage3.2.6-pytest",
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
            "actor": "stage3.2.6-legacy-test",
            "reason_code": f"LEGACY_{idx}",
            "reason": "Exercise preserved Stage-3.1 direct state transition API",
            "evidence_refs": [],
            "metadata": {"legacy_test": True, "stage": "3.2.6"},
        },
    )


def test_health_declares_stage326_without_migration_planner_or_authority_expansion(tmp_path):
    health = make_service(tmp_path).health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][15:30] == [
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
    assert health["mission_pause_resume_replan_schema_version"] == PAUSE_RESUME_REPLAN_SCHEMA_VERSION
    assert health["mission_pause_resume_replan_mode"] == PAUSE_RESUME_REPLAN_MODE
    assert health["mission_replan_readiness_status"] == REPLAN_READINESS_STATUS
    assert health["mission_lifecycle_stage3_2_6_pause_resume_replan_enabled"] is True
    assert health["mission_lifecycle_stage3_2_7_terminal_semantics_enabled"] is True
    assert health["mission_pause_resume_replan_planner_invocation_performed"] is False
    assert health["mission_pause_resume_replan_governance_query_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_pause_resume_replan_contract_is_local_and_empty_at_running(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "contract-running")
    activate_running(service, mission_id)
    view = service.get_mission_pause_resume_replan_contract(mission_id)["pause_resume_replan"]
    assert view["schema_version"] == PAUSE_RESUME_REPLAN_SCHEMA_VERSION
    assert view["current_state"] == "RUNNING"
    assert view["pause"]["active_pause"] is None
    assert view["replan"]["active_replan"] is None
    assert view["planner_invocation_performed"] is False
    assert view["governance_authorization_query_performed"] is False


def test_pause_from_running_records_durable_exact_source_context(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "pause-running")
    activate_running(service, mission_id)
    result = execute(service, mission_id, "PAUSE", "pause")
    pause = result["pause_control"]
    assert result["mission_state"]["state"] == "PAUSED"
    assert pause["schema_version"] == PAUSE_RESUME_REPLAN_SCHEMA_VERSION
    assert pause["pause_id"].startswith(f"pause:{mission_id}:")
    assert pause["from_state"] == "RUNNING"
    assert pause["to_state"] == "PAUSED"
    assert pause["planner_invocation_performed"] is False
    assert pause["authorization_granted"] is False
    assert result["transition"]["metadata"]["mission_pause_control"] == pause
    view = service.get_mission_pause_resume_replan_contract(mission_id)["pause_resume_replan"]
    assert view["pause"]["active_pause"]["valid"] is True
    assert view["resume"]["allowed_targets_for_active_pause"] == ["RUNNING"]


def test_exact_pause_replay_is_idempotent_without_duplicate_transition_or_event(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "pause-replay")
    activate_running(service, mission_id)
    request = lifecycle_request(service, mission_id, "PAUSE", "pause-replay")
    first = service.execute_mission_lifecycle_command(mission_id, request)
    t1 = service.get_mission_state_history(mission_id)["transition_count"]
    e1 = service.get_mission_events(mission_id)["event_count"]
    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["pause_control"] == first["pause_control"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == t1
    assert service.get_mission_events(mission_id)["event_count"] == e1


def test_legacy_direct_paused_state_cannot_bypass_pause_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-pause")
    activate_running(service, mission_id)
    direct_transition(service, mission_id, "PAUSED", "pause")
    with pytest.raises(MissionLifecycleGuardRejected, match="PAUSE_LINEAGE_FOR_RESUME"):
        execute(service, mission_id, "RESUME", "resume", target_state="RUNNING")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PAUSED"


def test_resume_from_running_pause_restores_running_with_durable_resume_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "resume-running")
    activate_running(service, mission_id)
    paused = execute(service, mission_id, "PAUSE", "pause")
    resumed = execute(service, mission_id, "RESUME", "resume", target_state="RUNNING")
    assert resumed["mission_state"]["state"] == "RUNNING"
    evidence = resumed["resume_control"]
    assert evidence["pause_id"] == paused["pause_control"]["pause_id"]
    assert evidence["paused_from_state"] == "RUNNING"
    assert evidence["to_state"] == "RUNNING"
    assert evidence["resume_prerequisite"]["valid"] is True
    assert resumed["transition"]["metadata"]["mission_resume_control"] == evidence


def test_resume_target_must_match_paused_source_policy(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "resume-target-policy")
    activate_running(service, mission_id)
    execute(service, mission_id, "PAUSE", "pause")
    with pytest.raises(MissionLifecycleGuardRejected, match="RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE"):
        execute(service, mission_id, "RESUME", "bad-resume", target_state="REPLANNING")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PAUSED"


def test_paused_waiting_dependency_cannot_resume_directly_to_running_but_can_replan(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "paused-wait")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_APPROVAL", "wait", dependency_id="dep-wait-pause")
    paused = execute(service, mission_id, "PAUSE", "pause")
    assert paused["pause_control"]["active_waiting_dependency"]["dependency_id"] == "dep-wait-pause"
    with pytest.raises(MissionLifecycleGuardRejected, match="RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE"):
        execute(service, mission_id, "RESUME", "bad-running", target_state="RUNNING")
    resumed = execute(service, mission_id, "RESUME", "safe-replan", target_state="REPLANNING")
    assert resumed["mission_state"]["state"] == "REPLANNING"
    assert resumed["resume_control"]["waiting_dependency_abandoned"] is True
    assert resumed["replan_control"]["abandoned_waiting_dependency"]["dependency_id"] == "dep-wait-pause"
    assert resumed["replan_control"]["planner_invocation_performed"] is False


def test_replan_from_running_records_durable_episode_without_invoking_planner(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replan-running")
    activate_running(service, mission_id)
    result = execute(service, mission_id, "REPLAN", "replan")
    assert result["mission_state"]["state"] == "REPLANNING"
    replan = result["replan_control"]
    assert replan["replan_id"].startswith(f"replan:{mission_id}:")
    assert replan["from_state"] == "RUNNING"
    assert replan["to_state"] == "REPLANNING"
    assert replan["origin"] == "REPLAN_COMMAND"
    assert replan["planner_invocation_performed"] is False
    assert replan["plan_artifact_created"] is False
    assert result["transition"]["metadata"]["mission_replan_control"] == replan


def test_legacy_direct_replanning_cannot_start_or_wait_without_stage326_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-replan")
    activate_running(service, mission_id)
    direct_transition(service, mission_id, "REPLANNING", "replan")
    with pytest.raises(MissionLifecycleGuardRejected, match="REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS"):
        execute(service, mission_id, "START", "start")
    with pytest.raises(MissionLifecycleGuardRejected, match="REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS"):
        execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "REPLANNING"


def test_start_from_replanning_requires_non_empty_readiness_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replan-no-evidence")
    activate_running(service, mission_id)
    execute(service, mission_id, "REPLAN", "replan")
    with pytest.raises(MissionLifecycleGuardRejected, match="REPLAN_READINESS_EVIDENCE_FOR_RETURN"):
        execute(service, mission_id, "START", "start", evidence_refs=[])
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "REPLANNING"


def test_valid_replanning_readiness_returns_running_and_is_idempotent(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replan-ready")
    activate_running(service, mission_id)
    replan = execute(service, mission_id, "REPLAN", "replan")
    request = lifecycle_request(service, mission_id, "START", "ready", evidence_refs=["plan-readiness:revision:2"])
    result = service.execute_mission_lifecycle_command(mission_id, request)
    assert result["mission_state"]["state"] == "RUNNING"
    readiness = result["replan_resolution"]
    assert readiness["replan_id"] == replan["replan_control"]["replan_id"]
    assert readiness["readiness_status"] == "READY"
    assert readiness["readiness_ready"] is True
    assert readiness["readiness_evidence_refs"] == ["plan-readiness:revision:2"]
    assert readiness["planner_invocation_performed"] is False
    t1 = service.get_mission_state_history(mission_id)["transition_count"]
    e1 = service.get_mission_events(mission_id)["event_count"]
    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["replan_resolution"] == readiness
    assert service.get_mission_state_history(mission_id)["transition_count"] == t1
    assert service.get_mission_events(mission_id)["event_count"] == e1


def test_canonical_replan_can_enter_waiting_dependency_without_planner_authority(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replan-wait")
    activate_running(service, mission_id)
    execute(service, mission_id, "REPLAN", "replan")
    wait = execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait", dependency_id="dep-replan-wait")
    assert wait["mission_state"]["state"] == "WAITING_EVIDENCE"
    assert wait["waiting_dependency"]["dependency_id"] == "dep-replan-wait"
    assert wait["lifecycle_guard"]["allowed"] is True


def test_pause_during_replanning_and_resume_preserves_active_replan_episode(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "pause-replanning")
    activate_running(service, mission_id)
    first_replan = execute(service, mission_id, "REPLAN", "replan")
    paused = execute(service, mission_id, "PAUSE", "pause")
    assert paused["pause_control"]["active_replan"]["replan_id"] == first_replan["replan_control"]["replan_id"]
    resumed = execute(service, mission_id, "RESUME", "resume", target_state="REPLANNING")
    assert resumed["mission_state"]["state"] == "REPLANNING"
    assert resumed["replan_control"]["continued_replan"] is True
    ready = execute(service, mission_id, "START", "ready", evidence_refs=["replan:ready:continued"])
    assert ready["mission_state"]["state"] == "RUNNING"
    assert ready["replan_resolution"]["readiness_ready"] is True


def test_pause_from_created_is_containment_only_and_cannot_resume_to_pip_bound(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "pause-created")
    paused = execute(service, mission_id, "PAUSE", "pause-created")
    assert paused["mission_state"]["state"] == "PAUSED"
    view = service.get_mission_pause_resume_replan_contract(mission_id)["pause_resume_replan"]
    assert view["pause"]["active_pause"]["paused_from_state"] == "CREATED"
    assert view["resume"]["allowed_targets_for_active_pause"] == []
    with pytest.raises(MissionLifecycleGuardRejected, match="RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE"):
        execute(service, mission_id, "RESUME", "resume-created", target_state="PIP_BOUND")


def test_generic_command_gate_cannot_bypass_stage326_replan_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic-replan")
    activate_running(service, mission_id)
    direct_transition(service, mission_id, "REPLANNING", "legacy")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    generic = {
        "command_id": "generic-stage326-start",
        "idempotency_key": "generic-stage326-start-idem",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": vector["version_sha256"],
        "payload": {
            "command": "START",
            "expected_state_version": state["state_version"],
            "actor": "stage3.2.6-pytest",
            "reason_code": "GENERIC_STAGE326_START",
            "reason": "Generic guarded command must still enforce Stage 3.2.6",
            "evidence_refs": ["evidence:generic:stage326"],
            "metadata": {"stage": "3.2.6"},
        },
        "submitted_by": "stage3.2.6-pytest",
        "metadata": {},
    }
    with pytest.raises(MissionLifecycleGuardRejected, match="REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS"):
        service.execute_mission_command(mission_id, generic)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "REPLANNING"


def test_lifecycle_discovery_exposes_stage326_semantics(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "discovery")
    activate_running(service, mission_id)
    execute(service, mission_id, "PAUSE", "pause")
    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert view["pause_resume_replan"]["schema_version"] == PAUSE_RESUME_REPLAN_SCHEMA_VERSION
    assert view["pause_resume_replan"]["resume"]["allowed_targets_for_active_pause"] == ["RUNNING"]
    assert view["guard_eligible_resume_targets"] == ["RUNNING"]
    assert view["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert view["target_action_dispatch_enabled"] is False
