"""Deterministic read-only live Mission state and execution projection for Stage 3.8.4."""
from __future__ import annotations
from typing import Any, Mapping
from .observability_trace import sha256_hex

SCHEMA_VERSION = "apts-live-mission-state-execution-projection-v1"
HASH_DOMAIN = "MISSION_LIVE_STATE_EXECUTION_PROJECTION_V1"
IDENTITY_PREFIX = "mproj-"


def _identity(mission_id: str, trace_id: str) -> str:
    return IDENTITY_PREFIX + sha256_hex({"hash_domain": HASH_DOMAIN, "mission_id": mission_id, "trace_id": trace_id})[:32]


def _latest(items: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return items[-1] if items else None


def _task_id(item: Mapping[str, Any]) -> str | None:
    for path in (("identity","planned_task_id"),("identity","task_id"),("task","planned_task_id"),("planned_task_id",),("task_id",)):
        cur: Any = item
        try:
            for k in path: cur = cur[k]
            if cur: return str(cur)
        except (KeyError, TypeError): pass
    return None


def build_live_mission_state_execution_projection(*, mission_id: str, trace_id: str, mission_state: Mapping[str, Any], normalized_events: list[Mapping[str, Any]], causal_graph: Mapping[str, Any], plan_versions: list[Mapping[str, Any]], planned_tasks: list[Mapping[str, Any]], readiness_projections: list[Mapping[str, Any]], route_decisions: list[Mapping[str, Any]], delegations: list[Mapping[str, Any]], execution_dispatches: list[Mapping[str, Any]], execution_attempts: list[Mapping[str, Any]], running_projections: list[Mapping[str, Any]], result_captures: list[Mapping[str, Any]], termination_controls: list[Mapping[str, Any]], task_outcomes: list[Mapping[str, Any]], task_completions: list[Mapping[str, Any]], adaptation_episodes: list[Mapping[str, Any]], replan_commits: list[Mapping[str, Any]]) -> dict[str, Any]:
    if causal_graph.get("mission_id") != mission_id or causal_graph.get("trace_id") != trace_id:
        raise ValueError("cross-mission or cross-trace causal graph rejected")
    if any(e.get("mission_id") != mission_id or e.get("trace_id") != trace_id for e in normalized_events):
        raise ValueError("cross-mission or cross-trace normalized event rejected")
    task_ids = [_task_id(x) for x in planned_tasks]
    task_ids = [x for x in task_ids if x]
    completed_ids = {_task_id(x) for x in task_completions} | {_task_id(x) for x in task_outcomes}
    completed_ids.discard(None)
    active_execution = max(0, len(execution_attempts) - len(result_captures) - len(termination_controls))
    latest_event = normalized_events[-1] if normalized_events else None
    core = {
        "schema_version": SCHEMA_VERSION, "projection_id": _identity(mission_id, trace_id),
        "mission_id": mission_id, "trace_id": trace_id,
        "mission": {"state": mission_state.get("state"), "state_version": mission_state.get("state_version"), "terminal": mission_state.get("state") in {"COMPLETED","FAILED","ABORTED","EXPIRED"}},
        "plan": {"version_count": len(plan_versions), "latest": _latest(plan_versions)},
        "tasks": {"total": len(task_ids), "completed": len(completed_ids & set(task_ids)), "readiness_projection_count": len(readiness_projections), "route_decision_count": len(route_decisions), "delegation_count": len(delegations)},
        "execution": {"dispatch_count": len(execution_dispatches), "attempt_count": len(execution_attempts), "running_projection_count": len(running_projections), "result_capture_count": len(result_captures), "termination_control_count": len(termination_controls), "active_attempt_count": active_execution, "latest_attempt": _latest(execution_attempts), "latest_running_projection": _latest(running_projections)},
        "adaptation": {"episode_count": len(adaptation_episodes), "replan_commit_count": len(replan_commits), "latest_episode": _latest(adaptation_episodes), "latest_commit": _latest(replan_commits)},
        "causal_head": None if latest_event is None else {"source_event_id": latest_event.get("source_event_id"), "event_type": latest_event.get("event_type"), "source_event_sha256": latest_event.get("source_event_sha256"), "graph_id": causal_graph.get("graph_id"), "graph_sha256": causal_graph.get("integrity",{}).get("canonical_sha256")},
        "source_counts": {"normalized_event_count": len(normalized_events), "causal_graph_node_count": causal_graph.get("node_count"), "causal_graph_edge_count": causal_graph.get("edge_count")},
        "semantics": {"deterministic": True, "restart_stable": True, "read_only_projection": True, "authoritative_state_mutation": False, "authorization_performed": False, "governance_query_performed": False, "runtime_probe_performed": False, "external_network_io_performed": False, "telemetry_export_performed": False, "mission_state_transition_performed": False, "routing_performed": False, "delegation_performed": False, "dispatch_performed": False, "execution_attempt_created": False, "target_action_dispatch_performed": False, "target_actuation": False, "database_migration_added": False, "durable_store_added": False},
    }
    return {**core, "integrity": {"hash_domain": HASH_DOMAIN, "canonical_sha256": sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})}}


def verify_live_mission_state_execution_projection(projection: Mapping[str, Any]) -> bool:
    try:
        if projection.get("schema_version") != SCHEMA_VERSION or not str(projection.get("projection_id","")).startswith(IDENTITY_PREFIX): return False
        sem = projection["semantics"]
        if not sem.get("read_only_projection") or not sem.get("deterministic") or sem.get("authoritative_state_mutation") or sem.get("dispatch_performed") or sem.get("target_actuation"): return False
        core = dict(projection); integrity = core.pop("integrity")
        return integrity.get("hash_domain") == HASH_DOMAIN and integrity.get("canonical_sha256") == sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})
    except (KeyError, TypeError, ValueError): return False


def canonical_live_mission_state_execution_projection_definition() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "identity_prefix": IDENTITY_PREFIX, "mode": "DETERMINISTIC_READ_ONLY_LIVE_MISSION_STATE_EXECUTION_PROJECTION", "sources": ["CANONICAL_MISSION_STATE", "AUTHORITATIVE_STAGE3_3_TO_STAGE3_7_STORES", "STAGE3_8_2_VERIFIED_NORMALIZED_MISSION_EVENT_LEDGER", "STAGE3_8_3_VERIFIED_GLOBAL_CAUSAL_LINEAGE_GRAPH"], "persistence_mode": "DERIVED_NO_NEW_DURABLE_STORE", "database_change_mode": "NO_NEW_DATABASE_MIGRATION", "runtime_side_effects": False}
