from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskDependencyGraphConflict,
    MissionTaskDependencyGraphGuardRejected,
    MissionTaskDependencyGraphNotFound,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_dependency_graph import (
    MAX_DEPENDENCY_EDGES,
    TASK_DEPENDENCY_EDGE_ID_PREFIX,
    TASK_DEPENDENCY_EDGE_SCHEMA_VERSION,
    TASK_DEPENDENCY_GRAPH_ID_PREFIX,
    TASK_DEPENDENCY_GRAPH_MODE,
    TASK_DEPENDENCY_GRAPH_REQUIRED_STATE,
    TASK_DEPENDENCY_GRAPH_SCHEMA_VERSION,
    TASK_DEPENDENCY_GRAPH_STATUS,
    TASK_DEPENDENCY_GRAPH_VERSION_INITIAL,
    TASK_DEPENDENCY_VALIDATION_MODE,
    verify_task_dependency_edge_contract,
    verify_task_dependency_graph_contract,
)


class NoExternalClient:
    base_url = "disabled://stage3.3.4"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(
            f"Stage 3.3.4 dependency-graph validation must remain local-only: unexpected external call {name}"
        )


def make_service(db: Path) -> CanonicalMissionService:
    client = NoExternalClient()
    return CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=client,
        cti_client=client,
    )


def mission_payload(key: str) -> dict:
    return {
        "idempotency_key": f"stage334-mission-{key}",
        "source_system": "STAGE334_PYTEST",
        "created_by": "stage3.3.4-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage334-lab"},
        "success_criteria": [
            {"metric": "dependency_graph_validated", "expected": True},
            {"metric": "authority_boundary_preserved", "expected": True},
        ],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": ["CTI"],
        "pip_id": f"pip-stage334-{key}",
        "pip_version": "18",
        "metadata": {"environment": "LAB", "stage": "3.3.4"},
    }


def create_mission(service: CanonicalMissionService, key: str) -> str:
    return service.create_mission(mission_payload(key))["canonical_identity"]["mission_id"]


def lifecycle_request(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "command_id": f"lc-334-{token}",
        "idempotency_key": f"idem-lc-334-{token}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.3.4-pytest",
        "reason_code": f"STAGE334_{command}",
        "reason": f"Stage 3.3.4 prerequisite command {command}",
        "evidence_refs": [f"evidence:stage334:{token}"],
        "metadata": {"stage": "3.3.4", "token": token},
    }


def execute(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    return service.execute_mission_lifecycle_command(
        mission_id, lifecycle_request(service, mission_id, command, token)
    )


def activate_planning(service: CanonicalMissionService, mission_id: str, token: str) -> None:
    execute(service, mission_id, "BIND_PIP", f"bind-{token}")
    execute(service, mission_id, "START_PLANNING", f"planning-{token}")


def scope_payload(key: str, *, expected: int = 0) -> dict:
    return {
        "expected_contract_version": expected,
        "idempotency_key": f"stage334-scope-{key}",
        "actor": "stage3.3.4-pytest",
        "scope": {
            "targets": [{"target_type": "CIDR", "target_value": "127.0.0.0/8", "environment": "LAB"}],
            "excluded_targets": [],
            "network_ranges": ["127.0.0.0/8"],
            "domains": ["lab.example.test"],
            "services": [{"name": "https", "protocol": "TCP", "port": 443, "target_ref": "lab.example.test"}],
        },
        "roe": {
            "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
            "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
            "maximum_concurrency": 2,
            "destructive_actions_allowed": False,
            "credential_usage_allowed": False,
            "persistence_allowed": False,
            "human_approval_required_for": ["VULNERABILITY_VALIDATION"],
        },
        "constraints": {
            "max_actions": 10,
            "max_duration": 1200,
            "risk_threshold": "LOW",
            "resource_budget": {"max_network_requests": 100},
            "data_handling_policy": {"classification": "INTERNAL"},
        },
        "reason": "Stage 3.3.4 graph context scope",
        "metadata": {"stage": "3.3.4"},
    }


def plan_request(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "idempotency_key": f"stage334-plan-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.4-pytest",
        "reason": "Register Stage-3.3.1 Plan prerequisite",
        "metadata": {"stage": "3.3.4", "prerequisite": "3.3.1"},
    }


def snapshot_request(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    plan = service.get_mission_plan_contract(mission_id)
    return {
        "idempotency_key": f"stage334-snapshot-{key}",
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": plan["plan_version"],
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.4-pytest",
        "reason": "Freeze Stage-3.3.2 planner-input prerequisite",
        "metadata": {"stage": "3.3.4", "prerequisite": "3.3.2"},
    }


def task_specs() -> list[dict]:
    base = [
        ("collect-cti", "CTI_COLLECTION", "Collect canonical CTI context", "cti.read.context", 10),
        ("analyze-cti", "CTI_ANALYSIS", "Analyze CTI context", "cti.analyze.context", 20),
        ("report-findings", "CTI_REPORT", "Structure planning findings", "cti.report.context", 30),
    ]
    tasks = []
    for index, (key, task_type, goal, capability, priority) in enumerate(base):
        tasks.append(
            {
                "task_key": key,
                "task_type": task_type,
                "objective": {"goal": goal},
                "required_capability": capability,
                "required_subsystem": "CTI",
                "preconditions": [],
                "expected_outputs": [{"artifact": f"artifact_{index}", "format": "STRUCTURED"}],
                "success_criteria": [{"metric": f"criterion_{index}", "expected": True}],
                "evidence_requirements": [{"type": "SOURCE_PROVENANCE"}],
                "priority": priority,
                "metadata": {"stage": "3.3.4", "sequence_hint": index + 1},
            }
        )
    return tasks


def decomposition_request(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    plan = service.get_mission_plan_contract(mission_id)
    snapshot = service.get_planner_input_snapshot(mission_id)
    return {
        "idempotency_key": f"stage334-decomposition-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": plan["plan_version"],
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snapshot["snapshot_id"],
        "expected_snapshot_version": snapshot["snapshot_version"],
        "expected_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.4-pytest",
        "reason": "Materialize Stage-3.3.3 planned tasks",
        "tasks": deepcopy(task_specs()),
        "metadata": {"stage": "3.3.4", "prerequisite": "3.3.3"},
    }


def provision_decomposition(
    service: CanonicalMissionService, key: str, *, with_scope: bool = False
) -> tuple[str, dict, dict, dict]:
    mission_id = create_mission(service, key)
    if with_scope:
        service.put_mission_scope_contract(mission_id, scope_payload(key))
    activate_planning(service, mission_id, key)
    plan = service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, key))
    snapshot = service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, key))
    decomp = service.create_task_decomposition(mission_id, decomposition_request(service, mission_id, key))
    return mission_id, plan, snapshot, decomp


def graph_request(
    service: CanonicalMissionService,
    mission_id: str,
    key: str,
    *,
    edges: list[dict] | None = None,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    plan = service.get_mission_plan_contract(mission_id)
    snapshot = service.get_planner_input_snapshot(mission_id)
    decomp = service.get_task_decomposition(mission_id)
    return {
        "idempotency_key": f"stage334-graph-{key}",
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
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.4-pytest",
        "reason": "Materialize deterministic dependency DAG only",
        "edges": deepcopy(
            edges
            if edges is not None
            else [
                {"from_task_key": "collect-cti", "to_task_key": "analyze-cti"},
                {"from_task_key": "analyze-cti", "to_task_key": "report-findings"},
            ]
        ),
        "metadata": {"stage": "3.3.4", "key": key},
    }


def test_health_activates_stage334_and_preserves_authority_execution_boundaries(tmp_path):
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
    assert health["task_dependency_graph_schema_version"] == TASK_DEPENDENCY_GRAPH_SCHEMA_VERSION
    assert health["task_dependency_edge_schema_version"] == TASK_DEPENDENCY_EDGE_SCHEMA_VERSION
    assert health["task_dependency_graph_mode"] == TASK_DEPENDENCY_GRAPH_MODE
    assert health["task_dependency_graph_structural_validation_mode"] == TASK_DEPENDENCY_VALIDATION_MODE
    assert health["task_dependency_graph_max_dependency_edges"] == MAX_DEPENDENCY_EDGES
    assert health["task_dependency_graph_materialized"] is True
    assert health["task_dependency_graph_dependency_validation_performed"] is True
    assert health["task_dependency_graph_planner_invocation_performed"] is False
    assert health["task_dependency_graph_readiness_projection_performed"] is False
    assert health["task_dependency_graph_scheduling_performed"] is False
    assert health["task_dependency_graph_graph_is_authorization"] is False
    assert health["task_dependency_graph_task_is_dispatch"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False
    assert health["mission_repository_migration_level"] == 53
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert "task_dependency_graph_version" in health["observed_version_domains"]


def test_graph_definition_is_discoverable_before_registration(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "definition")
    definition = service.get_task_dependency_graph_definition(mission_id)
    contract = definition["task_dependency_graph_definition"]
    assert definition["graph_registered"] is False
    assert contract["schema_version"] == TASK_DEPENDENCY_GRAPH_SCHEMA_VERSION
    assert contract["creation_state_required"] == TASK_DEPENDENCY_GRAPH_REQUIRED_STATE
    assert contract["requires_stage3_3_3_task_decomposition"] is True
    assert contract["dependency_graph_materialized"] is True
    assert contract["readiness_projection_performed"] is False
    assert contract["target_action_dispatch_enabled"] is False


def test_graph_requires_stage333_decomposition(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "missing-decomp")
    activate_planning(service, mission_id, "missing-decomp")
    service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, "missing-decomp"))
    service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, "missing-decomp"))
    vector = service.get_mission_version_vector(mission_id)
    state = service.get_mission_state(mission_id)["mission_state"]
    plan = service.get_mission_plan_contract(mission_id)
    snap = service.get_planner_input_snapshot(mission_id)
    payload = {
        "idempotency_key": "stage334-graph-missing-decomp",
        "expected_version_sha256": vector["version_sha256"],
        "expected_plan_id": plan["plan_id"], "expected_plan_version": 1, "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snap["snapshot_id"], "expected_snapshot_version": 1, "expected_snapshot_sha256": snap["canonical_sha256"],
        "expected_decomposition_id": "mdecomp-missing", "expected_decomposition_version": 1,
        "expected_decomposition_sha256": "0" * 64, "expected_task_set_sha256": "1" * 64,
        "expected_state_version": state["state_version"], "created_by": "stage3.3.4-pytest", "edges": [],
    }
    with pytest.raises(MissionTaskDependencyGraphGuardRejected, match="Stage-3.3.3"):
        service.create_task_dependency_graph(mission_id, payload)


def test_graph_materializes_complete_canonical_node_set_edges_and_topological_order(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, decomp = provision_decomposition(service, "canonical")
    result = service.create_task_dependency_graph(mission_id, graph_request(service, mission_id, "canonical"))
    graph = result["task_dependency_graph"]
    assert result["graph_id"].startswith(TASK_DEPENDENCY_GRAPH_ID_PREFIX)
    assert result["graph_version"] == TASK_DEPENDENCY_GRAPH_VERSION_INITIAL
    assert result["validation_status"] == "PASS"
    assert result["node_count"] == decomp["task_count"] == 3
    assert result["edge_count"] == 2
    assert verify_task_dependency_graph_contract(graph)
    assert [node["task_key"] for node in graph["graph"]["nodes"]] == [
        "collect-cti", "analyze-cti", "report-findings"
    ]
    assert graph["graph"]["topological_task_keys"] == [
        "collect-cti", "analyze-cti", "report-findings"
    ]
    assert graph["graph"]["root_task_keys"] == ["collect-cti"]
    assert graph["graph"]["leaf_task_keys"] == ["report-findings"]
    assert graph["structural_validation"]["status"] == "PASS"
    assert graph["semantics"]["planner_invocation_performed"] is False
    assert graph["semantics"]["target_action_dispatch_enabled"] is False


def test_graph_replay_is_order_independent_idempotent_and_event_side_effect_free(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "replay")
    request = graph_request(service, mission_id, "replay")
    first = service.create_task_dependency_graph(mission_id, request)
    events_before = service.get_mission_events(mission_id)
    reversed_request = deepcopy(request)
    reversed_request["edges"] = list(reversed(reversed_request["edges"]))
    replay = service.create_task_dependency_graph(mission_id, reversed_request)
    events_after = service.get_mission_events(mission_id)
    assert replay["idempotent_replay"] is True
    assert replay["graph_id"] == first["graph_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert events_after["event_count"] == events_before["event_count"]
    graph_events = [e for e in events_after["events"] if e["event_type"] == "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED"]
    assert len(graph_events) == 1


def test_graph_idempotency_conflict_and_second_immutable_graph_are_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "conflict")
    request = graph_request(service, mission_id, "conflict")
    service.create_task_dependency_graph(mission_id, request)
    changed = deepcopy(request)
    changed["edges"] = [{"from_task_key": "collect-cti", "to_task_key": "report-findings"}]
    with pytest.raises(MissionTaskDependencyGraphConflict, match="idempotency_key"):
        service.create_task_dependency_graph(mission_id, changed)
    second = deepcopy(request)
    second["idempotency_key"] = "stage334-graph-conflict-second"
    with pytest.raises(MissionTaskDependencyGraphConflict, match="already exists"):
        service.create_task_dependency_graph(mission_id, second)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_decomposition_version", 2),
        ("expected_decomposition_sha256", "a" * 64),
        ("expected_task_set_sha256", "b" * 64),
        ("expected_snapshot_sha256", "c" * 64),
        ("expected_plan_sha256", "d" * 64),
        ("expected_version_sha256", "e" * 64),
        ("expected_state_version", 99),
    ],
)
def test_exact_binding_and_concurrency_tokens_fail_closed(tmp_path, field, value):
    service = make_service(tmp_path / f"{field}.db")
    mission_id, _, _, _ = provision_decomposition(service, field)
    request = graph_request(service, mission_id, field)
    request[field] = value
    with pytest.raises(MissionConcurrencyConflict):
        service.create_task_dependency_graph(mission_id, request)


@pytest.mark.parametrize(
    ("edges", "message"),
    [
        ([{"from_task_key": "missing", "to_task_key": "analyze-cti"}], "unknown from_task_key"),
        ([{"from_task_key": "collect-cti", "to_task_key": "missing"}], "unknown to_task_key"),
        ([{"from_task_key": "collect-cti", "to_task_key": "collect-cti"}], "self-dependency"),
        ([
            {"from_task_key": "collect-cti", "to_task_key": "analyze-cti"},
            {"from_task_key": "collect-cti", "to_task_key": "analyze-cti"},
        ], "duplicate dependency edge"),
    ],
)
def test_dangling_self_and_duplicate_edges_fail_closed(tmp_path, edges, message):
    service = make_service(tmp_path / "structural.db")
    mission_id, _, _, _ = provision_decomposition(service, message.replace(" ", "-"))
    with pytest.raises(MissionTaskDependencyGraphGuardRejected, match=message):
        service.create_task_dependency_graph(
            mission_id, graph_request(service, mission_id, message.replace(" ", "-"), edges=edges)
        )


def test_directed_cycle_fails_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "cycle")
    edges = [
        {"from_task_key": "collect-cti", "to_task_key": "analyze-cti"},
        {"from_task_key": "analyze-cti", "to_task_key": "report-findings"},
        {"from_task_key": "report-findings", "to_task_key": "collect-cti"},
    ]
    with pytest.raises(MissionTaskDependencyGraphGuardRejected, match="directed cycle"):
        service.create_task_dependency_graph(
            mission_id, graph_request(service, mission_id, "cycle", edges=edges)
        )


def test_zero_edge_graph_is_valid_and_all_tasks_are_isolated_in_deterministic_order(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "isolated")
    result = service.create_task_dependency_graph(
        mission_id, graph_request(service, mission_id, "isolated", edges=[])
    )
    body = result["task_dependency_graph"]["graph"]
    assert result["edge_count"] == 0
    assert body["topological_task_keys"] == ["collect-cti", "analyze-cti", "report-findings"]
    assert body["isolated_task_keys"] == ["collect-cti", "analyze-cti", "report-findings"]
    assert body["root_task_keys"] == body["isolated_task_keys"]
    assert body["leaf_task_keys"] == body["isolated_task_keys"]


def test_structural_graph_does_not_mutate_plan_snapshot_decomposition_or_task_contracts(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "immutable")
    plan_before = deepcopy(service.get_mission_plan_contract(mission_id))
    snapshot_before = deepcopy(service.get_planner_input_snapshot(mission_id))
    decomp_before = deepcopy(service.get_task_decomposition(mission_id))
    tasks_before = deepcopy(service.list_planned_tasks(mission_id))
    service.create_task_dependency_graph(mission_id, graph_request(service, mission_id, "immutable"))
    assert service.get_mission_plan_contract(mission_id)["canonical_sha256"] == plan_before["canonical_sha256"]
    assert service.get_planner_input_snapshot(mission_id)["canonical_sha256"] == snapshot_before["canonical_sha256"]
    assert service.get_task_decomposition(mission_id)["canonical_sha256"] == decomp_before["canonical_sha256"]
    assert [x["canonical_sha256"] for x in service.list_planned_tasks(mission_id)["planned_tasks"]] == [
        x["canonical_sha256"] for x in tasks_before["planned_tasks"]
    ]
    assert service.get_mission_plan_contract(mission_id)["plan_contract"]["task_graph"]["status"] == "NOT_MATERIALIZED"


def test_version_vector_advances_only_graph_domain_among_stage33_planning_artifacts(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    versions_before = before["version_vector"]["versions"]
    assert versions_before["mission_plan_version"] == 1
    assert versions_before["planner_input_snapshot_version"] == 1
    assert versions_before["task_decomposition_version"] == 1
    assert versions_before["task_dependency_graph_version"] == 0
    result = service.create_task_dependency_graph(mission_id, graph_request(service, mission_id, "vector"))
    after = service.get_mission_version_vector(mission_id)
    versions_after = after["version_vector"]["versions"]
    assert versions_after["mission_plan_version"] == 1
    assert versions_after["planner_input_snapshot_version"] == 1
    assert versions_after["task_decomposition_version"] == 1
    assert versions_after["task_dependency_graph_version"] == 1
    assert result["source_version_sha256"] == before["version_sha256"]
    assert after["version_sha256"] != before["version_sha256"]


def test_scope_drift_after_snapshot_blocks_dependency_graph(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "scope-drift", with_scope=True)
    service.put_mission_scope_contract(mission_id, scope_payload("scope-drift-v2", expected=1))
    request = graph_request(service, mission_id, "scope-drift")
    with pytest.raises(MissionTaskDependencyGraphGuardRejected, match="Scope changed"):
        service.create_task_dependency_graph(mission_id, request)


def test_state_advance_after_decomposition_blocks_dependency_graph(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "state-drift")
    execute(service, mission_id, "START", "state-drift-running")
    request = graph_request(service, mission_id, "state-drift")
    with pytest.raises(MissionTaskDependencyGraphGuardRejected, match="PLANNING"):
        service.create_task_dependency_graph(mission_id, request)


def test_event_edge_read_model_repository_integrity_and_restart_reconstruction_are_local(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, _, _ = provision_decomposition(service, "repo")
    result = service.create_task_dependency_graph(mission_id, graph_request(service, mission_id, "repo"))
    events = service.get_mission_events(mission_id)
    graph_events = [e for e in events["events"] if e["event_type"] == "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED"]
    assert len(graph_events) == 1
    assert graph_events[0]["causation_id"] == result["graph_id"]
    edges = service.list_task_dependency_edges(mission_id)
    assert edges["edge_count"] == 2
    assert all(edge["dependency_edge_id"].startswith(TASK_DEPENDENCY_EDGE_ID_PREFIX) for edge in edges["dependency_edges"])
    assert all(verify_task_dependency_edge_contract(edge["edge"]) for edge in edges["dependency_edges"])

    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_task_dependency_graphs"] == 1
    assert repo["record_counts"]["mission_task_dependency_edges"] == 2
    assert repo["persistence_manifest"]["task_dependency_graph_store"]["graph_id"] == result["graph_id"]
    assert len(repo["persistence_manifest"]["task_dependency_edge_store"]) == 2

    restarted = make_service(db)
    reconstructed = restarted.get_task_dependency_graph(mission_id)
    reconstructed_edges = restarted.list_task_dependency_edges(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)
    assert reconstructed["canonical_sha256"] == result["canonical_sha256"]
    assert reconstructed_edges["edge_count"] == 2
    assert repo_after["integrity_status"] == "PASS"
    assert repo_after["repository_sha256"] == repo["repository_sha256"]


def test_graph_integrity_verifier_rejects_topological_order_tampering(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "topo-tamper")
    graph = service.create_task_dependency_graph(
        mission_id, graph_request(service, mission_id, "topo-tamper")
    )["task_dependency_graph"]
    assert verify_task_dependency_graph_contract(graph)
    tampered = deepcopy(graph)
    tampered["graph"]["topological_task_keys"] = ["report-findings", "analyze-cti", "collect-cti"]
    assert verify_task_dependency_graph_contract(tampered) is False


def test_repository_integrity_detects_persisted_graph_tampering(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, _, _ = provision_decomposition(service, "db-tamper")
    service.create_task_dependency_graph(mission_id, graph_request(service, mission_id, "db-tamper"))
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT canonical_json FROM mission_task_dependency_graphs WHERE mission_id=?", (mission_id,)
    ).fetchone()
    graph = json.loads(row[0])
    graph["graph"]["status"] = "TAMPERED"
    conn.execute(
        "UPDATE mission_task_dependency_graphs SET canonical_json=? WHERE mission_id=?",
        (json.dumps(graph, sort_keys=True, separators=(",", ":")), mission_id),
    )
    conn.commit()
    conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="canonical_task_dependency_graph_store"):
        service.get_mission_repository(mission_id)


def test_missing_graph_read_models_fail_with_typed_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "not-found")
    with pytest.raises(MissionTaskDependencyGraphNotFound):
        service.get_task_dependency_graph(mission_id)
    with pytest.raises(MissionTaskDependencyGraphNotFound):
        service.list_task_dependency_edges(mission_id)


def test_request_rejects_readiness_authorization_dispatch_and_execution_surface(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_decomposition(service, "surface")
    for field, value in (
        ("readiness", {"ready": True}),
        ("authorization", {"decision": "ALLOW"}),
        ("dispatch", {"destination": "CTI"}),
        ("execution_command", "do-it"),
        ("tools", ["nmap"]),
    ):
        request = graph_request(service, mission_id, f"surface-{field}")
        request[field] = value
        with pytest.raises(MissionValidationError, match="does not accept readiness, authorization, dispatch, tools, or execution commands"):
            service.create_task_dependency_graph(mission_id, request)


def test_migration_012_declares_graph_edge_stores_structural_boundary_and_level_12():
    sql = Path("migrations/012_stage3_3_4_task_dependency_graph_structural_validation.sql").read_text().lower()
    assert "create table if not exists mission_task_dependency_graphs" in sql
    assert "create table if not exists mission_task_dependency_edges" in sql
    assert "foreign key (decomposition_id) references mission_task_decompositions(decomposition_id)" in sql
    assert "foreign key (from_planned_task_id) references mission_planned_tasks(planned_task_id)" in sql
    assert "foreign key (to_planned_task_id) references mission_planned_tasks(planned_task_id)" in sql
    assert "planner" in sql
    assert "governance" in sql
    assert "dispatch" in sql
    assert "target actuation" in sql
    assert "    12," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[11].name == "012_stage3_3_4_task_dependency_graph_structural_validation.sql"
