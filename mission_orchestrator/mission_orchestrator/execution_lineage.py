from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence

from .errors import MissionValidationError
from .execution_attempt import verify_execution_attempt_contract
from .execution_delivery import verify_execution_delivery_contract
from .execution_result import verify_execution_result_capture_contract
from .execution_running import verify_running_execution_projection_contract
from .execution_termination import verify_outcome_propagation_contract, verify_termination_control_contract

EXECUTION_EVENT_LINEAGE_SCHEMA_VERSION = "apts-execution-event-lineage-v1"
EXECUTION_EVENT_REPLAY_SCHEMA_VERSION = "apts-execution-event-replay-v1"
EXECUTION_RECOVERY_CHECKPOINT_SCHEMA_VERSION = "apts-execution-recovery-checkpoint-v1"
EXECUTION_RECOVERY_CHECKPOINT_HASH_DOMAIN = "MISSION_EXECUTION_RECOVERY_CHECKPOINT_V1"
EXECUTION_RECOVERY_REQUEST_HASH_DOMAIN = "MISSION_EXECUTION_RECOVERY_REQUEST_V1"
EXECUTION_REPLAY_HASH_DOMAIN = "MISSION_EXECUTION_EVENT_REPLAY_V1"
EXECUTION_RECOVERY_CHECKPOINT_ID_PREFIX = "xrecover-"
EXECUTION_EVENT_LINEAGE_MODE = "CANONICAL_EXECUTION_EVENT_SUBCHAIN_WITH_ARTIFACT_CAUSATION_BINDINGS"
EXECUTION_REPLAY_MODE = "READ_ONLY_DETERMINISTIC_ORDERED_EXECUTION_REPLAY_NO_SIDE_EFFECTS"
EXECUTION_RECOVERY_MODE = "DURABLE_EXECUTION_ARTIFACT_RECONSTRUCTION_NO_RUNTIME_IO_NO_GOVERNANCE_QUERY_NO_REDISPATCH"
EXECUTION_RECOVERY_EVENT_TYPE = "MISSION_EXECUTION_RECOVERY_CHECKPOINTED"
EXECUTION_RECOVERY_ALLOWED_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})

EXECUTION_EVENT_TYPES = (
    "MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED",
    "MISSION_DISPATCH_ELIGIBILITY_PRECONDITIONS_SATISFIED",
    "MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED",
    "MISSION_EXECUTION_ATTEMPT_COMMITTED",
    "MISSION_EXECUTION_DISPATCH_DELIVERED_ACKNOWLEDGED",
    "MISSION_EXECUTION_RUNNING_HEARTBEAT_PROJECTED",
    "MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURED",
    "MISSION_EXECUTION_TERMINATION_CONTROL_ACKNOWLEDGED",
    "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED",
    EXECUTION_RECOVERY_EVENT_TYPE,
)

_ARTIFACT_ID_FIELDS = {
    "MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED": "execution_dispatch_id",
    "MISSION_DISPATCH_ELIGIBILITY_PRECONDITIONS_SATISFIED": "dispatch_eligibility_id",
    "MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED": "pre_dispatch_revalidation_id",
    "MISSION_EXECUTION_ATTEMPT_COMMITTED": "execution_attempt_id",
    "MISSION_EXECUTION_DISPATCH_DELIVERED_ACKNOWLEDGED": "execution_delivery_id",
    "MISSION_EXECUTION_RUNNING_HEARTBEAT_PROJECTED": "running_projection_id",
    "MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURED": "result_capture_id",
    "MISSION_EXECUTION_TERMINATION_CONTROL_ACKNOWLEDGED": "termination_control_id",
    "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED": "outcome_propagation_id",
    EXECUTION_RECOVERY_EVENT_TYPE: "checkpoint_id",
}

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_execution_attempt_id",
    "expected_execution_attempt_sha256",
    "expected_execution_delivery_id",
    "expected_execution_delivery_sha256",
    "expected_running_projection_id",
    "expected_running_projection_sha256",
    "expected_result_capture_id",
    "expected_result_capture_sha256",
    "expected_outcome_propagation_id",
    "expected_outcome_propagation_sha256",
    "expected_termination_control_count",
    "expected_execution_event_count",
    "expected_execution_event_tip_sha256",
    "created_by",
    "reason",
    "metadata",
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_execution_recovery_checkpoint_id() -> str:
    return f"{EXECUTION_RECOVERY_CHECKPOINT_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    raw = payload.get(key)
    if isinstance(raw, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 1:
        raise MissionValidationError(f"{key} must be >= 1")
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


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _require_string(payload, key, 64).lower()
    if _SHA256_RE.match(value) is None:
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_execution_recovery_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("execution recovery checkpoint request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported execution recovery checkpoint field(s): " + ", ".join(unknown)
            + "; Stage 3.5.9 reconstructs exclusively from canonical durable Stage-3.5.1 through Stage-3.5.8 artifacts and forbids caller-supplied runtime observations, authorization decisions, execution results, propagation results, recovery state, replay content, dispatch commands, or target actions"
        )

    values = {
        "idempotency_key": _require_string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _require_string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_attempt_id": _require_string(payload, "expected_execution_attempt_id"),
        "expected_execution_delivery_id": _require_string(payload, "expected_execution_delivery_id"),
        "expected_running_projection_id": _require_string(payload, "expected_running_projection_id"),
        "expected_result_capture_id": _require_string(payload, "expected_result_capture_id"),
        "expected_outcome_propagation_id": _require_string(payload, "expected_outcome_propagation_id"),
        "created_by": _require_string(payload, "created_by", 128),
    }
    for key, value in values.items():
        if _ID_RE.match(value) is None:
            raise MissionValidationError(f"{key} contains unsupported characters")
    prefix_requirements = {
        "expected_active_plan_version_record_id": "pver-",
        "expected_execution_attempt_id": "xattempt-",
        "expected_execution_delivery_id": "xack-",
        "expected_running_projection_id": "xrun-",
        "expected_result_capture_id": "xresult-",
        "expected_outcome_propagation_id": "xprop-",
    }
    for key, prefix in prefix_requirements.items():
        if not values[key].startswith(prefix):
            raise MissionValidationError(f"{key} must be a canonical {prefix}* identifier")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason in (None, ""):
        reason = None
    else:
        if not isinstance(reason, str) or not reason.strip():
            raise MissionValidationError("reason must be a non-empty string when provided")
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")

    return {
        **values,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_execution_attempt_sha256": _sha(payload, "expected_execution_attempt_sha256"),
        "expected_execution_delivery_sha256": _sha(payload, "expected_execution_delivery_sha256"),
        "expected_running_projection_sha256": _sha(payload, "expected_running_projection_sha256"),
        "expected_result_capture_sha256": _sha(payload, "expected_result_capture_sha256"),
        "expected_outcome_propagation_sha256": _sha(payload, "expected_outcome_propagation_sha256"),
        "expected_termination_control_count": _non_negative_int(payload, "expected_termination_control_count"),
        "expected_execution_event_count": _positive_int(payload, "expected_execution_event_count"),
        "expected_execution_event_tip_sha256": _sha(payload, "expected_execution_event_tip_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def execution_recovery_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": EXECUTION_RECOVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def is_execution_event(event: Mapping[str, Any]) -> bool:
    return str(event.get("event_type") or "") in EXECUTION_EVENT_TYPES


def build_execution_event_replay(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    selected = [dict(event) for event in events if is_execution_event(event)]
    replay_events = []
    for seq, event in enumerate(selected, 1):
        payload = dict(event.get("payload") or {})
        event_type = str(event.get("event_type") or "")
        artifact_id_field = _ARTIFACT_ID_FIELDS.get(event_type)
        replay_events.append(
            {
                "replay_sequence": seq,
                "event_id": event.get("event_id"),
                "event_type": event_type,
                "causation_id": event.get("causation_id"),
                "state_version": event.get("state_version"),
                "plan_version": event.get("plan_version"),
                "policy_version": event.get("policy_version"),
                "artifact_id": None if artifact_id_field is None else payload.get(artifact_id_field),
                "artifact_sha256": payload.get("canonical_sha256"),
                "event_sha256": event.get("canonical_sha256"),
                "previous_event_sha256": event.get("previous_event_sha256"),
                "occurred_at": event.get("occurred_at"),
            }
        )
    replay_core = {
        "schema_version": EXECUTION_EVENT_REPLAY_SCHEMA_VERSION,
        "mode": EXECUTION_REPLAY_MODE,
        "execution_event_count": len(replay_events),
        "events": replay_events,
    }
    replay_sha = sha256_hex({"hash_domain": EXECUTION_REPLAY_HASH_DOMAIN, "replay": replay_core})
    tip = None if not selected else selected[-1]
    return {
        **replay_core,
        "replay_sha256": replay_sha,
        "execution_event_tip_event_id": None if tip is None else tip.get("event_id"),
        "execution_event_tip_sha256": None if tip is None else tip.get("canonical_sha256"),
        "read_only": True,
        "side_effects_performed": False,
    }


def _artifact_ref(row: Mapping[str, Any], id_key: str) -> Dict[str, Any]:
    return {
        "id": row[id_key],
        "canonical_sha256": row["canonical_sha256"],
    }


def build_execution_recovery_checkpoint_contract(
    *,
    checkpoint_id: str,
    checkpoint_version: int,
    mission_id: str,
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    execution_attempt: Mapping[str, Any],
    execution_delivery: Mapping[str, Any],
    running_projection: Mapping[str, Any],
    result_capture: Mapping[str, Any],
    termination_control: Optional[Mapping[str, Any]],
    outcome_propagation: Mapping[str, Any],
    replay: Mapping[str, Any],
    created_by: str,
    reason: Optional[str],
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    if not verify_execution_attempt_contract(execution_attempt["execution_attempt_contract"]):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    if not verify_execution_delivery_contract(execution_delivery["execution_delivery_contract"]):
        raise MissionValidationError("Stage-3.5.5 execution-delivery contract failed integrity verification")
    if not verify_running_execution_projection_contract(running_projection["running_execution_projection_contract"]):
        raise MissionValidationError("Stage-3.5.6 running projection failed integrity verification")
    if not verify_execution_result_capture_contract(result_capture["execution_result_capture_contract"]):
        raise MissionValidationError("Stage-3.5.7 execution-result capture failed integrity verification")
    if termination_control is not None and not verify_termination_control_contract(termination_control["termination_control_contract"]):
        raise MissionValidationError("Stage-3.5.8 termination-control contract failed integrity verification")
    if not verify_outcome_propagation_contract(outcome_propagation["outcome_propagation_contract"]):
        raise MissionValidationError("Stage-3.5.8 outcome-propagation contract failed integrity verification")

    attempt_id = execution_attempt["execution_attempt_id"]
    if not all(
        row["execution_attempt_id"] == attempt_id
        for row in (execution_delivery, running_projection, result_capture, outcome_propagation)
    ):
        raise MissionValidationError("execution recovery sources do not share one execution_attempt_id")
    if termination_control is not None and termination_control["execution_attempt_id"] != attempt_id:
        raise MissionValidationError("termination-control source is bound to a different execution attempt")
    if outcome_propagation["result_capture_id"] != result_capture["result_capture_id"]:
        raise MissionValidationError("outcome propagation is not bound to the exact Stage-3.5.7 result capture")
    if result_capture["running_projection_id"] != running_projection["running_projection_id"]:
        raise MissionValidationError("result capture is not bound to the exact Stage-3.5.6 running projection")
    if running_projection["execution_delivery_id"] != execution_delivery["execution_delivery_id"]:
        raise MissionValidationError("running projection is not bound to the exact Stage-3.5.5 execution delivery")
    if execution_delivery["execution_attempt_id"] != execution_attempt["execution_attempt_id"]:
        raise MissionValidationError("execution delivery is not bound to the exact Stage-3.5.4 execution attempt")
    if execution_attempt["plan_version_record_id"] != active_plan["plan_version_record_id"]:
        raise MissionValidationError("execution attempt is not bound to the active Plan head")

    evidence_manifest = result_capture["execution_result_capture_contract"]["evidence_manifest"]
    artifact_manifest = result_capture["execution_result_capture_contract"]["artifact_manifest"]
    termination_ref = None if termination_control is None else _artifact_ref(termination_control, "termination_control_id")

    core = {
        "schema_version": EXECUTION_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "identity": {
            "checkpoint_id": checkpoint_id,
            "checkpoint_version": int(checkpoint_version),
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": execution_attempt["planned_task_id"],
            "task_key": execution_attempt["task_key"],
            "execution_attempt_id": attempt_id,
            "created_by": created_by,
            "created_at": created_at,
        },
        "source_bindings": {
            "state": source_state["state"],
            "state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan": _artifact_ref(active_plan, "plan_version_record_id"),
            "execution_attempt": _artifact_ref(execution_attempt, "execution_attempt_id"),
            "execution_delivery": _artifact_ref(execution_delivery, "execution_delivery_id"),
            "running_projection": _artifact_ref(running_projection, "running_projection_id"),
            "result_capture": _artifact_ref(result_capture, "result_capture_id"),
            "termination_control": termination_ref,
            "termination_control_count": 0 if termination_control is None else 1,
            "outcome_propagation": _artifact_ref(outcome_propagation, "outcome_propagation_id"),
            "execution_event_count": int(replay["execution_event_count"]),
            "execution_event_tip_event_id": replay["execution_event_tip_event_id"],
            "execution_event_tip_sha256": replay["execution_event_tip_sha256"],
            "execution_replay_sha256": replay["replay_sha256"],
        },
        "recovery_state": {
            "execution_dispatch_id": execution_attempt["execution_dispatch_id"],
            "execution_attempt_id": attempt_id,
            "dispatch_envelope_id": execution_attempt["dispatch_envelope_id"],
            "execution_delivery_id": execution_delivery["execution_delivery_id"],
            "running_projection_id": running_projection["running_projection_id"],
            "result_capture_id": result_capture["result_capture_id"],
            "termination_control_id": None if termination_control is None else termination_control["termination_control_id"],
            "outcome_propagation_id": outcome_propagation["outcome_propagation_id"],
            "execution_state": result_capture["execution_state"],
            "outcome_classification": outcome_propagation["outcome_classification"],
            "task_outcome_status": outcome_propagation["task_outcome_status"],
            "propagation_action": outcome_propagation["propagation_action"],
            "resulting_mission_state": outcome_propagation["resulting_mission_state"],
            "resulting_state_version": int(outcome_propagation["resulting_state_version"]),
            "evidence_count": int(result_capture["evidence_count"]),
            "evidence_manifest_sha256": result_capture["evidence_manifest_sha256"],
            "artifact_count": int(result_capture["artifact_count"]),
            "artifact_manifest_sha256": result_capture["artifact_manifest_sha256"],
            "evidence_items": list(evidence_manifest["items"]),
            "artifact_items": list(artifact_manifest["items"]),
            "terminal_execution_trajectory_reconstructed": True,
        },
        "replay": {
            "schema_version": replay["schema_version"],
            "mode": replay["mode"],
            "execution_event_count": int(replay["execution_event_count"]),
            "execution_event_tip_event_id": replay["execution_event_tip_event_id"],
            "execution_event_tip_sha256": replay["execution_event_tip_sha256"],
            "replay_sha256": replay["replay_sha256"],
            "event_ids": [item["event_id"] for item in replay["events"]],
        },
        "semantics": {
            "lineage_mode": EXECUTION_EVENT_LINEAGE_MODE,
            "replay_mode": EXECUTION_REPLAY_MODE,
            "recovery_mode": EXECUTION_RECOVERY_MODE,
            "durable_repository_is_source_of_truth": True,
            "requires_stage358_terminal_outcome_propagation": True,
            "runtime_health_probe_performed": False,
            "runtime_result_query_performed": False,
            "runtime_control_io_performed": False,
            "runtime_endpoint_resolution_performed": False,
            "external_network_io_performed": False,
            "governance_query_performed": False,
            "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False,
            "new_target_action_dispatch_performed": False,
            "mission_state_transition_performed": False,
            "failure_propagation_performed": False,
            "mission_success_completion_authority_exercised": False,
            "replay_is_execution": False,
            "recovery_is_authorization": False,
            "recovery_is_dispatch": False,
            "recovery_is_runtime_resumption": False,
            "recovery_is_lifecycle_transition": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": EXECUTION_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": EXECUTION_RECOVERY_CHECKPOINT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_execution_recovery_checkpoint_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != EXECUTION_RECOVERY_CHECKPOINT_SCHEMA_VERSION:
            return False
        identity = contract["identity"]
        source = contract["source_bindings"]
        recovery = contract["recovery_state"]
        replay = contract["replay"]
        semantics = contract["semantics"]
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        term_count = int(source.get("termination_control_count") or 0)
        term_ref = source.get("termination_control")
        return (
            str(identity.get("checkpoint_id") or "").startswith(EXECUTION_RECOVERY_CHECKPOINT_ID_PREFIX)
            and int(identity.get("checkpoint_version") or 0) >= 1
            and str(identity.get("execution_attempt_id") or "").startswith("xattempt-")
            and int(identity.get("plan_version") or 0) >= 1
            and source.get("state") in EXECUTION_RECOVERY_ALLOWED_STATES
            and int(source.get("state_version") or 0) >= 1
            and _SHA256_RE.match(str(source.get("source_version_sha256") or "")) is not None
            and str(source.get("active_plan", {}).get("id") or "").startswith("pver-")
            and _SHA256_RE.match(str(source.get("active_plan", {}).get("canonical_sha256") or "")) is not None
            and str(source.get("execution_attempt", {}).get("id") or "").startswith("xattempt-")
            and str(source.get("execution_delivery", {}).get("id") or "").startswith("xack-")
            and str(source.get("running_projection", {}).get("id") or "").startswith("xrun-")
            and str(source.get("result_capture", {}).get("id") or "").startswith("xresult-")
            and str(source.get("outcome_propagation", {}).get("id") or "").startswith("xprop-")
            and all(
                _SHA256_RE.match(str(source.get(key, {}).get("canonical_sha256") or "")) is not None
                for key in ("execution_attempt", "execution_delivery", "running_projection", "result_capture", "outcome_propagation")
            )
            and term_count in {0, 1}
            and ((term_count == 0 and term_ref is None) or (term_count == 1 and str(term_ref.get("id") or "").startswith("xterm-") and _SHA256_RE.match(str(term_ref.get("canonical_sha256") or "")) is not None))
            and int(source.get("execution_event_count") or 0) >= 8
            and _SHA256_RE.match(str(source.get("execution_event_tip_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("execution_replay_sha256") or "")) is not None
            and recovery.get("execution_attempt_id") == identity.get("execution_attempt_id")
            and recovery.get("execution_attempt_id") == source.get("execution_attempt", {}).get("id")
            and recovery.get("execution_delivery_id") == source.get("execution_delivery", {}).get("id")
            and recovery.get("running_projection_id") == source.get("running_projection", {}).get("id")
            and recovery.get("result_capture_id") == source.get("result_capture", {}).get("id")
            and recovery.get("outcome_propagation_id") == source.get("outcome_propagation", {}).get("id")
            and ((term_count == 0 and recovery.get("termination_control_id") is None) or (term_count == 1 and recovery.get("termination_control_id") == term_ref.get("id")))
            and recovery.get("execution_state") in {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"}
            and int(recovery.get("resulting_state_version") or 0) >= 1
            and int(recovery.get("evidence_count") or 0) >= 1
            and int(recovery.get("artifact_count") or 0) >= 0
            and _SHA256_RE.match(str(recovery.get("evidence_manifest_sha256") or "")) is not None
            and _SHA256_RE.match(str(recovery.get("artifact_manifest_sha256") or "")) is not None
            and replay.get("schema_version") == EXECUTION_EVENT_REPLAY_SCHEMA_VERSION
            and replay.get("mode") == EXECUTION_REPLAY_MODE
            and int(replay.get("execution_event_count") or 0) == int(source.get("execution_event_count") or 0)
            and replay.get("execution_event_tip_sha256") == source.get("execution_event_tip_sha256")
            and replay.get("replay_sha256") == source.get("execution_replay_sha256")
            and len(replay.get("event_ids") or []) == int(source.get("execution_event_count") or 0)
            and semantics.get("durable_repository_is_source_of_truth") is True
            and semantics.get("requires_stage358_terminal_outcome_propagation") is True
            and semantics.get("runtime_health_probe_performed") is False
            and semantics.get("runtime_result_query_performed") is False
            and semantics.get("runtime_control_io_performed") is False
            and semantics.get("runtime_endpoint_resolution_performed") is False
            and semantics.get("external_network_io_performed") is False
            and semantics.get("governance_query_performed") is False
            and semantics.get("dispatch_redelivery_performed") is False
            and semantics.get("new_execution_attempt_created") is False
            and semantics.get("new_target_action_dispatch_performed") is False
            and semantics.get("mission_state_transition_performed") is False
            and semantics.get("failure_propagation_performed") is False
            and semantics.get("mission_success_completion_authority_exercised") is False
            and semantics.get("replay_is_execution") is False
            and semantics.get("recovery_is_authorization") is False
            and semantics.get("recovery_is_dispatch") is False
            and semantics.get("recovery_is_runtime_resumption") is False
            and semantics.get("recovery_is_lifecycle_transition") is False
            and semantics.get("target_actuation") is False
            and integrity.get("hash_domain") == EXECUTION_RECOVERY_CHECKPOINT_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex({"hash_domain": EXECUTION_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core})
        )
    except Exception:
        return False


def canonical_execution_event_lineage_definition() -> Dict[str, Any]:
    return {
        "lineage_schema_version": EXECUTION_EVENT_LINEAGE_SCHEMA_VERSION,
        "replay_schema_version": EXECUTION_EVENT_REPLAY_SCHEMA_VERSION,
        "recovery_checkpoint_schema_version": EXECUTION_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "lineage_mode": EXECUTION_EVENT_LINEAGE_MODE,
        "replay_mode": EXECUTION_REPLAY_MODE,
        "recovery_mode": EXECUTION_RECOVERY_MODE,
        "checkpoint_id_prefix": EXECUTION_RECOVERY_CHECKPOINT_ID_PREFIX,
        "allowed_states": sorted(EXECUTION_RECOVERY_ALLOWED_STATES),
        "execution_event_types": list(EXECUTION_EVENT_TYPES),
        "requires_stage354_execution_attempt": True,
        "requires_stage355_execution_delivery": True,
        "requires_stage356_running_projection": True,
        "requires_stage357_terminal_result_capture": True,
        "requires_stage358_terminal_outcome_propagation": True,
        "termination_control_optional_and_cardinality_at_most_one": True,
        "one_immutable_checkpoint_per_outcome_propagation": True,
        "replay_read_only": True,
        "restart_recovery_from_durable_repository": True,
        "runtime_health_probe_on_recovery": False,
        "runtime_result_query_on_recovery": False,
        "runtime_control_io_on_recovery": False,
        "runtime_endpoint_resolution_on_recovery": False,
        "external_network_io_on_recovery": False,
        "governance_query_on_recovery": False,
        "dispatch_redelivery_on_recovery": False,
        "new_execution_attempt_on_recovery": False,
        "new_target_action_dispatch_on_recovery": False,
        "mission_state_transition_on_recovery": False,
        "failure_propagation_on_recovery": False,
        "mission_success_completion_authority_exercised": False,
        "replay_is_execution": False,
        "recovery_is_authorization": False,
        "recovery_is_dispatch": False,
        "recovery_is_runtime_resumption": False,
        "recovery_is_lifecycle_transition": False,
        "target_actuation": False,
        "next_stage": "3.5.10",
    }
