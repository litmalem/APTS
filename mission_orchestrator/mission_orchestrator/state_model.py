from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError

STATE_SCHEMA_VERSION = "apts-global-mission-state-v1"
TRANSITION_SCHEMA_VERSION = "apts-global-mission-state-transition-v1"
INITIAL_STATE = "CREATED"
TRANSITION_ID_PREFIX = "mtrans-"

CANONICAL_STATES = (
    "CREATED",
    "PIP_BOUND",
    "PLANNING",
    "RUNNING",
    "WAITING_EVIDENCE",
    "WAITING_APPROVAL",
    "REPLANNING",
    "PAUSED",
    "CLEANING_UP",
    "COMPLETED",
    "ABORTED",
    "FAILED",
    "EXPIRED",
)

TERMINAL_STATES = frozenset({"COMPLETED", "ABORTED", "FAILED", "EXPIRED"})

# Canonical global lifecycle topology. FAILED / ABORTED / EXPIRED are added to
# every non-terminal state below as fail/abort/expiry exits. COMPLETED is only
# reachable through CLEANING_UP so completion cannot bypass finalization.
_BASE_TRANSITIONS = {
    "CREATED": {"PIP_BOUND", "PAUSED"},
    "PIP_BOUND": {"PLANNING", "PAUSED"},
    "PLANNING": {"RUNNING", "WAITING_EVIDENCE", "WAITING_APPROVAL", "PAUSED"},
    "RUNNING": {"WAITING_EVIDENCE", "WAITING_APPROVAL", "REPLANNING", "PAUSED", "CLEANING_UP"},
    "WAITING_EVIDENCE": {"RUNNING", "REPLANNING", "PAUSED"},
    "WAITING_APPROVAL": {"RUNNING", "REPLANNING", "PAUSED"},
    "REPLANNING": {"RUNNING", "WAITING_EVIDENCE", "WAITING_APPROVAL", "PAUSED"},
    "PAUSED": {"PIP_BOUND", "PLANNING", "RUNNING", "REPLANNING", "CLEANING_UP"},
    "CLEANING_UP": {"COMPLETED"},
    "COMPLETED": set(),
    "ABORTED": set(),
    "FAILED": set(),
    "EXPIRED": set(),
}

FAIL_CLOSED_TERMINALS = {"FAILED", "ABORTED", "EXPIRED"}
ALLOWED_TRANSITIONS = {
    state: frozenset(targets | (FAIL_CLOSED_TERMINALS if state not in TERMINAL_STATES else set()))
    for state, targets in _BASE_TRANSITIONS.items()
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_TRANSITION_FIELDS = {
    "expected_state_version",
    "to_state",
    "actor",
    "reason_code",
    "reason",
    "evidence_refs",
    "metadata",
}


def new_transition_id() -> str:
    return f"{TRANSITION_ID_PREFIX}{uuid.uuid4()}"


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def allowed_targets(state: str) -> list[str]:
    return sorted(ALLOWED_TRANSITIONS.get(state, frozenset()))


def is_legal_transition(from_state: str, to_state: str) -> bool:
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


def _require_string(obj: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = obj.get(key)
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
    normalized: list[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError("evidence_refs entries must be non-empty strings")
        item = item.strip()
        if len(item) > 256:
            raise MissionValidationError("evidence_refs entry exceeds 256 characters")
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def normalize_transition_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("state transition request body must be a JSON object")

    unknown = sorted(set(payload.keys()) - _TRANSITION_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported state transition field(s): " + ", ".join(unknown) + "; put extensions under metadata"
        )

    try:
        expected_state_version = int(payload.get("expected_state_version"))
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("expected_state_version is required and must be an integer") from exc
    if expected_state_version < 1:
        raise MissionValidationError("expected_state_version must be >= 1")

    to_state = _require_string(payload, "to_state", 40).upper()
    if to_state not in CANONICAL_STATES:
        raise MissionValidationError(
            "to_state is not canonical; expected one of: " + ", ".join(CANONICAL_STATES)
        )

    actor = _require_string(payload, "actor")
    reason_code = _require_string(payload, "reason_code", 80).upper()
    if not _ID_RE.match(reason_code):
        raise MissionValidationError("reason_code contains unsupported characters")

    reason = payload.get("reason")
    if reason is not None:
        if not isinstance(reason, str):
            raise MissionValidationError("reason must be a string when provided")
        reason = reason.strip() or None
        if reason is not None and len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")

    evidence_refs = _normalize_evidence_refs(payload.get("evidence_refs"))
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    try:
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("metadata must contain JSON-serializable values") from exc

    return {
        "expected_state_version": expected_state_version,
        "to_state": to_state,
        "actor": actor,
        "reason_code": reason_code,
        "reason": reason,
        "evidence_refs": evidence_refs,
        "metadata": dict(metadata),
    }
