from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionRoutingDelegationRecoveryConflict,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.routing_delegation_lineage import (
    ROUTING_DELEGATION_EVENT_LINEAGE_MODE,
    ROUTING_DELEGATION_EVENT_LINEAGE_SCHEMA_VERSION,
    ROUTING_DELEGATION_EVENT_REPLAY_SCHEMA_VERSION,
    ROUTING_DELEGATION_RECOVERY_CHECKPOINT_ID_PREFIX,
    ROUTING_DELEGATION_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
    ROUTING_DELEGATION_RECOVERY_EVENT_TYPE,
    ROUTING_DELEGATION_RECOVERY_MODE,
    ROUTING_DELEGATION_REPLAY_MODE,
    canonical_routing_delegation_event_lineage_definition,
    verify_routing_delegation_recovery_checkpoint_contract,
)
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_4_8_retry_fallback_reassignment_conflict_control import (
    make_service,
    provision_owned,
    recovery_request,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def checkpoint_request(service, mission_id, route, delegation, delivery, key, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    lineage = service.get_routing_delegation_event_lineage(mission_id)
    controls = service.repository.list_delegation_recovery_controls(mission_id, delivery["delivery_receipt_id"])
    body = {
        "idempotency_key": f"stage349-checkpoint-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_delivery_receipt_id": delivery["delivery_receipt_id"],
        "expected_delivery_receipt_sha256": delivery["canonical_sha256"],
        "expected_delegation_id": delegation["delegation_id"],
        "expected_delegation_sha256": delegation["canonical_sha256"],
        "expected_route_decision_id": route["route_decision_id"],
        "expected_route_decision_sha256": route["canonical_sha256"],
        "expected_recovery_control_count": len(controls),
        "expected_routing_delegation_event_count": lineage["routing_delegation_event_count"],
        "expected_routing_delegation_event_tip_sha256": lineage["routing_delegation_event_tip_sha256"],
        "created_by": "APTS-MO01",
        "reason": "Stage 3.4.9 durable routing/delegation recovery snapshot only",
        "metadata": {"stage": "3.4.9", "key": key},
    }
    body.update(overrides)
    return body


def test_health_activates_stage349_and_preserves_all_authority_boundaries(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][38:40] == [
        "stage3.4.9-routing-delegation-event-lineage-replay-recovery",
        "stage3.4.10-routing-delegation-acceptance-regression-gate",
    ]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["routing_delegation_event_lineage_schema_version"] == ROUTING_DELEGATION_EVENT_LINEAGE_SCHEMA_VERSION
    assert health["routing_delegation_event_replay_schema_version"] == ROUTING_DELEGATION_EVENT_REPLAY_SCHEMA_VERSION
    assert health["routing_delegation_recovery_checkpoint_schema_version"] == ROUTING_DELEGATION_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert health["routing_delegation_event_lineage_mode"] == ROUTING_DELEGATION_EVENT_LINEAGE_MODE
    assert health["routing_delegation_event_replay_mode"] == ROUTING_DELEGATION_REPLAY_MODE
    assert health["routing_delegation_recovery_mode"] == ROUTING_DELEGATION_RECOVERY_MODE
    assert health["routing_delegation_replay_read_only"] is True
    assert health["routing_delegation_replay_is_execution"] is False
    assert health["routing_delegation_recovery_is_authorization"] is False
    assert health["routing_delegation_recovery_is_routing"] is False
    assert health["routing_delegation_recovery_is_redelivery"] is False
    assert health["routing_delegation_recovery_is_ownership_transfer"] is False
    assert health["routing_delegation_recovery_dispatch_performed"] is False
    assert health["routing_delegation_recovery_execution_authorized"] is False
    assert health["routing_delegation_recovery_target_actuation"] is False
    assert health["routing_delegation_recovery_persistence_store"] == "mission_routing_delegation_recovery_checkpoints"
    assert "mission_routing_delegation_recovery_checkpoints" in REPOSITORY_STORES


def test_definition_exposes_canonical_stage342_through_stage348_recovery_chain(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = provision_owned(service, "definition349")
    result = service.get_routing_delegation_event_lineage_definition(mission_id)
    definition = result["routing_delegation_event_lineage_definition"]
    assert definition == canonical_routing_delegation_event_lineage_definition()
    assert definition["canonical_chain"] == [
        "ROUTING_INTENT",
        "ELIGIBILITY_GATE",
        "ROUTE_DECISION",
        "GOVERNANCE_BOUND_DELEGATION_AUTHORIZATION",
        "DELEGATION_AND_HANDOFF",
        "DELIVERY_ACKNOWLEDGEMENT_OWNERSHIP",
        "ZERO_OR_MORE_RECOVERY_CONTROLS",
    ]
    assert definition["replay_read_only"] is True
    assert definition["recovery_checkpoint_is_authorization"] is False
    assert definition["recovery_checkpoint_is_routing"] is False
    assert definition["recovery_checkpoint_is_redelivery"] is False
    assert definition["recovery_checkpoint_is_ownership_transfer"] is False


def test_lineage_filters_exact_routing_delegation_event_family_in_causal_order(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = provision_owned(service, "lineage349")
    result = service.get_routing_delegation_event_lineage(mission_id)
    types = [x["event_type"] for x in result["routing_delegation_events"]]
    assert types == [
        "MISSION_TASK_ROUTING_CANDIDATES_RESOLVED",
        "MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED",
        "MISSION_TASK_ROUTE_DECISION_RECORDED",
        "MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED",
        "MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED",
        "MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED",
    ]
    assert result["routing_delegation_event_count"] == 6
    assert result["integrity_status"] == "PASS"
    assert result["full_mission_event_chain_verified"] is True


def test_replay_is_deterministic_read_only_and_does_not_append_mission_event(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, *_ = provision_owned(service, "replay349")
    before = service.get_mission_events(mission_id)["event_count"]
    first = service.get_routing_delegation_event_replay(mission_id)
    second = service.get_routing_delegation_event_replay(mission_id)
    after = service.get_mission_events(mission_id)["event_count"]
    assert first["replay"] == second["replay"]
    assert first["replay"]["read_only"] is True
    assert first["replay"]["side_effects_performed"] is False
    assert first["replay_is_execution"] is False
    assert first["dispatch_performed"] is False
    assert first["execution_authorized"] is False
    assert before == after


def test_checkpoint_materializes_durable_recovery_state_without_recovery_controls(tmp_path):
    service, gov = make_service(tmp_path / "m.db")
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "checkpoint349")
    calls_before = gov.evaluate_calls
    result = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "zero")
    )
    assert result["checkpoint_id"].startswith(ROUTING_DELEGATION_RECOVERY_CHECKPOINT_ID_PREFIX)
    assert result["checkpoint_version"] == 1
    assert result["recovery_control_count"] == 0
    assert result["recovery_state"]["current_owner"]["subsystem_id"] == delivery["recipient_subsystem"]
    assert result["recovery_state"]["current_owner"]["capability_id"] == delivery["recipient_capability"]
    assert verify_routing_delegation_recovery_checkpoint_contract(result["recovery_checkpoint"])
    assert result["replay_is_execution"] is False
    assert result["recovery_is_authorization"] is False
    assert result["recovery_is_routing"] is False
    assert result["recovery_is_redelivery"] is False
    assert result["recovery_is_ownership_transfer"] is False
    assert result["dispatch_performed"] is False
    assert result["execution_authorized"] is False
    assert gov.evaluate_calls == calls_before == 1


def test_checkpoint_includes_stage348_recovery_control_chain_and_tip(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "control349")
    control = service.control_task_delegation_recovery(
        mission_id, recovery_request(service, mission_id, active, route, delegation, delivery, "control349")
    )
    result = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "with-control")
    )
    source = result["recovery_checkpoint"]["source_bindings"]
    assert result["recovery_control_count"] == 1
    assert result["recovery_state"]["latest_recovery_control"]["recovery_control_id"] == control["recovery_control_id"]
    assert source["recovery_control_tip_id"] == control["recovery_control_id"]
    assert source["recovery_control_tip_sha256"] == control["canonical_sha256"]


def test_exact_idempotent_checkpoint_replay_does_not_duplicate_store_or_event(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "idem349")
    req = checkpoint_request(service, mission_id, route, delegation, delivery, "idem")
    first = service.create_routing_delegation_recovery_checkpoint(mission_id, req)
    event_count = service.get_mission_events(mission_id)["event_count"]
    second = service.create_routing_delegation_recovery_checkpoint(mission_id, deepcopy(req))
    assert second["idempotent_replay"] is True
    assert second["checkpoint_id"] == first["checkpoint_id"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count
    assert len(service.repository.list_routing_delegation_recovery_checkpoints(mission_id)) == 1


def test_new_idempotency_key_for_same_snapshot_is_rejected(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "snapshot349")
    service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "first")
    )
    with pytest.raises(MissionRoutingDelegationRecoveryConflict):
        service.create_routing_delegation_recovery_checkpoint(
            mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "second")
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_delivery_receipt_sha256", "0" * 64),
        ("expected_delegation_sha256", "1" * 64),
        ("expected_route_decision_sha256", "2" * 64),
        ("expected_recovery_control_count", 99),
        ("expected_routing_delegation_event_count", 99),
        ("expected_routing_delegation_event_tip_sha256", "3" * 64),
    ],
)
def test_stale_snapshot_guards_fail_closed(tmp_path, field, value):
    service, _ = make_service(tmp_path / f"{field}.db")
    mission_id, _, route, _, delegation, delivery = provision_owned(service, f"stale-{field}")
    req = checkpoint_request(service, mission_id, route, delegation, delivery, field)
    req[field] = value
    with pytest.raises(MissionConcurrencyConflict):
        service.create_routing_delegation_recovery_checkpoint(mission_id, req)


def test_caller_supplied_route_authorization_or_execution_material_is_forbidden(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "forbidden349")
    for field in ("route_candidates", "authorization_decision", "ownership", "dispatch", "execution"):
        req = checkpoint_request(service, mission_id, route, delegation, delivery, f"forbidden-{field}")
        req[field] = {"malicious": True}
        with pytest.raises(MissionValidationError):
            service.create_routing_delegation_recovery_checkpoint(mission_id, req)


def test_checkpoint_event_is_append_only_and_extends_lineage_without_execution_semantics(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "event349")
    before = service.get_routing_delegation_event_lineage(mission_id)
    result = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "event")
    )
    after = service.get_routing_delegation_event_lineage(mission_id)
    assert after["routing_delegation_event_count"] == before["routing_delegation_event_count"] + 1
    assert after["routing_delegation_events"][-1]["event_type"] == ROUTING_DELEGATION_RECOVERY_EVENT_TYPE
    event = result["checkpoint_event"]
    assert event["event_type"] == ROUTING_DELEGATION_RECOVERY_EVENT_TYPE
    payload = event["payload"]
    assert payload["replay_is_execution"] is False
    assert payload["recovery_is_authorization"] is False
    assert payload["recovery_is_routing"] is False
    assert payload["recovery_is_redelivery"] is False
    assert payload["recovery_is_ownership_transfer"] is False
    assert payload["dispatch_performed"] is False
    assert payload["execution_authorized"] is False


def test_recovery_survives_service_restart_and_performs_no_external_governance_query(tmp_path):
    db = tmp_path / "m.db"
    service, gov = make_service(db)
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "restart349")
    calls_before = gov.evaluate_calls
    created = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "restart")
    )
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=str(db)), governance_client=gov)
    recovered = restarted.recover_routing_delegation_state(mission_id)
    assert recovered["checkpoint_id"] == created["checkpoint_id"]
    assert recovered["reconstructed_from_durable_repository"] is True
    assert recovered["external_network_io_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert recovered["replay_is_execution"] is False
    assert recovered["dispatch_performed"] is False
    assert recovered["execution_authorized"] is False
    assert gov.evaluate_calls == calls_before


def test_new_checkpoint_allowed_only_after_stage348_control_chain_advances(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, active, route, _, delegation, delivery = provision_owned(service, "advance349")
    first = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "before-control")
    )
    service.control_task_delegation_recovery(
        mission_id, recovery_request(service, mission_id, active, route, delegation, delivery, "advance349")
    )
    second = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "after-control")
    )
    assert first["checkpoint_version"] == 1
    assert second["checkpoint_version"] == 2
    assert first["recovery_control_count"] == 0
    assert second["recovery_control_count"] == 1
    assert len(service.repository.list_routing_delegation_recovery_checkpoints(mission_id)) == 2


def test_repository_manifest_and_integrity_include_stage349_store(tmp_path):
    service, _ = make_service(tmp_path / "m.db")
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "repo349")
    service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "repo")
    )
    repository = service.get_mission_repository(mission_id)
    assert repository["integrity_status"] == "PASS"
    checks = {x["check"]: x["status"] for x in repository["integrity_checks"]}
    assert checks["routing_delegation_event_lineage_replay_recovery_store"] == "PASS"
    assert repository["record_counts"]["mission_routing_delegation_recovery_checkpoints"] == 1
    manifest = repository["persistence_manifest"]
    assert len(manifest["routing_delegation_recovery_checkpoint_store"]["checkpoints"]) == 1


def test_tampered_stage349_checkpoint_contract_fails_repository_integrity(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "tamper349")
    result = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "tamper")
    )
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT canonical_json FROM mission_routing_delegation_recovery_checkpoints WHERE checkpoint_id=?",
            (result["checkpoint_id"],),
        ).fetchone()
        contract = json.loads(row[0])
        contract["recovery_state"]["ownership_status"] = "CORRUPTED"
        conn.execute(
            "UPDATE mission_routing_delegation_recovery_checkpoints SET canonical_json=? WHERE checkpoint_id=?",
            (json.dumps(contract, separators=(",", ":"), sort_keys=True), result["checkpoint_id"]),
        )
    with pytest.raises(MissionRepositoryIntegrityError, match="routing_delegation_event_lineage_replay_recovery_store"):
        service.get_mission_repository(mission_id)


def test_tampered_checkpoint_event_fails_mission_event_chain(tmp_path):
    db = tmp_path / "m.db"
    service, _ = make_service(db)
    mission_id, _, route, _, delegation, delivery = provision_owned(service, "tamper-event349")
    created = service.create_routing_delegation_recovery_checkpoint(
        mission_id, checkpoint_request(service, mission_id, route, delegation, delivery, "tamper-event")
    )
    event_id = created["checkpoint_event"]["event_id"]
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT payload_json FROM mission_events WHERE event_id=?", (event_id,)).fetchone()
        payload = json.loads(row[0]); payload["execution_authorized"] = True
        conn.execute("UPDATE mission_events SET payload_json=? WHERE event_id=?", (json.dumps(payload), event_id))
    with pytest.raises(Exception, match="event lineage integrity|hash chain|integrity"):
        service.get_routing_delegation_event_lineage(mission_id)


def test_migration_026_declares_durable_stage349_store(tmp_path):
    migration = (tmp_path.parent.parent / "nonexistent")
    # Resolve from repository root rather than pytest temp directory.
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    text = (root / "migrations" / "026_stage3_4_9_routing_delegation_event_lineage_replay_recovery.sql").read_text()
    assert "mission_routing_delegation_recovery_checkpoints" in text
    assert "recovery_control_count" in text
    assert "source_event_tip_sha256" in text
    assert "UNIQUE KEY uq_routing_delegation_recovery_snapshot" in text
