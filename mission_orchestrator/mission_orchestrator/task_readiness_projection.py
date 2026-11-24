from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError

TASK_READINESS_PROJECTION_SCHEMA_VERSION = "apts-task-readiness-scheduling-projection-v1"
TASK_READINESS_PROJECTION_HASH_DOMAIN = "MISSION_TASK_READINESS_SCHEDULING_PROJECTION_V1"
TASK_READINESS_PROJECTION_REQUEST_HASH_DOMAIN = "MISSION_TASK_READINESS_SCHEDULING_PROJECTION_REQUEST_V1"
TASK_READINESS_PROJECTION_ID_PREFIX = "rproj-"
TASK_READINESS_PROJECTION_MODE = "IMMUTABLE_ACTIVE_PLAN_STRUCTURAL_READINESS_AND_DEPENDENCY_WAVE_PROJECTION"
TASK_READINESS_PROJECTION_STATES = frozenset({"PLANNING", "REPLANNING"})
TASK_READY = "READY"
TASK_BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
SCHEDULING_PROJECTION_MODE = "DEPENDENCY_LAYER_WAVES_NO_CLOCK_NO_RESOURCE_ASSIGNMENT"

_REQUEST_FIELDS = {
    "idempotency_key", "expected_version_sha256", "expected_state_version",
    "expected_active_plan_version_record_id", "expected_active_plan_version",
    "expected_active_plan_sha256", "created_by", "reason", "metadata",
}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_task_readiness_projection_id() -> str:
    return f"{TASK_READINESS_PROJECTION_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
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


def normalize_task_readiness_projection_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task readiness projection request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task readiness projection field(s): " + ", ".join(unknown)
            + "; Stage 3.3.8 derives structural readiness/scheduling from the active canonical Plan and does not accept caller-supplied task status, completion, authorization, permission, schedule, resource assignment, dispatch, execution, or target action fields"
        )
    idem = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idem):
        raise MissionValidationError("idempotency_key contains unsupported characters")
    plan_record_id = _require_string(payload, "expected_active_plan_version_record_id")
    if not _ID_RE.match(plan_record_id):
        raise MissionValidationError("expected_active_plan_version_record_id contains unsupported characters")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason not in (None, ""):
        if not isinstance(reason, str) or not reason.strip():
            raise MissionValidationError("reason must be a non-empty string when provided")
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    else:
        reason = None
    return {
        "idempotency_key": idem,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version_record_id": plan_record_id,
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "created_by": _require_string(payload, "created_by"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_readiness_projection_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_READINESS_PROJECTION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def derive_structural_readiness(candidate_plan: Mapping[str, Any]) -> Dict[str, Any]:
    steps = list(candidate_plan.get("plan_steps") or [])
    layers = list(candidate_plan.get("planning_layers") or [])
    if not steps:
        raise MissionValidationError("active Plan candidate has no plan_steps")
    by_key = {str(step["task_key"]): step for step in steps}
    if len(by_key) != len(steps):
        raise MissionValidationError("active Plan candidate task keys are not unique")

    task_items = []
    ready_keys = []
    blocked_keys = []
    for step in sorted(steps, key=lambda x: int(x["step_index"])):
        deps = list(step.get("dependency_task_keys") or [])
        status = TASK_READY if not deps else TASK_BLOCKED_DEPENDENCY
        if status == TASK_READY:
            ready_keys.append(step["task_key"])
        else:
            blocked_keys.append(step["task_key"])
        task_items.append({
            "planned_task_id": step["planned_task_id"],
            "task_key": step["task_key"],
            "task_index": int(step["task_index"]),
            "step_index": int(step["step_index"]),
            "planning_layer": int(step["planning_layer"]),
            "required_subsystem": step["required_subsystem"],
            "required_capability": step["required_capability"],
            "dependency_task_keys": deps,
            "unmet_dependency_task_keys": deps,
            "readiness_status": status,
            "structurally_ready": status == TASK_READY,
            "authorization_granted": False,
            "dispatch_performed": False,
        })

    schedule_waves = []
    flattened = []
    for layer in sorted(layers, key=lambda x: int(x["layer_index"])):
        keys = list(layer.get("task_keys") or [])
        for key in keys:
            if key not in by_key:
                raise MissionValidationError("planning layer references unknown task key")
        flattened.extend(keys)
        schedule_waves.append({
            "wave_index": int(layer["layer_index"]),
            "task_keys": keys,
            "planned_task_ids": list(layer.get("planned_task_ids") or []),
            "task_count": int(layer.get("task_count") or len(keys)),
            "parallelism_candidate": len(keys) > 1,
            "clock_time_assigned": False,
            "resource_assignment_performed": False,
            "dispatch_performed": False,
        })
    if set(flattened) != set(by_key) or len(flattened) != len(by_key):
        raise MissionValidationError("planning layers do not cover the exact active Plan task set")

    return {
        "task_readiness": task_items,
        "ready_task_keys": ready_keys,
        "blocked_task_keys": blocked_keys,
        "ready_task_count": len(ready_keys),
        "blocked_task_count": len(blocked_keys),
        "task_count": len(task_items),
        "scheduling_projection": {
            "mode": SCHEDULING_PROJECTION_MODE,
            "wave_count": len(schedule_waves),
            "waves": schedule_waves,
            "structural_order_only": True,
            "wall_clock_schedule_created": False,
            "resource_assignment_performed": False,
            "dispatch_performed": False,
        },
    }


def build_task_readiness_projection_contract(*, projection_id: str, mission_id: str, request_sha256: str,
    source_state: Mapping[str, Any], source_version_sha256: str, active_plan: Mapping[str, Any],
    created_by: str, reason: Optional[str], metadata: Mapping[str, Any], created_at: str) -> Dict[str, Any]:
    plan_contract = active_plan["plan_version_contract"]
    candidate = plan_contract["candidate_plan"]
    derived = derive_structural_readiness(candidate)
    core = {
        "schema_version": TASK_READINESS_PROJECTION_SCHEMA_VERSION,
        "identity": {
            "projection_id": projection_id, "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]), "created_by": created_by, "created_at": created_at,
        },
        "source_bindings": {
            "state": source_state["state"], "state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "candidate_plan_sha256": active_plan["candidate_plan_sha256"],
        },
        "projection": derived,
        "semantics": {
            "mode": TASK_READINESS_PROJECTION_MODE,
            "readiness_projection_performed": True,
            "scheduling_projection_performed": True,
            "scheduling_execution_performed": False,
            "readiness_is_permission": False,
            "ready_is_authorized": False,
            "plan_is_authorization": False,
            "task_is_dispatch": False,
            "planner_is_governance": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authorization_query_performed": False,
            "wall_clock_schedule_created": False,
            "resource_assignment_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "provenance": {"request_sha256": request_sha256, "reason": reason, "metadata": dict(metadata)},
    }
    digest = sha256_hex({"hash_domain": TASK_READINESS_PROJECTION_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "hash_domain": TASK_READINESS_PROJECTION_HASH_DOMAIN,
        "canonicalization": "UTF8_SORTED_JSON_V1", "canonical_sha256": digest}}


def verify_task_readiness_projection_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        projection = contract["projection"]
        semantics = contract["semantics"]
        statuses = {item["readiness_status"] for item in projection["task_readiness"]}
        return (
            contract.get("schema_version") == TASK_READINESS_PROJECTION_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == TASK_READINESS_PROJECTION_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256") == sha256_hex({"hash_domain": TASK_READINESS_PROJECTION_HASH_DOMAIN, "core": core})
            and str(identity.get("projection_id") or "").startswith(TASK_READINESS_PROJECTION_ID_PREFIX)
            and str(identity.get("plan_version_record_id") or "").startswith("pver-")
            and int(identity.get("plan_version")) >= 1
            and source.get("state") in TASK_READINESS_PROJECTION_STATES
            and int(source.get("state_version")) >= 1
            and _SHA256_RE.match(str(source.get("source_version_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("active_plan_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("candidate_plan_sha256") or "")) is not None
            and int(projection.get("task_count")) >= 1
            and int(projection.get("ready_task_count")) >= 1
            and int(projection.get("ready_task_count")) + int(projection.get("blocked_task_count")) == int(projection.get("task_count"))
            and statuses.issubset({TASK_READY, TASK_BLOCKED_DEPENDENCY})
            and projection["scheduling_projection"].get("mode") == SCHEDULING_PROJECTION_MODE
            and projection["scheduling_projection"].get("structural_order_only") is True
            and projection["scheduling_projection"].get("wall_clock_schedule_created") is False
            and projection["scheduling_projection"].get("resource_assignment_performed") is False
            and projection["scheduling_projection"].get("dispatch_performed") is False
            and semantics.get("readiness_projection_performed") is True
            and semantics.get("scheduling_projection_performed") is True
            and semantics.get("scheduling_execution_performed") is False
            and semantics.get("readiness_is_permission") is False
            and semantics.get("ready_is_authorized") is False
            and semantics.get("governance_authorization_authority") == "EXTERNAL_APTS_GSS"
            and semantics.get("governance_authorization_query_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
        )
    except Exception:
        return False


def canonical_task_readiness_projection_definition() -> Dict[str, Any]:
    return {
        "schema_version": TASK_READINESS_PROJECTION_SCHEMA_VERSION,
        "mode": TASK_READINESS_PROJECTION_MODE,
        "projection_id_prefix": TASK_READINESS_PROJECTION_ID_PREFIX,
        "allowed_source_states": sorted(TASK_READINESS_PROJECTION_STATES),
        "requires_active_stage3_3_7_plan_version": True,
        "one_immutable_projection_per_plan_version": True,
        "readiness_states": [TASK_READY, TASK_BLOCKED_DEPENDENCY],
        "root_task_semantics": TASK_READY,
        "dependent_task_semantics": TASK_BLOCKED_DEPENDENCY,
        "scheduling_projection_mode": SCHEDULING_PROJECTION_MODE,
        "wall_clock_schedule_created": False,
        "resource_assignment_performed": False,
        "readiness_is_permission": False,
        "ready_is_authorized": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
