from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .dispatch_eligibility import DISPATCH_ELIGIBILITY_GATE_PASSED, verify_dispatch_eligibility_contract
from .errors import MissionValidationError
from .execution_dispatch import verify_execution_dispatch_contract
from .pre_dispatch_governance import EXECUTION_AUTHORIZED_STATUS, verify_pre_dispatch_revalidation_contract

EXECUTION_ATTEMPT_SCHEMA_VERSION = "apts-idempotent-dispatch-execution-attempt-v1"
EXECUTION_ATTEMPT_HASH_DOMAIN = "MISSION_IDEMPOTENT_DISPATCH_EXECUTION_ATTEMPT_V1"
EXECUTION_ATTEMPT_REQUEST_HASH_DOMAIN = "MISSION_IDEMPOTENT_DISPATCH_EXECUTION_ATTEMPT_REQUEST_V1"
EXECUTION_ATTEMPT_ID_PREFIX = "xattempt-"
DISPATCH_ENVELOPE_ID_PREFIX = "xenv-"
EXECUTION_ATTEMPT_MODE = "IDEMPOTENT_DURABLE_DISPATCH_COMMIT_WITH_STABLE_EXECUTION_ATTEMPT_IDENTITY_PENDING_DELIVERY"
EXECUTION_ATTEMPT_ALLOWED_STATES = frozenset({"RUNNING"})
DISPATCH_COMMIT_STATUS = "COMMITTED_IDEMPOTENT_PENDING_DELIVERY"
EXECUTION_ATTEMPT_STATUS = "CREATED_NOT_DELIVERED"
EXECUTION_ATTEMPT_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_IDEMPOTENT_DISPATCH_COMMIT"

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
    "expected_pre_dispatch_revalidation_id",
    "expected_pre_dispatch_revalidation_sha256",
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


def new_execution_attempt_id() -> str:
    return f"{EXECUTION_ATTEMPT_ID_PREFIX}{uuid.uuid4()}"


def new_dispatch_envelope_id() -> str:
    return f"{DISPATCH_ENVELOPE_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_execution_attempt_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("execution-attempt request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported execution attempt field(s): " + ", ".join(unknown)
            + "; Stage 3.5.4 accepts only canonical concurrency/provenance references and idempotency metadata. "
              "Caller-supplied attempt/envelope identity, runtime endpoint, health result, resource assignment, execution payload, "
              "delivery/acknowledgement result, execution-start result, target-action result, or actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_dispatch_id": _string(payload, "expected_execution_dispatch_id"),
        "expected_dispatch_eligibility_id": _string(payload, "expected_dispatch_eligibility_id"),
        "expected_pre_dispatch_revalidation_id": _string(payload, "expected_pre_dispatch_revalidation_id"),
        "created_by": _string(payload, "created_by", 128),
    }
    expected_prefixes = {
        "expected_active_plan_version_record_id": "pver-",
        "expected_execution_dispatch_id": "xdispatch-",
        "expected_dispatch_eligibility_id": "xelig-",
        "expected_pre_dispatch_revalidation_id": "xreval-",
    }
    for key in ("idempotency_key", *expected_prefixes.keys()):
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    for key, prefix in expected_prefixes.items():
        if not values[key].startswith(prefix):
            raise MissionValidationError(f"{key} must be a canonical {prefix}* identifier")
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
        "expected_pre_dispatch_revalidation_sha256": _sha(payload, "expected_pre_dispatch_revalidation_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def execution_attempt_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": EXECUTION_ATTEMPT_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_execution_attempt_contract(
    *,
    execution_attempt_id: str,
    dispatch_envelope_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    execution_dispatch: Mapping[str, Any],
    dispatch_eligibility: Mapping[str, Any],
    pre_dispatch_revalidation: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    dispatch_contract = execution_dispatch["execution_dispatch_contract"]
    eligibility_contract = dispatch_eligibility["dispatch_eligibility_contract"]
    revalidation_contract = pre_dispatch_revalidation["pre_dispatch_revalidation_contract"]
    if not verify_execution_dispatch_contract(dispatch_contract):
        raise MissionValidationError("Stage-3.5.1 execution dispatch failed integrity verification")
    if not verify_dispatch_eligibility_contract(eligibility_contract):
        raise MissionValidationError("Stage-3.5.2 dispatch eligibility failed integrity verification")
    if not verify_pre_dispatch_revalidation_contract(revalidation_contract):
        raise MissionValidationError("Stage-3.5.3 pre-dispatch Governance revalidation failed integrity verification")
    if dispatch_eligibility.get("gate_result") != DISPATCH_ELIGIBILITY_GATE_PASSED:
        raise MissionValidationError("Stage-3.5.2 dispatch eligibility is not PASSED")
    if pre_dispatch_revalidation.get("governance_decision") != "ALLOW":
        raise MissionValidationError("latest Stage-3.5.3 Governance decision must be ALLOW")
    if pre_dispatch_revalidation.get("execution_authorization_status") != EXECUTION_AUTHORIZED_STATUS or not bool(pre_dispatch_revalidation.get("execution_authorized")):
        raise MissionValidationError("latest Stage-3.5.3 revalidation does not authorize execution")

    target = dispatch_contract["dispatch_target"]
    work = dispatch_contract["work_contract"]["work_context"]
    core: Dict[str, Any] = {
        "schema_version": EXECUTION_ATTEMPT_SCHEMA_VERSION,
        "identity": {
            "execution_attempt_id": execution_attempt_id,
            "dispatch_envelope_id": dispatch_envelope_id,
            "attempt_ordinal": 1,
            "mission_id": mission_id,
            "execution_dispatch_id": execution_dispatch["execution_dispatch_id"],
            "dispatch_eligibility_id": dispatch_eligibility["dispatch_eligibility_id"],
            "pre_dispatch_revalidation_id": pre_dispatch_revalidation["pre_dispatch_revalidation_id"],
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
            "execution_dispatch_sha256": execution_dispatch["canonical_sha256"],
            "dispatch_eligibility_sha256": dispatch_eligibility["canonical_sha256"],
            "pre_dispatch_revalidation_sha256": pre_dispatch_revalidation["canonical_sha256"],
            "policy_decision_id": pre_dispatch_revalidation["policy_decision_id"],
            "policy_decision_hash": pre_dispatch_revalidation["policy_decision_hash"],
            "policy_version": int(pre_dispatch_revalidation["policy_version"]),
        },
        "dispatch_envelope": {
            "dispatch_envelope_id": dispatch_envelope_id,
            "target": {
                "subsystem_id": target["subsystem_id"],
                "capability_id": target["capability_id"],
                "capability_version": int(target["capability_version"]),
                "logical_target_only": True,
                "runtime_endpoint": None,
            },
            "work_context": dict(work),
            "authorization": {
                "pre_dispatch_revalidation_id": pre_dispatch_revalidation["pre_dispatch_revalidation_id"],
                "governance_decision": "ALLOW",
                "execution_authorization_status": EXECUTION_AUTHORIZED_STATUS,
                "execution_authorized": True,
            },
            "delivery": {
                "delivery_performed": False,
                "delivery_acknowledged": False,
                "execution_started": False,
            },
        },
        "dispatch_commit": {
            "dispatch_commit_status": DISPATCH_COMMIT_STATUS,
            "idempotency_key": request["idempotency_key"],
            "request_sha256": request_sha256,
            "duplicate_dispatch_suppressed": True,
            "duplicate_execution_attempt_suppressed": True,
        },
        "execution_attempt": {
            "execution_attempt_status": EXECUTION_ATTEMPT_STATUS,
            "attempt_ordinal": 1,
            "execution_authorized": True,
            "eligible_for_delivery": True,
            "eligible_for_execution_start": False,
        },
        "semantics": {
            "mode": EXECUTION_ATTEMPT_MODE,
            "durable_dispatch_commit_performed": True,
            "idempotent_dispatch_identity_materialized": True,
            "stable_execution_attempt_identity_materialized": True,
            "immutable_dispatch_envelope_materialized": True,
            "authoritative_governance_query_performed": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "target_delivery_performed": False,
            "delivery_acknowledgement_performed": False,
            "execution_started": False,
            "external_target_network_io_performed": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
            "next_stage": "3.5.5",
        },
        "provenance": {
            "created_by": request["created_by"],
            "created_at": created_at,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
        },
    }
    digest = sha256_hex({"hash_domain": EXECUTION_ATTEMPT_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_execution_attempt_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        semantics = contract["semantics"]
        return (
            contract["schema_version"] == EXECUTION_ATTEMPT_SCHEMA_VERSION
            and str(identity["execution_attempt_id"]).startswith(EXECUTION_ATTEMPT_ID_PREFIX)
            and str(identity["dispatch_envelope_id"]).startswith(DISPATCH_ENVELOPE_ID_PREFIX)
            and int(identity["attempt_ordinal"]) == 1
            and contract["dispatch_commit"]["dispatch_commit_status"] == DISPATCH_COMMIT_STATUS
            and contract["execution_attempt"]["execution_attempt_status"] == EXECUTION_ATTEMPT_STATUS
            and contract["execution_attempt"]["execution_authorized"] is True
            and semantics["target_delivery_performed"] is False
            and semantics["execution_started"] is False
            and semantics["target_actuation"] is False
            and digest == sha256_hex({"hash_domain": EXECUTION_ATTEMPT_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_execution_attempt_definition() -> Dict[str, Any]:
    return {
        "schema_version": EXECUTION_ATTEMPT_SCHEMA_VERSION,
        "identity_prefix": EXECUTION_ATTEMPT_ID_PREFIX,
        "dispatch_envelope_identity_prefix": DISPATCH_ENVELOPE_ID_PREFIX,
        "mode": EXECUTION_ATTEMPT_MODE,
        "authority": EXECUTION_ATTEMPT_AUTHORITY,
        "allowed_source_states": sorted(EXECUTION_ATTEMPT_ALLOWED_STATES),
        "requires_stage351_execution_dispatch_contract": True,
        "requires_stage352_passed_dispatch_eligibility": True,
        "requires_latest_stage353_allow_execution_authorization": True,
        "one_canonical_initial_attempt_per_execution_dispatch": True,
        "idempotency_key_replay_returns_same_attempt_identity": True,
        "duplicate_dispatch_suppressed": True,
        "duplicate_execution_attempt_suppressed": True,
        "durable_dispatch_commit_performed": True,
        "immutable_dispatch_envelope_materialized": True,
        "governance_query_performed": False,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "target_delivery_performed": False,
        "delivery_acknowledgement_performed": False,
        "execution_started": False,
        "external_target_network_io_performed": False,
        "target_action_dispatch_performed": False,
        "target_actuation": False,
        "next_stage": "3.5.5",
    }
