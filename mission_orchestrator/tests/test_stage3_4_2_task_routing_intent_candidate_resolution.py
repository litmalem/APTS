from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskRoutingIntentConflict,
    MissionTaskRoutingIntentGuardRejected,
    MissionTaskRoutingIntentNotFound,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.subsystem_registry import build_canonical_registry_snapshot
from mission_orchestrator.task_decomposition import PLANNED_TASK_SCHEMA_VERSION
from mission_orchestrator.task_routing_intent import (
    CANDIDATE_RESOLUTION_MODE,
    RESOLUTION_CANDIDATES_FOUND,
    RESOLUTION_NO_CANDIDATE,
    TASK_ROUTING_INTENT_ID_PREFIX,
    TASK_ROUTING_INTENT_MODE,
    TASK_ROUTING_INTENT_SCHEMA_VERSION,
    canonical_task_routing_intent_definition,
    resolve_candidate_subsystems,
    verify_task_routing_intent_contract,
)
from tests.test_stage3_3_8_task_readiness_scheduling_projection import (
    create_projection,
    make_service,
    provision_active,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def routing_request(service, mission_id: str, projection: dict, active: dict, key: str, *, task_key="collect-cti", **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    task = next(item for item in projection["task_readiness"] if item["task_key"] == task_key)
    body = {
        "idempotency_key": f"stage342-routing-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": projection["projection_id"],
        "expected_task_readiness_projection_sha256": projection["canonical_sha256"],
        "planned_task_id": task["planned_task_id"],
        "created_by": "stage3.4.2-pytest",
        "reason": "Resolve routing intent and canonical candidate subsystem set",
        "metadata": {"stage": "3.4.2", "key": key},
    }
    body.update(overrides)
    return body


def provision_ready(service, key: str):
    mission_id, active = provision_active(service, key)
    projection = create_projection(service, mission_id, key)
    return mission_id, active, projection


def test_health_activates_stage342_without_crossing_route_selection_authority_or_execution(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
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
    assert health["task_routing_intent_schema_version"] == TASK_ROUTING_INTENT_SCHEMA_VERSION
    assert health["task_routing_intent_mode"] == TASK_ROUTING_INTENT_MODE
    assert health["task_routing_candidate_resolution_mode"] == CANDIDATE_RESOLUTION_MODE
    assert health["task_routing_candidate_resolution_performed"] is True
    assert health["task_routing_candidate_resolution_local_registry_only"] is True
    assert health["task_routing_candidate_is_eligibility_decision"] is False
    assert health["task_routing_eligibility_gate_performed"] is True
    assert health["task_routing_route_selection_performed"] is True
    assert health["task_routing_route_ranking_performed"] is True
    assert health["task_routing_runtime_endpoint_resolution_performed"] is False
    assert health["task_routing_runtime_health_probe_performed"] is False
    assert health["task_routing_governance_query_performed"] is False
    assert health["task_routing_authorization_granted"] is False
    assert health["task_routing_delegation_performed"] is True
    assert health["task_routing_dispatch_performed"] is False
    assert health["task_routing_target_action_dispatch_enabled"] is False
    assert health["task_routing_target_actuation"] is False
    assert health["task_routing_version_vector_extension_performed"] is False


def test_definition_is_discoverable_and_explicitly_stops_before_stage343(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_ready(service, "definition")
    result = service.get_task_routing_intent_definition(mission_id)
    definition = result["task_routing_intent_definition"]
    assert result["registered_intent_count"] == 0
    assert definition == canonical_task_routing_intent_definition()
    assert definition["requires_ready_task"] is True
    assert definition["candidate_is_eligibility_decision"] is False
    assert definition["eligibility_gate_performed"] is False
    assert definition["route_selection_performed"] is False
    assert definition["governance_query_performed"] is False
    assert definition["delegation_performed"] is False
    assert definition["dispatch_performed"] is False


def test_ready_cti_task_resolves_exact_registry_candidate_without_endpoint_probe(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_ready(service, "cti")
    result = service.create_task_routing_intent(
        mission_id, routing_request(service, mission_id, projection, active, "cti")
    )
    assert result["routing_intent_id"].startswith(TASK_ROUTING_INTENT_ID_PREFIX)
    assert result["resolution_status"] == RESOLUTION_CANDIDATES_FOUND
    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["candidate_index"] == 1
    assert candidate["subsystem_id"] == "CTI"
    assert candidate["capability_id"] == "cti.read.context"
    assert candidate["match"]["required_subsystem_match"] is True
    assert candidate["match"]["required_capability_exact_match"] is True
    assert candidate["runtime"] == {
        "endpoint_resolved": False,
        "health_probed": False,
        "availability": "UNKNOWN_NOT_PROBED",
    }
    assert verify_task_routing_intent_contract(result["routing_intent_contract"])
    assert result["candidate_is_eligibility_decision"] is False
    assert result["route_selection_performed"] is False
    assert result["selected_subsystem"] is None
    assert result["authorization_granted"] is False
    assert result["delegation_performed"] is False
    assert result["dispatch_performed"] is False


def test_blocked_dependency_task_cannot_enter_stage342(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_ready(service, "blocked")
    request = routing_request(service, mission_id, projection, active, "blocked", task_key="analyze-cti")
    with pytest.raises(MissionTaskRoutingIntentGuardRejected, match="only for a canonical READY task"):
        service.create_task_routing_intent(mission_id, request)
    assert service.get_task_routing_intent_history(mission_id)["intent_count"] == 0


@pytest.mark.parametrize("forbidden", [
    "required_capability", "required_subsystem", "candidates", "selected_subsystem",
    "eligible", "endpoint", "health", "resource_assignment", "authorization",
    "delegation", "dispatch", "target_action",
])
def test_request_rejects_caller_supplied_routing_authority_or_execution_surfaces(tmp_path, forbidden):
    service = make_service(tmp_path / f"{forbidden}.db")
    mission_id, active, projection = provision_ready(service, f"forbidden-{forbidden}")
    request = routing_request(service, mission_id, projection, active, f"forbidden-{forbidden}")
    request[forbidden] = True
    with pytest.raises(MissionValidationError, match="unsupported task routing intent field"):
        service.create_task_routing_intent(mission_id, request)


def test_stale_plan_readiness_state_and_version_guards_fail_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_ready(service, "stale")
    base = routing_request(service, mission_id, projection, active, "stale")
    cases = [
        ("expected_version_sha256", "0" * 64),
        ("expected_state_version", base["expected_state_version"] + 1),
        ("expected_active_plan_sha256", "1" * 64),
        ("expected_task_readiness_projection_sha256", "2" * 64),
    ]
    for field, value in cases:
        request = deepcopy(base)
        request["idempotency_key"] = f"stage342-stale-{field}"
        request[field] = value
        with pytest.raises(MissionConcurrencyConflict):
            service.create_task_routing_intent(mission_id, request)


def test_exact_replay_is_idempotent_and_does_not_duplicate_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_ready(service, "replay")
    request = routing_request(service, mission_id, projection, active, "replay")
    first = service.create_task_routing_intent(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.create_task_routing_intent(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["routing_intent_id"] == first["routing_intent_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_one_immutable_routing_intent_per_plan_task(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_ready(service, "one")
    service.create_task_routing_intent(mission_id, routing_request(service, mission_id, projection, active, "one"))
    second = routing_request(service, mission_id, projection, active, "one-2")
    with pytest.raises(MissionTaskRoutingIntentConflict, match="already has an immutable"):
        service.create_task_routing_intent(mission_id, second)


def test_pure_candidate_resolution_has_explicit_no_candidate_outcome_and_required_subsystem_filter():
    snapshot = build_canonical_registry_snapshot()
    unknown = {
        "schema_version": PLANNED_TASK_SCHEMA_VERSION,
        "required_subsystem": "CTI",
        "required_capability": "cti.unknown",
    }
    result = resolve_candidate_subsystems(unknown, snapshot)
    assert result["resolution_status"] == RESOLUTION_NO_CANDIDATE
    assert result["candidate_count"] == 0
    assert result["candidates"] == []

    mismatch = {
        "schema_version": PLANNED_TASK_SCHEMA_VERSION,
        "required_subsystem": "PENTEST",
        "required_capability": "cti.read.context",
    }
    result = resolve_candidate_subsystems(mismatch, snapshot)
    assert result["resolution_status"] == RESOLUTION_NO_CANDIDATE
    assert result["candidate_count"] == 0
    assert result["capability_match_count_before_subsystem_filter"] == 1
    assert "REQUIRED_SUBSYSTEM_MISMATCH" in result["excluded_matches"][0]["reasons"]


def test_candidate_resolution_is_deterministic_for_same_task_and_registry():
    snapshot = build_canonical_registry_snapshot()
    task = {
        "schema_version": PLANNED_TASK_SCHEMA_VERSION,
        "required_subsystem": "CTI",
        "required_capability": "cti.read.context",
    }
    a = resolve_candidate_subsystems(task, snapshot)
    b = resolve_candidate_subsystems(task, snapshot)
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_restart_reconstructs_routing_intent_and_repository_integrity(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, active, projection = provision_ready(service, "restart")
    created = service.create_task_routing_intent(
        mission_id, routing_request(service, mission_id, projection, active, "restart")
    )
    before = service.get_mission_repository(mission_id)
    assert before["integrity_status"] == "PASS"
    assert before["record_counts"]["mission_task_routing_intents"] == 1
    restarted = make_service(db)
    fetched = restarted.get_task_routing_intent(mission_id, created["routing_intent_id"])
    assert fetched["canonical_sha256"] == created["canonical_sha256"]
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"


def test_repository_integrity_detects_tampered_routing_intent_contract(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, active, projection = provision_ready(service, "tamper")
    created = service.create_task_routing_intent(
        mission_id, routing_request(service, mission_id, projection, active, "tamper")
    )
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "select canonical_json from mission_task_routing_intents where routing_intent_id=?",
            (created["routing_intent_id"],),
        ).fetchone()[0]
        body = json.loads(row)
        body["semantics"]["route_selection_performed"] = True
        conn.execute(
            "update mission_task_routing_intents set canonical_json=? where routing_intent_id=?",
            (json.dumps(body), created["routing_intent_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_unknown_routing_intent_is_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_ready(service, "missing")
    with pytest.raises(MissionTaskRoutingIntentNotFound):
        service.get_task_routing_intent(mission_id, "rint-missing")


def test_migration_019_declares_store_and_stage342_boundaries():
    sql = Path("migrations/019_stage3_4_2_task_routing_intent_candidate_resolution.sql").read_text().lower()
    assert "create table if not exists mission_task_routing_intents" in sql
    assert "candidate != eligible" in sql
    assert "candidate resolution != route selection" in sql
    assert "route selection != authorization" in sql
    assert "routing intent != delegation" in sql
    assert "no endpoint resolution" in sql
    assert "no health probe" in sql
    assert "no governance query" in sql
    assert "no target-action dispatch" in sql
    assert "    19," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert "mission_task_routing_intents" in REPOSITORY_STORES
    assert REPOSITORY_STORES[-1] == "mission_events"


def test_api_source_exposes_stage342_read_write_and_definition_routes():
    source = Path("mission_orchestrator/api_service.py").read_text()
    assert 'parts[3] == "task-routing-intents"' in source
    assert 'parts[3] == "task-routing-intent-definition"' in source
    assert "create_task_routing_intent" in source
    assert "get_task_routing_intent_history" in source
