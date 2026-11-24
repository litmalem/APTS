from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError

TASK_DECOMPOSITION_SCHEMA_VERSION = "apts-canonical-task-decomposition-v1"
PLANNED_TASK_SCHEMA_VERSION = "apts-canonical-planned-task-v1"
TASK_DECOMPOSITION_HASH_DOMAIN = "MISSION_CANONICAL_TASK_DECOMPOSITION_V1"
PLANNED_TASK_HASH_DOMAIN = "MISSION_CANONICAL_PLANNED_TASK_V1"
TASK_DECOMPOSITION_REQUEST_HASH_DOMAIN = "MISSION_CANONICAL_TASK_DECOMPOSITION_REQUEST_V1"
TASK_DECOMPOSITION_TASK_SET_HASH_DOMAIN = "MISSION_CANONICAL_TASK_SET_V1"
TASK_DECOMPOSITION_ID_PREFIX = "mdecomp-"
PLANNED_TASK_ID_PREFIX = "ptask-"
TASK_DECOMPOSITION_VERSION_INITIAL = 1
TASK_DECOMPOSITION_REQUIRED_STATE = "PLANNING"
TASK_DECOMPOSITION_MODE = "IMMUTABLE_STRUCTURED_TASK_SET_BOUND_TO_EXACT_PLAN_AND_PLANNER_INPUT_SNAPSHOT"
TASK_DECOMPOSITION_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_CANONICAL_TASK_DEFINITION"
TASK_MATERIALIZATION_STATUS = "TASKS_MATERIALIZED"
DEPENDENCY_GRAPH_STATUS_INITIAL = "NOT_MATERIALIZED"
TASK_STATUS_INITIAL = "DEFINED"
MAX_PLANNED_TASKS = 128

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_CAPABILITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/\-]{0,127}$")
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
    "expected_state_version",
    "created_by",
    "reason",
    "tasks",
    "metadata",
}

_TASK_FIELDS = {
    "task_key",
    "task_type",
    "objective",
    "required_capability",
    "required_subsystem",
    "preconditions",
    "expected_outputs",
    "success_criteria",
    "evidence_requirements",
    "priority",
    "metadata",
}

_FORBIDDEN_TASK_FIELDS = {
    "dependencies",
    "depends_on",
    "dependency_edges",
    "tool",
    "tools",
    "tool_calls",
    "authorization",
    "permission",
    "dispatch",
    "dispatch_target",
    "target_action",
    "target_actuation",
    "execution_command",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_task_decomposition_id() -> str:
    return f"{TASK_DECOMPOSITION_ID_PREFIX}{uuid.uuid4()}"


def new_planned_task_id() -> str:
    return f"{PLANNED_TASK_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 2000) -> Optional[str]:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    raw = payload.get(key)
    if isinstance(raw, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(raw)
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


def _json_object(value: Any, key: str, *, allow_empty: bool = True) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    if not allow_empty and not value:
        raise MissionValidationError(f"{key} must not be empty")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def _json_object_list(value: Any, key: str, *, require_non_empty: bool = False) -> list[Dict[str, Any]]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise MissionValidationError(f"{key} must be an array")
    if require_non_empty and not value:
        raise MissionValidationError(f"{key} must contain at least one item")
    out: list[Dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not item:
            raise MissionValidationError(f"{key}[{index}] must be a non-empty JSON object")
        try:
            canonical_json(item)
        except (TypeError, ValueError) as exc:
            raise MissionValidationError(f"{key}[{index}] must contain JSON-serializable values") from exc
        out.append(dict(item))
    return out


def normalize_planned_task_spec(payload: Any, *, index: int) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError(f"tasks[{index}] must be a JSON object")

    forbidden = sorted(set(payload) & _FORBIDDEN_TASK_FIELDS)
    if forbidden:
        raise MissionValidationError(
            f"tasks[{index}] contains Stage-3.3.4-or-later field(s): "
            + ", ".join(forbidden)
            + "; dependency graph, tools, authorization, and dispatch are not part of Stage 3.3.3"
        )
    unknown = sorted(set(payload) - _TASK_FIELDS)
    if unknown:
        raise MissionValidationError(
            f"unsupported tasks[{index}] field(s): " + ", ".join(unknown) + "; put annotations under metadata"
        )

    task_key = _require_string(payload, "task_key")
    if not _ID_RE.match(task_key):
        raise MissionValidationError(f"tasks[{index}].task_key contains unsupported characters")

    task_type = _require_string(payload, "task_type", 96).upper()
    if not _ID_RE.match(task_type):
        raise MissionValidationError(f"tasks[{index}].task_type contains unsupported characters")

    required_capability = _require_string(payload, "required_capability")
    if not _CAPABILITY_RE.match(required_capability):
        raise MissionValidationError(f"tasks[{index}].required_capability contains unsupported characters")

    required_subsystem = _require_string(payload, "required_subsystem", 64).upper()
    if not _ID_RE.match(required_subsystem):
        raise MissionValidationError(f"tasks[{index}].required_subsystem contains unsupported characters")

    raw_priority = payload.get("priority", 50)
    if isinstance(raw_priority, bool):
        raise MissionValidationError(f"tasks[{index}].priority must be an integer")
    try:
        priority = int(raw_priority)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"tasks[{index}].priority must be an integer") from exc
    if priority < 1 or priority > 100:
        raise MissionValidationError(f"tasks[{index}].priority must be between 1 and 100")

    return {
        "task_key": task_key,
        "task_type": task_type,
        "objective": _json_object(payload.get("objective"), f"tasks[{index}].objective", allow_empty=False),
        "required_capability": required_capability,
        "required_subsystem": required_subsystem,
        "preconditions": _json_object_list(payload.get("preconditions"), f"tasks[{index}].preconditions"),
        "expected_outputs": _json_object_list(
            payload.get("expected_outputs"), f"tasks[{index}].expected_outputs", require_non_empty=True
        ),
        "success_criteria": _json_object_list(
            payload.get("success_criteria"), f"tasks[{index}].success_criteria", require_non_empty=True
        ),
        "evidence_requirements": _json_object_list(
            payload.get("evidence_requirements"), f"tasks[{index}].evidence_requirements"
        ),
        "priority": priority,
        "metadata": _json_object(payload.get("metadata", {}), f"tasks[{index}].metadata"),
    }


def normalize_task_decomposition_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task-decomposition request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task-decomposition field(s): "
            + ", ".join(unknown)
            + "; Stage 3.3.3 accepts structured tasks only and does not accept dependencies, planner output, tools, authorization, or dispatch"
        )

    idempotency_key = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")

    expected_plan_id = _require_string(payload, "expected_plan_id")
    if not expected_plan_id.startswith("mplan-") or not _ID_RE.match(expected_plan_id):
        raise MissionValidationError("expected_plan_id must be a canonical mplan-* identifier")

    expected_snapshot_id = _require_string(payload, "expected_snapshot_id")
    if not expected_snapshot_id.startswith("mpis-") or not _ID_RE.match(expected_snapshot_id):
        raise MissionValidationError("expected_snapshot_id must be a canonical mpis-* identifier")

    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise MissionValidationError("tasks is required and must contain at least one planned task")
    if len(raw_tasks) > MAX_PLANNED_TASKS:
        raise MissionValidationError(f"tasks exceeds maximum of {MAX_PLANNED_TASKS} items")
    tasks = [normalize_planned_task_spec(item, index=index) for index, item in enumerate(raw_tasks)]
    keys = [item["task_key"] for item in tasks]
    if len(set(keys)) != len(keys):
        raise MissionValidationError("tasks.task_key values must be unique within one decomposition")

    metadata = _json_object(payload.get("metadata", {}), "metadata")

    return {
        "idempotency_key": idempotency_key,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_plan_id": expected_plan_id,
        "expected_plan_version": _positive_int(payload, "expected_plan_version"),
        "expected_plan_sha256": _sha(payload, "expected_plan_sha256"),
        "expected_snapshot_id": expected_snapshot_id,
        "expected_snapshot_version": _positive_int(payload, "expected_snapshot_version"),
        "expected_snapshot_sha256": _sha(payload, "expected_snapshot_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "created_by": _require_string(payload, "created_by"),
        "reason": _optional_string(payload.get("reason"), "reason"),
        "tasks": tasks,
        "metadata": metadata,
    }


def task_decomposition_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_DECOMPOSITION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_planned_task_contract(
    *,
    mission_id: str,
    decomposition_id: str,
    decomposition_version: int,
    plan_id: str,
    plan_version: int,
    snapshot_id: str,
    snapshot_version: int,
    snapshot_sha256: str,
    planned_task_id: str,
    task_index: int,
    task_spec: Mapping[str, Any],
    request_sha256: str,
    created_by: str,
    created_at: str,
) -> Dict[str, Any]:
    core: Dict[str, Any] = {
        "schema_version": PLANNED_TASK_SCHEMA_VERSION,
        "identity": {
            "planned_task_id": planned_task_id,
            "task_key": task_spec["task_key"],
            "task_index": int(task_index),
            "mission_id": mission_id,
            "decomposition_id": decomposition_id,
            "decomposition_version": int(decomposition_version),
            "plan_id": plan_id,
            "plan_version": int(plan_version),
            "created_by": created_by,
            "created_at": created_at,
        },
        "planner_input_binding": {
            "snapshot_id": snapshot_id,
            "snapshot_version": int(snapshot_version),
            "snapshot_sha256": snapshot_sha256,
        },
        "specification": {
            "task_type": task_spec["task_type"],
            "objective": dict(task_spec["objective"]),
            "required_capability": task_spec["required_capability"],
            "required_subsystem": task_spec["required_subsystem"],
            "preconditions": [dict(x) for x in task_spec["preconditions"]],
            "expected_outputs": [dict(x) for x in task_spec["expected_outputs"]],
            "success_criteria": [dict(x) for x in task_spec["success_criteria"]],
            "evidence_requirements": [dict(x) for x in task_spec["evidence_requirements"]],
            "priority": int(task_spec["priority"]),
        },
        "dependency_binding": {
            "status": DEPENDENCY_GRAPH_STATUS_INITIAL,
            "dependencies": [],
            "dependency_edge_count": 0,
            "structural_validation_performed": False,
        },
        "semantics": {
            "task_status": TASK_STATUS_INITIAL,
            "contract_role": "PLANNED_WORK_UNIT",
            "task_authority": TASK_DECOMPOSITION_AUTHORITY,
            "planner_invocation_performed": False,
            "task_decomposition_performed": True,
            "dependency_graph_materialized": False,
            "dependency_validation_performed": False,
            "task_is_dispatch": False,
            "task_is_authorization": False,
            "readiness_is_permission": False,
            "planner_is_governance": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authorization_query_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "provenance": {
            "decomposition_request_sha256": request_sha256,
            "task_metadata": dict(task_spec.get("metadata") or {}),
        },
    }
    digest = sha256_hex({"hash_domain": PLANNED_TASK_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": PLANNED_TASK_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def _task_set_sha256(tasks: list[Mapping[str, Any]]) -> str:
    projection = [
        {
            "planned_task_id": task["identity"]["planned_task_id"],
            "task_key": task["identity"]["task_key"],
            "task_index": int(task["identity"]["task_index"]),
            "canonical_sha256": task["integrity"]["canonical_sha256"],
        }
        for task in tasks
    ]
    return sha256_hex({"hash_domain": TASK_DECOMPOSITION_TASK_SET_HASH_DOMAIN, "tasks": projection})


def build_task_decomposition_contract(
    *,
    mission_id: str,
    decomposition_id: str,
    decomposition_version: int,
    request_sha256: str,
    version_sha256: str,
    state: Mapping[str, Any],
    plan_record: Mapping[str, Any],
    snapshot_record: Mapping[str, Any],
    task_specs: list[Mapping[str, Any]],
    planned_task_ids: list[str],
    created_by: str,
    reason: Optional[str],
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    if len(task_specs) != len(planned_task_ids):
        raise ValueError("task spec/id cardinality mismatch")

    snapshot = snapshot_record["snapshot"]
    plan = plan_record["plan_contract"]
    tasks = [
        build_planned_task_contract(
            mission_id=mission_id,
            decomposition_id=decomposition_id,
            decomposition_version=decomposition_version,
            plan_id=plan_record["plan_id"],
            plan_version=int(plan_record["plan_version"]),
            snapshot_id=snapshot_record["snapshot_id"],
            snapshot_version=int(snapshot_record["snapshot_version"]),
            snapshot_sha256=snapshot_record["canonical_sha256"],
            planned_task_id=planned_task_ids[index],
            task_index=index + 1,
            task_spec=task_spec,
            request_sha256=request_sha256,
            created_by=created_by,
            created_at=created_at,
        )
        for index, task_spec in enumerate(task_specs)
    ]
    task_set_sha256 = _task_set_sha256(tasks)

    core: Dict[str, Any] = {
        "schema_version": TASK_DECOMPOSITION_SCHEMA_VERSION,
        "identity": {
            "decomposition_id": decomposition_id,
            "decomposition_version": int(decomposition_version),
            "mission_id": mission_id,
            "plan_id": plan_record["plan_id"],
            "plan_version": int(plan_record["plan_version"]),
            "snapshot_id": snapshot_record["snapshot_id"],
            "snapshot_version": int(snapshot_record["snapshot_version"]),
            "created_by": created_by,
            "created_at": created_at,
        },
        "source_bindings": {
            "expected_version_sha256": version_sha256,
            "state": state["state"],
            "state_version": int(state["state_version"]),
            "plan_sha256": plan_record["canonical_sha256"],
            "plan_status": plan["semantics"]["plan_status"],
            "snapshot_sha256": snapshot_record["canonical_sha256"],
            "snapshot_context_sha256": snapshot["context_binding"]["source_context_sha256"],
            "mission_envelope_sha256": snapshot["mission_context"]["envelope_sha256"],
            "scope_snapshot_id": snapshot["scope_context"]["scope_snapshot_id"],
            "scope_sha256": snapshot["scope_context"]["scope_sha256"],
            "governance_binding_snapshot_id": snapshot["governance_context"]["binding_snapshot_id"],
            "governance_binding_sha256": snapshot["governance_context"]["binding_sha256"],
            "pip_id": snapshot["knowledge_context"]["pip_id"],
            "pip_version": snapshot["knowledge_context"]["pip_version"],
        },
        "task_set": {
            "materialization_status": TASK_MATERIALIZATION_STATUS,
            "dependency_graph_status": DEPENDENCY_GRAPH_STATUS_INITIAL,
            "task_count": len(tasks),
            "dependency_edge_count": 0,
            "task_set_sha256": task_set_sha256,
            "tasks": tasks,
            "dependency_edges": [],
        },
        "semantics": {
            "decomposition_mode": TASK_DECOMPOSITION_MODE,
            "decomposition_authority": TASK_DECOMPOSITION_AUTHORITY,
            "immutable_decomposition": True,
            "structured_task_contracts_materialized": True,
            "planner_input_snapshot_required": True,
            "planner_invocation_performed": False,
            "planner_output_consumed": False,
            "task_decomposition_performed": True,
            "dependency_graph_materialized": False,
            "dependency_validation_performed": False,
            "plan_revision_performed": False,
            "plan_contract_mutated": False,
            "decomposition_is_authorization": False,
            "task_is_authorization": False,
            "task_is_dispatch": False,
            "readiness_is_permission": False,
            "planner_is_governance": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authorization_query_performed": False,
            "external_context_refresh_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": TASK_DECOMPOSITION_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": TASK_DECOMPOSITION_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_planned_task_contract(task: Mapping[str, Any]) -> bool:
    try:
        integrity = task["integrity"]
        core = {k: v for k, v in task.items() if k != "integrity"}
        identity = task["identity"]
        binding = task["planner_input_binding"]
        dependency = task["dependency_binding"]
        semantics = task["semantics"]
        return (
            task.get("schema_version") == PLANNED_TASK_SCHEMA_VERSION
            and integrity.get("hash_domain") == PLANNED_TASK_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": PLANNED_TASK_HASH_DOMAIN, "core": core})
            and str(identity.get("planned_task_id") or "").startswith(PLANNED_TASK_ID_PREFIX)
            and int(identity.get("task_index")) >= 1
            and int(identity.get("decomposition_version")) >= 1
            and int(identity.get("plan_version")) >= 1
            and int(binding.get("snapshot_version")) >= 1
            and bool(_SHA256_RE.match(str(binding.get("snapshot_sha256") or "")))
            and dependency.get("status") == DEPENDENCY_GRAPH_STATUS_INITIAL
            and dependency.get("dependencies") == []
            and int(dependency.get("dependency_edge_count")) == 0
            and dependency.get("structural_validation_performed") is False
            and semantics.get("task_status") == TASK_STATUS_INITIAL
            and semantics.get("planner_invocation_performed") is False
            and semantics.get("task_decomposition_performed") is True
            and semantics.get("dependency_graph_materialized") is False
            and semantics.get("task_is_dispatch") is False
            and semantics.get("task_is_authorization") is False
            and semantics.get("governance_authorization_query_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
        )
    except Exception:
        return False


def verify_task_decomposition_contract(contract: Mapping[str, Any]) -> bool:
    try:
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        task_set = contract["task_set"]
        semantics = contract["semantics"]
        tasks = task_set["tasks"]
        task_ids = [task["identity"]["planned_task_id"] for task in tasks]
        task_keys = [task["identity"]["task_key"] for task in tasks]
        indices = [int(task["identity"]["task_index"]) for task in tasks]
        return (
            contract.get("schema_version") == TASK_DECOMPOSITION_SCHEMA_VERSION
            and integrity.get("hash_domain") == TASK_DECOMPOSITION_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": TASK_DECOMPOSITION_HASH_DOMAIN, "core": core})
            and str(identity.get("decomposition_id") or "").startswith(TASK_DECOMPOSITION_ID_PREFIX)
            and int(identity.get("decomposition_version")) == TASK_DECOMPOSITION_VERSION_INITIAL
            and int(identity.get("plan_version")) >= 1
            and int(identity.get("snapshot_version")) >= 1
            and source.get("state") == TASK_DECOMPOSITION_REQUIRED_STATE
            and bool(_SHA256_RE.match(str(source.get("plan_sha256") or "")))
            and bool(_SHA256_RE.match(str(source.get("snapshot_sha256") or "")))
            and bool(_SHA256_RE.match(str(source.get("expected_version_sha256") or "")))
            and task_set.get("materialization_status") == TASK_MATERIALIZATION_STATUS
            and task_set.get("dependency_graph_status") == DEPENDENCY_GRAPH_STATUS_INITIAL
            and int(task_set.get("task_count")) == len(tasks)
            and len(tasks) >= 1
            and int(task_set.get("dependency_edge_count")) == 0
            and task_set.get("dependency_edges") == []
            and task_set.get("task_set_sha256") == _task_set_sha256(tasks)
            and len(set(task_ids)) == len(task_ids)
            and len(set(task_keys)) == len(task_keys)
            and indices == list(range(1, len(tasks) + 1))
            and all(verify_planned_task_contract(task) for task in tasks)
            and all(task["identity"]["mission_id"] == identity["mission_id"] for task in tasks)
            and all(task["identity"]["decomposition_id"] == identity["decomposition_id"] for task in tasks)
            and all(task["identity"]["plan_id"] == identity["plan_id"] for task in tasks)
            and all(task["planner_input_binding"]["snapshot_id"] == identity["snapshot_id"] for task in tasks)
            and semantics.get("structured_task_contracts_materialized") is True
            and semantics.get("planner_invocation_performed") is False
            and semantics.get("planner_output_consumed") is False
            and semantics.get("task_decomposition_performed") is True
            and semantics.get("dependency_graph_materialized") is False
            and semantics.get("dependency_validation_performed") is False
            and semantics.get("plan_revision_performed") is False
            and semantics.get("plan_contract_mutated") is False
            and semantics.get("decomposition_is_authorization") is False
            and semantics.get("task_is_authorization") is False
            and semantics.get("task_is_dispatch") is False
            and semantics.get("readiness_is_permission") is False
            and semantics.get("planner_is_governance") is False
            and semantics.get("governance_authorization_query_performed") is False
            and semantics.get("external_context_refresh_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
        )
    except Exception:
        return False


def canonical_task_decomposition_definition() -> Dict[str, Any]:
    return {
        "schema_version": TASK_DECOMPOSITION_SCHEMA_VERSION,
        "planned_task_schema_version": PLANNED_TASK_SCHEMA_VERSION,
        "mode": TASK_DECOMPOSITION_MODE,
        "decomposition_identity_prefix": TASK_DECOMPOSITION_ID_PREFIX,
        "planned_task_identity_prefix": PLANNED_TASK_ID_PREFIX,
        "initial_decomposition_version": TASK_DECOMPOSITION_VERSION_INITIAL,
        "creation_state_required": TASK_DECOMPOSITION_REQUIRED_STATE,
        "max_planned_tasks": MAX_PLANNED_TASKS,
        "requires_stage3_3_1_plan_contract": True,
        "requires_stage3_3_2_planner_input_snapshot": True,
        "requires_exact_current_version_sha256": True,
        "requires_exact_plan_id_version_sha256": True,
        "requires_exact_snapshot_id_version_sha256": True,
        "requires_exact_state_version": True,
        "requires_snapshot_context_head_consistency": True,
        "task_required_fields": [
            "task_key",
            "task_type",
            "objective",
            "required_capability",
            "required_subsystem",
            "expected_outputs",
            "success_criteria",
        ],
        "task_optional_fields": ["preconditions", "evidence_requirements", "priority", "metadata"],
        "dependency_fields_allowed": False,
        "dependency_graph_materialized": False,
        "dependency_validation_performed": False,
        "planner_invocation_performed": False,
        "planner_output_consumed": False,
        "task_decomposition_performed": True,
        "plan_revision_performed": False,
        "plan_contract_mutated": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "governance_authorization_query_performed": False,
        "decomposition_is_authorization": False,
        "task_is_authorization": False,
        "task_is_dispatch": False,
        "readiness_is_permission": False,
        "planner_is_governance": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
