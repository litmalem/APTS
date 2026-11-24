from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .task_route_selection import verify_task_route_selection_contract, ROUTE_DECISION_SELECTED

DELEGATION_AUTH_SCHEMA_VERSION = "apts-governance-bound-delegation-authorization-v1"
DELEGATION_AUTH_HASH_DOMAIN = "MISSION_GOVERNANCE_BOUND_DELEGATION_AUTHORIZATION_V1"
DELEGATION_AUTH_REQUEST_HASH_DOMAIN = "MISSION_DELEGATION_AUTHORIZATION_REQUEST_V1"
DELEGATION_AUTH_ID_PREFIX = "dauth-"
DELEGATION_AUTH_OPERATION_PREFIX = "dauthop-"
DELEGATION_AUTH_MODE = "AUTHORITATIVE_GOVERNANCE_PRE_DELEGATION_FAIL_CLOSED"
DELEGATION_ACTION_CLASS = "TASK_DELEGATION"
DELEGATION_ACTION_NAME = "delegate_planned_task"
DELEGATION_RESOURCE_TYPE = "SUBSYSTEM_CAPABILITY"
DELEGATION_AUTH_ALLOWED_STATES = frozenset({"PLANNING", "REPLANNING"})

AUTH_STATUS_AUTHORIZED = "AUTHORIZED"
AUTH_STATUS_DENIED = "DENIED"
AUTH_STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key", "expected_version_sha256", "expected_state_version",
    "expected_active_plan_version_record_id", "expected_active_plan_version",
    "expected_active_plan_sha256", "expected_route_decision_id",
    "expected_route_decision_sha256", "planned_task_id", "requested_by",
    "reason", "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_delegation_authorization_id() -> str:
    return f"{DELEGATION_AUTH_ID_PREFIX}{uuid.uuid4()}"


def deterministic_operation_id(request_sha256: str) -> str:
    return f"{DELEGATION_AUTH_OPERATION_PREFIX}{request_sha256[:40]}"


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


def normalize_delegation_authorization_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("delegation authorization request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported delegation authorization field(s): " + ", ".join(unknown)
            + "; Stage 3.4.5 derives subsystem/capability exclusively from the immutable Stage-3.4.4 route decision. "
              "Caller-supplied decision/effect, subsystem, capability, endpoint, resource assignment, authorization result, "
              "delegation, dispatch, execution, or target-action fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_route_decision_id": _string(payload, "expected_route_decision_id"),
        "planned_task_id": _string(payload, "planned_task_id"),
        "requested_by": _string(payload, "requested_by", 128),
    }
    for key, value in values.items():
        if key != "requested_by" and not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_route_decision_id"].startswith("rdec-"):
        raise MissionValidationError("expected_route_decision_id must be a canonical rdec-* identifier")
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
        "expected_route_decision_sha256": _sha(payload, "expected_route_decision_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def delegation_authorization_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": DELEGATION_AUTH_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_delegation_authorization_contract(*, authorization_id: str, mission_id: str,
                                            request: Mapping[str, Any], route_decision: Mapping[str, Any],
                                            governance_binding: Mapping[str, Any], policy_decision: Mapping[str, Any],
                                            request_sha256: str, operation_id: str, created_at: str) -> Dict[str, Any]:
    if not verify_task_route_selection_contract(route_decision):
        raise MissionValidationError("route_selection_contract failed Stage-3.4.4 integrity verification")
    rd = route_decision["route_decision"]
    if rd.get("decision_status") != ROUTE_DECISION_SELECTED or rd.get("route_selected") is not True:
        raise MissionValidationError("Stage-3.4.5 requires a Stage-3.4.4 ROUTE_SELECTED decision")
    selected = rd["selected_route"]
    gov = governance_binding["binding"]["governance_authority"]
    decision = str(policy_decision["decision"]).upper()
    status = AUTH_STATUS_AUTHORIZED if decision == "ALLOW" else AUTH_STATUS_REVIEW_REQUIRED if decision == "REVIEW" else AUTH_STATUS_DENIED
    core = {
        "schema_version": DELEGATION_AUTH_SCHEMA_VERSION,
        "identity": {
            "delegation_authorization_id": authorization_id,
            "mission_id": mission_id,
            "route_decision_id": route_decision["identity"]["route_decision_id"],
            "plan_version_record_id": route_decision["identity"]["plan_version_record_id"],
            "plan_version": int(route_decision["identity"]["plan_version"]),
            "planned_task_id": route_decision["identity"]["planned_task_id"],
        },
        "source_bindings": {
            "source_state": route_decision["source_bindings"]["state"],
            "source_state_version": int(route_decision["source_bindings"]["state_version"]),
            "source_version_sha256": route_decision["source_bindings"]["source_version_sha256"],
            "active_plan_sha256": route_decision["source_bindings"]["active_plan_sha256"],
            "route_decision_sha256": route_decision["integrity"]["canonical_sha256"],
            "eligibility_gate_id": route_decision["identity"]["eligibility_gate_id"],
            "routing_intent_id": route_decision["identity"]["routing_intent_id"],
            "registry_sha256": route_decision["source_bindings"]["registry_sha256"],
            "mission_governance_binding_id": governance_binding["mission_governance_binding_id"],
            "governance_binding_version": int(governance_binding["binding_version"]),
            "governance_binding_sha256": governance_binding["canonical_sha256"],
            "governance_scope_contract_id": gov["governance_scope_contract_id"],
            "governance_scope_version": int(gov["governance_scope_version"]),
            "governance_scope_contract_hash": gov["governance_scope_contract_hash"],
            "policy_set_id": gov["policy_set_id"],
        },
        "delegation_subject": {
            "selected_subsystem": selected["subsystem_id"],
            "selected_capability": selected["capability_id"],
            "selected_capability_version": int(selected["capability_version"]),
            "logical_route_rank": int(selected["rank"]),
            "resource_type": DELEGATION_RESOURCE_TYPE,
            "resource_value": f"{selected['subsystem_id']}:{selected['capability_id']}",
        },
        "governance_decision": {
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "operation_id": operation_id,
            "authorization_request_id": policy_decision["request_id"],
            "policy_decision_id": policy_decision["decision_id"],
            "policy_decision_hash": policy_decision["decision_hash"],
            "decision": decision,
            "authorization_status": status,
            "authorization_granted": decision == "ALLOW",
            "reason_codes": list(policy_decision.get("reason_codes") or []),
            "constraints": dict(policy_decision.get("constraints") or {}),
            "requires_human_approval": bool(policy_decision.get("requires_human_approval")),
            "approval_request_id": policy_decision.get("approval_request_id"),
            "policy_version": int(policy_decision["policy_version"]),
            "valid_from": policy_decision["valid_from"],
            "valid_until": policy_decision["valid_until"],
            "governance_event_id": policy_decision.get("governance_event_id"),
        },
        "semantics": {
            "mode": DELEGATION_AUTH_MODE,
            "governance_query_performed": True,
            "authorization_is_authoritative": True,
            "authorization_bound_to_exact_route_decision": True,
            "authorization_granted": decision == "ALLOW",
            "authorization_is_delegation": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "execution_authorized": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "pre_delegation_revalidation_required": True,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "version_vector_extension_performed": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "requested_by": request["requested_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "created_at": created_at,
        },
    }
    digest = sha256_hex({"hash_domain": DELEGATION_AUTH_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "hash_domain": DELEGATION_AUTH_HASH_DOMAIN,
                                   "canonicalization": "UTF8_SORTED_JSON_V1", "canonical_sha256": digest}}


def verify_delegation_authorization_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        ident = contract["identity"]; src = contract["source_bindings"]; subj = contract["delegation_subject"]
        gov = contract["governance_decision"]; sem = contract["semantics"]
        decision = gov.get("decision")
        delegation_scope = (gov.get("constraints") or {}).get("delegation_scope") or {}
        expected_resource = f"{subj.get('selected_subsystem')}:{subj.get('selected_capability')}"
        expected_status = AUTH_STATUS_AUTHORIZED if decision == "ALLOW" else AUTH_STATUS_REVIEW_REQUIRED if decision == "REVIEW" else AUTH_STATUS_DENIED
        return (
            contract.get("schema_version") == DELEGATION_AUTH_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == DELEGATION_AUTH_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256") == sha256_hex({"hash_domain": DELEGATION_AUTH_HASH_DOMAIN, "core": core})
            and str(ident.get("delegation_authorization_id", "")).startswith(DELEGATION_AUTH_ID_PREFIX)
            and str(ident.get("route_decision_id", "")).startswith("rdec-")
            and str(ident.get("planned_task_id", "")).startswith("ptask-")
            and all(_SHA_RE.match(str(src.get(k) or "")) for k in ("source_version_sha256", "active_plan_sha256", "route_decision_sha256", "registry_sha256", "governance_binding_sha256", "governance_scope_contract_hash"))
            and subj.get("resource_type") == DELEGATION_RESOURCE_TYPE
            and subj.get("resource_value") == f"{subj.get('selected_subsystem')}:{subj.get('selected_capability')}"
            and decision in {"ALLOW", "DENY", "REVIEW"}
            and gov.get("authorization_status") == expected_status
            and gov.get("authorization_granted") == (decision == "ALLOW")
            and delegation_scope.get("action_class") == DELEGATION_ACTION_CLASS
            and delegation_scope.get("action_name") == DELEGATION_ACTION_NAME
            and delegation_scope.get("subject_component") == "APTS-MO01"
            and delegation_scope.get("resource_type") == DELEGATION_RESOURCE_TYPE
            and delegation_scope.get("resource_value") == expected_resource
            and delegation_scope.get("authorization_purpose") == "PRE_DELEGATION_ONLY"
            and delegation_scope.get("delegation_authorized") == (decision == "ALLOW")
            and delegation_scope.get("execution_authorized") is False
            and delegation_scope.get("target_actuation") is False
            and (decision != "ALLOW" or (
                isinstance((gov.get("constraints") or {}).get("allowed_capabilities"), list)
                and expected_resource in (gov.get("constraints") or {}).get("allowed_capabilities")
            ))
            and sem.get("mode") == DELEGATION_AUTH_MODE
            and sem.get("governance_query_performed") is True
            and sem.get("authorization_is_authoritative") is True
            and sem.get("authorization_bound_to_exact_route_decision") is True
            and sem.get("authorization_granted") == (decision == "ALLOW")
            and sem.get("authorization_is_delegation") is False
            and sem.get("delegation_performed") is False
            and sem.get("dispatch_performed") is False
            and sem.get("execution_authorized") is False
            and sem.get("target_action_dispatch_enabled") is False
            and sem.get("target_actuation") is False
            and sem.get("runtime_endpoint_resolution_performed") is False
            and sem.get("runtime_health_probe_performed") is False
            and sem.get("resource_assignment_performed") is False
            and sem.get("pre_delegation_revalidation_required") is True
            and sem.get("governance_authorization_authority") == "EXTERNAL_APTS_GSS"
            and sem.get("version_vector_extension_performed") is False
        )
    except Exception:
        return False


def canonical_delegation_authorization_definition() -> Dict[str, Any]:
    return {
        "schema_version": DELEGATION_AUTH_SCHEMA_VERSION,
        "mode": DELEGATION_AUTH_MODE,
        "delegation_authorization_id_prefix": DELEGATION_AUTH_ID_PREFIX,
        "allowed_source_states": sorted(DELEGATION_AUTH_ALLOWED_STATES),
        "requires_stage344_route_decision": True,
        "requires_route_selected": True,
        "requires_current_governance_binding": True,
        "governance_action_class": DELEGATION_ACTION_CLASS,
        "governance_action_name": DELEGATION_ACTION_NAME,
        "governance_resource_type": DELEGATION_RESOURCE_TYPE,
        "governance_query_performed": True,
        "authorization_is_authoritative": True,
        "authorization_bound_to_exact_route_decision": True,
        "authorization_is_delegation": False,
        "delegation_performed": False,
        "dispatch_performed": False,
        "execution_authorized": False,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "pre_delegation_revalidation_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "version_vector_extension_performed": False,
    }
