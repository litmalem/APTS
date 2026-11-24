from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.e2e_intake_lifecycle_qualification import build_intake_lifecycle_command_request
from mission_orchestrator.e2e_mission_acceptance import materialize_canonical_e2e_mission_request
from mission_orchestrator.e2e_planning_task_graph_qualification import (
    PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS,
    PLANNING_TASK_GRAPH_EDGES,
    PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES,
    PLANNING_TASK_GRAPH_QUALIFICATION_EDGE_COUNT,
    PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE,
    PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE_VERSION,
    PLANNING_TASK_GRAPH_QUALIFICATION_EXPECTED_MIGRATION_LEVEL,
    PLANNING_TASK_GRAPH_QUALIFICATION_GRAPH_STATUS,
    PLANNING_TASK_GRAPH_QUALIFICATION_NEXT_STAGE,
    PLANNING_TASK_GRAPH_QUALIFICATION_PREDECESSOR_CONTROL,
    PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION,
    PLANNING_TASK_GRAPH_QUALIFICATION_TASK_COUNT,
    PLANNING_TASK_GRAPH_TASK_KEYS,
    build_planning_dependency_graph_request,
    build_planning_decomposition_request,
    build_planning_plan_request,
    build_planning_snapshot_request,
    canonical_planning_dependency_edges,
    canonical_planning_task_graph_qualification_contract,
    canonical_planning_task_graph_qualification_definition,
    canonical_planning_task_specs,
    verify_planning_task_graph_qualification_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService

CURRENT_CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PREDECESSOR_CONTROL = "stage3.9.2-intake-lifecycle-e2e-segment-qualification"


class NoExternalClient:
    base_url = "disabled://stage393-no-external"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(f"Stage 3.9.3 must not call external dependency: {name}")


def make_service(db: Path) -> CanonicalMissionService:
    client = NoExternalClient()
    return CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=client,
        cti_client=client,
    )


def create_and_activate(service: CanonicalMissionService, run_id: str) -> str:
    created = service.create_mission(materialize_canonical_e2e_mission_request(run_id))
    mission_id = created["canonical_identity"]["mission_id"]
    for command in ("BIND_PIP", "START_PLANNING"):
        state = service.get_mission_state(mission_id)["mission_state"]
        vector = service.get_mission_version_vector(mission_id)
        request = build_intake_lifecycle_command_request(
            run_id=run_id,
            command=command,
            expected_version_sha256=vector["version_sha256"],
            expected_state_version=state["state_version"],
        )
        service.execute_mission_lifecycle_command(mission_id, request)
    return mission_id


def execute_stage393(service: CanonicalMissionService, mission_id: str, run_id: str):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    plan_req = build_planning_plan_request(
        run_id=run_id,
        expected_version_sha256=vector["version_sha256"],
        expected_state_version=state["state_version"],
    )
    plan = service.create_mission_plan_contract(mission_id, plan_req)

    state = service.get_mission_state(mission_id)["mission_state"]
    snapshot_req = build_planning_snapshot_request(
        run_id=run_id, plan=plan, expected_state_version=state["state_version"]
    )
    snapshot = service.create_planner_input_snapshot(mission_id, snapshot_req)

    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    decomp_req = build_planning_decomposition_request(
        run_id=run_id,
        expected_version_sha256=vector["version_sha256"],
        expected_state_version=state["state_version"],
        plan=plan,
        snapshot=snapshot,
    )
    decomposition = service.create_task_decomposition(mission_id, decomp_req)

    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    graph_req = build_planning_dependency_graph_request(
        run_id=run_id,
        expected_version_sha256=vector["version_sha256"],
        expected_state_version=state["state_version"],
        plan=plan,
        snapshot=snapshot,
        decomposition=decomposition,
    )
    graph = service.create_task_dependency_graph(mission_id, graph_req)
    proof = service.get_e2e_planning_task_graph_qualification(mission_id)
    return plan_req, plan, snapshot_req, snapshot, decomp_req, decomposition, graph_req, graph, proof


def qualify(service: CanonicalMissionService, run_id: str):
    mission_id = create_and_activate(service, run_id)
    return (mission_id, *execute_stage393(service, mission_id, run_id))


def test_01_contract_is_canonical_hashed_and_bound_to_stage392():
    contract = canonical_planning_task_graph_qualification_contract()
    assert verify_planning_task_graph_qualification_contract(contract)
    assert contract["schema_version"] == PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION
    assert contract["predecessor_control"] == PREDECESSOR_CONTROL
    assert contract["entry_head"] == {"state": "PLANNING", "state_version": 3, "plan_materialized": False}
    assert contract["canonical_task_keys"] == list(PLANNING_TASK_GRAPH_TASK_KEYS)
    assert contract["canonical_dependency_edges"] == canonical_planning_dependency_edges()
    assert contract["expected_repository_migration_level"] == 53
    for key, value in contract["verification_boundary"].items():
        if key.startswith("new_"):
            assert value is False


def test_02_contract_freezes_exact_task_graph_and_dependency_verification_head():
    contract = canonical_planning_task_graph_qualification_contract()
    head = contract["qualified_segment_head"]
    assert head["state"] == "PLANNING" and head["state_version"] == 3
    assert head["task_count"] == 3 and head["edge_count"] == 2
    assert head["graph_validation_status"] == "PASS"
    assert head["planner_invoked"] is False
    assert head["generated_plan_materialized"] is False
    assert head["readiness_projected"] is False
    assert contract["dependency_verification"]["expected_topological_task_keys"] == list(PLANNING_TASK_GRAPH_TASK_KEYS)


def test_03_health_activates_stage393_without_migration_or_authority_expansion(tmp_path):
    health = make_service(tmp_path / "health393.db").health()
    assert health["control_version"] == CURRENT_CONTROL
    assert health["supported_controls"][-9:] == [
        PREDECESSOR_CONTROL,
        "stage3.9.3-planning-task-graph-dependency-verification",
        "stage3.9.4-routing-delegation-governance-continuity",
        "stage3.9.5-dispatch-execution-evidence-continuity",
        "stage3.9.6-task-completion-mission-outcome-closure",
        "stage3.9.7-adaptation-replanning-e2e-scenario",
        "stage3.9.8-restart-replay-recovery-e2e-verification",
        "stage3.9.9-global-observation-reconstruction-forensic-equivalence",
        CURRENT_CONTROL,
    ]
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["stage3_9_3_planning_task_graph_qualification_schema_version"] == PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION
    assert health["stage3_9_3_planning_task_graph_qualification_graph_status"] == "PASS"
    assert health["stage3_9_3_planning_task_graph_qualification_task_count"] == 3
    assert health["stage3_9_3_planning_task_graph_qualification_edge_count"] == 2
    assert health["stage3_9_3_planning_task_graph_qualification_runtime_verifier_read_only"] is True
    for field in (
        "new_planner_authority_added", "new_governance_authority_added", "new_routing_authority_added",
        "new_delegation_authority_added", "new_dispatch_authority_added", "new_execution_authority_added",
        "new_target_actuation_authority_added", "new_external_network_io_added", "new_telemetry_export_added",
        "new_database_migration_added", "new_durable_store_added",
    ):
        assert health[f"stage3_9_3_planning_task_graph_qualification_{field}"] is False


def test_04_request_builders_are_deterministic_run_bound_and_fail_closed():
    plan = build_planning_plan_request(run_id="run393", expected_version_sha256="a" * 64, expected_state_version=3)
    assert plan == build_planning_plan_request(run_id="run393", expected_version_sha256="a" * 64, expected_state_version=3)
    assert plan["idempotency_key"] == "stage393-run393-plan"
    assert canonical_planning_task_specs("run393")[0]["metadata"]["run_id"] == "run393"
    assert canonical_planning_dependency_edges() == [
        {"from_task_key": "collect-cti", "to_task_key": "analyze-cti"},
        {"from_task_key": "analyze-cti", "to_task_key": "report-findings"},
    ]
    with pytest.raises(ValueError):
        build_planning_plan_request(run_id="bad run", expected_version_sha256="a" * 64, expected_state_version=3)


def test_05_canonical_segment_materializes_plan_snapshot_tasks_and_validated_dag(tmp_path):
    service = make_service(tmp_path / "success393.db")
    mission_id, _, plan, _, snapshot, _, decomposition, _, graph, proof = qualify(service, "success393")
    assert plan["plan_id"].startswith("mplan-") and plan["plan_version"] == 1
    assert snapshot["snapshot_id"].startswith("mpis-") and snapshot["snapshot_version"] == 1
    assert decomposition["decomposition_id"].startswith("mdecomp-") and decomposition["task_count"] == 3
    assert graph["graph_id"].startswith("mgraph-") and graph["validation_status"] == "PASS"
    assert graph["node_count"] == 3 and graph["edge_count"] == 2
    assert proof["mission_id"] == mission_id
    assert proof["qualification"]["status"] == "QUALIFIED"
    assert proof["qualification"]["failed_check_ids"] == []


def test_06_dependency_graph_is_exact_dag_with_expected_topology(tmp_path):
    service = make_service(tmp_path / "dag393.db")
    mission_id, *_ = qualify(service, "dag393")
    graph = service.get_task_dependency_graph(mission_id)["task_dependency_graph"]
    payload = graph["graph"]
    assert payload["topological_task_keys"] == list(PLANNING_TASK_GRAPH_TASK_KEYS)
    assert payload["root_task_keys"] == ["collect-cti"]
    assert payload["leaf_task_keys"] == ["report-findings"]
    edges = service.list_task_dependency_edges(mission_id)["dependency_edges"]
    assert [(e["from_task_key"], e["to_task_key"]) for e in edges] == list(PLANNING_TASK_GRAPH_EDGES)


def test_07_exact_replay_of_all_stage393_mutations_is_idempotent_and_event_stable(tmp_path):
    service = make_service(tmp_path / "replay393.db")
    mission_id, plan_req, plan, snapshot_req, snapshot, decomp_req, decomposition, graph_req, graph, proof = qualify(service, "replay393")
    before = service.repository.get_repository_record_counts(mission_id)
    assert service.create_mission_plan_contract(mission_id, plan_req)["idempotent_replay"] is True
    assert service.create_planner_input_snapshot(mission_id, snapshot_req)["idempotent_replay"] is True
    assert service.create_task_decomposition(mission_id, decomp_req)["idempotent_replay"] is True
    assert service.create_task_dependency_graph(mission_id, graph_req)["idempotent_replay"] is True
    after = service.repository.get_repository_record_counts(mission_id)
    assert before == after
    assert {k: v for k, v in after.items() if v} == PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS
    assert service.get_e2e_planning_task_graph_qualification(mission_id)["qualification"] == proof["qualification"]


def test_08_event_lineage_extends_stage392_with_exact_four_planning_events(tmp_path):
    service = make_service(tmp_path / "events393.db")
    mission_id, *_ = qualify(service, "events393")
    event_view = service.get_mission_events(mission_id)
    assert event_view["integrity_status"] == "PASS"
    events = event_view["events"]
    assert [e["event_type"] for e in events] == list(PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES)
    assert len(events) == 9
    for previous, current in zip(events, events[1:]):
        assert current["previous_event_sha256"] == previous["canonical_sha256"]
        assert current["parent_event_id"] == previous["event_id"]
    assert events[-4]["causation_id"].startswith("mplan-")
    assert events[-3]["causation_id"].startswith("mpis-")
    assert events[-2]["causation_id"].startswith("mdecomp-")
    assert events[-1]["causation_id"].startswith("mgraph-")


def test_09_partial_stage392_head_is_rejected_until_plan_graph_exists(tmp_path):
    service = make_service(tmp_path / "partial393.db")
    mission_id = create_and_activate(service, "partial393")
    before = service.repository.get_repository_record_counts(mission_id)
    result = service.get_e2e_planning_task_graph_qualification(mission_id)
    assert result["qualification"]["status"] == "REJECTED"
    assert "CANONICAL_PLAN_VERIFIED" in result["qualification"]["failed_check_ids"]
    assert result["read_only"] is True
    assert service.repository.get_repository_record_counts(mission_id) == before


def test_10_partial_plan_snapshot_decomposition_is_rejected_until_dependency_graph(tmp_path):
    service = make_service(tmp_path / "partialgraph393.db")
    mission_id = create_and_activate(service, "partialgraph393")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    plan = service.create_mission_plan_contract(mission_id, build_planning_plan_request(run_id="partialgraph393", expected_version_sha256=vector["version_sha256"], expected_state_version=state["state_version"]))
    state = service.get_mission_state(mission_id)["mission_state"]
    snapshot = service.create_planner_input_snapshot(mission_id, build_planning_snapshot_request(run_id="partialgraph393", plan=plan, expected_state_version=state["state_version"]))
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    service.create_task_decomposition(mission_id, build_planning_decomposition_request(run_id="partialgraph393", expected_version_sha256=vector["version_sha256"], expected_state_version=state["state_version"], plan=plan, snapshot=snapshot))
    result = service.get_e2e_planning_task_graph_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert "DEPENDENCY_GRAPH_INTEGRITY_AND_STATUS" in result["failed_check_ids"]
    assert "DEPENDENCY_DAG_STRUCTURAL_VERIFICATION" in result["failed_check_ids"]


def test_11_noncanonical_stage391_request_cannot_be_certified(tmp_path):
    service = make_service(tmp_path / "noncanonical393.db")
    request = materialize_canonical_e2e_mission_request("noncanonical393")
    request["objective"] = {"type": "CONTROL_PLANE_E2E_ACCEPTANCE", "target_ref": "wrong-target"}
    mission_id = service.create_mission(request)["canonical_identity"]["mission_id"]
    for command in ("BIND_PIP", "START_PLANNING"):
        state = service.get_mission_state(mission_id)["mission_state"]
        vector = service.get_mission_version_vector(mission_id)
        service.execute_mission_lifecycle_command(mission_id, build_intake_lifecycle_command_request(run_id="noncanonical393", command=command, expected_version_sha256=vector["version_sha256"], expected_state_version=state["state_version"]))
    execute_stage393(service, mission_id, "noncanonical393")
    result = service.get_e2e_planning_task_graph_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert "FROZEN_STAGE391_REQUEST_SEMANTICS" in result["failed_check_ids"]


def test_12_downstream_planner_routing_dispatch_execution_domains_remain_unmaterialized(tmp_path):
    service = make_service(tmp_path / "boundary393.db")
    mission_id, *_ = qualify(service, "boundary393")
    counts = service.repository.get_repository_record_counts(mission_id)
    assert {k: v for k, v in counts.items() if v} == PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS
    for key in (
        "mission_planner_invocations", "mission_generated_plans", "mission_plan_validations",
        "mission_plan_versions", "mission_task_readiness_projections", "mission_task_routing_intents",
        "mission_task_delegations", "mission_execution_dispatch_contracts", "mission_execution_attempts",
        "mission_task_outcomes", "mission_adaptation_replan_contracts",
    ):
        assert counts[key] == 0


def test_13_restart_stable_read_only_verification_uses_durable_planning_evidence(tmp_path):
    db = tmp_path / "restart393.db"
    first = make_service(db)
    mission_id, *_ = qualify(first, "restart393")
    proof1 = first.get_e2e_planning_task_graph_qualification(mission_id)
    second = make_service(db)
    proof2 = second.get_e2e_planning_task_graph_qualification(mission_id)
    assert proof1["qualification"] == proof2["qualification"]
    assert proof2["qualification"]["status"] == "QUALIFIED"
    assert second.get_mission_state(mission_id)["mission_state"]["state"] == "PLANNING"


def test_14_http_contract_and_mission_qualification_routes_are_deterministic_read_only(tmp_path):
    db = tmp_path / "http393.db"
    service = make_service(db)
    mission_id, *_ = qualify(service, "http393")
    before = service.repository.get_repository_record_counts(mission_id)
    handler = type("Stage393Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/api/e2e/planning-task-graph-qualification-contract") as response:
            contract = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-planning-task-graph-qualification") as response:
            proof1 = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-planning-task-graph-qualification") as response:
            proof2 = json.loads(response.read().decode("utf-8"))
        assert contract == service.get_e2e_planning_task_graph_qualification_contract_definition()
        assert proof1 == proof2
        assert proof1["qualification"]["status"] == "QUALIFIED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert service.repository.get_repository_record_counts(mission_id) == before


def test_15_definition_closes_stage393_and_hands_off_exact_graph_head_to_stage394(tmp_path):
    definition = canonical_planning_task_graph_qualification_definition()
    assert definition["schema_version"] == PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION
    assert definition["predecessor_control"] == PLANNING_TASK_GRAPH_QUALIFICATION_PREDECESSOR_CONTROL
    assert definition["expected_repository_migration_level"] == PLANNING_TASK_GRAPH_QUALIFICATION_EXPECTED_MIGRATION_LEVEL
    assert definition["qualified_segment_head_state"] == PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE
    assert definition["qualified_segment_head_state_version"] == PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE_VERSION
    assert definition["qualified_graph_validation_status"] == PLANNING_TASK_GRAPH_QUALIFICATION_GRAPH_STATUS
    assert definition["qualified_task_count"] == PLANNING_TASK_GRAPH_QUALIFICATION_TASK_COUNT
    assert definition["qualified_edge_count"] == PLANNING_TASK_GRAPH_QUALIFICATION_EDGE_COUNT
    assert definition["runtime_verifier_read_only"] is True
    assert definition["new_durable_store_added"] is False
    assert definition["new_database_migration_added"] is False
    assert definition["new_execution_authority_added"] is False
    assert definition["next_stage"] == PLANNING_TASK_GRAPH_QUALIFICATION_NEXT_STAGE == "3.9.4"
    service_definition = make_service(tmp_path / "definition393.db").get_e2e_planning_task_graph_qualification_contract_definition()
    assert service_definition["control_version"] == CURRENT_CONTROL
    assert service_definition["definition"] == definition
    assert verify_planning_task_graph_qualification_contract(service_definition["contract"])
