from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .delegation_delivery import (
    ACKNOWLEDGEMENT_STATUS,
    DELIVERY_STATUS,
    OWNERSHIP_STATUS,
    verify_delivery_receipt_contract,
)
from .delegation_handoff import verify_delegation_contract, verify_handoff_envelope
from .errors import MissionValidationError

EXECUTION_DISPATCH_CONTRACT_SCHEMA_VERSION = "apts-canonical-execution-dispatch-contract-v1"
EXECUTION_DISPATCH_CONTRACT_HASH_DOMAIN = "MISSION_CANONICAL_EXECUTION_DISPATCH_CONTRACT_V1"
EXECUTION_DISPATCH_REQUEST_HASH_DOMAIN = "MISSION_CANONICAL_EXECUTION_DISPATCH_REQUEST_V1"
EXECUTION_DISPATCH_ID_PREFIX = "xdispatch-"
EXECUTION_DISPATCH_MODE = "IMMUTABLE_EXECUTION_DISPATCH_IDENTITY_BOUND_TO_OWNED_DELEGATION_PENDING_PRE_DISPATCH_AUTHORIZATION"
EXECUTION_DISPATCH_ALLOWED_STATES = frozenset({"RUNNING"})
EXECUTION_DISPATCH_STATUS = "MATERIALIZED_PENDING_PRE_DISPATCH_AUTHORIZATION"
EXECUTION_AUTHORIZATION_STATUS = "NOT_EVALUATED"
EXECUTION_DISPATCH_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_CANONICAL_EXECUTION_DISPATCH_DEFINITION"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_delivery_receipt_id",
    "expected_delivery_receipt_sha256",
    "planned_task_id",
    "created_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_execution_dispatch_id() -> str:
    return f"{EXECUTION_DISPATCH_ID_PREFIX}{uuid.uuid4()}"


def _string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
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
    value = _string(payload, key, 64).lower()
    if not _SHA_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_execution_dispatch_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("execution dispatch-contract request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported execution dispatch-contract field(s): "
            + ", ".join(unknown)
            + "; Stage 3.5.1 accepts only canonical provenance/concurrency references and dispatch identity metadata. "
              "Caller-supplied runtime endpoint, health result, worker/resource assignment, execution payload, Governance decision, "
              "execution authorization/grant, dispatch attempt, command payload, target-action dispatch, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_delivery_receipt_id": _string(payload, "expected_delivery_receipt_id"),
        "planned_task_id": _string(payload, "planned_task_id"),
        "created_by": _string(payload, "created_by", 128),
    }
    for key in ("idempotency_key", "expected_active_plan_version_record_id", "expected_delivery_receipt_id", "planned_task_id"):
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_delivery_receipt_id"].startswith("drecv-"):
        raise MissionValidationError("expected_delivery_receipt_id must be a canonical drecv-* identifier")
    if not values["planned_task_id"].startswith("ptask-"):
        raise MissionValidationError("planned_task_id must be a canonical ptask-* identifier")

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
        **values,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_delivery_receipt_sha256": _sha(payload, "expected_delivery_receipt_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def execution_dispatch_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": EXECUTION_DISPATCH_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _latest_recovery_binding(recovery_controls: list[Mapping[str, Any]]) -> Dict[str, Any]:
    latest: Optional[Mapping[str, Any]] = recovery_controls[-1] if recovery_controls else None
    return {
        "recovery_control_count": len(recovery_controls),
        "latest_recovery_control_id": None if latest is None else latest.get("recovery_control_id"),
        "latest_recovery_control_sha256": None if latest is None else latest.get("canonical_sha256"),
        "latest_control_action": None if latest is None else latest.get("control_action"),
        "latest_control_outcome": None if latest is None else latest.get("control_outcome"),
        "latest_conflict_status": None if latest is None else latest.get("conflict_status"),
    }


def build_execution_dispatch_contract(
    *,
    execution_dispatch_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    delivery: Mapping[str, Any],
    delegation: Mapping[str, Any],
    recovery_controls: list[Mapping[str, Any]],
    created_at: str,
) -> Dict[str, Any]:
    delivery_contract = delivery.get("delivery_receipt") or delivery.get("delivery_receipt_contract")
    if not verify_delivery_receipt_contract(delivery_contract):
        raise MissionValidationError("Stage-3.4.7 delivery/ACK/ownership receipt failed integrity verification")
    delegation_contract = delegation["delegation_contract"]
    if not verify_delegation_contract(delegation_contract):
        raise MissionValidationError("Stage-3.4.6 delegation contract failed integrity verification")
    handoff = delegation_contract["handoff_envelope"]
    if not verify_handoff_envelope(handoff):
        raise MissionValidationError("Stage-3.4.6 handoff envelope failed integrity verification")

    if delivery_contract["delivery"].get("delivery_status") != DELIVERY_STATUS or not delivery_contract["delivery"].get("handoff_transmitted"):
        raise MissionValidationError("Stage-3.4.7 canonical handoff must be delivered before execution dispatch identity can be materialized")
    if delivery_contract["acknowledgement"].get("acknowledgement_status") != ACKNOWLEDGEMENT_STATUS or not delivery_contract["acknowledgement"].get("handoff_acknowledged"):
        raise MissionValidationError("Stage-3.4.7 canonical handoff must be acknowledged before execution dispatch identity can be materialized")
    if delivery_contract["ownership"].get("ownership_status") != OWNERSHIP_STATUS or not delivery_contract["ownership"].get("ownership_accepted"):
        raise MissionValidationError("Stage-3.4.7 control-plane ownership must be accepted before execution dispatch identity can be materialized")

    source_bindings = delegation_contract["source_bindings"]
    recipient = handoff["recipient"]
    work_context = handoff["work_context"]
    authority_context = handoff["authority_context"]
    recovery = _latest_recovery_binding(recovery_controls)

    core: Dict[str, Any] = {
        "schema_version": EXECUTION_DISPATCH_CONTRACT_SCHEMA_VERSION,
        "identity": {
            "execution_dispatch_id": execution_dispatch_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": delegation["planned_task_id"],
            "task_key": delegation["task_key"],
            "created_by": request["created_by"],
            "created_at": created_at,
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "route_decision_id": delegation["route_decision_id"],
            "route_decision_sha256": source_bindings["route_decision_sha256"],
            "delegation_authorization_id": delegation["delegation_authorization_id"],
            "delegation_authorization_sha256": source_bindings["delegation_authorization_sha256"],
            "delegation_id": delegation["delegation_id"],
            "delegation_sha256": delegation["canonical_sha256"],
            "handoff_envelope_id": delegation["handoff_envelope_id"],
            "handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
            "delivery_receipt_id": delivery["delivery_receipt_id"],
            "delivery_receipt_sha256": delivery["canonical_sha256"],
            "mission_scope_snapshot_id": source_bindings["mission_scope_snapshot_id"],
            "mission_scope_sha256": source_bindings["mission_scope_sha256"],
            "governance_binding_version": int(source_bindings["governance_binding_version"]),
            "governance_binding_sha256": source_bindings["governance_binding_sha256"],
            "delegation_policy_decision_id": source_bindings["policy_decision_id"],
            "delegation_policy_decision_hash": source_bindings["policy_decision_hash"],
            "delegation_policy_version": int(source_bindings["policy_version"]),
            **recovery,
        },
        "dispatch_target": {
            "subsystem_id": recipient["subsystem_id"],
            "capability_id": recipient["capability_id"],
            "capability_version": int(recipient["capability_version"]),
            "logical_target_only": True,
            "runtime_endpoint": None,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
        },
        "work_contract": {
            "work_context": dict(work_context),
            "work_context_sha256": sha256_hex({"work_context": work_context}),
            "caller_supplied_execution_payload": False,
            "payload_derivation": "CANONICAL_STAGE346_HANDOFF_WORK_CONTEXT_ONLY",
        },
        "authority_context": {
            "delegation_authorization_id": authority_context["delegation_authorization_id"],
            "delegation_authorization_scope": "DELEGATION_ONLY",
            "delegation_authorization_reused_as_execution_grant": False,
            "execution_authorization_status": EXECUTION_AUTHORIZATION_STATUS,
            "execution_authorization_id": None,
            "execution_authorized": False,
            "target_action_authorized": False,
            "pre_dispatch_governance_revalidation_required": True,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        },
        "dispatch": {
            "status": EXECUTION_DISPATCH_STATUS,
            "dispatch_contract_materialized": True,
            "dispatch_identity_allocated": True,
            "dispatch_attempt_started": False,
            "dispatch_performed": False,
            "external_network_io_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "semantics": {
            "mode": EXECUTION_DISPATCH_MODE,
            "execution_dispatch_authority": EXECUTION_DISPATCH_AUTHORITY,
            "requires_running_mission_state": True,
            "requires_stage347_delivery_acknowledgement_ownership": True,
            "requires_current_active_plan_version": True,
            "requires_exact_delivery_receipt_hash": True,
            "recipient_derived_from_canonical_handoff": True,
            "work_context_derived_from_canonical_handoff": True,
            "ownership_is_execution_authority": False,
            "dispatch_contract_is_dispatch": False,
            "dispatch_identity_is_execution_authorization": False,
            "execution_authorization_performed": False,
            "governance_query_performed": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "external_network_io_performed": False,
            "dispatch_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "pre_dispatch_governance_revalidation_required": True,
            "version_vector_extension_performed": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "created_at": created_at,
        },
    }
    return {
        "hash_domain": EXECUTION_DISPATCH_CONTRACT_HASH_DOMAIN,
        **core,
        "canonical_sha256": sha256_hex({"hash_domain": EXECUTION_DISPATCH_CONTRACT_HASH_DOMAIN, "core": core}),
    }


def verify_execution_dispatch_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != EXECUTION_DISPATCH_CONTRACT_SCHEMA_VERSION:
            return False
        if contract.get("hash_domain") != EXECUTION_DISPATCH_CONTRACT_HASH_DOMAIN:
            return False
        core = {k: v for k, v in contract.items() if k not in {"hash_domain", "canonical_sha256"}}
        if contract.get("canonical_sha256") != sha256_hex({"hash_domain": EXECUTION_DISPATCH_CONTRACT_HASH_DOMAIN, "core": core}):
            return False
        ident = contract["identity"]
        src = contract["source_bindings"]
        target = contract["dispatch_target"]
        work = contract["work_contract"]
        authority = contract["authority_context"]
        dispatch = contract["dispatch"]
        semantics = contract["semantics"]
        if not str(ident.get("execution_dispatch_id") or "").startswith(EXECUTION_DISPATCH_ID_PREFIX):
            return False
        if not str(ident.get("plan_version_record_id") or "").startswith("pver-"):
            return False
        if not str(ident.get("planned_task_id") or "").startswith("ptask-"):
            return False
        if src.get("source_state") not in EXECUTION_DISPATCH_ALLOWED_STATES:
            return False
        sha_fields = (
            "source_version_sha256", "active_plan_sha256", "route_decision_sha256",
            "delegation_authorization_sha256", "delegation_sha256", "handoff_envelope_sha256",
            "delivery_receipt_sha256", "mission_scope_sha256", "governance_binding_sha256",
            "delegation_policy_decision_hash",
        )
        if any(not _SHA_RE.match(str(src.get(k) or "")) for k in sha_fields):
            return False
        if src.get("latest_recovery_control_sha256") not in (None, "") and not _SHA_RE.match(str(src["latest_recovery_control_sha256"])):
            return False
        prefixes = {
            "route_decision_id": "rdec-",
            "delegation_authorization_id": "dauth-",
            "delegation_id": "deleg-",
            "handoff_envelope_id": "handoff-",
            "delivery_receipt_id": "drecv-",
        }
        for key, prefix in prefixes.items():
            if not str(src.get(key) or "").startswith(prefix):
                return False
        if not target.get("subsystem_id") or not target.get("capability_id"):
            return False
        if not target.get("logical_target_only") or target.get("runtime_endpoint") is not None:
            return False
        if any(target.get(k) for k in ("runtime_endpoint_resolution_performed", "runtime_health_probe_performed", "resource_assignment_performed")):
            return False
        if work.get("caller_supplied_execution_payload") or work.get("payload_derivation") != "CANONICAL_STAGE346_HANDOFF_WORK_CONTEXT_ONLY":
            return False
        if work.get("work_context_sha256") != sha256_hex({"work_context": work.get("work_context")}):
            return False
        if authority.get("delegation_authorization_scope") != "DELEGATION_ONLY":
            return False
        if authority.get("delegation_authorization_reused_as_execution_grant"):
            return False
        if authority.get("execution_authorization_status") != EXECUTION_AUTHORIZATION_STATUS:
            return False
        if authority.get("execution_authorized") or authority.get("target_action_authorized"):
            return False
        if not authority.get("pre_dispatch_governance_revalidation_required"):
            return False
        if dispatch.get("status") != EXECUTION_DISPATCH_STATUS or not dispatch.get("dispatch_contract_materialized") or not dispatch.get("dispatch_identity_allocated"):
            return False
        if any(dispatch.get(k) for k in ("dispatch_attempt_started", "dispatch_performed", "external_network_io_performed", "target_action_dispatch_enabled", "target_actuation")):
            return False
        if semantics.get("mode") != EXECUTION_DISPATCH_MODE:
            return False
        required_true = (
            "requires_running_mission_state", "requires_stage347_delivery_acknowledgement_ownership",
            "requires_current_active_plan_version", "requires_exact_delivery_receipt_hash",
            "recipient_derived_from_canonical_handoff", "work_context_derived_from_canonical_handoff",
            "pre_dispatch_governance_revalidation_required",
        )
        if not all(semantics.get(k) is True for k in required_true):
            return False
        required_false = (
            "ownership_is_execution_authority", "dispatch_contract_is_dispatch",
            "dispatch_identity_is_execution_authorization", "execution_authorization_performed",
            "governance_query_performed", "runtime_endpoint_resolution_performed",
            "runtime_health_probe_performed", "resource_assignment_performed",
            "external_network_io_performed", "dispatch_performed", "target_action_dispatch_enabled",
            "target_actuation", "version_vector_extension_performed",
        )
        if any(semantics.get(k) is not False for k in required_false):
            return False
        return True
    except Exception:
        return False


def canonical_execution_dispatch_definition() -> Dict[str, Any]:
    return {
        "schema_version": EXECUTION_DISPATCH_CONTRACT_SCHEMA_VERSION,
        "mode": EXECUTION_DISPATCH_MODE,
        "execution_dispatch_id_prefix": EXECUTION_DISPATCH_ID_PREFIX,
        "allowed_source_states": sorted(EXECUTION_DISPATCH_ALLOWED_STATES),
        "status": EXECUTION_DISPATCH_STATUS,
        "execution_authorization_status": EXECUTION_AUTHORIZATION_STATUS,
        "execution_dispatch_authority": EXECUTION_DISPATCH_AUTHORITY,
        "requires_stage347_delivery_acknowledgement_ownership": True,
        "requires_current_active_plan_version": True,
        "requires_current_mission_state_and_version_vector": True,
        "requires_exact_delivery_receipt_hash": True,
        "recipient_derived_from_canonical_handoff": True,
        "work_context_derived_from_canonical_handoff": True,
        "caller_supplied_execution_payload_forbidden": True,
        "ownership_is_execution_authority": False,
        "dispatch_contract_is_dispatch": False,
        "dispatch_identity_is_execution_authorization": False,
        "pre_dispatch_governance_revalidation_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "governance_query_performed": False,
        "execution_authorization_performed": False,
        "dispatch_attempt_started": False,
        "dispatch_performed": False,
        "external_network_io_performed": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "version_vector_extension_performed": False,
    }
