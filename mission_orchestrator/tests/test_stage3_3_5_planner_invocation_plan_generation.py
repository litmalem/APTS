from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionPlannerGenerationConflict,
    MissionPlannerGenerationGuardRejected,
    MissionPlannerGenerationNotFound,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.planner_generation import (
    GENERATED_PLAN_ID_PREFIX,
    GENERATED_PLAN_SCHEMA_VERSION,
    GENERATED_PLAN_STATUS,
    PLANNER_ENGINE,
    PLANNER_ENGINE_VERSION,
    PLANNER_GENERATION_MODE,
    PLANNER_GENERATION_REQUIRED_STATE,
    PLANNER_INVOCATION_ID_PREFIX,
    PLANNER_INVOCATION_MODE,
    PLANNER_INVOCATION_SCHEMA_VERSION,
    PLANNER_PROFILE_CANONICAL_DAG_V1,
    PLANNING_STRATEGY,
    canonical_planner_generation_definition,
    generate_planner_output,
    verify_generated_plan_contract,
    verify_planner_invocation_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL

from tests.test_stage3_3_4_task_dependency_graph_structural_validation import (
    activate_planning,
    create_mission,
    execute,
    graph_request,
    make_service,
    plan_request,
    provision_decomposition,
    scope_payload,
    snapshot_request,
)


def provision_graph(service, key: str, *, with_scope: bool = False, edges=None):
    mission_id, plan, snapshot, decomp = provision_decomposition(service, key, with_scope=with_scope)
    graph = service.create_task_dependency_graph(
        mission_id, graph_request(service, mission_id, key, edges=edges)
    )
    return mission_id, plan, snapshot, decomp, graph


def planner_request(service, mission_id: str, key: str, **overrides) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    plan = service.get_mission_plan_contract(mission_id)
    snapshot = service.get_planner_input_snapshot(mission_id)
    decomp = service.get_task_decomposition(mission_id)
    graph = service.get_task_dependency_graph(mission_id)
    request = {
        "idempotency_key": f"stage335-planner-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": plan["plan_version"],
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snapshot["snapshot_id"],
        "expected_snapshot_version": snapshot["snapshot_version"],
        "expected_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_decomposition_id": decomp["decomposition_id"],
        "expected_decomposition_version": decomp["decomposition_version"],
        "expected_decomposition_sha256": decomp["canonical_sha256"],
        "expected_task_set_sha256": decomp["task_set_sha256"],
        "expected_graph_id": graph["graph_id"],
        "expected_graph_version": graph["graph_version"],
        "expected_graph_sha256": graph["canonical_sha256"],
        "expected_node_set_sha256": graph["node_set_sha256"],
        "expected_edge_set_sha256": graph["edge_set_sha256"],
        "expected_state_version": state["state_version"],
        "planner_profile": PLANNER_PROFILE_CANONICAL_DAG_V1,
        "created_by": "stage3.3.5-pytest",
        "reason": "Invoke deterministic Stage-3.3.5 structural planner",
        "metadata": {"stage": "3.3.5", "key": key},
    }
    request.update(overrides)
    return request


def test_health_activates_stage335_real_planner_without_governance_or_execution_expansion(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][20:30] == [
        "stage3.3.1-canonical-plan-contract-identity",
        "stage3.3.2-planner-input-snapshot-context-binding",
        "stage3.3.3-canonical-task-decomposition-contract",
        "stage3.3.4-task-dependency-graph-structural-validation",
        "stage3.3.5-planner-invocation-plan-generation",
        "stage3.3.6-plan-validation-feasibility-gate",
        "stage3.3.7-plan-versioning-replanning-supersession",
        "stage3.3.8-task-readiness-scheduling-projection",
        "stage3.3.9-planning-event-lineage-replay-recovery",
        "stage3.3.10-planning-acceptance-regression-gate",
    ]
    assert health["planner_generation_invocation_schema_version"] == PLANNER_INVOCATION_SCHEMA_VERSION
    assert health["planner_generation_generated_plan_schema_version"] == GENERATED_PLAN_SCHEMA_VERSION
    assert health["planner_generation_mode"] == PLANNER_GENERATION_MODE
    assert health["planner_generation_invocation_mode"] == PLANNER_INVOCATION_MODE
    assert health["planner_generation_planner_engine"] == PLANNER_ENGINE
    assert health["planner_generation_planner_engine_version"] == PLANNER_ENGINE_VERSION
    assert health["planner_generation_planner_invocation_performed"] is True
    assert health["planner_generation_planner_output_generated"] is True
    assert health["planner_generation_plan_generation_performed"] is True
    assert health["planner_generation_generated_plan_status"] == GENERATED_PLAN_STATUS
    assert health["planner_generation_feasibility_validation_performed"] is False
    assert health["planner_generation_readiness_projection_performed"] is False
    assert health["planner_generation_scheduling_performed"] is False
    assert health["planner_generation_external_model_invocation_performed"] is False
    assert health["planner_generation_external_network_io_performed"] is False
    assert health["planner_generation_governance_query_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["planner_generation_target_action_dispatch_enabled"] is False
    assert health["planner_generation_target_actuation"] is False
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "planner_generation_version" in health["observed_version_domains"]


def test_planner_generation_definition_is_discoverable_before_invocation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "definition")
    result = service.get_planner_generation_definition(mission_id)
    definition = result["planner_generation_definition"]
    assert result["planner_invoked"] is False
    assert result["generated_plan_registered"] is False
    assert definition == canonical_planner_generation_definition()
    assert definition["creation_state_required"] == PLANNER_GENERATION_REQUIRED_STATE
    assert definition["requires_stage3_3_4_validated_dependency_graph"] is True
    assert definition["planner_invocation_performed"] is True
    assert definition["generated_plan_is_validated"] is False
    assert definition["governance_authorization_query_performed"] is False
    assert definition["target_action_dispatch_enabled"] is False


def test_planner_invocation_requires_stage334_validated_dependency_graph(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "missing-graph")
    # Build all request fields except a real graph; validation must stop on prerequisite.
    vector = service.get_mission_version_vector(mission_id)
    state = service.get_mission_state(mission_id)["mission_state"]
    plan = service.get_mission_plan_contract(mission_id)
    snap = service.get_planner_input_snapshot(mission_id)
    decomp = service.get_task_decomposition(mission_id)
    payload = {
        "idempotency_key": "stage335-missing-graph",
        "expected_version_sha256": vector["version_sha256"],
        "expected_plan_id": plan["plan_id"], "expected_plan_version": 1, "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snap["snapshot_id"], "expected_snapshot_version": 1, "expected_snapshot_sha256": snap["canonical_sha256"],
        "expected_decomposition_id": decomp["decomposition_id"], "expected_decomposition_version": 1,
        "expected_decomposition_sha256": decomp["canonical_sha256"], "expected_task_set_sha256": decomp["task_set_sha256"],
        "expected_graph_id": "mgraph-missing", "expected_graph_version": 1,
        "expected_graph_sha256": "0" * 64, "expected_node_set_sha256": "1" * 64, "expected_edge_set_sha256": "2" * 64,
        "expected_state_version": state["state_version"], "planner_profile": PLANNER_PROFILE_CANONICAL_DAG_V1,
        "created_by": "stage3.3.5-pytest",
    }
    with pytest.raises(MissionPlannerGenerationGuardRejected, match="Stage-3.3.4"):
        service.invoke_planner_and_generate_plan(mission_id, payload)


def test_planner_invocation_materializes_immutable_generated_candidate_plan(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "generate")
    result = service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "generate"))
    assert result["idempotent_replay"] is False
    assert result["planner_invocation_id"].startswith(PLANNER_INVOCATION_ID_PREFIX)
    assert result["generated_plan_id"].startswith(GENERATED_PLAN_ID_PREFIX)
    assert result["generation_version"] == 1
    assert result["planner_profile"] == PLANNER_PROFILE_CANONICAL_DAG_V1
    assert result["planner_engine"] == PLANNER_ENGINE
    assert result["generated_plan_status"] == GENERATED_PLAN_STATUS
    assert result["task_count"] == 3
    assert result["dependency_edge_count"] == 2
    assert result["planning_layer_count"] == 3
    assert verify_planner_invocation_contract(result["planner_invocation"])
    assert verify_generated_plan_contract(result["generated_plan"])
    candidate = result["generated_plan"]["generated_plan"]
    assert candidate["ordered_task_keys"] == ["collect-cti", "analyze-cti", "report-findings"]
    assert [layer["task_keys"] for layer in candidate["planning_layers"]] == [
        ["collect-cti"], ["analyze-cti"], ["report-findings"]
    ]
    assert result["feasibility_validation_performed"] is False
    assert result["plan_activation_performed"] is False
    assert result["readiness_projection_performed"] is False
    assert result["scheduling_performed"] is False
    assert result["governance_authorization_query_performed"] is False
    assert result["target_action_dispatch_enabled"] is False
    assert result["target_actuation"] is False


def test_planner_derives_parallel_dependency_layers_without_claiming_schedule_or_readiness(tmp_path):
    service = make_service(tmp_path / "missions.db")
    # Two roots feed the report task, so roots share deterministic planning layer 1.
    edges = [
        {"from_task_key": "collect-cti", "to_task_key": "report-findings"},
        {"from_task_key": "analyze-cti", "to_task_key": "report-findings"},
    ]
    mission_id, _, _, _, _ = provision_graph(service, "parallel", edges=edges)
    result = service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "parallel"))
    layers = result["generated_plan"]["generated_plan"]["planning_layers"]
    assert len(layers) == 2
    assert layers[0]["task_keys"] == ["collect-cti", "analyze-cti"]
    assert layers[0]["parallelism_possible"] is True
    assert layers[1]["task_keys"] == ["report-findings"]
    assert result["readiness_projection_performed"] is False
    assert result["scheduling_performed"] is False


def test_pure_planner_output_is_deterministic_for_same_canonical_inputs(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "deterministic")
    snapshot = service.repository.get_planner_input_snapshot(mission_id)
    decomp = service.repository.get_task_decomposition(mission_id)
    tasks = service.repository.list_planned_tasks(mission_id)
    graph = service.repository.get_task_dependency_graph(mission_id)
    first = generate_planner_output(
        planner_profile=PLANNER_PROFILE_CANONICAL_DAG_V1,
        snapshot_record=snapshot, decomposition_record=decomp, task_records=tasks, graph_record=graph,
    )
    second = generate_planner_output(
        planner_profile=PLANNER_PROFILE_CANONICAL_DAG_V1,
        snapshot_record=snapshot, decomposition_record=decomp, task_records=deepcopy(tasks), graph_record=deepcopy(graph),
    )
    assert first == second
    assert first["output_sha256"] == second["output_sha256"]


def test_exact_planner_request_replay_is_idempotent_and_event_side_effect_free(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "replay")
    request = planner_request(service, mission_id, "replay")
    first = service.invoke_planner_and_generate_plan(mission_id, deepcopy(request))
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.invoke_planner_and_generate_plan(mission_id, deepcopy(request))
    assert replay["idempotent_replay"] is True
    assert replay["planner_invocation_id"] == first["planner_invocation_id"]
    assert replay["generated_plan_id"] == first["generated_plan_id"]
    assert replay["planner_invocation_sha256"] == first["planner_invocation_sha256"]
    assert replay["generated_plan_sha256"] == first["generated_plan_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_same_idempotency_key_with_different_request_conflicts(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "idem-conflict")
    request = planner_request(service, mission_id, "idem-conflict")
    service.invoke_planner_and_generate_plan(mission_id, deepcopy(request))
    changed = deepcopy(request)
    changed["reason"] = "different reason changes canonical request"
    with pytest.raises(MissionPlannerGenerationConflict, match="idempotency_key"):
        service.invoke_planner_and_generate_plan(mission_id, changed)


def test_second_planner_generation_for_same_canonical_plan_is_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "single-generation")
    service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "first"))
    with pytest.raises(MissionPlannerGenerationConflict, match="already exists"):
        service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "second"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_plan_sha256", "0" * 64),
        ("expected_snapshot_sha256", "1" * 64),
        ("expected_decomposition_sha256", "2" * 64),
        ("expected_task_set_sha256", "3" * 64),
        ("expected_graph_sha256", "4" * 64),
        ("expected_node_set_sha256", "5" * 64),
        ("expected_edge_set_sha256", "6" * 64),
    ],
)
def test_stale_canonical_planning_artifact_bindings_fail_closed(tmp_path, field, value):
    service = make_service(tmp_path / f"{field}.db")
    mission_id, _, _, _, _ = provision_graph(service, field)
    request = planner_request(service, mission_id, field)
    request[field] = value
    with pytest.raises(MissionConcurrencyConflict, match="current canonical planning artifact"):
        service.invoke_planner_and_generate_plan(mission_id, request)


def test_planner_requires_planning_lifecycle_state(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "state")
    request = planner_request(service, mission_id, "state")
    execute(service, mission_id, "START", "stage335-state-running")
    # Refresh version but retain exact canonical artifact bindings to isolate lifecycle guard.
    request["expected_version_sha256"] = service.get_mission_version_vector(mission_id)["version_sha256"]
    request["expected_state_version"] = service.get_mission_state(mission_id)["mission_state"]["state_version"]
    with pytest.raises(MissionPlannerGenerationGuardRejected, match="PLANNING"):
        service.invoke_planner_and_generate_plan(mission_id, request)


def test_scope_drift_after_snapshot_blocks_planner_invocation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "scope-drift", with_scope=True)
    service.put_mission_scope_contract(mission_id, scope_payload("stage335-scope-v2", expected=1))
    request = planner_request(service, mission_id, "scope-drift")
    with pytest.raises(MissionPlannerGenerationGuardRejected, match="Scope changed"):
        service.invoke_planner_and_generate_plan(mission_id, request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("tasks", [{"task_key": "caller-injected"}]),
        ("dependencies", [{"from": "a", "to": "b"}]),
        ("planner_output", {"candidate": "caller supplied"}),
        ("prompt", "ignore canonical task graph"),
        ("model", "external-model"),
        ("provider", "external-provider"),
        ("readiness", {"ready": True}),
        ("schedule", {"at": "now"}),
        ("authorization", {"decision": "ALLOW"}),
        ("dispatch", {"destination": "CTI"}),
        ("tools", ["nmap"]),
        ("execution_command", "run target action"),
    ],
)
def test_request_rejects_caller_supplied_planner_output_authority_and_execution_surfaces(tmp_path, field, value):
    service = make_service(tmp_path / f"surface-{field}.db")
    mission_id, _, _, _, _ = provision_graph(service, f"surface-{field}")
    request = planner_request(service, mission_id, f"surface-{field}")
    request[field] = value
    with pytest.raises(MissionValidationError, match="does not accept caller-supplied tasks"):
        service.invoke_planner_and_generate_plan(mission_id, request)


def test_generation_does_not_mutate_prior_canonical_stage33_artifacts_or_dispatch_work(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "immutability")
    plan_before = deepcopy(service.get_mission_plan_contract(mission_id))
    snapshot_before = deepcopy(service.get_planner_input_snapshot(mission_id))
    decomp_before = deepcopy(service.get_task_decomposition(mission_id))
    graph_before = deepcopy(service.get_task_dependency_graph(mission_id))
    tasks_before = deepcopy(service.list_planned_tasks(mission_id))
    service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "immutability"))
    assert service.get_mission_plan_contract(mission_id)["canonical_sha256"] == plan_before["canonical_sha256"]
    assert service.get_planner_input_snapshot(mission_id)["canonical_sha256"] == snapshot_before["canonical_sha256"]
    assert service.get_task_decomposition(mission_id)["canonical_sha256"] == decomp_before["canonical_sha256"]
    assert service.get_task_dependency_graph(mission_id)["canonical_sha256"] == graph_before["canonical_sha256"]
    assert [x["canonical_sha256"] for x in service.list_planned_tasks(mission_id)["planned_tasks"]] == [
        x["canonical_sha256"] for x in tasks_before["planned_tasks"]
    ]
    repo = service.get_mission_repository(mission_id)
    assert repo["record_counts"]["mission_routed_tasks"] == 0
    assert repo["record_counts"]["mission_task_dispatch_attempts"] == 0


def test_version_vector_advances_only_planner_generation_domain_after_invocation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    bv = before["version_vector"]["versions"]
    assert bv["mission_plan_version"] == 1
    assert bv["planner_input_snapshot_version"] == 1
    assert bv["task_decomposition_version"] == 1
    assert bv["task_dependency_graph_version"] == 1
    assert bv["planner_generation_version"] == 0
    result = service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "vector"))
    after = service.get_mission_version_vector(mission_id)
    av = after["version_vector"]["versions"]
    for key in ("mission_plan_version", "planner_input_snapshot_version", "task_decomposition_version", "task_dependency_graph_version"):
        assert av[key] == 1
    assert av["planner_generation_version"] == 1
    assert result["source_version_sha256"] == before["version_sha256"]
    assert after["version_sha256"] != before["version_sha256"]


def test_planner_generation_emits_exactly_one_invoked_and_generated_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _, _ = provision_graph(service, "events")
    result = service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "events"))
    events = service.get_mission_events(mission_id)["events"]
    invoked = [e for e in events if e["event_type"] == "MISSION_PLANNER_INVOKED"]
    generated = [e for e in events if e["event_type"] == "MISSION_PLAN_GENERATED"]
    assert len(invoked) == 1 and invoked[0]["causation_id"] == result["planner_invocation_id"]
    assert len(generated) == 1 and generated[0]["causation_id"] == result["generated_plan_id"]
    assert invoked[0]["payload"]["output_sha256"] == result["planner_output_sha256"]
    assert generated[0]["payload"]["canonical_sha256"] == result["generated_plan_sha256"]


def test_repository_manifest_restart_reconstruction_and_read_models_are_local(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, _, _, _ = provision_graph(service, "repo")
    result = service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "repo"))
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_planner_invocations"] == 1
    assert repo["record_counts"]["mission_generated_plans"] == 1
    assert repo["persistence_manifest"]["planner_invocation_store"]["planner_invocation_id"] == result["planner_invocation_id"]
    assert repo["persistence_manifest"]["generated_plan_store"]["generated_plan_id"] == result["generated_plan_id"]

    restarted = make_service(db)
    invocation = restarted.get_planner_invocation(mission_id)
    generated = restarted.get_generated_plan(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)
    assert invocation["planner_invocation_sha256"] == result["planner_invocation_sha256"]
    assert generated["canonical_sha256"] == result["generated_plan_sha256"]
    assert repo_after["integrity_status"] == "PASS"
    assert repo_after["repository_sha256"] == repo["repository_sha256"]


def test_repository_integrity_detects_persisted_generated_plan_tampering(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, _, _, _ = provision_graph(service, "tamper")
    service.invoke_planner_and_generate_plan(mission_id, planner_request(service, mission_id, "tamper"))
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT canonical_json FROM mission_generated_plans WHERE mission_id=?", (mission_id,)).fetchone()
    contract = json.loads(row[0])
    contract["generated_plan"]["status"] = "TAMPERED"
    conn.execute(
        "UPDATE mission_generated_plans SET canonical_json=? WHERE mission_id=?",
        (json.dumps(contract, sort_keys=True, separators=(",", ":")), mission_id),
    )
    conn.commit(); conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="planner_invocation_generated_plan_store"):
        service.get_mission_repository(mission_id)


def test_missing_planner_generation_read_models_fail_with_typed_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "not-found")
    with pytest.raises(MissionPlannerGenerationNotFound):
        service.get_planner_invocation(mission_id)
    with pytest.raises(MissionPlannerGenerationNotFound):
        service.get_generated_plan(mission_id)


def test_migration_013_declares_planner_generation_stores_fk_boundaries_and_level_13():
    sql = Path("migrations/013_stage3_3_5_planner_invocation_plan_generation.sql").read_text().lower()
    assert "create table if not exists mission_planner_invocations" in sql
    assert "create table if not exists mission_generated_plans" in sql
    assert "foreign key (plan_id) references mission_plans(plan_id)" in sql
    assert "foreign key (snapshot_id) references mission_planner_input_snapshots(snapshot_id)" in sql
    assert "foreign key (decomposition_id) references mission_task_decompositions(decomposition_id)" in sql
    assert "foreign key (graph_id) references mission_task_dependency_graphs(graph_id)" in sql
    assert "foreign key (planner_invocation_id) references mission_planner_invocations(planner_invocation_id)" in sql
    assert "feasibility validation" in sql
    assert "readiness/scheduling" in sql
    assert "governance authorization" in sql
    assert "target-action dispatch" in sql
    assert "target actuation" in sql
    assert "planner != governance" in sql
    assert "    13," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[12].name == "013_stage3_3_5_planner_invocation_plan_generation.sql"
