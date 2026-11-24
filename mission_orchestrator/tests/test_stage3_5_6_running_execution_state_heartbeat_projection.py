from __future__ import annotations

import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionExecutionRunningProjectionConflict,
    MissionExecutionRunningProjectionGuardRejected,
    MissionRepositoryIntegrityError,
    MissionSubsystemProtocolError,
    MissionSubsystemUnavailable,
    MissionValidationError,
)
from mission_orchestrator.execution_running import (
    HEARTBEAT_STATUS,
    RUNNING_EXECUTION_ATTEMPT_STATUS,
    RUNNING_EXECUTION_AUTHORITY,
    RUNNING_EXECUTION_ID_PREFIX,
    RUNNING_EXECUTION_MODE,
    RUNNING_EXECUTION_SCHEMA_VERSION,
    RUNNING_EXECUTION_STATE,
    canonical_running_execution_definition,
    verify_running_execution_projection_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation import revalidation_request
from tests.test_stage3_5_5_dispatch_delivery_execution_acknowledgement import (
    FakeExecutionDeliveryClient,
    delivery_request,
    provision,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE356 = "stage3.5.6-running-execution-state-heartbeat-projection"
STAGE357 = "stage3.5.7-execution-result-evidence-artifact-capture"
STAGE355 = "stage3.5.5-dispatch-delivery-execution-acknowledgement"


class FakeRunningExecutionClient(FakeExecutionDeliveryClient):
    def __init__(self):
        super().__init__()
        self.status_calls = 0
        self.status_response = None
        self.raise_status = None
        self.started_at = "2026-09-15T01:00:00Z"
        self.next_sequence = 1

    def execution_status(self, subsystem_id, endpoint, *, mission_id, execution_attempt_id, dispatch_envelope_id):
        self.status_calls += 1
        if self.raise_status is not None:
            raise self.raise_status
        if self.status_response is not None:
            return self.status_response
        seq = self.next_sequence
        self.next_sequence += 1
        return {
            "status": "running",
            "mission_id": mission_id,
            "execution_attempt_id": execution_attempt_id,
            "dispatch_envelope_id": dispatch_envelope_id,
            "observed_by": subsystem_id,
            "execution_state": "RUNNING",
            "execution_started": True,
            "started_at": self.started_at,
            "target_actuation": False,
            "heartbeat": {
                "heartbeat_id": f"runtime-hb-{seq}",
                "sequence": seq,
                "observed_at": f"2026-09-15T01:00:{seq:02d}Z",
                "status": "alive",
            },
        }


def provision_running(tmp_path, key: str):
    service, governance, _, mission_id, active, dispatch, gate, reval, attempt = provision(tmp_path, key)
    runtime = FakeRunningExecutionClient()
    service.execution_delivery_client = runtime
    delivery = service.deliver_execution_attempt(
        mission_id, delivery_request(service, mission_id, active, attempt, key)
    )
    return service, governance, runtime, mission_id, active, dispatch, gate, reval, attempt, delivery


def running_request(service, mission_id: str, active: dict, attempt: dict, delivery: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage356-running-{key}",
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
        "projected_by": "stage3.5.6-pytest",
        "reason": "Observe downstream RUNNING state and persist append-only heartbeat projection",
        "metadata": {"stage": "3.5.6", "key": key},
    }
    body.update(overrides)
    return body


def test_01_health_activates_stage356_and_declares_observation_boundary(tmp_path):
    service, _ = __import__(
        "tests.test_stage3_5_4_idempotent_dispatch_execution_attempt_identity",
        fromlist=["make_service"],
    ).make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert (health if "health" in locals() else h)["supported_controls"][-1] == CONTROL
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["running_execution_schema_version"] == RUNNING_EXECUTION_SCHEMA_VERSION
    assert health["running_execution_mode"] == RUNNING_EXECUTION_MODE
    assert health["running_execution_authority"] == RUNNING_EXECUTION_AUTHORITY
    assert health["running_execution_database_migration_level"] == 32
    assert health["running_execution_persistence_store"] == "mission_execution_running_projections"
    assert "mission_execution_running_projections" in REPOSITORY_STORES
    assert health["running_execution_runtime_endpoint_resolution_performed"] is False
    assert health["running_execution_runtime_execution_state_query_performed"] is True
    assert health["running_execution_execution_started"] is True
    assert health["running_execution_running_state_recorded"] is True
    assert health["running_execution_heartbeat_recorded"] is True
    assert health["running_execution_target_actuation"] is False


def test_02_definition_requires_stage355_and_defers_post_running_to_357(tmp_path):
    service, _, _, mission_id, *_ = provision_running(tmp_path, "definition")
    definition = service.get_execution_running_projection_definition(mission_id)[
        "running_execution_state_heartbeat_projection_definition"
    ]
    assert definition == canonical_running_execution_definition()
    assert definition["requires_stage355_delivery_acknowledgement"] is True
    assert definition["append_only_heartbeat_projection"] is True
    assert definition["heartbeat_sequence_monotonic_per_attempt"] is True
    assert definition["execution_state"] == RUNNING_EXECUTION_STATE
    assert definition["execution_attempt_status"] == RUNNING_EXECUTION_ATTEMPT_STATUS
    assert definition["heartbeat_status"] == HEARTBEAT_STATUS
    assert definition["runtime_endpoint_reused_from_stage355"] is True
    assert definition["governance_query_performed"] is False
    assert definition["target_actuation"] is False
    assert definition["next_stage"] == "3.5.7"


def test_03_happy_path_projects_running_and_heartbeat_without_actuation(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "happy")
    result = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "happy")
    )
    assert result["running_projection_id"].startswith(RUNNING_EXECUTION_ID_PREFIX)
    assert result["execution_state"] == RUNNING_EXECUTION_STATE
    assert result["execution_attempt_status"] == RUNNING_EXECUTION_ATTEMPT_STATUS
    assert result["execution_started"] is True
    assert result["running_state_recorded"] is True
    assert result["heartbeat_recorded"] is True
    assert result["heartbeat_sequence"] == 1
    assert result["heartbeat_status"] == HEARTBEAT_STATUS
    assert result["target_actuation"] is False
    assert verify_running_execution_projection_contract(result["running_execution_projection_contract"])
    assert runtime.status_calls == 1


def test_04_stage356_reuses_persisted_runtime_endpoint_without_resolution_or_redelivery(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "endpoint")
    assert runtime.resolve_calls == 1 and runtime.deliver_calls == 1 and runtime.health_calls == 1
    result = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "endpoint")
    )
    assert runtime.resolve_calls == 1
    assert runtime.deliver_calls == 1
    assert runtime.health_calls == 2
    assert runtime.status_calls == 1
    assert result["runtime_endpoint"] == delivery["runtime_endpoint"]
    assert result["runtime_endpoint_resolution_performed"] is False
    assert result["dispatch_redelivery_performed"] is False


def test_05_stage356_performs_no_new_governance_query(tmp_path):
    service, governance, _, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "nogov")
    before = governance.evaluate_calls
    result = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "nogov")
    )
    assert governance.evaluate_calls == before
    assert result["governance_query_performed"] is False


def test_06_later_governance_deny_does_not_hide_already_running_observation(tmp_path):
    service, governance, _, mission_id, active, dispatch, gate, _, attempt, delivery = provision_running(tmp_path, "laterdeny")
    governance.emergency_stop = True
    deny = service.authorize_pre_dispatch_execution(
        mission_id,
        revalidation_request(service, mission_id, active, dispatch, gate, "stage356-laterdeny"),
    )
    assert deny["governance_decision"] == "DENY"
    result = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "laterdeny")
    )
    assert result["execution_state"] == "RUNNING"
    assert result["policy_decision_id"] == delivery["execution_delivery_contract"]["source_bindings"]["policy_decision_id"]
    assert result["governance_query_performed"] is False


def test_07_stale_state_and_version_vector_fail_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "stale")
    baseline = (runtime.health_calls, runtime.status_calls)
    body = running_request(service, mission_id, active, attempt, delivery, "stale-state")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict):
        service.project_running_execution_state(mission_id, body)
    assert (runtime.health_calls, runtime.status_calls) == baseline
    body = running_request(service, mission_id, active, attempt, delivery, "stale-vector")
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.project_running_execution_state(mission_id, body)
    assert (runtime.health_calls, runtime.status_calls) == baseline


def test_08_stale_plan_or_stage355_binding_fails_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "bindings")
    baseline = (runtime.health_calls, runtime.status_calls)
    body = running_request(service, mission_id, active, attempt, delivery, "plan")
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.project_running_execution_state(mission_id, body)
    body = running_request(service, mission_id, active, attempt, delivery, "delivery")
    body["expected_execution_delivery_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.project_running_execution_state(mission_id, body)
    assert (runtime.health_calls, runtime.status_calls) == baseline


def test_09_caller_cannot_inject_runtime_running_heartbeat_or_actuation_state(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "inject")
    baseline = (runtime.health_calls, runtime.status_calls)
    for field, value in [
        ("runtime_endpoint", "http://attacker"),
        ("execution_state", "RUNNING"),
        ("heartbeat", {"sequence": 999}),
        ("target_actuation", True),
    ]:
        body = running_request(service, mission_id, active, attempt, delivery, f"inject-{field}")
        body[field] = value
        with pytest.raises(MissionValidationError):
            service.project_running_execution_state(mission_id, body)
    assert (runtime.health_calls, runtime.status_calls) == baseline


def test_10_runtime_unavailable_or_protocol_invalid_is_fail_closed_without_projection(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "runtimefail")
    runtime.raise_health = MissionSubsystemUnavailable("runtime down")
    with pytest.raises(MissionSubsystemUnavailable):
        service.project_running_execution_state(
            mission_id, running_request(service, mission_id, active, attempt, delivery, "healthfail")
        )
    assert service.get_execution_running_projection_history(mission_id)["running_projection_count"] == 0
    runtime.raise_health = None
    runtime.status_response = {"status": "ok"}
    with pytest.raises(MissionSubsystemProtocolError):
        service.project_running_execution_state(
            mission_id, running_request(service, mission_id, active, attempt, delivery, "badstatus")
        )
    assert service.get_execution_running_projection_history(mission_id)["running_projection_count"] == 0


def test_11_runtime_binding_and_target_actuation_are_strict(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "strict")
    runtime.status_response = {
        "status": "running",
        "mission_id": mission_id,
        "execution_attempt_id": attempt["execution_attempt_id"],
        "dispatch_envelope_id": attempt["dispatch_envelope_id"],
        "observed_by": delivery["recipient_subsystem_id"],
        "execution_state": "RUNNING",
        "execution_started": True,
        "started_at": runtime.started_at,
        "target_actuation": True,
        "heartbeat": {"heartbeat_id": "hb-bad", "sequence": 1, "observed_at": "2026-09-15T01:00:01Z", "status": "alive"},
    }
    with pytest.raises(MissionSubsystemProtocolError, match="target_actuation"):
        service.project_running_execution_state(
            mission_id, running_request(service, mission_id, active, attempt, delivery, "strict")
        )


def test_12_exact_idempotent_replay_does_not_repeat_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "replay")
    body = running_request(service, mission_id, active, attempt, delivery, "replay")
    first = service.project_running_execution_state(mission_id, body)
    counts = (runtime.health_calls, runtime.status_calls)
    second = service.project_running_execution_state(mission_id, body)
    assert second["idempotent_replay"] is True
    assert second["running_projection_id"] == first["running_projection_id"]
    assert (runtime.health_calls, runtime.status_calls) == counts


def test_13_idempotency_key_reuse_with_different_request_is_conflict(tmp_path):
    service, _, _, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "idemconflict")
    body = running_request(service, mission_id, active, attempt, delivery, "idemconflict")
    service.project_running_execution_state(mission_id, body)
    changed = dict(body)
    changed["reason"] = "different request"
    with pytest.raises(MissionExecutionRunningProjectionConflict):
        service.project_running_execution_state(mission_id, changed)


def test_14_append_only_heartbeat_history_requires_monotonic_sequence(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "history")
    first = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "history-1")
    )
    second = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "history-2")
    )
    assert [first["heartbeat_sequence"], second["heartbeat_sequence"]] == [1, 2]
    history = service.get_execution_running_projection_history(mission_id)
    assert history["running_projection_count"] == 2
    assert [x["heartbeat_sequence"] for x in history["running_projections"]] == [1, 2]
    runtime.next_sequence = 2
    with pytest.raises(MissionExecutionRunningProjectionConflict, match="not newer"):
        service.project_running_execution_state(
            mission_id, running_request(service, mission_id, active, attempt, delivery, "history-stale")
        )
    assert service.get_execution_running_projection_history(mission_id)["running_projection_count"] == 2


def test_15_started_at_is_immutable_for_same_execution_attempt(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "startedat")
    service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "startedat-1")
    )
    runtime.started_at = "2026-09-15T02:00:00Z"
    with pytest.raises(MissionExecutionRunningProjectionGuardRejected, match="started_at changed"):
        service.project_running_execution_state(
            mission_id, running_request(service, mission_id, active, attempt, delivery, "startedat-2")
        )


def test_16_event_lineage_records_running_and_heartbeat_semantics(tmp_path):
    service, _, _, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "event")
    result = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "event")
    )
    event = service.repository.get_mission_event_by_causation(
        mission_id, "MISSION_EXECUTION_RUNNING_HEARTBEAT_PROJECTED", result["running_projection_id"]
    )
    assert event is not None
    payload = event["payload"]
    assert payload["canonical_sha256"] == result["canonical_sha256"]
    assert payload["execution_started"] is True
    assert payload["running_state_recorded"] is True
    assert payload["heartbeat_recorded"] is True
    assert payload["heartbeat_sequence"] == 1
    assert payload["dispatch_redelivery_performed"] is False
    assert payload["target_action_dispatch_performed"] is False
    assert payload["target_actuation"] is False


def test_17_repository_reconstruction_includes_projection_and_detects_tamper(tmp_path):
    service, _, _, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "repo")
    service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "repo")
    )
    view = service.get_mission_repository(mission_id)
    assert view["integrity_status"] == "PASS"
    assert view["record_counts"]["mission_execution_running_projections"] == 1
    assert len(view["persistence_manifest"]["running_execution_state_heartbeat_projection_store"]["projections"]) == 1

    db = service.repository.sqlite_path
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_execution_running_projections SET heartbeat_status='DEAD' WHERE mission_id=?",
            (mission_id,),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError, match="running_execution_state_heartbeat_projection_store"):
        service.get_mission_repository(mission_id)


def test_18_projection_survives_repository_restart(tmp_path):
    db = tmp_path / "restart.db"
    service, governance, _, mission_id, active, _, _, _, attempt, delivery = provision_running(tmp_path, "restart")
    # provision_running uses a key-specific database; reopen that actual durable source.
    db_path = service.repository.sqlite_path
    result = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, attempt, delivery, "restart")
    )
    restarted = CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=db_path),
        governance_client=governance,
        execution_delivery_client=FakeRunningExecutionClient(),
    )
    recovered = restarted.get_execution_running_projection(mission_id, result["running_projection_id"])
    assert recovered["running_projection_id"] == result["running_projection_id"]
    assert recovered["heartbeat_sequence"] == 1
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"
