from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Mapping

from .errors import MissionValidationError

VERSION_VECTOR_SCHEMA_VERSION = "apts-mission-version-vector-v1"
COMMAND_SCHEMA_VERSION = "apts-mission-command-v1"
VERSION_VECTOR_HASH_DOMAIN = "MISSION_VERSION_VECTOR_V1"
COMMAND_REQUEST_HASH_DOMAIN = "MISSION_COMMAND_REQUEST_V1"
CONCURRENCY_MODE = "OPTIMISTIC_VERSION_VECTOR_IDEMPOTENT_COMMAND_GATE"

SUPPORTED_COMMAND_OPERATIONS = frozenset(
    {
        "LIFECYCLE_COMMAND",
        "STATE_TRANSITION",
        "SCOPE_CONTRACT_PUT",
        "GOVERNANCE_BINDING_PUT",
        "AUTHORIZATION_BINDING_CREATE",
        "ROUTING_TASK_CREATE",
        "ROUTING_TASK_DISPATCH",
    }
)

_COMMAND_FIELDS = {
    "command_id",
    "idempotency_key",
    "operation",
    "expected_version_sha256",
    "payload",
    "submitted_by",
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


def build_version_vector_core(
    *,
    mission_id: str,
    envelope_version: int,
    state: str,
    state_version: int,
    mission_plan_version: int,
    planner_input_snapshot_version: int,
    task_decomposition_version: int,
    task_dependency_graph_version: int,
    planner_generation_version: int,
    plan_validation_version: int,
    plan_versioning_version: int,
    task_readiness_projection_version: int,
    planning_recovery_version: int,
    scope_contract_version: int,
    scope_snapshot_id: str | None,
    scope_sha256: str | None,
    governance_binding_version: int,
    governance_binding_snapshot_id: str | None,
    governance_binding_sha256: str | None,
    governance_scope_version: int | None,
    latest_policy_version: int | None,
    latest_policy_decision_id: str | None,
    authorization_binding_count: int,
    routing_task_count: int,
    routing_task_set_sha256: str,
    cti_observation_status: str,
    cti_mission_status: str | None,
    cti_state_version: int | None,
    cti_plan_version: int | None,
) -> Dict[str, Any]:
    return {
        "schema_version": VERSION_VECTOR_SCHEMA_VERSION,
        "mission_id": mission_id,
        "versions": {
            "envelope_version": int(envelope_version),
            "state_version": int(state_version),
            "mission_plan_version": int(mission_plan_version),
            "planner_input_snapshot_version": int(planner_input_snapshot_version),
            "task_decomposition_version": int(task_decomposition_version),
            "task_dependency_graph_version": int(task_dependency_graph_version),
            "planner_generation_version": int(planner_generation_version),
            "plan_validation_version": int(plan_validation_version),
            "plan_versioning_version": int(plan_versioning_version),
            "task_readiness_projection_version": int(task_readiness_projection_version),
            "planning_recovery_version": int(planning_recovery_version),
            "scope_contract_version": int(scope_contract_version),
            "governance_binding_version": int(governance_binding_version),
            "governance_scope_version": None if governance_scope_version is None else int(governance_scope_version),
            "policy_version": None if latest_policy_version is None else int(latest_policy_version),
            "cti_state_version": None if cti_state_version is None else int(cti_state_version),
            "cti_plan_version": None if cti_plan_version is None else int(cti_plan_version),
        },
        "identity_bindings": {
            "state": state,
            "scope_snapshot_id": scope_snapshot_id,
            "scope_sha256": scope_sha256,
            "governance_binding_snapshot_id": governance_binding_snapshot_id,
            "governance_binding_sha256": governance_binding_sha256,
            "latest_policy_decision_id": latest_policy_decision_id,
        },
        "local_revisions": {
            "authorization_binding_count": int(authorization_binding_count),
            "routing_task_count": int(routing_task_count),
            "routing_task_set_sha256": routing_task_set_sha256,
        },
        "subsystem_observations": {
            "cti_observation_status": cti_observation_status,
            "cti_mission_status": cti_mission_status,
        },
    }


def finalize_version_vector(core: Mapping[str, Any], *, complete: bool, observed_at: str) -> Dict[str, Any]:
    digest = sha256_hex({"hash_domain": VERSION_VECTOR_HASH_DOMAIN, "vector": dict(core)})
    return {
        **dict(core),
        "complete": bool(complete),
        "observed_at": observed_at,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": VERSION_VECTOR_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def routing_task_set_sha256(tasks: list[Mapping[str, Any]]) -> str:
    projection = [
        {
            "task_id": t.get("task_id"),
            "destination_subsystem": t.get("destination_subsystem"),
            "task_status": t.get("task_status"),
            "canonical_sha256": t.get("canonical_sha256"),
        }
        for t in sorted(tasks, key=lambda x: str(x.get("task_id") or ""))
    ]
    return sha256_hex({"hash_domain": "MISSION_ROUTING_TASK_SET_V1", "tasks": projection})


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def normalize_command_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("mission command request body must be a JSON object")

    unknown = sorted(set(payload) - _COMMAND_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported mission command field(s): " + ", ".join(unknown) + "; put extensions under metadata"
        )

    command_id = _require_string(payload, "command_id")
    idempotency_key = _require_string(payload, "idempotency_key")
    submitted_by = _require_string(payload, "submitted_by")
    if not _ID_RE.match(command_id):
        raise MissionValidationError("command_id contains unsupported characters")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")

    operation = _require_string(payload, "operation", 64).upper()
    if operation not in SUPPORTED_COMMAND_OPERATIONS:
        raise MissionValidationError(
            "unsupported mission command operation; expected one of: "
            + ", ".join(sorted(SUPPORTED_COMMAND_OPERATIONS))
        )

    expected = _require_string(payload, "expected_version_sha256", 64).lower()
    if not _SHA256_RE.match(expected):
        raise MissionValidationError("expected_version_sha256 must be a lowercase SHA-256 hex digest")

    body = payload.get("payload")
    if not isinstance(body, dict):
        raise MissionValidationError("payload must be a JSON object")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")

    try:
        canonical_json(body)
        canonical_json(metadata)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("payload and metadata must contain JSON-serializable values") from exc

    return {
        "command_id": command_id,
        "idempotency_key": idempotency_key,
        "operation": operation,
        "expected_version_sha256": expected,
        "payload": dict(body),
        "submitted_by": submitted_by,
        "metadata": dict(metadata),
    }


def command_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": COMMAND_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def verify_version_vector(vector: Mapping[str, Any]) -> bool:
    """Verify a persisted Stage-3.1.6 version-vector without live observations."""
    try:
        integrity = vector["integrity"]
        core = {k: v for k, v in vector.items() if k not in {"complete", "observed_at", "integrity"}}
        return (
            integrity.get("hash_domain") == VERSION_VECTOR_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": VERSION_VECTOR_HASH_DOMAIN, "vector": core})
        )
    except Exception:
        return False
