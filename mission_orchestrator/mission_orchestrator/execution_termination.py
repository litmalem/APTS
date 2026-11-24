from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionSubsystemProtocolError, MissionValidationError
from .execution_attempt import verify_execution_attempt_contract
from .execution_delivery import verify_execution_delivery_contract
from .execution_result import TERMINAL_EXECUTION_STATES, verify_execution_result_capture_contract
from .execution_running import verify_running_execution_projection_contract

STAGE358_SCHEMA_VERSION = "apts-execution-timeout-cancellation-abort-failure-propagation-v1"
TERMINATION_CONTROL_SCHEMA_VERSION = "apts-execution-termination-control-v1"
TERMINAL_OUTCOME_PROPAGATION_SCHEMA_VERSION = "apts-execution-terminal-outcome-propagation-v1"
TERMINATION_CONTROL_HASH_DOMAIN = "MISSION_EXECUTION_TERMINATION_CONTROL_V1"
TERMINATION_CONTROL_REQUEST_HASH_DOMAIN = "MISSION_EXECUTION_TERMINATION_CONTROL_REQUEST_V1"
OUTCOME_PROPAGATION_HASH_DOMAIN = "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATION_V1"
OUTCOME_PROPAGATION_REQUEST_HASH_DOMAIN = "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATION_REQUEST_V1"
TERMINATION_CONTROL_ID_PREFIX = "xterm-"
OUTCOME_PROPAGATION_ID_PREFIX = "xprop-"
TERMINATION_CONTROL_MODE = "FAIL_CLOSED_RUNTIME_TIMEOUT_CANCELLATION_ABORT_CONTROL_PENDING_TERMINAL_RESULT"
OUTCOME_PROPAGATION_MODE = "VERIFIED_TERMINAL_OUTCOME_WITH_FAIL_FAST_MISSION_FAILURE_PROPAGATION"
TERMINATION_CONTROL_AUTHORITY = "MISSION_ORCHESTRATOR_EXECUTION_CONTROL_INTENT"
OUTCOME_PROPAGATION_AUTHORITY = "MISSION_ORCHESTRATOR_VERIFIED_EXECUTION_OUTCOME_PROPAGATION"
TERMINATION_ALLOWED_STATES = frozenset({"RUNNING"})
RUNTIME_TERMINATION_CONTROL_CHANNEL = "RUNTIME_EXECUTION_TERMINATION_CONTROL"
TERMINATION_CONTROL_STATUS = "ACKNOWLEDGED_PENDING_TERMINAL_RESULT"

ACTION_TIMEOUT = "TIMEOUT"
ACTION_CANCEL = "CANCEL"
ACTION_ABORT = "ABORT"
TERMINATION_ACTIONS = frozenset({ACTION_TIMEOUT, ACTION_CANCEL, ACTION_ABORT})
EXPECTED_TERMINAL_STATE_BY_ACTION = {
    ACTION_TIMEOUT: "TIMED_OUT",
    ACTION_CANCEL: "CANCELLED",
    ACTION_ABORT: "CANCELLED",
}

OUTCOME_VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
OUTCOME_VERIFIED_FAILURE = "VERIFIED_FAILURE"
OUTCOME_VERIFIED_CANCELLATION = "VERIFIED_CANCELLATION"
OUTCOME_VERIFIED_ABORT = "VERIFIED_ABORT"
OUTCOME_VERIFIED_TIMEOUT = "VERIFIED_TIMEOUT"
OUTCOME_CLASSIFICATIONS = frozenset(
    {
        OUTCOME_VERIFIED_SUCCESS,
        OUTCOME_VERIFIED_FAILURE,
        OUTCOME_VERIFIED_CANCELLATION,
        OUTCOME_VERIFIED_ABORT,
        OUTCOME_VERIFIED_TIMEOUT,
    }
)
TASK_OUTCOME_COMPLETED = "VERIFIED_COMPLETED"
TASK_OUTCOME_FAILED = "VERIFIED_FAILED"
TASK_OUTCOME_CANCELLED = "VERIFIED_CANCELLED"
TASK_OUTCOME_TIMED_OUT = "VERIFIED_TIMED_OUT"
PROPAGATION_NONE = "NO_MISSION_FAILURE_PROPAGATION"
PROPAGATION_FAIL = "MISSION_FAIL"
PROPAGATION_ABORT = "MISSION_ABORT"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_REQUEST_FIELDS = {
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
    "expected_running_projection_id",
    "expected_running_projection_sha256",
    "control_action",
    "requested_by",
    "reason",
    "metadata",
}
_PROPAGATION_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_result_capture_id",
    "expected_result_capture_sha256",
    "expected_execution_attempt_id",
    "expected_execution_attempt_sha256",
    "propagated_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_termination_control_id() -> str:
    return f"{TERMINATION_CONTROL_ID_PREFIX}{uuid.uuid4()}"


def new_outcome_propagation_id() -> str:
    return f"{OUTCOME_PROPAGATION_ID_PREFIX}{uuid.uuid4()}"


def deterministic_lifecycle_command_identity(result_capture_id: str) -> tuple[str, str]:
    digest = sha256_hex({"stage": "3.5.8", "result_capture_id": result_capture_id})[:24]
    return f"lc-358-{digest}", f"idem-lc-358-{digest}"


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


def _metadata_and_reason(payload: Mapping[str, Any]) -> tuple[Dict[str, Any], Optional[str]]:
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason in (None, ""):
        return dict(metadata), None
    if not isinstance(reason, str) or not reason.strip():
        raise MissionValidationError("reason must be a non-empty string when provided")
    reason = reason.strip()
    if len(reason) > 2000:
        raise MissionValidationError("reason exceeds 2000 characters")
    return dict(metadata), reason


def normalize_termination_control_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("execution termination-control request body must be a JSON object")
    unknown = sorted(set(payload) - _CONTROL_REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported execution termination-control field(s): "
            + ", ".join(unknown)
            + "; Stage 3.5.8 derives runtime endpoint, recipient identity, authorization provenance, "
              "terminal-state expectation, runtime acknowledgement, and failure propagation from durable Stage-3.5.4 through Stage-3.5.7 records. "
              "Caller-supplied endpoint/result/mission-state/propagation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_delivery_id": _string(payload, "expected_execution_delivery_id"),
        "expected_execution_attempt_id": _string(payload, "expected_execution_attempt_id"),
        "expected_dispatch_envelope_id": _string(payload, "expected_dispatch_envelope_id"),
        "expected_running_projection_id": _string(payload, "expected_running_projection_id"),
        "requested_by": _string(payload, "requested_by", 128),
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
    if not values["expected_running_projection_id"].startswith("xrun-"):
        raise MissionValidationError("expected_running_projection_id must be a canonical xrun-* identifier")
    action = _string(payload, "control_action", 32).upper()
    if action not in TERMINATION_ACTIONS:
        raise MissionValidationError("control_action must be one of: " + ", ".join(sorted(TERMINATION_ACTIONS)))
    metadata, reason = _metadata_and_reason(payload)
    return {
        **values,
        "control_action": action,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_execution_delivery_sha256": _sha(payload, "expected_execution_delivery_sha256"),
        "expected_execution_attempt_sha256": _sha(payload, "expected_execution_attempt_sha256"),
        "expected_running_projection_sha256": _sha(payload, "expected_running_projection_sha256"),
        "reason": reason,
        "metadata": metadata,
    }


def termination_control_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TERMINATION_CONTROL_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def normalize_outcome_propagation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("execution outcome-propagation request body must be a JSON object")
    unknown = sorted(set(payload) - _PROPAGATION_REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported execution outcome-propagation field(s): "
            + ", ".join(unknown)
            + "; Stage 3.5.8 derives outcome classification, lifecycle command, mission target state, and failure semantics from the immutable Stage-3.5.7 result capture"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_result_capture_id": _string(payload, "expected_result_capture_id"),
        "expected_execution_attempt_id": _string(payload, "expected_execution_attempt_id"),
        "propagated_by": _string(payload, "propagated_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_result_capture_id"].startswith("xresult-"):
        raise MissionValidationError("expected_result_capture_id must be a canonical xresult-* identifier")
    if not values["expected_execution_attempt_id"].startswith("xattempt-"):
        raise MissionValidationError("expected_execution_attempt_id must be a canonical xattempt-* identifier")
    metadata, reason = _metadata_and_reason(payload)
    return {
        **values,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_result_capture_sha256": _sha(payload, "expected_result_capture_sha256"),
        "expected_execution_attempt_sha256": _sha(payload, "expected_execution_attempt_sha256"),
        "reason": reason,
        "metadata": metadata,
    }


def outcome_propagation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": OUTCOME_PROPAGATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_runtime_termination_control_payload(
    *, mission_id: str, execution_attempt: Mapping[str, Any], control_action: str, reason: Optional[str]
) -> Dict[str, Any]:
    if control_action not in TERMINATION_ACTIONS:
        raise MissionValidationError("unsupported Stage-3.5.8 termination control action")
    if not verify_execution_attempt_contract(execution_attempt["execution_attempt_contract"]):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    return {
        "schema_version": "apts-runtime-execution-termination-control-v1",
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt["execution_attempt_id"],
        "dispatch_envelope_id": execution_attempt["dispatch_envelope_id"],
        "control_action": control_action,
        "expected_terminal_state": EXPECTED_TERMINAL_STATE_BY_ACTION[control_action],
        "reason": reason,
        "semantics": {
            "execution_control_only": True,
            "new_execution_dispatch": False,
            "new_governance_authorization": False,
            "terminal_result_must_be_captured_separately": True,
        },
    }


def normalize_runtime_termination_acknowledgement(
    response: Any,
    *,
    mission_id: str,
    execution_attempt_id: str,
    dispatch_envelope_id: str,
    subsystem_id: str,
    control_action: str,
) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise MissionSubsystemProtocolError("runtime termination-control response must be a JSON object")
    status = str(response.get("status") or "").strip().lower()
    if status not in {"accepted", "acknowledged"}:
        raise MissionSubsystemProtocolError("runtime termination-control response did not indicate accepted/acknowledged")
    bindings = {
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
    }
    for key, expected in bindings.items():
        if response.get(key) != expected:
            raise MissionSubsystemProtocolError(f"runtime termination-control {key} does not match Stage-3.5 execution binding")
    if str(response.get("observed_by") or "").strip() != subsystem_id:
        raise MissionSubsystemProtocolError("runtime termination-control observed_by does not match target subsystem")
    if str(response.get("control_action") or "").strip().upper() != control_action:
        raise MissionSubsystemProtocolError("runtime termination-control action does not match requested action")
    if response.get("termination_requested") is not True:
        raise MissionSubsystemProtocolError("runtime termination-control must acknowledge termination_requested=true")
    acknowledged_at = response.get("acknowledged_at")
    if not isinstance(acknowledged_at, str) or not acknowledged_at.strip() or len(acknowledged_at.strip()) > 80:
        raise MissionSubsystemProtocolError("runtime termination-control acknowledged_at is missing or invalid")
    normalized = {
        "status": status,
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
        "observed_by": subsystem_id,
        "control_action": control_action,
        "termination_requested": True,
        "acknowledged_at": acknowledged_at.strip(),
        "expected_terminal_state": EXPECTED_TERMINAL_STATE_BY_ACTION[control_action],
    }
    normalized["acknowledgement_sha256"] = sha256_hex(normalized)
    return normalized


def build_termination_control_contract(
    *,
    termination_control_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    execution_attempt: Mapping[str, Any],
    execution_delivery: Mapping[str, Any],
    running_projection: Mapping[str, Any],
    runtime_health: Mapping[str, Any],
    runtime_ack: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    if not verify_execution_attempt_contract(execution_attempt["execution_attempt_contract"]):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    if not verify_execution_delivery_contract(execution_delivery["execution_delivery_contract"]):
        raise MissionValidationError("Stage-3.5.5 execution-delivery contract failed integrity verification")
    if not verify_running_execution_projection_contract(running_projection["running_execution_projection_contract"]):
        raise MissionValidationError("Stage-3.5.6 running projection failed integrity verification")
    action = request["control_action"]
    core = {
        "schema_version": TERMINATION_CONTROL_SCHEMA_VERSION,
        "stage_schema_version": STAGE358_SCHEMA_VERSION,
        "identity": {
            "termination_control_id": termination_control_id,
            "mission_id": mission_id,
            "running_projection_id": running_projection["running_projection_id"],
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
            "running_projection_sha256": running_projection["canonical_sha256"],
            "running_heartbeat_sequence": int(running_projection["heartbeat_sequence"]),
            "policy_decision_id": execution_attempt["policy_decision_id"],
            "policy_decision_hash": execution_attempt["policy_decision_hash"],
            "policy_version": int(execution_attempt["policy_version"]),
        },
        "runtime_control": {
            "subsystem_id": execution_delivery["recipient_subsystem_id"],
            "capability_id": execution_delivery["recipient_capability_id"],
            "runtime_endpoint": execution_delivery["runtime_endpoint"],
            "runtime_endpoint_reused_from_stage355": True,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": True,
            "runtime_health_status": runtime_health["status"],
            "runtime_health_sha256": sha256_hex(dict(runtime_health)),
            "control_channel": RUNTIME_TERMINATION_CONTROL_CHANNEL,
            "control_action": action,
            "expected_terminal_state": EXPECTED_TERMINAL_STATE_BY_ACTION[action],
            "termination_requested": True,
            "control_status": TERMINATION_CONTROL_STATUS,
            "acknowledged_at": runtime_ack["acknowledged_at"],
            "acknowledgement_sha256": runtime_ack["acknowledgement_sha256"],
        },
        "idempotency": {
            "idempotency_key": request["idempotency_key"],
            "request_sha256": request_sha256,
            "one_termination_control_per_execution_attempt": True,
        },
        "semantics": {
            "mode": TERMINATION_CONTROL_MODE,
            "authority": TERMINATION_CONTROL_AUTHORITY,
            "control_action": action,
            "runtime_control_io_performed": True,
            "governance_query_performed": False,
            "runtime_endpoint_resolution_performed": False,
            "dispatch_redelivery_performed": False,
            "new_target_action_dispatch_performed": False,
            "terminal_result_capture_performed": False,
            "mission_state_transition_performed": False,
            "failure_propagation_performed": False,
            "terminal_result_capture_required_next": True,
        },
        "provenance": {
            "requested_by": request["requested_by"],
            "created_at": created_at,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
        },
    }
    digest = sha256_hex({"hash_domain": TERMINATION_CONTROL_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_termination_control_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        runtime = contract["runtime_control"]
        semantics = contract["semantics"]
        return (
            contract["schema_version"] == TERMINATION_CONTROL_SCHEMA_VERSION
            and contract["stage_schema_version"] == STAGE358_SCHEMA_VERSION
            and str(identity["termination_control_id"]).startswith(TERMINATION_CONTROL_ID_PREFIX)
            and str(identity["running_projection_id"]).startswith("xrun-")
            and str(identity["execution_attempt_id"]).startswith("xattempt-")
            and runtime["control_action"] in TERMINATION_ACTIONS
            and runtime["expected_terminal_state"] == EXPECTED_TERMINAL_STATE_BY_ACTION[runtime["control_action"]]
            and runtime["termination_requested"] is True
            and runtime["control_status"] == TERMINATION_CONTROL_STATUS
            and semantics["runtime_control_io_performed"] is True
            and semantics["governance_query_performed"] is False
            and semantics["dispatch_redelivery_performed"] is False
            and semantics["new_target_action_dispatch_performed"] is False
            and semantics["mission_state_transition_performed"] is False
            and semantics["failure_propagation_performed"] is False
            and digest == sha256_hex({"hash_domain": TERMINATION_CONTROL_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def classify_terminal_outcome(
    execution_state: str,
    *,
    termination_control: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    execution_state = str(execution_state or "").upper()
    if execution_state not in TERMINAL_EXECUTION_STATES:
        raise MissionValidationError("Stage-3.5.8 requires a Stage-3.5.7 terminal execution state")
    control_action = None
    if termination_control is not None:
        if not verify_termination_control_contract(termination_control["termination_control_contract"]):
            raise MissionValidationError("Stage-3.5.8 termination-control contract failed integrity verification")
        control_action = termination_control["control_action"]

    if execution_state == "SUCCEEDED":
        return {
            "outcome_classification": OUTCOME_VERIFIED_SUCCESS,
            "task_outcome_status": TASK_OUTCOME_COMPLETED,
            "propagation_action": PROPAGATION_NONE,
            "lifecycle_command": None,
            "target_mission_state": "RUNNING",
            "failure_propagation_required": False,
        }
    if execution_state == "FAILED":
        return {
            "outcome_classification": OUTCOME_VERIFIED_FAILURE,
            "task_outcome_status": TASK_OUTCOME_FAILED,
            "propagation_action": PROPAGATION_FAIL,
            "lifecycle_command": "FAIL",
            "target_mission_state": "FAILED",
            "failure_propagation_required": True,
        }
    if execution_state == "TIMED_OUT":
        return {
            "outcome_classification": OUTCOME_VERIFIED_TIMEOUT,
            "task_outcome_status": TASK_OUTCOME_TIMED_OUT,
            "propagation_action": PROPAGATION_FAIL,
            "lifecycle_command": "FAIL",
            "target_mission_state": "FAILED",
            "failure_propagation_required": True,
        }
    # CANCELLED
    if control_action == ACTION_TIMEOUT:
        return {
            "outcome_classification": OUTCOME_VERIFIED_TIMEOUT,
            "task_outcome_status": TASK_OUTCOME_TIMED_OUT,
            "propagation_action": PROPAGATION_FAIL,
            "lifecycle_command": "FAIL",
            "target_mission_state": "FAILED",
            "failure_propagation_required": True,
        }
    if control_action == ACTION_ABORT:
        outcome = OUTCOME_VERIFIED_ABORT
    else:
        outcome = OUTCOME_VERIFIED_CANCELLATION
    return {
        "outcome_classification": outcome,
        "task_outcome_status": TASK_OUTCOME_CANCELLED,
        "propagation_action": PROPAGATION_ABORT,
        "lifecycle_command": "ABORT",
        "target_mission_state": "ABORTED",
        "failure_propagation_required": True,
    }


def build_outcome_propagation_contract(
    *,
    outcome_propagation_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    execution_attempt: Mapping[str, Any],
    result_capture: Mapping[str, Any],
    termination_control: Optional[Mapping[str, Any]],
    lifecycle_result: Optional[Mapping[str, Any]],
    created_at: str,
) -> Dict[str, Any]:
    if not verify_execution_attempt_contract(execution_attempt["execution_attempt_contract"]):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    if not verify_execution_result_capture_contract(result_capture["execution_result_capture_contract"]):
        raise MissionValidationError("Stage-3.5.7 execution-result capture failed integrity verification")
    classification = classify_terminal_outcome(
        result_capture["execution_state"], termination_control=termination_control
    )
    transition = None
    terminal_control = None
    lifecycle_command_id = None
    lifecycle_idempotency_key = None
    resulting_state = source_state["state"]
    resulting_state_version = int(source_state["state_version"])
    if classification["failure_propagation_required"]:
        if not isinstance(lifecycle_result, Mapping):
            raise MissionValidationError("failure propagation requires a completed lifecycle command result")
        transition = lifecycle_result.get("transition")
        terminal_control = lifecycle_result.get("terminal_control")
        lifecycle_command_id = lifecycle_result.get("command_id")
        lifecycle_idempotency_key = lifecycle_result.get("idempotency_key")
        if not isinstance(transition, Mapping):
            raise MissionValidationError("failure propagation lifecycle result is missing transition evidence")
        if transition.get("from_state") != source_state["state"]:
            raise MissionValidationError("failure propagation transition source state does not match Stage-3.5.8 source state")
        if transition.get("to_state") != classification["target_mission_state"]:
            raise MissionValidationError("failure propagation lifecycle target state does not match terminal outcome classification")
        mission_state = lifecycle_result.get("mission_state") or {}
        resulting_state = mission_state.get("state")
        resulting_state_version = int(mission_state.get("state_version"))
        if resulting_state != classification["target_mission_state"]:
            raise MissionValidationError("failure propagation resulting Mission state is inconsistent")

    core = {
        "schema_version": TERMINAL_OUTCOME_PROPAGATION_SCHEMA_VERSION,
        "stage_schema_version": STAGE358_SCHEMA_VERSION,
        "identity": {
            "outcome_propagation_id": outcome_propagation_id,
            "mission_id": mission_id,
            "result_capture_id": result_capture["result_capture_id"],
            "termination_control_id": None if termination_control is None else termination_control["termination_control_id"],
            "execution_attempt_id": execution_attempt["execution_attempt_id"],
            "dispatch_envelope_id": execution_attempt["dispatch_envelope_id"],
            "execution_dispatch_id": execution_attempt["execution_dispatch_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": execution_attempt["planned_task_id"],
            "task_key": execution_attempt["task_key"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "execution_attempt_sha256": execution_attempt["canonical_sha256"],
            "result_capture_sha256": result_capture["canonical_sha256"],
            "result_execution_state": result_capture["execution_state"],
            "evidence_manifest_sha256": result_capture["evidence_manifest_sha256"],
            "artifact_manifest_sha256": result_capture["artifact_manifest_sha256"],
            "policy_decision_id": execution_attempt["policy_decision_id"],
            "policy_decision_hash": execution_attempt["policy_decision_hash"],
            "policy_version": int(execution_attempt["policy_version"]),
        },
        "outcome_verification": {
            **classification,
            "result_capture_integrity_verified": True,
            "evidence_manifest_bound": True,
            "artifact_manifest_bound": True,
            "termination_control_action": None if termination_control is None else termination_control["control_action"],
            "execution_outcome_verification_authority_exercised": True,
            "mission_success_completion_authority_exercised": False,
        },
        "failure_propagation": {
            "performed": bool(classification["failure_propagation_required"]),
            "lifecycle_command": classification["lifecycle_command"],
            "lifecycle_command_id": lifecycle_command_id,
            "lifecycle_idempotency_key": lifecycle_idempotency_key,
            "transition_id": None if transition is None else transition.get("transition_id"),
            "terminal_control_id": None if terminal_control is None else terminal_control.get("terminal_id"),
            "resulting_mission_state": resulting_state,
            "resulting_state_version": resulting_state_version,
            "terminal_failure_is_immutable": bool(classification["failure_propagation_required"]),
        },
        "idempotency": {
            "idempotency_key": request["idempotency_key"],
            "request_sha256": request_sha256,
            "one_outcome_propagation_per_result_capture": True,
        },
        "semantics": {
            "mode": OUTCOME_PROPAGATION_MODE,
            "authority": OUTCOME_PROPAGATION_AUTHORITY,
            "stage357_result_is_authoritative_source": True,
            "runtime_result_query_performed": False,
            "runtime_control_io_performed": False,
            "governance_query_performed": False,
            "dispatch_redelivery_performed": False,
            "new_target_action_dispatch_performed": False,
            "success_does_not_imply_mission_completion": True,
            "non_success_fail_fast_propagation": True,
            "mission_state_transition_performed": bool(classification["failure_propagation_required"]),
            "next_stage": "3.5.9",
        },
        "provenance": {
            "propagated_by": request["propagated_by"],
            "created_at": created_at,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
        },
    }
    digest = sha256_hex({"hash_domain": OUTCOME_PROPAGATION_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_outcome_propagation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        outcome = contract["outcome_verification"]
        propagation = contract["failure_propagation"]
        semantics = contract["semantics"]
        failure_required = bool(outcome["failure_propagation_required"])
        return (
            contract["schema_version"] == TERMINAL_OUTCOME_PROPAGATION_SCHEMA_VERSION
            and contract["stage_schema_version"] == STAGE358_SCHEMA_VERSION
            and str(identity["outcome_propagation_id"]).startswith(OUTCOME_PROPAGATION_ID_PREFIX)
            and str(identity["result_capture_id"]).startswith("xresult-")
            and str(identity["execution_attempt_id"]).startswith("xattempt-")
            and outcome["outcome_classification"] in OUTCOME_CLASSIFICATIONS
            and outcome["result_capture_integrity_verified"] is True
            and outcome["execution_outcome_verification_authority_exercised"] is True
            and outcome["mission_success_completion_authority_exercised"] is False
            and bool(propagation["performed"]) == failure_required
            and semantics["stage357_result_is_authoritative_source"] is True
            and semantics["runtime_result_query_performed"] is False
            and semantics["runtime_control_io_performed"] is False
            and semantics["governance_query_performed"] is False
            and semantics["dispatch_redelivery_performed"] is False
            and semantics["new_target_action_dispatch_performed"] is False
            and semantics["success_does_not_imply_mission_completion"] is True
            and bool(semantics["mission_state_transition_performed"]) == failure_required
            and digest == sha256_hex({"hash_domain": OUTCOME_PROPAGATION_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_stage358_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": STAGE358_SCHEMA_VERSION,
        "allowed_source_states": sorted(TERMINATION_ALLOWED_STATES),
        "termination_control": {
            "schema_version": TERMINATION_CONTROL_SCHEMA_VERSION,
            "identity_prefix": TERMINATION_CONTROL_ID_PREFIX,
            "mode": TERMINATION_CONTROL_MODE,
            "authority": TERMINATION_CONTROL_AUTHORITY,
            "actions": sorted(TERMINATION_ACTIONS),
            "expected_terminal_state_by_action": dict(EXPECTED_TERMINAL_STATE_BY_ACTION),
            "runtime_control_channel": RUNTIME_TERMINATION_CONTROL_CHANNEL,
            "one_termination_control_per_execution_attempt": True,
            "requires_latest_stage356_running_projection": True,
            "requires_no_stage357_result_yet": True,
            "runtime_endpoint_reused_from_stage355": True,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": True,
            "runtime_control_io_performed": True,
            "governance_query_performed": False,
            "dispatch_redelivery_performed": False,
            "new_target_action_dispatch_performed": False,
            "mission_state_transition_performed": False,
        },
        "outcome_propagation": {
            "schema_version": TERMINAL_OUTCOME_PROPAGATION_SCHEMA_VERSION,
            "identity_prefix": OUTCOME_PROPAGATION_ID_PREFIX,
            "mode": OUTCOME_PROPAGATION_MODE,
            "authority": OUTCOME_PROPAGATION_AUTHORITY,
            "terminal_execution_states": sorted(TERMINAL_EXECUTION_STATES),
            "one_outcome_propagation_per_result_capture": True,
            "success_task_outcome": TASK_OUTCOME_COMPLETED,
            "success_mission_state_transition_performed": False,
            "success_does_not_imply_mission_completion": True,
            "failed_mission_state": "FAILED",
            "timed_out_mission_state": "FAILED",
            "cancelled_mission_state": "ABORTED",
            "abort_intent_mission_state": "ABORTED",
            "execution_outcome_verification_authority_exercised": True,
            "mission_success_completion_authority_exercised": False,
            "non_success_fail_fast_propagation": True,
            "runtime_result_query_performed": False,
            "runtime_control_io_performed": False,
            "governance_query_performed": False,
            "dispatch_redelivery_performed": False,
            "new_target_action_dispatch_performed": False,
        },
        "next_stage": "3.5.9",
    }
