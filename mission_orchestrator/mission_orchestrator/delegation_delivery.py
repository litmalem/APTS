from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .delegation_handoff import verify_delegation_contract, verify_handoff_envelope
from .errors import MissionValidationError

DELIVERY_RECEIPT_SCHEMA_VERSION = "apts-canonical-delegation-delivery-acknowledgement-ownership-v1"
DELIVERY_RECEIPT_HASH_DOMAIN = "MISSION_CANONICAL_DELEGATION_DELIVERY_ACK_OWNERSHIP_V1"
DELIVERY_REQUEST_HASH_DOMAIN = "MISSION_CANONICAL_DELEGATION_DELIVERY_REQUEST_V1"
DELIVERY_RECEIPT_ID_PREFIX = "drecv-"
DELIVERY_MODE = "CONTROL_PLANE_HANDOFF_DELIVERY_WITH_RECIPIENT_ACK_AND_OWNERSHIP_ACCEPTANCE_NO_DISPATCH"
DELIVERY_CHANNEL = "CANONICAL_RECIPIENT_CONTROL_PLANE_INBOX"
DELIVERY_STATUS = "DELIVERED"
ACKNOWLEDGEMENT_STATUS = "ACKNOWLEDGED"
OWNERSHIP_STATUS = "ACCEPTED"
OWNERSHIP_SCOPE = "DELEGATED_TASK_CONTROL_PLANE_RESPONSIBILITY_ONLY"
DELIVERY_ALLOWED_STATES = frozenset({"PLANNING", "REPLANNING"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_delegation_id",
    "expected_delegation_sha256",
    "expected_handoff_envelope_id",
    "expected_handoff_envelope_sha256",
    "recipient_subsystem_id",
    "recipient_capability_id",
    "acknowledged_by",
    "ownership_accepted_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_delivery_receipt_id() -> str:
    return f"{DELIVERY_RECEIPT_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_delivery_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("delegation delivery request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported delegation delivery field(s): "
            + ", ".join(unknown)
            + "; Stage 3.4.7 accepts only canonical provenance/concurrency references and recipient acknowledgement identity. "
              "Runtime endpoint, worker/resource assignment, dispatch instruction, execution authorization, command payload, "
              "or target-action fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_delegation_id": _string(payload, "expected_delegation_id"),
        "expected_handoff_envelope_id": _string(payload, "expected_handoff_envelope_id"),
        "recipient_subsystem_id": _string(payload, "recipient_subsystem_id", 64),
        "recipient_capability_id": _string(payload, "recipient_capability_id", 160),
        "acknowledged_by": _string(payload, "acknowledged_by", 128),
        "ownership_accepted_by": _string(payload, "ownership_accepted_by", 128),
    }
    for key in (
        "idempotency_key",
        "expected_active_plan_version_record_id",
        "expected_delegation_id",
        "expected_handoff_envelope_id",
        "recipient_subsystem_id",
        "recipient_capability_id",
    ):
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_delegation_id"].startswith("deleg-"):
        raise MissionValidationError("expected_delegation_id must be a canonical deleg-* identifier")
    if not values["expected_handoff_envelope_id"].startswith("handoff-"):
        raise MissionValidationError("expected_handoff_envelope_id must be a canonical handoff-* identifier")

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
        "expected_delegation_sha256": _sha(payload, "expected_delegation_sha256"),
        "expected_handoff_envelope_sha256": _sha(payload, "expected_handoff_envelope_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def delivery_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": DELIVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_delivery_receipt_contract(
    *,
    delivery_receipt_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    delegation: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    delegation_contract = delegation["delegation_contract"]
    if not verify_delegation_contract(delegation_contract):
        raise MissionValidationError("Stage-3.4.6 delegation contract failed integrity verification")
    handoff = delegation_contract["handoff_envelope"]
    if not verify_handoff_envelope(handoff):
        raise MissionValidationError("Stage-3.4.6 handoff envelope failed integrity verification")

    recipient = handoff["recipient"]
    if request["recipient_subsystem_id"] != recipient["subsystem_id"]:
        raise MissionValidationError("recipient_subsystem_id does not match canonical Stage-3.4.6 handoff recipient")
    if request["recipient_capability_id"] != recipient["capability_id"]:
        raise MissionValidationError("recipient_capability_id does not match canonical Stage-3.4.6 handoff capability")

    core = {
        "schema_version": DELIVERY_RECEIPT_SCHEMA_VERSION,
        "identity": {
            "delivery_receipt_id": delivery_receipt_id,
            "mission_id": mission_id,
            "delegation_id": delegation["delegation_id"],
            "handoff_envelope_id": delegation["handoff_envelope_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": delegation["planned_task_id"],
            "task_key": delegation["task_key"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "delegation_sha256": delegation["canonical_sha256"],
            "handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
            "delegation_authorization_id": delegation["delegation_authorization_id"],
            "route_decision_id": delegation["route_decision_id"],
        },
        "delivery": {
            "delivery_status": DELIVERY_STATUS,
            "delivery_channel": DELIVERY_CHANNEL,
            "handoff_transmitted": True,
            "logical_recipient_only": True,
            "recipient_subsystem_id": recipient["subsystem_id"],
            "recipient_capability_id": recipient["capability_id"],
            "recipient_capability_version": int(recipient["capability_version"]),
            "runtime_endpoint": None,
            "runtime_endpoint_resolution_performed": False,
            "external_network_io_performed": False,
        },
        "acknowledgement": {
            "acknowledgement_status": ACKNOWLEDGEMENT_STATUS,
            "handoff_acknowledged": True,
            "acknowledged_by": request["acknowledged_by"],
            "acknowledged_handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
            "acknowledged_at": created_at,
        },
        "ownership": {
            "ownership_status": OWNERSHIP_STATUS,
            "ownership_accepted": True,
            "ownership_scope": OWNERSHIP_SCOPE,
            "ownership_accepted_by": request["ownership_accepted_by"],
            "ownership_accepted_at": created_at,
            "execution_authority_transferred": False,
            "target_action_authority_transferred": False,
        },
        "semantics": {
            "mode": DELIVERY_MODE,
            "requires_stage346_immutable_delegation": True,
            "handoff_envelope_materialized": True,
            "handoff_transmitted": True,
            "handoff_acknowledged": True,
            "ownership_accepted": True,
            "delivery_is_control_plane_handoff_only": True,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "dispatch_performed": False,
            "execution_authorized": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "governance_query_performed": False,
            "authorization_reused_as_execution_grant": False,
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
    digest = sha256_hex({"hash_domain": DELIVERY_RECEIPT_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": DELIVERY_RECEIPT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_delivery_receipt_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        ident = contract["identity"]
        source = contract["source_bindings"]
        delivery = contract["delivery"]
        acknowledgement = contract["acknowledgement"]
        ownership = contract["ownership"]
        sem = contract["semantics"]
        return (
            contract.get("schema_version") == DELIVERY_RECEIPT_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == DELIVERY_RECEIPT_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256")
            == sha256_hex({"hash_domain": DELIVERY_RECEIPT_HASH_DOMAIN, "core": core})
            and str(ident.get("delivery_receipt_id") or "").startswith(DELIVERY_RECEIPT_ID_PREFIX)
            and str(ident.get("delegation_id") or "").startswith("deleg-")
            and str(ident.get("handoff_envelope_id") or "").startswith("handoff-")
            and str(ident.get("plan_version_record_id") or "").startswith("pver-")
            and str(ident.get("planned_task_id") or "").startswith("ptask-")
            and all(_SHA_RE.match(str(source.get(key) or "")) for key in (
                "source_version_sha256", "active_plan_sha256", "delegation_sha256", "handoff_envelope_sha256"
            ))
            and delivery.get("delivery_status") == DELIVERY_STATUS
            and delivery.get("delivery_channel") == DELIVERY_CHANNEL
            and delivery.get("handoff_transmitted") is True
            and delivery.get("logical_recipient_only") is True
            and delivery.get("runtime_endpoint") is None
            and delivery.get("runtime_endpoint_resolution_performed") is False
            and delivery.get("external_network_io_performed") is False
            and acknowledgement.get("acknowledgement_status") == ACKNOWLEDGEMENT_STATUS
            and acknowledgement.get("handoff_acknowledged") is True
            and acknowledgement.get("acknowledged_handoff_envelope_sha256") == source.get("handoff_envelope_sha256")
            and ownership.get("ownership_status") == OWNERSHIP_STATUS
            and ownership.get("ownership_accepted") is True
            and ownership.get("ownership_scope") == OWNERSHIP_SCOPE
            and ownership.get("execution_authority_transferred") is False
            and ownership.get("target_action_authority_transferred") is False
            and sem.get("mode") == DELIVERY_MODE
            and sem.get("requires_stage346_immutable_delegation") is True
            and sem.get("handoff_envelope_materialized") is True
            and sem.get("handoff_transmitted") is True
            and sem.get("handoff_acknowledged") is True
            and sem.get("ownership_accepted") is True
            and sem.get("delivery_is_control_plane_handoff_only") is True
            and sem.get("runtime_endpoint_resolution_performed") is False
            and sem.get("runtime_health_probe_performed") is False
            and sem.get("resource_assignment_performed") is False
            and sem.get("dispatch_performed") is False
            and sem.get("execution_authorized") is False
            and sem.get("target_action_dispatch_enabled") is False
            and sem.get("target_actuation") is False
            and sem.get("governance_query_performed") is False
            and sem.get("authorization_reused_as_execution_grant") is False
            and sem.get("pre_dispatch_governance_revalidation_required") is True
            and sem.get("version_vector_extension_performed") is False
        )
    except Exception:
        return False


def canonical_delivery_definition() -> Dict[str, Any]:
    return {
        "schema_version": DELIVERY_RECEIPT_SCHEMA_VERSION,
        "mode": DELIVERY_MODE,
        "delivery_channel": DELIVERY_CHANNEL,
        "delivery_receipt_id_prefix": DELIVERY_RECEIPT_ID_PREFIX,
        "allowed_source_states": sorted(DELIVERY_ALLOWED_STATES),
        "requires_stage346_immutable_delegation": True,
        "requires_current_active_plan": True,
        "requires_current_mission_state_and_version_vector": True,
        "requires_exact_handoff_envelope_hash": True,
        "recipient_identity_must_match_canonical_handoff": True,
        "delivery_status": DELIVERY_STATUS,
        "acknowledgement_status": ACKNOWLEDGEMENT_STATUS,
        "ownership_status": OWNERSHIP_STATUS,
        "ownership_scope": OWNERSHIP_SCOPE,
        "handoff_envelope_materialized": True,
        "handoff_transmitted": True,
        "handoff_acknowledged": True,
        "ownership_accepted": True,
        "delivery_is_control_plane_handoff_only": True,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "dispatch_performed": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "governance_query_performed": False,
        "authorization_reused_as_execution_grant": False,
        "pre_dispatch_governance_revalidation_required": True,
        "version_vector_extension_performed": False,
    }
