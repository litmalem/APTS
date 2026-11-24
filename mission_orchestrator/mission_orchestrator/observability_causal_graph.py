"""Deterministic read-only global causal lineage graph projection for Stage 3.8.3."""

from __future__ import annotations

from typing import Any, Mapping

from .observability_trace import sha256_hex

SCHEMA_VERSION = "apts-global-causal-lineage-graph-v1"
NODE_SCHEMA_VERSION = "apts-global-causal-lineage-node-v1"
EDGE_SCHEMA_VERSION = "apts-global-causal-lineage-edge-v1"
HASH_DOMAIN = "MISSION_GLOBAL_CAUSAL_LINEAGE_GRAPH_V1"
NODE_HASH_DOMAIN = "MISSION_GLOBAL_CAUSAL_LINEAGE_NODE_V1"
EDGE_HASH_DOMAIN = "MISSION_GLOBAL_CAUSAL_LINEAGE_EDGE_V1"
IDENTITY_PREFIX = "cgraph-"
NODE_ID_PREFIX = "cnode-"
EDGE_ID_PREFIX = "cedge-"


def _identity(prefix: str, domain: str, material: Mapping[str, Any]) -> str:
    return prefix + sha256_hex({"hash_domain": domain, "material": dict(material)})[:32]


def _node(core: dict[str, Any]) -> dict[str, Any]:
    return {**core, "integrity": {"hash_domain": NODE_HASH_DOMAIN, "canonical_sha256": sha256_hex({"hash_domain": NODE_HASH_DOMAIN, "core": core})}}


def _edge(source: str, target: str, relation: str, ordinal: int) -> dict[str, Any]:
    material = {"source_node_id": source, "target_node_id": target, "relation_type": relation, "ordinal": ordinal}
    edge_id = _identity(EDGE_ID_PREFIX, EDGE_HASH_DOMAIN, material)
    core = {"schema_version": EDGE_SCHEMA_VERSION, "edge_id": edge_id, **material}
    return {**core, "integrity": {"hash_domain": EDGE_HASH_DOMAIN, "canonical_sha256": sha256_hex({"hash_domain": EDGE_HASH_DOMAIN, "core": core})}}


def build_global_causal_lineage_graph(*, mission_id: str, trace_id: str, normalized_events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a deterministic DAG exclusively from the verified normalized ledger projection."""
    event_ids = [str(e["source_event_id"]) for e in normalized_events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("duplicate normalized source event rejected")
    if any(e.get("mission_id") != mission_id or e.get("trace_id") != trace_id for e in normalized_events):
        raise ValueError("cross-mission or cross-trace normalized event rejected")

    graph_id = _identity(IDENTITY_PREFIX, HASH_DOMAIN, {"mission_id": mission_id, "trace_id": trace_id})
    root_id = _identity(NODE_ID_PREFIX, NODE_HASH_DOMAIN, {"kind": "MISSION_ROOT", "mission_id": mission_id, "trace_id": trace_id})
    root_core = {
        "schema_version": NODE_SCHEMA_VERSION, "node_id": root_id, "node_type": "MISSION_ROOT",
        "mission_id": mission_id, "trace_id": trace_id, "source_event_id": None,
        "source_event_sha256": None, "event_type": None, "source_component": "mission_orchestrator",
        "occurred_at_utc": None, "causation_id": None, "parent_event_id": None,
    }
    nodes = [_node(root_core)]
    event_node_ids: dict[str, str] = {}
    for event in normalized_events:
        source_event_id = str(event["source_event_id"])
        node_id = _identity(NODE_ID_PREFIX, NODE_HASH_DOMAIN, {
            "mission_id": mission_id, "trace_id": trace_id, "source_event_id": source_event_id,
            "source_event_sha256": event["source_event_sha256"],
        })
        event_node_ids[source_event_id] = node_id
        core = {
            "schema_version": NODE_SCHEMA_VERSION, "node_id": node_id, "node_type": "MISSION_EVENT",
            "mission_id": mission_id, "trace_id": trace_id, "source_event_id": source_event_id,
            "source_event_sha256": event["source_event_sha256"], "event_type": event["event_type"],
            "source_component": event["source_component"], "occurred_at_utc": event["occurred_at_utc"],
            "causation_id": event.get("causation_id"), "parent_event_id": event.get("parent_event_id"),
        }
        nodes.append(_node(core))

    edges: list[dict[str, Any]] = []
    unresolved_causation_refs: list[dict[str, str]] = []
    for ordinal, event in enumerate(normalized_events):
        eid = str(event["source_event_id"])
        target = event_node_ids[eid]
        parent = event.get("parent_event_id")
        if parent:
            if parent not in event_node_ids:
                raise ValueError(f"dangling parent event rejected: {parent}")
            source = event_node_ids[parent]
            relation = "PARENT_EVENT"
        else:
            source = root_id
            relation = "MISSION_ROOT"
        edges.append(_edge(source, target, relation, ordinal))

        causation = event.get("causation_id")
        if causation and causation != parent:
            if causation in event_node_ids:
                edges.append(_edge(event_node_ids[causation], target, "CAUSATION_EVENT", ordinal))
            else:
                unresolved_causation_refs.append({"source_event_id": eid, "causation_id": str(causation)})

    # Parent edges are guaranteed to point to an earlier ledger event by verified ledger semantics.
    positions = {eid: i for i, eid in enumerate(event_ids)}
    for event in normalized_events:
        parent = event.get("parent_event_id")
        if parent and positions[parent] >= positions[str(event["source_event_id"])]:
            raise ValueError("non-causal parent ordering rejected")

    core = {
        "schema_version": SCHEMA_VERSION, "graph_id": graph_id, "mission_id": mission_id, "trace_id": trace_id,
        "root_node_id": root_id, "node_count": len(nodes), "edge_count": len(edges),
        "nodes": nodes, "edges": edges, "unresolved_external_causation_refs": unresolved_causation_refs,
        "semantics": {
            "directed": True, "acyclic": True, "deterministic": True, "restart_stable": True,
            "read_only_projection": True, "source": "STAGE3_8_2_VERIFIED_NORMALIZED_MISSION_EVENT_LEDGER",
            "external_causation_refs_are_authority": False, "authorization_performed": False,
            "governance_query_performed": False, "runtime_probe_performed": False,
            "external_network_io_performed": False, "telemetry_export_performed": False,
            "mission_state_transition_performed": False, "routing_performed": False,
            "delegation_performed": False, "dispatch_performed": False,
            "execution_attempt_created": False, "target_action_dispatch_performed": False,
            "target_actuation": False, "database_migration_added": False, "durable_store_added": False,
        },
    }
    return {**core, "integrity": {"hash_domain": HASH_DOMAIN, "canonical_sha256": sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})}}


def verify_global_causal_lineage_graph(graph: Mapping[str, Any]) -> bool:
    try:
        if graph.get("schema_version") != SCHEMA_VERSION:
            return False
        nodes = list(graph["nodes"]); edges = list(graph["edges"])
        node_ids = {n["node_id"] for n in nodes}
        if len(node_ids) != len(nodes) or graph["root_node_id"] not in node_ids:
            return False
        if graph.get("node_count") != len(nodes) or graph.get("edge_count") != len(edges):
            return False
        for n in nodes:
            ni = n["integrity"]; core = dict(n); core.pop("integrity", None)
            if ni.get("canonical_sha256") != sha256_hex({"hash_domain": NODE_HASH_DOMAIN, "core": core}): return False
        adjacency = {nid: [] for nid in node_ids}; indegree = {nid: 0 for nid in node_ids}
        for e in edges:
            if e["source_node_id"] not in node_ids or e["target_node_id"] not in node_ids: return False
            ei = e["integrity"]; core = dict(e); core.pop("integrity", None)
            if ei.get("canonical_sha256") != sha256_hex({"hash_domain": EDGE_HASH_DOMAIN, "core": core}): return False
            adjacency[e["source_node_id"]].append(e["target_node_id"]); indegree[e["target_node_id"]] += 1
        queue = sorted([n for n, d in indegree.items() if d == 0]); visited = []
        while queue:
            n = queue.pop(0); visited.append(n)
            for child in adjacency[n]:
                indegree[child] -= 1
                if indegree[child] == 0: queue.append(child); queue.sort()
        if len(visited) != len(nodes): return False
        reachable = {graph["root_node_id"]}; stack = [graph["root_node_id"]]
        while stack:
            for child in adjacency[stack.pop()]:
                if child not in reachable: reachable.add(child); stack.append(child)
        if reachable != node_ids: return False
        core = dict(graph); integrity = core.pop("integrity")
        return integrity.get("hash_domain") == HASH_DOMAIN and integrity.get("canonical_sha256") == sha256_hex({"hash_domain": HASH_DOMAIN, "core": core})
    except (KeyError, TypeError, ValueError):
        return False


def canonical_global_causal_lineage_graph_definition() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "node_schema_version": NODE_SCHEMA_VERSION,
        "edge_schema_version": EDGE_SCHEMA_VERSION, "identity_prefix": IDENTITY_PREFIX,
        "mode": "DETERMINISTIC_READ_ONLY_GLOBAL_CAUSAL_DAG_FROM_STAGE3_8_2_NORMALIZED_EVENTS",
        "source": "STAGE3_8_2_VERIFIED_NORMALIZED_MISSION_EVENT_LEDGER",
        "persistence_mode": "DERIVED_NO_NEW_DURABLE_STORE", "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "external_causation_reference_mode": "RECORDED_NOT_PROMOTED_TO_AUTHORITY",
        "runtime_side_effects": False,
    }
