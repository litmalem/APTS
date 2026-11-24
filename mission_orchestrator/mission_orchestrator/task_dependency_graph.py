from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from heapq import heappop, heappush
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionTaskDependencyGraphGuardRejected, MissionValidationError

TASK_DEPENDENCY_GRAPH_SCHEMA_VERSION = "apts-canonical-task-dependency-graph-v1"
TASK_DEPENDENCY_EDGE_SCHEMA_VERSION = "apts-canonical-task-dependency-edge-v1"
TASK_DEPENDENCY_GRAPH_HASH_DOMAIN = "MISSION_CANONICAL_TASK_DEPENDENCY_GRAPH_V1"
TASK_DEPENDENCY_EDGE_HASH_DOMAIN = "MISSION_CANONICAL_TASK_DEPENDENCY_EDGE_V1"
TASK_DEPENDENCY_GRAPH_REQUEST_HASH_DOMAIN = "MISSION_CANONICAL_TASK_DEPENDENCY_GRAPH_REQUEST_V1"
TASK_DEPENDENCY_NODE_SET_HASH_DOMAIN = "MISSION_CANONICAL_TASK_DEPENDENCY_NODE_SET_V1"
TASK_DEPENDENCY_EDGE_SET_HASH_DOMAIN = "MISSION_CANONICAL_TASK_DEPENDENCY_EDGE_SET_V1"
TASK_DEPENDENCY_GRAPH_ID_PREFIX = "mgraph-"
TASK_DEPENDENCY_EDGE_ID_PREFIX = "medge-"
TASK_DEPENDENCY_GRAPH_VERSION_INITIAL = 1
TASK_DEPENDENCY_GRAPH_REQUIRED_STATE = "PLANNING"
TASK_DEPENDENCY_GRAPH_MODE = "IMMUTABLE_COMPLETE_DAG_BOUND_TO_EXACT_CANONICAL_TASK_DECOMPOSITION"
TASK_DEPENDENCY_GRAPH_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_CANONICAL_TASK_GRAPH_DEFINITION"
TASK_DEPENDENCY_GRAPH_STATUS = "STRUCTURALLY_VALIDATED"
TASK_DEPENDENCY_VALIDATION_MODE = "DETERMINISTIC_COMPLETE_DAG_FAIL_CLOSED"
MAX_DEPENDENCY_EDGES = 8128  # n*(n-1)/2 for the Stage-3.3.3 maximum n=128.

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_plan_id",
    "expected_plan_version",
    "expected_plan_sha256",
    "expected_snapshot_id",
    "expected_snapshot_version",
    "expected_snapshot_sha256",
    "expected_decomposition_id",
    "expected_decomposition_version",
    "expected_decomposition_sha256",
    "expected_task_set_sha256",
    "expected_state_version",
    "created_by",
    "reason",
    "edges",
    "metadata",
}
_EDGE_FIELDS = {"from_task_key", "to_task_key"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_task_dependency_graph_id() -> str:
    return TASK_DEPENDENCY_GRAPH_ID_PREFIX + str(uuid.uuid4())


def new_task_dependency_edge_id() -> str:
    return TASK_DEPENDENCY_EDGE_ID_PREFIX + str(uuid.uuid4())


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 2000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MissionValidationError(f"{key} must be a string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value or None


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    raw = payload.get(key)
    if isinstance(raw, bool):
        raise MissionValidationError(f"{key} must be an integer >= 1")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must be an integer >= 1") from exc
    if value < 1:
        raise MissionValidationError(f"{key} must be an integer >= 1")
    return value


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _require_string(payload, key, 64).lower()
    if not _SHA256_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def _json_object(value: Any, key: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def normalize_dependency_edge(payload: Any, *, index: int) -> Dict[str, str]:
    if not isinstance(payload, dict):
        raise MissionValidationError(f"edges[{index}] must be a JSON object")
    unknown = sorted(set(payload) - _EDGE_FIELDS)
    if unknown:
        raise MissionValidationError(
            f"unsupported edges[{index}] field(s): " + ", ".join(unknown)
        )
    from_key = _require_string(payload, "from_task_key")
    to_key = _require_string(payload, "to_task_key")
    if not _ID_RE.match(from_key):
        raise MissionValidationError(f"edges[{index}].from_task_key contains unsupported characters")
    if not _ID_RE.match(to_key):
        raise MissionValidationError(f"edges[{index}].to_task_key contains unsupported characters")
    return {"from_task_key": from_key, "to_task_key": to_key}


def normalize_task_dependency_graph_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task-dependency-graph request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task-dependency-graph field(s): "
            + ", ".join(unknown)
            + "; Stage 3.3.4 accepts dependency edges only and does not accept readiness, authorization, dispatch, tools, or execution commands"
        )

    idempotency_key = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")

    expected_plan_id = _require_string(payload, "expected_plan_id")
    expected_snapshot_id = _require_string(payload, "expected_snapshot_id")
    expected_decomposition_id = _require_string(payload, "expected_decomposition_id")
    if not expected_plan_id.startswith("mplan-") or not _ID_RE.match(expected_plan_id):
        raise MissionValidationError("expected_plan_id must be a canonical mplan-* identifier")
    if not expected_snapshot_id.startswith("mpis-") or not _ID_RE.match(expected_snapshot_id):
        raise MissionValidationError("expected_snapshot_id must be a canonical mpis-* identifier")
    if not expected_decomposition_id.startswith("mdecomp-") or not _ID_RE.match(expected_decomposition_id):
        raise MissionValidationError("expected_decomposition_id must be a canonical mdecomp-* identifier")

    raw_edges = payload.get("edges", [])
    if not isinstance(raw_edges, list):
        raise MissionValidationError("edges must be an array")
    if len(raw_edges) > MAX_DEPENDENCY_EDGES:
        raise MissionValidationError(f"edges exceeds maximum of {MAX_DEPENDENCY_EDGES} items")
    edges = [normalize_dependency_edge(item, index=index) for index, item in enumerate(raw_edges)]
    # Canonicalize order so equivalent graph submissions have one request fingerprint.
    edges.sort(key=lambda item: (item["from_task_key"], item["to_task_key"]))

    return {
        "idempotency_key": idempotency_key,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_plan_id": expected_plan_id,
        "expected_plan_version": _positive_int(payload, "expected_plan_version"),
        "expected_plan_sha256": _sha(payload, "expected_plan_sha256"),
        "expected_snapshot_id": expected_snapshot_id,
        "expected_snapshot_version": _positive_int(payload, "expected_snapshot_version"),
        "expected_snapshot_sha256": _sha(payload, "expected_snapshot_sha256"),
        "expected_decomposition_id": expected_decomposition_id,
        "expected_decomposition_version": _positive_int(payload, "expected_decomposition_version"),
        "expected_decomposition_sha256": _sha(payload, "expected_decomposition_sha256"),
        "expected_task_set_sha256": _sha(payload, "expected_task_set_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "created_by": _require_string(payload, "created_by"),
        "reason": _optional_string(payload.get("reason"), "reason"),
        "edges": edges,
        "metadata": _json_object(payload.get("metadata", {}), "metadata"),
    }


def task_dependency_graph_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_DEPENDENCY_GRAPH_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _node_projection(task_records: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    nodes: list[Dict[str, Any]] = []
    for row in sorted(task_records, key=lambda x: (int(x["task_index"]), str(x["planned_task_id"]))):
        nodes.append(
            {
                "planned_task_id": row["planned_task_id"],
                "task_key": row["task_key"],
                "task_index": int(row["task_index"]),
                "task_sha256": row["canonical_sha256"],
                "required_subsystem": row["required_subsystem"],
                "required_capability": row["required_capability"],
            }
        )
    return nodes


def validate_dependency_structure(
    task_records: Sequence[Mapping[str, Any]], edge_specs: Sequence[Mapping[str, str]]
) -> Dict[str, Any]:
    nodes = _node_projection(task_records)
    if not nodes:
        raise MissionTaskDependencyGraphGuardRejected(
            "dependency graph requires at least one canonical Stage-3.3.3 planned task"
        )

    key_to_node = {node["task_key"]: node for node in nodes}
    if len(key_to_node) != len(nodes):
        raise MissionTaskDependencyGraphGuardRejected("planned-task key set is not unique")

    seen: set[tuple[str, str]] = set()
    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    canonical_edges: list[Dict[str, Any]] = []

    for edge in edge_specs:
        from_key = edge["from_task_key"]
        to_key = edge["to_task_key"]
        if from_key not in key_to_node:
            raise MissionTaskDependencyGraphGuardRejected(
                f"dependency edge references unknown from_task_key={from_key}; dangling references fail closed"
            )
        if to_key not in key_to_node:
            raise MissionTaskDependencyGraphGuardRejected(
                f"dependency edge references unknown to_task_key={to_key}; dangling references fail closed"
            )
        if from_key == to_key:
            raise MissionTaskDependencyGraphGuardRejected(
                f"dependency edge {from_key}->{to_key} is a self-dependency"
            )
        pair = (from_key, to_key)
        if pair in seen:
            raise MissionTaskDependencyGraphGuardRejected(
                f"duplicate dependency edge {from_key}->{to_key} is not allowed"
            )
        seen.add(pair)
        adjacency[from_key].append(to_key)
        reverse[to_key].append(from_key)
        canonical_edges.append(
            {
                "from_task_key": from_key,
                "from_planned_task_id": key_to_node[from_key]["planned_task_id"],
                "to_task_key": to_key,
                "to_planned_task_id": key_to_node[to_key]["planned_task_id"],
            }
        )

    index_by_key = {node["task_key"]: int(node["task_index"]) for node in nodes}
    for key in list(adjacency):
        adjacency[key].sort(key=lambda child: (index_by_key[child], child))
    for key in list(reverse):
        reverse[key].sort(key=lambda parent: (index_by_key[parent], parent))
    canonical_edges.sort(
        key=lambda e: (
            index_by_key[e["from_task_key"]],
            index_by_key[e["to_task_key"]],
            e["from_task_key"],
            e["to_task_key"],
        )
    )

    indegree = {key: len(reverse.get(key, [])) for key in key_to_node}
    working = dict(indegree)
    heap: list[tuple[int, str]] = []
    for key, degree in working.items():
        if degree == 0:
            heappush(heap, (index_by_key[key], key))

    topological_keys: list[str] = []
    while heap:
        _, key = heappop(heap)
        topological_keys.append(key)
        for child in adjacency.get(key, []):
            working[child] -= 1
            if working[child] == 0:
                heappush(heap, (index_by_key[child], child))

    if len(topological_keys) != len(nodes):
        cyclic = sorted(
            [key for key, degree in working.items() if degree > 0],
            key=lambda key: (index_by_key[key], key),
        )
        raise MissionTaskDependencyGraphGuardRejected(
            "dependency graph contains a directed cycle involving task(s): " + ", ".join(cyclic)
        )

    roots = [node for node in nodes if indegree[node["task_key"]] == 0]
    leaves = [node for node in nodes if len(adjacency.get(node["task_key"], [])) == 0]
    isolated = [
        node
        for node in nodes
        if indegree[node["task_key"]] == 0 and len(adjacency.get(node["task_key"], [])) == 0
    ]

    dependency_bindings = []
    for node in nodes:
        key = node["task_key"]
        dependency_bindings.append(
            {
                "planned_task_id": node["planned_task_id"],
                "task_key": key,
                "task_index": node["task_index"],
                "dependency_task_keys": list(reverse.get(key, [])),
                "dependent_task_keys": list(adjacency.get(key, [])),
                "in_degree": indegree[key],
                "out_degree": len(adjacency.get(key, [])),
                "root": indegree[key] == 0,
                "leaf": len(adjacency.get(key, [])) == 0,
            }
        )

    return {
        "nodes": nodes,
        "canonical_edges": canonical_edges,
        "dependency_bindings": dependency_bindings,
        "topological_task_keys": topological_keys,
        "topological_planned_task_ids": [key_to_node[key]["planned_task_id"] for key in topological_keys],
        "root_task_keys": [node["task_key"] for node in roots],
        "leaf_task_keys": [node["task_key"] for node in leaves],
        "isolated_task_keys": [node["task_key"] for node in isolated],
        "node_count": len(nodes),
        "edge_count": len(canonical_edges),
    }


def build_task_dependency_edge_contract(
    *,
    dependency_edge_id: str,
    graph_id: str,
    graph_version: int,
    mission_id: str,
    decomposition_id: str,
    decomposition_version: int,
    plan_id: str,
    plan_version: int,
    edge: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    core = {
        "schema_version": TASK_DEPENDENCY_EDGE_SCHEMA_VERSION,
        "identity": {
            "dependency_edge_id": dependency_edge_id,
            "graph_id": graph_id,
            "graph_version": int(graph_version),
            "mission_id": mission_id,
            "decomposition_id": decomposition_id,
            "decomposition_version": int(decomposition_version),
            "plan_id": plan_id,
            "plan_version": int(plan_version),
            "created_at": created_at,
        },
        "dependency": {
            "from_task_key": edge["from_task_key"],
            "from_planned_task_id": edge["from_planned_task_id"],
            "to_task_key": edge["to_task_key"],
            "to_planned_task_id": edge["to_planned_task_id"],
            "semantics": "PREREQUISITE_PRECEDES_DEPENDENT",
        },
    }
    digest = sha256_hex({"hash_domain": TASK_DEPENDENCY_EDGE_HASH_DOMAIN, "edge": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": TASK_DEPENDENCY_EDGE_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def build_task_dependency_graph_contract(
    *,
    mission_id: str,
    graph_id: str,
    graph_version: int,
    request_sha256: str,
    version_sha256: str,
    state: Mapping[str, Any],
    plan_record: Mapping[str, Any],
    snapshot_record: Mapping[str, Any],
    decomposition_record: Mapping[str, Any],
    task_records: Sequence[Mapping[str, Any]],
    edge_specs: Sequence[Mapping[str, str]],
    created_by: str,
    reason: str | None,
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    validated = validate_dependency_structure(task_records, edge_specs)
    edge_contracts = []
    for edge in validated["canonical_edges"]:
        edge_contracts.append(
            build_task_dependency_edge_contract(
                dependency_edge_id=new_task_dependency_edge_id(),
                graph_id=graph_id,
                graph_version=graph_version,
                mission_id=mission_id,
                decomposition_id=decomposition_record["decomposition_id"],
                decomposition_version=int(decomposition_record["decomposition_version"]),
                plan_id=plan_record["plan_id"],
                plan_version=int(plan_record["plan_version"]),
                edge=edge,
                created_at=created_at,
            )
        )

    node_set_sha256 = sha256_hex(
        {"hash_domain": TASK_DEPENDENCY_NODE_SET_HASH_DOMAIN, "nodes": validated["nodes"]}
    )
    edge_set_sha256 = sha256_hex(
        {
            "hash_domain": TASK_DEPENDENCY_EDGE_SET_HASH_DOMAIN,
            "edges": [edge["integrity"]["canonical_sha256"] for edge in edge_contracts],
        }
    )

    core: Dict[str, Any] = {
        "schema_version": TASK_DEPENDENCY_GRAPH_SCHEMA_VERSION,
        "identity": {
            "graph_id": graph_id,
            "graph_version": int(graph_version),
            "mission_id": mission_id,
            "created_by": created_by,
            "created_at": created_at,
        },
        "plan_binding": {
            "plan_id": plan_record["plan_id"],
            "plan_version": int(plan_record["plan_version"]),
            "plan_sha256": plan_record["canonical_sha256"],
        },
        "planner_input_binding": {
            "snapshot_id": snapshot_record["snapshot_id"],
            "snapshot_version": int(snapshot_record["snapshot_version"]),
            "snapshot_sha256": snapshot_record["canonical_sha256"],
        },
        "decomposition_binding": {
            "decomposition_id": decomposition_record["decomposition_id"],
            "decomposition_version": int(decomposition_record["decomposition_version"]),
            "decomposition_sha256": decomposition_record["canonical_sha256"],
            "task_set_sha256": decomposition_record["task_set_sha256"],
            "task_count": int(decomposition_record["task_count"]),
        },
        "lifecycle_binding": {
            "required_state": TASK_DEPENDENCY_GRAPH_REQUIRED_STATE,
            "state": state["state"],
            "state_version": int(state["state_version"]),
            "mission_version_sha256_before_graph": version_sha256,
        },
        "graph": {
            "status": TASK_DEPENDENCY_GRAPH_STATUS,
            "node_count": validated["node_count"],
            "edge_count": validated["edge_count"],
            "node_set_sha256": node_set_sha256,
            "edge_set_sha256": edge_set_sha256,
            "nodes": validated["nodes"],
            "edges": edge_contracts,
            "dependency_bindings": validated["dependency_bindings"],
            "topological_task_keys": validated["topological_task_keys"],
            "topological_planned_task_ids": validated["topological_planned_task_ids"],
            "root_task_keys": validated["root_task_keys"],
            "leaf_task_keys": validated["leaf_task_keys"],
            "isolated_task_keys": validated["isolated_task_keys"],
        },
        "structural_validation": {
            "performed": True,
            "status": "PASS",
            "validation_mode": TASK_DEPENDENCY_VALIDATION_MODE,
            "checks": [
                "NODE_SET_EXACTLY_MATCHES_CANONICAL_DECOMPOSITION",
                "NO_DANGLING_TASK_REFERENCES",
                "NO_SELF_DEPENDENCIES",
                "NO_DUPLICATE_DEPENDENCY_EDGES",
                "DIRECTED_ACYCLIC_GRAPH",
                "TOPOLOGICAL_ORDER_COVERS_ALL_TASKS",
            ],
            "cycle_detected": False,
            "dangling_reference_count": 0,
            "self_dependency_count": 0,
            "duplicate_edge_count": 0,
            "topological_order_complete": True,
        },
        "semantics": {
            "graph_authority": TASK_DEPENDENCY_GRAPH_AUTHORITY,
            "dependency_graph_materialized": True,
            "dependency_validation_performed": True,
            "task_contracts_mutated": False,
            "plan_contract_mutated": False,
            "planner_input_snapshot_mutated": False,
            "decomposition_contract_mutated": False,
            "planner_invocation_performed": False,
            "planner_output_consumed": False,
            "readiness_projection_performed": False,
            "scheduling_performed": False,
            "graph_is_authorization": False,
            "task_is_dispatch": False,
            "readiness_is_permission": False,
            "planner_is_governance": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authorization_query_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "provenance": {
            "graph_request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": TASK_DEPENDENCY_GRAPH_HASH_DOMAIN, "graph": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": TASK_DEPENDENCY_GRAPH_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_task_dependency_edge_contract(edge: Mapping[str, Any]) -> bool:
    try:
        integrity = edge["integrity"]
        core = {k: v for k, v in edge.items() if k != "integrity"}
        identity = edge["identity"]
        dep = edge["dependency"]
        return (
            edge.get("schema_version") == TASK_DEPENDENCY_EDGE_SCHEMA_VERSION
            and str(identity.get("dependency_edge_id", "")).startswith(TASK_DEPENDENCY_EDGE_ID_PREFIX)
            and str(identity.get("graph_id", "")).startswith(TASK_DEPENDENCY_GRAPH_ID_PREFIX)
            and dep.get("semantics") == "PREREQUISITE_PRECEDES_DEPENDENT"
            and dep.get("from_task_key") != dep.get("to_task_key")
            and integrity.get("hash_domain") == TASK_DEPENDENCY_EDGE_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": TASK_DEPENDENCY_EDGE_HASH_DOMAIN, "edge": core})
        )
    except Exception:
        return False


def verify_task_dependency_graph_contract(graph: Mapping[str, Any]) -> bool:
    try:
        integrity = graph["integrity"]
        core = {k: v for k, v in graph.items() if k != "integrity"}
        identity = graph["identity"]
        body = graph["graph"]
        validation = graph["structural_validation"]
        semantics = graph["semantics"]
        nodes = body["nodes"]
        edges = body["edges"]
        keys = [node["task_key"] for node in nodes]
        ids = [node["planned_task_id"] for node in nodes]
        edge_pairs = [(e["dependency"]["from_task_key"], e["dependency"]["to_task_key"]) for e in edges]
        topo = list(body.get("topological_task_keys") or [])
        topo_position = {key: index for index, key in enumerate(topo)}
        topological_edges_valid = (
            len(topo) == len(keys)
            and len(topo_position) == len(keys)
            and set(topo) == set(keys)
            and all(
                from_key in topo_position
                and to_key in topo_position
                and topo_position[from_key] < topo_position[to_key]
                for from_key, to_key in edge_pairs
            )
        )
        return (
            graph.get("schema_version") == TASK_DEPENDENCY_GRAPH_SCHEMA_VERSION
            and str(identity.get("graph_id", "")).startswith(TASK_DEPENDENCY_GRAPH_ID_PREFIX)
            and int(identity.get("graph_version", 0)) == TASK_DEPENDENCY_GRAPH_VERSION_INITIAL
            and graph["lifecycle_binding"].get("state") == TASK_DEPENDENCY_GRAPH_REQUIRED_STATE
            and body.get("status") == TASK_DEPENDENCY_GRAPH_STATUS
            and int(body.get("node_count", -1)) == len(nodes)
            and int(body.get("edge_count", -1)) == len(edges)
            and len(set(keys)) == len(keys)
            and len(set(ids)) == len(ids)
            and len(set(edge_pairs)) == len(edge_pairs)
            and all(verify_task_dependency_edge_contract(edge) for edge in edges)
            and body.get("node_set_sha256")
            == sha256_hex({"hash_domain": TASK_DEPENDENCY_NODE_SET_HASH_DOMAIN, "nodes": nodes})
            and body.get("edge_set_sha256")
            == sha256_hex(
                {
                    "hash_domain": TASK_DEPENDENCY_EDGE_SET_HASH_DOMAIN,
                    "edges": [edge["integrity"]["canonical_sha256"] for edge in edges],
                }
            )
            and topological_edges_valid
            and validation.get("performed") is True
            and validation.get("status") == "PASS"
            and validation.get("validation_mode") == TASK_DEPENDENCY_VALIDATION_MODE
            and validation.get("cycle_detected") is False
            and validation.get("topological_order_complete") is True
            and semantics.get("dependency_graph_materialized") is True
            and semantics.get("dependency_validation_performed") is True
            and semantics.get("task_contracts_mutated") is False
            and semantics.get("planner_invocation_performed") is False
            and semantics.get("readiness_projection_performed") is False
            and semantics.get("governance_authorization_query_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
            and integrity.get("hash_domain") == TASK_DEPENDENCY_GRAPH_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": TASK_DEPENDENCY_GRAPH_HASH_DOMAIN, "graph": core})
        )
    except Exception:
        return False


def canonical_task_dependency_graph_definition() -> Dict[str, Any]:
    return {
        "schema_version": TASK_DEPENDENCY_GRAPH_SCHEMA_VERSION,
        "edge_schema_version": TASK_DEPENDENCY_EDGE_SCHEMA_VERSION,
        "graph_identity_prefix": TASK_DEPENDENCY_GRAPH_ID_PREFIX,
        "edge_identity_prefix": TASK_DEPENDENCY_EDGE_ID_PREFIX,
        "initial_graph_version": TASK_DEPENDENCY_GRAPH_VERSION_INITIAL,
        "creation_state_required": TASK_DEPENDENCY_GRAPH_REQUIRED_STATE,
        "mode": TASK_DEPENDENCY_GRAPH_MODE,
        "structural_validation_mode": TASK_DEPENDENCY_VALIDATION_MODE,
        "graph_status_after_registration": TASK_DEPENDENCY_GRAPH_STATUS,
        "max_dependency_edges": MAX_DEPENDENCY_EDGES,
        "edge_semantics": "from_task_key is a prerequisite of to_task_key",
        "all_canonical_planned_tasks_are_materialized_as_graph_nodes": True,
        "isolated_tasks_allowed": True,
        "required_structural_checks": [
            "EXACT_CANONICAL_NODE_SET",
            "DANGLING_REFERENCE_REJECTION",
            "SELF_DEPENDENCY_REJECTION",
            "DUPLICATE_EDGE_REJECTION",
            "DIRECTED_CYCLE_REJECTION",
            "COMPLETE_DETERMINISTIC_TOPOLOGICAL_ORDER",
        ],
        "requires_stage3_3_1_plan_contract": True,
        "requires_stage3_3_2_planner_input_snapshot": True,
        "requires_stage3_3_3_task_decomposition": True,
        "requires_exact_version_sha256": True,
        "requires_exact_plan_identity_version_hash": True,
        "requires_exact_snapshot_identity_version_hash": True,
        "requires_exact_decomposition_identity_version_hash": True,
        "requires_exact_task_set_sha256": True,
        "requires_exact_state_version": True,
        "requires_snapshot_context_head_consistency": True,
        "planner_invocation_performed": False,
        "planner_output_consumed": False,
        "dependency_graph_materialized": True,
        "dependency_validation_performed": True,
        "readiness_projection_performed": False,
        "scheduling_performed": False,
        "task_contracts_mutated": False,
        "plan_contract_mutated": False,
        "decomposition_contract_mutated": False,
        "governance_authorization_query_performed": False,
        "graph_is_authorization": False,
        "task_is_dispatch": False,
        "readiness_is_permission": False,
        "planner_is_governance": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
