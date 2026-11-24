from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionSubsystemProtocolError, MissionValidationError
from .execution_delivery import (
    ACKNOWLEDGED_ATTEMPT_STATUS,
    ACKNOWLEDGEMENT_STATUS,
    DELIVERY_STATUS,
    verify_execution_delivery_contract,
)
from .execution_attempt import verify_execution_attempt_contract

RUNNING_EXECUTION_SCHEMA_VERSION = "apts-running-execution-state-heartbeat-projection-v1"
RUNNING_EXECUTION_HASH_DOMAIN = "MISSION_RUNNING_EXECUTION_STATE_HEARTBEAT_PROJECTION_V1"
RUNNING_EXECUTION_REQUEST_HASH_DOMAIN = "MISSION_RUNNING_EXECUTION_STATE_HEARTBEAT_REQUEST_V1"
RUNNING_EXECUTION_ID_PREFIX = "xrun-"
RUNNING_EXECUTION_MODE = "AUTHORITATIVE_RUNTIME_RUNNING_STATE_WITH_APPEND_ONLY_HEARTBEAT_PROJECTION"
RUNNING_EXECUTION_AUTHORITY = "DOWNSTREAM_SUBSYSTEM_RUNTIME_EXECUTION_STATE"
RUNNING_EXECUTION_ALLOWED_STATES = frozenset({"RUNNING"})
RUNNING_EXECUTION_STATE = "RUNNING"
RUNNING_EXECUTION_ATTEMPT_STATUS = "RUNNING_HEARTBEAT_CONFIRMED"
HEARTBEAT_STATUS = "ALIVE"
RUNTIME_OBSERVATION_CHANNEL = "RUNTIME_EXECUTION_STATUS_AND_HEARTBEAT_READ"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_execution_delivery_id",
    "expected_execution_delivery_sha256",
    "expected_execution_attempt_id",
    "expected_execution_attempt_sha256",
    "expected_dispatch_envelope_id",
    "projected_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_running_execution_projection_id() -> str:
    return f"{RUNNING_EXECUTION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_running_execution_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("running execution projection request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported running execution projection field(s): " + ", ".join(unknown)
            + "; Stage 3.5.6 derives runtime endpoint, runtime state, execution start, heartbeat identity/sequence/time/status, and target-actuation state from the persisted Stage-3.5.5 delivery and downstream runtime observation. Caller-supplied runtime/running/heartbeat/actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_delivery_id": _string(payload, "expected_execution_delivery_id"),
        "expected_execution_attempt_id": _string(payload, "expected_execution_attempt_id"),
        "expected_dispatch_envelope_id": _string(payload, "expected_dispatch_envelope_id"),
        "projected_by": _string(payload, "projected_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_execution_delivery_id"].startswith("xack-"):
        raise MissionValidationError("expected_execution_delivery_id must be a canonical xack-* identifier")
    if not values["expected_execution_attempt_id"].startswith("xattempt-"):
        raise MissionValidationError("expected_execution_attempt_id must be a canonical xattempt-* identifier")
    if not values["expected_dispatch_envelope_id"].startswith("xenv-"):
        raise MissionValidationError("expected_dispatch_envelope_id must be a canonical xenv-* identifier")

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
        "expected_execution_delivery_sha256": _sha(payload, "expected_execution_delivery_sha256"),
        "expected_execution_attempt_sha256": _sha(payload, "expected_execution_attempt_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def running_execution_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": RUNNING_EXECUTION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _runtime_string(response: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = response.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionSubsystemProtocolError(f"runtime running-state {key} is missing or invalid")
    value = value.strip()
    if len(value) > max_len:
        raise MissionSubsystemProtocolError(f"runtime running-state {key} exceeds {max_len} characters")
    return value


def normalize_runtime_running_observation(
    response: Any,
    *,
    mission_id: str,
    execution_attempt_id: str,
    dispatch_envelope_id: str,
    subsystem_id: str,
) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise MissionSubsystemProtocolError("runtime execution-state response must be a JSON object")
    status = str(response.get("status") or "").strip().lower()
    if status not in {"ok", "running", "active"}:
        raise MissionSubsystemProtocolError("runtime execution-state response did not indicate a running observation")
    for key, expected in {
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
    }.items():
        if response.get(key) != expected:
            raise MissionSubsystemProtocolError(f"runtime running-state {key} does not match Stage-3.5.5 binding")
    observed_by = _runtime_string(response, "observed_by")
    if observed_by != subsystem_id:
        raise MissionSubsystemProtocolError("runtime running-state observed_by does not match target subsystem")
    execution_state = str(response.get("execution_state") or "").strip().upper()
    if execution_state != RUNNING_EXECUTION_STATE:
        raise MissionSubsystemProtocolError("Stage-3.5.6 requires downstream execution_state=RUNNING")
    if response.get("execution_started") is not True:
        raise MissionSubsystemProtocolError("Stage-3.5.6 requires execution_started=true")
    if response.get("target_actuation") is not False:
        raise MissionSubsystemProtocolError("Stage-3.5.6 projection requires target_actuation=false")
    started_at = _runtime_string(response, "started_at", 80)

    heartbeat = response.get("heartbeat")
    if not isinstance(heartbeat, dict):
        raise MissionSubsystemProtocolError("runtime running-state heartbeat must be a JSON object")
    heartbeat_id = _runtime_string(heartbeat, "heartbeat_id")
    if not _ID_RE.match(heartbeat_id):
        raise MissionSubsystemProtocolError("runtime heartbeat_id contains unsupported characters")
    raw_sequence = heartbeat.get("sequence")
    if isinstance(raw_sequence, bool):
        raise MissionSubsystemProtocolError("runtime heartbeat sequence must be an integer")
    try:
        sequence = int(raw_sequence)
    except (TypeError, ValueError) as exc:
        raise MissionSubsystemProtocolError("runtime heartbeat sequence is missing or invalid") from exc
    if sequence < 1:
        raise MissionSubsystemProtocolError("runtime heartbeat sequence must be >= 1")
    heartbeat_at = _runtime_string(heartbeat, "observed_at", 80)
    remote_hb_status = str(heartbeat.get("status") or "").strip().lower()
    if remote_hb_status not in {"alive", "healthy"}:
        raise MissionSubsystemProtocolError("runtime heartbeat status must be alive/healthy")
    normalized_heartbeat = {
        "heartbeat_id": heartbeat_id,
        "sequence": sequence,
        "observed_at": heartbeat_at,
        "status": HEARTBEAT_STATUS,
    }
    normalized_heartbeat["heartbeat_sha256"] = sha256_hex(normalized_heartbeat)
    normalized = {
        "status": status,
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
        "observed_by": observed_by,
        "execution_state": RUNNING_EXECUTION_STATE,
        "execution_started": True,
        "started_at": started_at,
        "heartbeat": normalized_heartbeat,
        "target_actuation": False,
    }
    normalized["observation_sha256"] = sha256_hex(normalized)
    return normalized


def build_running_execution_projection_contract(
    *,
    running_projection_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    execution_attempt: Mapping[str, Any],
    execution_delivery: Mapping[str, Any],
    runtime_health: Mapping[str, Any],
    runtime_observation: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    delivery_contract = execution_delivery["execution_delivery_contract"]
    if not verify_execution_delivery_contract(delivery_contract):
        raise MissionValidationError("Stage-3.5.5 execution-delivery contract failed integrity verification")
    if execution_delivery["delivery_status"] != DELIVERY_STATUS:
        raise MissionValidationError("Stage-3.5.5 delivery status is not DELIVERED_TO_RUNTIME")
    if execution_delivery["acknowledgement_status"] != ACKNOWLEDGEMENT_STATUS:
        raise MissionValidationError("Stage-3.5.5 acknowledgement is not accepted for execution")
    if execution_delivery["execution_attempt_status"] != ACKNOWLEDGED_ATTEMPT_STATUS:
        raise MissionValidationError("Stage-3.5.5 execution attempt is not pending RUNNING")
    attempt_contract = execution_attempt["execution_attempt_contract"]
    if not verify_execution_attempt_contract(attempt_contract):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")

    heartbeat = runtime_observation["heartbeat"]
    core = {
        "schema_version": RUNNING_EXECUTION_SCHEMA_VERSION,
        "identity": {
            "running_projection_id": running_projection_id,
            "mission_id": mission_id,
            "execution_delivery_id": execution_delivery["execution_delivery_id"],
            "execution_attempt_id": execution_attempt["execution_attempt_id"],
            "dispatch_envelope_id": execution_attempt["dispatch_envelope_id"],
            "execution_dispatch_id": execution_attempt["execution_dispatch_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": execution_attempt["planned_task_id"],
            "task_key": execution_attempt["task_key"],
        },
        "source_bindings": {
            "source_state": state["state"],
            "source_state_version": int(state["state_version"]),
            "source_version_sha256": version_vector["version_sha256"],
            "active_plan_sha256": active_plan["canonical_sha256"],
            "execution_attempt_sha256": execution_attempt["canonical_sha256"],
            "execution_delivery_sha256": execution_delivery["canonical_sha256"],
            "pre_dispatch_revalidation_id": execution_attempt["pre_dispatch_revalidation_id"],
            "policy_decision_id": execution_attempt["policy_decision_id"],
            "policy_decision_hash": execution_attempt["policy_decision_hash"],
            "policy_version": int(execution_attempt["policy_version"]),
        },
        "runtime_binding": {
            "subsystem_id": execution_delivery["recipient_subsystem_id"],
            "capability_id": execution_delivery["recipient_capability_id"],
            "capability_version": int(delivery_contract["runtime_binding"]["capability_version"]),
            "runtime_endpoint": execution_delivery["runtime_endpoint"],
            "runtime_endpoint_reused_from_stage355": True,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": True,
            "runtime_health_status": runtime_health["status"],
            "runtime_health_sha256": sha256_hex(dict(runtime_health)),
            "observation_channel": RUNTIME_OBSERVATION_CHANNEL,
            "observation_sha256": runtime_observation["observation_sha256"],
        },
        "running_state": {
            "execution_state": RUNNING_EXECUTION_STATE,
            "execution_attempt_status": RUNNING_EXECUTION_ATTEMPT_STATUS,
            "execution_started": True,
            "started_at": runtime_observation["started_at"],
            "running_state_recorded": True,
            "target_actuation": False,
        },
        "heartbeat": {
            "heartbeat_id": heartbeat["heartbeat_id"],
            "heartbeat_sequence": int(heartbeat["sequence"]),
            "heartbeat_at": heartbeat["observed_at"],
            "heartbeat_status": HEARTBEAT_STATUS,
            "heartbeat_sha256": heartbeat["heartbeat_sha256"],
            "heartbeat_recorded": True,
        },
        "idempotency": {
            "idempotency_key": request["idempotency_key"],
            "request_sha256": request_sha256,
            "append_only_heartbeat_projection": True,
            "heartbeat_sequence_monotonic_per_attempt": True,
        },
        "semantics": {
            "mode": RUNNING_EXECUTION_MODE,
            "requires_stage355_delivery_acknowledgement": True,
            "stage355_delivery_reused_no_redelivery": True,
            "authoritative_governance_query_performed": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": True,
            "runtime_execution_state_query_performed": True,
            "execution_start_observed": True,
            "execution_started": True,
            "running_state_recorded": True,
            "heartbeat_recorded": True,
            "dispatch_redelivery_performed": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
            "projection_is_observation_not_execution_authority": True,
            "next_stage": "3.5.7",
        },
        "provenance": {
            "projected_by": request["projected_by"],
            "created_at": created_at,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
        },
    }
    digest = sha256_hex({"hash_domain": RUNNING_EXECUTION_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_running_execution_projection_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        running = contract["running_state"]
        heartbeat = contract["heartbeat"]
        semantics = contract["semantics"]
        return (
            contract["schema_version"] == RUNNING_EXECUTION_SCHEMA_VERSION
            and str(identity["running_projection_id"]).startswith(RUNNING_EXECUTION_ID_PREFIX)
            and str(identity["execution_delivery_id"]).startswith("xack-")
            and str(identity["execution_attempt_id"]).startswith("xattempt-")
            and str(identity["dispatch_envelope_id"]).startswith("xenv-")
            and running["execution_state"] == RUNNING_EXECUTION_STATE
            and running["execution_attempt_status"] == RUNNING_EXECUTION_ATTEMPT_STATUS
            and running["execution_started"] is True
            and running["running_state_recorded"] is True
            and running["target_actuation"] is False
            and int(heartbeat["heartbeat_sequence"]) >= 1
            and heartbeat["heartbeat_status"] == HEARTBEAT_STATUS
            and heartbeat["heartbeat_recorded"] is True
            and semantics["runtime_execution_state_query_performed"] is True
            and semantics["execution_started"] is True
            and semantics["running_state_recorded"] is True
            and semantics["heartbeat_recorded"] is True
            and semantics["dispatch_redelivery_performed"] is False
            and semantics["target_action_dispatch_performed"] is False
            and semantics["target_actuation"] is False
            and digest == sha256_hex({"hash_domain": RUNNING_EXECUTION_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_running_execution_definition() -> Dict[str, Any]:
    return {
        "schema_version": RUNNING_EXECUTION_SCHEMA_VERSION,
        "identity_prefix": RUNNING_EXECUTION_ID_PREFIX,
        "mode": RUNNING_EXECUTION_MODE,
        "authority": RUNNING_EXECUTION_AUTHORITY,
        "allowed_source_states": sorted(RUNNING_EXECUTION_ALLOWED_STATES),
        "requires_stage355_delivery_acknowledgement": True,
        "append_only_heartbeat_projection": True,
        "heartbeat_sequence_monotonic_per_attempt": True,
        "execution_state": RUNNING_EXECUTION_STATE,
        "execution_attempt_status": RUNNING_EXECUTION_ATTEMPT_STATUS,
        "heartbeat_status": HEARTBEAT_STATUS,
        "runtime_endpoint_reused_from_stage355": True,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": True,
        "runtime_execution_state_query_performed": True,
        "governance_query_performed": False,
        "execution_start_observed": True,
        "execution_started": True,
        "running_state_recorded": True,
        "heartbeat_recorded": True,
        "dispatch_redelivery_performed": False,
        "target_action_dispatch_performed": False,
        "target_actuation": False,
        "projection_is_observation_not_execution_authority": True,
        "next_stage": "3.5.7",
    }
