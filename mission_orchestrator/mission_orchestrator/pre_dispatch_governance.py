from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence

from .dispatch_eligibility import (
    DISPATCH_ELIGIBILITY_GATE_PASSED,
    evaluate_dispatch_execution_preconditions,
    verify_dispatch_eligibility_contract,
)
from .errors import MissionValidationError
from .governance_binding import verify_binding_contract
from .scope_contract import verify_contract

PRE_DISPATCH_REVALIDATION_SCHEMA_VERSION = "apts-authoritative-pre-dispatch-governance-revalidation-v1"
PRE_DISPATCH_REVALIDATION_HASH_DOMAIN = "MISSION_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE_REVALIDATION_V1"
PRE_DISPATCH_REVALIDATION_REQUEST_HASH_DOMAIN = "MISSION_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE_REVALIDATION_REQUEST_V1"
PRE_DISPATCH_REVALIDATION_ID_PREFIX = "xreval-"
PRE_DISPATCH_REVALIDATION_OPERATION_PREFIX = "xreval-op-"
PRE_DISPATCH_REVALIDATION_MODE = "AUTHORITATIVE_PRE_DISPATCH_FAIL_CLOSED"
PRE_DISPATCH_REVALIDATION_ALLOWED_STATES = frozenset({"RUNNING"})
PRE_DISPATCH_GOVERNANCE_ACTION_CLASS = "TASK_EXECUTION"
#: Governance (aptsGS) has no TASK_EXECUTION class; it authorizes the action class of
#: the capability being dispatched. Unmapped capabilities keep the legacy value, which
#: Governance rejects (fail-closed) rather than silently receiving a broader class.
PRE_DISPATCH_CAPABILITY_ACTION_CLASS = {
    "pentest.recon": "TARGET_RECON",
    "pentest.validate": "VULNERABILITY_VALIDATION",
    "cti.analyze.context": "CTI_SOURCE_READ",
}


def pre_dispatch_action_class(capability_id: str) -> str:
    return PRE_DISPATCH_CAPABILITY_ACTION_CLASS.get(capability_id, PRE_DISPATCH_GOVERNANCE_ACTION_CLASS)


PRE_DISPATCH_GOVERNANCE_ACTION_NAME = "AUTHORIZE_EXECUTION_DISPATCH"
PRE_DISPATCH_GOVERNANCE_RESOURCE_TYPE = "SUBSYSTEM_CAPABILITY"
PRE_DISPATCH_REVALIDATION_AUTHORITY = "EXTERNAL_APTS_GSS"
def pre_dispatch_governance_resource(target: Mapping[str, Any], external_scope: Mapping[str, Any]):
    """(action_name, resource_type, resource_value) submitted to Governance.

    Governance scopes TARGET_RECON by the Mission's scoped target, so a Recon dispatch is
    authorized with the scope's own ``AUTHORIZE_TARGET_EXECUTION`` rule against the single
    allowed scope target. Anything else (other capabilities, zero/multiple targets) keeps
    the logical SUBSYSTEM_CAPABILITY resource, which Governance denies out of scope.
    """
    default = (PRE_DISPATCH_GOVERNANCE_ACTION_NAME, PRE_DISPATCH_GOVERNANCE_RESOURCE_TYPE,
               f"{target['subsystem_id']}:{target['capability_id']}")
    if target.get("capability_id") != "pentest.recon":
        return default
    allowed = [t for t in (external_scope or {}).get("targets") or [] if t.get("allowed")]
    if len(allowed) != 1 or not allowed[0].get("target_type") or not allowed[0].get("target_value"):
        return default
    return ("AUTHORIZE_TARGET_EXECUTION", str(allowed[0]["target_type"]), str(allowed[0]["target_value"]))


PRE_DISPATCH_STATIC_REVALIDATION_PASSED = "PASSED"
PRE_DISPATCH_STATIC_REVALIDATION_FAILED = "FAILED"
EXECUTION_AUTHORIZED_STATUS = "AUTHORIZED_BY_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE"
EXECUTION_DENIED_STATUS = "DENIED_BY_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE"
EXECUTION_REVIEW_STATUS = "REVIEW_REQUIRED_BY_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_execution_dispatch_id",
    "expected_execution_dispatch_sha256",
    "expected_dispatch_eligibility_id",
    "expected_dispatch_eligibility_sha256",
    "requested_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_pre_dispatch_revalidation_id() -> str:
    return f"{PRE_DISPATCH_REVALIDATION_ID_PREFIX}{uuid.uuid4()}"


def deterministic_revalidation_operation_id(request_sha256: str) -> str:
    return f"{PRE_DISPATCH_REVALIDATION_OPERATION_PREFIX}{request_sha256[:40]}"


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


def normalize_pre_dispatch_revalidation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("pre-dispatch Governance revalidation request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported pre-dispatch Governance revalidation field(s): "
            + ", ".join(unknown)
            + "; Stage 3.5.3 derives static revalidation, authoritative Governance PolicyDecision, and execution authorization from canonical Mission artifacts. Caller-supplied Governance decisions, authorization results, runtime endpoints, health results, resource assignments, execution payloads, dispatch attempts, target actions, or actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_dispatch_id": _string(payload, "expected_execution_dispatch_id"),
        "expected_dispatch_eligibility_id": _string(payload, "expected_dispatch_eligibility_id"),
        "requested_by": _string(payload, "requested_by", 128),
    }
    for key in ("idempotency_key", "expected_active_plan_version_record_id", "expected_execution_dispatch_id", "expected_dispatch_eligibility_id"):
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_execution_dispatch_id"].startswith("xdispatch-"):
        raise MissionValidationError("expected_execution_dispatch_id must be a canonical xdispatch-* identifier")
    if not values["expected_dispatch_eligibility_id"].startswith("xelig-"):
        raise MissionValidationError("expected_dispatch_eligibility_id must be a canonical xelig-* identifier")
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
        "expected_execution_dispatch_sha256": _sha(payload, "expected_execution_dispatch_sha256"),
        "expected_dispatch_eligibility_sha256": _sha(payload, "expected_dispatch_eligibility_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def pre_dispatch_revalidation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": PRE_DISPATCH_REVALIDATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def evaluate_authoritative_pre_dispatch_static_revalidation(
    *,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    readiness_projection: Mapping[str, Any],
    execution_dispatch: Mapping[str, Any],
    dispatch_eligibility: Mapping[str, Any],
    delivery: Mapping[str, Any],
    delegation: Mapping[str, Any],
    route: Mapping[str, Any],
    delegation_authorization: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
    recovery_controls: Sequence[Mapping[str, Any]],
    registry_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    checks: Dict[str, bool] = {}
    eligibility_contract = dispatch_eligibility.get("dispatch_eligibility_contract") or {}
    checks["stage352_eligibility_contract_integrity_valid"] = verify_dispatch_eligibility_contract(eligibility_contract)
    checks["stage352_gate_passed"] = dispatch_eligibility.get("gate_result") == DISPATCH_ELIGIBILITY_GATE_PASSED
    checks["stage352_bound_to_stage351_dispatch"] = (
        dispatch_eligibility.get("execution_dispatch_id") == execution_dispatch.get("execution_dispatch_id")
        and eligibility_contract.get("source_bindings", {}).get("execution_dispatch_sha256") == execution_dispatch.get("canonical_sha256")
    )
    checks["stage352_bound_to_active_plan"] = (
        dispatch_eligibility.get("plan_version_record_id") == active_plan.get("plan_version_record_id")
        and int(dispatch_eligibility.get("plan_version") or 0) == int(active_plan.get("plan_version") or -1)
        and eligibility_contract.get("source_bindings", {}).get("active_plan_sha256") == active_plan.get("canonical_sha256")
    )
    checks["canonical_scope_integrity_valid"] = verify_contract(scope_record.get("contract") or {})
    checks["canonical_governance_binding_integrity_valid"] = verify_binding_contract(governance_binding.get("binding") or {})
    refreshed = evaluate_dispatch_execution_preconditions(
        state=state,
        version_vector=version_vector,
        active_plan=active_plan,
        readiness_projection=readiness_projection,
        execution_dispatch=execution_dispatch,
        delivery=delivery,
        delegation=delegation,
        route=route,
        delegation_authorization=delegation_authorization,
        scope_record=scope_record,
        governance_binding=governance_binding,
        recovery_controls=recovery_controls,
        registry_snapshot=registry_snapshot,
    )
    for key, value in refreshed["checks"].items():
        checks[f"refreshed_{key}"] = bool(value)
    failed = sorted(k for k, v in checks.items() if not v)
    return {
        "status": PRE_DISPATCH_STATIC_REVALIDATION_PASSED if not failed else PRE_DISPATCH_STATIC_REVALIDATION_FAILED,
        "checks": checks,
        "precondition_count": len(checks),
        "satisfied_precondition_count": len(checks) - len(failed),
        "failed_precondition_count": len(failed),
        "failed_preconditions": failed,
        "eligible_for_authoritative_governance_query": not failed,
    }


def _execution_status(decision: Mapping[str, Any]) -> tuple[str, bool]:
    value = str(decision.get("decision") or "").upper()
    human = bool(decision.get("requires_human_approval"))
    if value == "ALLOW" and not human:
        return EXECUTION_AUTHORIZED_STATUS, True
    if value == "REVIEW" or human:
        return EXECUTION_REVIEW_STATUS, False
    return EXECUTION_DENIED_STATUS, False


def build_pre_dispatch_revalidation_contract(
    *,
    revalidation_id: str,
    revalidation_sequence: int,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    operation_id: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    readiness_projection: Mapping[str, Any],
    execution_dispatch: Mapping[str, Any],
    dispatch_eligibility: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
    registry_snapshot: Mapping[str, Any],
    static_revalidation: Mapping[str, Any],
    policy_decision: Mapping[str, Any],
    created_at: str,
    governance_resource: Any = None,
) -> Dict[str, Any]:
    dispatch_contract = execution_dispatch["execution_dispatch_contract"]
    target = dispatch_contract["dispatch_target"]
    gov = governance_binding["binding"]["governance_authority"]
    execution_status, authorized = _execution_status(policy_decision)
    gov_action_name, gov_resource_type, gov_resource_value = governance_resource or (
        PRE_DISPATCH_GOVERNANCE_ACTION_NAME, PRE_DISPATCH_GOVERNANCE_RESOURCE_TYPE,
        f"{target['subsystem_id']}:{target['capability_id']}")
    core = {
        "schema_version": PRE_DISPATCH_REVALIDATION_SCHEMA_VERSION,
        "identity": {
            "pre_dispatch_revalidation_id": revalidation_id,
            "revalidation_sequence": int(revalidation_sequence),
            "mission_id": mission_id,
            "execution_dispatch_id": execution_dispatch["execution_dispatch_id"],
            "dispatch_eligibility_id": dispatch_eligibility["dispatch_eligibility_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": execution_dispatch["planned_task_id"],
            "task_key": execution_dispatch["task_key"],
        },
        "source_bindings": {
            "source_state": state["state"],
            "source_state_version": int(state["state_version"]),
            "source_version_sha256": version_vector["version_sha256"],
            "active_plan_sha256": active_plan["canonical_sha256"],
            "task_readiness_projection_id": readiness_projection["projection_id"],
            "task_readiness_projection_sha256": readiness_projection["canonical_sha256"],
            "execution_dispatch_sha256": execution_dispatch["canonical_sha256"],
            "dispatch_eligibility_sha256": dispatch_eligibility["canonical_sha256"],
            "mission_scope_snapshot_id": scope_record["snapshot_id"],
            "mission_scope_sha256": scope_record["canonical_sha256"],
            "governance_binding_version": int(governance_binding["binding_version"]),
            "governance_binding_sha256": governance_binding["canonical_sha256"],
            "registry_id": registry_snapshot["identity"]["registry_id"],
            "registry_version": int(registry_snapshot["identity"]["registry_version"]),
            "registry_sha256": registry_snapshot["integrity"]["canonical_sha256"],
        },
        "dispatch_target": {
            "subsystem_id": target["subsystem_id"],
            "capability_id": target["capability_id"],
            "capability_version": int(target["capability_version"]),
            "logical_target_only": True,
            "runtime_endpoint": None,
            "runtime_availability": "UNKNOWN_NOT_PROBED",
        },
        "static_revalidation": dict(static_revalidation),
        "governance_request": {
            "operation_id": operation_id,
            "authority": PRE_DISPATCH_REVALIDATION_AUTHORITY,
            "authority_component": "GOV-PLANE",
            "action_class": pre_dispatch_action_class(target["capability_id"]),
            "action_name": gov_action_name,
            "resource_type": gov_resource_type,
            "resource_value": gov_resource_value,
            "scope_contract_id": gov["governance_scope_contract_id"],
            "scope_version": int(gov["governance_scope_version"]),
            "policy_set_id": gov["policy_set_id"],
            "requested_by": request["requested_by"],
        },
        "governance_decision": {
            "decision_id": policy_decision["decision_id"],
            "request_id": policy_decision["request_id"],
            "decision": policy_decision["decision"],
            "decision_hash": policy_decision["decision_hash"],
            "reason_codes": list(policy_decision.get("reason_codes") or []),
            "constraints": dict(policy_decision.get("constraints") or {}),
            "requires_human_approval": bool(policy_decision.get("requires_human_approval")),
            "approval_request_id": policy_decision.get("approval_request_id"),
            "policy_set_id": policy_decision["policy_set_id"],
            "policy_version": int(policy_decision["policy_version"]),
            "scope_contract_id": policy_decision["scope_contract_id"],
            "scope_version": int(policy_decision["scope_version"]),
            "valid_from": policy_decision["valid_from"],
            "valid_until": policy_decision["valid_until"],
            "governance_event_id": policy_decision.get("governance_event_id"),
        },
        "execution_authorization": {
            "execution_authorization_status": execution_status,
            "execution_authorization_performed": True,
            "execution_authorized": authorized,
            "eligible_for_execution": authorized,
            "target_action_authorized": authorized,
            "dispatch_authorized": False,
        },
        "semantics": {
            "mode": PRE_DISPATCH_REVALIDATION_MODE,
            "static_preconditions_revalidated": True,
            "authoritative_governance_query_performed": True,
            "fresh_authoritative_policy_decision_bound": True,
            "execution_authorization_performed": True,
            "execution_authorized": authorized,
            "eligible_for_execution": authorized,
            "authorization_is_dispatch": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "dispatch_attempt_started": False,
            "dispatch_performed": False,
            "external_target_network_io_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
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
        "hash_domain": PRE_DISPATCH_REVALIDATION_HASH_DOMAIN,
        **core,
        "canonical_sha256": sha256_hex({"hash_domain": PRE_DISPATCH_REVALIDATION_HASH_DOMAIN, "core": core}),
    }


def verify_pre_dispatch_revalidation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != PRE_DISPATCH_REVALIDATION_SCHEMA_VERSION:
            return False
        if contract.get("hash_domain") != PRE_DISPATCH_REVALIDATION_HASH_DOMAIN:
            return False
        core = {k: v for k, v in contract.items() if k not in {"hash_domain", "canonical_sha256"}}
        if contract.get("canonical_sha256") != sha256_hex({"hash_domain": PRE_DISPATCH_REVALIDATION_HASH_DOMAIN, "core": core}):
            return False
        ident = contract["identity"]
        if not str(ident.get("pre_dispatch_revalidation_id") or "").startswith(PRE_DISPATCH_REVALIDATION_ID_PREFIX):
            return False
        if int(ident.get("revalidation_sequence") or 0) < 1:
            return False
        if not str(ident.get("execution_dispatch_id") or "").startswith("xdispatch-"):
            return False
        if not str(ident.get("dispatch_eligibility_id") or "").startswith("xelig-"):
            return False
        src = contract["source_bindings"]
        for key in (
            "source_version_sha256", "active_plan_sha256", "task_readiness_projection_sha256",
            "execution_dispatch_sha256", "dispatch_eligibility_sha256", "mission_scope_sha256",
            "governance_binding_sha256", "registry_sha256",
        ):
            if not _SHA_RE.match(str(src.get(key) or "")):
                return False
        static = contract["static_revalidation"]
        if static.get("status") != PRE_DISPATCH_STATIC_REVALIDATION_PASSED:
            return False
        checks = static.get("checks") or {}
        if not checks or not all(value is True for value in checks.values()):
            return False
        if int(static.get("failed_precondition_count", -1)) != 0 or list(static.get("failed_preconditions") or []):
            return False
        if static.get("eligible_for_authoritative_governance_query") is not True:
            return False
        gov = contract["governance_decision"]
        if gov.get("decision") not in {"ALLOW", "DENY", "REVIEW"}:
            return False
        if not _SHA_RE.match(str(gov.get("decision_hash") or "")):
            return False
        auth = contract["execution_authorization"]
        expected_status, expected_authorized = _execution_status(gov)
        if auth.get("execution_authorization_status") != expected_status:
            return False
        if auth.get("execution_authorization_performed") is not True:
            return False
        if auth.get("execution_authorized") is not expected_authorized:
            return False
        if auth.get("eligible_for_execution") is not expected_authorized:
            return False
        if auth.get("target_action_authorized") is not expected_authorized:
            return False
        if auth.get("dispatch_authorized") is not False:
            return False
        semantics = contract["semantics"]
        if semantics.get("mode") != PRE_DISPATCH_REVALIDATION_MODE:
            return False
        for key in ("static_preconditions_revalidated", "authoritative_governance_query_performed", "fresh_authoritative_policy_decision_bound", "execution_authorization_performed"):
            if semantics.get(key) is not True:
                return False
        if semantics.get("execution_authorized") is not expected_authorized or semantics.get("eligible_for_execution") is not expected_authorized:
            return False
        for key in (
            "authorization_is_dispatch", "runtime_endpoint_resolution_performed", "runtime_health_probe_performed",
            "resource_assignment_performed", "dispatch_attempt_started", "dispatch_performed",
            "external_target_network_io_performed", "target_action_dispatch_enabled", "target_actuation",
            "version_vector_extension_performed",
        ):
            if semantics.get(key) is not False:
                return False
        return True
    except Exception:
        return False


def canonical_pre_dispatch_revalidation_definition() -> Dict[str, Any]:
    return {
        "schema_version": PRE_DISPATCH_REVALIDATION_SCHEMA_VERSION,
        "mode": PRE_DISPATCH_REVALIDATION_MODE,
        "identity_prefix": PRE_DISPATCH_REVALIDATION_ID_PREFIX,
        "allowed_source_states": sorted(PRE_DISPATCH_REVALIDATION_ALLOWED_STATES),
        "requires_stage351_execution_dispatch_contract": True,
        "requires_stage352_passed_dispatch_eligibility": True,
        "revalidates_stage352_static_preconditions_immediately_before_governance_query": True,
        "requires_current_active_plan": True,
        "requires_current_scope_and_governance_binding": True,
        "governance_authorization_authority": PRE_DISPATCH_REVALIDATION_AUTHORITY,
        "governance_action_class": PRE_DISPATCH_GOVERNANCE_ACTION_CLASS,
        "governance_action_name": PRE_DISPATCH_GOVERNANCE_ACTION_NAME,
        "governance_resource_type": PRE_DISPATCH_GOVERNANCE_RESOURCE_TYPE,
        "governance_query_performed": True,
        "fresh_authoritative_policy_decision_required": True,
        "allow_grants_execution_authorization": True,
        "deny_and_review_fail_closed": True,
        "execution_authorization_is_dispatch": False,
        "append_only_revalidation_history": True,
        "idempotent_operation_recovery_supported": True,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "dispatch_attempt_started": False,
        "dispatch_performed": False,
        "external_target_network_io_performed": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "version_vector_extension_performed": False,
    }
