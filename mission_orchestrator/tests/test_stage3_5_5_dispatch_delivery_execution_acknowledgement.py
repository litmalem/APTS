from __future__ import annotations

import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionExecutionDeliveryConflict,
    MissionExecutionDeliveryGuardRejected,
    MissionExecutionDeliveryNotFound,
    MissionRepositoryIntegrityError,
    MissionSubsystemProtocolError,
    MissionSubsystemUnavailable,
    MissionValidationError,
)
from mission_orchestrator.execution_delivery import (
    ACKNOWLEDGED_ATTEMPT_STATUS,
    ACKNOWLEDGEMENT_STATUS,
    DELIVERY_CHANNEL,
    DELIVERY_STATUS,
    EXECUTION_DELIVERY_AUTHORITY,
    EXECUTION_DELIVERY_ID_PREFIX,
    EXECUTION_DELIVERY_MODE,
    EXECUTION_DELIVERY_SCHEMA_VERSION,
    canonical_execution_delivery_definition,
    verify_execution_delivery_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation import revalidation_request
from tests.test_stage3_5_4_idempotent_dispatch_execution_attempt_identity import committed, make_service

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE354 = "stage3.5.4-idempotent-dispatch-execution-attempt-identity"
STAGE355 = "stage3.5.5-dispatch-delivery-execution-acknowledgement"


class FakeExecutionDeliveryClient:
    def __init__(self):
        self.resolve_calls = 0
        self.health_calls = 0
        self.deliver_calls = 0
        self.payloads = []
        self.health_response = None
        self.ack_response = None
        self.raise_health = None
        self.raise_delivery = None

    def resolve_endpoint(self, subsystem_id: str) -> str:
        self.resolve_calls += 1
        return f"http://runtime/{subsystem_id.lower()}"

    def health(self, subsystem_id: str, endpoint: str):
        self.health_calls += 1
        if self.raise_health is not None:
            raise self.raise_health
        return self.health_response or {
            "status": "ok",
            "subsystem_id": subsystem_id,
            "component_id": f"{subsystem_id}-RUNTIME",
            "control_version": "runtime-test-v1",
        }

    def deliver(self, subsystem_id: str, endpoint: str, payload: dict):
        self.deliver_calls += 1
        self.payloads.append(payload)
        if self.raise_delivery is not None:
            raise self.raise_delivery
        if self.ack_response is not None:
            return self.ack_response
        return {
            "status": "accepted",
            "mission_id": payload["mission_id"],
            "execution_attempt_id": payload["execution_attempt_id"],
            "dispatch_envelope_id": payload["dispatch_envelope_id"],
            "acknowledgement_id": f"remote-ack-{self.deliver_calls}",
            "acknowledgement_status": ACKNOWLEDGEMENT_STATUS,
            "acknowledged_by": subsystem_id,
            "execution_started": False,
            "target_actuation": False,
        }


def provision(tmp_path, key: str):
    service, governance = make_service(tmp_path / f"{key}.db")
    runtime = FakeExecutionDeliveryClient()
    service.execution_delivery_client = runtime
    mission_id, active, route, authorization, delegation, delivery, dispatch, gate, reval, attempt_body, attempt = committed(service, key)
    return service, governance, runtime, mission_id, active, dispatch, gate, reval, attempt


def delivery_request(service, mission_id: str, active: dict, attempt: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage355-delivery-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_execution_attempt_id": attempt["execution_attempt_id"],
        "expected_execution_attempt_sha256": attempt["canonical_sha256"],
        "expected_dispatch_envelope_id": attempt["dispatch_envelope_id"],
        "delivered_by": "stage3.5.5-pytest",
        "reason": "Deliver immutable dispatch envelope to runtime intake and persist acknowledgement",
        "metadata": {"stage": "3.5.5", "key": key},
    }
    body.update(overrides)
    return body


def test_01_health_activates_stage355_and_declares_delivery_boundary(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][43:50] == [STAGE354, STAGE355, "stage3.5.6-running-execution-state-heartbeat-projection", "stage3.5.7-execution-result-evidence-artifact-capture", "stage3.5.8-timeout-cancellation-abort-failure-propagation", "stage3.5.9-execution-event-lineage-replay-recovery", "stage3.5.10-execution-dispatch-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["execution_delivery_schema_version"] == EXECUTION_DELIVERY_SCHEMA_VERSION
    assert health["execution_delivery_mode"] == EXECUTION_DELIVERY_MODE
    assert health["execution_delivery_authority"] == EXECUTION_DELIVERY_AUTHORITY
    assert health["execution_delivery_database_migration_level"] == 31
    assert health["execution_delivery_persistence_store"] == "mission_execution_deliveries"
    assert "mission_execution_deliveries" in REPOSITORY_STORES
    assert health["execution_delivery_target_delivery_performed"] is True
    assert health["execution_delivery_acknowledgement_performed"] is True
    assert health["execution_delivery_execution_started"] is False
    assert health["execution_delivery_running_state_recorded"] is False
    assert health["execution_delivery_target_actuation"] is False


def test_02_definition_delivers_and_acknowledges_but_defers_running_to_356(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "definition")
    definition = service.get_execution_delivery_definition(mission_id)["dispatch_delivery_execution_acknowledgement_definition"]
    assert definition == canonical_execution_delivery_definition()
    assert definition["requires_stage354_committed_execution_attempt"] is True
    assert definition["requires_current_latest_stage353_allow"] is True
    assert definition["target_delivery_performed"] is True
    assert definition["delivery_acknowledgement_performed"] is True
    assert definition["execution_start_acknowledged"] is True
    assert definition["execution_started"] is False
    assert definition["running_state_recorded"] is False
    assert definition["heartbeat_recorded"] is False
    assert definition["target_actuation"] is False
    assert definition["next_stage"] == "3.5.6"


def test_03_happy_path_delivers_envelope_and_persists_ack_without_running(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "happy")
    result = service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "happy"))
    assert result["execution_delivery_id"].startswith(EXECUTION_DELIVERY_ID_PREFIX)
    assert result["delivery_status"] == DELIVERY_STATUS
    assert result["acknowledgement_status"] == ACKNOWLEDGEMENT_STATUS
    assert result["execution_attempt_status"] == ACKNOWLEDGED_ATTEMPT_STATUS
    assert result["target_delivery_performed"] is True
    assert result["delivery_acknowledgement_performed"] is True
    assert result["execution_start_acknowledged"] is True
    assert result["execution_started"] is False
    assert result["running_state_recorded"] is False
    assert result["heartbeat_recorded"] is False
    assert result["target_actuation"] is False
    assert verify_execution_delivery_contract(result["execution_delivery_contract"])
    assert runtime.resolve_calls == runtime.health_calls == runtime.deliver_calls == 1


def test_04_runtime_payload_uses_xenv_as_remote_idempotency_and_exact_authority(tmp_path):
    service, _, runtime, mission_id, active, _, _, reval, attempt = provision(tmp_path, "payload")
    service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "payload"))
    payload = runtime.payloads[0]
    assert payload["idempotency_key"] == attempt["dispatch_envelope_id"]
    assert payload["execution_attempt_id"] == attempt["execution_attempt_id"]
    assert payload["dispatch_envelope_id"] == attempt["dispatch_envelope_id"]
    assert payload["authorization"]["pre_dispatch_revalidation_id"] == reval["pre_dispatch_revalidation_id"]
    assert payload["authorization"]["policy_decision_id"] == reval["policy_decision_id"]
    assert payload["authorization"]["policy_decision_hash"] == reval["policy_decision_hash"]
    assert payload["authorization"]["execution_authorized"] is True
    assert payload["semantics"]["execution_start_is_separate"] is True
    assert payload["semantics"]["target_actuation_requested"] is False


def test_05_delivery_reuses_governance_evidence_without_new_query(tmp_path):
    service, governance, _, mission_id, active, _, _, _, attempt = provision(tmp_path, "nogov")
    before = governance.evaluate_calls
    result = service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "nogov"))
    assert result["governance_query_performed"] is False
    assert governance.evaluate_calls == before


def test_06_newer_deny_invalidates_committed_attempt_before_runtime_io(tmp_path):
    service, governance, runtime, mission_id, active, dispatch, gate, _, attempt = provision(tmp_path, "deny")
    governance.emergency_stop = True
    deny = service.authorize_pre_dispatch_execution(
        mission_id,
        revalidation_request(service, mission_id, active, dispatch, gate, "deny-newer"),
    )
    assert deny["governance_decision"] == "DENY"
    with pytest.raises(MissionExecutionDeliveryGuardRejected, match="latest"):
        service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "deny"))
    assert runtime.resolve_calls == runtime.health_calls == runtime.deliver_calls == 0


def test_07_stale_state_version_fails_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "stalestate")
    body = delivery_request(service, mission_id, active, attempt, "stalestate")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict):
        service.deliver_execution_attempt(mission_id, body)
    assert runtime.resolve_calls == 0


def test_08_stale_version_vector_fails_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "stalevector")
    body = delivery_request(service, mission_id, active, attempt, "stalevector")
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.deliver_execution_attempt(mission_id, body)
    assert runtime.resolve_calls == 0


def test_09_stale_active_plan_hash_fails_before_runtime_io(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "staleplan")
    body = delivery_request(service, mission_id, active, attempt, "staleplan")
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.deliver_execution_attempt(mission_id, body)
    assert runtime.resolve_calls == 0


def test_10_unknown_or_mismatched_attempt_identity_is_fail_closed(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "attemptid")
    body = delivery_request(service, mission_id, active, attempt, "attemptid")
    body["expected_execution_attempt_id"] = "xattempt-00000000-0000-0000-0000-000000000000"
    with pytest.raises(Exception):
        service.deliver_execution_attempt(mission_id, body)
    assert runtime.resolve_calls == 0
    body = delivery_request(service, mission_id, active, attempt, "attemptsha")
    body["expected_execution_attempt_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.deliver_execution_attempt(mission_id, body)
    assert runtime.resolve_calls == 0


def test_11_wrong_dispatch_envelope_identity_is_fail_closed(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "envelope")
    body = delivery_request(service, mission_id, active, attempt, "envelope")
    body["expected_dispatch_envelope_id"] = "xenv-00000000-0000-0000-0000-000000000000"
    with pytest.raises(MissionExecutionDeliveryGuardRejected):
        service.deliver_execution_attempt(mission_id, body)
    assert runtime.resolve_calls == 0


def test_12_caller_cannot_supply_runtime_ack_execution_or_actuation_fields(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "forbidden")
    for field, value in [
        ("runtime_endpoint", "http://evil"),
        ("acknowledgement_id", "forged"),
        ("execution_started", True),
        ("target_actuation", True),
    ]:
        body = delivery_request(service, mission_id, active, attempt, f"forbidden-{field}")
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported execution delivery field"):
            service.deliver_execution_attempt(mission_id, body)
    assert runtime.resolve_calls == 0


def test_13_unhealthy_runtime_is_fail_closed_and_persists_no_delivery(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "unhealthy")
    runtime.health_response = {"status": "down", "subsystem_id": "CTI"}
    with pytest.raises(MissionSubsystemUnavailable):
        service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "unhealthy"))
    assert runtime.resolve_calls == 1 and runtime.health_calls == 1 and runtime.deliver_calls == 0
    assert service.repository.list_execution_deliveries(mission_id) == []


def test_14_mismatched_ack_is_fail_closed_and_persists_no_delivery(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "badack")
    runtime.ack_response = {
        "status": "accepted",
        "mission_id": mission_id,
        "execution_attempt_id": attempt["execution_attempt_id"],
        "dispatch_envelope_id": attempt["dispatch_envelope_id"],
        "acknowledgement_id": "bad-ack",
        "acknowledgement_status": ACKNOWLEDGEMENT_STATUS,
        "acknowledged_by": "WRONG",
        "execution_started": False,
        "target_actuation": False,
    }
    with pytest.raises(MissionSubsystemProtocolError):
        service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "badack"))
    assert runtime.deliver_calls == 1
    assert service.repository.list_execution_deliveries(mission_id) == []


def test_15_exact_local_replay_returns_same_xack_without_redelivery(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "replay")
    body = delivery_request(service, mission_id, active, attempt, "replay")
    first = service.deliver_execution_attempt(mission_id, body)
    second = service.deliver_execution_attempt(mission_id, body)
    assert second["idempotent_replay"] is True
    assert second["execution_delivery_id"] == first["execution_delivery_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]
    assert runtime.deliver_calls == 1


def test_16_idempotency_conflict_and_second_delivery_for_same_attempt_are_rejected(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt = provision(tmp_path, "conflict")
    body = delivery_request(service, mission_id, active, attempt, "conflict")
    service.deliver_execution_attempt(mission_id, body)
    changed = dict(body)
    changed["reason"] = "different canonical request"
    with pytest.raises(MissionExecutionDeliveryConflict):
        service.deliver_execution_attempt(mission_id, changed)
    second_key = delivery_request(service, mission_id, active, attempt, "conflict-2")
    with pytest.raises(MissionExecutionDeliveryConflict, match="already has"):
        service.deliver_execution_attempt(mission_id, second_key)
    assert runtime.deliver_calls == 1


def test_17_event_lineage_records_delivery_ack_but_not_running_or_actuation(tmp_path):
    service, _, _, mission_id, active, _, _, _, attempt = provision(tmp_path, "event")
    result = service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "event"))
    event = service.repository.get_mission_event_by_causation(
        mission_id, "MISSION_EXECUTION_DISPATCH_DELIVERED_ACKNOWLEDGED", result["execution_delivery_id"]
    )
    assert event is not None
    payload = event["payload"]
    assert payload["target_delivery_performed"] is True
    assert payload["delivery_acknowledgement_performed"] is True
    assert payload["execution_start_acknowledged"] is True
    assert payload["execution_started"] is False
    assert payload["running_state_recorded"] is False
    assert payload["heartbeat_recorded"] is False
    assert payload["target_actuation"] is False


def test_18_repository_projection_detects_delivery_tamper_and_history_survives_restart(tmp_path):
    db = tmp_path / "durable.db"
    service, governance = make_service(db)
    runtime = FakeExecutionDeliveryClient()
    service.execution_delivery_client = runtime
    mission_id, active, *_, attempt = committed(service, "durable")
    result = service.deliver_execution_attempt(mission_id, delivery_request(service, mission_id, active, attempt, "durable"))
    projection = service.get_mission_repository(mission_id)
    assert projection["integrity_status"] == "PASS"
    assert projection["record_counts"]["mission_execution_deliveries"] == 1
    assert projection["persistence_manifest"]["dispatch_delivery_execution_acknowledgement_store"]["deliveries"][0]["execution_delivery_id"] == result["execution_delivery_id"]

    restarted = CanonicalMissionService(MissionRepository(sqlite_path=str(db)), governance_client=governance, execution_delivery_client=FakeExecutionDeliveryClient())
    history = restarted.get_execution_delivery_history(mission_id)
    assert history["execution_delivery_count"] == 1
    assert history["execution_deliveries"][0]["execution_delivery_id"] == result["execution_delivery_id"]

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_execution_deliveries SET canonical_sha256 = ? WHERE execution_delivery_id = ?",
            ("0" * 64, result["execution_delivery_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError, match="dispatch_delivery_execution_acknowledgement_store"):
        restarted.get_mission_repository(mission_id)


def test_19_get_unknown_execution_delivery_is_not_found(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "notfound")
    with pytest.raises(MissionExecutionDeliveryNotFound):
        service.get_execution_delivery(mission_id, "xack-00000000-0000-0000-0000-000000000000")
