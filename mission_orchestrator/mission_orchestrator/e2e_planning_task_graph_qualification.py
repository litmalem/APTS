from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping, Sequence

from .canonical import verify_envelope
from .e2e_intake_lifecycle_qualification import (
    INTAKE_LIFECYCLE_COMMAND_SEQUENCE,
    INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES,
    INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE,
    INTAKE_LIFECYCLE_QUALIFICATION_TERMINAL_STATE_VERSION,
    canonical_intake_lifecycle_qualification_contract,
)
from .e2e_mission_acceptance import E2E_MISSION_SCENARIO_ID, materialize_canonical_e2e_mission_request
from .mission_plan import verify_plan_contract
from .planner_input_snapshot import verify_planner_input_snapshot
from .task_decomposition import verify_planned_task_contract, verify_task_decomposition_contract
from .task_dependency_graph import verify_task_dependency_edge_contract, verify_task_dependency_graph_contract

PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION = (
    "apts-stage3.9-planning-task-graph-dependency-qualification-v1"
)
PLANNING_TASK_GRAPH_QUALIFICATION_HASH_DOMAIN = (
    "MISSION_STAGE3_9_3_PLANNING_TASK_GRAPH_DEPENDENCY_QUALIFICATION_CONTRACT_V1"
)
PLANNING_TASK_GRAPH_QUALIFICATION_MODE = (
    "EXTERNAL_ACCEPTANCE_HARNESS_EXISTING_STAGE3_3_1_TO_3_3_4_AUTHORITIES_"
    "READ_ONLY_RUNTIME_VERIFICATION_NO_NEW_AUTHORITY"
)
PLANNING_TASK_GRAPH_QUALIFICATION_PREDECESSOR_CONTROL = (
    "stage3.9.2-intake-lifecycle-e2e-segment-qualification"
)
PLANNING_TASK_GRAPH_QUALIFICATION_EXPECTED_MIGRATION_LEVEL = 53
PLANNING_TASK_GRAPH_QUALIFICATION_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
PLANNING_TASK_GRAPH_QUALIFICATION_PERSISTENCE_MODE = (
    "EXISTING_PLAN_SNAPSHOT_DECOMPOSITION_PLANNED_TASK_GRAPH_EDGE_AND_EVENT_STORES_ONLY"
)
PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE = "PLANNING"
PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE_VERSION = 3
PLANNING_TASK_GRAPH_QUALIFICATION_GRAPH_STATUS = "PASS"
PLANNING_TASK_GRAPH_QUALIFICATION_TASK_COUNT = 3
PLANNING_TASK_GRAPH_QUALIFICATION_EDGE_COUNT = 2
PLANNING_TASK_GRAPH_QUALIFICATION_NEXT_STAGE = "3.9.4"

PLANNING_TASK_GRAPH_TASK_KEYS = (
    "collect-cti",
    "analyze-cti",
    "report-findings",
)
PLANNING_TASK_GRAPH_EDGES = (
    ("collect-cti", "analyze-cti"),
    ("analyze-cti", "report-findings"),
)
PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES = INTAKE_LIFECYCLE_EXPECTED_EVENT_TYPES + (
    "MISSION_PLAN_CONTRACT_REGISTERED",
    "MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED",
    "MISSION_TASK_DECOMPOSITION_REGISTERED",
    "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED",
)
PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS = {
    "global_missions": 1,
    "mission_envelopes": 1,
    "mission_states": 1,
    "mission_state_transitions": 2,
    "mission_command_journal": 2,
    "mission_plans": 1,
    "mission_planner_input_snapshots": 1,
    "mission_task_decompositions": 1,
    "mission_planned_tasks": 3,
    "mission_task_dependency_graphs": 1,
    "mission_task_dependency_edges": 2,
    "mission_events": 9,
}
PLANNING_TASK_GRAPH_FORBIDDEN_NEW_AUTHORITIES = (
    "governance_authorization",
    "routing",
    "delegation",
    "dispatch",
    "execution",
    "target_action_dispatch",
    "target_actuation",
    "external_network_io",
    "telemetry_export",
    "planner_invocation",
    "generated_plan_materialization",
    "plan_validation",
    "plan_activation",
    "readiness_projection",
    "scheduling",
    "database_migration",
    "durable_store_creation",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = _canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_run_id(run_id: str) -> None:
    materialize_canonical_e2e_mission_request(run_id)


def canonical_planning_task_specs(run_id: str) -> list[dict[str, Any]]:
    _validate_run_id(run_id)
    return [
        {
            "task_key": "collect-cti",
            "task_type": "CTI_COLLECTION",
            "objective": {"goal": "Collect canonical CTI context for the Stage 3.9 E2E mission"},
            "required_capability": "cti.read.context",
            "required_subsystem": "CTI",
            "preconditions": [{"kind": "PIP_BOUND", "required": True}],
            "expected_outputs": [{"artifact": "cti_context", "format": "STRUCTURED"}],
            "success_criteria": [{"metric": "cti_context_available", "expected": True}],
            "evidence_requirements": [{"type": "SOURCE_PROVENANCE"}],
            "priority": 10,
            "metadata": {"stage": "3.9.3", "run_id": run_id, "sequence_hint": 1},
        },
        {
            "task_key": "analyze-cti",
            "task_type": "CTI_ANALYSIS",
            "objective": {"goal": "Analyze canonical CTI context for the Stage 3.9 E2E mission"},
            "required_capability": "cti.analyze.context",
            "required_subsystem": "CTI",
            "preconditions": [],
            "expected_outputs": [{"artifact": "cti_analysis", "format": "STRUCTURED"}],
            "success_criteria": [{"metric": "analysis_complete", "expected": True}],
            "evidence_requirements": [{"type": "ANALYSIS_PROVENANCE"}],
            "priority": 20,
            "metadata": {"stage": "3.9.3", "run_id": run_id, "sequence_hint": 2},
        },
        {
            "task_key": "report-findings",
            "task_type": "CTI_REPORT",
            "objective": {"goal": "Structure canonical planning findings for the Stage 3.9 E2E mission"},
            "required_capability": "cti.report.context",
            "required_subsystem": "CTI",
            "preconditions": [],
            "expected_outputs": [{"artifact": "planning_findings", "format": "STRUCTURED"}],
            "success_criteria": [{"metric": "findings_structured", "expected": True}],
            "evidence_requirements": [{"type": "SOURCE_PROVENANCE"}],
            "priority": 30,
            "metadata": {"stage": "3.9.3", "run_id": run_id, "sequence_hint": 3},
        },
    ]


def canonical_planning_dependency_edges() -> list[dict[str, str]]:
    return [
        {"from_task_key": source, "to_task_key": target}
        for source, target in PLANNING_TASK_GRAPH_EDGES
    ]


def canonical_planning_task_graph_qualification_contract() -> dict[str, Any]:
    predecessor = canonical_intake_lifecycle_qualification_contract()
    core = {
        "schema_version": PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION,
        "mode": PLANNING_TASK_GRAPH_QUALIFICATION_MODE,
        "predecessor_control": PLANNING_TASK_GRAPH_QUALIFICATION_PREDECESSOR_CONTROL,
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": predecessor["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": PLANNING_TASK_GRAPH_QUALIFICATION_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": PLANNING_TASK_GRAPH_QUALIFICATION_DATABASE_CHANGE_MODE,
        "persistence_mode": PLANNING_TASK_GRAPH_QUALIFICATION_PERSISTENCE_MODE,
        "entry_head": {
            "state": PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE,
            "state_version": PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE_VERSION,
            "plan_materialized": False,
        },
        "existing_authority_sequence": [
            "STAGE3_3_1_CANONICAL_PLAN_CONTRACT",
            "STAGE3_3_2_PLANNER_INPUT_SNAPSHOT",
            "STAGE3_3_3_CANONICAL_TASK_DECOMPOSITION",
            "STAGE3_3_4_TASK_DEPENDENCY_GRAPH_STRUCTURAL_VALIDATION",
        ],
        "canonical_task_keys": list(PLANNING_TASK_GRAPH_TASK_KEYS),
        "canonical_dependency_edges": canonical_planning_dependency_edges(),
        "qualified_segment_head": {
            "state": PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE,
            "state_version": PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE_VERSION,
            "plan_version": 1,
            "snapshot_version": 1,
            "decomposition_version": 1,
            "task_count": PLANNING_TASK_GRAPH_QUALIFICATION_TASK_COUNT,
            "graph_version": 1,
            "graph_validation_status": PLANNING_TASK_GRAPH_QUALIFICATION_GRAPH_STATUS,
            "edge_count": PLANNING_TASK_GRAPH_QUALIFICATION_EDGE_COUNT,
            "planner_invoked": False,
            "generated_plan_materialized": False,
            "readiness_projected": False,
        },
        "expected_event_types": list(PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS),
        "dependency_verification": {
            "complete_node_set_required": True,
            "no_dangling_edges": True,
            "no_self_dependencies": True,
            "no_duplicate_edges": True,
            "directed_acyclic_graph_required": True,
            "expected_topological_task_keys": list(PLANNING_TASK_GRAPH_TASK_KEYS),
            "expected_root_task_keys": ["collect-cti"],
            "expected_leaf_task_keys": ["report-findings"],
        },
        "replay_requirements": {
            "plan_exact_replay_is_idempotent": True,
            "snapshot_exact_replay_is_idempotent": True,
            "decomposition_exact_replay_is_idempotent": True,
            "dependency_graph_exact_replay_is_idempotent": True,
            "no_duplicate_planning_artifact_or_event": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True,
            "acceptance_execution_uses_existing_stage3_3_public_routes": True,
            "new_planner_authority_added": False,
            "new_governance_authority_added": False,
            "new_routing_authority_added": False,
            "new_delegation_authority_added": False,
            "new_dispatch_authority_added": False,
            "new_execution_authority_added": False,
            "new_target_actuation_authority_added": False,
            "new_external_network_io_added": False,
            "new_telemetry_export_added": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "forbidden_new_authorities": list(PLANNING_TASK_GRAPH_FORBIDDEN_NEW_AUTHORITIES),
        },
    }
    return {
        **core,
        "integrity": {
            "hash_domain": PLANNING_TASK_GRAPH_QUALIFICATION_HASH_DOMAIN,
            "canonical_sha256": _sha256_hex({
                "hash_domain": PLANNING_TASK_GRAPH_QUALIFICATION_HASH_DOMAIN,
                "core": core,
            }),
        },
    }


def verify_planning_task_graph_qualification_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION:
            return False
        core = dict(contract)
        integrity = core.pop("integrity")
        expected = _sha256_hex({
            "hash_domain": PLANNING_TASK_GRAPH_QUALIFICATION_HASH_DOMAIN,
            "core": core,
        })
        if integrity.get("hash_domain") != PLANNING_TASK_GRAPH_QUALIFICATION_HASH_DOMAIN:
            return False
        if integrity.get("canonical_sha256") != expected:
            return False
        return dict(contract) == canonical_planning_task_graph_qualification_contract()
    except (KeyError, TypeError, ValueError):
        return False


def _meta(run_id: str, artifact: str) -> dict[str, Any]:
    return {
        "stage": "3.9.3",
        "scenario_id": E2E_MISSION_SCENARIO_ID,
        "run_id": run_id,
        "segment": "PLANNING_TO_TASK_GRAPH",
        "artifact": artifact,
    }


def build_planning_plan_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage393-{run_id}-plan",
        "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version,
        "created_by": "stage3.9.3-acceptance-runner",
        "reason": "Stage 3.9.3 canonical E2E Plan materialization",
        "metadata": _meta(run_id, "CANONICAL_PLAN"),
    }


def build_planning_snapshot_request(*, run_id: str, plan: Mapping[str, Any], expected_state_version: int) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage393-{run_id}-snapshot",
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": int(plan["plan_version"]),
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_state_version": expected_state_version,
        "created_by": "stage3.9.3-acceptance-runner",
        "reason": "Stage 3.9.3 canonical E2E planner-input snapshot",
        "metadata": _meta(run_id, "PLANNER_INPUT_SNAPSHOT"),
    }


def build_planning_decomposition_request(
    *, run_id: str, expected_version_sha256: str, expected_state_version: int,
    plan: Mapping[str, Any], snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage393-{run_id}-decomposition",
        "expected_version_sha256": expected_version_sha256,
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": int(plan["plan_version"]),
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snapshot["snapshot_id"],
        "expected_snapshot_version": int(snapshot["snapshot_version"]),
        "expected_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_state_version": expected_state_version,
        "created_by": "stage3.9.3-acceptance-runner",
        "reason": "Stage 3.9.3 canonical E2E task decomposition",
        "tasks": canonical_planning_task_specs(run_id),
        "metadata": _meta(run_id, "TASK_DECOMPOSITION"),
    }


def build_planning_dependency_graph_request(
    *, run_id: str, expected_version_sha256: str, expected_state_version: int,
    plan: Mapping[str, Any], snapshot: Mapping[str, Any], decomposition: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage393-{run_id}-dependency-graph",
        "expected_version_sha256": expected_version_sha256,
        "expected_plan_id": plan["plan_id"],
        "expected_plan_version": int(plan["plan_version"]),
        "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snapshot["snapshot_id"],
        "expected_snapshot_version": int(snapshot["snapshot_version"]),
        "expected_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_decomposition_id": decomposition["decomposition_id"],
        "expected_decomposition_version": int(decomposition["decomposition_version"]),
        "expected_decomposition_sha256": decomposition["canonical_sha256"],
        "expected_task_set_sha256": decomposition["task_set_sha256"],
        "expected_state_version": expected_state_version,
        "created_by": "stage3.9.3-acceptance-runner",
        "reason": "Stage 3.9.3 canonical E2E dependency DAG materialization and structural verification",
        "edges": canonical_planning_dependency_edges(),
        "metadata": _meta(run_id, "TASK_DEPENDENCY_GRAPH"),
    }


def _check(checks: list[dict[str, Any]], check_id: str, passed: bool, observed: Any, required: Any) -> None:
    checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "observed": observed, "required": required})


def _request_projection(envelope: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provenance": {k: envelope.get("provenance", {}).get(k) for k in ("source_system", "created_by", "idempotency_key")},
        "mission": envelope.get("mission"),
        "bindings": envelope.get("bindings"),
        "metadata": envelope.get("metadata"),
    }


def _expected_envelope_projection(run_id: str) -> dict[str, Any]:
    request = materialize_canonical_e2e_mission_request(run_id)
    return {
        "provenance": {k: request[k] for k in ("source_system", "created_by", "idempotency_key")},
        "mission": {k: request[k] for k in ("mission_kind", "objective", "success_criteria", "budgets", "required_subsystems")},
        "bindings": {
            "scope": {
                "scope_contract_id": request["scope_contract_id"], "scope_version": request["scope_version"],
                "scope_snapshot_id": f"{request['scope_contract_id']}@v{request['scope_version']}", "roe_version": request["roe_version"],
            },
            "pip": {"pip_id": request["pip_id"], "pip_version": request["pip_version"]},
            "governance": {"authority": "aptsGSS", "authority_component": "GOV-PLANE", "policy_version": request["policy_version"]},
        },
        "metadata": request["metadata"],
    }


def evaluate_planning_task_graph_qualification(
    *, mission_id: str, envelope: Mapping[str, Any], state: Mapping[str, Any],
    transitions: Sequence[Mapping[str, Any]], commands: Sequence[Mapping[str, Any]],
    plan_record: Mapping[str, Any] | None, snapshot_record: Mapping[str, Any] | None,
    decomposition_record: Mapping[str, Any] | None, planned_task_records: Sequence[Mapping[str, Any]],
    graph_record: Mapping[str, Any] | None, edge_records: Sequence[Mapping[str, Any]],
    planner_invocation_present: bool, generated_plan_present: bool, readiness_projection_present: bool,
    events: Sequence[Mapping[str, Any]], repository_counts: Mapping[str, int], event_integrity_status: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    metadata = envelope.get("metadata") if isinstance(envelope.get("metadata"), Mapping) else {}
    run_id = metadata.get("run_id")
    run_valid = isinstance(run_id, str)
    expected_envelope = None
    if run_valid:
        try:
            expected_envelope = _expected_envelope_projection(run_id)
        except ValueError:
            run_valid = False

    _check(checks, "CANONICAL_RUN_BINDING_PRESENT", run_valid, run_id, "VALID_STAGE3_9_RUN_ID")
    _check(checks, "CANONICAL_ENVELOPE_INTEGRITY", verify_envelope(envelope), "VERIFIED" if verify_envelope(envelope) else "FAILED", "VERIFIED")
    _check(checks, "CANONICAL_SCENARIO_ID", metadata.get("scenario_id") == E2E_MISSION_SCENARIO_ID, metadata.get("scenario_id"), E2E_MISSION_SCENARIO_ID)
    observed_projection = None if expected_envelope is None else _request_projection(envelope, expected_envelope)
    _check(checks, "FROZEN_STAGE391_REQUEST_SEMANTICS", observed_projection == expected_envelope if expected_envelope else False, observed_projection, expected_envelope or "CANONICAL_STAGE391_REQUEST")

    _check(checks, "ENTRY_HEAD_REMAINS_PLANNING", state.get("state") == PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE and state.get("state_version") == PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE_VERSION and state.get("terminal") is False, {"state": state.get("state"), "state_version": state.get("state_version"), "terminal": state.get("terminal")}, {"state": "PLANNING", "state_version": 3, "terminal": False})
    transition_projection = [(x.get("from_state"), x.get("to_state"), x.get("from_state_version"), x.get("to_state_version")) for x in transitions]
    required_transitions = [(a, b, c, d) for _, a, b, c, d in INTAKE_LIFECYCLE_COMMAND_SEQUENCE]
    _check(checks, "PREDECESSOR_LIFECYCLE_TRANSITIONS_PRESERVED", transition_projection == required_transitions, transition_projection, required_transitions)
    command_names = []
    for row in commands:
        result = row.get("result") if isinstance(row.get("result"), Mapping) else {}
        transition = result.get("transition") if isinstance(result.get("transition"), Mapping) else {}
        tmeta = transition.get("metadata") if isinstance(transition.get("metadata"), Mapping) else {}
        command_names.append(tmeta.get("lifecycle_command"))
    _check(checks, "PREDECESSOR_LIFECYCLE_COMMANDS_PRESERVED", command_names == ["BIND_PIP", "START_PLANNING"], command_names, ["BIND_PIP", "START_PLANNING"])

    plan_ok = bool(plan_record and verify_plan_contract(plan_record.get("plan_contract", {})) and int(plan_record.get("plan_version", 0)) == 1 and plan_record.get("mission_id") == mission_id)
    _check(checks, "CANONICAL_PLAN_VERIFIED", plan_ok, None if not plan_record else plan_record.get("plan_id"), "mplan-* / v1 / VERIFIED")
    snapshot_ok = bool(snapshot_record and verify_planner_input_snapshot(snapshot_record.get("snapshot", {})) and int(snapshot_record.get("snapshot_version", 0)) == 1 and plan_record and snapshot_record.get("plan_id") == plan_record.get("plan_id"))
    _check(checks, "PLANNER_INPUT_SNAPSHOT_VERIFIED", snapshot_ok, None if not snapshot_record else snapshot_record.get("snapshot_id"), "mpis-* / v1 / PLAN_BOUND / VERIFIED")
    decomposition_ok = bool(decomposition_record and verify_task_decomposition_contract(decomposition_record.get("decomposition", {})) and int(decomposition_record.get("decomposition_version", 0)) == 1 and snapshot_record and decomposition_record.get("snapshot_id") == snapshot_record.get("snapshot_id") and plan_record and decomposition_record.get("plan_id") == plan_record.get("plan_id"))
    _check(checks, "TASK_DECOMPOSITION_VERIFIED", decomposition_ok, None if not decomposition_record else decomposition_record.get("decomposition_id"), "mdecomp-* / v1 / SNAPSHOT_BOUND / VERIFIED")

    task_contracts_ok = len(planned_task_records) == PLANNING_TASK_GRAPH_QUALIFICATION_TASK_COUNT and all(verify_planned_task_contract(row.get("task_contract", {})) for row in planned_task_records)
    observed_task_keys = [row.get("task_key") for row in sorted(planned_task_records, key=lambda x: int(x.get("task_index", 0)))]
    task_run_binding_ok = run_valid and all((row.get("task_contract", {}).get("provenance", {}).get("task_metadata", {}) or {}).get("run_id") == run_id for row in planned_task_records)
    _check(checks, "CANONICAL_TASK_SET_VERIFIED", task_contracts_ok and observed_task_keys == list(PLANNING_TASK_GRAPH_TASK_KEYS), observed_task_keys, list(PLANNING_TASK_GRAPH_TASK_KEYS))
    _check(checks, "TASK_SET_RUN_BINDING", task_run_binding_ok, task_run_binding_ok, True)

    graph_contract = {} if not graph_record else graph_record.get("graph", {})
    graph_ok = bool(graph_record and verify_task_dependency_graph_contract(graph_contract) and int(graph_record.get("graph_version", 0)) == 1 and graph_record.get("validation_status") == "PASS" and decomposition_record and graph_record.get("decomposition_id") == decomposition_record.get("decomposition_id"))
    _check(checks, "DEPENDENCY_GRAPH_INTEGRITY_AND_STATUS", graph_ok, None if not graph_record else {"graph_id": graph_record.get("graph_id"), "status": graph_record.get("validation_status")}, {"id": "mgraph-*", "status": "PASS"})
    edges_ok = len(edge_records) == PLANNING_TASK_GRAPH_QUALIFICATION_EDGE_COUNT and all(verify_task_dependency_edge_contract(row.get("edge", {})) for row in edge_records)
    observed_edges = [(row.get("from_task_key"), row.get("to_task_key")) for row in edge_records]
    _check(checks, "DEPENDENCY_EDGES_VERIFIED", edges_ok and observed_edges == list(PLANNING_TASK_GRAPH_EDGES), observed_edges, list(PLANNING_TASK_GRAPH_EDGES))

    graph_payload = graph_contract.get("graph", {}) if isinstance(graph_contract, Mapping) else {}
    dag_projection = {
        "topological_task_keys": graph_payload.get("topological_task_keys"),
        "root_task_keys": graph_payload.get("root_task_keys"),
        "leaf_task_keys": graph_payload.get("leaf_task_keys"),
        "node_count": graph_record.get("node_count") if graph_record else None,
        "edge_count": graph_record.get("edge_count") if graph_record else None,
    }
    expected_dag = {"topological_task_keys": list(PLANNING_TASK_GRAPH_TASK_KEYS), "root_task_keys": ["collect-cti"], "leaf_task_keys": ["report-findings"], "node_count": 3, "edge_count": 2}
    _check(checks, "DEPENDENCY_DAG_STRUCTURAL_VERIFICATION", dag_projection == expected_dag, dag_projection, expected_dag)

    lineage_ok = bool(plan_record and snapshot_record and decomposition_record and graph_record and snapshot_record.get("plan_id") == plan_record.get("plan_id") and decomposition_record.get("plan_id") == plan_record.get("plan_id") and graph_record.get("plan_id") == plan_record.get("plan_id") and decomposition_record.get("snapshot_id") == snapshot_record.get("snapshot_id") and graph_record.get("snapshot_id") == snapshot_record.get("snapshot_id") and graph_record.get("decomposition_id") == decomposition_record.get("decomposition_id"))
    _check(checks, "PLAN_SNAPSHOT_TASK_GRAPH_LINEAGE", lineage_ok, lineage_ok, True)

    no_downstream = not planner_invocation_present and not generated_plan_present and not readiness_projection_present
    _check(checks, "DOWNSTREAM_PLANNER_AND_READINESS_UNMATERIALIZED", no_downstream, {"planner_invocation": planner_invocation_present, "generated_plan": generated_plan_present, "readiness_projection": readiness_projection_present}, {"planner_invocation": False, "generated_plan": False, "readiness_projection": False})

    observed_event_types = [x.get("event_type") for x in events]
    _check(checks, "EXACT_EVENT_SEQUENCE", observed_event_types == list(PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES), observed_event_types, list(PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES))
    _check(checks, "EVENT_LEDGER_INTEGRITY", event_integrity_status == "PASS", event_integrity_status, "PASS")
    mission_binding_ok = all(x.get("mission_id") == mission_id for x in events) and all(x.get("mission_id") == mission_id for x in transitions)
    _check(checks, "SINGLE_MISSION_ROOT_BINDING", mission_binding_ok, mission_binding_ok, True)

    nonzero = {k: int(v) for k, v in repository_counts.items() if int(v) != 0}
    expected_counts = dict(PLANNING_TASK_GRAPH_ALLOWED_NONZERO_REPOSITORY_COUNTS)
    _check(checks, "EXACT_SEGMENT_REPOSITORY_FOOTPRINT", nonzero == expected_counts, nonzero, expected_counts)

    failures = [x["check_id"] for x in checks if x["status"] != "PASS"]
    contract = canonical_planning_task_graph_qualification_contract()
    return {
        "schema_version": PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION,
        "segment": "PLANNING_TO_TASK_GRAPH_DEPENDENCY_VERIFICATION",
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "qualification_contract_sha256": contract["integrity"]["canonical_sha256"],
        "mission_id": mission_id,
        "run_id": run_id,
        "status": "QUALIFIED" if not failures else "REJECTED",
        "qualified": not failures,
        "failed_check_ids": failures,
        "checks": checks,
        "segment_head": {
            "state": state.get("state"), "state_version": state.get("state_version"),
            "plan_id": None if not plan_record else plan_record.get("plan_id"),
            "snapshot_id": None if not snapshot_record else snapshot_record.get("snapshot_id"),
            "decomposition_id": None if not decomposition_record else decomposition_record.get("decomposition_id"),
            "task_count": len(planned_task_records),
            "graph_id": None if not graph_record else graph_record.get("graph_id"),
            "graph_validation_status": None if not graph_record else graph_record.get("validation_status"),
            "edge_count": len(edge_records), "event_count": len(events),
        },
        "authority_boundary": {
            "verification_read_only": True,
            "new_planner_authority_added": False,
            "new_governance_authority_added": False,
            "new_routing_authority_added": False,
            "new_delegation_authority_added": False,
            "new_dispatch_authority_added": False,
            "new_execution_authority_added": False,
            "new_target_actuation_authority_added": False,
            "new_external_network_io_added": False,
            "new_telemetry_export_added": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
        },
    }


def canonical_planning_task_graph_qualification_definition() -> dict[str, Any]:
    contract = canonical_planning_task_graph_qualification_contract()
    return {
        "schema_version": PLANNING_TASK_GRAPH_QUALIFICATION_SCHEMA_VERSION,
        "mode": PLANNING_TASK_GRAPH_QUALIFICATION_MODE,
        "predecessor_control": PLANNING_TASK_GRAPH_QUALIFICATION_PREDECESSOR_CONTROL,
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": PLANNING_TASK_GRAPH_QUALIFICATION_EXPECTED_MIGRATION_LEVEL,
        "qualified_segment_head_state": PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE,
        "qualified_segment_head_state_version": PLANNING_TASK_GRAPH_QUALIFICATION_ENTRY_STATE_VERSION,
        "qualified_graph_validation_status": PLANNING_TASK_GRAPH_QUALIFICATION_GRAPH_STATUS,
        "qualified_task_count": PLANNING_TASK_GRAPH_QUALIFICATION_TASK_COUNT,
        "qualified_edge_count": PLANNING_TASK_GRAPH_QUALIFICATION_EDGE_COUNT,
        "runtime_verifier_read_only": True,
        "acceptance_execution_uses_existing_stage3_3_public_routes": True,
        "new_planner_authority_added": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "new_execution_authority_added": False,
        "next_stage": PLANNING_TASK_GRAPH_QUALIFICATION_NEXT_STAGE,
    }
