from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionIllegalTransition
from mission_orchestrator.mission_lifecycle import (
    LIFECYCLE_COMMAND_OPERATION,
    TERMINAL_COMMAND_TARGETS,
    TERMINAL_RECOVERY_SEMANTICS,
    TERMINAL_SEMANTIC_PROFILES,
    TERMINAL_SEMANTICS_MODE,
    TERMINAL_SEMANTICS_SCHEMA_VERSION,
    evaluate_lifecycle_guard,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage327-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(
            f"Stage 3.2.7 terminal semantics must remain local-only: unexpected call {name}"
        )


def make_service(tmp_path: Path) -> CanonicalMissionService:
    no_call = NoCallExternal()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str, *, with_pip: bool = True) -> dict:
    payload = {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE327",
        "created_by": "stage3.2.7-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage327-lab"},
        "success_criteria": [{"metric": "typed_terminal_semantics", "expected": True}],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "metadata": {"environment": "LAB", "stage": "3.2.7"},
    }
    if with_pip:
        payload["pip_id"] = f"pip-{key}"
        payload["pip_version"] = "12"
    return payload


def create_mission(service: CanonicalMissionService, key: str, *, with_pip: bool = True) -> str:
    return service.create_mission(mission_payload(key, with_pip=with_pip))["canonical_identity"]["mission_id"]


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
        "command_id": f"lc-327-{idx}",
        "idempotency_key": f"idem-lc-327-{idx}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.7-pytest",
        "reason_code": f"STAGE327_{command}",
        "reason": f"Stage 3.2.7 lifecycle command {command}",
        "evidence_refs": list(evidence_refs if evidence_refs is not None else ["evidence:test:stage327"]),
        "metadata": dict(metadata or {"stage": "3.2.7", "idx": idx}),
    }
    if target_state is not None:
        body["target_state"] = target_state
    if command in {"WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"}:
        body["metadata"]["dependency"] = {
            "dependency_id": dependency_id or f"dep-327-{idx}",
            "kind": "EVIDENCE" if command == "WAIT_FOR_EVIDENCE" else "APPROVAL",
            "description": "Stage 3.2.7 terminal-context dependency",
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


def direct_transition(service: CanonicalMissionService, mission_id: str, to_state: str, idx: str):
    state = service.get_mission_state(mission_id)["mission_state"]
    return service.transition_mission_state(
        mission_id,
        {
            "expected_state_version": state["state_version"],
            "to_state": to_state,
            "actor": "stage3.2.7-legacy-test",
            "reason_code": f"LEGACY_{idx}",
            "reason": "Exercise preserved Stage-3.1 direct state transition API",
            "evidence_refs": [],
            "metadata": {"legacy_test": True, "stage": "3.2.7"},
        },
    )


def test_health_declares_stage327_without_migration_or_authority_expansion(tmp_path):
    health = make_service(tmp_path).health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert health["supported_controls"][16:30] == [
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
    assert health["mission_terminal_semantics_schema_version"] == TERMINAL_SEMANTICS_SCHEMA_VERSION
    assert health["mission_terminal_semantics_mode"] == TERMINAL_SEMANTICS_MODE
    assert health["mission_terminal_commands"] == TERMINAL_COMMAND_TARGETS
    assert health["mission_terminal_recovery_semantics"] == TERMINAL_RECOVERY_SEMANTICS
    assert health["mission_terminal_state_immutability_enforced"] is True
    assert health["mission_terminal_evidence_refs_required"] is False
    assert health["mission_terminal_pip_binding_required"] is False
    assert health["mission_lifecycle_stage3_2_7_terminal_semantics_enabled"] is True
    assert health["mission_lifecycle_stage3_2_8_completion_gate_enabled"] is True
    assert health["mission_terminal_governance_query_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_terminal_contract_exposes_distinct_abort_failure_and_expiration_profiles(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "contract")
    view = service.get_mission_terminal_semantics_contract(mission_id)["terminal_semantics"]
    assert view["schema_version"] == TERMINAL_SEMANTICS_SCHEMA_VERSION
    assert view["current_state"] == "CREATED"
    assert view["is_terminal"] is False
    assert view["terminal_commands"] == TERMINAL_COMMAND_TARGETS
    assert view["semantic_profiles"] == TERMINAL_SEMANTIC_PROFILES
    assert view["semantic_profiles"]["ABORT"]["cause_family"] == "CONTROLLED_STOP"
    assert view["semantic_profiles"]["FAIL"]["cause_family"] == "FAILURE"
    assert view["semantic_profiles"]["EXPIRE"]["cause_family"] == "EXPIRATION"
    assert view["automatic_retry_allowed_after_terminal"] is False
    assert view["resume_allowed_after_terminal"] is False


def test_abort_from_running_records_durable_typed_control_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "abort-running")
    activate_running(service, mission_id)
    result = execute(
        service,
        mission_id,
        "ABORT",
        "abort",
        metadata={"stage": "3.2.7", "terminal": {"abort_source": "OPERATOR"}},
    )
    terminal = result["terminal_control"]
    assert result["mission_state"]["state"] == "ABORTED"
    assert terminal["schema_version"] == TERMINAL_SEMANTICS_SCHEMA_VERSION
    assert terminal["terminal_id"].startswith(f"terminal-abort:{mission_id}:")
    assert terminal["terminal_command"] == "ABORT"
    assert terminal["terminal_state"] == "ABORTED"
    assert terminal["from_state"] == "RUNNING"
    assert terminal["cause_family"] == "CONTROLLED_STOP"
    assert terminal["disposition"] == "INTENTIONAL_ABORT"
    assert terminal["terminal_context"] == {"abort_source": "OPERATOR"}
    assert terminal["verified_completion_claimed"] is False
    assert terminal["governance_authorization_query_performed"] is False
    assert result["transition"]["metadata"]["mission_terminal_control"] == terminal
    projection = service.get_mission_terminal_semantics_contract(mission_id)["terminal_semantics"]
    assert projection["current_terminal_lineage"]["valid"] is True
    assert projection["current_terminal_lineage"]["terminal_id"] == terminal["terminal_id"]


def test_fail_from_waiting_state_preserves_abandoned_dependency_context(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "fail-wait")
    activate_running(service, mission_id)
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "wait", dependency_id="dep-terminal-fail")
    result = execute(
        service,
        mission_id,
        "FAIL",
        "fail",
        metadata={"stage": "3.2.7", "terminal": {"failure_class": "UNRECOVERABLE_DEPENDENCY"}},
    )
    terminal = result["terminal_control"]
    assert result["mission_state"]["state"] == "FAILED"
    assert terminal["cause_family"] == "FAILURE"
    assert terminal["disposition"] == "UNRECOVERABLE_FAILURE"
    assert terminal["active_waiting_dependency"]["dependency_id"] == "dep-terminal-fail"
    assert "WAITING_DEPENDENCY" in terminal["abandoned_control_contexts"]
    assert terminal["terminal_context"]["failure_class"] == "UNRECOVERABLE_DEPENDENCY"


def test_expire_from_paused_state_preserves_exact_pause_context(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "expire-pause")
    activate_running(service, mission_id)
    paused = execute(service, mission_id, "PAUSE", "pause")
    result = execute(
        service,
        mission_id,
        "EXPIRE",
        "expire",
        metadata={"stage": "3.2.7", "terminal": {"deadline_ref": "mission-deadline:2026-09-04"}},
    )
    terminal = result["terminal_control"]
    assert result["mission_state"]["state"] == "EXPIRED"
    assert terminal["cause_family"] == "EXPIRATION"
    assert terminal["disposition"] == "VALIDITY_EXPIRED"
    assert terminal["active_pause"]["pause_id"] == paused["pause_control"]["pause_id"]
    assert terminal["active_pause"]["paused_from_state"] == "RUNNING"
    assert "PAUSE" in terminal["abandoned_control_contexts"]


def test_fail_from_replanning_preserves_active_replan_context(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "fail-replan")
    activate_running(service, mission_id)
    replan = execute(service, mission_id, "REPLAN", "replan")
    result = execute(service, mission_id, "FAIL", "fail")
    terminal = result["terminal_control"]
    assert terminal["active_replan"]["replan_id"] == replan["replan_control"]["replan_id"]
    assert "REPLAN" in terminal["abandoned_control_contexts"]
    assert terminal["automatic_retry_allowed_after_terminal"] is False
    assert terminal["recovery_semantics"] == TERMINAL_RECOVERY_SEMANTICS


def test_exact_terminal_command_replay_is_idempotent_without_duplicate_transition_or_event(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "terminal-replay")
    activate_running(service, mission_id)
    request = lifecycle_request(service, mission_id, "ABORT", "replay")
    first = service.execute_mission_lifecycle_command(mission_id, request)
    t1 = service.get_mission_state_history(mission_id)["transition_count"]
    e1 = service.get_mission_events(mission_id)["event_count"]
    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["terminal_control"] == first["terminal_control"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == t1
    assert service.get_mission_events(mission_id)["event_count"] == e1


@pytest.mark.parametrize("command,target", [("ABORT", "ABORTED"), ("FAIL", "FAILED"), ("EXPIRE", "EXPIRED")])
def test_fail_safe_terminal_exit_requires_neither_pip_nor_evidence(tmp_path, command, target):
    service = make_service(tmp_path)
    mission_id = create_mission(service, f"no-pip-{command.lower()}", with_pip=False)
    result = execute(service, mission_id, command, f"no-pip-{command}", evidence_refs=[])
    assert result["mission_state"]["state"] == target
    assert result["terminal_control"]["terminal_evidence_refs"] == []
    pip_guard = next(
        item for item in result["lifecycle_guard"]["checks"]
        if item["guard_id"] == "PIP_BINDING_COMPLETE_WHEN_REQUIRED"
    )
    assert pip_guard["status"] == "PASS"
    assert pip_guard["required"] == "NOT_REQUIRED"


def test_terminal_state_is_immutable_for_lifecycle_and_direct_transition_paths(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "terminal-immutable")
    execute(service, mission_id, "FAIL", "fail")
    with pytest.raises(MissionIllegalTransition, match="terminal mission state FAILED is immutable"):
        execute(service, mission_id, "ABORT", "after-fail")
    with pytest.raises(MissionIllegalTransition, match="terminal mission state FAILED is immutable"):
        direct_transition(service, mission_id, "ABORTED", "AFTER_FAIL")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "FAILED"


def test_generic_guarded_lifecycle_command_also_generates_stage327_terminal_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic-terminal")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    generic = {
        "command_id": "generic-stage327-expire",
        "idempotency_key": "generic-stage327-expire-idem",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": vector["version_sha256"],
        "payload": {
            "command": "EXPIRE",
            "expected_state_version": state["state_version"],
            "actor": "stage3.2.7-pytest",
            "reason_code": "GENERIC_STAGE327_EXPIRE",
            "reason": "Generic guarded lifecycle command must retain Stage 3.2.7 semantics",
            "evidence_refs": [],
            "metadata": {"stage": "3.2.7"},
        },
        "submitted_by": "stage3.2.7-pytest",
        "metadata": {},
    }
    result = service.execute_mission_command(mission_id, generic)["result"]
    assert result["mission_state"]["state"] == "EXPIRED"
    assert result["terminal_control"]["terminal_command"] == "EXPIRE"
    assert result["transition"]["metadata"]["mission_terminal_control"] == result["terminal_control"]


def test_legacy_direct_terminal_transition_is_visible_but_does_not_fabricate_typed_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "legacy-terminal", with_pip=False)
    direct_transition(service, mission_id, "ABORTED", "ABORT")
    projection = service.get_mission_terminal_semantics_contract(mission_id)["terminal_semantics"]
    assert projection["is_terminal"] is True
    assert projection["terminal_state_immutable"] is True
    lineage = projection["current_terminal_lineage"]
    assert lineage["valid"] is False
    assert lineage["status"] == "LEGACY_DIRECT_TERMINAL_TRANSITION_NO_STAGE_3_2_7_EVIDENCE"
    assert lineage["terminal_state"] == "ABORTED"


def test_lifecycle_discovery_embeds_stage327_terminal_projection(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "discovery")
    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert view["terminal_semantics"]["schema_version"] == TERMINAL_SEMANTICS_SCHEMA_VERSION
    assert view["lifecycle_command_contract"]["stage3_2_7_terminal_semantics_schema_version"] == TERMINAL_SEMANTICS_SCHEMA_VERSION
    assert view["lifecycle_command_contract"]["stage3_2_7_terminal_commands"] == TERMINAL_COMMAND_TARGETS
    assert "TYPED_TERMINATION_CONTROL" in view["eligibility_semantics"]
    assert view["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert view["target_action_dispatch_enabled"] is False


def test_terminal_exit_from_cleaning_up_does_not_claim_verified_completion(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "cleanup-failure")
    activate_running(service, mission_id)
    cleanup = execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    assert cleanup["mission_state"]["state"] == "CLEANING_UP"
    failed = execute(service, mission_id, "FAIL", "cleanup-fail")
    assert failed["mission_state"]["state"] == "FAILED"
    assert failed["terminal_control"]["from_state"] == "CLEANING_UP"
    assert failed["terminal_control"]["verified_completion_claimed"] is False
    assert failed["terminal_control"]["cleanup_completion_gate_applied"] is False


def test_completed_terminal_uses_stage328_verified_completion_semantics_after_upgrade(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "completed-deferred")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup")
    refs = [
        "evidence:objective:stage327-upgrade",
        "evidence:criterion:0:stage327-upgrade",
        "evidence:cleanup:stage327-upgrade",
    ]
    completion_metadata = {
        "stage": "3.2.8",
        "completion": {
            "verification_status": "VERIFIED",
            "objective_status": "SATISFIED",
            "objective_evidence_refs": [refs[0]],
            "success_criteria_status": "SATISFIED",
            "criteria_results": [
                {"criterion_index": 0, "status": "SATISFIED", "evidence_refs": [refs[1]]}
            ],
            "cleanup_status": "VERIFIED",
            "cleanup_checks": [
                {"check_id": "STAGE327_COMPAT_CLEANUP", "status": "PASS", "evidence_refs": [refs[2]]}
            ],
            "outstanding_critical_dependencies": 0,
        },
    }
    completed = execute(
        service, mission_id, "COMPLETE", "complete", evidence_refs=refs, metadata=completion_metadata
    )
    assert completed["completion_verification"]["verified_completion_claimed"] is True
    projection = service.get_mission_terminal_semantics_contract(mission_id)["terminal_semantics"]
    assert projection["current_state"] == "COMPLETED"
    assert projection["is_terminal"] is True
    assert projection["current_terminal_lineage"]["status"] == "VALID_VERIFIED_COMPLETION"
    assert projection["current_terminal_lineage"]["terminal_command"] == "COMPLETE"
    assert projection["verified_completion_claimed"] is True


def test_terminal_intent_target_consistency_guard_fails_closed_on_mismatched_low_level_evaluation(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "guard-mismatch", with_pip=False)
    stored = service.repository.get_by_mission_id(mission_id)
    state = service.repository.get_state(mission_id)
    evaluation = evaluate_lifecycle_guard(
        mission_id=mission_id,
        envelope=stored.envelope,
        current_state=state,
        command="ABORT",
        target_state="FAILED",
        state_transitions=[],
    )
    assert evaluation["allowed"] is False
    assert "TERMINAL_INTENT_TARGET_CONSISTENCY" in evaluation["failed_guard_ids"]
