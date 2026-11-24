from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.errors import MissionLifecycleGuardRejected
from mission_orchestrator.mission_lifecycle import (
    ACTIVATION_COMMAND,
    ACTIVATION_MODE,
    ACTIVATION_SCHEMA_VERSION,
    LIFECYCLE_COMMAND_OPERATION,
    mission_activation_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class NoCallExternal:
    base_url = "fake://stage323-no-call"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.2.3 activation must remain local-only: unexpected external call {name}")


def make_service(tmp_path: Path) -> CanonicalMissionService:
    no_call = NoCallExternal()
    repo = MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "missions.db"))
    return CanonicalMissionService(repo, governance_client=no_call, cti_client=no_call)


def mission_payload(key: str, *, with_pip: bool = True) -> dict:
    payload = {
        "idempotency_key": key,
        "source_system": "PYTEST_STAGE323",
        "created_by": "stage3.2.3-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage323-lab"},
        "success_criteria": [{"metric": "pip_activation", "expected": True}],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "metadata": {"environment": "LAB", "stage": "3.2.3"},
    }
    if with_pip:
        payload["pip_id"] = f"pip-{key}"
        payload["pip_version"] = "7"
    return payload


def create_mission(service: CanonicalMissionService, key: str, *, with_pip: bool = True) -> str:
    return service.create_mission(mission_payload(key, with_pip=with_pip))["canonical_identity"]["mission_id"]


def lifecycle_request(service: CanonicalMissionService, mission_id: str, command_id: str = "lc-323-bind") -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "command_id": command_id,
        "idempotency_key": f"idem-{command_id}",
        "command": "BIND_PIP",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.3-pytest",
        "reason_code": "ACTIVATE_PIP",
        "reason": "Activate immutable canonical PIP binding",
        "evidence_refs": ["evidence:test:stage323"],
        "metadata": {"stage": "3.2.3"},
    }


def test_health_declares_stage323_activation_without_migration_or_authority_expansion(tmp_path):
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
    assert health["mission_activation_schema_version"] == ACTIVATION_SCHEMA_VERSION
    assert health["mission_activation_mode"] == ACTIVATION_MODE
    assert health["mission_activation_command"] == ACTIVATION_COMMAND
    assert health["mission_activation_transition"] == "CREATED->PIP_BOUND"
    assert health["mission_activation_binding_source"] == "IMMUTABLE_CANONICAL_MISSION_ENVELOPE"
    assert health["mission_activation_pip_artifact_query_performed"] is False
    assert health["mission_activation_governance_query_performed"] is False
    assert health["mission_activation_authorization_granted"] is False
    assert health["mission_activation_execution_authorized"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_activation_contract_is_ready_only_from_created_with_complete_immutable_pip(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "ready")
    view = service.get_mission_activation_contract(mission_id)
    activation = view["mission_activation"]

    assert activation["schema_version"] == ACTIVATION_SCHEMA_VERSION
    assert activation["mode"] == ACTIVATION_MODE
    assert activation["activation_command"] == "BIND_PIP"
    assert activation["current_state"] == "CREATED"
    assert activation["activation_ready"] is True
    assert activation["pip_binding"] == {
        "pip_id": "pip-ready",
        "pip_version": "7",
        "binding_source": "IMMUTABLE_CANONICAL_MISSION_ENVELOPE",
    }
    assert activation["canonical_envelope"]["integrity_verified"] is True
    assert all(check["status"] == "PASS" for check in activation["checks"])
    assert activation["pip_artifact_query_performed"] is False
    assert activation["governance_authorization_query_performed"] is False
    assert activation["execution_authorized"] is False


def test_missing_pip_is_not_activation_ready_and_bind_still_fails_closed(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "missing", with_pip=False)
    view = service.get_mission_activation_contract(mission_id)["mission_activation"]
    assert view["activation_ready"] is False
    assert next(x for x in view["checks"] if x["check_id"] == "ACTIVATION_PIP_BINDING_COMPLETE")["status"] == "FAIL"

    before_events = service.get_mission_events(mission_id)["event_count"]
    with pytest.raises(MissionLifecycleGuardRejected, match="PIP_BINDING_COMPLETE_WHEN_REQUIRED"):
        service.execute_mission_lifecycle_command(mission_id, lifecycle_request(service, mission_id, "lc-323-missing"))
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "CREATED"
    assert service.get_mission_state_history(mission_id)["transition_count"] == 0
    assert service.get_mission_events(mission_id)["event_count"] == before_events


def test_successful_bind_pip_returns_durable_activation_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "success")
    before_envelope = service.get_envelope(mission_id)["envelope"]

    result = service.execute_mission_lifecycle_command(mission_id, lifecycle_request(service, mission_id))
    activation = result["mission_activation"]

    assert result["mission_state"]["state"] == "PIP_BOUND"
    assert activation["schema_version"] == ACTIVATION_SCHEMA_VERSION
    assert activation["activation_ready"] is True
    assert activation["from_state"] == "CREATED"
    assert activation["to_state"] == "PIP_BOUND"
    assert activation["pip_binding"]["pip_id"] == "pip-success"
    assert activation["pip_binding"]["pip_version"] == "7"
    assert activation["canonical_envelope"]["canonical_sha256"] == before_envelope["integrity"]["canonical_sha256"]
    assert result["transition"]["metadata"]["mission_activation"] == activation


def test_activation_does_not_mutate_the_immutable_pip_binding_or_envelope_hash(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "immutability")
    before = service.get_envelope(mission_id)["envelope"]
    service.execute_mission_lifecycle_command(mission_id, lifecycle_request(service, mission_id, "lc-323-immutable"))
    after = service.get_envelope(mission_id)["envelope"]
    assert after == before
    assert after["bindings"]["pip"] == {"pip_id": "pip-immutability", "pip_version": "7"}


def test_activation_contract_after_bind_is_not_ready_for_a_second_activation(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "once")
    service.execute_mission_lifecycle_command(mission_id, lifecycle_request(service, mission_id, "lc-323-once"))
    activation = service.get_mission_activation_contract(mission_id)["mission_activation"]
    assert activation["current_state"] == "PIP_BOUND"
    assert activation["activation_ready"] is False
    source = next(x for x in activation["checks"] if x["check_id"] == "ACTIVATION_SOURCE_STATE_CREATED")
    assert source["status"] == "FAIL"


def test_lifecycle_discovery_embeds_activation_projection(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "discovery")
    view = service.get_mission_lifecycle_command_contract(mission_id)
    assert view["mission_activation"]["activation_ready"] is True
    assert view["lifecycle_command_contract"]["stage3_2_3_activation_contract_schema_version"] == ACTIVATION_SCHEMA_VERSION
    assert view["lifecycle_command_contract"]["stage3_2_3_activation_command"] == "BIND_PIP"
    bind_guard = next(x for x in view["guard_evaluations"] if x["command"] == "BIND_PIP")
    integrity_check = next(
        x for x in bind_guard["checks"] if x["guard_id"] == "CANONICAL_ENVELOPE_INTEGRITY_FOR_PIP_ACTIVATION"
    )
    assert integrity_check["status"] == "PASS"
    assert integrity_check["required"] == "VERIFIED"


def test_non_activation_lifecycle_commands_do_not_claim_activation_authority(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "non-activation")
    service.execute_mission_lifecycle_command(mission_id, lifecycle_request(service, mission_id, "lc-323-first"))
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    request = {
        "command_id": "lc-323-plan",
        "idempotency_key": "idem-lc-323-plan",
        "command": "START_PLANNING",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.2.3-pytest",
        "reason_code": "START_PLAN",
        "evidence_refs": [],
        "metadata": {},
    }
    result = service.execute_mission_lifecycle_command(mission_id, request)
    assert result["mission_state"]["state"] == "PLANNING"
    assert result["mission_activation"] is None
    integrity_check = next(
        x for x in result["lifecycle_guard"]["checks"] if x["guard_id"] == "CANONICAL_ENVELOPE_INTEGRITY_FOR_PIP_ACTIVATION"
    )
    assert integrity_check["required"] == "NOT_REQUIRED"


def test_generic_guarded_command_path_preserves_stage323_activation_evidence(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "generic")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    generic = {
        "command_id": "cmd-323-generic",
        "idempotency_key": "idem-cmd-323-generic",
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": vector["version_sha256"],
        "payload": {
            "command": "BIND_PIP",
            "expected_state_version": state["state_version"],
            "actor": "stage3.2.3-pytest",
            "reason_code": "GENERIC_ACTIVATE",
            "reason": "Exercise generic guarded command path",
            "evidence_refs": [],
            "metadata": {},
        },
        "submitted_by": "stage3.2.3-pytest",
        "metadata": {},
    }
    result = service.execute_mission_command(mission_id, generic)
    assert result["result"]["mission_state"]["state"] == "PIP_BOUND"
    assert result["result"]["mission_activation"]["schema_version"] == ACTIVATION_SCHEMA_VERSION
    assert result["result"]["mission_activation"]["execution_authorized"] is False


def test_exact_replay_preserves_activation_evidence_without_duplicate_transition(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "replay")
    request = lifecycle_request(service, mission_id, "lc-323-replay")
    first = service.execute_mission_lifecycle_command(mission_id, request)
    replay = service.execute_mission_lifecycle_command(mission_id, request)
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert replay["mission_activation"] == first["mission_activation"]
    assert service.get_mission_state_history(mission_id)["transition_count"] == 1


def test_activation_uses_existing_event_lineage_without_new_authority_event_type(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "events")
    service.execute_mission_lifecycle_command(mission_id, lifecycle_request(service, mission_id, "lc-323-events"))
    events = service.get_mission_events(mission_id)["events"]
    assert [event["event_type"] for event in events] == [
        "MISSION_REGISTERED",
        "MISSION_STATE_TRANSITIONED",
        "MISSION_COMMAND_COMPLETED",
    ]
    assert all(event["event_type"] != "MISSION_AUTHORIZATION_BOUND" for event in events)


def test_activation_contract_fails_integrity_projection_for_tampered_envelope_without_external_query(tmp_path):
    service = make_service(tmp_path)
    mission_id = create_mission(service, "tamper-projection")
    envelope = deepcopy(service.get_envelope(mission_id)["envelope"])
    state = service.get_mission_state(mission_id)["mission_state"]
    envelope["bindings"]["pip"]["pip_version"] = "tampered"

    projection = mission_activation_contract(mission_id=mission_id, envelope=envelope, current_state=state)
    assert projection["activation_ready"] is False
    check = next(x for x in projection["checks"] if x["check_id"] == "ACTIVATION_CANONICAL_ENVELOPE_INTEGRITY")
    assert check["status"] == "FAIL"
    assert projection["pip_artifact_query_performed"] is False
    assert projection["governance_authorization_query_performed"] is False
