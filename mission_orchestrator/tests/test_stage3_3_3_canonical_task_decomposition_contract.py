from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionTaskDecompositionConflict,
    MissionTaskDecompositionGuardRejected,
    MissionTaskDecompositionNotFound,
    MissionValidationError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_decomposition import (
    DEPENDENCY_GRAPH_STATUS_INITIAL,
    MAX_PLANNED_TASKS,
    PLANNED_TASK_ID_PREFIX,
    PLANNED_TASK_SCHEMA_VERSION,
    TASK_DECOMPOSITION_ID_PREFIX,
    TASK_DECOMPOSITION_MODE,
    TASK_DECOMPOSITION_SCHEMA_VERSION,
    TASK_DECOMPOSITION_VERSION_INITIAL,
    TASK_MATERIALIZATION_STATUS,
    TASK_STATUS_INITIAL,
    verify_planned_task_contract,
    verify_task_decomposition_contract,
)


class NoExternalClient:
    base_url = "disabled://stage3.3.3"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise AssertionError(
            f"Stage 3.3.3 task decomposition must remain local-only: unexpected external call {name}"
        )


def make_service(db: Path) -> CanonicalMissionService:
    client = NoExternalClient()
    return CanonicalMissionService(
        MissionRepository(driver="sqlite", sqlite_path=str(db)),
        governance_client=client,
        cti_client=client,
    )


def mission_payload(key: str, *, subsystems: list[str] | None = None) -> dict:
    return {
        "idempotency_key": f"stage333-mission-{key}",
        "source_system": "STAGE333_PYTEST",
        "created_by": "stage3.3.3-pytest",
        "mission_kind": "AUTONOMOUS_PENTEST",
        "objective": {"type": "SECURITY_VALIDATION", "target_ref": "stage333-lab"},
        "success_criteria": [
            {"metric": "structured_tasks_materialized", "expected": True},
            {"metric": "authority_boundary_preserved", "expected": True},
        ],
        "budgets": {"time_seconds": 1200, "max_actions": 10, "risk_ceiling": "LOW"},
        "required_subsystems": list(subsystems or ["CTI"]),
        "pip_id": f"pip-stage333-{key}",
        "pip_version": "17",
        "metadata": {"environment": "LAB", "stage": "3.3.3"},
    }


def create_mission(service: CanonicalMissionService, key: str, *, subsystems: list[str] | None = None) -> str:
    return service.create_mission(mission_payload(key, subsystems=subsystems))["canonical_identity"]["mission_id"]


def lifecycle_request(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "command_id": f"lc-333-{token}",
        "idempotency_key": f"idem-lc-333-{token}",
        "command": command,
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "actor": "stage3.3.3-pytest",
        "reason_code": f"STAGE333_{command}",
        "reason": f"Stage 3.3.3 prerequisite command {command}",
        "evidence_refs": [f"evidence:stage333:{token}"],
        "metadata": {"stage": "3.3.3", "token": token},
    }


def execute(service: CanonicalMissionService, mission_id: str, command: str, token: str) -> dict:
    return service.execute_mission_lifecycle_command(
        mission_id, lifecycle_request(service, mission_id, command, token)
    )


def activate_planning(service: CanonicalMissionService, mission_id: str, token: str) -> None:
    execute(service, mission_id, "BIND_PIP", f"bind-{token}")
    execute(service, mission_id, "START_PLANNING", f"planning-{token}")


def scope_payload(key: str, *, expected: int = 0, max_actions: int = 10) -> dict:
    return {
        "expected_contract_version": expected,
        "idempotency_key": f"stage333-scope-{key}",
        "actor": "stage3.3.3-pytest",
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
            "max_actions": max_actions,
            "max_duration": 1200,
            "risk_threshold": "LOW",
            "resource_budget": {"max_network_requests": 100},
            "data_handling_policy": {"classification": "INTERNAL"},
        },
        "reason": "Stage 3.3.3 canonical task context scope",
        "metadata": {"stage": "3.3.3"},
    }


def plan_request(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "idempotency_key": f"stage333-plan-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.3-pytest",
        "reason": "Register Stage-3.3.1 canonical Plan prerequisite",
        "metadata": {"stage": "3.3.3", "prerequisite": "3.3.1"},
    }


def snapshot_request(service: CanonicalMissionService, mission_id: str, key: str) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    plan = service.get_mission_plan_contract(mission_id)
    return {
        "idempotency_key": f"stage333-snapshot-{key}",
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": plan["plan_version"],
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.3-pytest",
        "reason": "Freeze exact Stage-3.3.2 planner input prerequisite",
        "metadata": {"stage": "3.3.3", "prerequisite": "3.3.2"},
    }


def task_specs() -> list[dict]:
    return [
        {
            "task_key": "collect-cti",
            "task_type": "CTI_COLLECTION",
            "objective": {"goal": "Collect relevant canonical CTI context"},
            "required_capability": "cti.read.context",
            "required_subsystem": "CTI",
            "preconditions": [{"kind": "PIP_BOUND", "required": True}],
            "expected_outputs": [{"artifact": "cti_context", "format": "STRUCTURED"}],
            "success_criteria": [{"metric": "cti_context_available", "expected": True}],
            "evidence_requirements": [{"type": "SOURCE_PROVENANCE"}],
            "priority": 10,
            "metadata": {"stage": "3.3.3", "sequence_hint": 1},
        },
        {
            "task_key": "analyze-cti",
            "task_type": "CTI_ANALYSIS",
            "objective": {"goal": "Analyze CTI context for mission planning"},
            "required_capability": "cti.analyze.context",
            "required_subsystem": "CTI",
            "preconditions": [],
            "expected_outputs": [{"artifact": "cti_analysis", "format": "STRUCTURED"}],
            "success_criteria": [{"metric": "analysis_complete", "expected": True}],
            "evidence_requirements": [{"type": "ANALYSIS_PROVENANCE"}],
            "priority": 20,
            "metadata": {"stage": "3.3.3", "sequence_hint": 2},
        },
    ]


def decomposition_request(
    service: CanonicalMissionService,
    mission_id: str,
    key: str,
    *,
    tasks: list[dict] | None = None,
) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    plan = service.get_mission_plan_contract(mission_id)
    snapshot = service.get_planner_input_snapshot(mission_id)
    return {
        "idempotency_key": f"stage333-decomposition-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": plan["plan_version"],
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snapshot["snapshot_id"],
        "expected_snapshot_version": snapshot["snapshot_version"],
        "expected_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_state_version": state["state_version"],
        "created_by": "stage3.3.3-pytest",
        "reason": "Materialize canonical structured planned tasks without graph/dispatch",
        "tasks": deepcopy(task_specs() if tasks is None else tasks),
        "metadata": {"stage": "3.3.3", "key": key},
    }


def provision_snapshot(
    service: CanonicalMissionService,
    key: str,
    *,
    with_scope: bool = False,
    subsystems: list[str] | None = None,
) -> tuple[str, dict, dict]:
    mission_id = create_mission(service, key, subsystems=subsystems)
    if with_scope:
        service.put_mission_scope_contract(mission_id, scope_payload(key))
    activate_planning(service, mission_id, key)
    plan = service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, key))
    snapshot = service.create_planner_input_snapshot(mission_id, snapshot_request(service, mission_id, key))
    return mission_id, plan, snapshot


def test_health_activates_stage333_and_preserves_planning_authority_boundary(tmp_path):
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
    assert health["task_decomposition_schema_version"] == TASK_DECOMPOSITION_SCHEMA_VERSION
    assert health["planned_task_schema_version"] == PLANNED_TASK_SCHEMA_VERSION
    assert health["task_decomposition_mode"] == TASK_DECOMPOSITION_MODE
    assert health["task_decomposition_initial_version"] == TASK_DECOMPOSITION_VERSION_INITIAL
    assert health["task_decomposition_max_planned_tasks"] == MAX_PLANNED_TASKS
    assert health["task_decomposition_dependency_graph_status"] == DEPENDENCY_GRAPH_STATUS_INITIAL
    assert health["task_decomposition_planner_invocation_performed"] is False
    assert health["task_decomposition_dependency_graph_materialized"] is False
    assert health["task_decomposition_governance_query_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False
    assert health["mission_repository_migration_level"] == 53
    assert REPOSITORY_MIGRATION_LEVEL == 53


def test_task_decomposition_definition_is_discoverable_before_prerequisites(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "definition")
    result = service.get_task_decomposition_definition(mission_id)
    definition = result["task_decomposition_definition"]
    assert result["plan_registered"] is False
    assert result["snapshot_registered"] is False
    assert result["decomposition_registered"] is False
    assert definition["schema_version"] == TASK_DECOMPOSITION_SCHEMA_VERSION
    assert definition["planned_task_schema_version"] == PLANNED_TASK_SCHEMA_VERSION
    assert definition["creation_state_required"] == "PLANNING"
    assert definition["requires_stage3_3_1_plan_contract"] is True
    assert definition["requires_stage3_3_2_planner_input_snapshot"] is True
    assert definition["dependency_fields_allowed"] is False
    assert definition["planner_invocation_performed"] is False
    assert definition["task_is_dispatch"] is False


def test_decomposition_fails_closed_without_plan_or_snapshot_prerequisite(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "no-prereq")
    activate_planning(service, mission_id, "no-prereq")
    fake = {
        "idempotency_key": "stage333-no-prereq",
        "expected_version_sha256": service.get_mission_version_vector(mission_id)["version_sha256"],
        "expected_plan_id": "mplan-missing",
        "expected_plan_version": 1,
        "expected_plan_sha256": "0" * 64,
        "expected_snapshot_id": "mpis-missing",
        "expected_snapshot_version": 1,
        "expected_snapshot_sha256": "0" * 64,
        "expected_state_version": service.get_mission_state(mission_id)["mission_state"]["state_version"],
        "created_by": "stage3.3.3-pytest",
        "tasks": task_specs(),
        "metadata": {},
    }
    with pytest.raises(MissionTaskDecompositionGuardRejected, match="3.3.1"):
        service.create_task_decomposition(mission_id, fake)

    service.create_mission_plan_contract(mission_id, plan_request(service, mission_id, "no-prereq"))
    plan = service.get_mission_plan_contract(mission_id)
    fake.update(
        expected_version_sha256=service.get_mission_version_vector(mission_id)["version_sha256"],
        expected_plan_id=plan["plan_id"],
        expected_plan_version=plan["plan_version"],
        expected_plan_sha256=plan["canonical_sha256"],
    )
    fake["idempotency_key"] = "stage333-no-snapshot"
    with pytest.raises(MissionTaskDecompositionGuardRejected, match="3.3.2"):
        service.create_task_decomposition(mission_id, fake)


def test_canonical_decomposition_materializes_structured_immutable_planned_tasks(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, plan, snapshot = provision_snapshot(service, "canonical")
    result = service.create_task_decomposition(
        mission_id, decomposition_request(service, mission_id, "canonical")
    )
    contract = result["task_decomposition"]
    assert result["idempotent_replay"] is False
    assert result["decomposition_id"].startswith(TASK_DECOMPOSITION_ID_PREFIX)
    assert result["decomposition_version"] == 1
    assert result["task_count"] == 2
    assert result["plan_id"] == plan["plan_id"]
    assert result["snapshot_id"] == snapshot["snapshot_id"]
    assert verify_task_decomposition_contract(contract)
    assert contract["task_set"]["materialization_status"] == TASK_MATERIALIZATION_STATUS
    assert contract["task_set"]["dependency_graph_status"] == "NOT_MATERIALIZED"
    assert contract["task_set"]["dependency_edges"] == []
    assert contract["task_set"]["dependency_edge_count"] == 0
    assert contract["semantics"]["planner_invocation_performed"] is False
    assert contract["semantics"]["plan_contract_mutated"] is False
    assert contract["semantics"]["task_is_dispatch"] is False
    for index, task in enumerate(contract["task_set"]["tasks"], start=1):
        assert task["identity"]["planned_task_id"].startswith(PLANNED_TASK_ID_PREFIX)
        assert task["identity"]["task_index"] == index
        assert task["schema_version"] == PLANNED_TASK_SCHEMA_VERSION
        assert task["dependency_binding"]["status"] == "NOT_MATERIALIZED"
        assert task["dependency_binding"]["dependencies"] == []
        assert task["semantics"]["task_status"] == TASK_STATUS_INITIAL
        assert task["semantics"]["task_is_authorization"] is False
        assert task["semantics"]["target_action_dispatch_enabled"] is False
        assert verify_planned_task_contract(task)


def test_exact_decomposition_replay_is_idempotent_without_duplicate_tasks_or_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "replay")
    request = decomposition_request(service, mission_id, "replay")
    first = service.create_task_decomposition(mission_id, request)
    events_before = service.get_mission_events(mission_id)
    replay = service.create_task_decomposition(mission_id, request)
    events_after = service.get_mission_events(mission_id)
    tasks = service.list_planned_tasks(mission_id)
    assert replay["idempotent_replay"] is True
    assert replay["decomposition_id"] == first["decomposition_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert tasks["task_count"] == 2
    assert events_after["event_count"] == events_before["event_count"]
    assert len([e for e in events_after["events"] if e["event_type"] == "MISSION_TASK_DECOMPOSITION_REGISTERED"]) == 1


def test_idempotency_conflict_and_second_decomposition_are_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "conflict")
    request = decomposition_request(service, mission_id, "conflict")
    service.create_task_decomposition(mission_id, request)

    changed = deepcopy(request)
    changed["tasks"][0]["priority"] = 99
    with pytest.raises(MissionTaskDecompositionConflict, match="idempotency_key"):
        service.create_task_decomposition(mission_id, changed)

    second = deepcopy(request)
    second["idempotency_key"] = "stage333-decomposition-second"
    with pytest.raises(MissionTaskDecompositionConflict, match="already exists"):
        service.create_task_decomposition(mission_id, second)


def test_exact_version_plan_snapshot_and_state_tokens_fail_closed_when_stale(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "stale")
    base = decomposition_request(service, mission_id, "stale")
    cases = [
        ("expected_version_sha256", "0" * 64),
        ("expected_plan_id", "mplan-wrong"),
        ("expected_plan_version", 2),
        ("expected_plan_sha256", "0" * 64),
        ("expected_snapshot_id", "mpis-wrong"),
        ("expected_snapshot_version", 2),
        ("expected_snapshot_sha256", "0" * 64),
        ("expected_state_version", int(base["expected_state_version"]) + 1),
    ]
    for field, value in cases:
        bad = deepcopy(base)
        bad[field] = value
        bad["idempotency_key"] = f"stage333-stale-{field}"
        with pytest.raises(MissionConcurrencyConflict):
            service.create_task_decomposition(mission_id, bad)


def test_task_surface_rejects_dependency_tool_authorization_and_dispatch_fields(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "surface")
    for field, value in (
        ("dependencies", ["collect-cti"]),
        ("tools", ["nmap"]),
        ("authorization", {"decision": "ALLOW"}),
        ("dispatch", {"destination": "CTI"}),
        ("execution_command", "do-it"),
    ):
        tasks = task_specs()
        tasks[1][field] = value
        request = decomposition_request(service, mission_id, f"surface-{field}", tasks=tasks)
        with pytest.raises(MissionValidationError, match="Stage-3.3.4-or-later"):
            service.create_task_decomposition(mission_id, request)


def test_task_schema_requires_nonempty_unique_structured_contract_fields(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "validation")

    with pytest.raises(MissionValidationError, match="at least one"):
        service.create_task_decomposition(
            mission_id, decomposition_request(service, mission_id, "empty", tasks=[])
        )

    duplicate = task_specs()
    duplicate[1]["task_key"] = duplicate[0]["task_key"]
    with pytest.raises(MissionValidationError, match="unique"):
        service.create_task_decomposition(
            mission_id, decomposition_request(service, mission_id, "duplicate", tasks=duplicate)
        )

    missing_output = task_specs()
    missing_output[0]["expected_outputs"] = []
    with pytest.raises(MissionValidationError, match="expected_outputs"):
        service.create_task_decomposition(
            mission_id, decomposition_request(service, mission_id, "missing-output", tasks=missing_output)
        )

    missing_criteria = task_specs()
    missing_criteria[0]["success_criteria"] = []
    with pytest.raises(MissionValidationError, match="success_criteria"):
        service.create_task_decomposition(
            mission_id, decomposition_request(service, mission_id, "missing-criteria", tasks=missing_criteria)
        )


def test_required_subsystem_must_be_declared_by_canonical_mission_snapshot(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "subsystem")
    tasks = task_specs()
    tasks[1]["required_subsystem"] = "PENTEST"
    with pytest.raises(MissionTaskDecompositionGuardRejected, match="required_subsystems"):
        service.create_task_decomposition(
            mission_id, decomposition_request(service, mission_id, "subsystem", tasks=tasks)
        )


def test_scope_drift_after_snapshot_blocks_task_decomposition(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "scope-drift", with_scope=True)
    service.put_mission_scope_contract(
        mission_id, scope_payload("scope-drift-v2", expected=1, max_actions=5)
    )
    request = decomposition_request(service, mission_id, "scope-drift")
    with pytest.raises(MissionTaskDecompositionGuardRejected, match="Scope changed"):
        service.create_task_decomposition(mission_id, request)


def test_state_advance_after_snapshot_blocks_task_decomposition(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "state-drift")
    execute(service, mission_id, "START", "state-drift-run")
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"
    request = decomposition_request(service, mission_id, "state-drift")
    with pytest.raises(MissionTaskDecompositionGuardRejected, match="PLANNING"):
        service.create_task_decomposition(mission_id, request)


def test_stage333_does_not_mutate_plan_or_snapshot_and_leaves_graph_unmaterialized(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "immutable")
    plan_before = service.get_mission_plan_contract(mission_id)
    snapshot_before = service.get_planner_input_snapshot(mission_id)
    service.create_task_decomposition(
        mission_id, decomposition_request(service, mission_id, "immutable")
    )
    plan_after = service.get_mission_plan_contract(mission_id)
    snapshot_after = service.get_planner_input_snapshot(mission_id)
    assert plan_after["canonical_sha256"] == plan_before["canonical_sha256"]
    assert plan_after["plan_contract"] == plan_before["plan_contract"]
    assert plan_after["plan_contract"]["task_graph"]["status"] == "NOT_MATERIALIZED"
    assert plan_after["plan_contract"]["task_graph"]["task_count"] == 0
    assert snapshot_after["canonical_sha256"] == snapshot_before["canonical_sha256"]
    assert snapshot_after["planner_input_snapshot"] == snapshot_before["planner_input_snapshot"]


def test_version_vector_advances_only_task_decomposition_domain_and_no_routing_dispatch(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    assert before["version_vector"]["versions"]["task_decomposition_version"] == 0
    routing_before = deepcopy(before["version_vector"]["local_revisions"])
    service.create_task_decomposition(
        mission_id, decomposition_request(service, mission_id, "vector")
    )
    after = service.get_mission_version_vector(mission_id)
    assert after["version_vector"]["versions"]["task_decomposition_version"] == 1
    assert after["version_vector"]["versions"]["mission_plan_version"] == 1
    assert after["version_vector"]["versions"]["planner_input_snapshot_version"] == 1
    assert after["version_vector"]["local_revisions"] == routing_before
    assert after["version_sha256"] != before["version_sha256"]
    assert service.health()["target_action_dispatch_enabled"] is False


def test_planned_task_read_model_and_integrity_are_canonical(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "read-model")
    created = service.create_task_decomposition(
        mission_id, decomposition_request(service, mission_id, "read-model")
    )
    listed = service.list_planned_tasks(mission_id)
    assert listed["task_count"] == 2
    assert [x["task_key"] for x in listed["planned_tasks"]] == ["collect-cti", "analyze-cti"]
    first_id = listed["planned_tasks"][0]["planned_task_id"]
    first = service.get_planned_task(mission_id, first_id)
    assert first["decomposition_id"] == created["decomposition_id"]
    assert first["task_status"] == "DEFINED"
    assert verify_planned_task_contract(first["planned_task"])
    assert first["planned_task"]["planner_input_binding"]["snapshot_id"] == created["snapshot_id"]


def test_event_repository_manifest_integrity_and_restart_reconstruction_are_local(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, _ = provision_snapshot(service, "repo")
    result = service.create_task_decomposition(
        mission_id, decomposition_request(service, mission_id, "repo")
    )
    events = service.get_mission_events(mission_id)
    decomp_events = [e for e in events["events"] if e["event_type"] == "MISSION_TASK_DECOMPOSITION_REGISTERED"]
    assert len(decomp_events) == 1
    assert decomp_events[0]["causation_id"] == result["decomposition_id"]
    assert decomp_events[0]["plan_version"] == "1"

    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_task_decompositions"] == 1
    assert repo["record_counts"]["mission_planned_tasks"] == 2
    assert repo["persistence_manifest"]["task_decomposition_store"]["decomposition_id"] == result["decomposition_id"]
    assert len(repo["persistence_manifest"]["planned_task_store"]) == 2

    restarted = make_service(db)
    reconstructed = restarted.get_task_decomposition(mission_id)
    tasks = restarted.list_planned_tasks(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)
    assert reconstructed["canonical_sha256"] == result["canonical_sha256"]
    assert tasks["task_count"] == 2
    assert repo_after["integrity_status"] == "PASS"
    assert repo_after["repository_sha256"] == repo["repository_sha256"]


def test_decomposition_integrity_rejects_tampering(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_snapshot(service, "tamper")
    contract = service.create_task_decomposition(
        mission_id, decomposition_request(service, mission_id, "tamper")
    )["task_decomposition"]
    assert verify_task_decomposition_contract(contract)
    tampered = deepcopy(contract)
    tampered["task_set"]["tasks"][0]["specification"]["priority"] = 100
    assert verify_task_decomposition_contract(tampered) is False


def test_missing_decomposition_read_fails_with_typed_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id = create_mission(service, "not-found")
    with pytest.raises(MissionTaskDecompositionNotFound):
        service.get_task_decomposition(mission_id)
    assert service.list_planned_tasks(mission_id)["task_count"] == 0


def test_migration_011_declares_task_stores_stage_boundary_and_level_11():
    sql = Path("migrations/011_stage3_3_3_canonical_task_decomposition_contract.sql").read_text().lower()
    assert "create table if not exists mission_task_decompositions" in sql
    assert "create table if not exists mission_planned_tasks" in sql
    assert "foreign key (plan_id) references mission_plans(plan_id)" in sql
    assert "foreign key (snapshot_id) references mission_planner_input_snapshots(snapshot_id)" in sql
    assert "planner invocation" in sql
    assert "dependency graph" in sql
    assert "governance" in sql
    assert "dispatch" in sql
    assert "target actuation" in sql
    assert "    11," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[10].name == "011_stage3_3_3_canonical_task_decomposition_contract.sql"
