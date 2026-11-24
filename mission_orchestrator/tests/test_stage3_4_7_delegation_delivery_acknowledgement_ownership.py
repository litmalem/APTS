from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.delegation_delivery import (
    ACKNOWLEDGEMENT_STATUS,
    DELIVERY_CHANNEL,
    DELIVERY_MODE,
    DELIVERY_RECEIPT_ID_PREFIX,
    DELIVERY_RECEIPT_SCHEMA_VERSION,
    DELIVERY_STATUS,
    OWNERSHIP_SCOPE,
    OWNERSHIP_STATUS,
    canonical_delivery_definition,
    verify_delivery_receipt_contract,
)
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionDelegationDeliveryConflict,
    MissionDelegationDeliveryGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_4_6_canonical_delegation_contract_handoff_envelope import (
    delegation_request,
    make_service,
    provision_authorized,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision_delegated(service, key: str):
    mission_id, active, route, authorization = provision_authorized(service, key)
    delegation = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization, key)
    )
    return mission_id, active, route, authorization, delegation


def delivery_request(service, mission_id, active, delegation, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    recipient = delegation["handoff_envelope"]["recipient"]
    body = {
        "idempotency_key": f"stage347-delivery-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_delegation_id": delegation["delegation_id"],
        "expected_delegation_sha256": delegation["canonical_sha256"],
        "expected_handoff_envelope_id": delegation["handoff_envelope_id"],
        "expected_handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
        "recipient_subsystem_id": recipient["subsystem_id"],
        "recipient_capability_id": recipient["capability_id"],
        "acknowledged_by": recipient["subsystem_id"],
        "ownership_accepted_by": recipient["subsystem_id"],
        "reason": "Deliver immutable handoff to canonical recipient and record ACK/ownership only",
        "metadata": {"stage": "3.4.7", "key": key},
    }
    body.update(overrides)
    return body


def test_health_activates_stage347_and_preserves_dispatch_execution_boundary(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][30:40] == [
        "stage3.4.1-canonical-subsystem-registry-capability-contract",
        "stage3.4.2-task-routing-intent-candidate-resolution",
        "stage3.4.3-routing-eligibility-compatibility-gate",
        "stage3.4.4-deterministic-route-selection-decision-record",
        "stage3.4.5-governance-bound-delegation-authorization",
        "stage3.4.6-canonical-delegation-contract-handoff-envelope",
        "stage3.4.7-delegation-delivery-acknowledgement-ownership",
        "stage3.4.8-retry-fallback-reassignment-conflict-control",
        "stage3.4.9-routing-delegation-event-lineage-replay-recovery",
        "stage3.4.10-routing-delegation-acceptance-regression-gate",
    ]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["delegation_delivery_schema_version"] == DELIVERY_RECEIPT_SCHEMA_VERSION
    assert health["delegation_delivery_mode"] == DELIVERY_MODE
    assert health["delegation_delivery_channel"] == DELIVERY_CHANNEL
    assert health["delegation_delivery_handoff_transmitted"] is True
    assert health["delegation_delivery_handoff_acknowledged"] is True
    assert health["delegation_delivery_ownership_accepted"] is True
    assert health["delegation_delivery_dispatch_performed"] is False
    assert health["delegation_delivery_execution_authorized"] is False
    assert health["delegation_delivery_governance_query_performed"] is False
    assert health["delegation_delivery_pre_dispatch_governance_revalidation_required"] is True
    assert health["delegation_delivery_persistence_store"] == "mission_delegation_deliveries"
    assert "mission_delegation_deliveries" in REPOSITORY_STORES


def test_definition_declares_control_plane_delivery_ack_and_ownership_only(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = provision_authorized(service, "definition347")
    result = service.get_delegation_delivery_definition(mission_id)
    definition = result["delegation_delivery_definition"]
    assert definition == canonical_delivery_definition()
    assert definition["requires_stage346_immutable_delegation"] is True
    assert definition["handoff_transmitted"] is True
    assert definition["handoff_acknowledged"] is True
    assert definition["ownership_accepted"] is True
    assert definition["ownership_scope"] == OWNERSHIP_SCOPE
    assert definition["dispatch_performed"] is False
    assert definition["execution_authorized"] is False
    assert definition["target_actuation"] is False


def test_delegation_delivery_materializes_immutable_ack_and_ownership_receipt_without_dispatch(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "happy347")
    governance_calls_before = gov.evaluate_calls
    result = service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "happy347")
    )
    assert result["delivery_receipt_id"].startswith(DELIVERY_RECEIPT_ID_PREFIX)
    assert result["delivery_status"] == DELIVERY_STATUS
    assert result["acknowledgement_status"] == ACKNOWLEDGEMENT_STATUS
    assert result["ownership_status"] == OWNERSHIP_STATUS
    assert result["handoff_transmitted"] is True
    assert result["handoff_acknowledged"] is True
    assert result["ownership_accepted"] is True
    assert result["dispatch_performed"] is False
    assert result["execution_authorized"] is False
    assert result["target_actuation"] is False
    assert result["governance_query_performed"] is False
    assert gov.evaluate_calls == governance_calls_before == 1
    assert verify_delivery_receipt_contract(result["delivery_receipt"])


def test_receipt_binds_exact_delegation_handoff_plan_and_canonical_recipient(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "bindings347")
    result = service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "bindings347")
    )
    receipt = result["delivery_receipt"]
    source = receipt["source_bindings"]
    delivery = receipt["delivery"]
    recipient = delegation["handoff_envelope"]["recipient"]
    assert source["delegation_sha256"] == delegation["canonical_sha256"]
    assert source["handoff_envelope_sha256"] == delegation["handoff_envelope_sha256"]
    assert source["active_plan_sha256"] == active["canonical_sha256"]
    assert delivery["recipient_subsystem_id"] == recipient["subsystem_id"]
    assert delivery["recipient_capability_id"] == recipient["capability_id"]
    assert delivery["runtime_endpoint"] is None
    assert delivery["external_network_io_performed"] is False
    assert receipt["ownership"]["execution_authority_transferred"] is False
    assert receipt["ownership"]["target_action_authority_transferred"] is False


def test_stage346_delegation_remains_immutable_after_stage347_receipt(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "immutable347")
    before = deepcopy(service.repository.get_task_delegation(mission_id, delegation["delegation_id"]))
    service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "immutable347")
    )
    after = service.repository.get_task_delegation(mission_id, delegation["delegation_id"])
    assert after["canonical_sha256"] == before["canonical_sha256"]
    assert after["handoff_envelope_sha256"] == before["handoff_envelope_sha256"]
    assert after["delegation_contract"] == before["delegation_contract"]


def test_exact_replay_is_idempotent_without_duplicate_event_or_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "replay347")
    req = delivery_request(service, mission_id, active, delegation, "replay347")
    first = service.deliver_task_delegation(mission_id, req)
    event_count = service.get_mission_events(mission_id)["event_count"]
    calls = gov.evaluate_calls
    second = service.deliver_task_delegation(mission_id, req)
    assert second["idempotent_replay"] is True
    assert second["delivery_receipt_id"] == first["delivery_receipt_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count
    assert gov.evaluate_calls == calls


def test_idempotency_key_reuse_with_different_request_is_conflict(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "idem347")
    req = delivery_request(service, mission_id, active, delegation, "idem347")
    service.deliver_task_delegation(mission_id, req)
    changed = deepcopy(req)
    changed["reason"] = "different"
    with pytest.raises(MissionDelegationDeliveryConflict, match="idempotency_key"):
        service.deliver_task_delegation(mission_id, changed)


@pytest.mark.parametrize("field,value", [
    ("runtime_endpoint", "http://127.0.0.1:9999"),
    ("worker_id", "worker-1"),
    ("dispatch", True),
    ("execution_authorized", True),
    ("target_action", {"kind": "scan"}),
])
def test_request_rejects_runtime_dispatch_execution_and_target_action_fields(tmp_path, field, value):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, f"forbid-{field}")
    req = delivery_request(service, mission_id, active, delegation, f"forbid-{field}")
    req[field] = value
    with pytest.raises(MissionValidationError, match="unsupported delegation delivery field"):
        service.deliver_task_delegation(mission_id, req)


def test_wrong_recipient_or_ack_actor_fails_closed(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "recipient347")
    req = delivery_request(service, mission_id, active, delegation, "recipient347")
    wrong = deepcopy(req)
    wrong["recipient_subsystem_id"] = "APTS-OTHER"
    with pytest.raises(MissionDelegationDeliveryGuardRejected, match="recipient_subsystem_id"):
        service.deliver_task_delegation(mission_id, wrong)
    wrong = deepcopy(req)
    wrong["acknowledged_by"] = "APTS-OTHER"
    with pytest.raises(MissionDelegationDeliveryGuardRejected, match="acknowledged_by"):
        service.deliver_task_delegation(mission_id, wrong)


def test_stale_expected_hashes_and_state_version_fail_closed(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "stale347")
    req = delivery_request(service, mission_id, active, delegation, "stale347")
    bad = deepcopy(req)
    bad["expected_delegation_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="expected_delegation_sha256"):
        service.deliver_task_delegation(mission_id, bad)
    bad = deepcopy(req)
    bad["expected_state_version"] += 1
    with pytest.raises(MissionConcurrencyConflict, match="expected_state_version"):
        service.deliver_task_delegation(mission_id, bad)


def test_one_stage346_delegation_can_have_only_one_immutable_stage347_receipt(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "single347")
    service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "single347-a")
    )
    with pytest.raises(MissionDelegationDeliveryConflict, match="already has an immutable"):
        service.deliver_task_delegation(
            mission_id, delivery_request(service, mission_id, active, delegation, "single347-b")
        )


def test_event_lineage_records_delivery_ack_ownership_not_dispatch_or_execution(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "event347")
    result = service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "event347")
    )
    event = service.repository.get_mission_event_by_causation(
        mission_id, "MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED", result["delivery_receipt_id"]
    )
    assert event is not None
    payload = event["payload"]
    assert payload["delegation_id"] == delegation["delegation_id"]
    assert payload["handoff_transmitted"] is True
    assert payload["handoff_acknowledged"] is True
    assert payload["ownership_accepted"] is True
    assert payload["dispatch_performed"] is False
    assert payload["execution_authorized"] is False
    assert payload["target_action_dispatch_enabled"] is False
    assert payload["target_actuation"] is False


def test_restart_reads_same_delivery_receipt_from_durable_repository(tmp_path):
    db = tmp_path / "m.db"
    service, gov = make_service(db)
    mission_id, active, _, _, delegation = provision_delegated(service, "restart347")
    created = service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "restart347")
    )
    restarted, _ = make_service(db, gov)
    loaded = restarted.get_delegation_delivery(mission_id, created["delivery_receipt_id"])
    assert loaded["canonical_sha256"] == created["canonical_sha256"]
    assert loaded["delegation_sha256"] == created["delegation_sha256"]
    assert loaded["delivery_receipt"] == created["delivery_receipt"]


def test_repository_manifest_includes_stage347_store_and_integrity_pass(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, _, _, delegation = provision_delegated(service, "repository347")
    service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "repository347")
    )
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_delegation_deliveries"] == 1
    assert len(repo["persistence_manifest"]["delegation_delivery_store"]["deliveries"]) == 1
    checks = {x["check"]: x["status"] for x in repo["integrity_checks"]}
    assert checks["delegation_delivery_acknowledgement_ownership_store"] == "PASS"


def test_repository_integrity_detects_stage347_receipt_corruption(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, active, _, _, delegation = provision_delegated(service, "corrupt347")
    created = service.deliver_task_delegation(
        mission_id, delivery_request(service, mission_id, active, delegation, "corrupt347")
    )
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT canonical_json FROM mission_delegation_deliveries WHERE delivery_receipt_id=?",
            (created["delivery_receipt_id"],),
        ).fetchone()
        contract = json.loads(row[0])
        contract["ownership"]["ownership_status"] = "CORRUPTED"
        conn.execute(
            "UPDATE mission_delegation_deliveries SET canonical_json=? WHERE delivery_receipt_id=?",
            (json.dumps(contract, separators=(",", ":"), sort_keys=True), created["delivery_receipt_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="delegation_delivery_acknowledgement_ownership_store"):
        service.get_mission_repository(mission_id)
