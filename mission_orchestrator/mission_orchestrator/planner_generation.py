from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError

PLANNER_INVOCATION_SCHEMA_VERSION = "apts-planner-invocation-v1"
GENERATED_PLAN_SCHEMA_VERSION = "apts-generated-mission-plan-v1"
PLANNER_GENERATION_REQUEST_HASH_DOMAIN = "MISSION_PLANNER_GENERATION_REQUEST_V1"
PLANNER_OUTPUT_HASH_DOMAIN = "MISSION_PLANNER_OUTPUT_V1"
PLANNER_INVOCATION_HASH_DOMAIN = "MISSION_PLANNER_INVOCATION_V1"
GENERATED_PLAN_HASH_DOMAIN = "MISSION_GENERATED_PLAN_V1"
PLANNER_INVOCATION_ID_PREFIX = "pinvoke-"
GENERATED_PLAN_ID_PREFIX = "pgen-"
PLANNER_GENERATION_VERSION_INITIAL = 1
PLANNER_GENERATION_REQUIRED_STATE = "PLANNING"
PLANNER_PROFILE_CANONICAL_DAG_V1 = "CANONICAL_DAG_STRUCTURAL_PLANNER_V1"
SUPPORTED_PLANNER_PROFILES = frozenset({PLANNER_PROFILE_CANONICAL_DAG_V1})
PLANNER_ENGINE = "APTS_MO_LOCAL_DETERMINISTIC_GRAPH_PLANNER"
PLANNER_ENGINE_VERSION = "1"
PLANNER_INVOCATION_MODE = "LOCAL_DETERMINISTIC_PURE_FUNCTION_OVER_CANONICAL_STAGE3_3_ARTIFACTS"
GENERATED_PLAN_STATUS = "GENERATED_UNVALIDATED"
PLANNER_GENERATION_MODE = "INVOKE_LOCAL_PLANNER_AND_MATERIALIZE_IMMUTABLE_CANDIDATE_PLAN"
PLANNING_STRATEGY = "DEPENDENCY_LAYERED_TOPOLOGICAL_V1"

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
    "expected_graph_id",
    "expected_graph_version",
    "expected_graph_sha256",
    "expected_node_set_sha256",
    "expected_edge_set_sha256",
    "expected_state_version",
    "planner_profile",
    "created_by",
    "reason",
    "metadata",
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_planner_invocation_id() -> str:
    return f"{PLANNER_INVOCATION_ID_PREFIX}{uuid.uuid4()}"


def new_generated_plan_id() -> str:
    return f"{GENERATED_PLAN_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 2000) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return value


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _require_string(payload, key, 64).lower()
    if not _SHA256_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_planner_generation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("planner invocation request body must be a JSON object")

    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported planner invocation field(s): "
            + ", ".join(unknown)
            + "; Stage 3.3.5 invokes the configured planner itself and does not accept caller-supplied tasks, "
            "dependencies, planner output, prompts/models/providers, readiness, schedules, authorization, dispatch, tools, or execution commands"
        )

    idempotency_key = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")

    planner_profile = _require_string(payload, "planner_profile", 96).upper()
    if planner_profile not in SUPPORTED_PLANNER_PROFILES:
        raise MissionValidationError(
            "unsupported planner_profile; expected one of: " + ", ".join(sorted(SUPPORTED_PLANNER_PROFILES))
        )

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    try:
        canonical_json(metadata)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("metadata must contain JSON-serializable values") from exc

    ids = {}
    for key in ("expected_plan_id", "expected_snapshot_id", "expected_decomposition_id", "expected_graph_id"):
        ids[key] = _require_string(payload, key)
        if not _ID_RE.match(ids[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")

    return {
        "idempotency_key": idempotency_key,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        **ids,
        "expected_plan_version": _positive_int(payload, "expected_plan_version"),
        "expected_plan_sha256": _sha(payload, "expected_plan_sha256"),
        "expected_snapshot_version": _positive_int(payload, "expected_snapshot_version"),
        "expected_snapshot_sha256": _sha(payload, "expected_snapshot_sha256"),
        "expected_decomposition_version": _positive_int(payload, "expected_decomposition_version"),
        "expected_decomposition_sha256": _sha(payload, "expected_decomposition_sha256"),
        "expected_task_set_sha256": _sha(payload, "expected_task_set_sha256"),
        "expected_graph_version": _positive_int(payload, "expected_graph_version"),
        "expected_graph_sha256": _sha(payload, "expected_graph_sha256"),
        "expected_node_set_sha256": _sha(payload, "expected_node_set_sha256"),
        "expected_edge_set_sha256": _sha(payload, "expected_edge_set_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "planner_profile": planner_profile,
        "created_by": _require_string(payload, "created_by"),
        "reason": _optional_string(payload.get("reason"), "reason"),
        "metadata": dict(metadata),
    }


def planner_generation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": PLANNER_GENERATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _task_contract_projection(task_row: Mapping[str, Any]) -> Dict[str, Any]:
    contract = task_row["task_contract"]
    body = contract["specification"]
    identity = contract["identity"]
    return {
        "planned_task_id": identity["planned_task_id"],
        "task_key": identity["task_key"],
        "task_index": int(identity["task_index"]),
        "task_sha256": contract["integrity"]["canonical_sha256"],
        "task_type": body["task_type"],
        "objective": body["objective"],
        "required_capability": body["required_capability"],
        "required_subsystem": body["required_subsystem"],
        "preconditions": body.get("preconditions") or [],
        "expected_outputs": body.get("expected_outputs") or [],
        "success_criteria": body.get("success_criteria") or [],
        "evidence_requirements": body.get("evidence_requirements") or [],
        "priority": int(body.get("priority", 100)),
    }


def generate_planner_output(
    *,
    planner_profile: str,
    snapshot_record: Mapping[str, Any],
    decomposition_record: Mapping[str, Any],
    task_records: Sequence[Mapping[str, Any]],
    graph_record: Mapping[str, Any],
) -> Dict[str, Any]:
    """Pure deterministic Stage-3.3.5 planner.

    This planner intentionally performs *planning only*. It consumes the immutable
    Stage-3.3.2/3.3.3/3.3.4 artifacts and derives a candidate dependency-layered plan.
    It does not query external systems, compute live readiness, create a schedule,
    authorize work, dispatch tasks, or actuate a target.
    """

    if planner_profile != PLANNER_PROFILE_CANONICAL_DAG_V1:
        raise MissionValidationError(f"unsupported planner profile: {planner_profile}")

    graph_contract = graph_record["graph"]
    graph_body = graph_contract["graph"]
    task_by_key = {
        projection["task_key"]: projection
        for projection in (_task_contract_projection(row) for row in task_records)
    }

    topological_keys = list(graph_body["topological_task_keys"])
    if set(topological_keys) != set(task_by_key) or len(topological_keys) != len(task_by_key):
        raise MissionValidationError("canonical graph topological order does not cover the exact planned-task set")

    parents: dict[str, list[str]] = defaultdict(list)
    for edge in graph_body["edges"]:
        dep = edge["dependency"]
        parents[dep["to_task_key"]].append(dep["from_task_key"])

    layer_by_key: dict[str, int] = {}
    for key in topological_keys:
        predecessors = parents.get(key, [])
        layer_by_key[key] = 1 if not predecessors else 1 + max(layer_by_key[parent] for parent in predecessors)

    layers: dict[int, list[str]] = defaultdict(list)
    for key in topological_keys:
        layers[layer_by_key[key]].append(key)

    plan_steps = []
    for ordinal, key in enumerate(topological_keys, start=1):
        task = task_by_key[key]
        plan_steps.append(
            {
                "step_index": ordinal,
                "planning_layer": layer_by_key[key],
                "planned_task_id": task["planned_task_id"],
                "task_key": task["task_key"],
                "task_index": task["task_index"],
                "task_sha256": task["task_sha256"],
                "task_type": task["task_type"],
                "objective": task["objective"],
                "required_capability": task["required_capability"],
                "required_subsystem": task["required_subsystem"],
                "dependency_task_keys": sorted(
                    parents.get(key, []),
                    key=lambda parent: topological_keys.index(parent),
                ),
                "preconditions": task["preconditions"],
                "expected_outputs": task["expected_outputs"],
                "success_criteria": task["success_criteria"],
                "evidence_requirements": task["evidence_requirements"],
                "priority": task["priority"],
            }
        )

    planning_layers = []
    for layer_index in sorted(layers):
        keys = layers[layer_index]
        planning_layers.append(
            {
                "layer_index": layer_index,
                "task_keys": keys,
                "planned_task_ids": [task_by_key[key]["planned_task_id"] for key in keys],
                "task_count": len(keys),
                "parallelism_possible": len(keys) > 1,
            }
        )

    edges = [
        {
            "from_task_key": edge["dependency"]["from_task_key"],
            "from_planned_task_id": edge["dependency"]["from_planned_task_id"],
            "to_task_key": edge["dependency"]["to_task_key"],
            "to_planned_task_id": edge["dependency"]["to_planned_task_id"],
        }
        for edge in graph_body["edges"]
    ]

    output_core = {
        "planner_profile": planner_profile,
        "planner_engine": PLANNER_ENGINE,
        "planner_engine_version": PLANNER_ENGINE_VERSION,
        "planning_strategy": PLANNING_STRATEGY,
        "deterministic": True,
        "source_bindings": {
            "snapshot_id": snapshot_record["snapshot_id"],
            "snapshot_version": int(snapshot_record["snapshot_version"]),
            "snapshot_sha256": snapshot_record["canonical_sha256"],
            "decomposition_id": decomposition_record["decomposition_id"],
            "decomposition_version": int(decomposition_record["decomposition_version"]),
            "decomposition_sha256": decomposition_record["canonical_sha256"],
            "task_set_sha256": decomposition_record["task_set_sha256"],
            "graph_id": graph_record["graph_id"],
            "graph_version": int(graph_record["graph_version"]),
            "graph_sha256": graph_record["canonical_sha256"],
            "node_set_sha256": graph_record["node_set_sha256"],
            "edge_set_sha256": graph_record["edge_set_sha256"],
        },
        "candidate": {
            "status": GENERATED_PLAN_STATUS,
            "task_count": len(plan_steps),
            "dependency_edge_count": len(edges),
            "planning_layer_count": len(planning_layers),
            "ordered_task_keys": topological_keys,
            "ordered_planned_task_ids": [task_by_key[key]["planned_task_id"] for key in topological_keys],
            "planning_layers": planning_layers,
            "plan_steps": plan_steps,
            "dependency_edges": edges,
        },
        "semantics": {
            "planner_invocation_performed": True,
            "planner_output_generated": True,
            "planner_output_consumed_for_candidate_plan": True,
            "candidate_plan_generated": True,
            "feasibility_validation_performed": False,
            "plan_activation_performed": False,
            "readiness_projection_performed": False,
            "scheduling_performed": False,
            "governance_authorization_query_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
    }
    return {
        **output_core,
        "output_sha256": sha256_hex({"hash_domain": PLANNER_OUTPUT_HASH_DOMAIN, "output": output_core}),
    }


def build_planner_invocation_contract(
    *,
    invocation_id: str,
    generation_version: int,
    mission_id: str,
    request_sha256: str,
    version_sha256: str,
    state: Mapping[str, Any],
    plan_record: Mapping[str, Any],
    snapshot_record: Mapping[str, Any],
    decomposition_record: Mapping[str, Any],
    graph_record: Mapping[str, Any],
    planner_profile: str,
    planner_output: Mapping[str, Any],
    created_by: str,
    reason: str | None,
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    core = {
        "schema_version": PLANNER_INVOCATION_SCHEMA_VERSION,
        "identity": {
            "planner_invocation_id": invocation_id,
            "generation_version": int(generation_version),
            "mission_id": mission_id,
            "plan_id": plan_record["plan_id"],
            "plan_version": int(plan_record["plan_version"]),
            "created_by": created_by,
            "created_at": created_at,
        },
        "input_bindings": {
            "source_version_sha256": version_sha256,
            "state": state["state"],
            "state_version": int(state["state_version"]),
            "plan_sha256": plan_record["canonical_sha256"],
            "snapshot_id": snapshot_record["snapshot_id"],
            "snapshot_version": int(snapshot_record["snapshot_version"]),
            "snapshot_sha256": snapshot_record["canonical_sha256"],
            "decomposition_id": decomposition_record["decomposition_id"],
            "decomposition_version": int(decomposition_record["decomposition_version"]),
            "decomposition_sha256": decomposition_record["canonical_sha256"],
            "task_set_sha256": decomposition_record["task_set_sha256"],
            "graph_id": graph_record["graph_id"],
            "graph_version": int(graph_record["graph_version"]),
            "graph_sha256": graph_record["canonical_sha256"],
            "node_set_sha256": graph_record["node_set_sha256"],
            "edge_set_sha256": graph_record["edge_set_sha256"],
        },
        "planner": {
            "planner_profile": planner_profile,
            "planner_engine": PLANNER_ENGINE,
            "planner_engine_version": PLANNER_ENGINE_VERSION,
            "invocation_mode": PLANNER_INVOCATION_MODE,
            "planning_strategy": PLANNING_STRATEGY,
            "deterministic": True,
            "external_model_invocation_performed": False,
            "external_network_io_performed": False,
        },
        "output": {
            "status": "GENERATED",
            "output_sha256": planner_output["output_sha256"],
            "candidate_status": planner_output["candidate"]["status"],
            "task_count": int(planner_output["candidate"]["task_count"]),
            "dependency_edge_count": int(planner_output["candidate"]["dependency_edge_count"]),
            "planning_layer_count": int(planner_output["candidate"]["planning_layer_count"]),
        },
        "semantics": {
            "planner_invocation_performed": True,
            "planner_output_generated": True,
            "planner_output_is_authorization": False,
            "planner_is_governance": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authorization_query_performed": False,
            "readiness_projection_performed": False,
            "scheduling_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": PLANNER_INVOCATION_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": PLANNER_INVOCATION_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def build_generated_plan_contract(
    *,
    generated_plan_id: str,
    generation_version: int,
    mission_id: str,
    invocation_contract: Mapping[str, Any],
    plan_record: Mapping[str, Any],
    snapshot_record: Mapping[str, Any],
    decomposition_record: Mapping[str, Any],
    graph_record: Mapping[str, Any],
    planner_output: Mapping[str, Any],
    created_by: str,
    created_at: str,
) -> Dict[str, Any]:
    core = {
        "schema_version": GENERATED_PLAN_SCHEMA_VERSION,
        "identity": {
            "generated_plan_id": generated_plan_id,
            "generation_version": int(generation_version),
            "mission_id": mission_id,
            "plan_id": plan_record["plan_id"],
            "plan_version": int(plan_record["plan_version"]),
            "planner_invocation_id": invocation_contract["identity"]["planner_invocation_id"],
            "created_by": created_by,
            "created_at": created_at,
        },
        "source_bindings": {
            "planner_invocation_sha256": invocation_contract["integrity"]["canonical_sha256"],
            "planner_output_sha256": planner_output["output_sha256"],
            "snapshot_id": snapshot_record["snapshot_id"],
            "snapshot_version": int(snapshot_record["snapshot_version"]),
            "snapshot_sha256": snapshot_record["canonical_sha256"],
            "decomposition_id": decomposition_record["decomposition_id"],
            "decomposition_version": int(decomposition_record["decomposition_version"]),
            "decomposition_sha256": decomposition_record["canonical_sha256"],
            "task_set_sha256": decomposition_record["task_set_sha256"],
            "graph_id": graph_record["graph_id"],
            "graph_version": int(graph_record["graph_version"]),
            "graph_sha256": graph_record["canonical_sha256"],
            "node_set_sha256": graph_record["node_set_sha256"],
            "edge_set_sha256": graph_record["edge_set_sha256"],
        },
        "planner": {
            "planner_profile": planner_output["planner_profile"],
            "planner_engine": planner_output["planner_engine"],
            "planner_engine_version": planner_output["planner_engine_version"],
            "planning_strategy": planner_output["planning_strategy"],
            "deterministic": True,
        },
        "generated_plan": planner_output["candidate"],
        "semantics": {
            "generated_plan_status": GENERATED_PLAN_STATUS,
            "immutable_candidate_plan": True,
            "canonical_plan_contract_mutated": False,
            "planner_input_snapshot_mutated": False,
            "task_decomposition_mutated": False,
            "task_dependency_graph_mutated": False,
            "planner_invocation_performed": True,
            "planner_output_consumed": True,
            "plan_generation_performed": True,
            "feasibility_validation_performed": False,
            "plan_activation_performed": False,
            "readiness_projection_performed": False,
            "scheduling_performed": False,
            "generated_plan_is_authorization": False,
            "task_is_dispatch": False,
            "readiness_is_permission": False,
            "planner_is_governance": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authorization_query_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
    }
    digest = sha256_hex({"hash_domain": GENERATED_PLAN_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": GENERATED_PLAN_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_planner_invocation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        identity = contract["identity"]
        planner = contract["planner"]
        output = contract["output"]
        semantics = contract["semantics"]
        bindings = contract["input_bindings"]
        return (
            contract.get("schema_version") == PLANNER_INVOCATION_SCHEMA_VERSION
            and integrity.get("hash_domain") == PLANNER_INVOCATION_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": PLANNER_INVOCATION_HASH_DOMAIN, "core": core})
            and str(identity.get("planner_invocation_id") or "").startswith(PLANNER_INVOCATION_ID_PREFIX)
            and int(identity.get("generation_version")) >= 1
            and bindings.get("state") == PLANNER_GENERATION_REQUIRED_STATE
            and bool(_SHA256_RE.match(str(bindings.get("source_version_sha256") or "")))
            and bool(_SHA256_RE.match(str(bindings.get("plan_sha256") or "")))
            and bool(_SHA256_RE.match(str(bindings.get("snapshot_sha256") or "")))
            and bool(_SHA256_RE.match(str(bindings.get("decomposition_sha256") or "")))
            and bool(_SHA256_RE.match(str(bindings.get("task_set_sha256") or "")))
            and bool(_SHA256_RE.match(str(bindings.get("graph_sha256") or "")))
            and bool(_SHA256_RE.match(str(bindings.get("node_set_sha256") or "")))
            and bool(_SHA256_RE.match(str(bindings.get("edge_set_sha256") or "")))
            and planner.get("planner_profile") in SUPPORTED_PLANNER_PROFILES
            and planner.get("planner_engine") == PLANNER_ENGINE
            and planner.get("deterministic") is True
            and planner.get("external_model_invocation_performed") is False
            and planner.get("external_network_io_performed") is False
            and output.get("status") == "GENERATED"
            and output.get("candidate_status") == GENERATED_PLAN_STATUS
            and bool(_SHA256_RE.match(str(output.get("output_sha256") or "")))
            and semantics.get("planner_invocation_performed") is True
            and semantics.get("planner_output_generated") is True
            and semantics.get("planner_output_is_authorization") is False
            and semantics.get("planner_is_governance") is False
            and semantics.get("governance_authorization_query_performed") is False
            and semantics.get("readiness_projection_performed") is False
            and semantics.get("scheduling_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
        )
    except Exception:
        return False


def verify_generated_plan_contract(contract: Mapping[str, Any]) -> bool:
    try:
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        generated = contract["generated_plan"]
        semantics = contract["semantics"]
        steps = generated["plan_steps"]
        keys = generated["ordered_task_keys"]
        ids = generated["ordered_planned_task_ids"]
        layers = generated["planning_layers"]
        return (
            contract.get("schema_version") == GENERATED_PLAN_SCHEMA_VERSION
            and integrity.get("hash_domain") == GENERATED_PLAN_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": GENERATED_PLAN_HASH_DOMAIN, "core": core})
            and str(identity.get("generated_plan_id") or "").startswith(GENERATED_PLAN_ID_PREFIX)
            and str(identity.get("planner_invocation_id") or "").startswith(PLANNER_INVOCATION_ID_PREFIX)
            and int(identity.get("generation_version")) >= 1
            and all(bool(_SHA256_RE.match(str(source.get(field) or ""))) for field in (
                "planner_invocation_sha256", "planner_output_sha256", "snapshot_sha256",
                "decomposition_sha256", "task_set_sha256", "graph_sha256", "node_set_sha256", "edge_set_sha256"
            ))
            and generated.get("status") == GENERATED_PLAN_STATUS
            and int(generated.get("task_count")) == len(steps) == len(keys) == len(ids)
            and int(generated.get("planning_layer_count")) == len(layers)
            and [step["task_key"] for step in steps] == keys
            and [step["planned_task_id"] for step in steps] == ids
            and [int(step["step_index"]) for step in steps] == list(range(1, len(steps) + 1))
            and semantics.get("immutable_candidate_plan") is True
            and semantics.get("canonical_plan_contract_mutated") is False
            and semantics.get("planner_input_snapshot_mutated") is False
            and semantics.get("task_decomposition_mutated") is False
            and semantics.get("task_dependency_graph_mutated") is False
            and semantics.get("planner_invocation_performed") is True
            and semantics.get("planner_output_consumed") is True
            and semantics.get("plan_generation_performed") is True
            and semantics.get("feasibility_validation_performed") is False
            and semantics.get("plan_activation_performed") is False
            and semantics.get("readiness_projection_performed") is False
            and semantics.get("scheduling_performed") is False
            and semantics.get("generated_plan_is_authorization") is False
            and semantics.get("task_is_dispatch") is False
            and semantics.get("readiness_is_permission") is False
            and semantics.get("planner_is_governance") is False
            and semantics.get("governance_authorization_query_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
        )
    except Exception:
        return False


def canonical_planner_generation_definition() -> Dict[str, Any]:
    return {
        "planner_invocation_schema_version": PLANNER_INVOCATION_SCHEMA_VERSION,
        "generated_plan_schema_version": GENERATED_PLAN_SCHEMA_VERSION,
        "mode": PLANNER_GENERATION_MODE,
        "invocation_mode": PLANNER_INVOCATION_MODE,
        "planner_engine": PLANNER_ENGINE,
        "planner_engine_version": PLANNER_ENGINE_VERSION,
        "supported_planner_profiles": sorted(SUPPORTED_PLANNER_PROFILES),
        "default_planner_profile": PLANNER_PROFILE_CANONICAL_DAG_V1,
        "planning_strategy": PLANNING_STRATEGY,
        "planner_invocation_identity_prefix": PLANNER_INVOCATION_ID_PREFIX,
        "generated_plan_identity_prefix": GENERATED_PLAN_ID_PREFIX,
        "initial_generation_version": PLANNER_GENERATION_VERSION_INITIAL,
        "creation_state_required": PLANNER_GENERATION_REQUIRED_STATE,
        "requires_stage3_3_1_plan_contract": True,
        "requires_stage3_3_2_planner_input_snapshot": True,
        "requires_stage3_3_3_task_decomposition": True,
        "requires_stage3_3_4_validated_dependency_graph": True,
        "requires_exact_current_version_sha256": True,
        "requires_exact_state_version": True,
        "requires_exact_plan_snapshot_decomposition_graph_hashes": True,
        "requires_snapshot_context_head_consistency": True,
        "planner_invocation_performed": True,
        "planner_output_generated": True,
        "planner_output_consumed": True,
        "plan_generation_performed": True,
        "generated_plan_status": GENERATED_PLAN_STATUS,
        "generated_plan_is_validated": False,
        "feasibility_validation_performed": False,
        "plan_activation_performed": False,
        "readiness_projection_performed": False,
        "scheduling_performed": False,
        "external_model_invocation_performed": False,
        "external_network_io_performed": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "governance_authorization_query_performed": False,
        "plan_is_authorization": False,
        "task_is_dispatch": False,
        "readiness_is_permission": False,
        "planner_is_governance": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
