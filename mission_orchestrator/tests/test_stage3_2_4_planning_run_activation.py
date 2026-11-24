from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionLifecycleGuardRejected
from mission_orchestrator.mission_lifecycle import (
    LIFECYCLE_COMMAND_OPERATION,
    PLANNING_ACTIVATION_COMMAND,
    PLANNING_RUN_ACTIVATION_MODE,
    PLANNING_RUN_ACTIVATION_SCHEMA_VERSION,
    RUN_ACTIVATION_COMMAND,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage324-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.2.4 planning/run activation must remain local-only: unexpected call {name}")


def make_service(tmp_path: Path) -> CanonicalMissionService:
    no_call = NoCallExternal()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str) -> dict:
    return {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE324",
        "created_by": "stage3.2.4-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage324-lab"},
        "success_criteria": [{"metric": "planning_run_activation", "expected": True}],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-{key}",
        "pip_version": "9",
        "metadata": {"environment": "LAB", "stage": "3.2.4"},
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
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "command_id": f"lc-324-{idx}",
        "idempotency_key": f"idem-lc-324-{idx}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.4-pytest",
        "reason_code": f"STAGE324_{command}",
        "reason": f"Stage 3.2.4 lifecycle command {command}",
        "evidence_refs": ["evidence:test:stage324"],
        "metadata": {"stage": "3.2.4", "idx": idx},
    }
    if command in {"WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"}:
        body["metadata"]["dependency"] = {
            "dependency_id": f"dep-324-{idx}",
            "kind": "EVIDENCE" if command == "WAIT_FOR_EVIDENCE" else "APPROVAL",
            "description": "Stage-3.2.4 compatibility waiting dependency",
        }
    if command == "START" and state["state"] in {"WAITING_EVIDENCE", "WAITING_APPROVAL"}:
        active = service.get_mission_waiting_dependency_contract(mission_id)["waiting_dependency"]["active_dependency"]
        body["metadata"]["dependency_resolution"] = {
            "dependency_id": active["dependency_id"],
            "status": "SATISFIED",
            "resolved_by": "stage3.2.4-pytest",
        }
    if target_state is not None:
        body["target_state"] = target_state
    return body


def execute(service, mission_id: str, command: str, idx: str, *, target_state: str | None = None):
    return service.execute_mission_lifecycle_command(
        mission_id,
        lifecycle_request(service, mission_id, command, idx, target_state=target_state),
    )


def direct_transition(service, mission_id: str, to_state: str, idx: str):
    state = service.get_mission_state(mission_id)["mission_state"]
    return service.transition_mission_state(
        mission_id,
        {
            "expected_state_version": state["state_version"],
            "to_state": to_state,
            "actor": "stage3.2.4-legacy-test",
            "reason_code": f"LEGACY_{idx}",
            "reason": "Exercise preserved Stage-3.1 direct state transition API",
            "evidence_refs": [],
            "metadata": {"legacy_test": True, "stage": "3.2.4"},
        },
    )


def activate_pip(service, mission_id: str, idx: str = "bind"):
    return execute(service, mission_id, "BIND_PIP", idx)


def activate_planning(service, mission_id: str, idx: str = "plan"):
    return execute(service, mission_id, "START_PLANNING", idx)


def activate_running(service, mission_id: str, idx: str = "run"):
    return execute(service, mission_id, "START", idx)


def test_health_declares_stage324_without_migration_planner_or_authority_expansion(tmp_path):
    health = make_service(tmp_path).health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][13:30] == [
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
    assert health["mission_repository_migration_level"] == 53
    assert health["mission_planning_run_activation_schema_version"] == PLANNING_RUN_ACTIVATION_SCHEMA_VERSION
    assert health["mission_planning_run_activation_mode"] == PLANNING_RUN_ACTIVATION_MODE
    assert health["mission_planning_activation_command"] == PLANNING_ACTIVATION_COMMAND
    assert health["mission_planning_activation_transition"] == "PIP_BOUND->PLANNING"
    assert health["mission_run_activation_command"] == RUN_ACTIVATION_COMMAND
    assert health["mission_run_activation_transition"] == "PLANNING->RUNNING"
    assert health["mission_planning_run_requires_pip_activation_lineage"] is True
    assert health["mission_run_requires_planning_activation_lineage"] is True
    assert health["mission_planning_run_planner_invocation_performed"] is False
    assert health["mission_planning_run_plan_artifact_created"] is False
    assert health["mission_planning_run_governance_query_performed"] is False
    assert health["mission_planning_run_execution_authorized"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_planning_run_contract_at_created_is_local_and_not_ready(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "created-contract")
    view = service.get_mission_planning_run_activation_contract(mission_id)
    activation = view["planning_run_activation"]
    assert activation["schema_version"] == PLANNING_RUN_ACTIVATION_SCHEMA_VERSION
    assert activation["current_state"] == "CREATED"
    assert activation["planning_activation"]["activation_ready"] is False
    assert activation["run_activation"]["activation_ready"] is False
    assert activation["activation_chain"]["pip_activation"]["status"] == "MISSING"
    assert activation["planner_invocation_performed"] is False
    assert activation["plan_artifact_created"] is False
    assert activation["governance_authorization_query_performed"] is False
    assert activation["execution_authorized"] is False


def test_valid_stage323_bind_makes_planning_activation_ready(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "planning-ready")
    bind = activate_pip(service, mission_id)
    assert bind["mission_state"]["state"] == "PIP_BOUND"

    activation = service.get_mission_planning_run_activation_contract(mission_id)["planning_run_activation"]
    assert activation["planning_activation"]["activation_ready"] is True
    assert activation["run_activation"]["activation_ready"] is False
    assert activation["activation_chain"]["pip_activation"]["valid"] is True
    assert activation["activation_chain"]["pip_activation"]["transition_id"] == bind["transition"]["transition_id"]


def test_legacy_direct_pip_bound_without_stage323_activation_lineage_cannot_start_planning(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-pip-bound")
    direct_transition(service, mission_id, "PIP_BOUND", "pip-bound")

    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert "START_PLANNING" in view["topology_eligible_commands"]
    assert "START_PLANNING" not in view["guard_eligible_commands"]
    evaluation = next(x for x in view["guard_evaluations"] if x["command"] == "START_PLANNING")
    assert "PIP_ACTIVATION_EVIDENCE_FOR_PLANNING" in evaluation["failed_guard_ids"]

    with pytest.raises(MissionLifecycleGuardRejected, match="PIP_ACTIVATION_EVIDENCE_FOR_PLANNING"):
        activate_planning(service, mission_id, "legacy-plan")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PIP_BOUND"


def test_start_planning_records_stage324_evidence_and_preserves_immutable_envelope(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "planning-evidence")
    activate_pip(service, mission_id)
    before = deepcopy(service.get_envelope(mission_id)["envelope"])

    result = activate_planning(service, mission_id)
    after = service.get_envelope(mission_id)["envelope"]
    evidence = result["planning_run_activation"]
    assert result["mission_state"]["state"] == "PLANNING"
    assert evidence["schema_version"] == PLANNING_RUN_ACTIVATION_SCHEMA_VERSION
    assert evidence["phase"] == "PLANNING"
    assert evidence["activation_command"] == "START_PLANNING"
    assert evidence["activation_ready"] is True
    assert evidence["pip_activation_proof"]["valid"] is True
    assert evidence["planner_invocation_performed"] is False
    assert evidence["plan_artifact_created"] is False
    assert evidence["execution_authorized"] is False
    assert result["transition"]["metadata"]["mission_planning_run_activation"] == evidence
    assert after == before


def test_start_planning_exact_replay_preserves_evidence_without_duplicate_transition_or_event(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "planning-replay")
    activate_pip(service, mission_id)
    request = lifecycle_request(service, mission_id, "START_PLANNING", "planning-replay")
    first = service.execute_mission_lifecycle_command(mission_id, request)
    transitions_before = service.get_mission_state_history(mission_id)["transition_count"]
    events_before = service.get_mission_events(mission_id)["event_count"]
    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert replay["planning_run_activation"] == first["planning_run_activation"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == transitions_before
    assert service.get_mission_events(mission_id)["event_count"] == events_before


def test_legacy_direct_planning_without_stage324_planning_lineage_cannot_initial_start(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-planning")
    activate_pip(service, mission_id)
    direct_transition(service, mission_id, "PLANNING", "planning")

    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert "START" in view["topology_eligible_commands"]
    assert "START" not in view["guard_eligible_commands"]
    evaluation = next(x for x in view["guard_evaluations"] if x["command"] == "START")
    assert "PLANNING_ACTIVATION_EVIDENCE_FOR_INITIAL_RUN" in evaluation["failed_guard_ids"]

    with pytest.raises(MissionLifecycleGuardRejected, match="PLANNING_ACTIVATION_EVIDENCE_FOR_INITIAL_RUN"):
        activate_running(service, mission_id, "legacy-run")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PLANNING"


def test_valid_initial_start_records_run_activation_evidence_without_execution_authority(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "run-evidence")
    bind = activate_pip(service, mission_id)
    planning = activate_planning(service, mission_id)
    result = activate_running(service, mission_id)

    evidence = result["planning_run_activation"]
    assert result["mission_state"]["state"] == "RUNNING"
    assert evidence["phase"] == "RUNNING"
    assert evidence["activation_command"] == "START"
    assert evidence["activation_ready"] is True
    assert evidence["pip_activation_proof"]["transition_id"] == bind["transition"]["transition_id"]
    assert evidence["planning_activation_proof"]["transition_id"] == planning["transition"]["transition_id"]
    assert evidence["planner_invocation_performed"] is False
    assert evidence["plan_artifact_created"] is False
    assert evidence["governance_authorization_query_performed"] is False
    assert evidence["execution_authorized"] is False
    assert evidence["target_action_dispatch_enabled"] is False
    assert evidence["target_actuation"] is False
    assert result["transition"]["metadata"]["mission_planning_run_activation"] == evidence


def test_initial_start_exact_replay_preserves_run_evidence_without_duplicate_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "run-replay")
    activate_pip(service, mission_id)
    activate_planning(service, mission_id)
    request = lifecycle_request(service, mission_id, "START", "run-replay")
    first = service.execute_mission_lifecycle_command(mission_id, request)
    transitions_before = service.get_mission_state_history(mission_id)["transition_count"]
    events_before = service.get_mission_events(mission_id)["event_count"]
    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["planning_run_activation"] == first["planning_run_activation"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == transitions_before
    assert service.get_mission_events(mission_id)["event_count"] == events_before


def test_contract_after_running_reports_complete_activation_chain(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "chain-complete")
    activate_pip(service, mission_id)
    activate_planning(service, mission_id)
    activate_running(service, mission_id)

    activation = service.get_mission_planning_run_activation_contract(mission_id)["planning_run_activation"]
    assert activation["current_state"] == "RUNNING"
    assert activation["activation_chain"]["pip_activation"]["valid"] is True
    assert activation["activation_chain"]["planning_activation"]["valid"] is True
    assert activation["activation_chain"]["run_activation"]["valid"] is True
    assert activation["activation_chain"]["chain_complete"] is True
    assert activation["planning_activation"]["activation_ready"] is False
    assert activation["run_activation"]["activation_ready"] is False


def test_generic_guarded_command_api_cannot_bypass_planning_activation_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic-bypass")
    direct_transition(service, mission_id, "PIP_BOUND", "generic-pip")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    generic = {
        "command_id": "cmd-324-generic-plan",
        "idempotency_key": "idem-cmd-324-generic-plan",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": vector["version_sha256"],
        "payload": {
            "command": "START_PLANNING",
            "expected_state_version": state["state_version"],
            "actor": "stage3.2.4-pytest",
            "reason_code": "GENERIC_START_PLANNING",
            "evidence_refs": [],
            "metadata": {},
        },
        "submitted_by": "stage3.2.4-pytest",
        "metadata": {},
    }
    with pytest.raises(MissionLifecycleGuardRejected, match="PIP_ACTIVATION_EVIDENCE_FOR_PLANNING"):
        service.execute_mission_command(mission_id, generic)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PIP_BOUND"


def test_lifecycle_discovery_embeds_stage324_projection_and_lineage_eligibility(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "discovery")
    activate_pip(service, mission_id)
    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert view["planning_run_activation"]["planning_activation"]["activation_ready"] is True
    assert view["lifecycle_command_contract"]["stage3_2_4_planning_run_activation_schema_version"] == PLANNING_RUN_ACTIVATION_SCHEMA_VERSION
    assert view["lifecycle_command_contract"]["stage3_2_4_planning_activation_command"] == "START_PLANNING"
    assert "START_PLANNING" in view["guard_eligible_commands"]
    assert "NOT_GOVERNANCE_AUTHORIZATION" in view["eligibility_semantics"]
    assert view["authority_query_performed"] is False
    assert view["target_action_dispatch_enabled"] is False


def test_start_from_waiting_state_is_not_mislabeled_as_initial_stage324_run_activation(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "waiting-start")
    activate_pip(service, mission_id)
    activate_planning(service, mission_id)
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait")
    result = execute(service, mission_id, "START", "return-from-wait")
    assert result["mission_state"]["state"] == "RUNNING"
    assert result["planning_run_activation"] is None
    assert result["lifecycle_guard"]["allowed"] is True
    assert result["waiting_dependency_resolution"]["resolution_ready"] is True
    assert result["waiting_dependency_resolution"]["kind"] == "EVIDENCE"
    assert result["waiting_dependency_resolution"]["governance_authorization_query_performed"] is False


def test_stage324_uses_existing_transition_event_and_command_lineage_only(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "lineage")
    activate_pip(service, mission_id)
    activate_planning(service, mission_id)
    activate_running(service, mission_id)

    history = service.get_mission_state_history(mission_id)
    assert history["transition_count"] == 3
    assert [(x["from_state"], x["to_state"]) for x in history["transitions"]] == [
        ("CREATED", "PIP_BOUND"),
        ("PIP_BOUND", "PLANNING"),
        ("PLANNING", "RUNNING"),
    ]
    events = service.get_mission_events(mission_id)
    types = [x["event_type"] for x in events["events"]]
    assert types.count("MISSION_STATE_TRANSITIONED") == 3
    assert types.count("MISSION_COMMAND_COMPLETED") == 3
    commands = service.get_mission_command_history(mission_id)["commands"]
    assert len(commands) == 3
    assert all(x["operation"] == LIFECYCLE_COMMAND_OPERATION for x in commands)
    assert service.health()["mission_repository_migration_level"] == 53
