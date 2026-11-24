from __future__ import annotations

import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionExecutionResultCaptureConflict,
    MissionExecutionResultCaptureGuardRejected,
    MissionRepositoryIntegrityError,
    MissionSubsystemProtocolError,
    MissionSubsystemUnavailable,
    MissionValidationError,
)
from mission_orchestrator.execution_result import (
    EXECUTION_RESULT_ATTEMPT_STATUS,
    EXECUTION_RESULT_AUTHORITY,
    EXECUTION_RESULT_ID_PREFIX,
    EXECUTION_RESULT_MODE,
    EXECUTION_RESULT_SCHEMA_VERSION,
    TERMINAL_EXECUTION_STATES,
    canonical_execution_result_definition,
    verify_execution_result_capture_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_6_running_execution_state_heartbeat_projection import (
    FakeRunningExecutionClient,
    provision_running,
    running_request,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE356 = "stage3.5.6-running-execution-state-heartbeat-projection"
STAGE357 = "stage3.5.7-execution-result-evidence-artifact-capture"


class FakeExecutionResultClient(FakeRunningExecutionClient):
    def __init__(self):
        super().__init__()
        self.result_calls = 0
        self.result_response = None
        self.raise_result = None

    def execution_result(self, subsystem_id, endpoint, *, mission_id, execution_attempt_id, dispatch_envelope_id):
        self.result_calls += 1
        if self.raise_result is not None:
            raise self.raise_result
        if self.result_response is not None:
            return self.result_response
        return {
            "status": "completed",
            "mission_id": mission_id,
            "execution_attempt_id": execution_attempt_id,
            "dispatch_envelope_id": dispatch_envelope_id,
            "observed_by": subsystem_id,
            "execution_state": "SUCCEEDED",
            "execution_started": True,
            "completed_at": "2026-09-15T02:00:00Z",
            "summary": "Authorized runtime execution completed and produced verifiable evidence.",
            "evidence": [
                {
                    "evidence_id": "evidence-runtime-log-1",
                    "type": "runtime-log",
                    "uri": "evidence://runtime/logs/1",
                    "sha256": "1" * 64,
                    "media_type": "application/json",
                    "size_bytes": 128,
                    "metadata": {"source": "runtime"},
                }
            ],
            "artifacts": [
                {
                    "artifact_id": "artifact-report-1",
                    "type": "execution-report",
                    "uri": "artifact://reports/execution-1.json",
                    "sha256": "2" * 64,
                    "media_type": "application/json",
                    "size_bytes": 256,
                    "metadata": {"classification": "test"},
                }
            ],
        }


def provision_result(tmp_path, key: str):
    service, governance, _, mission_id, active, dispatch, gate, reval, attempt, delivery = provision_running(tmp_path, key)
    runtime = FakeExecutionResultClient()
    service.execution_delivery_client = runtime
    running = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, f"{key}-running")
    )
    return service, governance, runtime, mission_id, active, dispatch, gate, reval, attempt, delivery, running


def result_request(service, mission_id: str, active: dict, attempt: dict, delivery: dict, running: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage357-result-{key}",
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
        "captured_by": "stage3.5.7-pytest",
        "reason": "Capture authoritative terminal result plus immutable evidence/artifact references",
        "metadata": {"stage": "3.5.7", "key": key},
    }
    body.update(overrides)
    return body


def test_01_health_activates_stage357_and_declares_capture_boundary(tmp_path):
    service, *_ = provision_result(tmp_path, "health")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert (health if "health" in locals() else h)["supported_controls"][-1] == CONTROL
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["execution_result_schema_version"] == EXECUTION_RESULT_SCHEMA_VERSION
    assert health["execution_result_mode"] == EXECUTION_RESULT_MODE
    assert health["execution_result_authority"] == EXECUTION_RESULT_AUTHORITY
    assert health["execution_result_database_migration_level"] == 33
    assert health["execution_result_persistence_store"] == "mission_execution_result_captures"
    assert "mission_execution_result_captures" in REPOSITORY_STORES
    assert health["execution_result_evidence_required"] is True
    assert health["execution_result_artifact_optional"] is True
    assert health["execution_result_inline_artifact_payload_persisted"] is False
    assert health["execution_result_is_not_task_completion_authority"] is True
    assert health["execution_result_mission_state_transition_performed"] is False


def test_02_definition_requires_latest_stage356_and_defers_verification_to_358(tmp_path):
    service, _, _, mission_id, *_ = provision_result(tmp_path, "definition")
    definition = service.get_execution_result_capture_definition(mission_id)[
        "execution_result_evidence_artifact_capture_definition"
    ]
    assert definition == canonical_execution_result_definition()
    assert definition["requires_latest_stage356_running_projection"] is True
    assert definition["one_terminal_result_per_execution_attempt"] is True
    assert set(definition["terminal_execution_states"]) == set(TERMINAL_EXECUTION_STATES)
    assert definition["evidence_required"] is True
    assert definition["artifact_optional"] is True
    assert definition["result_capture_is_not_task_completion_authority"] is True
    assert definition["next_stage"] == "3.5.8"


def test_03_happy_path_captures_terminal_result_evidence_and_artifact_references(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "happy")
    result = service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, "happy")
    )
    assert result["result_capture_id"].startswith(EXECUTION_RESULT_ID_PREFIX)
    assert result["execution_state"] == "SUCCEEDED"
    assert result["execution_attempt_status"] == EXECUTION_RESULT_ATTEMPT_STATUS
    assert result["evidence_count"] == 1
    assert result["artifact_count"] == 1
    assert result["evidence_capture_performed"] is True
    assert result["artifact_capture_performed"] is True
    assert result["result_capture_is_not_task_completion_authority"] is True
    assert result["mission_state_transition_performed"] is False
    assert verify_execution_result_capture_contract(result["execution_result_capture_contract"])
    assert runtime.result_calls == 1
    assert result["execution_result_capture_contract"]["evidence_manifest"]["items"][0]["uri"].startswith("evidence://")
    assert result["execution_result_capture_contract"]["artifact_manifest"]["items"][0]["uri"].startswith("artifact://")


def test_04_evidence_is_required_but_artifacts_are_optional(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "optional")
    default = runtime.execution_result(delivery["recipient_subsystem_id"], delivery["runtime_endpoint"], mission_id=mission_id, execution_attempt_id=attempt["execution_attempt_id"], dispatch_envelope_id=attempt["dispatch_envelope_id"])
    runtime.result_calls = 0
    default["artifacts"] = []
    runtime.result_response = default
    result = service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, "optional")
    )
    assert result["evidence_count"] == 1
    assert result["artifact_count"] == 0
    assert result["artifact_capture_performed"] is False

    service2, _, runtime2, mission2, active2, _, _, _, attempt2, delivery2, running2 = provision_result(tmp_path, "missing-evidence")
    bad = runtime2.execution_result(delivery2["recipient_subsystem_id"], delivery2["runtime_endpoint"], mission_id=mission2, execution_attempt_id=attempt2["execution_attempt_id"], dispatch_envelope_id=attempt2["dispatch_envelope_id"])
    runtime2.result_calls = 0
    bad["evidence"] = []
    runtime2.result_response = bad
    with pytest.raises(MissionSubsystemProtocolError, match="at least one authoritative evidence"):
        service2.capture_execution_result(
            mission2, result_request(service2, mission2, active2, attempt2, delivery2, running2, "missing-evidence")
        )


def test_05_inline_evidence_or_artifact_payload_is_rejected(tmp_path):
    for collection, key, value in [("evidence", "content", "raw-secret"), ("artifacts", "base64", "AA==")]:
        service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, f"inline-{collection}")
        bad = runtime.execution_result(delivery["recipient_subsystem_id"], delivery["runtime_endpoint"], mission_id=mission_id, execution_attempt_id=attempt["execution_attempt_id"], dispatch_envelope_id=attempt["dispatch_envelope_id"])
        runtime.result_calls = 0
        bad[collection][0][key] = value
        runtime.result_response = bad
        with pytest.raises(MissionSubsystemProtocolError, match="forbidden inline payload"):
            service.capture_execution_result(
                mission_id, result_request(service, mission_id, active, attempt, delivery, running, f"inline-{collection}")
            )


def test_06_stage357_reuses_runtime_endpoint_and_performs_no_governance_or_redelivery(tmp_path):
    service, governance, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "boundary")
    before_gov = governance.evaluate_calls
    before = (runtime.resolve_calls, runtime.deliver_calls, runtime.status_calls)
    result = service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, "boundary")
    )
    assert governance.evaluate_calls == before_gov
    assert (runtime.resolve_calls, runtime.deliver_calls, runtime.status_calls) == before
    assert runtime.result_calls == 1
    assert result["runtime_endpoint"] == delivery["runtime_endpoint"]
    assert result["runtime_endpoint_resolution_performed"] is False
    assert result["dispatch_redelivery_performed"] is False
    assert result["governance_query_performed"] is False


def test_07_stale_state_or_version_vector_fails_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "stale")
    baseline = (runtime.health_calls, runtime.result_calls)
    body = result_request(service, mission_id, active, attempt, delivery, running, "stale-state")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict):
        service.capture_execution_result(mission_id, body)
    body = result_request(service, mission_id, active, attempt, delivery, running, "stale-vector")
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.capture_execution_result(mission_id, body)
    assert (runtime.health_calls, runtime.result_calls) == baseline


def test_08_stale_plan_delivery_attempt_or_running_binding_fails_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "bindings")
    baseline = (runtime.health_calls, runtime.result_calls)
    for field in [
        "expected_active_plan_sha256",
        "expected_execution_delivery_sha256",
        "expected_execution_attempt_sha256",
        "expected_running_projection_sha256",
    ]:
        body = result_request(service, mission_id, active, attempt, delivery, running, f"bad-{field}")
        body[field] = "0" * 64
        with pytest.raises(MissionConcurrencyConflict):
            service.capture_execution_result(mission_id, body)
    assert (runtime.health_calls, runtime.result_calls) == baseline


def test_09_result_must_bind_latest_stage356_projection(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, first = provision_result(tmp_path, "latest")
    second = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "latest-running-2")
    )
    baseline = (runtime.health_calls, runtime.result_calls)
    with pytest.raises(MissionExecutionResultCaptureGuardRejected, match="latest durable"):
        service.capture_execution_result(
            mission_id, result_request(service, mission_id, active, attempt, delivery, first, "old-running")
        )
    assert (runtime.health_calls, runtime.result_calls) == baseline
    assert second["heartbeat_sequence"] > first["heartbeat_sequence"]


def test_10_caller_cannot_inject_result_evidence_artifacts_or_runtime_endpoint(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "inject")
    baseline = (runtime.health_calls, runtime.result_calls)
    for field, value in [
        ("execution_state", "SUCCEEDED"),
        ("evidence", []),
        ("artifacts", []),
        ("runtime_endpoint", "http://attacker"),
        ("completed_at", "2026-09-15T02:00:00Z"),
    ]:
        body = result_request(service, mission_id, active, attempt, delivery, running, f"inject-{field}")
        body[field] = value
        with pytest.raises(MissionValidationError):
            service.capture_execution_result(mission_id, body)
    assert (runtime.health_calls, runtime.result_calls) == baseline


def test_11_runtime_unavailable_or_protocol_invalid_fails_closed_without_capture(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "runtimefail")
    runtime.raise_health = MissionSubsystemUnavailable("runtime down")
    with pytest.raises(MissionSubsystemUnavailable):
        service.capture_execution_result(
            mission_id, result_request(service, mission_id, active, attempt, delivery, running, "healthfail")
        )
    assert service.get_execution_result_capture_history(mission_id)["result_capture_count"] == 0
    runtime.raise_health = None
    runtime.result_response = {"status": "completed"}
    with pytest.raises(MissionSubsystemProtocolError):
        service.capture_execution_result(
            mission_id, result_request(service, mission_id, active, attempt, delivery, running, "badresult")
        )
    assert service.get_execution_result_capture_history(mission_id)["result_capture_count"] == 0


def test_12_runtime_identity_and_terminal_state_are_strict(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "strict")
    response = runtime.execution_result(delivery["recipient_subsystem_id"], delivery["runtime_endpoint"], mission_id=mission_id, execution_attempt_id=attempt["execution_attempt_id"], dispatch_envelope_id=attempt["dispatch_envelope_id"])
    runtime.result_calls = 0
    response["execution_state"] = "RUNNING"
    runtime.result_response = response
    with pytest.raises(MissionSubsystemProtocolError, match="terminal execution_state"):
        service.capture_execution_result(
            mission_id, result_request(service, mission_id, active, attempt, delivery, running, "strict")
        )


def test_13_exact_idempotent_replay_does_not_repeat_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "replay")
    body = result_request(service, mission_id, active, attempt, delivery, running, "replay")
    first = service.capture_execution_result(mission_id, body)
    counts = (runtime.health_calls, runtime.result_calls)
    second = service.capture_execution_result(mission_id, body)
    assert second["idempotent_replay"] is True
    assert second["result_capture_id"] == first["result_capture_id"]
    assert (runtime.health_calls, runtime.result_calls) == counts


def test_14_idempotency_reuse_or_second_terminal_capture_is_conflict(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "conflict")
    body = result_request(service, mission_id, active, attempt, delivery, running, "conflict")
    service.capture_execution_result(mission_id, body)
    changed = dict(body)
    changed["reason"] = "different request"
    with pytest.raises(MissionExecutionResultCaptureConflict):
        service.capture_execution_result(mission_id, changed)
    counts = (runtime.health_calls, runtime.result_calls)
    second_key = result_request(service, mission_id, active, attempt, delivery, running, "second-key")
    with pytest.raises(MissionExecutionResultCaptureConflict, match="already has"):
        service.capture_execution_result(mission_id, second_key)
    assert (runtime.health_calls, runtime.result_calls) == counts


def test_15_event_lineage_records_terminal_result_and_manifest_digests(tmp_path):
    service, _, _, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "event")
    result = service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, "event")
    )
    event = service.repository.get_mission_event_by_causation(
        mission_id, "MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURED", result["result_capture_id"]
    )
    assert event is not None
    payload = event["payload"]
    assert payload["canonical_sha256"] == result["canonical_sha256"]
    assert payload["execution_state"] == "SUCCEEDED"
    assert payload["evidence_manifest_sha256"] == result["evidence_manifest_sha256"]
    assert payload["artifact_manifest_sha256"] == result["artifact_manifest_sha256"]
    assert payload["result_capture_is_not_task_completion_authority"] is True
    assert payload["mission_state_transition_performed"] is False


def test_16_repository_reconstruction_includes_result_capture_and_detects_tamper(tmp_path):
    service, _, _, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "repo")
    service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, "repo")
    )
    view = service.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert view["record_counts"]["mission_execution_result_captures"] == 1
    assert len(view["persistence_manifest"]["execution_result_evidence_artifact_capture_store"]["captures"]) == 1

    db = service.repository.sqlite_path
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_execution_result_captures SET evidence_count=999 WHERE mission_id=?",
            (mission_id,),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError, match="execution_result_evidence_artifact_capture_store"):
        service.get_mission_repository(mission_id)


def test_17_result_capture_survives_repository_restart(tmp_path):
    service, governance, _, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "restart")
    db_path = service.repository.sqlite_path
    result = service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, "restart")
    )
    restarted = CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=db_path),
        governance_client=governance,
        execution_delivery_client=FakeExecutionResultClient(),
    )
    recovered = restarted.get_execution_result_capture(mission_id, result["result_capture_id"])
    assert recovered["result_capture_id"] == result["result_capture_id"]
    assert recovered["evidence_count"] == 1
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"


def test_18_result_capture_does_not_mark_task_or_mission_completed(tmp_path):
    service, _, _, mission_id, active, _, _, _, attempt, delivery, running = provision_result(tmp_path, "authority")
    before = service.get_mission_state(mission_id)["mission_state"]
    result = service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, attempt, delivery, running, "authority")
    )
    after = service.get_mission_state(mission_id)["mission_state"]
    assert before["state"] == after["state"] == "RUNNING"
    assert before["state_version"] == after["state_version"]
    assert result["result_capture_is_not_task_completion_authority"] is True
    assert result["mission_state_transition_performed"] is False
