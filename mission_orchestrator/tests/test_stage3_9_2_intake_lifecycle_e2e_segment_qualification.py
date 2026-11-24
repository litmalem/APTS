from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.e2e_intake_lifecycle_qualification import (
    INTAKE_LIFECYCLE_ALLOWED_NONZERO_REPOSITORY_COUNTS,
    INTAKE_LIFECYCLE_COMMAND_SEQUENCE,
    INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES,
    INTAKE_LIFECYCLE_QUALIFICATION_DATABASE_CHANGE_MODE,
    INTAKE_LIFECYCLE_QUALIFICATION_EXPECTED_MIGRATION_LEVEL,
    INTAKE_LIFECYCLE_QUALIFICATION_MODE,
    INTAKE_LIFECYCLE_QUALIFICATION_NEXT_STAGE,
    INTAKE_LIFECYCLE_QUALIFICATION_PREDECESSOR_CONTROL,
    INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION,
    INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE,
    INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION,
    build_intake_lifecycle_command_request,
    canonical_intake_lifecycle_qualification_contract,
    canonical_intake_lifecycle_qualification_definition,
    verify_intake_lifecycle_qualification_contract,
)
from mission_orchestrator.e2e_mission_acceptance import (
    E2E_MISSION_SCENARIO_ID,
    canonical_e2e_mission_acceptance_contract,
    materialize_canonical_e2e_mission_request,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService

CURRENT_CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE392_CONTROL = "stage3.9.2-intake-lifecycle-e2e-segment-qualification"
PREDECESSOR_CONTROL = "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract"


class NoExternalClient:
    base_url = "disabled://stage392-no-external"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.9.2 must not call external dependency: {name}")


def make_service(db: Path) -> CanonicalMissionService:
    client = NoExternalClient()
    return CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=client,
        cti_client=client,
    )


def create_canonical(service: CanonicalMissionService, run_id: str) -> tuple[str, dict]:
    request = materialize_canonical_e2e_mission_request(run_id)
    created = service.create_mission(request)
    return created["canonical_identity"]["mission_id"], request


def execute_segment_command(service: CanonicalMissionService, mission_id: str, run_id: str, command: str):
    state = service.get_mission_state(mission_id)["mission_state"]
    version = service.get_mission_version_vector(mission_id)
    request = build_intake_lifecycle_command_request(
        run_id=run_id,
        command=command,
        expected_version_sha256=version["version_sha256"],
        expected_state_version=state["state_version"],
    )
    return request, service.execute_mission_lifecycle_command(mission_id, request)


def qualify(service: CanonicalMissionService, run_id: str):
    mission_id, request = create_canonical(service, run_id)
    bind_req, bind = execute_segment_command(service, mission_id, run_id, "BIND_PIP")
    plan_req, planning = execute_segment_command(service, mission_id, run_id, "START_PLANNING")
    proof = service.get_e2e_intake_lifecycle_qualification(mission_id)
    return mission_id, request, bind_req, bind, plan_req, planning, proof


def test_01_qualification_contract_is_canonical_hashed_and_bound_to_stage391_source():
    contract = canonical_intake_lifecycle_qualification_contract()
    stage391 = canonical_e2e_mission_acceptance_contract()
    assert verify_intake_lifecycle_qualification_contract(contract)
    assert contract["schema_version"] == INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION
    assert contract["mode"] == INTAKE_LIFECYCLE_QUALIFICATION_MODE
    assert contract["predecessor_control"] == PREDECESSOR_CONTROL
    assert contract["source_scenario_id"] == E2E_MISSION_SCENARIO_ID
    assert contract["source_acceptance_contract_sha256"] == stage391["integrity"]["canonical_sha256"]
    assert contract["expected_repository_migration_level"] == 53
    assert contract["database_change_mode"] == INTAKE_LIFECYCLE_QUALIFICATION_DATABASE_CHANGE_MODE
    assert contract["verification_boundary"]["runtime_verifier_read_only"] is True
    for key, value in contract["verification_boundary"].items():
        if key.startswith("new_"):
            assert value is False


def test_02_contract_freezes_created_to_pip_bound_to_planning_and_no_plan_materialization():
    contract = canonical_intake_lifecycle_qualification_contract()
    assert [(x["command"], x["from_state"], x["to_state"]) for x in contract["command_sequence"]] == [
        ("BIND_PIP", "CREATED", "PIP_BOUND"),
        ("START_PLANNING", "PIP_BOUND", "PLANNING"),
    ]
    assert contract["qualified_segment_head"] == {
        "state": "PLANNING",
        "state_version": 3,
        "plan_materialized": False,
        "planner_invoked": False,
    }
    assert contract["expected_event_types"] == list(INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES)
    assert contract["expected_repository_nonzero_counts"] == INTAKE_LIFECYCLE_ALLOWED_NONZERO_REPOSITORY_COUNTS


def test_03_health_activates_stage392_after_stage391_without_authority_or_migration_expansion(tmp_path):
    health = make_service(tmp_path / "health392.db").health()
    assert health["control_version"] == CURRENT_CONTROL
    assert health["supported_controls"][-9:] == [STAGE392_CONTROL, "stage3.9.3-planning-task-graph-dependency-verification", "stage3.9.4-routing-delegation-governance-continuity", "stage3.9.5-dispatch-execution-evidence-continuity", "stage3.9.6-task-completion-mission-outcome-closure", "stage3.9.7-adaptation-replanning-e2e-scenario", "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CURRENT_CONTROL]
    assert health["mission_repository_migration_level"] == 53
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert health["stage3_9_2_intake_lifecycle_qualification_schema_version"] == INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION
    assert health["stage3_9_2_intake_lifecycle_qualification_predecessor_control"] == PREDECESSOR_CONTROL
    assert health["stage3_9_2_intake_lifecycle_qualification_terminal_state"] == "PLANNING"
    assert health["stage3_9_2_intake_lifecycle_qualification_terminal_state_version"] == 3
    assert health["stage3_9_2_intake_lifecycle_qualification_runtime_verifier_read_only"] is True
    assert health["stage3_9_2_intake_lifecycle_qualification_existing_public_routes_only"] is True
    for field in (
        "new_governance_authority_added", "new_routing_authority_added", "new_delegation_authority_added",
        "new_dispatch_authority_added", "new_execution_authority_added", "new_target_actuation_authority_added",
        "new_external_network_io_added", "new_telemetry_export_added", "new_planner_authority_added",
        "new_database_migration_added", "new_durable_store_added",
    ):
        assert health[f"stage3_9_2_intake_lifecycle_qualification_{field}"] is False


def test_04_command_builder_is_deterministic_run_bound_and_fail_closed():
    request = build_intake_lifecycle_command_request(
        run_id="run-392-A",
        command="BIND_PIP",
        expected_version_sha256="a" * 64,
        expected_state_version=1,
    )
    assert request == build_intake_lifecycle_command_request(
        run_id="run-392-A", command="BIND_PIP", expected_version_sha256="a" * 64, expected_state_version=1
    )
    assert request["command_id"] == "stage392-run-392-A-bind-pip"
    assert request["metadata"] == {
        "stage": "3.9.2", "scenario_id": E2E_MISSION_SCENARIO_ID,
        "run_id": "run-392-A", "segment": "INTAKE_TO_LIFECYCLE",
    }
    with pytest.raises(ValueError):
        build_intake_lifecycle_command_request(run_id="bad run", command="BIND_PIP", expected_version_sha256="a" * 64, expected_state_version=1)
    with pytest.raises(ValueError):
        build_intake_lifecycle_command_request(run_id="run", command="START", expected_version_sha256="a" * 64, expected_state_version=1)
    with pytest.raises(ValueError):
        build_intake_lifecycle_command_request(run_id="run", command="BIND_PIP", expected_version_sha256="short", expected_state_version=1)


def test_05_canonical_segment_executes_frozen_stage391_intake_to_planning(tmp_path):
    service = make_service(tmp_path / "success392.db")
    mission_id, request, _, bind, _, planning, proof = qualify(service, "success392")
    assert request == materialize_canonical_e2e_mission_request("success392")
    assert bind["mission_state"]["state"] == "PIP_BOUND"
    assert bind["mission_state"]["state_version"] == 2
    assert bind["mission_activation"]["activation_ready"] is True
    assert planning["mission_state"]["state"] == "PLANNING"
    assert planning["mission_state"]["state_version"] == 3
    assert planning["planning_run_activation"]["pip_activation_proof"]["valid"] is True
    assert planning["planning_run_activation"]["planner_invocation_performed"] is False
    assert planning["planning_run_activation"]["plan_artifact_created"] is False
    assert proof["mission_id"] == mission_id
    assert proof["qualification"]["status"] == "QUALIFIED"
    assert proof["qualification"]["qualified"] is True
    assert proof["qualification"]["failed_check_ids"] == []


def test_06_exact_replays_are_idempotent_and_do_not_duplicate_segment_footprint(tmp_path):
    service = make_service(tmp_path / "replay392.db")
    mission_id, create_req, bind_req, _, plan_req, _, proof = qualify(service, "replay392")
    before = service.repository.get_repository_record_counts(mission_id)
    assert service.create_mission(create_req)["idempotent_replay"] is True
    assert service.execute_mission_lifecycle_command(mission_id, bind_req)["idempotent_replay"] is True
    assert service.execute_mission_lifecycle_command(mission_id, plan_req)["idempotent_replay"] is True
    after = service.repository.get_repository_record_counts(mission_id)
    assert before == after
    assert {k: v for k, v in after.items() if v} == INTAKE_LIFECYCLE_ALLOWED_NONZERO_REPOSITORY_COUNTS
    assert service.get_e2e_intake_lifecycle_qualification(mission_id)["qualification"] == proof["qualification"]


def test_07_qualification_proof_has_exact_transition_command_event_and_identity_lineage(tmp_path):
    service = make_service(tmp_path / "lineage392.db")
    mission_id, *_ = qualify(service, "lineage392")
    transitions = service.get_mission_state_history(mission_id)["transitions"]
    commands = service.get_mission_command_history(mission_id)["commands"]
    events = service.get_mission_events(mission_id)["events"]
    assert [(x["from_state"], x["to_state"], x["from_state_version"], x["to_state_version"]) for x in transitions] == [
        ("CREATED", "PIP_BOUND", 1, 2), ("PIP_BOUND", "PLANNING", 2, 3)
    ]
    assert all(x["transition_id"].startswith("mtrans-") for x in transitions)
    assert [x["event_type"] for x in events] == list(INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES)
    assert all(x["event_id"].startswith("mevent-") for x in events)
    assert all(x["mission_id"] == mission_id for x in transitions + events)
    assert [x["operation"] for x in commands] == ["LIFECYCLE_COMMAND", "LIFECYCLE_COMMAND"]


def test_08_event_hash_chain_and_causation_survive_segment_qualification(tmp_path):
    service = make_service(tmp_path / "events392.db")
    mission_id, *_ = qualify(service, "events392")
    view = service.get_mission_events(mission_id)
    assert view["integrity_status"] == "PASS"
    events = view["events"]
    assert events[0]["previous_event_sha256"] is None
    for previous, current in zip(events, events[1:]):
        assert current["previous_event_sha256"] == previous["canonical_sha256"]
        assert current["parent_event_id"] == previous["event_id"]
    assert events[1]["causation_id"].startswith("mtrans-")
    assert events[2]["causation_id"].startswith("stage392-")


def test_09_incomplete_created_segment_is_rejected_read_only(tmp_path):
    service = make_service(tmp_path / "created392.db")
    mission_id, _ = create_canonical(service, "created392")
    before = service.repository.get_repository_record_counts(mission_id)
    result = service.get_e2e_intake_lifecycle_qualification(mission_id)
    after = service.repository.get_repository_record_counts(mission_id)
    assert result["qualification"]["status"] == "REJECTED"
    assert "FINAL_LIFECYCLE_STATE" in result["qualification"]["failed_check_ids"]
    assert result["read_only"] is True
    assert before == after


def test_10_partial_pip_bound_segment_is_rejected_until_planning_head(tmp_path):
    service = make_service(tmp_path / "partial392.db")
    mission_id, _ = create_canonical(service, "partial392")
    execute_segment_command(service, mission_id, "partial392", "BIND_PIP")
    result = service.get_e2e_intake_lifecycle_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert result["segment_head"]["state"] == "PIP_BOUND"
    assert "FINAL_LIFECYCLE_STATE" in result["failed_check_ids"]
    assert "EXACT_LIFECYCLE_COMMAND_SEQUENCE" in result["failed_check_ids"]


def test_11_noncanonical_request_cannot_be_certified_even_with_same_lifecycle_shape(tmp_path):
    service = make_service(tmp_path / "noncanonical392.db")
    request = materialize_canonical_e2e_mission_request("noncanonical392")
    request["objective"] = {"type": "CONTROL_PLANE_E2E_ACCEPTANCE", "target_ref": "wrong-target"}
    mission_id = service.create_mission(request)["canonical_identity"]["mission_id"]
    execute_segment_command(service, mission_id, "noncanonical392", "BIND_PIP")
    execute_segment_command(service, mission_id, "noncanonical392", "START_PLANNING")
    result = service.get_e2e_intake_lifecycle_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert "FROZEN_STAGE391_REQUEST_SEMANTICS" in result["failed_check_ids"]


def test_12_downstream_domains_remain_unmaterialized_at_stage392_head(tmp_path):
    service = make_service(tmp_path / "boundary392.db")
    mission_id, *_ = qualify(service, "boundary392")
    counts = service.repository.get_repository_record_counts(mission_id)
    assert {k: v for k, v in counts.items() if v} == INTAKE_LIFECYCLE_ALLOWED_NONZERO_REPOSITORY_COUNTS
    for key in (
        "mission_plans", "mission_planner_input_snapshots", "mission_task_decompositions",
        "mission_planned_tasks", "mission_task_dependency_graphs", "mission_task_routing_intents",
        "mission_task_delegations", "mission_execution_dispatch_contracts", "mission_execution_attempts",
        "mission_task_outcomes", "mission_adaptation_replan_contracts",
    ):
        assert counts[key] == 0


def test_13_restart_stable_read_only_verification_uses_durable_segment_evidence(tmp_path):
    db = tmp_path / "restart392.db"
    first = make_service(db)
    mission_id, *_ = qualify(first, "restart392")
    proof1 = first.get_e2e_intake_lifecycle_qualification(mission_id)
    second = make_service(db)
    proof2 = second.get_e2e_intake_lifecycle_qualification(mission_id)
    assert proof1["qualification"] == proof2["qualification"]
    assert proof2["qualification"]["status"] == "QUALIFIED"
    assert second.get_mission_state(mission_id)["mission_state"]["state"] == "PLANNING"


def test_14_http_contract_and_mission_qualification_routes_are_deterministic_read_only(tmp_path):
    db = tmp_path / "http392.db"
    service = make_service(db)
    mission_id, *_ = qualify(service, "http392")
    before = service.repository.get_repository_record_counts(mission_id)
    handler = type("Stage392Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/api/e2e/intake-lifecycle-qualification-contract") as response:
            contract = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-intake-lifecycle-qualification") as response:
            proof1 = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-intake-lifecycle-qualification") as response:
            proof2 = json.loads(response.read().decode("utf-8"))
        assert contract == service.get_e2e_intake_lifecycle_qualification_contract_definition()
        assert proof1 == proof2
        assert proof1["qualification"]["status"] == "QUALIFIED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert service.repository.get_repository_record_counts(mission_id) == before


def test_15_definition_closes_stage392_and_hands_off_exact_planning_head_to_stage393(tmp_path):
    definition = canonical_intake_lifecycle_qualification_definition()
    assert definition["schema_version"] == INTAKE_LIFECYCLE_QUALIFICATION_SCHEMA_VERSION
    assert definition["predecessor_control"] == INTAKE_LIFECYCLE_QUALIFICATION_PREDECESSOR_CONTROL
    assert definition["expected_repository_migration_level"] == INTAKE_LIFECYCLE_QUALIFICATION_EXPECTED_MIGRATION_LEVEL
    assert definition["qualified_segment_head_state"] == INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE
    assert definition["qualified_segment_head_state_version"] == INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION
    assert definition["runtime_verifier_read_only"] is True
    assert definition["new_durable_store_added"] is False
    assert definition["new_database_migration_added"] is False
    assert definition["new_execution_authority_added"] is False
    assert definition["next_stage"] == INTAKE_LIFECYCLE_QUALIFICATION_NEXT_STAGE == "3.9.3"
    service_definition = make_service(tmp_path / "definition392.db").get_e2e_intake_lifecycle_qualification_contract_definition()
    assert service_definition["control_version"] == CURRENT_CONTROL
    assert service_definition["definition"] == definition
    assert verify_intake_lifecycle_qualification_contract(service_definition["contract"])
