from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import (
    MissionCommandConflict,
    MissionConcurrencyConflict,
    MissionIllegalTransition,
    MissionValidationError,
)
from mission_orchestrator.mission_lifecycle import (
    LIFECYCLE_COMMAND_MODE,
    LIFECYCLE_COMMAND_OPERATION,
    LIFECYCLE_COMMAND_SCHEMA_VERSION,
    LIFECYCLE_COMMANDS,
    RESUME_TARGETS,
    normalize_lifecycle_command_request,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage321-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.2.1 lifecycle command must not call external dependency: {name}")


def make_service(tmp_path: Path) -> CanonicalMissionService:
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    no_call = NoCallExternal()
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str = "stage321-mission"):
    return {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE321",
        "created_by": "stage3.2.1-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage321-lab"},
        "success_criteria": [{"metric": "lifecycle_contract", "expected": True}],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": "pip-stage321",
        "pip_version": "1",
        "metadata": {"environment": "LAB", "stage": "3.2.1"},
    }


def create_mission(service: CanonicalMissionService, key: str = "stage321-mission") -> str:
    return service.create_mission(mission_payload(key))["canonical_identity"]["mission_id"]


def lifecycle_request(
    service: CanonicalMissionService,
    mission_id: str,
    command: str,
    *,
    command_id: str,
    expected_state_version: int | None = None,
    expected_version_sha256: str | None = None,
    target_state: str | None = None,
    idempotency_key: str | None = None,
):
    state = service.get_mission_state(mission_id)["mission_state"]
    version = service.get_mission_version_vector(mission_id)
    payload = {
        "command_id": command_id,
        "idempotency_key": idempotency_key or f"idem-{command_id}",
        "command": command,
        "expected_version_sha256": expected_version_sha256 or version["version_sha256"],
        "expected_state_version": expected_state_version or state["state_version"],
        "actor": "stage3.2.1-pytest",
        "reason_code": f"LC_{command}",
        "reason": f"Stage 3.2.1 lifecycle command {command}",
        "evidence_refs": ["evidence:test:stage321"],
        "metadata": {"stage": "3.2.1"},
    }
    if command == "COMPLETE":
        refs = [
            "evidence:objective:stage321",
            "evidence:criterion:0:stage321",
            "evidence:cleanup:stage321",
        ]
        payload["evidence_refs"] = refs
        payload["metadata"]["completion"] = {
            "verification_status": "VERIFIED",
            "objective_status": "SATISFIED",
            "objective_evidence_refs": [refs[0]],
            "success_criteria_status": "SATISFIED",
            "criteria_results": [
                {"criterion_index": 0, "status": "SATISFIED", "evidence_refs": [refs[1]]}
            ],
            "cleanup_status": "VERIFIED",
            "cleanup_checks": [
                {"check_id": "LIFECYCLE_CLEANUP_COMPLETE", "status": "PASS", "evidence_refs": [refs[2]]}
            ],
            "outstanding_critical_dependencies": 0,
        }
    if command in {"WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"}:
        payload["metadata"]["dependency"] = {
            "dependency_id": f"dep-{command_id}",
            "kind": "EVIDENCE" if command == "WAIT_FOR_EVIDENCE" else "APPROVAL",
            "description": "Compatibility declaration for Stage-3.2.1 vocabulary regression",
        }
    if target_state is not None:
        payload["target_state"] = target_state
    return payload


def execute(service, mission_id, command, idx, *, target_state=None):
    request = lifecycle_request(
        service,
        mission_id,
        command,
        command_id=f"lc-{idx}",
        target_state=target_state,
    )
    return service.execute_mission_lifecycle_command(mission_id, request)


def test_health_declares_stage321_contract_without_authority_or_migration_expansion(tmp_path):
    service = make_service(tmp_path)
    health = service.health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][10:30] == [
        "stage3.2.1-mission-lifecycle-command-contract",
        "stage3.2.2-lifecycle-transition-guard-matrix",
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
    assert health["mission_repository_migration_level"] == 53
    assert health["mission_lifecycle_command_schema_version"] == LIFECYCLE_COMMAND_SCHEMA_VERSION
    assert health["mission_lifecycle_command_mode"] == LIFECYCLE_COMMAND_MODE
    assert health["mission_lifecycle_command_operation"] == LIFECYCLE_COMMAND_OPERATION
    assert health["supported_mission_lifecycle_commands"] == list(LIFECYCLE_COMMANDS)
    assert health["mission_lifecycle_resume_targets"] == list(RESUME_TARGETS)
    assert health["mission_lifecycle_command_uses_existing_command_journal"] is True
    assert health["mission_lifecycle_command_stage3_2_2_guard_matrix_enabled"] is True
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_lifecycle_contract_discovery_is_topology_only_not_authorization(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "contract-discovery")
    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert view["lifecycle_command_contract"]["schema_version"] == LIFECYCLE_COMMAND_SCHEMA_VERSION
    assert view["lifecycle_command_contract"]["stage3_2_2_guard_matrix_not_implemented"] is False
    assert set(view["topology_eligible_commands"]) == {"BIND_PIP", "PAUSE", "ABORT", "FAIL", "EXPIRE"}
    assert "NOT_GOVERNANCE_AUTHORIZATION" in view["eligibility_semantics"]
    assert view["target_action_dispatch_enabled"] is False


def test_bind_pip_lifecycle_command_uses_existing_journal_transition_and_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "bind-pip")
    result = execute(service, mission_id, "BIND_PIP", 1)

    assert result["status"] == "completed"
    assert result["idempotent_replay"] is False
    assert result["lifecycle_command"] == "BIND_PIP"
    assert result["resolved_target_state"] == "PIP_BOUND"
    assert result["mission_state"]["state"] == "PIP_BOUND"
    assert result["transition"]["metadata"]["lifecycle_command"] == "BIND_PIP"
    assert result["guarded_command"]["operation"] == LIFECYCLE_COMMAND_OPERATION
    assert result["guarded_command"]["metadata"]["lifecycle_command"] == "BIND_PIP"

    history = service.get_mission_command_history(mission_id)
    assert history["command_count"] == 1
    assert history["commands"][0]["operation"] == LIFECYCLE_COMMAND_OPERATION
    events = service.get_mission_events(mission_id)
    assert [x["event_type"] for x in events["events"]] == [
        "MISSION_REGISTERED",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_COMMAND_COMPLETED",
    ]


def test_exact_lifecycle_command_replay_is_idempotent_and_does_not_duplicate_state_or_events(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replay")
    request = lifecycle_request(service, mission_id, "BIND_PIP", command_id="lc-replay")
    first = service.execute_mission_lifecycle_command(mission_id, request)
    state_after = service.get_mission_state(mission_id)["mission_state"]
    events_after = service.get_mission_events(mission_id)["event_count"]

    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert service.get_mission_state(mission_id)["mission_state"] == state_after
    assert service.get_mission_events(mission_id)["event_count"] == events_after
    assert service.get_mission_command_history(mission_id)["command_count"] == 1


def test_lifecycle_idempotency_key_reuse_with_changed_intent_is_rejected(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "idem-conflict")
    request = lifecycle_request(service, mission_id, "BIND_PIP", command_id="lc-conflict", idempotency_key="idem-shared")
    service.execute_mission_lifecycle_command(mission_id, request)

    replay_changed = dict(request)
    replay_changed["command"] = "PAUSE"
    replay_changed["reason_code"] = "LC_PAUSE"
    with pytest.raises(MissionCommandConflict):
        service.execute_mission_lifecycle_command(mission_id, replay_changed)


def test_stale_version_vector_rejected_before_lifecycle_mutation(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "stale-vector")
    stale = service.get_mission_version_vector(mission_id)["version_sha256"]
    execute(service, mission_id, "BIND_PIP", 1)
    before = service.get_mission_state(mission_id)["mission_state"]

    request = lifecycle_request(
        service,
        mission_id,
        "START_PLANNING",
        command_id="lc-stale",
        expected_version_sha256=stale,
    )
    with pytest.raises(MissionConcurrencyConflict):
        service.execute_mission_lifecycle_command(mission_id, request)
    assert service.get_mission_state(mission_id)["mission_state"] == before


def test_state_version_must_match_same_guarded_version_vector(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "state-version")
    request = lifecycle_request(
        service,
        mission_id,
        "BIND_PIP",
        command_id="lc-state-stale",
        expected_state_version=99,
    )
    with pytest.raises(MissionConcurrencyConflict):
        service.execute_mission_lifecycle_command(mission_id, request)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"


def test_happy_path_command_vocabulary_maps_to_canonical_states(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "happy-path")
    assert execute(service, mission_id, "BIND_PIP", 1)["mission_state"]["state"] == "PIP_BOUND"
    assert execute(service, mission_id, "START_PLANNING", 2)["mission_state"]["state"] == "PLANNING"
    assert execute(service, mission_id, "START", 3)["mission_state"]["state"] == "RUNNING"
    assert execute(service, mission_id, "WAIT_FOR_EVIDENCE", 4)["mission_state"]["state"] == "WAITING_EVIDENCE"
    assert execute(service, mission_id, "REPLAN", 5)["mission_state"]["state"] == "REPLANNING"
    assert execute(service, mission_id, "WAIT_FOR_APPROVAL", 6)["mission_state"]["state"] == "WAITING_APPROVAL"
    assert execute(service, mission_id, "PAUSE", 7)["mission_state"]["state"] == "PAUSED"
    assert execute(service, mission_id, "RESUME", 8, target_state="REPLANNING")["mission_state"]["state"] == "REPLANNING"
    assert execute(service, mission_id, "START", 9)["mission_state"]["state"] == "RUNNING"
    assert execute(service, mission_id, "BEGIN_CLEANUP", 10)["mission_state"]["state"] == "CLEANING_UP"
    assert execute(service, mission_id, "COMPLETE", 11)["mission_state"]["state"] == "COMPLETED"


def test_resume_requires_explicit_canonical_resume_target():
    base = {
        "command_id": "lc-resume",
        "idempotency_key": "idem-lc-resume",
        "command": "RESUME",
        "expected_version_sha256": "0" * 64,
        "expected_state_version": 2,
        "actor": "pytest",
        "reason_code": "RESUME_TEST",
    }
    with pytest.raises(MissionValidationError, match="target_state is required for RESUME"):
        normalize_lifecycle_command_request(base)
    with pytest.raises(MissionValidationError, match="RESUME target_state"):
        normalize_lifecycle_command_request({**base, "target_state": "WAITING_APPROVAL"})
    assert normalize_lifecycle_command_request({**base, "target_state": "RUNNING"})["target_state"] == "RUNNING"


def test_fixed_lifecycle_command_rejects_caller_supplied_target_state():
    with pytest.raises(MissionValidationError, match="must not be supplied"):
        normalize_lifecycle_command_request(
            {
                "command_id": "lc-fixed",
                "idempotency_key": "idem-lc-fixed",
                "command": "START",
                "target_state": "RUNNING",
                "expected_version_sha256": "0" * 64,
                "expected_state_version": 1,
                "actor": "pytest",
                "reason_code": "START_TEST",
            }
        )


def test_illegal_lifecycle_command_does_not_bypass_existing_canonical_topology(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "illegal-topology")
    request = lifecycle_request(service, mission_id, "START", command_id="lc-start-too-early")
    with pytest.raises(MissionIllegalTransition):
        service.execute_mission_lifecycle_command(mission_id, request)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"
    command = service.get_mission_command_history(mission_id)["commands"][0]
    assert command["command_status"] == "FAILED"


def test_terminal_lifecycle_command_preserves_terminal_immutability(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "terminal")
    assert execute(service, mission_id, "ABORT", 1)["mission_state"]["state"] == "ABORTED"
    request = lifecycle_request(service, mission_id, "START", command_id="lc-after-abort")
    with pytest.raises(MissionIllegalTransition):
        service.execute_mission_lifecycle_command(mission_id, request)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "ABORTED"


def test_generic_command_api_cannot_bypass_lifecycle_payload_validation(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic-bypass")
    version = service.get_mission_version_vector(mission_id)["version_sha256"]
    generic = {
        "command_id": "generic-lc-invalid",
        "idempotency_key": "idem-generic-lc-invalid",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": version,
        "payload": {
            "command": "DO_ANYTHING",
            "expected_state_version": 1,
            "actor": "pytest",
            "reason_code": "INVALID",
        },
        "submitted_by": "pytest",
        "metadata": {},
    }
    with pytest.raises(MissionValidationError, match="unsupported lifecycle command"):
        service.execute_mission_command(mission_id, generic)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"


def test_fail_and_expire_are_explicit_terminal_lifecycle_intents(tmp_path):
    service = make_service(tmp_path)
    failed_id = create_mission(service, "terminal-fail")
    expired_id = create_mission(service, "terminal-expire")
    assert execute(service, failed_id, "FAIL", 1)["mission_state"]["state"] == "FAILED"
    assert execute(service, expired_id, "EXPIRE", 2)["mission_state"]["state"] == "EXPIRED"
