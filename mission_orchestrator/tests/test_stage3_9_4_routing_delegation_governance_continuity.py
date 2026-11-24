from __future__ import annotations

from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.e2e_intake_lifecycle_qualification import build_intake_lifecycle_command_request
from mission_orchestrator.e2e_mission_acceptance import materialize_canonical_e2e_mission_request
from mission_orchestrator.e2e_planning_task_graph_qualification import (
    build_planning_dependency_graph_request,
    build_planning_decomposition_request,
    build_planning_plan_request,
    build_planning_snapshot_request,
)
from mission_orchestrator.e2e_routing_delegation_governance_qualification import (
    ROUTING_DELEGATION_GOVERNANCE_ALLOWED_NONZERO_REPOSITORY_COUNTS,
    ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES,
    ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_SCHEMA_VERSION,
    ROUTING_DELEGATION_GOVERNANCE_PREDECESSOR_CONTROL,
    build_delegation_authorization_request,
    build_delegation_delivery_request,
    build_delegation_request,
    build_governance_binding_request,
    build_plan_activation_request,
    build_plan_validation_request,
    build_planner_generation_request,
    build_readiness_projection_request,
    build_route_selection_request,
    build_routing_eligibility_request,
    build_routing_intent_request,
    build_scope_request,
    canonical_routing_delegation_governance_qualification_contract,
    verify_routing_delegation_governance_qualification_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from test_stage3_1_4_governance_authorization_binding import FakeGovernanceClient

CURRENT_CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def make_service(db: Path, gov: FakeGovernanceClient | None = None):
    gov = gov or FakeGovernanceClient()
    service = CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=gov,
        cti_client=gov,
    )
    return service, gov


def _state(service, mission_id):
    return service.get_mission_state(mission_id)["mission_state"]


def _vector(service, mission_id):
    return service.get_mission_version_vector(mission_id)["version_sha256"]


def provision_stage394(service: CanonicalMissionService, run_id: str, *, stop_after_authorization=False):
    created = service.create_mission(materialize_canonical_e2e_mission_request(run_id))
    mission_id = created["canonical_identity"]["mission_id"]
    requests = {}
    responses = {}

    for command in ("BIND_PIP", "START_PLANNING"):
        req = build_intake_lifecycle_command_request(
            run_id=run_id,
            command=command,
            expected_version_sha256=_vector(service, mission_id),
            expected_state_version=_state(service, mission_id)["state_version"],
        )
        service.execute_mission_lifecycle_command(mission_id, req)

    requests["plan"] = build_planning_plan_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"])
    responses["plan"] = service.create_mission_plan_contract(mission_id, requests["plan"])
    requests["snapshot"] = build_planning_snapshot_request(
        run_id=run_id, plan=responses["plan"], expected_state_version=_state(service, mission_id)["state_version"])
    responses["snapshot"] = service.create_planner_input_snapshot(mission_id, requests["snapshot"])
    requests["decomposition"] = build_planning_decomposition_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"],
        plan=responses["plan"], snapshot=responses["snapshot"])
    responses["decomposition"] = service.create_task_decomposition(mission_id, requests["decomposition"])
    requests["graph"] = build_planning_dependency_graph_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], plan=responses["plan"],
        snapshot=responses["snapshot"], decomposition=responses["decomposition"])
    responses["graph"] = service.create_task_dependency_graph(mission_id, requests["graph"])

    requests["planner"] = build_planner_generation_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], plan=responses["plan"],
        snapshot=responses["snapshot"], decomposition=responses["decomposition"], graph=responses["graph"])
    responses["planner"] = service.invoke_planner_and_generate_plan(mission_id, requests["planner"])
    requests["validation"] = build_plan_validation_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], generated=responses["planner"])
    responses["validation"] = service.validate_generated_plan_feasibility(mission_id, requests["validation"])
    requests["activation"] = build_plan_activation_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], validation=responses["validation"])
    responses["activation"] = service.activate_initial_plan_version(mission_id, requests["activation"])
    requests["readiness"] = build_readiness_projection_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], active=responses["activation"])
    responses["readiness"] = service.create_task_readiness_projection(mission_id, requests["readiness"])

    requests["scope"] = build_scope_request(run_id=run_id)
    responses["scope"] = service.put_mission_scope_contract(mission_id, requests["scope"])
    requests["binding"] = build_governance_binding_request(run_id=run_id)
    responses["binding"] = service.put_mission_governance_binding(mission_id, requests["binding"])

    tasks = service.list_planned_tasks(mission_id)["planned_tasks"]
    root = next(t for t in tasks if t["task_key"] == "collect-cti")
    requests["routing"] = build_routing_intent_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], active=responses["activation"],
        readiness=responses["readiness"], planned_task_id=root["planned_task_id"])
    responses["routing"] = service.create_task_routing_intent(mission_id, requests["routing"])
    requests["eligibility"] = build_routing_eligibility_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], active=responses["activation"],
        readiness=responses["readiness"], routing=responses["routing"])
    responses["eligibility"] = service.create_task_routing_eligibility_gate(mission_id, requests["eligibility"])
    requests["route"] = build_route_selection_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], active=responses["activation"],
        readiness=responses["readiness"], routing=responses["routing"], eligibility=responses["eligibility"])
    responses["route"] = service.create_task_route_selection_decision(mission_id, requests["route"])
    requests["authorization"] = build_delegation_authorization_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], active=responses["activation"],
        route=responses["route"])
    responses["authorization"] = service.authorize_task_delegation(mission_id, requests["authorization"])
    if stop_after_authorization:
        return mission_id, requests, responses

    requests["delegation"] = build_delegation_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], active=responses["activation"],
        route=responses["route"], authorization=responses["authorization"])
    responses["delegation"] = service.create_task_delegation(mission_id, requests["delegation"])
    requests["delivery"] = build_delegation_delivery_request(
        run_id=run_id, expected_version_sha256=_vector(service, mission_id),
        expected_state_version=_state(service, mission_id)["state_version"], active=responses["activation"],
        delegation=responses["delegation"])
    responses["delivery"] = service.deliver_task_delegation(mission_id, requests["delivery"])
    return mission_id, requests, responses


def test_01_contract_is_canonical_hashed_and_binds_stage393_predecessor():
    contract = canonical_routing_delegation_governance_qualification_contract()
    assert verify_routing_delegation_governance_qualification_contract(contract)
    assert contract["schema_version"] == ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_SCHEMA_VERSION
    assert contract["predecessor_control"] == ROUTING_DELEGATION_GOVERNANCE_PREDECESSOR_CONTROL
    assert contract["qualified_segment_head"]["selected_subsystem"] == "CTI"
    assert contract["qualified_segment_head"]["selected_capability"] == "cti.read.context"
    assert contract["qualified_segment_head"]["dispatch_performed"] is False
    assert contract["continuity_requirements"]["pre_dispatch_governance_revalidation_remains_required"] is True


def test_02_health_activates_stage394_without_migration_or_new_authority(tmp_path):
    service, _ = make_service(tmp_path / "health394.db")
    h = service.health()
    assert h["control_version"] == CURRENT_CONTROL
    assert h["supported_controls"][-7:] == ["stage3.9.4-routing-delegation-governance-continuity", "stage3.9.5-dispatch-execution-evidence-continuity", "stage3.9.6-task-completion-mission-outcome-closure", "stage3.9.7-adaptation-replanning-e2e-scenario", "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CURRENT_CONTROL]
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["stage3_9_4_runtime_verifier_read_only"] is True
    assert h["stage3_9_4_authoritative_governance_required"] is True
    assert h["stage3_9_4_pre_dispatch_governance_revalidation_required"] is True
    assert h["stage3_9_4_new_database_migration_added"] is False
    assert h["stage3_9_4_new_dispatch_authority_added"] is False
    assert h["stage3_9_4_next_stage"] == "3.9.5"


def test_03_canonical_trajectory_qualifies_end_to_end_to_ownership(tmp_path):
    service, gov = make_service(tmp_path / "success394.db")
    mission_id, _, responses = provision_stage394(service, "success394")
    proof = service.get_e2e_routing_delegation_governance_qualification(mission_id)
    assert proof["qualification"]["status"] == "QUALIFIED"
    assert proof["qualification"]["failed_check_ids"] == []
    assert responses["route"]["selected_subsystem"] == "CTI"
    assert responses["route"]["selected_capability"] == "cti.read.context"
    assert responses["authorization"]["authorization_status"] == "AUTHORIZED"
    assert responses["authorization"]["authorization_granted"] is True
    assert responses["delivery"]["ownership_status"] == "ACCEPTED"
    assert gov.evaluate_calls == 1


def test_04_only_dependency_ready_root_task_routes(tmp_path):
    service, _ = make_service(tmp_path / "ready394.db")
    mission_id, _, responses = provision_stage394(service, "ready394")
    readiness = responses["readiness"]["projection_contract"]["projection"]
    assert readiness["ready_task_keys"] == ["collect-cti"]
    assert readiness["blocked_task_keys"] == ["analyze-cti", "report-findings"]
    intents = service.get_task_routing_intent_history(mission_id)["routing_intents"]
    assert len(intents) == 1
    root_id = next(t["planned_task_id"] for t in service.list_planned_tasks(mission_id)["planned_tasks"] if t["task_key"] == "collect-cti")
    assert intents[0]["planned_task_id"] == root_id


def test_05_exact_event_sequence_and_repository_footprint_are_frozen(tmp_path):
    service, _ = make_service(tmp_path / "footprint394.db")
    mission_id, _, _ = provision_stage394(service, "footprint394")
    events = service.get_mission_events(mission_id)
    assert events["integrity_status"] == "PASS"
    assert [e["event_type"] for e in events["events"]] == list(ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES)
    assert len(events["events"]) == 22
    counts = service.repository.get_repository_record_counts(mission_id)
    assert {k: v for k, v in counts.items() if v} == ROUTING_DELEGATION_GOVERNANCE_ALLOWED_NONZERO_REPOSITORY_COUNTS


def test_06_verifier_is_read_only_and_does_not_requery_governance(tmp_path):
    service, gov = make_service(tmp_path / "readonly394.db")
    mission_id, _, _ = provision_stage394(service, "readonly394")
    before = service.repository.get_repository_record_counts(mission_id)
    calls = gov.evaluate_calls
    first = service.get_e2e_routing_delegation_governance_qualification(mission_id)
    second = service.get_e2e_routing_delegation_governance_qualification(mission_id)
    assert first["qualification"] == second["qualification"]
    assert first["read_only"] is True
    assert service.repository.get_repository_record_counts(mission_id) == before
    assert gov.evaluate_calls == calls == 1


def test_07_stage394_mutations_are_idempotent_without_duplicate_governance_query(tmp_path):
    service, gov = make_service(tmp_path / "replay394.db")
    mission_id, requests, responses = provision_stage394(service, "replay394")
    before = service.repository.get_repository_record_counts(mission_id)
    assert service.invoke_planner_and_generate_plan(mission_id, requests["planner"])["idempotent_replay"] is True
    assert service.validate_generated_plan_feasibility(mission_id, requests["validation"])["idempotent_replay"] is True
    assert service.activate_initial_plan_version(mission_id, requests["activation"])["idempotent_replay"] is True
    assert service.create_task_readiness_projection(mission_id, requests["readiness"])["idempotent_replay"] is True
    assert service.put_mission_scope_contract(mission_id, requests["scope"])["idempotent_replay"] is True
    assert service.put_mission_governance_binding(mission_id, requests["binding"])["idempotent_replay"] is True
    assert service.create_task_routing_intent(mission_id, requests["routing"])["idempotent_replay"] is True
    assert service.create_task_routing_eligibility_gate(mission_id, requests["eligibility"])["idempotent_replay"] is True
    assert service.create_task_route_selection_decision(mission_id, requests["route"])["idempotent_replay"] is True
    assert service.authorize_task_delegation(mission_id, requests["authorization"])["idempotent_replay"] is True
    assert service.create_task_delegation(mission_id, requests["delegation"])["idempotent_replay"] is True
    assert service.deliver_task_delegation(mission_id, requests["delivery"])["idempotent_replay"] is True
    assert service.repository.get_repository_record_counts(mission_id) == before
    assert gov.evaluate_calls == 1
    assert responses["authorization"]["policy_decision_id"] == service.get_task_delegation_authorization_history(mission_id)["delegation_authorizations"][0]["policy_decision_id"]


def test_08_governance_deny_is_durable_fail_closed_and_cannot_qualify(tmp_path):
    gov = FakeGovernanceClient(); gov.emergency_stop = True
    service, _ = make_service(tmp_path / "deny394.db", gov)
    mission_id, _, responses = provision_stage394(service, "deny394", stop_after_authorization=True)
    assert responses["authorization"]["authorization_status"] == "DENIED"
    assert responses["authorization"]["authorization_granted"] is False
    assert service.get_task_delegation_history(mission_id)["task_delegations"] == []
    assert service.get_delegation_delivery_history(mission_id)["delegation_deliveries"] == []
    proof = service.get_e2e_routing_delegation_governance_qualification(mission_id)["qualification"]
    assert proof["status"] == "REJECTED"
    assert "EXACT_SINGLE_READY_TASK_ROUTING_TRAJECTORY" in proof["failed_check_ids"]
    assert gov.evaluate_calls == 1


def test_09_restart_reconstructs_same_qualification_without_external_query(tmp_path):
    db = tmp_path / "restart394.db"
    service, gov = make_service(db)
    mission_id, _, _ = provision_stage394(service, "restart394")
    expected = service.get_e2e_routing_delegation_governance_qualification(mission_id)["qualification"]
    replacement = FakeGovernanceClient()
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(db)), governance_client=replacement, cti_client=replacement)
    observed = restarted.get_e2e_routing_delegation_governance_qualification(mission_id)["qualification"]
    assert observed == expected
    assert replacement.evaluate_calls == 0
    assert gov.evaluate_calls == 1


def test_10_no_stage395_dispatch_execution_or_target_actuation_is_materialized(tmp_path):
    service, _ = make_service(tmp_path / "boundary394.db")
    mission_id, _, _ = provision_stage394(service, "boundary394")
    counts = service.repository.get_repository_record_counts(mission_id)
    for table in (
        "mission_execution_dispatches", "mission_dispatch_eligibility_gates",
        "mission_pre_dispatch_governance_revalidations", "mission_execution_attempts",
        "mission_execution_deliveries", "mission_execution_running_projections", "mission_execution_result_captures",
    ):
        assert counts.get(table, 0) == 0
    proof = service.get_e2e_routing_delegation_governance_qualification(mission_id)
    assert proof["dispatch_performed"] is False
    assert proof["execution_performed"] is False
    assert proof["target_actuation"] is False


def test_11_contract_endpoint_definition_matches_runtime_definition(tmp_path):
    service, _ = make_service(tmp_path / "definition394.db")
    payload = service.get_e2e_routing_delegation_governance_qualification_contract_definition()
    assert payload["control_version"] == CURRENT_CONTROL
    assert payload["contract"] == canonical_routing_delegation_governance_qualification_contract()
    assert payload["definition"]["next_stage"] == "3.9.5"


def test_12_invalid_run_id_builder_fails_closed():
    with pytest.raises(ValueError):
        build_scope_request(run_id="bad run")
