from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from mission_orchestrator.errors import (
    MissionCommandConflict,
    MissionConcurrencyConflict,
    MissionLifecycleGuardRejected,
    MissionValidationError,
)
from mission_orchestrator.mission_lifecycle_automation import (
    EVENT_TO_COMMAND,
    LIFECYCLE_AUTOMATION_EVENT_TYPES,
    LIFECYCLE_AUTOMATION_MODE,
    LIFECYCLE_AUTOMATION_SCHEMA_VERSION,
    MISSION_LIFECYCLE_EVENT_APPLIED,
    MISSION_LIFECYCLE_EVENT_RECEIVED,
    MISSION_LIFECYCLE_EVENT_REJECTED,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoExternalClient:
    base_url = "disabled://stage3.2.9"

    def __getattr__(self, name):
        def _unexpected(*args, **kwargs):
            raise AssertionError(f"Stage 3.2.9 lifecycle automation must remain local-only: unexpected call {name}")

        return _unexpected


def make_service(tmp_path) -> CanonicalMissionService:
    db = tmp_path if str(tmp_path).endswith(".db") else tmp_path / "missions.db"
    return CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=NoExternalClient(),
        cti_client=NoExternalClient(),
    )


def mission_payload(key: str, *, criteria_count: int = 2) -> dict:
    return {
        "idempotency_key": f"stage329-{key}",
        "source_system": "PYTEST_STAGE329",
        "created_by": "stage3.2.9-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage329-lab"},
        "success_criteria": [
            {"metric": f"criterion_{idx}", "expected": True} for idx in range(criteria_count)
        ],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-{key}",
        "pip_version": "13",
        "metadata": {"environment": "LAB", "stage": "3.2.9"},
    }


def create_mission(service: CanonicalMissionService, key: str, *, criteria_count: int = 2) -> str:
    return service.create_mission(mission_payload(key, criteria_count=criteria_count))["canonical_identity"]["mission_id"]


def lifecycle_request(service: CanonicalMissionService, mission_id: str, command: str, idx: str, *, metadata=None, evidence_refs=None, target_state=None):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "command_id": f"lc-329-{idx}",
        "idempotency_key": f"idem-lc-329-{idx}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.9-pytest",
        "reason_code": f"STAGE329_{command}",
        "reason": f"Stage 3.2.9 helper command {command}",
        "evidence_refs": list(evidence_refs if evidence_refs is not None else [f"evidence:stage329:{idx}"]),
        "metadata": dict(metadata or {"stage": "3.2.9", "idx": idx}),
    }
    if target_state is not None:
        body["target_state"] = target_state
    return body


def execute(service: CanonicalMissionService, mission_id: str, command: str, idx: str, **kwargs):
    return service.execute_mission_lifecycle_command(mission_id, lifecycle_request(service, mission_id, command, idx, **kwargs))


def activate_running(service: CanonicalMissionService, mission_id: str):
    execute(service, mission_id, "BIND_PIP", "bind")
    execute(service, mission_id, "START_PLANNING", "plan")
    execute(service, mission_id, "START", "run")


def event_request(service: CanonicalMissionService, mission_id: str, event_type: str, token: str, *, metadata=None, evidence_refs=None, target_state=None, event_id=None, reason=None) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "event_id": event_id or f"source-event-{token}",
        "event_type": event_type,
        "source_component": "STAGE329-SOURCE",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "observed_state": state["state"],
        "observed_state_version": state["state_version"],
        "observed_version_sha256": vector["version_sha256"],
        "actor": "stage3.2.9-event-adapter",
        "reason": reason or f"Stage 3.2.9 source event {event_type}",
        "evidence_refs": list(evidence_refs or []),
        "metadata": dict(metadata or {}),
    }
    if target_state is not None:
        body["target_state"] = target_state
    return body


def valid_completion_bundle(criteria_count: int = 2, prefix: str = "ok") -> tuple[list[str], dict]:
    objective_ref = f"evidence:objective:{prefix}"
    criterion_refs = [f"evidence:criterion:{idx}:{prefix}" for idx in range(criteria_count)]
    cleanup_ref = f"evidence:cleanup:{prefix}"
    refs = [objective_ref, *criterion_refs, cleanup_ref]
    return refs, {
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
        }
    }


def test_health_declares_stage329_without_migration_or_authority_expansion(tmp_path):
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
    assert health["mission_lifecycle_automation_schema_version"] == LIFECYCLE_AUTOMATION_SCHEMA_VERSION
    assert health["mission_lifecycle_automation_mode"] == LIFECYCLE_AUTOMATION_MODE
    assert health["mission_lifecycle_automation_event_types"] == list(LIFECYCLE_AUTOMATION_EVENT_TYPES)
    assert health["mission_lifecycle_automation_event_to_command"] == EVENT_TO_COMMAND
    assert health["mission_lifecycle_automation_uses_existing_command_journal"] is True
    assert health["mission_lifecycle_automation_uses_existing_event_ledger"] is True
    assert health["mission_lifecycle_automation_direct_state_mutation_allowed"] is False
    assert health["mission_lifecycle_automation_external_event_delivery_enabled"] is False
    assert health["mission_lifecycle_automation_governance_query_performed"] is False
    assert health["mission_lifecycle_automation_planner_invocation_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_automation_contract_exposes_mapping_pipeline_and_current_eligibility(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "contract")
    view = service.get_mission_lifecycle_automation_contract(mission_id)
    contract = view["lifecycle_automation"]
    assert contract["schema_version"] == LIFECYCLE_AUTOMATION_SCHEMA_VERSION
    assert contract["event_to_command"]["PIP_BIND_REQUESTED"] == "BIND_PIP"
    assert contract["blind_state_mutation_allowed"] is False
    assert contract["direct_state_transition_api_used_by_automation"] is False
    assert contract["pipeline"][0] == "NORMALIZE_TYPED_EVENT"
    assert "STAGE_3_2_LIFECYCLE_GUARD_CHAIN" in contract["pipeline"]
    assert "PIP_BIND_REQUESTED" in contract["eligible_event_types_for_current_state"]
    assert "RUN_START_REQUESTED" not in contract["eligible_event_types_for_current_state"]
    discovery = service.get_mission_lifecycle_command_contract(mission_id)
    assert discovery["event_driven_lifecycle_automation"]["schema_version"] == LIFECYCLE_AUTOMATION_SCHEMA_VERSION


def test_invalid_event_type_and_timezone_fail_before_persistence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "invalid")
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "invalid")
    body["event_type"] = "UNKNOWN_EVENT"
    with pytest.raises(MissionValidationError):
        service.process_mission_lifecycle_event(mission_id, body)
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "invalid-time")
    body["occurred_at"] = "2026-09-04T09:00:00"
    with pytest.raises(MissionValidationError):
        service.process_mission_lifecycle_event(mission_id, body)
    events = service.get_mission_events(mission_id)
    assert events["event_count"] == 1


def test_pip_bind_event_applies_only_through_guarded_command_and_records_provenance(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "bind")
    before = service.get_mission_events(mission_id)["event_count"]
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "bind")
    result = service.process_mission_lifecycle_event(mission_id, body)
    assert result["automation_status"] == "APPLIED"
    assert result["idempotent_replay"] is False
    assert result["lifecycle_command_result"]["lifecycle_command"] == "BIND_PIP"
    assert result["mission_state"]["state"] == "PIP_BOUND"
    transition = result["transition"]
    provenance = transition["metadata"]["lifecycle_automation"]
    assert provenance["source_event_id"] == body["event_id"]
    assert provenance["source_event_type"] == "PIP_BIND_REQUESTED"
    assert provenance["signal_sha256"] == result["source_event_sha256"]
    assert provenance["governance_authorization_query_performed"] is False
    assert provenance["target_action_dispatch_enabled"] is False
    after = service.get_mission_events(mission_id)
    assert after["event_count"] == before + 4
    delta = after["events"][before:]
    assert [event["event_type"] for event in delta] == [
        MISSION_LIFECYCLE_EVENT_RECEIVED,
        "MISSION_STATE_TRANSITIONED",
        "MISSION_COMMAND_COMPLETED",
        MISSION_LIFECYCLE_EVENT_APPLIED,
    ]
    assert delta[-1]["parent_event_id"] == delta[-2]["event_id"]


def test_exact_source_event_replay_is_idempotent_and_adds_no_records(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replay")
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "replay")
    first = service.process_mission_lifecycle_event(mission_id, body)
    transitions = service.get_mission_state_history(mission_id)["transition_count"]
    events = service.get_mission_events(mission_id)["event_count"]
    commands = service.get_mission_command_history(mission_id)["command_count"]
    second = service.process_mission_lifecycle_event(mission_id, body)
    assert first["transition"]["transition_id"] == second["transition"]["transition_id"]
    assert second["idempotent_replay"] is True
    assert second["lifecycle_command_result"]["idempotent_replay"] is True
    assert service.get_mission_state_history(mission_id)["transition_count"] == transitions
    assert service.get_mission_events(mission_id)["event_count"] == events
    assert service.get_mission_command_history(mission_id)["command_count"] == commands


def test_source_event_identity_cannot_be_reused_with_different_payload(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "conflict")
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "conflict", event_id="source-fixed-conflict")
    service.process_mission_lifecycle_event(mission_id, body)
    conflicting = deepcopy(body)
    conflicting["reason"] = "different canonical payload under same source event identity"
    with pytest.raises(MissionCommandConflict):
        service.process_mission_lifecycle_event(mission_id, conflicting)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PIP_BOUND"


def test_stale_state_version_is_rejected_durably_and_replay_does_not_reevaluate(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "stale-state")
    stale = event_request(service, mission_id, "PIP_BIND_REQUESTED", "stale-state")
    stale["observed_state_version"] += 1
    before = service.get_mission_events(mission_id)["event_count"]
    with pytest.raises(MissionConcurrencyConflict):
        service.process_mission_lifecycle_event(mission_id, stale)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"
    after = service.get_mission_events(mission_id)
    assert after["event_count"] == before + 2
    assert after["events"][-2]["event_type"] == MISSION_LIFECYCLE_EVENT_RECEIVED
    assert after["events"][-1]["event_type"] == MISSION_LIFECYCLE_EVENT_REJECTED
    rejected_count = after["event_count"]
    with pytest.raises(MissionConcurrencyConflict):
        service.process_mission_lifecycle_event(mission_id, stale)
    assert service.get_mission_events(mission_id)["event_count"] == rejected_count


def test_stale_version_hash_is_rejected_before_state_mutation(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "stale-hash")
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "stale-hash")
    body["observed_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.process_mission_lifecycle_event(mission_id, body)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"
    assert service.get_mission_command_history(mission_id)["command_count"] == 0


def test_event_source_state_contract_rejects_semantically_wrong_observation(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "wrong-source")
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "wrong-source")
    body["observed_state"] = "RUNNING"
    with pytest.raises(MissionValidationError):
        service.process_mission_lifecycle_event(mission_id, body)
    assert service.get_mission_events(mission_id)["event_count"] == 1


def test_evidence_required_and_ready_events_drive_wait_resolution_with_exact_dependency(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "evidence")
    activate_running(service, mission_id)
    dep_id = "dep-stage329-evidence"
    required = event_request(
        service,
        mission_id,
        "EVIDENCE_REQUIRED",
        "evidence-required",
        metadata={"dependency": {"dependency_id": dep_id, "kind": "EVIDENCE", "description": "Need verified evidence"}},
        evidence_refs=["evidence:request:evidence"],
    )
    waiting = service.process_mission_lifecycle_event(mission_id, required)
    assert waiting["mission_state"]["state"] == "WAITING_EVIDENCE"
    assert waiting["lifecycle_command_result"]["waiting_dependency"]["dependency_id"] == dep_id
    ready = event_request(
        service,
        mission_id,
        "EVIDENCE_READY",
        "evidence-ready",
        metadata={"dependency_resolution": {"dependency_id": dep_id, "status": "SATISFIED", "resolved_by": "stage329-source"}},
        evidence_refs=["evidence:resolved:evidence"],
    )
    resumed = service.process_mission_lifecycle_event(mission_id, ready)
    assert resumed["mission_state"]["state"] == "RUNNING"
    resolution = resumed["lifecycle_command_result"]["waiting_dependency_resolution"]
    assert resolution["dependency_id"] == dep_id
    assert resolution["resolution_status"] == "SATISFIED"


def test_approval_events_remain_workflow_dependency_not_governance_authorization(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "approval")
    activate_running(service, mission_id)
    dep_id = "dep-stage329-approval"
    service.process_mission_lifecycle_event(
        mission_id,
        event_request(
            service,
            mission_id,
            "APPROVAL_REQUIRED",
            "approval-required",
            metadata={"dependency": {"dependency_id": dep_id, "kind": "APPROVAL"}},
        ),
    )
    granted = service.process_mission_lifecycle_event(
        mission_id,
        event_request(
            service,
            mission_id,
            "APPROVAL_GRANTED",
            "approval-granted",
            metadata={"dependency_resolution": {"dependency_id": dep_id, "status": "SATISFIED", "resolved_by": "human-review"}},
            evidence_refs=["evidence:approval:human-review"],
        ),
    )
    resolution = granted["lifecycle_command_result"]["waiting_dependency_resolution"]
    assert granted["mission_state"]["state"] == "RUNNING"
    assert resolution["approval_dependency_is_governance_authorization"] is False
    assert resolution["governance_authorization_query_performed"] is False
    assert resolution["authorization_granted"] is False


def test_pause_and_resume_events_preserve_stage326_pause_lineage(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "pause-resume")
    activate_running(service, mission_id)
    paused = service.process_mission_lifecycle_event(
        mission_id, event_request(service, mission_id, "PAUSE_REQUESTED", "pause")
    )
    assert paused["mission_state"]["state"] == "PAUSED"
    pause_id = paused["lifecycle_command_result"]["pause_control"]["pause_id"]
    resumed = service.process_mission_lifecycle_event(
        mission_id,
        event_request(service, mission_id, "RESUME_REQUESTED", "resume", target_state="RUNNING"),
    )
    assert resumed["mission_state"]["state"] == "RUNNING"
    assert resumed["lifecycle_command_result"]["resume_control"]["pause_id"] == pause_id


def test_resume_event_cannot_bypass_paused_waiting_dependency(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "pause-wait")
    activate_running(service, mission_id)
    dep_id = "dep-stage329-pause-wait"
    execute(
        service,
        mission_id,
        "WAIT_FOR_EVIDENCE",
        "wait-before-pause",
        metadata={"dependency": {"dependency_id": dep_id, "kind": "EVIDENCE"}},
    )
    execute(service, mission_id, "PAUSE", "pause-wait")
    body = event_request(service, mission_id, "RESUME_REQUESTED", "unsafe-resume", target_state="RUNNING")
    with pytest.raises(MissionLifecycleGuardRejected):
        service.process_mission_lifecycle_event(mission_id, body)
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "PAUSED"
    assert service.get_mission_events(mission_id)["events"][-1]["event_type"] == MISSION_LIFECYCLE_EVENT_REJECTED


def test_replan_requested_and_ready_events_use_existing_replan_readiness_gate(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replan")
    activate_running(service, mission_id)
    requested = service.process_mission_lifecycle_event(
        mission_id,
        event_request(service, mission_id, "REPLAN_REQUESTED", "replan-request", evidence_refs=["evidence:replan:trigger"]),
    )
    assert requested["mission_state"]["state"] == "REPLANNING"
    replan_id = requested["lifecycle_command_result"]["replan_control"]["replan_id"]
    ready = service.process_mission_lifecycle_event(
        mission_id,
        event_request(service, mission_id, "REPLAN_READY", "replan-ready", evidence_refs=["evidence:replan:ready"]),
    )
    assert ready["mission_state"]["state"] == "RUNNING"
    assert ready["lifecycle_command_result"]["replan_resolution"]["replan_id"] == replan_id
    assert ready["lifecycle_command_result"]["replan_resolution"]["readiness_status"] == "READY"


def test_cleanup_and_verified_completion_events_preserve_stage328_gate(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "complete", criteria_count=2)
    activate_running(service, mission_id)
    cleanup = service.process_mission_lifecycle_event(
        mission_id, event_request(service, mission_id, "CLEANUP_REQUESTED", "cleanup")
    )
    assert cleanup["mission_state"]["state"] == "CLEANING_UP"
    refs, metadata = valid_completion_bundle(2, prefix="event-complete")
    completed = service.process_mission_lifecycle_event(
        mission_id,
        event_request(service, mission_id, "COMPLETION_VERIFIED", "complete", metadata=metadata, evidence_refs=refs),
    )
    assert completed["mission_state"]["state"] == "COMPLETED"
    verification = completed["lifecycle_command_result"]["completion_verification"]
    assert verification["verified_completion_claimed"] is True
    assert verification["cleanup_completion_gate_applied"] is True


def test_completion_event_requires_structured_completion_contract_before_receipt(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "complete-invalid")
    activate_running(service, mission_id)
    execute(service, mission_id, "BEGIN_CLEANUP", "cleanup-invalid")
    before = service.get_mission_events(mission_id)["event_count"]
    body = event_request(service, mission_id, "COMPLETION_VERIFIED", "missing-completion", evidence_refs=["evidence:x"])
    with pytest.raises(MissionValidationError):
        service.process_mission_lifecycle_event(mission_id, body)
    assert service.get_mission_events(mission_id)["event_count"] == before
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CLEANING_UP"


def test_abort_requested_event_preserves_typed_terminal_semantics(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "abort")
    result = service.process_mission_lifecycle_event(
        mission_id, event_request(service, mission_id, "ABORT_REQUESTED", "abort", evidence_refs=["evidence:abort"])
    )
    assert result["mission_state"]["state"] == "ABORTED"
    terminal = result["lifecycle_command_result"]["terminal_control"]
    assert terminal["terminal_command"] == "ABORT"
    assert terminal["terminal_state"] == "ABORTED"
    assert terminal["verified_completion_claimed"] is False


def test_failure_detected_event_preserves_failed_terminal_semantics(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "failure")
    result = service.process_mission_lifecycle_event(
        mission_id, event_request(service, mission_id, "FAILURE_DETECTED", "failure", evidence_refs=["evidence:failure"])
    )
    assert result["mission_state"]["state"] == "FAILED"
    assert result["lifecycle_command_result"]["terminal_control"]["cause_family"] == "FAILURE"


def test_expiration_reached_event_preserves_expired_terminal_semantics(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "expire")
    result = service.process_mission_lifecycle_event(
        mission_id, event_request(service, mission_id, "EXPIRATION_REACHED", "expire")
    )
    assert result["mission_state"]["state"] == "EXPIRED"
    assert result["lifecycle_command_result"]["terminal_control"]["cause_family"] == "EXPIRATION"


def test_lifecycle_lineage_exposes_upstream_source_event_edges(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "lineage")
    body = event_request(service, mission_id, "PIP_BIND_REQUESTED", "lineage", event_id="upstream-lifecycle-001")
    result = service.process_mission_lifecycle_event(mission_id, body)
    lineage = service.get_mission_lineage(mission_id)
    matching = [edge for edge in lineage["upstream_edges"] if edge["upstream_event_id"] == "upstream-lifecycle-001"]
    assert len(matching) == 2
    local_ids = {edge["local_event_id"] for edge in matching}
    assert result["receipt_event"]["event_id"] in local_ids
    assert result["outcome_event"]["event_id"] in local_ids
    assert lineage["integrity_status"] == "PASS"


def test_automation_uses_deterministic_command_journal_and_canonical_command_event(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "journal")
    result = service.process_mission_lifecycle_event(
        mission_id, event_request(service, mission_id, "PIP_BIND_REQUESTED", "journal")
    )
    commands = service.get_mission_command_history(mission_id)
    assert commands["command_count"] == 1
    command = commands["commands"][0]
    assert command["operation"] == "LIFECYCLE_COMMAND"
    assert command["command_id"].startswith("lauto-")
    assert command["idempotency_key"].startswith("lauto-idem-")
    events = service.get_mission_events(mission_id)["events"]
    command_events = [event for event in events if event["event_type"] == "MISSION_COMMAND_COMPLETED"]
    assert len(command_events) == 1
    assert command_events[0]["causation_id"] == command["command_id"]
    assert result["outcome_event"]["payload"]["existing_command_journal_used"] is True
    assert result["outcome_event"]["payload"]["direct_state_transition_bypass_used"] is False
