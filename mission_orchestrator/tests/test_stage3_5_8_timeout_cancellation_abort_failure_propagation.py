from __future__ import annotations

import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionExecutionOutcomePropagationConflict,
    MissionExecutionOutcomePropagationGuardRejected,
    MissionExecutionTerminationControlConflict,
    MissionExecutionTerminationControlGuardRejected,
    MissionRepositoryIntegrityError,
    MissionSubsystemProtocolError,
    MissionSubsystemUnavailable,
    MissionValidationError,
)
from mission_orchestrator.execution_termination import (
    ACTION_ABORT,
    ACTION_CANCEL,
    ACTION_TIMEOUT,
    EXPECTED_TERMINAL_STATE_BY_ACTION,
    OUTCOME_PROPAGATION_ID_PREFIX,
    STAGE358_SCHEMA_VERSION,
    TERMINAL_OUTCOME_PROPAGATION_SCHEMA_VERSION,
    TERMINATION_CONTROL_ID_PREFIX,
    TERMINATION_CONTROL_SCHEMA_VERSION,
    canonical_stage358_definition,
    verify_outcome_propagation_contract,
    verify_termination_control_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_7_execution_result_evidence_artifact_capture import (
    FakeExecutionResultClient,
    provision_result,
    result_request,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE357 = "stage3.5.7-execution-result-evidence-artifact-capture"


class FakeStage358Runtime(FakeExecutionResultClient):
    def __init__(self):
        super().__init__()
        self.control_calls = 0
        self.control_response = None
        self.raise_control = None
        self.last_control_payload = None

    def execution_control(self, subsystem_id, endpoint, *, mission_id, execution_attempt_id, dispatch_envelope_id, payload):
        self.control_calls += 1
        self.last_control_payload = payload
        if self.raise_control is not None:
            raise self.raise_control
        if self.control_response is not None:
            return self.control_response
        return {
            "status": "accepted",
            "mission_id": mission_id,
            "execution_attempt_id": execution_attempt_id,
            "dispatch_envelope_id": dispatch_envelope_id,
            "observed_by": subsystem_id,
            "control_action": payload["control_action"],
            "termination_requested": True,
            "acknowledged_at": "2026-09-15T08:00:00Z",
        }


def provision_358(tmp_path, key: str):
    service, governance, _, mission_id, active, dispatch, gate, reval, attempt, delivery, running = provision_result(tmp_path, key)
    runtime = FakeStage358Runtime()
    service.execution_delivery_client = runtime
    return service, governance, runtime, mission_id, active, dispatch, gate, reval, attempt, delivery, running


def termination_request(service, mission_id, active, attempt, delivery, running, key, action=ACTION_CANCEL, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage358-term-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_execution_delivery_id": delivery["execution_delivery_id"],
        "expected_execution_delivery_sha256": delivery["canonical_sha256"],
        "expected_execution_attempt_id": attempt["execution_attempt_id"],
        "expected_execution_attempt_sha256": attempt["canonical_sha256"],
        "expected_dispatch_envelope_id": attempt["dispatch_envelope_id"],
        "expected_running_projection_id": running["running_projection_id"],
        "expected_running_projection_sha256": running["canonical_sha256"],
        "control_action": action,
        "requested_by": "stage3.5.8-pytest",
        "reason": "exercise explicit runtime termination control",
        "metadata": {"stage": "3.5.8", "key": key},
    }
    body.update(overrides)
    return body


def capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, key, execution_state):
    raw = runtime.execution_result(
        delivery["recipient_subsystem_id"], delivery["runtime_endpoint"], mission_id=mission_id,
        execution_attempt_id=attempt["execution_attempt_id"], dispatch_envelope_id=attempt["dispatch_envelope_id"]
    )
    runtime.result_calls = 0
    raw["execution_state"] = execution_state
    runtime.result_response = raw
    return service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, key)
    )


def propagation_request(service, mission_id, active, attempt, result, key, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage358-prop-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_result_capture_id": result["result_capture_id"],
        "expected_result_capture_sha256": result["canonical_sha256"],
        "expected_execution_attempt_id": attempt["execution_attempt_id"],
        "expected_execution_attempt_sha256": attempt["canonical_sha256"],
        "propagated_by": "stage3.5.8-pytest",
        "reason": "verify terminal execution outcome and propagate non-success fail-fast",
        "metadata": {"stage": "3.5.8", "key": key},
    }
    body.update(overrides)
    return body


def test_01_health_activates_stage358_and_migration34(tmp_path):
    service, *_ = provision_358(tmp_path, "health")
    h = service.health()
    assert h["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert (health if "health" in locals() else h)["supported_controls"][-1] == CONTROL
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["stage358_schema_version"] == STAGE358_SCHEMA_VERSION
    assert h["execution_termination_control_schema_version"] == TERMINATION_CONTROL_SCHEMA_VERSION
    assert h["execution_outcome_propagation_schema_version"] == TERMINAL_OUTCOME_PROPAGATION_SCHEMA_VERSION
    assert "mission_execution_termination_controls" in REPOSITORY_STORES
    assert "mission_execution_outcome_propagations" in REPOSITORY_STORES


def test_02_definition_declares_control_actions_and_failure_mapping(tmp_path):
    service, _, _, mission_id, *_ = provision_358(tmp_path, "definition")
    definition = service.get_stage358_definition(mission_id)["timeout_cancellation_abort_failure_propagation_definition"]
    assert definition == canonical_stage358_definition()
    assert set(definition["termination_control"]["actions"]) == {"TIMEOUT", "CANCEL", "ABORT"}
    assert definition["termination_control"]["expected_terminal_state_by_action"] == EXPECTED_TERMINAL_STATE_BY_ACTION
    assert definition["outcome_propagation"]["success_does_not_imply_mission_completion"] is True
    assert definition["next_stage"] == "3.5.9"


@pytest.mark.parametrize("action,expected", [(ACTION_TIMEOUT, "TIMED_OUT"), (ACTION_CANCEL, "CANCELLED"), (ACTION_ABORT, "CANCELLED")])
def test_03_05_runtime_termination_controls_are_acknowledged_and_immutable(tmp_path, action, expected):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, action.lower())
    result = service.control_running_execution(
        mission_id, termination_request(service, mission_id, active, attempt, delivery, running, action.lower(), action)
    )
    assert result["termination_control_id"].startswith(TERMINATION_CONTROL_ID_PREFIX)
    assert result["control_action"] == action
    assert result["expected_terminal_state"] == expected
    assert result["control_status"] == "ACKNOWLEDGED_PENDING_TERMINAL_RESULT"
    assert result["mission_state_transition_performed"] is False
    assert verify_termination_control_contract(result["termination_control_contract"])
    assert runtime.control_calls == 1
    assert runtime.last_control_payload["control_action"] == action
    assert runtime.last_control_payload["semantics"]["new_execution_dispatch"] is False


def test_06_control_rejects_stale_state_or_hash_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "stale")
    baseline = (runtime.health_calls, runtime.control_calls)
    body = termination_request(service, mission_id, active, attempt, delivery, running, "stale-state")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict):
        service.control_running_execution(mission_id, body)
    body = termination_request(service, mission_id, active, attempt, delivery, running, "stale-hash")
    body["expected_running_projection_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.control_running_execution(mission_id, body)
    assert (runtime.health_calls, runtime.control_calls) == baseline


def test_07_control_is_forbidden_after_terminal_result_capture(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "late")
    capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "late-result", "SUCCEEDED")
    with pytest.raises(MissionExecutionTerminationControlConflict, match="terminal result"):
        service.control_running_execution(
            mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "late", ACTION_CANCEL)
        )


def test_08_control_runtime_failure_fails_closed_without_record(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "runtime-fail")
    runtime.raise_control = MissionSubsystemUnavailable("runtime control unavailable")
    with pytest.raises(MissionSubsystemUnavailable):
        service.control_running_execution(
            mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "down", ACTION_ABORT)
        )
    assert service.get_execution_termination_control_history(mission_id)["termination_control_count"] == 0
    runtime.raise_control = None
    runtime.control_response = {"status": "accepted"}
    with pytest.raises(MissionSubsystemProtocolError):
        service.control_running_execution(
            mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "bad-protocol", ACTION_ABORT)
        )
    assert service.get_execution_termination_control_history(mission_id)["termination_control_count"] == 0


def test_09_control_exact_replay_does_not_repeat_runtime_io_and_second_control_conflicts(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "control-replay")
    body = termination_request(service, mission_id, active, attempt, delivery, running, "replay", ACTION_CANCEL)
    first = service.control_running_execution(mission_id, body)
    counts = (runtime.health_calls, runtime.control_calls)
    replay = service.control_running_execution(mission_id, body)
    assert replay["idempotent_replay"] is True
    assert replay["termination_control_id"] == first["termination_control_id"]
    assert (runtime.health_calls, runtime.control_calls) == counts
    with pytest.raises(MissionExecutionTerminationControlConflict):
        service.control_running_execution(
            mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "second", ACTION_ABORT)
        )


def test_10_success_is_verified_without_completing_mission(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "success")
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "success-result", "SUCCEEDED")
    prop = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, attempt, result, "success")
    )
    assert prop["outcome_propagation_id"].startswith(OUTCOME_PROPAGATION_ID_PREFIX)
    assert prop["outcome_classification"] == "VERIFIED_SUCCESS"
    assert prop["task_outcome_status"] == "VERIFIED_COMPLETED"
    assert prop["failure_propagation_performed"] is False
    assert prop["resulting_mission_state"] == "RUNNING"
    assert verify_outcome_propagation_contract(prop["outcome_propagation_contract"])
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"


@pytest.mark.parametrize(
    "execution_state,classification,target,command",
    [("FAILED", "VERIFIED_FAILURE", "FAILED", "FAIL"), ("TIMED_OUT", "VERIFIED_TIMEOUT", "FAILED", "FAIL"), ("CANCELLED", "VERIFIED_CANCELLATION", "ABORTED", "ABORT")],
)
def test_11_13_non_success_results_propagate_to_canonical_terminal_state(tmp_path, execution_state, classification, target, command):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, execution_state.lower())
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, execution_state.lower(), execution_state)
    prop = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, attempt, result, execution_state.lower())
    )
    assert prop["outcome_classification"] == classification
    assert prop["lifecycle_command"] == command
    assert prop["failure_propagation_performed"] is True
    assert prop["resulting_mission_state"] == target
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == target


def test_14_cancelled_after_abort_control_is_verified_abort(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "abort")
    term = service.control_running_execution(
        mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "abort", ACTION_ABORT)
    )
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "abort-result", "CANCELLED")
    prop = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, attempt, result, "abort-prop")
    )
    assert prop["termination_control_id"] == term["termination_control_id"]
    assert prop["outcome_classification"] == "VERIFIED_ABORT"
    assert prop["resulting_mission_state"] == "ABORTED"


def test_15_cancelled_after_timeout_control_is_verified_timeout_and_fails_mission(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "timeout-fallback")
    service.control_running_execution(
        mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "timeout", ACTION_TIMEOUT)
    )
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "timeout-result", "CANCELLED")
    prop = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, attempt, result, "timeout-prop")
    )
    assert prop["outcome_classification"] == "VERIFIED_TIMEOUT"
    assert prop["task_outcome_status"] == "VERIFIED_TIMED_OUT"
    assert prop["resulting_mission_state"] == "FAILED"


def test_16_success_after_acknowledged_termination_control_is_fail_closed(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "inconsistent")
    service.control_running_execution(
        mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "cancel", ACTION_CANCEL)
    )
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "success-result", "SUCCEEDED")
    with pytest.raises(MissionExecutionOutcomePropagationGuardRejected, match="SUCCEEDED"):
        service.propagate_execution_outcome(
            mission_id, propagation_request(service, mission_id, active, attempt, result, "inconsistent")
        )


def test_17_propagation_idempotency_replay_does_not_duplicate_terminal_transition(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "prop-replay")
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "failed", "FAILED")
    body = propagation_request(service, mission_id, active, attempt, result, "failed")
    first = service.propagate_execution_outcome(mission_id, body)
    state_after = service.get_mission_state(mission_id)["mission_state"]
    second = service.propagate_execution_outcome(mission_id, body)
    assert second["idempotent_replay"] is True
    assert second["outcome_propagation_id"] == first["outcome_propagation_id"]
    assert service.get_mission_state(mission_id)["mission_state"]["state_version"] == state_after["state_version"]


def test_18_caller_cannot_inject_outcome_or_target_state(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "inject")
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "inject-result", "FAILED")
    for field, value in [("outcome_classification", "VERIFIED_SUCCESS"), ("target_mission_state", "COMPLETED"), ("lifecycle_command", "COMPLETE")]:
        body = propagation_request(service, mission_id, active, attempt, result, field)
        body[field] = value
        with pytest.raises(MissionValidationError):
            service.propagate_execution_outcome(mission_id, body)


def test_19_event_lineage_and_repository_reconstruction_cover_both_stage358_stores(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "repo")
    term = service.control_running_execution(
        mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "term", ACTION_CANCEL)
    )
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "result", "CANCELLED")
    prop = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, attempt, result, "prop")
    )
    assert service.repository.get_mission_event_by_causation(mission_id, "MISSION_EXECUTION_TERMINATION_CONTROL_ACKNOWLEDGED", term["termination_control_id"])
    assert service.repository.get_mission_event_by_causation(mission_id, "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED", prop["outcome_propagation_id"])
    view = service.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert view["record_counts"]["mission_execution_termination_controls"] == 1
    assert view["record_counts"]["mission_execution_outcome_propagations"] == 1
    assert len(view["persistence_manifest"]["execution_timeout_cancellation_abort_control_store"]["controls"]) == 1
    assert len(view["persistence_manifest"]["execution_terminal_outcome_failure_propagation_store"]["propagations"]) == 1


def test_20_repository_tamper_detection_and_restart_durability(tmp_path):
    service, governance, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "restart")
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "result", "SUCCEEDED")
    prop = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, attempt, result, "prop")
    )
    db = service.repository.sqlite_path
    restarted = CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=db),
        governance_client=governance,
        execution_delivery_client=FakeStage358Runtime(),
    )
    recovered = restarted.get_execution_outcome_propagation(mission_id, prop["outcome_propagation_id"])
    assert recovered["outcome_classification"] == "VERIFIED_SUCCESS"
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE mission_execution_outcome_propagations SET task_outcome_status='TAMPERED' WHERE mission_id=?", (mission_id,))
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError, match="execution_terminal_outcome_failure_propagation_store"):
        restarted.get_mission_repository(mission_id)
