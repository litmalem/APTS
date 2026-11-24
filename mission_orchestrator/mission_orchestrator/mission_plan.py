from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError

PLAN_CONTRACT_SCHEMA_VERSION = "apts-mission-plan-contract-v1"
PLAN_CONTRACT_HASH_DOMAIN = "MISSION_PLAN_CONTRACT_V1"
PLAN_REQUEST_HASH_DOMAIN = "MISSION_PLAN_CONTRACT_REQUEST_V1"
PLAN_ID_PREFIX = "mplan-"
PLAN_VERSION_INITIAL = 1
PLAN_CONTRACT_MODE = "IMMUTABLE_CANONICAL_PLAN_IDENTITY_BOUND_TO_MISSION_AND_PLANNING_ACTIVATION"
PLAN_LIFECYCLE_STATE_REQUIRED = "PLANNING"
PLAN_STATUS_INITIAL = "DRAFT"
PLAN_TASK_GRAPH_STATUS_INITIAL = "NOT_MATERIALIZED"
PLAN_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_CANONICAL_PLAN_DEFINITION"

_PLAN_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
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


def new_plan_id() -> str:
    return f"{PLAN_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 1000) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def normalize_plan_contract_request(payload: Any) -> Dict[str, Any]:
    """Normalize the explicit Stage-3.3.1 plan-registration request.

    Stage 3.3.1 intentionally does *not* accept tasks, dependencies, tool calls,
    authorization decisions, or planner output. The canonical plan body is derived
    from existing Mission state/envelope/scope data; later Stage-3.3 controls own
    decomposition and plan revision semantics.
    """

    if not isinstance(payload, dict):
        raise MissionValidationError("mission plan-contract request body must be a JSON object")

    unknown = sorted(set(payload) - _PLAN_REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported mission plan-contract field(s): "
            + ", ".join(unknown)
            + "; Stage 3.3.1 does not accept task/dependency/planner fields; put annotations under metadata"
        )

    idempotency_key = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")

    expected_version_sha256 = _require_string(payload, "expected_version_sha256", 64).lower()
    if not _SHA256_RE.match(expected_version_sha256):
        raise MissionValidationError("expected_version_sha256 must be a lowercase SHA-256 hex digest")

    created_by = _require_string(payload, "created_by")

    raw_state_version = payload.get("expected_state_version")
    if isinstance(raw_state_version, bool):
        raise MissionValidationError("expected_state_version must be an integer")
    try:
        expected_state_version = int(raw_state_version)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("expected_state_version is required and must be an integer") from exc
    if expected_state_version < 1:
        raise MissionValidationError("expected_state_version must be >= 1")

    reason = _optional_string(payload.get("reason"), "reason", 2000)
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    try:
        canonical_json(metadata)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("metadata must contain JSON-serializable values") from exc

    return {
        "idempotency_key": idempotency_key,
        "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version,
        "created_by": created_by,
        "reason": reason,
        "metadata": dict(metadata),
    }


def plan_contract_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": PLAN_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _scope_binding(scope_record: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if scope_record is None:
        return {
            "binding_status": "UNBOUND",
            "mission_scope_contract_id": None,
            "scope_version": 0,
            "scope_snapshot_id": None,
            "scope_sha256": None,
        }
    return {
        "binding_status": "BOUND",
        "mission_scope_contract_id": scope_record["mission_scope_contract_id"],
        "scope_version": int(scope_record["contract_version"]),
        "scope_snapshot_id": scope_record["snapshot_id"],
        "scope_sha256": scope_record["canonical_sha256"],
    }


def build_plan_contract(
    *,
    mission_id: str,
    plan_id: str,
    plan_version: int,
    request_sha256: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    planning_transition: Mapping[str, Any],
    scope_record: Optional[Mapping[str, Any]],
    created_by: str,
    reason: Optional[str],
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    """Build the immutable Stage-3.3.1 canonical plan identity/contract.

    The body deliberately contains no executable task graph. It creates a stable,
    hashed plan identity and binds that identity to the exact Mission envelope,
    exact PLANNING state/version, Stage-3.2.4 activation lineage, PIP identity, and
    current local Scope contract (when one exists).
    """

    identity = dict(envelope["identity"])
    mission = dict(envelope["mission"])
    bindings = dict(envelope.get("bindings") or {})
    pip_binding = dict(bindings.get("pip") or {})
    envelope_sha256 = envelope["integrity"]["canonical_sha256"]

    core: Dict[str, Any] = {
        "schema_version": PLAN_CONTRACT_SCHEMA_VERSION,
        "identity": {
            "plan_id": plan_id,
            "plan_version": int(plan_version),
            "mission_id": mission_id,
            "created_by": created_by,
            "created_at": created_at,
        },
        "mission_binding": {
            "mission_id": mission_id,
            "envelope_id": identity["envelope_id"],
            "envelope_version": int(identity["envelope_version"]),
            "envelope_sha256": envelope_sha256,
            "correlation_id": identity["correlation_id"],
            "parent_mission_id": identity.get("parent_mission_id"),
            "source_system": envelope.get("provenance", {}).get("source_system"),
            "mission_kind": mission["mission_kind"],
            "objective_sha256": sha256_hex({"objective": mission["objective"]}),
            "success_criteria_sha256": sha256_hex({"success_criteria": mission.get("success_criteria") or []}),
            "budgets_sha256": sha256_hex({"budgets": mission.get("budgets") or {}}),
            "required_subsystems_sha256": sha256_hex(
                {"required_subsystems": mission.get("required_subsystems") or []}
            ),
            "pip_id": pip_binding.get("pip_id"),
            "pip_version": pip_binding.get("pip_version"),
            "scope": _scope_binding(scope_record),
        },
        "planning_activation_binding": {
            "required_state": PLAN_LIFECYCLE_STATE_REQUIRED,
            "state": current_state["state"],
            "state_version": int(current_state["state_version"]),
            "planning_transition_id": planning_transition["transition_id"],
            "planning_transition_from_state": planning_transition["from_state"],
            "planning_transition_to_state": planning_transition["to_state"],
            "planning_activation_reason_code": planning_transition["reason_code"],
        },
        "planning_basis": {
            "objective": mission["objective"],
            "success_criteria": mission.get("success_criteria") or [],
            "budgets": mission.get("budgets") or {},
            "required_subsystems": mission.get("required_subsystems") or [],
        },
        "task_graph": {
            "status": PLAN_TASK_GRAPH_STATUS_INITIAL,
            "task_count": 0,
            "dependency_edge_count": 0,
            "tasks": [],
            "dependency_edges": [],
        },
        "semantics": {
            "plan_status": PLAN_STATUS_INITIAL,
            "plan_authority": PLAN_AUTHORITY,
            "plan_contract_mode": PLAN_CONTRACT_MODE,
            "immutable_identity": True,
            "initial_plan_version": PLAN_VERSION_INITIAL,
            "planner_invocation_performed": False,
            "task_decomposition_performed": False,
            "plan_revision_performed": False,
            "plan_is_authorization": False,
            "task_is_dispatch": False,
            "readiness_is_permission": False,
            "planner_is_governance": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": PLAN_CONTRACT_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": PLAN_CONTRACT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_plan_contract(plan: Mapping[str, Any]) -> bool:
    try:
        if plan.get("schema_version") != PLAN_CONTRACT_SCHEMA_VERSION:
            return False
        core = {k: v for k, v in plan.items() if k != "integrity"}
        integrity = plan["integrity"]
        identity = plan["identity"]
        semantics = plan["semantics"]
        activation = plan["planning_activation_binding"]
        task_graph = plan["task_graph"]
        return (
            integrity.get("hash_domain") == PLAN_CONTRACT_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": PLAN_CONTRACT_HASH_DOMAIN, "core": core})
            and str(identity.get("plan_id") or "").startswith(PLAN_ID_PREFIX)
            and int(identity.get("plan_version")) >= 1
            and identity.get("mission_id") == plan["mission_binding"].get("mission_id")
            and activation.get("state") == PLAN_LIFECYCLE_STATE_REQUIRED
            and activation.get("planning_transition_to_state") == PLAN_LIFECYCLE_STATE_REQUIRED
            and semantics.get("plan_is_authorization") is False
            and semantics.get("task_is_dispatch") is False
            and semantics.get("readiness_is_permission") is False
            and semantics.get("planner_is_governance") is False
            and semantics.get("planner_invocation_performed") is False
            and semantics.get("task_decomposition_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
            and task_graph.get("status") == PLAN_TASK_GRAPH_STATUS_INITIAL
            and int(task_graph.get("task_count")) == 0
            and int(task_graph.get("dependency_edge_count")) == 0
            and task_graph.get("tasks") == []
            and task_graph.get("dependency_edges") == []
        )
    except Exception:
        return False


def canonical_plan_contract_definition() -> Dict[str, Any]:
    """Static discovery contract for Stage 3.3.1."""
    return {
        "schema_version": PLAN_CONTRACT_SCHEMA_VERSION,
        "mode": PLAN_CONTRACT_MODE,
        "plan_identity_prefix": PLAN_ID_PREFIX,
        "initial_plan_version": PLAN_VERSION_INITIAL,
        "creation_state_required": PLAN_LIFECYCLE_STATE_REQUIRED,
        "creation_requires_stage3_2_4_planning_activation_lineage": True,
        "creation_requires_exact_version_sha256": True,
        "creation_requires_exact_state_version": True,
        "mission_binding": "IMMUTABLE_ENVELOPE_PLUS_EXACT_PLANNING_STATE_PLUS_OPTIONAL_LOCAL_SCOPE_SNAPSHOT",
        "task_graph_status_at_stage3_3_1": PLAN_TASK_GRAPH_STATUS_INITIAL,
        "planner_invocation_performed": False,
        "task_decomposition_performed": False,
        "plan_revision_performed": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "plan_is_authorization": False,
        "task_is_dispatch": False,
        "readiness_is_permission": False,
        "planner_is_governance": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
