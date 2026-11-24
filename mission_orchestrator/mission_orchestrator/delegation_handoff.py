from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .delegation_authorization import (
    AUTH_STATUS_AUTHORIZED,
    verify_delegation_authorization_contract,
)
from .errors import MissionValidationError
from .scope_contract import verify_contract as verify_scope_contract
from .task_decomposition import verify_planned_task_contract

DELEGATION_CONTRACT_SCHEMA_VERSION = "apts-canonical-delegation-contract-v1"
HANDOFF_ENVELOPE_SCHEMA_VERSION = "apts-canonical-delegation-handoff-envelope-v1"
DELEGATION_CONTRACT_HASH_DOMAIN = "MISSION_CANONICAL_DELEGATION_CONTRACT_V1"
HANDOFF_ENVELOPE_HASH_DOMAIN = "MISSION_CANONICAL_DELEGATION_HANDOFF_ENVELOPE_V1"
DELEGATION_REQUEST_HASH_DOMAIN = "MISSION_CANONICAL_DELEGATION_REQUEST_V1"
DELEGATION_ID_PREFIX = "deleg-"
HANDOFF_ENVELOPE_ID_PREFIX = "handoff-"
DELEGATION_MODE = "AUTHORIZED_LOGICAL_DELEGATION_WITH_IMMUTABLE_HANDOFF_ENVELOPE_NO_DISPATCH"
HANDOFF_MODE = "IMMUTABLE_CONTEXT_HANDOFF_MATERIALIZED_NOT_TRANSMITTED"
DELEGATION_ALLOWED_STATES = frozenset({"PLANNING", "REPLANNING"})
DELEGATION_STATUS = "DELEGATED"
HANDOFF_STATUS = "MATERIALIZED_NOT_DELIVERED"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_delegation_authorization_id",
    "expected_delegation_authorization_sha256",
    "planned_task_id",
    "delegated_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_pre_delegation_revalidation(
    result: Mapping[str, Any], *, policy_decision_hash: str
) -> bool:
    """Accept only current GSS proof for delegation, never target execution."""
    try:
        return (
            str(result.get("revalidation_id") or "").startswith("greval-")
            and result.get("valid") is True
            and result.get("status") == "VALID"
            and result.get("delegation_authorized") is True
            and result.get("execution_authorized") is False
            and result.get("decision_hash") == policy_decision_hash
            and result.get("authority") == "aptsGSS"
            and result.get("authority_component") == "GOV-PLANE"
        )
    except Exception:
        return False


def new_delegation_id() -> str:
    return f"{DELEGATION_ID_PREFIX}{uuid.uuid4()}"


def new_handoff_envelope_id() -> str:
    return f"{HANDOFF_ENVELOPE_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_delegation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("delegation request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported delegation field(s): "
            + ", ".join(unknown)
            + "; Stage 3.4.6 derives recipient, capability, objective, scope, constraints, outputs, completion criteria, "
              "evidence requirements, and authority exclusively from canonical upstream artifacts. Caller-supplied "
              "recipient, endpoint, payload, handoff, dispatch, ownership, execution, or target-action fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_delegation_authorization_id": _string(payload, "expected_delegation_authorization_id"),
        "planned_task_id": _string(payload, "planned_task_id"),
        "delegated_by": _string(payload, "delegated_by", 128),
    }
    for key in ("idempotency_key", "expected_active_plan_version_record_id", "expected_delegation_authorization_id", "planned_task_id"):
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_delegation_authorization_id"].startswith("dauth-"):
        raise MissionValidationError("expected_delegation_authorization_id must be a canonical dauth-* identifier")
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
        "expected_delegation_authorization_sha256": _sha(payload, "expected_delegation_authorization_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def delegation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": DELEGATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_handoff_envelope(
    *,
    handoff_envelope_id: str,
    delegation_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    planned_task: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    delegation_authorization: Mapping[str, Any],
    pre_delegation_revalidation: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    task_contract = planned_task["task_contract"]
    if not verify_planned_task_contract(task_contract):
        raise MissionValidationError("planned task failed canonical integrity verification")
    scope_contract = scope_record["contract"]
    if not verify_scope_contract(scope_contract):
        raise MissionValidationError("Mission scope contract failed canonical integrity verification")
    auth_contract = delegation_authorization["delegation_authorization_contract"]
    if not verify_delegation_authorization_contract(auth_contract):
        raise MissionValidationError("Stage-3.4.5 delegation authorization failed integrity verification")
    if auth_contract["governance_decision"].get("authorization_status") != AUTH_STATUS_AUTHORIZED:
        raise MissionValidationError("handoff envelope requires an AUTHORIZED Stage-3.4.5 authorization")
    if auth_contract["governance_decision"].get("authorization_granted") is not True:
        raise MissionValidationError("handoff envelope requires authorization_granted=true")
    if not verify_pre_delegation_revalidation(
        pre_delegation_revalidation,
        policy_decision_hash=auth_contract["governance_decision"].get("policy_decision_hash", ""),
    ):
        raise MissionValidationError("handoff envelope requires current non-execution GSS delegation revalidation")

    spec = task_contract["specification"]
    subject = auth_contract["delegation_subject"]
    source = auth_contract["source_bindings"]

    core = {
        "schema_version": HANDOFF_ENVELOPE_SCHEMA_VERSION,
        "identity": {
            "handoff_envelope_id": handoff_envelope_id,
            "delegation_id": delegation_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": planned_task["planned_task_id"],
            "task_key": planned_task["task_key"],
        },
        "sender": {
            "component_id": "APTS-MO01",
            "role": "GLOBAL_MISSION_ORCHESTRATOR",
        },
        "recipient": {
            "subsystem_id": subject["selected_subsystem"],
            "capability_id": subject["selected_capability"],
            "capability_version": int(subject["selected_capability_version"]),
            "logical_recipient_only": True,
            "runtime_endpoint": None,
        },
        "work_context": {
            "task_type": spec["task_type"],
            "objective": dict(spec["objective"]),
            "preconditions": [dict(x) for x in spec["preconditions"]],
            "scope": dict(scope_contract["scope"]),
            "rules_of_engagement": dict(scope_contract["roe"]),
            "constraints": dict(scope_contract["constraints"]),
            "expected_outputs": [dict(x) for x in spec["expected_outputs"]],
            "completion_criteria": [dict(x) for x in spec["success_criteria"]],
            "evidence_requirements": [dict(x) for x in spec["evidence_requirements"]],
            "priority": int(spec["priority"]),
        },
        "authority_context": {
            "delegation_authorization_id": delegation_authorization["delegation_authorization_id"],
            "delegation_authorization_sha256": delegation_authorization["canonical_sha256"],
            "policy_decision_id": auth_contract["governance_decision"]["policy_decision_id"],
            "policy_decision_hash": auth_contract["governance_decision"]["policy_decision_hash"],
            "policy_version": int(auth_contract["governance_decision"]["policy_version"]),
            "authorization_status": auth_contract["governance_decision"]["authorization_status"],
            "authorization_granted": True,
            "authorization_purpose": "PRE_DELEGATION_ONLY",
            "pre_delegation_revalidation": dict(pre_delegation_revalidation),
            "pre_delegation_revalidation_sha256": sha256_hex(dict(pre_delegation_revalidation)),
            "execution_authorized": False,
            "target_action_authorized": False,
            "pre_dispatch_governance_revalidation_required": True,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        },
        "source_artifacts": {
            "planned_task": {
                "planned_task_id": planned_task["planned_task_id"],
                "canonical_sha256": planned_task["canonical_sha256"],
            },
            "active_plan": {
                "plan_version_record_id": active_plan["plan_version_record_id"],
                "plan_version": int(active_plan["plan_version"]),
                "canonical_sha256": active_plan["canonical_sha256"],
            },
            "mission_scope": {
                "snapshot_id": scope_record["snapshot_id"],
                "contract_version": int(scope_record["contract_version"]),
                "canonical_sha256": scope_record["canonical_sha256"],
            },
            "route_decision": {
                "route_decision_id": auth_contract["identity"]["route_decision_id"],
                "canonical_sha256": source["route_decision_sha256"],
            },
            "delegation_authorization": {
                "delegation_authorization_id": delegation_authorization["delegation_authorization_id"],
                "canonical_sha256": delegation_authorization["canonical_sha256"],
            },
            "governance_binding": {
                "binding_version": int(source["governance_binding_version"]),
                "canonical_sha256": source["governance_binding_sha256"],
            },
        },
        "handoff_semantics": {
            "mode": HANDOFF_MODE,
            "handoff_envelope_materialized": True,
            "handoff_context_complete": True,
            "handoff_transmitted": False,
            "handoff_acknowledged": False,
            "ownership_accepted": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "dispatch_performed": False,
            "execution_authorized": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "pre_dispatch_governance_revalidation_required": True,
        },
        "provenance": {
            "delegated_by": request["delegated_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "created_at": created_at,
        },
    }
    digest = sha256_hex({"hash_domain": HANDOFF_ENVELOPE_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": HANDOFF_ENVELOPE_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def build_delegation_contract(
    *,
    delegation_id: str,
    handoff_envelope_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    planned_task: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
    delegation_authorization: Mapping[str, Any],
    pre_delegation_revalidation: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    handoff = build_handoff_envelope(
        handoff_envelope_id=handoff_envelope_id,
        delegation_id=delegation_id,
        mission_id=mission_id,
        request=request,
        active_plan=active_plan,
        planned_task=planned_task,
        scope_record=scope_record,
        delegation_authorization=delegation_authorization,
        pre_delegation_revalidation=pre_delegation_revalidation,
        created_at=created_at,
    )
    auth = delegation_authorization["delegation_authorization_contract"]
    subject = auth["delegation_subject"]
    core = {
        "schema_version": DELEGATION_CONTRACT_SCHEMA_VERSION,
        "identity": {
            "delegation_id": delegation_id,
            "handoff_envelope_id": handoff_envelope_id,
            "mission_id": mission_id,
            "delegation_authorization_id": delegation_authorization["delegation_authorization_id"],
            "route_decision_id": delegation_authorization["route_decision_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": planned_task["planned_task_id"],
            "task_key": planned_task["task_key"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "planned_task_sha256": planned_task["canonical_sha256"],
            "mission_scope_snapshot_id": scope_record["snapshot_id"],
            "mission_scope_version": int(scope_record["contract_version"]),
            "mission_scope_sha256": scope_record["canonical_sha256"],
            "governance_binding_version": int(governance_binding["binding_version"]),
            "governance_binding_sha256": governance_binding["canonical_sha256"],
            "route_decision_sha256": auth["source_bindings"]["route_decision_sha256"],
            "delegation_authorization_sha256": delegation_authorization["canonical_sha256"],
            "policy_decision_id": auth["governance_decision"]["policy_decision_id"],
            "policy_decision_hash": auth["governance_decision"]["policy_decision_hash"],
            "policy_version": int(auth["governance_decision"]["policy_version"]),
        },
        "delegation": {
            "delegation_status": DELEGATION_STATUS,
            "delegation_performed": True,
            "responsibility_transfer_mode": "LOGICAL_CONTROL_PLANE_DELEGATION",
            "delegated_from_component": "APTS-MO01",
            "delegated_to_subsystem": subject["selected_subsystem"],
            "delegated_to_capability": subject["selected_capability"],
            "delegated_to_capability_version": int(subject["selected_capability_version"]),
            "handoff_envelope_status": HANDOFF_STATUS,
            "handoff_envelope_sha256": handoff["integrity"]["canonical_sha256"],
        },
        "handoff_envelope": handoff,
        "semantics": {
            "mode": DELEGATION_MODE,
            "requires_stage345_authorized_decision": True,
            "authorization_reused_as_execution_grant": False,
            "delegation_contract_materialized": True,
            "delegation_performed": True,
            "handoff_envelope_materialized": True,
            "handoff_transmitted": False,
            "handoff_acknowledged": False,
            "ownership_accepted": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "dispatch_performed": False,
            "execution_authorized": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "governance_query_performed": False,
            "pre_dispatch_governance_revalidation_required": True,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "version_vector_extension_performed": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "delegated_by": request["delegated_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "created_at": created_at,
        },
    }
    digest = sha256_hex({"hash_domain": DELEGATION_CONTRACT_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": DELEGATION_CONTRACT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_handoff_envelope(envelope: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in envelope.items() if k != "integrity"}
        ident = envelope["identity"]
        rec = envelope["recipient"]
        auth = envelope["authority_context"]
        sem = envelope["handoff_semantics"]
        return (
            envelope.get("schema_version") == HANDOFF_ENVELOPE_SCHEMA_VERSION
            and envelope["integrity"].get("hash_domain") == HANDOFF_ENVELOPE_HASH_DOMAIN
            and envelope["integrity"].get("canonical_sha256") == sha256_hex({"hash_domain": HANDOFF_ENVELOPE_HASH_DOMAIN, "core": core})
            and str(ident.get("handoff_envelope_id") or "").startswith(HANDOFF_ENVELOPE_ID_PREFIX)
            and str(ident.get("delegation_id") or "").startswith(DELEGATION_ID_PREFIX)
            and str(ident.get("planned_task_id") or "").startswith("ptask-")
            and isinstance(rec.get("subsystem_id"), str) and bool(rec.get("subsystem_id"))
            and isinstance(rec.get("capability_id"), str) and bool(rec.get("capability_id"))
            and rec.get("logical_recipient_only") is True
            and rec.get("runtime_endpoint") is None
            and auth.get("authorization_status") == AUTH_STATUS_AUTHORIZED
            and auth.get("authorization_granted") is True
            and auth.get("execution_authorized") is False
            and auth.get("target_action_authorized") is False
            and auth.get("pre_delegation_revalidation", {}).get("valid") is True
            and auth.get("pre_delegation_revalidation", {}).get("delegation_authorized") is True
            and auth.get("pre_delegation_revalidation", {}).get("execution_authorized") is False
            and auth.get("pre_delegation_revalidation", {}).get("decision_hash") == auth.get("policy_decision_hash")
            and auth.get("pre_delegation_revalidation_sha256") == sha256_hex(auth.get("pre_delegation_revalidation"))
            and auth.get("pre_dispatch_governance_revalidation_required") is True
            and sem.get("mode") == HANDOFF_MODE
            and sem.get("handoff_envelope_materialized") is True
            and sem.get("handoff_context_complete") is True
            and sem.get("handoff_transmitted") is False
            and sem.get("handoff_acknowledged") is False
            and sem.get("ownership_accepted") is False
            and sem.get("runtime_endpoint_resolution_performed") is False
            and sem.get("runtime_health_probe_performed") is False
            and sem.get("resource_assignment_performed") is False
            and sem.get("dispatch_performed") is False
            and sem.get("execution_authorized") is False
            and sem.get("target_action_dispatch_enabled") is False
            and sem.get("target_actuation") is False
            and sem.get("pre_dispatch_governance_revalidation_required") is True
        )
    except Exception:
        return False


def verify_delegation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        ident = contract["identity"]
        src = contract["source_bindings"]
        delegation = contract["delegation"]
        sem = contract["semantics"]
        handoff = contract["handoff_envelope"]
        return (
            contract.get("schema_version") == DELEGATION_CONTRACT_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == DELEGATION_CONTRACT_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256") == sha256_hex({"hash_domain": DELEGATION_CONTRACT_HASH_DOMAIN, "core": core})
            and str(ident.get("delegation_id") or "").startswith(DELEGATION_ID_PREFIX)
            and str(ident.get("handoff_envelope_id") or "").startswith(HANDOFF_ENVELOPE_ID_PREFIX)
            and str(ident.get("delegation_authorization_id") or "").startswith("dauth-")
            and str(ident.get("route_decision_id") or "").startswith("rdec-")
            and str(ident.get("plan_version_record_id") or "").startswith("pver-")
            and str(ident.get("planned_task_id") or "").startswith("ptask-")
            and all(_SHA_RE.match(str(src.get(key) or "")) for key in (
                "source_version_sha256", "active_plan_sha256", "planned_task_sha256",
                "mission_scope_sha256", "governance_binding_sha256", "route_decision_sha256",
                "delegation_authorization_sha256", "policy_decision_hash",
            ))
            and delegation.get("delegation_status") == DELEGATION_STATUS
            and delegation.get("delegation_performed") is True
            and delegation.get("responsibility_transfer_mode") == "LOGICAL_CONTROL_PLANE_DELEGATION"
            and delegation.get("handoff_envelope_status") == HANDOFF_STATUS
            and delegation.get("handoff_envelope_sha256") == handoff["integrity"]["canonical_sha256"]
            and ident.get("handoff_envelope_id") == handoff["identity"]["handoff_envelope_id"]
            and ident.get("delegation_id") == handoff["identity"]["delegation_id"]
            and ident.get("planned_task_id") == handoff["identity"]["planned_task_id"]
            and verify_handoff_envelope(handoff)
            and sem.get("mode") == DELEGATION_MODE
            and sem.get("requires_stage345_authorized_decision") is True
            and sem.get("authorization_reused_as_execution_grant") is False
            and sem.get("delegation_contract_materialized") is True
            and sem.get("delegation_performed") is True
            and sem.get("handoff_envelope_materialized") is True
            and sem.get("handoff_transmitted") is False
            and sem.get("handoff_acknowledged") is False
            and sem.get("ownership_accepted") is False
            and sem.get("runtime_endpoint_resolution_performed") is False
            and sem.get("runtime_health_probe_performed") is False
            and sem.get("resource_assignment_performed") is False
            and sem.get("dispatch_performed") is False
            and sem.get("execution_authorized") is False
            and sem.get("target_action_dispatch_enabled") is False
            and sem.get("target_actuation") is False
            and sem.get("governance_query_performed") is False
            and sem.get("pre_dispatch_governance_revalidation_required") is True
            and sem.get("governance_authorization_authority") == "EXTERNAL_APTS_GSS"
            and sem.get("version_vector_extension_performed") is False
        )
    except Exception:
        return False


def canonical_delegation_definition() -> Dict[str, Any]:
    return {
        "delegation_contract_schema_version": DELEGATION_CONTRACT_SCHEMA_VERSION,
        "handoff_envelope_schema_version": HANDOFF_ENVELOPE_SCHEMA_VERSION,
        "mode": DELEGATION_MODE,
        "handoff_mode": HANDOFF_MODE,
        "delegation_id_prefix": DELEGATION_ID_PREFIX,
        "handoff_envelope_id_prefix": HANDOFF_ENVELOPE_ID_PREFIX,
        "allowed_source_states": sorted(DELEGATION_ALLOWED_STATES),
        "requires_stage345_authorized_decision": True,
        "requires_current_active_plan": True,
        "requires_current_scope_contract": True,
        "requires_current_governance_binding": True,
        "recipient_derived_from_stage344_route": True,
        "work_context_derived_from_planned_task_and_scope": True,
        "delegation_contract_materialized": True,
        "delegation_performed": True,
        "handoff_envelope_materialized": True,
        "handoff_transmitted": False,
        "handoff_acknowledged": False,
        "ownership_accepted": False,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "dispatch_performed": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "governance_query_performed": False,
        "pre_dispatch_governance_revalidation_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "version_vector_extension_performed": False,
    }
