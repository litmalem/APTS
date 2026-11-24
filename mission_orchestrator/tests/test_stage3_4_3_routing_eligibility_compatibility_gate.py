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
    MissionTaskRoutingEligibilityConflict,
    MissionTaskRoutingEligibilityGuardRejected,
    MissionTaskRoutingEligibilityNotFound,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.task_routing_eligibility import (
    CANDIDATE_ELIGIBLE,
    CANDIDATE_INELIGIBLE,
    ELIGIBILITY_EVALUATION_MODE,
    ELIGIBILITY_GATE_FAILED_CLOSED,
    ELIGIBILITY_GATE_PASSED,
    ELIGIBILITY_STATUS_ELIGIBLE,
    ELIGIBILITY_STATUS_NONE,
    TASK_ROUTING_ELIGIBILITY_ID_PREFIX,
    TASK_ROUTING_ELIGIBILITY_MODE,
    TASK_ROUTING_ELIGIBILITY_SCHEMA_VERSION,
    canonical_task_routing_eligibility_definition,
    evaluate_routing_eligibility,
    verify_task_routing_eligibility_contract,
)
from mission_orchestrator.task_routing_intent import (
    RESOLUTION_NO_CANDIDATE,
    TASK_ROUTING_INTENT_HASH_DOMAIN,
    sha256_hex as routing_sha256,
    verify_task_routing_intent_contract,
)
from tests.test_stage3_4_2_task_routing_intent_candidate_resolution import (
    make_service,
    provision_ready,
    routing_request,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision_routing_intent(service, key: str):
    mission_id, active, projection = provision_ready(service, key)
    routing = service.create_task_routing_intent(
        mission_id,
        routing_request(service, mission_id, projection, active, key),
    )
    return mission_id, active, projection, routing


def eligibility_request(service, mission_id: str, active: dict, projection: dict, routing: dict, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage343-eligibility-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": projection["projection_id"],
        "expected_task_readiness_projection_sha256": projection["canonical_sha256"],
        "expected_routing_intent_id": routing["routing_intent_id"],
        "expected_routing_intent_sha256": routing["canonical_sha256"],
        "planned_task_id": routing["planned_task_id"],
        "created_by": "stage3.4.3-pytest",
        "reason": "Evaluate static routing eligibility and compatibility without selecting a route",
        "metadata": {"stage": "3.4.3", "key": key},
    }
    body.update(overrides)
    return body


def create_eligibility(service, key: str):
    mission_id, active, projection, routing = provision_routing_intent(service, key)
    request = eligibility_request(service, mission_id, active, projection, routing, key)
    result = service.create_task_routing_eligibility_gate(mission_id, request)
    return mission_id, active, projection, routing, request, result


def _routing_contract_with_no_candidates(routing_contract: dict) -> dict:
    contract = deepcopy(routing_contract)
    contract["routing_intent"]["candidates"] = []
    contract["routing_intent"]["candidate_count"] = 0
    contract["routing_intent"]["resolution_status"] = RESOLUTION_NO_CANDIDATE
    core = {k: v for k, v in contract.items() if k != "integrity"}
    contract["integrity"]["canonical_sha256"] = routing_sha256(
        {"hash_domain": TASK_ROUTING_INTENT_HASH_DOMAIN, "core": core}
    )
    assert verify_task_routing_intent_contract(contract)
    return contract


def test_health_activates_stage343_and_preserves_authority_boundary(tmp_path):
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
    assert health["task_routing_eligibility_schema_version"] == TASK_ROUTING_ELIGIBILITY_SCHEMA_VERSION
    assert health["task_routing_eligibility_mode"] == TASK_ROUTING_ELIGIBILITY_MODE
    assert health["task_routing_eligibility_evaluation_mode"] == ELIGIBILITY_EVALUATION_MODE
    assert health["task_routing_eligibility_gate_performed"] is True
    assert health["task_routing_eligibility_static_contract_only"] is True
    assert health["task_routing_eligible_candidate_is_selected_route"] is False
    assert health["task_routing_eligibility_is_authorization"] is False
    assert health["task_routing_eligibility_is_runtime_availability"] is False
    assert health["task_routing_route_selection_performed"] is True
    assert health["task_routing_route_ranking_performed"] is True
    assert health["task_routing_runtime_endpoint_resolution_performed"] is False
    assert health["task_routing_runtime_health_probe_performed"] is False
    assert health["task_routing_governance_query_performed"] is False
    assert health["task_routing_authorization_granted"] is False
    assert health["task_routing_delegation_performed"] is True
    assert health["task_routing_dispatch_performed"] is False
    assert health["task_routing_eligibility_database_migration_level"] == 20
    assert health["task_routing_eligibility_persistence_store"] == "mission_task_routing_eligibility_gates"
    assert "mission_task_routing_eligibility_gates" in REPOSITORY_STORES


def test_definition_is_discoverable_and_explicitly_stops_before_route_selection(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_routing_intent(service, "definition")
    result = service.get_task_routing_eligibility_definition(mission_id)
    definition = result["task_routing_eligibility_definition"]
    assert result["registered_gate_count"] == 0
    assert definition == canonical_task_routing_eligibility_definition()
    assert definition["requires_stage342_routing_intent"] is True
    assert definition["compatibility_gate_performed"] is True
    assert definition["eligible_candidate_is_selected_route"] is False
    assert definition["eligibility_is_authorization"] is False
    assert definition["route_selection_performed"] is False
    assert definition["governance_query_performed"] is False
    assert definition["delegation_performed"] is False
    assert definition["dispatch_performed"] is False


def test_ready_cti_candidate_passes_static_eligibility_gate_without_selection_or_runtime_probe(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing, request, result = create_eligibility(service, "positive")
    assert result["eligibility_gate_id"].startswith(TASK_ROUTING_ELIGIBILITY_ID_PREFIX)
    assert result["routing_intent_id"] == routing["routing_intent_id"]
    assert result["gate_result"] == ELIGIBILITY_GATE_PASSED
    assert result["eligibility_status"] == ELIGIBILITY_STATUS_ELIGIBLE
    assert result["candidate_count"] == 1
    assert result["eligible_candidate_count"] == 1
    assert result["ineligible_candidate_count"] == 0
    eligible = result["eligible_candidates"][0]
    assert eligible["subsystem_id"] == "CTI"
    assert eligible["capability_id"] == "cti.read.context"
    assert eligible["eligibility_status"] == CANDIDATE_ELIGIBLE
    assert all(eligible["compatibility_checks"].values())
    assert eligible["runtime"]["availability"] == "UNKNOWN_NOT_PROBED"
    assert result["eligible_candidate_is_selected_route"] is False
    assert result["selected_subsystem"] is None
    assert result["eligibility_is_authorization"] is False
    assert result["eligibility_is_runtime_availability"] is False
    assert result["runtime_endpoint_resolution_performed"] is False
    assert result["runtime_health_probe_performed"] is False
    assert result["governance_query_performed"] is False
    assert result["authorization_granted"] is False
    assert result["delegation_performed"] is False
    assert result["dispatch_performed"] is False
    assert verify_task_routing_eligibility_contract(result["eligibility_contract"])


def test_gate_emits_one_canonical_lineage_event_bound_to_gate(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _, result = create_eligibility(service, "event")
    events = service.get_mission_events(mission_id)["events"]
    matches = [e for e in events if e["event_type"] == "MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED"]
    assert len(matches) == 1
    event = matches[0]
    assert event["causation_id"] == result["eligibility_gate_id"]
    assert event["payload"]["routing_intent_id"] == result["routing_intent_id"]
    assert event["payload"]["gate_result"] == ELIGIBILITY_GATE_PASSED
    assert event["payload"]["eligible_candidate_count"] == 1
    assert event["payload"]["authorization_granted"] is False
    assert event["payload"]["delegation_performed"] is False
    assert event["payload"]["dispatch_performed"] is False


def test_exact_replay_is_idempotent_and_does_not_duplicate_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing = provision_routing_intent(service, "replay")
    request = eligibility_request(service, mission_id, active, projection, routing, "replay")
    first = service.create_task_routing_eligibility_gate(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.create_task_routing_eligibility_gate(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["eligibility_gate_id"] == first["eligibility_gate_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_one_immutable_eligibility_gate_per_stage342_routing_intent(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing = provision_routing_intent(service, "single")
    service.create_task_routing_eligibility_gate(
        mission_id, eligibility_request(service, mission_id, active, projection, routing, "single")
    )
    with pytest.raises(MissionTaskRoutingEligibilityConflict, match="already has an immutable"):
        service.create_task_routing_eligibility_gate(
            mission_id, eligibility_request(service, mission_id, active, projection, routing, "single-second")
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("eligible", True),
        ("eligible_candidates", []),
        ("route_rank", 1),
        ("selected_subsystem", "CTI"),
        ("endpoint", "http://127.0.0.1"),
        ("health", "UP"),
        ("authorization_granted", True),
        ("delegation", {"to": "CTI"}),
        ("dispatch", True),
        ("target_action", "SCAN"),
    ],
)
def test_request_rejects_caller_supplied_eligibility_selection_runtime_and_authority_fields(tmp_path, field, value):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing = provision_routing_intent(service, f"forbid-{field}")
    request = eligibility_request(service, mission_id, active, projection, routing, f"forbid-{field}")
    request[field] = value
    with pytest.raises(MissionValidationError, match="unsupported task routing eligibility field"):
        service.create_task_routing_eligibility_gate(mission_id, request)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("expected_version_sha256", "0" * 64, "expected_version_sha256"),
        ("expected_state_version", 999, "expected_state_version"),
        ("expected_active_plan_version_record_id", "pver-wrong", "expected_active_plan_version_record_id"),
        ("expected_active_plan_version", 99, "expected_active_plan_version"),
        ("expected_active_plan_sha256", "0" * 64, "expected_active_plan_sha256"),
        ("expected_task_readiness_projection_id", "tready-wrong", "expected_task_readiness_projection_id"),
        ("expected_task_readiness_projection_sha256", "0" * 64, "expected_task_readiness_projection_sha256"),
        ("expected_routing_intent_sha256", "0" * 64, "expected_routing_intent_sha256"),
    ],
)
def test_stale_source_bindings_fail_closed_before_materialization(tmp_path, field, value, match):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing = provision_routing_intent(service, f"stale-{field}")
    request = eligibility_request(service, mission_id, active, projection, routing, f"stale-{field}", **{field: value})
    with pytest.raises(MissionConcurrencyConflict, match=match):
        service.create_task_routing_eligibility_gate(mission_id, request)
    assert service.get_task_routing_eligibility_history(mission_id)["gate_count"] == 0


def test_missing_stage342_routing_intent_is_not_synthesized(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing = provision_routing_intent(service, "missing-intent")
    request = eligibility_request(
        service, mission_id, active, projection, routing, "missing-intent",
        expected_routing_intent_id="rint-missing",
    )
    with pytest.raises(MissionTaskRoutingEligibilityNotFound):
        service.create_task_routing_eligibility_gate(mission_id, request)


def test_planned_task_binding_must_match_stage342_intent(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing = provision_routing_intent(service, "task-binding")
    other = next(x for x in projection["task_readiness"] if x["planned_task_id"] != routing["planned_task_id"])
    request = eligibility_request(
        service, mission_id, active, projection, routing, "task-binding",
        planned_task_id=other["planned_task_id"],
    )
    with pytest.raises(MissionTaskRoutingEligibilityGuardRejected, match="does not match"):
        service.create_task_routing_eligibility_gate(mission_id, request)


def test_pure_evaluator_rejects_candidate_outside_mission_required_subsystems(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, routing = provision_routing_intent(service, "scope-eval")
    registry = service.get_subsystem_registry()["registry"]
    evaluation = evaluate_routing_eligibility(routing["routing_intent_contract"], registry, ["PENTEST"])
    assert evaluation["gate_result"] == ELIGIBILITY_GATE_FAILED_CLOSED
    assert evaluation["eligibility_status"] == ELIGIBILITY_STATUS_NONE
    assert evaluation["eligible_candidate_count"] == 0
    assert evaluation["ineligible_candidate_count"] == 1
    assert evaluation["ineligible_candidates"][0]["eligibility_status"] == CANDIDATE_INELIGIBLE
    assert "SUBSYSTEM_OUTSIDE_MISSION_REQUIRED_SUBSYSTEMS" in evaluation["ineligible_candidates"][0]["rejection_reasons"]


def test_pure_evaluator_fails_closed_when_stage342_has_zero_candidates(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, routing = provision_routing_intent(service, "zero")
    registry = service.get_subsystem_registry()["registry"]
    no_candidate_contract = _routing_contract_with_no_candidates(routing["routing_intent_contract"])
    evaluation = evaluate_routing_eligibility(no_candidate_contract, registry, ["CTI"])
    assert evaluation["candidate_count"] == 0
    assert evaluation["eligible_candidate_count"] == 0
    assert evaluation["gate_result"] == ELIGIBILITY_GATE_FAILED_CLOSED
    assert evaluation["eligibility_status"] == ELIGIBILITY_STATUS_NONE
    assert evaluation["gate_rejection_reasons"] == ["NO_STAGE342_CANDIDATE"]


def test_pure_evaluator_detects_registry_contract_divergence_and_does_not_resurrect_candidate(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, routing = provision_routing_intent(service, "registry-diverge")
    registry = deepcopy(service.get_subsystem_registry()["registry"])
    cap = next(c for c in registry["capabilities"] if c["identity"]["capability_id"] == "cti.read.context")
    cap["registration"]["enabled"] = False
    evaluation = evaluate_routing_eligibility(routing["routing_intent_contract"], registry, ["CTI"])
    assert evaluation["candidate_count"] == routing["candidate_count"] == 1
    assert evaluation["eligible_candidate_count"] == 0
    reasons = evaluation["ineligible_candidates"][0]["rejection_reasons"]
    assert "CAPABILITY_CONTRACT_INTEGRITY_INVALID" in reasons
    assert "CAPABILITY_NOT_REGISTERED_OR_ENABLED" in reasons


def test_eligibility_materialization_does_not_extend_mission_version_vector(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, routing = provision_routing_intent(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    result = service.create_task_routing_eligibility_gate(
        mission_id, eligibility_request(service, mission_id, active, projection, routing, "vector")
    )
    after = service.get_mission_version_vector(mission_id)
    assert after["version_sha256"] == before["version_sha256"]
    assert result["eligibility_contract"]["semantics"]["version_vector_extension_performed"] is False


def test_repository_reconstruction_includes_gate_and_passes_integrity_after_restart(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, _, routing, _, result = create_eligibility(service, "restart")
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_task_routing_eligibility_gates"] == 1
    assert repo["persistence_manifest"]["task_routing_eligibility_store"]["gates"][0]["eligibility_gate_id"] == result["eligibility_gate_id"]
    restarted = make_service(db)
    loaded = restarted.get_task_routing_eligibility(mission_id, result["eligibility_gate_id"])
    assert loaded["canonical_sha256"] == result["canonical_sha256"]
    assert restarted.get_mission_repository(mission_id)["integrity_status"] == "PASS"


def test_repository_integrity_detects_tampered_eligibility_contract(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, _, _, _, result = create_eligibility(service, "tamper")
    with sqlite3.connect(db) as conn:
        raw = conn.execute(
            "SELECT canonical_json FROM mission_task_routing_eligibility_gates WHERE eligibility_gate_id=?",
            (result["eligibility_gate_id"],),
        ).fetchone()[0]
        doc = json.loads(raw)
        doc["eligibility_gate"]["eligible_candidates"][0]["subsystem_id"] = "PENTEST"
        conn.execute(
            "UPDATE mission_task_routing_eligibility_gates SET canonical_json=? WHERE eligibility_gate_id=?",
            (json.dumps(doc, sort_keys=True, separators=(",", ":")), result["eligibility_gate_id"]),
        )
    with pytest.raises(MissionRepositoryIntegrityError, match="task_routing_eligibility_compatibility_store"):
        service.get_mission_repository(mission_id)


def test_api_surface_contains_stage343_read_and_create_routes_and_error_mapping():
    source = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    assert source.count('parts[3] == "task-routing-eligibility-gates"') == 3  # GET list, GET item, POST create
    assert 'parts[3] == "task-routing-eligibility-definition"' in source
    assert "create_task_routing_eligibility_gate" in source
    assert "get_task_routing_eligibility_history" in source
    assert "MISSION_TASK_ROUTING_ELIGIBILITY_CONFLICT" in source
    assert "MISSION_TASK_ROUTING_ELIGIBILITY_GUARD_REJECTED" in source
    assert "MISSION_TASK_ROUTING_ELIGIBILITY_NOT_FOUND" in source


def test_migration_020_is_present_and_preserves_stage343_boundary():
    path = Path("migrations/020_stage3_4_3_routing_eligibility_compatibility_gate.sql")
    sql = path.read_text(encoding="utf-8")
    assert "mission_task_routing_eligibility_gates" in sql
    assert "migration_level" in sql and "20" in sql
    assert "Eligible candidate != selected route" in sql
    assert "Eligibility != authorization" in sql
    assert "No route ranking/selection" in sql
    assert "No Governance query" in sql
    assert "aptsGSS / GOV-PLANE" in sql


def test_response_and_contract_never_claim_selection_authorization_delegation_or_dispatch(tmp_path):
    service = make_service(tmp_path / "missions.db")
    *_, result = create_eligibility(service, "boundary")
    semantics = result["eligibility_contract"]["semantics"]
    for field in (
        "route_selection_performed",
        "route_ranking_performed",
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
        assert semantics[field] is False
        assert result[field] is False
    assert semantics["selected_subsystem"] is None
    assert result["selected_subsystem"] is None
    assert semantics["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
