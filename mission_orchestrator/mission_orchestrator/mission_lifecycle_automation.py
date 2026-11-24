from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .state_model import CANONICAL_STATES, TERMINAL_STATES

LIFECYCLE_AUTOMATION_SCHEMA_VERSION = "apts-mission-lifecycle-automation-v1"
LIFECYCLE_AUTOMATION_MODE = "TYPED_EVENT_TO_GUARDED_IDEMPOTENT_LIFECYCLE_COMMAND_FAIL_CLOSED"
LIFECYCLE_AUTOMATION_AUTHORITY_SEMANTICS = (
    "MISSION_LIFECYCLE_EVENT_TRIGGER_ONLY_NOT_GOVERNANCE_AUTHORIZATION_PLANNER_OR_TARGET_EXECUTION"
)
LIFECYCLE_AUTOMATION_SOURCE_EVENT_IDEMPOTENCY = "SOURCE_COMPONENT_PLUS_EVENT_ID_CANONICAL_FINGERPRINT"
LIFECYCLE_AUTOMATION_REPLAY_MODE = "DURABLE_RECEIPT_OUTCOME_PLUS_EXISTING_COMMAND_JOURNAL"
LIFECYCLE_AUTOMATION_STALE_POLICY = "REJECT_BEFORE_MUTATION_EXACT_STATE_VERSION_VECTOR_BINDING"

MISSION_LIFECYCLE_EVENT_RECEIVED = "MISSION_LIFECYCLE_EVENT_RECEIVED"
MISSION_LIFECYCLE_EVENT_APPLIED = "MISSION_LIFECYCLE_EVENT_APPLIED"
MISSION_LIFECYCLE_EVENT_REJECTED = "MISSION_LIFECYCLE_EVENT_REJECTED"

# Stage 3.2.9 deliberately maps typed external/internal lifecycle signals to the
# existing Stage-3.2 lifecycle command vocabulary.  The mapping is a proposal
# only: the generated command must still pass the canonical state/version gate
# and the Stage-3.2.2..3.2.8 lifecycle guards before any state transition is
# committed.
EVENT_TO_COMMAND = {
    "PIP_BIND_REQUESTED": "BIND_PIP",
    "PLANNING_START_REQUESTED": "START_PLANNING",
    "RUN_START_REQUESTED": "START",
    "EVIDENCE_REQUIRED": "WAIT_FOR_EVIDENCE",
    "APPROVAL_REQUIRED": "WAIT_FOR_APPROVAL",
    "EVIDENCE_READY": "START",
    "APPROVAL_GRANTED": "START",
    "PAUSE_REQUESTED": "PAUSE",
    "RESUME_REQUESTED": "RESUME",
    "REPLAN_REQUESTED": "REPLAN",
    "REPLAN_READY": "START",
    "CLEANUP_REQUESTED": "BEGIN_CLEANUP",
    "COMPLETION_VERIFIED": "COMPLETE",
    "ABORT_REQUESTED": "ABORT",
    "FAILURE_DETECTED": "FAIL",
    "EXPIRATION_REACHED": "EXPIRE",
}

EVENT_SOURCE_STATES = {
    "PIP_BIND_REQUESTED": ("CREATED",),
    "PLANNING_START_REQUESTED": ("PIP_BOUND",),
    "RUN_START_REQUESTED": ("PLANNING",),
    "EVIDENCE_REQUIRED": ("PLANNING", "RUNNING", "REPLANNING"),
    "APPROVAL_REQUIRED": ("PLANNING", "RUNNING", "REPLANNING"),
    "EVIDENCE_READY": ("WAITING_EVIDENCE",),
    "APPROVAL_GRANTED": ("WAITING_APPROVAL",),
    "PAUSE_REQUESTED": (
        "CREATED",
        "PIP_BOUND",
        "PLANNING",
        "RUNNING",
        "WAITING_EVIDENCE",
        "WAITING_APPROVAL",
        "REPLANNING",
    ),
    "RESUME_REQUESTED": ("PAUSED",),
    "REPLAN_REQUESTED": ("RUNNING", "WAITING_EVIDENCE", "WAITING_APPROVAL"),
    "REPLAN_READY": ("REPLANNING",),
    "CLEANUP_REQUESTED": ("RUNNING", "PAUSED"),
    "COMPLETION_VERIFIED": ("CLEANING_UP",),
    "ABORT_REQUESTED": tuple(state for state in CANONICAL_STATES if state not in TERMINAL_STATES),
    "FAILURE_DETECTED": tuple(state for state in CANONICAL_STATES if state not in TERMINAL_STATES),
    "EXPIRATION_REACHED": tuple(state for state in CANONICAL_STATES if state not in TERMINAL_STATES),
}

EVENT_METADATA_REQUIREMENTS = {
    "EVIDENCE_REQUIRED": "metadata.dependency",
    "APPROVAL_REQUIRED": "metadata.dependency",
    "EVIDENCE_READY": "metadata.dependency_resolution",
    "APPROVAL_GRANTED": "metadata.dependency_resolution",
    "RESUME_REQUESTED": "target_state",
    "COMPLETION_VERIFIED": "metadata.completion",
}

LIFECYCLE_AUTOMATION_EVENT_TYPES = tuple(EVENT_TO_COMMAND.keys())

_EVENT_FIELDS = {
    "event_id",
    "event_type",
    "source_component",
    "occurred_at",
    "observed_state",
    "observed_state_version",
    "observed_version_sha256",
    "actor",
    "reason_code",
    "reason",
    "evidence_refs",
    "target_state",
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


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _normalize_evidence_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError("evidence_refs must be an array")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError("evidence_refs entries must be non-empty strings")
        normalized = item.strip()
        if len(normalized) > 256:
            raise MissionValidationError("evidence_refs entry exceeds 256 characters")
        if normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _normalize_occurred_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError("occurred_at is required and must be an ISO-8601 timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MissionValidationError("occurred_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise MissionValidationError("occurred_at must include an explicit timezone offset")
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize_json_object(payload: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def normalize_lifecycle_automation_event(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("mission lifecycle event request body must be a JSON object")

    unknown = sorted(set(payload) - _EVENT_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported mission lifecycle event field(s): "
            + ", ".join(unknown)
            + "; put extensions under metadata"
        )

    event_id = _require_string(payload, "event_id")
    source_component = _require_string(payload, "source_component", 100)
    actor = _require_string(payload, "actor")
    if not _ID_RE.match(event_id):
        raise MissionValidationError("event_id contains unsupported characters")
    if not _ID_RE.match(source_component):
        raise MissionValidationError("source_component contains unsupported characters")

    event_type = _require_string(payload, "event_type", 80).upper()
    if event_type not in EVENT_TO_COMMAND:
        raise MissionValidationError(
            "unsupported mission lifecycle event_type; expected one of: "
            + ", ".join(LIFECYCLE_AUTOMATION_EVENT_TYPES)
        )

    observed_state = _require_string(payload, "observed_state", 40).upper()
    if observed_state not in CANONICAL_STATES:
        raise MissionValidationError("observed_state is not a canonical Mission state")
    allowed_sources = EVENT_SOURCE_STATES[event_type]
    if observed_state not in allowed_sources:
        raise MissionValidationError(
            f"event_type={event_type} is not valid for observed_state={observed_state}; "
            f"expected one of: {', '.join(allowed_sources)}"
        )

    try:
        observed_state_version = int(payload.get("observed_state_version"))
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("observed_state_version is required and must be an integer") from exc
    if observed_state_version < 1:
        raise MissionValidationError("observed_state_version must be >= 1")

    observed_version_sha256 = _require_string(payload, "observed_version_sha256", 64).lower()
    if not _SHA256_RE.match(observed_version_sha256):
        raise MissionValidationError("observed_version_sha256 must be a lowercase SHA-256 hex digest")

    target_state = payload.get("target_state")
    if target_state is not None:
        if not isinstance(target_state, str) or not target_state.strip():
            raise MissionValidationError("target_state must be a non-empty string when provided")
        target_state = target_state.strip().upper()
        if target_state not in CANONICAL_STATES:
            raise MissionValidationError("target_state is not a canonical Mission state")
    if event_type == "RESUME_REQUESTED" and target_state is None:
        raise MissionValidationError("RESUME_REQUESTED requires target_state")
    if event_type != "RESUME_REQUESTED" and target_state is not None:
        raise MissionValidationError("target_state is only accepted for RESUME_REQUESTED")

    reason_code = payload.get("reason_code")
    if reason_code is None:
        reason_code = f"AUTO_{event_type}"
    if not isinstance(reason_code, str) or not reason_code.strip():
        raise MissionValidationError("reason_code must be a non-empty string when provided")
    reason_code = reason_code.strip().upper()
    if len(reason_code) > 80 or not _ID_RE.match(reason_code):
        raise MissionValidationError("reason_code contains unsupported characters or exceeds 80 characters")

    reason = payload.get("reason")
    if reason is not None:
        if not isinstance(reason, str):
            raise MissionValidationError("reason must be a string when provided")
        reason = reason.strip() or None
        if reason is not None and len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")

    metadata = _normalize_json_object(payload, "metadata")
    evidence_refs = _normalize_evidence_refs(payload.get("evidence_refs"))

    # Request-shape prerequisites remain explicit.  Their semantic validity is
    # still enforced by the Stage-3.2 lifecycle guard at execution time.
    if event_type in {"EVIDENCE_REQUIRED", "APPROVAL_REQUIRED"} and not isinstance(metadata.get("dependency"), dict):
        raise MissionValidationError(f"{event_type} requires metadata.dependency")
    if event_type in {"EVIDENCE_READY", "APPROVAL_GRANTED"} and not isinstance(metadata.get("dependency_resolution"), dict):
        raise MissionValidationError(f"{event_type} requires metadata.dependency_resolution")
    if event_type == "COMPLETION_VERIFIED" and not isinstance(metadata.get("completion"), dict):
        raise MissionValidationError("COMPLETION_VERIFIED requires metadata.completion")

    return {
        "schema_version": LIFECYCLE_AUTOMATION_SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "source_component": source_component,
        "occurred_at": _normalize_occurred_at(payload.get("occurred_at")),
        "observed_state": observed_state,
        "observed_state_version": observed_state_version,
        "observed_version_sha256": observed_version_sha256,
        "actor": actor,
        "reason_code": reason_code,
        "reason": reason,
        "evidence_refs": evidence_refs,
        "target_state": target_state,
        "metadata": metadata,
    }


def lifecycle_automation_event_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": "APTS_MISSION_LIFECYCLE_AUTOMATION_EVENT_V1", "event": dict(normalized)})


def lifecycle_automation_key(normalized: Mapping[str, Any]) -> str:
    identity = f"{normalized['source_component']}\x00{normalized['event_id']}"
    return "lauto-source:" + sha256_hex(identity)


def lifecycle_automation_command_ids(normalized: Mapping[str, Any]) -> tuple[str, str]:
    digest = sha256_hex(f"{normalized['source_component']}\x00{normalized['event_id']}")[:40]
    return f"lauto-{digest}", f"lauto-idem-{digest}"


def build_lifecycle_automation_command(normalized: Mapping[str, Any]) -> Dict[str, Any]:
    event_type = str(normalized["event_type"])
    command = EVENT_TO_COMMAND[event_type]
    command_id, idempotency_key = lifecycle_automation_command_ids(normalized)
    signal_sha256 = lifecycle_automation_event_fingerprint(normalized)

    metadata = dict(normalized.get("metadata") or {})
    metadata["lifecycle_automation"] = {
        "schema_version": LIFECYCLE_AUTOMATION_SCHEMA_VERSION,
        "mode": LIFECYCLE_AUTOMATION_MODE,
        "source_event_id": normalized["event_id"],
        "source_event_type": event_type,
        "source_component": normalized["source_component"],
        "source_occurred_at": normalized["occurred_at"],
        "observed_state": normalized["observed_state"],
        "observed_state_version": int(normalized["observed_state_version"]),
        "observed_version_sha256": normalized["observed_version_sha256"],
        "signal_sha256": signal_sha256,
        "authority_semantics": LIFECYCLE_AUTOMATION_AUTHORITY_SEMANTICS,
        "governance_authorization_query_performed": False,
        "planner_invocation_performed": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }

    result: Dict[str, Any] = {
        "command_id": command_id,
        "idempotency_key": idempotency_key,
        "command": command,
        "expected_version_sha256": normalized["observed_version_sha256"],
        "expected_state_version": int(normalized["observed_state_version"]),
        "actor": normalized["actor"],
        "reason_code": normalized["reason_code"],
        "reason": normalized.get("reason") or (
            f"Stage 3.2.9 lifecycle automation from {normalized['source_component']}:{normalized['event_id']}"
        ),
        "evidence_refs": list(normalized.get("evidence_refs") or []),
        "metadata": metadata,
    }
    if command == "RESUME":
        result["target_state"] = normalized["target_state"]
    return result


def lifecycle_automation_contract() -> Dict[str, Any]:
    return {
        "schema_version": LIFECYCLE_AUTOMATION_SCHEMA_VERSION,
        "mode": LIFECYCLE_AUTOMATION_MODE,
        "authority_semantics": LIFECYCLE_AUTOMATION_AUTHORITY_SEMANTICS,
        "source_event_idempotency": LIFECYCLE_AUTOMATION_SOURCE_EVENT_IDEMPOTENCY,
        "replay_mode": LIFECYCLE_AUTOMATION_REPLAY_MODE,
        "stale_event_policy": LIFECYCLE_AUTOMATION_STALE_POLICY,
        "event_to_command": dict(EVENT_TO_COMMAND),
        "event_source_states": {key: list(value) for key, value in EVENT_SOURCE_STATES.items()},
        "event_metadata_requirements": dict(EVENT_METADATA_REQUIREMENTS),
        "supported_event_types": list(LIFECYCLE_AUTOMATION_EVENT_TYPES),
        "pipeline": [
            "NORMALIZE_TYPED_EVENT",
            "DURABLE_RECEIPT_AND_FINGERPRINT_DEDUP",
            "EXACT_STATE_AND_VERSION_VECTOR_CHECK",
            "TRANSLATE_TO_CANONICAL_LIFECYCLE_COMMAND",
            "EXISTING_COMMAND_JOURNAL_IDEMPOTENCY_GATE",
            "STAGE_3_2_LIFECYCLE_GUARD_CHAIN",
            "CANONICAL_STATE_TRANSITION_COMMIT",
            "DURABLE_APPLIED_OR_REJECTED_OUTCOME_EVENT",
        ],
        "blind_state_mutation_allowed": False,
        "direct_state_transition_api_used_by_automation": False,
        "governance_authorization_query_performed": False,
        "governance_decision_synthesized": False,
        "planner_invocation_performed": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
