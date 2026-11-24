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
    MissionTaskRouteSelectionConflict,
    MissionTaskRouteSelectionGuardRejected,
    MissionTaskRouteSelectionNotFound,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.task_route_selection import (
    ROUTE_DECISION_NO_ROUTE,
    ROUTE_DECISION_SELECTED,
    ROUTE_SELECTION_POLICY,
    TASK_ROUTE_SELECTION_HASH_DOMAIN,
    TASK_ROUTE_SELECTION_ID_PREFIX,
    TASK_ROUTE_SELECTION_MODE,
    TASK_ROUTE_SELECTION_SCHEMA_VERSION,
    canonical_task_route_selection_definition,
    deterministically_select_route,
    verify_task_route_selection_contract,
)
from mission_orchestrator.task_routing_eligibility import (
    CANDIDATE_ELIGIBLE,
    ELIGIBILITY_GATE_FAILED_CLOSED,
    ELIGIBILITY_GATE_PASSED,
    ELIGIBILITY_STATUS_ELIGIBLE,
    ELIGIBILITY_STATUS_NONE,
    TASK_ROUTING_ELIGIBILITY_HASH_DOMAIN,
    sha256_hex as eligibility_sha256,
    verify_task_routing_eligibility_contract,
)
from tests.test_stage3_4_3_routing_eligibility_compatibility_gate import (
    create_eligibility,
    make_service,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def route_selection_request(service, mission_id: str, active: dict, projection: dict, routing: dict, eligibility: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage344-route-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": projection["projection_id"],
        "expected_task_readiness_projection_sha256": projection["canonical_sha256"],
        "expected_routing_intent_id": routing["routing_intent_id"],
        "expected_routing_intent_sha256": routing["canonical_sha256"],
        "expected_eligibility_gate_id": eligibility["eligibility_gate_id"],
        "expected_eligibility_gate_sha256": eligibility["canonical_sha256"],
        "planned_task_id": routing["planned_task_id"],
        "created_by": "stage3.4.4-pytest",
        "reason": "Deterministically select one logical route only from Stage-3.4.3 ELIGIBLE candidates",
        "metadata": {"stage": "3.4.4", "key": key},
    }
    body.update(overrides)
    return body


def create_route_decision(service, key: str):
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, key)
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, key)
    result = service.create_task_route_selection_decision(mission_id, request)
    return mission_id, active, projection, routing, eligibility, request, result


def _rehash_eligibility(contract: dict) -> dict:
    core = {k: v for k, v in contract.items() if k != "integrity"}
    contract["integrity"]["canonical_sha256"] = eligibility_sha256(
        {"hash_domain": TASK_ROUTING_ELIGIBILITY_HASH_DOMAIN, "core": core}
    )
    assert verify_task_routing_eligibility_contract(contract)
    return contract


def _synthetic_multi_eligible(contract: dict) -> dict:
    doc = deepcopy(contract)
    base = deepcopy(doc["eligibility_gate"]["eligible_candidates"][0])
    items = []
    for idx, subsystem, capability, version in (
        (3, "PENTEST", "pentest.execute.assessment", 2),
        (1, "CTI", "cti.read.context", 1),
        (2, "CTI", "cti.enrich.finding", 3),
    ):
        item = deepcopy(base)
        item["candidate_index"] = idx
        item["subsystem_id"] = subsystem
        item["capability_id"] = capability
        item["capability_version"] = version
        item["eligibility_status"] = CANDIDATE_ELIGIBLE
        items.append(item)
    doc["eligibility_gate"]["candidate_evaluations"] = list(reversed(items))
    doc["eligibility_gate"]["eligible_candidates"] = list(reversed(items))
    doc["eligibility_gate"]["ineligible_candidates"] = []
    doc["eligibility_gate"]["candidate_count"] = len(items)
    doc["eligibility_gate"]["eligible_candidate_count"] = len(items)
    doc["eligibility_gate"]["ineligible_candidate_count"] = 0
    doc["eligibility_gate"]["gate_result"] = ELIGIBILITY_GATE_PASSED
    doc["eligibility_gate"]["eligibility_status"] = ELIGIBILITY_STATUS_ELIGIBLE
    return _rehash_eligibility(doc)


def _synthetic_no_eligible(contract: dict) -> dict:
    doc = deepcopy(contract)
    doc["eligibility_gate"]["candidate_evaluations"] = []
    doc["eligibility_gate"]["eligible_candidates"] = []
    doc["eligibility_gate"]["ineligible_candidates"] = []
    doc["eligibility_gate"]["candidate_count"] = 0
    doc["eligibility_gate"]["eligible_candidate_count"] = 0
    doc["eligibility_gate"]["ineligible_candidate_count"] = 0
    doc["eligibility_gate"]["gate_result"] = ELIGIBILITY_GATE_FAILED_CLOSED
    doc["eligibility_gate"]["eligibility_status"] = ELIGIBILITY_STATUS_NONE
    return _rehash_eligibility(doc)


def test_health_activates_stage344_and_stops_before_governance_delegation_dispatch(tmp_path):
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
    assert health["task_route_selection_schema_version"] == TASK_ROUTE_SELECTION_SCHEMA_VERSION
    assert health["task_route_selection_mode"] == TASK_ROUTE_SELECTION_MODE
    assert health["task_route_selection_policy"] == ROUTE_SELECTION_POLICY
    assert health["task_routing_route_ranking_performed"] is True
    assert health["task_routing_route_selection_performed"] is True
    assert health["task_routing_runtime_endpoint_resolution_performed"] is False
    assert health["task_routing_runtime_health_probe_performed"] is False
    assert health["task_routing_governance_query_performed"] is False
    assert health["task_routing_authorization_granted"] is False
    assert health["task_routing_delegation_performed"] is True
    assert health["task_routing_dispatch_performed"] is False
    assert health["task_route_selection_database_migration_level"] == 21
    assert health["task_route_selection_persistence_store"] == "mission_task_route_decisions"
    assert "mission_task_route_decisions" in REPOSITORY_STORES


def test_definition_is_discoverable_and_explicit_about_determinism_and_authority_boundary(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = create_eligibility(service, "definition")
    result = service.get_task_route_selection_definition(mission_id)
    definition = result["task_route_selection_definition"]
    assert result["registered_decision_count"] == 0
    assert definition == canonical_task_route_selection_definition()
    assert definition["requires_stage343_eligibility_gate"] is True
    assert definition["eligible_candidate_source"] == "STAGE343_ELIGIBLE_CANDIDATES_ONLY"
    assert definition["route_ranking_performed"] is True
    assert definition["route_selection_decision_performed"] is True
    assert definition["selected_route_is_logical_only"] is True
    assert definition["selection_is_authorization"] is False
    assert definition["selection_is_runtime_availability"] is False
    assert definition["governance_query_performed"] is False
    assert definition["delegation_performed"] is False
    assert definition["dispatch_performed"] is False


def test_ready_cti_task_selects_deterministic_logical_route_from_stage343_only(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, routing, eligibility, _, result = create_route_decision(service, "positive")
    assert result["route_decision_id"].startswith(TASK_ROUTE_SELECTION_ID_PREFIX)
    assert result["eligibility_gate_id"] == eligibility["eligibility_gate_id"]
    assert result["routing_intent_id"] == routing["routing_intent_id"]
    assert result["decision_status"] == ROUTE_DECISION_SELECTED
    assert result["route_selected"] is True
    assert result["eligible_candidate_count"] == 1
    assert len(result["ranked_candidates"]) == 1
    selected = result["selected_route"]
    assert selected["rank"] == 1
    assert selected["subsystem_id"] == "CTI"
    assert selected["capability_id"] == "cti.read.context"
    assert selected["logical_route_only"] is True
    assert selected["runtime"] == {
        "endpoint_resolved": False,
        "health_probed": False,
        "availability": "UNKNOWN_NOT_PROBED",
    }
    assert result["selected_subsystem"] == "CTI"
    assert result["selected_capability"] == "cti.read.context"
    assert verify_task_route_selection_contract(result["route_selection_contract"])


def test_contract_binds_exact_stage343_gate_intent_plan_readiness_and_registry(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, eligibility, _, result = create_route_decision(service, "bindings")
    contract = result["route_selection_contract"]
    identity = contract["identity"]
    source = contract["source_bindings"]
    assert identity["mission_id"] == mission_id
    assert identity["eligibility_gate_id"] == eligibility["eligibility_gate_id"]
    assert identity["routing_intent_id"] == routing["routing_intent_id"]
    assert identity["plan_version_record_id"] == active["plan_version_record_id"]
    assert source["task_readiness_projection_id"] == projection["projection_id"]
    assert source["routing_intent_sha256"] == routing["canonical_sha256"]
    assert source["eligibility_gate_sha256"] == eligibility["canonical_sha256"]
    assert source["registry_sha256"] == eligibility["eligibility_contract"]["source_bindings"]["registry_sha256"]
    assert contract["integrity"]["hash_domain"] == TASK_ROUTE_SELECTION_HASH_DOMAIN


def test_route_decision_emits_one_canonical_lineage_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_prefix, result = create_route_decision(service, "event")
    matches = [
        event for event in service.get_mission_events(mission_id)["events"]
        if event["event_type"] == "MISSION_TASK_ROUTE_DECISION_RECORDED"
    ]
    assert len(matches) == 1
    event = matches[0]
    assert event["causation_id"] == result["route_decision_id"]
    assert event["payload"]["eligibility_gate_id"] == result["eligibility_gate_id"]
    assert event["payload"]["decision_status"] == ROUTE_DECISION_SELECTED
    assert event["payload"]["route_selected"] is True
    assert event["payload"]["selected_subsystem"] == "CTI"
    assert event["payload"]["selection_is_authorization"] is False
    assert event["payload"]["authorization_granted"] is False
    assert event["payload"]["delegation_performed"] is False
    assert event["payload"]["dispatch_performed"] is False


def test_exact_replay_is_idempotent_and_does_not_duplicate_lineage_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, "replay")
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, "replay")
    first = service.create_task_route_selection_decision(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.create_task_route_selection_decision(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["route_decision_id"] == first["route_decision_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_idempotency_key_reuse_with_different_request_is_conflict(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, "idem-conflict")
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, "idem-conflict")
    service.create_task_route_selection_decision(mission_id, request)
    changed = deepcopy(request)
    changed["reason"] = "different canonical request"
    with pytest.raises(MissionTaskRouteSelectionConflict, match="idempotency_key"):
        service.create_task_route_selection_decision(mission_id, changed)


def test_one_immutable_route_decision_per_stage343_eligibility_gate(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, "single")
    service.create_task_route_selection_decision(
        mission_id, route_selection_request(service, mission_id, active, projection, routing, eligibility, "single")
    )
    with pytest.raises(MissionTaskRouteSelectionConflict, match="already has an immutable"):
        service.create_task_route_selection_decision(
            mission_id, route_selection_request(service, mission_id, active, projection, routing, eligibility, "single-second")
        )


@pytest.mark.parametrize(
    "forbidden,value",
    [
        ("candidates", []),
        ("eligible_candidates", []),
        ("rank", 1),
        ("score", 0.99),
        ("priority", 1),
        ("selected_route", {"subsystem_id": "CTI"}),
        ("selected_subsystem", "CTI"),
        ("selected_capability", "cti.read.context"),
        ("endpoint", "http://127.0.0.1:8765"),
        ("health", "UP"),
        ("resource_assignment", {"worker": "x"}),
        ("authorization_granted", True),
        ("delegation", {"to": "CTI"}),
        ("dispatch", True),
        ("execution", True),
        ("target_action", "scan"),
    ],
)
def test_request_rejects_caller_supplied_selection_runtime_authority_or_execution_fields(tmp_path, forbidden, value):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, f"forbid-{forbidden}")
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, f"forbid-{forbidden}")
    request[forbidden] = value
    with pytest.raises(MissionValidationError, match="unsupported task route-selection field"):
        service.create_task_route_selection_decision(mission_id, request)


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("expected_version_sha256", "0" * 64),
        ("expected_state_version", 999999),
        ("expected_active_plan_version_record_id", "pver-stale"),
        ("expected_active_plan_version", 999999),
        ("expected_active_plan_sha256", "1" * 64),
        ("expected_task_readiness_projection_id", "ready-stale"),
        ("expected_task_readiness_projection_sha256", "2" * 64),
        ("expected_routing_intent_sha256", "3" * 64),
        ("expected_eligibility_gate_sha256", "4" * 64),
    ],
)
def test_stale_source_bindings_fail_closed_as_concurrency_conflict(tmp_path, field, bad_value):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, f"stale-{field}")
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, f"stale-{field}")
    request[field] = bad_value
    with pytest.raises(MissionConcurrencyConflict):
        service.create_task_route_selection_decision(mission_id, request)


def test_missing_stage343_eligibility_gate_is_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, "missing-gate")
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, "missing-gate")
    request["expected_eligibility_gate_id"] = "relig-does-not-exist"
    with pytest.raises(MissionTaskRouteSelectionNotFound):
        service.create_task_route_selection_decision(mission_id, request)


def test_planned_task_mismatch_is_guard_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, "task-mismatch")
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, "task-mismatch")
    request["planned_task_id"] = "ptask-other"
    with pytest.raises(MissionTaskRouteSelectionGuardRejected, match="planned_task_id"):
        service.create_task_route_selection_decision(mission_id, request)


def test_pure_selector_is_deterministic_and_independent_of_stage343_eligible_list_order(tmp_path):
    service = make_service(tmp_path / "missions.db")
    *_, eligibility = create_eligibility(service, "determinism")
    contract = _synthetic_multi_eligible(eligibility["eligibility_contract"])
    first = deterministically_select_route(contract)
    reversed_contract = deepcopy(contract)
    reversed_contract["eligibility_gate"]["eligible_candidates"] = list(
        reversed(reversed_contract["eligibility_gate"]["eligible_candidates"])
    )
    reversed_contract["eligibility_gate"]["candidate_evaluations"] = list(
        reversed(reversed_contract["eligibility_gate"]["candidate_evaluations"])
    )
    _rehash_eligibility(reversed_contract)
    second = deterministically_select_route(reversed_contract)
    assert first == second
    assert [item["candidate_index"] for item in first["ranked_candidates"]] == [1, 2, 3]
    assert first["selected_route"]["candidate_index"] == 1
    assert first["selected_route"]["subsystem_id"] == "CTI"
    assert first["selection_policy"] == ROUTE_SELECTION_POLICY


def test_pure_selector_returns_durable_no_route_semantics_when_stage343_has_no_eligible_candidate(tmp_path):
    service = make_service(tmp_path / "missions.db")
    *_, eligibility = create_eligibility(service, "no-route")
    no_eligible = _synthetic_no_eligible(eligibility["eligibility_contract"])
    decision = deterministically_select_route(no_eligible)
    assert decision["decision_status"] == ROUTE_DECISION_NO_ROUTE
    assert decision["route_selected"] is False
    assert decision["eligible_candidate_count"] == 0
    assert decision["ranked_candidates"] == []
    assert decision["selected_route"] is None
    assert decision["selected_subsystem"] is None
    assert decision["selected_capability"] is None
    assert decision["decision_reasons"] == ["NO_STAGE343_ELIGIBLE_CANDIDATE"]


def test_pure_selector_rejects_duplicate_canonical_candidate_identity(tmp_path):
    service = make_service(tmp_path / "missions.db")
    *_, eligibility = create_eligibility(service, "duplicate")
    doc = deepcopy(eligibility["eligibility_contract"])
    item = deepcopy(doc["eligibility_gate"]["eligible_candidates"][0])
    doc["eligibility_gate"]["candidate_evaluations"] = [item, deepcopy(item)]
    doc["eligibility_gate"]["eligible_candidates"] = [item, deepcopy(item)]
    doc["eligibility_gate"]["ineligible_candidates"] = []
    doc["eligibility_gate"]["candidate_count"] = 2
    doc["eligibility_gate"]["eligible_candidate_count"] = 2
    doc["eligibility_gate"]["ineligible_candidate_count"] = 0
    _rehash_eligibility(doc)
    with pytest.raises(MissionValidationError, match="duplicate canonical candidate identities"):
        deterministically_select_route(doc)


def test_route_selection_materialization_does_not_extend_mission_version_vector(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    result = service.create_task_route_selection_decision(
        mission_id, route_selection_request(service, mission_id, active, projection, routing, eligibility, "vector")
    )
    after = service.get_mission_version_vector(mission_id)
    assert after["version_sha256"] == before["version_sha256"]
    assert result["route_selection_contract"]["semantics"]["version_vector_extension_performed"] is False


def test_read_history_and_single_decision_are_durable_and_verifiable(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_prefix, result = create_route_decision(service, "read")
    single = service.get_task_route_selection_decision(mission_id, result["route_decision_id"])
    history = service.get_task_route_selection_history(mission_id)
    assert single["canonical_sha256"] == result["canonical_sha256"]
    assert history["decision_count"] == 1
    assert history["route_decisions"][0]["route_decision_id"] == result["route_decision_id"]
    assert history["selection_is_authorization"] is False
    assert history["selected_route_is_runtime_endpoint"] is False


def test_unknown_route_decision_is_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = create_eligibility(service, "unknown-read")
    with pytest.raises(MissionTaskRouteSelectionNotFound):
        service.get_task_route_selection_decision(mission_id, "rdec-does-not-exist")


def test_repository_reconstruction_includes_route_decision_and_passes_after_restart(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_prefix, result = create_route_decision(service, "restart")
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_task_route_decisions"] == 1
    ref = repo["persistence_manifest"]["task_route_selection_store"]["decisions"][0]
    assert ref["route_decision_id"] == result["route_decision_id"]
    restarted = make_service(db)
    loaded = restarted.get_task_route_selection_decision(mission_id, result["route_decision_id"])
    assert loaded["canonical_sha256"] == result["canonical_sha256"]
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"


def test_repository_integrity_detects_tampered_route_selection_contract(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_prefix, result = create_route_decision(service, "tamper")
    with sqlite3.connect(db) as conn:
        raw = conn.execute(
            "SELECT canonical_json FROM mission_task_route_decisions WHERE route_decision_id=?",
            (result["route_decision_id"],),
        ).fetchone()[0]
        doc = json.loads(raw)
        doc["route_decision"]["selected_route"]["subsystem_id"] = "PENTEST"
        conn.execute(
            "UPDATE mission_task_route_decisions SET canonical_json=? WHERE route_decision_id=?",
            (json.dumps(doc, sort_keys=True, separators=(",", ":")), result["route_decision_id"]),
        )
    with pytest.raises(MissionRepositoryIntegrityError, match="task_deterministic_route_selection_decision_store"):
        service.get_mission_repository(mission_id)


def test_api_surface_contains_stage344_read_create_definition_and_error_mapping():
    source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert source.count('parts[3] == "task-route-decisions"') == 3  # GET list, GET item, POST create
    assert 'parts[3] == "task-route-selection-definition"' in source
    assert "create_task_route_selection_decision" in source
    assert "get_task_route_selection_history" in source
    assert "MISSION_TASK_ROUTE_SELECTION_CONFLICT" in source
    assert "MISSION_TASK_ROUTE_SELECTION_GUARD_REJECTED" in source
    assert "MISSION_TASK_ROUTE_SELECTION_NOT_FOUND" in source


def test_migration_021_is_present_and_preserves_stage344_authority_boundary():
    path = Path("migrations/021_stage3_4_4_deterministic_route_selection_decision_record.sql")
    sql = path.read_text(encoding="utf-8")
    assert "mission_task_route_decisions" in sql
    assert "migration_level" in sql and "21" in sql
    assert "Stage-3.4.3 ELIGIBLE candidates" in sql
    assert "deterministic" in sql.lower()
    assert "Selected route != runtime availability" in sql
    assert "Selected route != authorization" in sql
    assert "Route selection != delegation. Route selection != dispatch. Route selection != execution." in sql
    assert "aptsGSS / GOV-PLANE" in sql


def test_sqlite_schema_enforces_one_decision_per_eligibility_gate_and_plan_task(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_ = create_route_decision(service, "schema")
    with sqlite3.connect(db) as conn:
        indexes = conn.execute("PRAGMA index_list('mission_task_route_decisions')").fetchall()
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='mission_task_route_decisions'"
        ).fetchone()[0]
    assert mission_id
    assert indexes
    assert "eligibility_gate_id" in sql
    assert "canonical_json" in sql


def test_response_and_contract_never_claim_runtime_authorization_delegation_dispatch_or_actuation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    *_, result = create_route_decision(service, "boundary")
    semantics = result["route_selection_contract"]["semantics"]
    for field in (
        "runtime_endpoint_resolution_performed",
        "runtime_health_probe_performed",
        "resource_assignment_performed",
        "governance_query_performed",
        "authorization_granted",
        "delegation_performed",
        "dispatch_performed",
        "target_action_dispatch_enabled",
        "target_actuation",
    ):
        assert result[field] is False
        assert semantics[field] is False
    assert result["selection_is_authorization"] is False
    assert result["selection_is_runtime_availability"] is False
    assert semantics["selection_is_authorization"] is False
    assert semantics["selection_is_runtime_availability"] is False
    assert result["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"


def test_ranked_candidate_runtime_is_always_unknown_and_unprobed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    *_, result = create_route_decision(service, "runtime")
    for candidate in result["ranked_candidates"]:
        assert candidate["runtime"]["endpoint_resolved"] is False
        assert candidate["runtime"]["health_probed"] is False
        assert candidate["runtime"]["availability"] == "UNKNOWN_NOT_PROBED"


def test_selected_route_is_derived_not_copied_from_caller(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, _, eligibility = create_eligibility(service, "derived")
    request = route_selection_request(service, mission_id, active, projection, routing, eligibility, "derived")
    result = service.create_task_route_selection_decision(mission_id, request)
    assert "selected_route" not in request
    assert result["selected_route"]["subsystem_id"] == eligibility["eligible_candidates"][0]["subsystem_id"]
    assert result["selected_route"]["capability_id"] == eligibility["eligible_candidates"][0]["capability_id"]


def test_selection_contract_integrity_rejects_tampered_rank_or_selected_route(tmp_path):
    service = make_service(tmp_path / "missions.db")
    *_, result = create_route_decision(service, "verify-tamper")
    for mutate in ("rank", "selected"):
        doc = deepcopy(result["route_selection_contract"])
        if mutate == "rank":
            doc["route_decision"]["ranked_candidates"][0]["rank"] = 2
        else:
            doc["route_decision"]["selected_route"]["capability_id"] = "tampered.capability"
        assert verify_task_route_selection_contract(doc) is False
