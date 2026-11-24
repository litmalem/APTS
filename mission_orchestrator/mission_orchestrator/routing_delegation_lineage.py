from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError

ROUTING_DELEGATION_EVENT_LINEAGE_SCHEMA_VERSION = "apts-routing-delegation-event-lineage-v1"
ROUTING_DELEGATION_EVENT_REPLAY_SCHEMA_VERSION = "apts-routing-delegation-event-replay-v1"
ROUTING_DELEGATION_RECOVERY_CHECKPOINT_SCHEMA_VERSION = "apts-routing-delegation-recovery-checkpoint-v1"
ROUTING_DELEGATION_RECOVERY_CHECKPOINT_HASH_DOMAIN = "MISSION_ROUTING_DELEGATION_RECOVERY_CHECKPOINT_V1"
ROUTING_DELEGATION_RECOVERY_REQUEST_HASH_DOMAIN = "MISSION_ROUTING_DELEGATION_RECOVERY_REQUEST_V1"
ROUTING_DELEGATION_REPLAY_HASH_DOMAIN = "MISSION_ROUTING_DELEGATION_EVENT_REPLAY_V1"
ROUTING_DELEGATION_RECOVERY_CHECKPOINT_ID_PREFIX = "rdrecover-"
ROUTING_DELEGATION_EVENT_LINEAGE_MODE = "CANONICAL_ROUTING_DELEGATION_EVENT_SUBCHAIN_WITH_ARTIFACT_CAUSATION_BINDINGS"
ROUTING_DELEGATION_REPLAY_MODE = "READ_ONLY_DETERMINISTIC_ORDERED_ROUTING_DELEGATION_REPLAY_NO_SIDE_EFFECTS"
ROUTING_DELEGATION_RECOVERY_MODE = "DURABLE_ROUTING_DELEGATION_ARTIFACT_RECONSTRUCTION_NO_REROUTE_NO_REDELIVERY_NO_EXTERNAL_READS"
ROUTING_DELEGATION_RECOVERY_EVENT_TYPE = "MISSION_ROUTING_DELEGATION_RECOVERY_CHECKPOINTED"

ROUTING_DELEGATION_EVENT_TYPES = (
    "MISSION_TASK_ROUTING_CANDIDATES_RESOLVED",
    "MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED",
    "MISSION_TASK_ROUTE_DECISION_RECORDED",
    "MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED",
    "MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED",
    "MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED",
    "MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED",
    ROUTING_DELEGATION_RECOVERY_EVENT_TYPE,
)

_ARTIFACT_ID_FIELDS = {
    "MISSION_TASK_ROUTING_CANDIDATES_RESOLVED": "routing_intent_id",
    "MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED": "eligibility_gate_id",
    "MISSION_TASK_ROUTE_DECISION_RECORDED": "route_decision_id",
    "MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED": "delegation_authorization_id",
    "MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED": "delegation_id",
    "MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED": "delivery_receipt_id",
    "MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED": "recovery_control_id",
    ROUTING_DELEGATION_RECOVERY_EVENT_TYPE: "checkpoint_id",
}

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_delivery_receipt_id",
    "expected_delivery_receipt_sha256",
    "expected_delegation_id",
    "expected_delegation_sha256",
    "expected_route_decision_id",
    "expected_route_decision_sha256",
    "expected_recovery_control_count",
    "expected_routing_delegation_event_count",
    "expected_routing_delegation_event_tip_sha256",
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


def new_routing_delegation_recovery_checkpoint_id() -> str:
    return f"{ROUTING_DELEGATION_RECOVERY_CHECKPOINT_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _non_negative_int(payload: Mapping[str, Any], key: str) -> int:
    raw = payload.get(key)
    if isinstance(raw, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 0:
        raise MissionValidationError(f"{key} must be >= 0")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = _non_negative_int(payload, key)
    if value < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return value


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _require_string(payload, key, 64).lower()
    if not _SHA256_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_routing_delegation_recovery_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("routing/delegation recovery checkpoint request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported routing/delegation recovery checkpoint field(s): " + ", ".join(unknown)
            + "; Stage 3.4.9 reconstructs exclusively from canonical durable routing/delegation artifacts and forbids caller-supplied route candidates, authorization decisions, handoff envelopes, ownership state, recovery-control content, dispatch commands, or execution content"
        )
    idem = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idem):
        raise MissionValidationError("idempotency_key contains unsupported characters")
    for key in ("expected_delivery_receipt_id", "expected_delegation_id", "expected_route_decision_id"):
        value = _require_string(payload, key)
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
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
        "expected_delivery_receipt_id": _require_string(payload, "expected_delivery_receipt_id"),
        "expected_delivery_receipt_sha256": _sha(payload, "expected_delivery_receipt_sha256"),
        "expected_delegation_id": _require_string(payload, "expected_delegation_id"),
        "expected_delegation_sha256": _sha(payload, "expected_delegation_sha256"),
        "expected_route_decision_id": _require_string(payload, "expected_route_decision_id"),
        "expected_route_decision_sha256": _sha(payload, "expected_route_decision_sha256"),
        "expected_recovery_control_count": _non_negative_int(payload, "expected_recovery_control_count"),
        "expected_routing_delegation_event_count": _positive_int(payload, "expected_routing_delegation_event_count"),
        "expected_routing_delegation_event_tip_sha256": _sha(payload, "expected_routing_delegation_event_tip_sha256"),
        "created_by": _require_string(payload, "created_by"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def routing_delegation_recovery_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": ROUTING_DELEGATION_RECOVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def is_routing_delegation_event(event: Mapping[str, Any]) -> bool:
    return str(event.get("event_type") or "") in ROUTING_DELEGATION_EVENT_TYPES


def build_routing_delegation_event_replay(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    selected = [dict(event) for event in events if is_routing_delegation_event(event)]
    replay_events = []
    for seq, event in enumerate(selected, 1):
        payload = dict(event.get("payload") or {})
        event_type = str(event.get("event_type") or "")
        artifact_id_field = _ARTIFACT_ID_FIELDS.get(event_type)
        replay_events.append({
            "replay_sequence": seq,
            "event_id": event.get("event_id"),
            "event_type": event_type,
            "causation_id": event.get("causation_id"),
            "state_version": event.get("state_version"),
            "plan_version": event.get("plan_version"),
            "policy_version": event.get("policy_version"),
            "artifact_id": None if artifact_id_field is None else payload.get(artifact_id_field),
            "event_sha256": event.get("canonical_sha256"),
            "previous_event_sha256": event.get("previous_event_sha256"),
            "occurred_at": event.get("occurred_at"),
        })
    replay_core = {
        "schema_version": ROUTING_DELEGATION_EVENT_REPLAY_SCHEMA_VERSION,
        "mode": ROUTING_DELEGATION_REPLAY_MODE,
        "routing_delegation_event_count": len(replay_events),
        "events": replay_events,
    }
    replay_sha = sha256_hex({"hash_domain": ROUTING_DELEGATION_REPLAY_HASH_DOMAIN, "replay": replay_core})
    tip = None if not selected else selected[-1]
    return {
        **replay_core,
        "replay_sha256": replay_sha,
        "routing_delegation_event_tip_event_id": None if tip is None else tip.get("event_id"),
        "routing_delegation_event_tip_sha256": None if tip is None else tip.get("canonical_sha256"),
        "read_only": True,
        "side_effects_performed": False,
    }


def _artifact_ref(row: Mapping[str, Any], id_key: str) -> Dict[str, Any]:
    return {
        "artifact_id": row[id_key],
        "canonical_sha256": row["canonical_sha256"],
    }


def build_routing_delegation_recovery_checkpoint_contract(
    *,
    checkpoint_id: str,
    checkpoint_version: int,
    mission_id: str,
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    routing_intent: Mapping[str, Any],
    eligibility_gate: Mapping[str, Any],
    route_decision: Mapping[str, Any],
    delegation_authorization: Mapping[str, Any],
    delegation: Mapping[str, Any],
    delivery: Mapping[str, Any],
    recovery_controls: Sequence[Mapping[str, Any]],
    replay: Mapping[str, Any],
    created_by: str,
    reason: str | None,
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    controls = [
        {
            "recovery_control_id": row["recovery_control_id"],
            "control_sequence": int(row["control_sequence"]),
            "control_action": row["control_action"],
            "control_outcome": row["control_outcome"],
            "conflict_status": row["conflict_status"],
            "canonical_sha256": row["canonical_sha256"],
        }
        for row in recovery_controls
    ]
    latest_control = None if not controls else controls[-1]
    route_contract = route_decision["route_selection_contract"]
    route_core = route_contract["route_decision"]
    delivery_contract = delivery["delivery_receipt_contract"]
    recipient = delivery_contract["delivery"]
    ownership = delivery_contract["ownership"]
    recovery_state = {
        "plan_version_record_id": delivery["plan_version_record_id"],
        "plan_version": int(delivery["plan_version"]),
        "planned_task_id": delivery["planned_task_id"],
        "task_key": delivery["task_key"],
        "route_selected": bool(route_core.get("route_selected")),
        "selected_subsystem": route_decision.get("selected_subsystem"),
        "selected_capability": route_decision.get("selected_capability"),
        "authorization_status": delegation_authorization["authorization_status"],
        "authorization_granted": bool(delegation_authorization["authorization_granted"]),
        "delegation_status": delegation["delegation_status"],
        "delivery_status": delivery["delivery_status"],
        "acknowledgement_status": delivery["acknowledgement_status"],
        "ownership_status": delivery["ownership_status"],
        "current_owner": {
            "subsystem_id": recipient["recipient_subsystem_id"],
            "capability_id": recipient["recipient_capability_id"],
            "capability_version": int(recipient["recipient_capability_version"]),
            "ownership_accepted_by": ownership["ownership_accepted_by"],
        },
        "recovery_control_count": len(controls),
        "latest_recovery_control": latest_control,
        "next_recovery_control_sequence": len(controls) + 1,
        "recovery_controls": controls,
        "reconstructed_from_durable_artifacts": True,
    }
    core = {
        "schema_version": ROUTING_DELEGATION_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "checkpoint": {
            "checkpoint_id": checkpoint_id,
            "checkpoint_version": int(checkpoint_version),
            "mission_id": mission_id,
            "created_by": created_by,
            "created_at": created_at,
            "reason": reason,
            "metadata": dict(metadata),
        },
        "source_bindings": {
            "request_sha256": request_sha256,
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "routing_intent": _artifact_ref(routing_intent, "routing_intent_id"),
            "eligibility_gate": _artifact_ref(eligibility_gate, "eligibility_gate_id"),
            "route_decision": _artifact_ref(route_decision, "route_decision_id"),
            "delegation_authorization": _artifact_ref(delegation_authorization, "delegation_authorization_id"),
            "delegation": _artifact_ref(delegation, "delegation_id"),
            "handoff_envelope_id": delegation["handoff_envelope_id"],
            "handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
            "delivery": _artifact_ref(delivery, "delivery_receipt_id"),
            "policy_decision_id": delegation_authorization["policy_decision_id"],
            "policy_decision_hash": delegation_authorization["policy_decision_hash"],
            "policy_version": int(delegation_authorization["policy_version"]),
            "recovery_control_count": len(controls),
            "recovery_control_tip_id": None if latest_control is None else latest_control["recovery_control_id"],
            "recovery_control_tip_sha256": None if latest_control is None else latest_control["canonical_sha256"],
            "source_routing_delegation_event_count": int(replay["routing_delegation_event_count"]),
            "source_routing_delegation_event_tip_event_id": replay.get("routing_delegation_event_tip_event_id"),
            "source_routing_delegation_event_tip_sha256": replay.get("routing_delegation_event_tip_sha256"),
            "source_replay_sha256": replay["replay_sha256"],
        },
        "recovery_state": recovery_state,
        "replay": {
            "schema_version": replay["schema_version"],
            "mode": replay["mode"],
            "routing_delegation_event_count": int(replay["routing_delegation_event_count"]),
            "routing_delegation_event_tip_event_id": replay.get("routing_delegation_event_tip_event_id"),
            "routing_delegation_event_tip_sha256": replay.get("routing_delegation_event_tip_sha256"),
            "replay_sha256": replay["replay_sha256"],
            "read_only": True,
            "side_effects_performed": False,
        },
        "authority_boundaries": {
            "replay_is_execution": False,
            "recovery_is_authorization": False,
            "recovery_is_routing": False,
            "recovery_is_redelivery": False,
            "recovery_is_ownership_transfer": False,
            "governance_query_performed": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "external_network_io_performed": False,
            "dispatch_performed": False,
            "execution_authorized": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
    }
    digest = sha256_hex({"hash_domain": ROUTING_DELEGATION_RECOVERY_CHECKPOINT_HASH_DOMAIN, "checkpoint": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": ROUTING_DELEGATION_RECOVERY_CHECKPOINT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_routing_delegation_recovery_checkpoint_contract(contract: Mapping[str, Any]) -> bool:
    try:
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        return (
            contract.get("schema_version") == ROUTING_DELEGATION_RECOVERY_CHECKPOINT_SCHEMA_VERSION
            and integrity.get("hash_domain") == ROUTING_DELEGATION_RECOVERY_CHECKPOINT_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": ROUTING_DELEGATION_RECOVERY_CHECKPOINT_HASH_DOMAIN, "checkpoint": core})
            and contract["replay"]["read_only"] is True
            and contract["replay"]["side_effects_performed"] is False
            and contract["authority_boundaries"]["replay_is_execution"] is False
            and contract["authority_boundaries"]["recovery_is_authorization"] is False
            and contract["authority_boundaries"]["recovery_is_routing"] is False
            and contract["authority_boundaries"]["recovery_is_redelivery"] is False
            and contract["authority_boundaries"]["recovery_is_ownership_transfer"] is False
            and contract["authority_boundaries"]["dispatch_performed"] is False
            and contract["authority_boundaries"]["execution_authorized"] is False
        )
    except Exception:
        return False


def canonical_routing_delegation_event_lineage_definition() -> Dict[str, Any]:
    return {
        "lineage_schema_version": ROUTING_DELEGATION_EVENT_LINEAGE_SCHEMA_VERSION,
        "replay_schema_version": ROUTING_DELEGATION_EVENT_REPLAY_SCHEMA_VERSION,
        "recovery_checkpoint_schema_version": ROUTING_DELEGATION_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "lineage_mode": ROUTING_DELEGATION_EVENT_LINEAGE_MODE,
        "replay_mode": ROUTING_DELEGATION_REPLAY_MODE,
        "recovery_mode": ROUTING_DELEGATION_RECOVERY_MODE,
        "event_types": list(ROUTING_DELEGATION_EVENT_TYPES),
        "canonical_chain": [
            "ROUTING_INTENT",
            "ELIGIBILITY_GATE",
            "ROUTE_DECISION",
            "GOVERNANCE_BOUND_DELEGATION_AUTHORIZATION",
            "DELEGATION_AND_HANDOFF",
            "DELIVERY_ACKNOWLEDGEMENT_OWNERSHIP",
            "ZERO_OR_MORE_RECOVERY_CONTROLS",
        ],
        "replay_read_only": True,
        "replay_side_effects_performed": False,
        "recovery_reconstructs_durable_artifacts_only": True,
        "recovery_checkpoint_is_authorization": False,
        "recovery_checkpoint_is_routing": False,
        "recovery_checkpoint_is_redelivery": False,
        "recovery_checkpoint_is_ownership_transfer": False,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "external_network_io_performed": False,
        "governance_query_performed": False,
        "dispatch_performed": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
