from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError

PLANNER_INPUT_SNAPSHOT_SCHEMA_VERSION = "apts-planner-input-snapshot-v1"
PLANNER_INPUT_SNAPSHOT_HASH_DOMAIN = "MISSION_PLANNER_INPUT_SNAPSHOT_V1"
PLANNER_INPUT_SNAPSHOT_REQUEST_HASH_DOMAIN = "MISSION_PLANNER_INPUT_SNAPSHOT_REQUEST_V1"
PLANNER_INPUT_SNAPSHOT_ID_PREFIX = "mpis-"
PLANNER_INPUT_SNAPSHOT_VERSION_INITIAL = 1
PLANNER_INPUT_SNAPSHOT_MODE = "IMMUTABLE_LOCAL_CONTEXT_BOUND_TO_CANONICAL_PLAN_AND_EXACT_PLANNING_STATE"
PLANNER_INPUT_SNAPSHOT_REQUIRED_STATE = "PLANNING"
PLANNER_INPUT_CONTEXT_MODE = "CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH"
PLANNER_INPUT_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_PLANNER_INPUT_DEFINITION"

_PLANNER_INPUT_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_plan_id",
    "expected_plan_version",
    "expected_plan_sha256",
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


def new_planner_input_snapshot_id() -> str:
    return f"{PLANNER_INPUT_SNAPSHOT_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 2000) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if result < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return result


def normalize_planner_input_snapshot_request(payload: Any) -> Dict[str, Any]:
    """Normalize Stage-3.3.2 snapshot-registration input.

    The caller supplies concurrency/binding tokens only. Planner content is never
    accepted from the request: the snapshot is derived from already-canonical local
    Mission/Plan/Scope/Governance/lifecycle records so callers cannot smuggle task
    decomposition, planner output, authorization, or dispatch instructions into the
    planner-input boundary.
    """

    if not isinstance(payload, dict):
        raise MissionValidationError("planner-input-snapshot request body must be a JSON object")

    unknown = sorted(set(payload) - _PLANNER_INPUT_REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported planner-input-snapshot field(s): "
            + ", ".join(unknown)
            + "; Stage 3.3.2 accepts binding tokens only and does not accept planner output, tasks, dependencies, tools, authorization, or dispatch fields"
        )

    idempotency_key = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")

    expected_plan_id = _require_string(payload, "expected_plan_id")
    if not _ID_RE.match(expected_plan_id):
        raise MissionValidationError("expected_plan_id contains unsupported characters")

    expected_plan_version = _positive_int(payload.get("expected_plan_version"), "expected_plan_version")
    expected_state_version = _positive_int(payload.get("expected_state_version"), "expected_state_version")

    expected_plan_sha256 = _require_string(payload, "expected_plan_sha256", 64).lower()
    if not _SHA256_RE.match(expected_plan_sha256):
        raise MissionValidationError("expected_plan_sha256 must be a lowercase SHA-256 hex digest")

    created_by = _require_string(payload, "created_by")
    reason = _optional_string(payload.get("reason"), "reason")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    try:
        canonical_json(metadata)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("metadata must contain JSON-serializable values") from exc

    return {
        "idempotency_key": idempotency_key,
        "expected_plan_id": expected_plan_id,
        "expected_plan_version": expected_plan_version,
        "expected_plan_sha256": expected_plan_sha256,
        "expected_state_version": expected_state_version,
        "created_by": created_by,
        "reason": reason,
        "metadata": dict(metadata),
    }


def planner_input_snapshot_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex(
        {"hash_domain": PLANNER_INPUT_SNAPSHOT_REQUEST_HASH_DOMAIN, "request": dict(normalized)}
    )


def _scope_context(scope_record: Optional[Mapping[str, Any]], plan_contract: Mapping[str, Any]) -> Dict[str, Any]:
    planned = plan_contract["mission_binding"]["scope"]
    if planned["binding_status"] == "UNBOUND":
        return {
            "binding_status": "UNBOUND",
            "mission_scope_contract_id": None,
            "scope_version": 0,
            "scope_snapshot_id": None,
            "scope_sha256": None,
            "scope_contract": None,
        }
    if scope_record is None:
        raise ValueError("bound plan scope requires a local canonical Scope record")
    return {
        "binding_status": "BOUND",
        "mission_scope_contract_id": scope_record["mission_scope_contract_id"],
        "scope_version": int(scope_record["contract_version"]),
        "scope_snapshot_id": scope_record["snapshot_id"],
        "scope_sha256": scope_record["canonical_sha256"],
        "scope_contract": dict(scope_record["contract"]),
    }


def _governance_context(governance_record: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if governance_record is None:
        return {
            "binding_status": "UNBOUND",
            "mission_governance_binding_id": None,
            "binding_version": 0,
            "binding_snapshot_id": None,
            "binding_sha256": None,
            "governance_scope_contract_id": None,
            "governance_scope_version": None,
            "governance_scope_contract_hash": None,
            "governance_binding": None,
            "authorization_semantics": "NO_EXECUTION_PERMISSION_DERIVED",
        }
    return {
        "binding_status": "BOUND",
        "mission_governance_binding_id": governance_record["mission_governance_binding_id"],
        "binding_version": int(governance_record["binding_version"]),
        "binding_snapshot_id": governance_record["binding_snapshot_id"],
        "binding_sha256": governance_record["canonical_sha256"],
        "governance_scope_contract_id": governance_record["governance_scope_contract_id"],
        "governance_scope_version": int(governance_record["governance_scope_version"]),
        "governance_scope_contract_hash": governance_record["governance_scope_contract_hash"],
        "governance_binding": dict(governance_record["binding"]),
        "authorization_semantics": "CONSTRAINT_CONTEXT_ONLY_NO_EXECUTION_PERMISSION_DERIVED",
    }


def build_planner_input_snapshot(
    *,
    mission_id: str,
    snapshot_id: str,
    snapshot_version: int,
    request_sha256: str,
    envelope: Mapping[str, Any],
    state: Mapping[str, Any],
    plan_record: Mapping[str, Any],
    planning_transition: Mapping[str, Any],
    scope_record: Optional[Mapping[str, Any]],
    governance_record: Optional[Mapping[str, Any]],
    created_by: str,
    reason: Optional[str],
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    """Build an immutable deterministic planner-input snapshot from local canonical facts."""

    plan_contract = plan_record["plan_contract"]
    envelope_identity = envelope["identity"]
    envelope_integrity = envelope["integrity"]
    plan_identity = plan_contract["identity"]
    plan_semantics = plan_contract["semantics"]
    pip_binding = (envelope.get("bindings") or {}).get("pip") or {}
    activation_evidence = (planning_transition.get("metadata") or {}).get("mission_planning_run_activation") or {}

    scope_context = _scope_context(scope_record, plan_contract)
    governance_context = _governance_context(governance_record)

    source_context = {
        "mission_envelope_sha256": envelope_integrity["canonical_sha256"],
        "state": state["state"],
        "state_version": int(state["state_version"]),
        "planning_transition_id": planning_transition["transition_id"],
        "plan_id": plan_record["plan_id"],
        "plan_version": int(plan_record["plan_version"]),
        "plan_sha256": plan_record["canonical_sha256"],
        "scope_snapshot_id": scope_context["scope_snapshot_id"],
        "scope_sha256": scope_context["scope_sha256"],
        "governance_binding_snapshot_id": governance_context["binding_snapshot_id"],
        "governance_binding_sha256": governance_context["binding_sha256"],
        "pip_id": pip_binding.get("pip_id"),
        "pip_version": pip_binding.get("pip_version"),
    }
    source_context_sha256 = sha256_hex(
        {"hash_domain": "MISSION_PLANNER_INPUT_SOURCE_CONTEXT_V1", "context": source_context}
    )

    core: Dict[str, Any] = {
        "schema_version": PLANNER_INPUT_SNAPSHOT_SCHEMA_VERSION,
        "identity": {
            "snapshot_id": snapshot_id,
            "snapshot_version": int(snapshot_version),
            "mission_id": mission_id,
            "plan_id": plan_record["plan_id"],
            "plan_version": int(plan_record["plan_version"]),
            "created_by": created_by,
            "created_at": created_at,
        },
        "mission_context": {
            "mission_id": mission_id,
            "envelope_id": envelope_identity["envelope_id"],
            "envelope_version": int(envelope_identity["envelope_version"]),
            "envelope_sha256": envelope_integrity["canonical_sha256"],
            "correlation_id": envelope_identity["correlation_id"],
            "parent_mission_id": envelope_identity.get("parent_mission_id"),
            "mission_kind": plan_contract["mission_binding"]["mission_kind"],
            "objective": plan_contract["planning_basis"]["objective"],
            "success_criteria": plan_contract["planning_basis"]["success_criteria"],
            "budgets": plan_contract["planning_basis"]["budgets"],
            "required_subsystems": plan_contract["planning_basis"]["required_subsystems"],
        },
        "plan_binding": {
            "plan_id": plan_record["plan_id"],
            "plan_version": int(plan_record["plan_version"]),
            "plan_schema_version": plan_record["schema_version"],
            "plan_sha256": plan_record["canonical_sha256"],
            "plan_status": plan_semantics["plan_status"],
            "task_graph_status": plan_contract["task_graph"]["status"],
            "task_count": int(plan_contract["task_graph"]["task_count"]),
            "dependency_edge_count": int(plan_contract["task_graph"]["dependency_edge_count"]),
        },
        "lifecycle_context": {
            "required_state": PLANNER_INPUT_SNAPSHOT_REQUIRED_STATE,
            "state": state["state"],
            "state_version": int(state["state_version"]),
            "planning_transition_id": planning_transition["transition_id"],
            "planning_transition_from_state": planning_transition["from_state"],
            "planning_transition_to_state": planning_transition["to_state"],
            "planning_transition_reason_code": planning_transition["reason_code"],
            "stage3_2_4_activation_evidence": dict(activation_evidence),
        },
        "scope_context": scope_context,
        "governance_context": governance_context,
        "knowledge_context": {
            "pip_binding_status": "BOUND" if pip_binding.get("pip_id") and pip_binding.get("pip_version") else "UNBOUND",
            "pip_id": pip_binding.get("pip_id"),
            "pip_version": pip_binding.get("pip_version"),
            "external_knowledge_refresh_performed": False,
            "knowledge_materialization_mode": "REFERENCE_EXISTING_IMMUTABLE_PIP_BINDING_ONLY",
        },
        "context_binding": {
            "mode": PLANNER_INPUT_CONTEXT_MODE,
            "source_context_sha256": source_context_sha256,
            "source_context": source_context,
            "fact_policy": "CANONICAL_DURABLE_LOCAL_FACTS_ONLY",
            "hypothesis_materialization_performed": False,
            "provenance_required": True,
            "freshness_semantics": "IMMUTABLE_AS_OF_CAPTURE",
        },
        "semantics": {
            "snapshot_mode": PLANNER_INPUT_SNAPSHOT_MODE,
            "snapshot_authority": PLANNER_INPUT_AUTHORITY,
            "immutable_snapshot": True,
            "planner_input_ready": True,
            "planner_invocation_performed": False,
            "plan_synthesis_performed": False,
            "task_decomposition_performed": False,
            "plan_revision_performed": False,
            "snapshot_is_authorization": False,
            "context_is_permission": False,
            "plan_is_authorization": False,
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

    digest = sha256_hex({"hash_domain": PLANNER_INPUT_SNAPSHOT_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": PLANNER_INPUT_SNAPSHOT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_planner_input_snapshot(snapshot: Mapping[str, Any]) -> bool:
    try:
        if snapshot.get("schema_version") != PLANNER_INPUT_SNAPSHOT_SCHEMA_VERSION:
            return False
        integrity = snapshot["integrity"]
        core = {k: v for k, v in snapshot.items() if k != "integrity"}
        identity = snapshot["identity"]
        plan = snapshot["plan_binding"]
        lifecycle = snapshot["lifecycle_context"]
        scope = snapshot["scope_context"]
        governance = snapshot["governance_context"]
        semantics = snapshot["semantics"]
        context_binding = snapshot["context_binding"]

        scope_ok = scope.get("binding_status") in {"BOUND", "UNBOUND"}
        if scope.get("binding_status") == "BOUND":
            scope_contract = scope.get("scope_contract")
            scope_ok = (
                isinstance(scope_contract, dict)
                and scope.get("scope_sha256") == scope_contract.get("integrity", {}).get("canonical_sha256")
                and int(scope.get("scope_version")) >= 1
            )
        else:
            scope_ok = scope.get("scope_contract") is None and int(scope.get("scope_version", -1)) == 0

        governance_ok = governance.get("binding_status") in {"BOUND", "UNBOUND"}
        if governance.get("binding_status") == "BOUND":
            binding = governance.get("governance_binding")
            governance_ok = (
                isinstance(binding, dict)
                and governance.get("binding_sha256") == binding.get("integrity", {}).get("canonical_sha256")
                and int(governance.get("binding_version")) >= 1
            )
        else:
            governance_ok = governance.get("governance_binding") is None and int(governance.get("binding_version", -1)) == 0

        source_context = context_binding["source_context"]
        source_context_ok = context_binding.get("source_context_sha256") == sha256_hex(
            {"hash_domain": "MISSION_PLANNER_INPUT_SOURCE_CONTEXT_V1", "context": source_context}
        )

        return (
            integrity.get("hash_domain") == PLANNER_INPUT_SNAPSHOT_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": PLANNER_INPUT_SNAPSHOT_HASH_DOMAIN, "core": core})
            and str(identity.get("snapshot_id") or "").startswith(PLANNER_INPUT_SNAPSHOT_ID_PREFIX)
            and int(identity.get("snapshot_version")) >= 1
            and identity.get("mission_id") == snapshot["mission_context"].get("mission_id")
            and identity.get("plan_id") == plan.get("plan_id")
            and int(identity.get("plan_version")) == int(plan.get("plan_version"))
            and plan.get("task_graph_status") == "NOT_MATERIALIZED"
            and int(plan.get("task_count")) == 0
            and int(plan.get("dependency_edge_count")) == 0
            and lifecycle.get("state") == PLANNER_INPUT_SNAPSHOT_REQUIRED_STATE
            and lifecycle.get("planning_transition_to_state") == PLANNER_INPUT_SNAPSHOT_REQUIRED_STATE
            and scope_ok
            and governance_ok
            and source_context_ok
            and semantics.get("planner_input_ready") is True
            and semantics.get("planner_invocation_performed") is False
            and semantics.get("plan_synthesis_performed") is False
            and semantics.get("task_decomposition_performed") is False
            and semantics.get("snapshot_is_authorization") is False
            and semantics.get("context_is_permission") is False
            and semantics.get("plan_is_authorization") is False
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


def canonical_planner_input_snapshot_definition() -> Dict[str, Any]:
    return {
        "schema_version": PLANNER_INPUT_SNAPSHOT_SCHEMA_VERSION,
        "mode": PLANNER_INPUT_SNAPSHOT_MODE,
        "snapshot_identity_prefix": PLANNER_INPUT_SNAPSHOT_ID_PREFIX,
        "initial_snapshot_version": PLANNER_INPUT_SNAPSHOT_VERSION_INITIAL,
        "creation_state_required": PLANNER_INPUT_SNAPSHOT_REQUIRED_STATE,
        "requires_stage3_3_1_plan_contract": True,
        "requires_exact_plan_id": True,
        "requires_exact_plan_version": True,
        "requires_exact_plan_sha256": True,
        "requires_exact_state_version": True,
        "requires_plan_scope_head_consistency": True,
        "context_mode": PLANNER_INPUT_CONTEXT_MODE,
        "context_sources": [
            "CANONICAL_MISSION_ENVELOPE",
            "CANONICAL_PLAN_CONTRACT",
            "EXACT_PLANNING_STATE_AND_STAGE3_2_4_ACTIVATION_LINEAGE",
            "BOUND_LOCAL_SCOPE_CONTRACT_WHEN_PRESENT",
            "CURRENT_LOCAL_GOVERNANCE_BINDING_WHEN_PRESENT",
            "IMMUTABLE_PIP_BINDING_REFERENCE",
        ],
        "caller_supplied_planner_content_allowed": False,
        "external_context_refresh_performed": False,
        "planner_input_ready": True,
        "planner_invocation_performed": False,
        "plan_synthesis_performed": False,
        "task_decomposition_performed": False,
        "plan_revision_performed": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "governance_authorization_query_performed": False,
        "snapshot_is_authorization": False,
        "context_is_permission": False,
        "plan_is_authorization": False,
        "task_is_dispatch": False,
        "readiness_is_permission": False,
        "planner_is_governance": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
