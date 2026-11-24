from __future__ import annotations

import json
import re
from typing import Any, Dict, Mapping

from .canonical import verify_envelope
from .errors import MissionLifecycleGuardRejected, MissionValidationError
from .state_model import CANONICAL_STATES, TERMINAL_STATES, is_legal_transition

LIFECYCLE_COMMAND_SCHEMA_VERSION = "apts-mission-lifecycle-command-v1"
LIFECYCLE_COMMAND_MODE = "EXPLICIT_COMMAND_TO_CANONICAL_STATE_VIA_GUARDED_COMMAND_JOURNAL"
LIFECYCLE_COMMAND_OPERATION = "LIFECYCLE_COMMAND"

GUARD_MATRIX_SCHEMA_VERSION = "apts-mission-lifecycle-guard-matrix-v1"
GUARD_MATRIX_MODE = "DETERMINISTIC_LOCAL_PRECONDITION_FAIL_CLOSED"
GUARD_MATRIX_APPLIES_TO = "LIFECYCLE_COMMAND"
GUARD_MATRIX_AUTHORITY_SEMANTICS = "MISSION_LIFECYCLE_CONTROL_ONLY_NOT_GOVERNANCE_AUTHORIZATION"

ACTIVATION_SCHEMA_VERSION = "apts-mission-pip-activation-v1"
ACTIVATION_MODE = "CREATED_TO_PIP_BOUND_FROM_IMMUTABLE_CANONICAL_PIP_BINDING"
ACTIVATION_COMMAND = "BIND_PIP"
ACTIVATION_FROM_STATE = "CREATED"
ACTIVATION_TO_STATE = "PIP_BOUND"
ACTIVATION_AUTHORITY_SEMANTICS = "MISSION_ORCHESTRATOR_LIFECYCLE_BINDING_ONLY_PIP_ARTIFACT_AUTHORITY_EXTERNAL"

PLANNING_RUN_ACTIVATION_SCHEMA_VERSION = "apts-mission-planning-run-activation-v1"
PLANNING_RUN_ACTIVATION_MODE = "PIP_BOUND_TO_PLANNING_TO_RUNNING_WITH_LOCAL_LINEAGE_PROOFS"
PLANNING_ACTIVATION_COMMAND = "START_PLANNING"
PLANNING_ACTIVATION_FROM_STATE = "PIP_BOUND"
PLANNING_ACTIVATION_TO_STATE = "PLANNING"
RUN_ACTIVATION_COMMAND = "START"
RUN_ACTIVATION_FROM_STATE = "PLANNING"
RUN_ACTIVATION_TO_STATE = "RUNNING"
PLANNING_RUN_ACTIVATION_AUTHORITY_SEMANTICS = (
    "MISSION_LIFECYCLE_PHASE_ACTIVATION_ONLY_NOT_PLANNER_OR_GOVERNANCE_AUTHORIZATION"
)

WAITING_DEPENDENCY_SCHEMA_VERSION = "apts-mission-waiting-dependency-control-v1"
WAITING_DEPENDENCY_MODE = "EXPLICIT_WAIT_DECLARATION_AND_LOCAL_RESOLUTION_EVIDENCE_FAIL_CLOSED"
WAITING_DEPENDENCY_AUTHORITY_SEMANTICS = (
    "MISSION_LIFECYCLE_DEPENDENCY_CONTROL_ONLY_NOT_GOVERNANCE_AUTHORIZATION"
)
WAIT_COMMAND_KIND = {
    "WAIT_FOR_EVIDENCE": "EVIDENCE",
    "WAIT_FOR_APPROVAL": "APPROVAL",
}
WAIT_STATE_KIND = {
    "WAITING_EVIDENCE": "EVIDENCE",
    "WAITING_APPROVAL": "APPROVAL",
}
WAIT_KIND_STATE = {kind: state for state, kind in WAIT_STATE_KIND.items()}
DEPENDENCY_RESOLUTION_STATUS = "SATISFIED"

PAUSE_RESUME_REPLAN_SCHEMA_VERSION = "apts-mission-pause-resume-replan-control-v1"
PAUSE_RESUME_REPLAN_MODE = "DURABLE_PAUSE_CONTEXT_MATCHED_RESUME_AND_REPLAN_READINESS_FAIL_CLOSED"
PAUSE_RESUME_REPLAN_AUTHORITY_SEMANTICS = (
    "MISSION_LIFECYCLE_CONTROL_ONLY_NOT_PLANNER_GOVERNANCE_AUTHORIZATION_OR_TARGET_EXECUTION"
)
REPLAN_READINESS_STATUS = "READY"

TERMINAL_SEMANTICS_SCHEMA_VERSION = "apts-mission-terminal-semantics-v1"
TERMINAL_SEMANTICS_MODE = "DURABLE_TYPED_TERMINATION_CAUSE_WITH_IMMUTABLE_FINALITY_FAIL_CLOSED"
TERMINAL_SEMANTICS_AUTHORITY_SEMANTICS = (
    "MISSION_LIFECYCLE_TERMINATION_ONLY_NOT_GOVERNANCE_AUTHORIZATION_CLEANUP_COMPLETION_OR_TARGET_EXECUTION"
)
TERMINAL_COMMAND_TARGETS = {
    "ABORT": "ABORTED",
    "FAIL": "FAILED",
    "EXPIRE": "EXPIRED",
}
TERMINAL_SEMANTIC_PROFILES = {
    "ABORT": {
        "terminal_state": "ABORTED",
        "cause_family": "CONTROLLED_STOP",
        "disposition": "INTENTIONAL_ABORT",
        "meaning": "MISSION_STOPPED_BY_EXPLICIT_CONTROL_INTENT",
    },
    "FAIL": {
        "terminal_state": "FAILED",
        "cause_family": "FAILURE",
        "disposition": "UNRECOVERABLE_FAILURE",
        "meaning": "MISSION_CANNOT_CONTINUE_TO_OBJECTIVE_UNDER_CURRENT_MISSION",
    },
    "EXPIRE": {
        "terminal_state": "EXPIRED",
        "cause_family": "EXPIRATION",
        "disposition": "VALIDITY_EXPIRED",
        "meaning": "MISSION_VALIDITY_OR_TIME_HORIZON_NO_LONGER_PERMITS_CONTINUATION",
    },
}
TERMINAL_RECOVERY_SEMANTICS = "NEW_MISSION_OR_EXPLICIT_REVISION_REQUIRED_NO_RESUME"

CLEANUP_COMPLETION_SCHEMA_VERSION = "apts-mission-cleanup-completion-gate-v1"
CLEANUP_COMPLETION_MODE = "DURABLE_CLEANUP_LINEAGE_AND_EVIDENCE_GATED_VERIFIED_COMPLETION_FAIL_CLOSED"
CLEANUP_COMPLETION_AUTHORITY_SEMANTICS = (
    "MISSION_LIFECYCLE_COMPLETION_VERIFICATION_ONLY_NOT_GOVERNANCE_AUTHORIZATION_OR_TARGET_EXECUTION"
)
CLEANUP_COMMAND = "BEGIN_CLEANUP"
CLEANUP_STATE = "CLEANING_UP"
COMPLETION_COMMAND = "COMPLETE"
COMPLETION_STATE = "COMPLETED"
COMPLETION_VERIFICATION_STATUS = "VERIFIED"
OBJECTIVE_COMPLETION_STATUS = "SATISFIED"
SUCCESS_CRITERIA_COMPLETION_STATUS = "SATISFIED"
CLEANUP_VERIFICATION_STATUS = "VERIFIED"
CLEANUP_CHECK_STATUS = "PASS"

# Stage 3.2.6 deliberately narrows RESUME semantics by the state that was
# actually paused.  A paused waiting dependency cannot be resumed directly to
# RUNNING because that would bypass Stage-3.2.5 dependency resolution; its safe
# continuation is REPLANNING.  CREATED remains pausable as a fail-safe
# containment state, but has no resumable target in the Stage-3.1.2 topology.
PAUSED_SOURCE_RESUME_TARGETS = {
    "CREATED": (),
    "PIP_BOUND": ("PIP_BOUND",),
    "PLANNING": ("PLANNING",),
    "RUNNING": ("RUNNING",),
    "WAITING_EVIDENCE": ("REPLANNING",),
    "WAITING_APPROVAL": ("REPLANNING",),
    "REPLANNING": ("REPLANNING",),
}

LIFECYCLE_COMMANDS = (
    "BIND_PIP",
    "START_PLANNING",
    "START",
    "WAIT_FOR_EVIDENCE",
    "WAIT_FOR_APPROVAL",
    "PAUSE",
    "RESUME",
    "REPLAN",
    "BEGIN_CLEANUP",
    "COMPLETE",
    "ABORT",
    "FAIL",
    "EXPIRE",
)

FIXED_TARGETS = {
    "BIND_PIP": "PIP_BOUND",
    "START_PLANNING": "PLANNING",
    "START": "RUNNING",
    "WAIT_FOR_EVIDENCE": "WAITING_EVIDENCE",
    "WAIT_FOR_APPROVAL": "WAITING_APPROVAL",
    "PAUSE": "PAUSED",
    "REPLAN": "REPLANNING",
    "BEGIN_CLEANUP": "CLEANING_UP",
    "COMPLETE": "COMPLETED",
    "ABORT": "ABORTED",
    "FAIL": "FAILED",
    "EXPIRE": "EXPIRED",
}

# RESUME remains explicit because PAUSED can legally return to more than one
# canonical state.  Stage 3.2.2 adds a source-state guard: RESUME itself is only
# valid from PAUSED; returning from WAITING/REPLANNING to RUNNING continues to
# use START until later event/dependency stages introduce richer automation.
RESUME_TARGETS = (
    "PIP_BOUND",
    "PLANNING",
    "RUNNING",
    "REPLANNING",
    "CLEANING_UP",
)

_NON_TERMINAL_STATES = tuple(state for state in CANONICAL_STATES if state not in TERMINAL_STATES)

# Stage 3.2.2 is deliberately more semantic than Stage-3.1 topology.  Example:
# PAUSED -> RUNNING is topologically legal, but START is rejected there because
# the lifecycle intent must be RESUME.  Fail-safe terminal exits stay available
# from every non-terminal state and are not blocked by missing operational
# prerequisites such as PIP metadata.
COMMAND_SOURCE_STATES = {
    "BIND_PIP": ("CREATED",),
    "START_PLANNING": ("PIP_BOUND",),
    "START": ("PLANNING", "WAITING_EVIDENCE", "WAITING_APPROVAL", "REPLANNING"),
    "WAIT_FOR_EVIDENCE": ("PLANNING", "RUNNING", "REPLANNING"),
    "WAIT_FOR_APPROVAL": ("PLANNING", "RUNNING", "REPLANNING"),
    "PAUSE": (
        "CREATED",
        "PIP_BOUND",
        "PLANNING",
        "RUNNING",
        "WAITING_EVIDENCE",
        "WAITING_APPROVAL",
        "REPLANNING",
    ),
    "RESUME": ("PAUSED",),
    "REPLAN": ("RUNNING", "WAITING_EVIDENCE", "WAITING_APPROVAL"),
    "BEGIN_CLEANUP": ("RUNNING", "PAUSED"),
    "COMPLETE": ("CLEANING_UP",),
    "ABORT": _NON_TERMINAL_STATES,
    "FAIL": _NON_TERMINAL_STATES,
    "EXPIRE": _NON_TERMINAL_STATES,
}

# PIP is an immutable mission-envelope prerequisite, not an authorization
# decision.  Once the lifecycle attempts to enter or operate beyond PIP_BOUND,
# the canonical envelope must identify the exact PIP artifact/version.  Abort,
# fail, expire, and pause remain usable even when that prerequisite is absent so
# the control plane can always stop or contain an invalid mission safely.
PIP_REQUIRED_COMMANDS = frozenset(
    {
        "BIND_PIP",
        "START_PLANNING",
        "START",
        "WAIT_FOR_EVIDENCE",
        "WAIT_FOR_APPROVAL",
        "RESUME",
        "REPLAN",
        "BEGIN_CLEANUP",
        "COMPLETE",
    }
)

DEFERRED_LIFECYCLE_GUARDS = (
    "GOVERNANCE_AUTHORIZATION_REMAINS_EXTERNAL_APTS_GSS",
)

_LIFECYCLE_OPERATION_FIELDS = {
    "command",
    "expected_state_version",
    "actor",
    "reason_code",
    "reason",
    "evidence_refs",
    "target_state",
    "metadata",
}

_LIFECYCLE_COMMAND_FIELDS = {
    "command_id",
    "idempotency_key",
    "expected_version_sha256",
    *_LIFECYCLE_OPERATION_FIELDS,
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _normalize_json_object(payload: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def resolve_lifecycle_target(command: str, target_state: Any = None) -> str:
    command = str(command or "").strip().upper()
    if command not in LIFECYCLE_COMMANDS:
        raise MissionValidationError(
            "unsupported lifecycle command; expected one of: " + ", ".join(LIFECYCLE_COMMANDS)
        )

    if command == "RESUME":
        if not isinstance(target_state, str) or not target_state.strip():
            raise MissionValidationError("target_state is required for RESUME")
        normalized_target = target_state.strip().upper()
        if normalized_target not in RESUME_TARGETS:
            raise MissionValidationError(
                "RESUME target_state must be one of: " + ", ".join(RESUME_TARGETS)
            )
        return normalized_target

    if target_state not in (None, ""):
        raise MissionValidationError(
            f"target_state is derived by the {command} lifecycle command and must not be supplied"
        )
    return FIXED_TARGETS[command]


def normalize_lifecycle_operation_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("lifecycle command payload must be a JSON object")

    unknown = sorted(set(payload) - _LIFECYCLE_OPERATION_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported lifecycle command payload field(s): "
            + ", ".join(unknown)
            + "; put extensions under metadata"
        )

    command = _require_string(payload, "command", 64).upper()
    target_state = resolve_lifecycle_target(command, payload.get("target_state"))
    if target_state not in CANONICAL_STATES:
        raise MissionValidationError("resolved lifecycle target_state is not canonical")

    try:
        expected_state_version = int(payload.get("expected_state_version"))
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("expected_state_version is required and must be an integer") from exc
    if expected_state_version < 1:
        raise MissionValidationError("expected_state_version must be >= 1")

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
    metadata = _normalize_json_object(payload, "metadata")

    return {
        "command": command,
        "expected_state_version": expected_state_version,
        "actor": actor,
        "reason_code": reason_code,
        "reason": reason,
        "evidence_refs": evidence_refs,
        "target_state": target_state,
        "metadata": metadata,
    }


def normalize_lifecycle_command_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("mission lifecycle command request body must be a JSON object")

    unknown = sorted(set(payload) - _LIFECYCLE_COMMAND_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported mission lifecycle command field(s): "
            + ", ".join(unknown)
            + "; put extensions under metadata"
        )

    command_id = _require_string(payload, "command_id")
    idempotency_key = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(command_id):
        raise MissionValidationError("command_id contains unsupported characters")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")

    expected_version_sha256 = _require_string(payload, "expected_version_sha256", 64).lower()
    if not _SHA256_RE.match(expected_version_sha256):
        raise MissionValidationError("expected_version_sha256 must be a lowercase SHA-256 hex digest")

    operation_payload = normalize_lifecycle_operation_payload(
        {key: value for key, value in payload.items() if key in _LIFECYCLE_OPERATION_FIELDS}
    )
    return {
        "schema_version": LIFECYCLE_COMMAND_SCHEMA_VERSION,
        "command_id": command_id,
        "idempotency_key": idempotency_key,
        "expected_version_sha256": expected_version_sha256,
        **operation_payload,
    }


def build_guarded_lifecycle_command(normalized: Mapping[str, Any]) -> Dict[str, Any]:
    operation_payload = {
        "command": normalized["command"],
        "expected_state_version": int(normalized["expected_state_version"]),
        "actor": normalized["actor"],
        "reason_code": normalized["reason_code"],
        "reason": normalized.get("reason"),
        "evidence_refs": list(normalized.get("evidence_refs") or []),
        "metadata": dict(normalized.get("metadata") or {}),
    }
    if normalized["command"] == "RESUME":
        operation_payload["target_state"] = normalized["target_state"]

    return {
        "command_id": normalized["command_id"],
        "idempotency_key": normalized["idempotency_key"],
        "operation": LIFECYCLE_COMMAND_OPERATION,
        "expected_version_sha256": normalized["expected_version_sha256"],
        "payload": operation_payload,
        "submitted_by": normalized["actor"],
        "metadata": {
            "contract": "MISSION_LIFECYCLE_COMMAND",
            "lifecycle_command_schema_version": LIFECYCLE_COMMAND_SCHEMA_VERSION,
            "lifecycle_guard_matrix_schema_version": GUARD_MATRIX_SCHEMA_VERSION,
            "lifecycle_command": normalized["command"],
            "resolved_target_state": normalized["target_state"],
            "request_metadata": dict(normalized.get("metadata") or {}),
        },
    }


def lifecycle_transition_request(payload: Any) -> Dict[str, Any]:
    normalized = normalize_lifecycle_operation_payload(payload)
    transition_metadata = dict(normalized["metadata"])
    transition_metadata.update(
        {
            "lifecycle_command_schema_version": LIFECYCLE_COMMAND_SCHEMA_VERSION,
            "lifecycle_guard_matrix_schema_version": GUARD_MATRIX_SCHEMA_VERSION,
            "lifecycle_command": normalized["command"],
            "resolved_target_state": normalized["target_state"],
        }
    )
    return {
        "expected_state_version": normalized["expected_state_version"],
        "to_state": normalized["target_state"],
        "actor": normalized["actor"],
        "reason_code": normalized["reason_code"],
        "reason": normalized["reason"],
        "evidence_refs": normalized["evidence_refs"],
        "metadata": transition_metadata,
    }


def _pip_binding_complete(envelope: Mapping[str, Any]) -> bool:
    bindings = envelope.get("bindings") if isinstance(envelope, Mapping) else None
    pip = bindings.get("pip") if isinstance(bindings, Mapping) else None
    if not isinstance(pip, Mapping):
        return False
    pip_id = pip.get("pip_id")
    pip_version = pip.get("pip_version")
    return bool(isinstance(pip_id, str) and pip_id.strip() and isinstance(pip_version, str) and pip_version.strip())


def lifecycle_guard_matrix_contract() -> Dict[str, Any]:
    return {
        "schema_version": GUARD_MATRIX_SCHEMA_VERSION,
        "mode": GUARD_MATRIX_MODE,
        "applies_to": GUARD_MATRIX_APPLIES_TO,
        "authority_semantics": GUARD_MATRIX_AUTHORITY_SEMANTICS,
        "command_source_states": {command: list(states) for command, states in COMMAND_SOURCE_STATES.items()},
        "pip_required_commands": sorted(PIP_REQUIRED_COMMANDS),
        "fail_safe_terminal_commands": list(TERMINAL_COMMAND_TARGETS),
        "checks": [
            "SOURCE_STATE_ALLOWED_FOR_COMMAND",
            "CANONICAL_TARGET_TOPOLOGY_LEGAL",
            "PIP_BINDING_COMPLETE_WHEN_REQUIRED",
            "CANONICAL_ENVELOPE_INTEGRITY_FOR_PIP_ACTIVATION",
            "PIP_ACTIVATION_EVIDENCE_FOR_PLANNING",
            "PLANNING_ACTIVATION_EVIDENCE_FOR_INITIAL_RUN",
            "CANONICAL_ENVELOPE_INTEGRITY_FOR_PLANNING_RUN_ACTIVATION",
            "WAITING_DEPENDENCY_DECLARATION_FOR_WAIT",
            "WAITING_DEPENDENCY_LINEAGE_FOR_RETURN",
            "WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN",
            "WAITING_DEPENDENCY_RESOLUTION_EVIDENCE_FOR_RETURN",
            "PAUSE_LINEAGE_FOR_RESUME",
            "RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE",
            "RESUME_PREREQUISITE_LINEAGE_FOR_TARGET",
            "REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS",
            "REPLAN_READINESS_EVIDENCE_FOR_RETURN",
            "RUN_ACTIVATION_LINEAGE_FOR_CLEANUP",
            "CANONICAL_ENVELOPE_INTEGRITY_FOR_CLEANUP_COMPLETION",
            "CLEANUP_LINEAGE_FOR_COMPLETION",
            "CLEANUP_COMPLETION_BLOCKERS_CLEAR",
            "COMPLETION_DECLARATION_VERIFIED",
            "COMPLETION_OBJECTIVE_SATISFIED",
            "COMPLETION_SUCCESS_CRITERIA_COVERAGE",
            "COMPLETION_CLEANUP_VERIFIED",
            "COMPLETION_CRITICAL_DEPENDENCIES_CLEAR",
            "COMPLETION_EVIDENCE_REFS_BOUND",
            "TERMINAL_INTENT_TARGET_CONSISTENCY",
        ],
        "deferred_guards": list(DEFERRED_LIFECYCLE_GUARDS),
        "external_authority_queries": False,
        "governance_decision_synthesized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def evaluate_lifecycle_guard(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    command: str,
    target_state: str,
    state_transitions: list[Mapping[str, Any]] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    request_context_provided: bool = False,
) -> Dict[str, Any]:
    command = str(command or "").strip().upper()
    target_state = str(target_state or "").strip().upper()
    from_state = str(current_state.get("state") or "").strip().upper()

    allowed_sources = COMMAND_SOURCE_STATES.get(command, ())
    source_ok = from_state in allowed_sources
    topology_ok = is_legal_transition(from_state, target_state)
    pip_required = command in PIP_REQUIRED_COMMANDS
    pip_ok = _pip_binding_complete(envelope)
    activation_integrity_required = command == ACTIVATION_COMMAND
    activation_integrity_ok = verify_envelope(envelope)
    transitions = list(state_transitions or [])
    pip_activation_proof = _pip_activation_lineage_proof(envelope, transitions)
    planning_activation_proof = _planning_activation_lineage_proof(envelope, transitions)
    planning_activation_required = (
        command == PLANNING_ACTIVATION_COMMAND and from_state == PLANNING_ACTIVATION_FROM_STATE
    )
    initial_run_activation_required = (
        command == RUN_ACTIVATION_COMMAND and from_state == RUN_ACTIVATION_FROM_STATE
    )
    planning_run_integrity_required = planning_activation_required or initial_run_activation_required

    request_metadata = dict(request_metadata or {})
    request_evidence_refs = list(evidence_refs or [])
    wait_declaration_required = command in WAIT_COMMAND_KIND
    wait_declaration = _waiting_dependency_declaration_request(command, request_metadata)
    wait_declaration_ok = bool(wait_declaration.get("valid"))
    waiting_return_required = command == "START" and from_state in WAIT_STATE_KIND
    active_waiting_dependency = _waiting_dependency_lineage_proof(transitions, from_state)
    waiting_resolution = _waiting_dependency_resolution_request(
        request_metadata, active_waiting_dependency
    )
    waiting_resolution_ok = bool(waiting_resolution.get("valid"))
    waiting_resolution_evidence_ok = bool(request_evidence_refs)

    pause_lineage = _pause_lineage_proof(transitions) if from_state == "PAUSED" else {
        "valid": False,
        "status": "NOT_PAUSED",
        "transition_id": None,
        "pause_id": None,
        "paused_from_state": None,
    }
    resume_required = command == "RESUME" and from_state == "PAUSED"
    paused_from_state = str(pause_lineage.get("paused_from_state") or "").strip().upper()
    resume_policy_targets = PAUSED_SOURCE_RESUME_TARGETS.get(paused_from_state, ())
    resume_target_ok = target_state in resume_policy_targets
    resume_prerequisite = _resume_prerequisite_proof(
        envelope=envelope,
        state_transitions=transitions,
        pause_lineage=pause_lineage,
        target_state=target_state,
    ) if resume_required else {"valid": True, "status": "NOT_REQUIRED", "transition_id": None}

    replanning_progress_required = (
        from_state == "REPLANNING"
        and command in {"START", "WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL"}
    )
    active_replan = _replan_lineage_proof(transitions) if from_state == "REPLANNING" else {
        "valid": False,
        "status": "NOT_REPLANNING",
        "transition_id": None,
        "replan_id": None,
    }
    replan_return_required = command == "START" and from_state == "REPLANNING"
    replan_readiness_evidence_ok = bool(request_evidence_refs)

    cleanup_begin_required = command == CLEANUP_COMMAND
    completion_required = command == COMPLETION_COMMAND and from_state == CLEANUP_STATE
    cleanup_completion_integrity_required = cleanup_begin_required or completion_required
    run_activation_for_cleanup = (
        _run_activation_lineage_proof(envelope, transitions)
        if cleanup_completion_integrity_required
        else {"valid": True, "status": "NOT_REQUIRED", "transition_id": None}
    )
    cleanup_lineage = (
        _cleanup_lineage_proof(envelope, transitions)
        if completion_required
        else {
            "valid": True,
            "status": "NOT_REQUIRED",
            "transition_id": None,
            "cleanup_id": None,
            "completion_blockers": [],
        }
    )
    cleanup_blockers_clear = bool(
        not completion_required or (cleanup_lineage.get("valid") and not cleanup_lineage.get("completion_blockers"))
    )
    completion_request = (
        _completion_request_evaluation(
            envelope=envelope,
            metadata=request_metadata,
            evidence_refs=request_evidence_refs,
        )
        if completion_required and request_context_provided
        else {
            "valid": True,
            "status": "REQUEST_REQUIRED_AT_EXECUTION" if completion_required else "NOT_REQUIRED",
            "verification_status_ok": True,
            "objective_satisfied": True,
            "success_criteria_satisfied": True,
            "criteria_results_valid": True,
            "criteria_coverage_exact": True,
            "cleanup_verified": True,
            "cleanup_checks_valid": True,
            "critical_dependencies_clear": True,
            "command_evidence_refs_present": True,
            "nested_evidence_refs_bound": True,
            "success_criteria_count": len(_mission_success_criteria(envelope)),
            "outstanding_critical_dependencies": None,
        }
    )

    terminal_intent_required = command in TERMINAL_COMMAND_TARGETS
    terminal_intent_target_ok = (
        not terminal_intent_required
        or TERMINAL_COMMAND_TARGETS.get(command) == target_state
    )

    checks = [
        {
            "guard_id": "SOURCE_STATE_ALLOWED_FOR_COMMAND",
            "status": "PASS" if source_ok else "FAIL",
            "observed": from_state,
            "required": list(allowed_sources),
        },
        {
            "guard_id": "CANONICAL_TARGET_TOPOLOGY_LEGAL",
            "status": "PASS" if topology_ok else "FAIL",
            "observed": f"{from_state}->{target_state}",
            "required": "STAGE_3_1_2_CANONICAL_STATE_MACHINE",
        },
        {
            "guard_id": "PIP_BINDING_COMPLETE_WHEN_REQUIRED",
            "status": "PASS" if (not pip_required or pip_ok) else "FAIL",
            "observed": "COMPLETE" if pip_ok else "MISSING_OR_INCOMPLETE",
            "required": "COMPLETE" if pip_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "CANONICAL_ENVELOPE_INTEGRITY_FOR_PIP_ACTIVATION",
            "status": "PASS" if (not activation_integrity_required or activation_integrity_ok) else "FAIL",
            "observed": "VERIFIED" if activation_integrity_ok else "FAILED",
            "required": "VERIFIED" if activation_integrity_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "PIP_ACTIVATION_EVIDENCE_FOR_PLANNING",
            "status": "PASS" if (not planning_activation_required or pip_activation_proof["valid"]) else "FAIL",
            "observed": pip_activation_proof["status"],
            "required": "VALID_STAGE_3_2_3_PIP_ACTIVATION_LINEAGE" if planning_activation_required else "NOT_REQUIRED",
            "transition_id": pip_activation_proof.get("transition_id"),
        },
        {
            "guard_id": "PLANNING_ACTIVATION_EVIDENCE_FOR_INITIAL_RUN",
            "status": "PASS" if (not initial_run_activation_required or planning_activation_proof["valid"]) else "FAIL",
            "observed": planning_activation_proof["status"],
            "required": "VALID_STAGE_3_2_4_PLANNING_ACTIVATION_LINEAGE" if initial_run_activation_required else "NOT_REQUIRED",
            "transition_id": planning_activation_proof.get("transition_id"),
        },
        {
            "guard_id": "CANONICAL_ENVELOPE_INTEGRITY_FOR_PLANNING_RUN_ACTIVATION",
            "status": "PASS" if (not planning_run_integrity_required or activation_integrity_ok) else "FAIL",
            "observed": "VERIFIED" if activation_integrity_ok else "FAILED",
            "required": "VERIFIED" if planning_run_integrity_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "WAITING_DEPENDENCY_DECLARATION_FOR_WAIT",
            "status": (
                "PASS"
                if (
                    not wait_declaration_required
                    or not request_context_provided
                    or wait_declaration_ok
                )
                else "FAIL"
            ),
            "observed": (
                wait_declaration.get("status")
                if request_context_provided
                else ("REQUEST_REQUIRED_AT_EXECUTION" if wait_declaration_required else "NOT_REQUIRED")
            ),
            "required": (
                "VALID_EXPLICIT_DEPENDENCY_DECLARATION"
                if wait_declaration_required
                else "NOT_REQUIRED"
            ),
            "dependency_id": wait_declaration.get("dependency_id"),
            "dependency_kind": wait_declaration.get("kind"),
        },
        {
            "guard_id": "WAITING_DEPENDENCY_LINEAGE_FOR_RETURN",
            "status": "PASS" if (not waiting_return_required or active_waiting_dependency.get("valid")) else "FAIL",
            "observed": active_waiting_dependency.get("status") if waiting_return_required else "NOT_REQUIRED",
            "required": "VALID_STAGE_3_2_5_WAITING_DEPENDENCY_LINEAGE" if waiting_return_required else "NOT_REQUIRED",
            "transition_id": active_waiting_dependency.get("transition_id"),
            "dependency_id": active_waiting_dependency.get("dependency_id"),
        },
        {
            "guard_id": "WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN",
            "status": (
                "PASS"
                if (
                    not waiting_return_required
                    or not request_context_provided
                    or waiting_resolution_ok
                )
                else "FAIL"
            ),
            "observed": (
                waiting_resolution.get("status")
                if request_context_provided
                else ("REQUEST_REQUIRED_AT_EXECUTION" if waiting_return_required else "NOT_REQUIRED")
            ),
            "required": "MATCHING_SATISFIED_DEPENDENCY_RESOLUTION" if waiting_return_required else "NOT_REQUIRED",
            "dependency_id": waiting_resolution.get("dependency_id"),
        },
        {
            "guard_id": "WAITING_DEPENDENCY_RESOLUTION_EVIDENCE_FOR_RETURN",
            "status": (
                "PASS"
                if (
                    not waiting_return_required
                    or not request_context_provided
                    or waiting_resolution_evidence_ok
                )
                else "FAIL"
            ),
            "observed": (
                "PRESENT"
                if (request_context_provided and waiting_resolution_evidence_ok)
                else ("MISSING" if request_context_provided and waiting_return_required else ("REQUEST_REQUIRED_AT_EXECUTION" if waiting_return_required else "NOT_REQUIRED"))
            ),
            "required": "NON_EMPTY_EVIDENCE_REFS" if waiting_return_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "PAUSE_LINEAGE_FOR_RESUME",
            "status": "PASS" if (not resume_required or pause_lineage.get("valid")) else "FAIL",
            "observed": pause_lineage.get("status") if resume_required else "NOT_REQUIRED",
            "required": "VALID_STAGE_3_2_6_PAUSE_LINEAGE" if resume_required else "NOT_REQUIRED",
            "transition_id": pause_lineage.get("transition_id"),
            "pause_id": pause_lineage.get("pause_id"),
            "paused_from_state": pause_lineage.get("paused_from_state"),
        },
        {
            "guard_id": "RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE",
            "status": "PASS" if (not resume_required or resume_target_ok) else "FAIL",
            "observed": target_state if resume_required else "NOT_REQUIRED",
            "required": list(resume_policy_targets) if resume_required else "NOT_REQUIRED",
            "paused_from_state": pause_lineage.get("paused_from_state"),
        },
        {
            "guard_id": "RESUME_PREREQUISITE_LINEAGE_FOR_TARGET",
            "status": "PASS" if (not resume_required or resume_prerequisite.get("valid")) else "FAIL",
            "observed": resume_prerequisite.get("status") if resume_required else "NOT_REQUIRED",
            "required": resume_prerequisite.get("required", "VALID_PRIOR_LIFECYCLE_LINEAGE") if resume_required else "NOT_REQUIRED",
            "transition_id": resume_prerequisite.get("transition_id"),
        },
        {
            "guard_id": "REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS",
            "status": "PASS" if (not replanning_progress_required or active_replan.get("valid")) else "FAIL",
            "observed": active_replan.get("status") if replanning_progress_required else "NOT_REQUIRED",
            "required": "VALID_STAGE_3_2_6_REPLAN_LINEAGE" if replanning_progress_required else "NOT_REQUIRED",
            "transition_id": active_replan.get("transition_id"),
            "replan_id": active_replan.get("replan_id"),
        },
        {
            "guard_id": "REPLAN_READINESS_EVIDENCE_FOR_RETURN",
            "status": (
                "PASS"
                if (
                    not replan_return_required
                    or not request_context_provided
                    or replan_readiness_evidence_ok
                )
                else "FAIL"
            ),
            "observed": (
                "PRESENT"
                if (request_context_provided and replan_readiness_evidence_ok)
                else (
                    "MISSING"
                    if request_context_provided and replan_return_required
                    else ("REQUEST_REQUIRED_AT_EXECUTION" if replan_return_required else "NOT_REQUIRED")
                )
            ),
            "required": "NON_EMPTY_REPLAN_READINESS_EVIDENCE_REFS" if replan_return_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "RUN_ACTIVATION_LINEAGE_FOR_CLEANUP",
            "status": "PASS" if (not cleanup_completion_integrity_required or run_activation_for_cleanup.get("valid")) else "FAIL",
            "observed": run_activation_for_cleanup.get("status") if cleanup_completion_integrity_required else "NOT_REQUIRED",
            "required": "VALID_STAGE_3_2_4_RUN_ACTIVATION_LINEAGE" if cleanup_completion_integrity_required else "NOT_REQUIRED",
            "transition_id": run_activation_for_cleanup.get("transition_id"),
        },
        {
            "guard_id": "CANONICAL_ENVELOPE_INTEGRITY_FOR_CLEANUP_COMPLETION",
            "status": "PASS" if (not cleanup_completion_integrity_required or activation_integrity_ok) else "FAIL",
            "observed": "VERIFIED" if activation_integrity_ok else "FAILED",
            "required": "VERIFIED" if cleanup_completion_integrity_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "CLEANUP_LINEAGE_FOR_COMPLETION",
            "status": "PASS" if (not completion_required or cleanup_lineage.get("valid")) else "FAIL",
            "observed": cleanup_lineage.get("status") if completion_required else "NOT_REQUIRED",
            "required": "VALID_STAGE_3_2_8_CLEANUP_LINEAGE" if completion_required else "NOT_REQUIRED",
            "transition_id": cleanup_lineage.get("transition_id"),
            "cleanup_id": cleanup_lineage.get("cleanup_id"),
        },
        {
            "guard_id": "CLEANUP_COMPLETION_BLOCKERS_CLEAR",
            "status": "PASS" if cleanup_blockers_clear else "FAIL",
            "observed": list(cleanup_lineage.get("completion_blockers") or []) if completion_required else "NOT_REQUIRED",
            "required": [] if completion_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "COMPLETION_DECLARATION_VERIFIED",
            "status": "PASS" if (not completion_required or not request_context_provided or completion_request.get("verification_status_ok")) else "FAIL",
            "observed": completion_request.get("status") if completion_required else "NOT_REQUIRED",
            "required": COMPLETION_VERIFICATION_STATUS if completion_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "COMPLETION_OBJECTIVE_SATISFIED",
            "status": "PASS" if (not completion_required or not request_context_provided or completion_request.get("objective_satisfied")) else "FAIL",
            "observed": "SATISFIED_WITH_EVIDENCE" if completion_request.get("objective_satisfied") else (completion_request.get("status") if completion_required else "NOT_REQUIRED"),
            "required": "SATISFIED_WITH_NON_EMPTY_EVIDENCE_REFS" if completion_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "COMPLETION_SUCCESS_CRITERIA_COVERAGE",
            "status": "PASS" if (not completion_required or not request_context_provided or (completion_request.get("success_criteria_satisfied") and completion_request.get("criteria_results_valid") and completion_request.get("criteria_coverage_exact"))) else "FAIL",
            "observed": {
                "success_criteria_count": completion_request.get("success_criteria_count"),
                "coverage_exact": completion_request.get("criteria_coverage_exact"),
                "criteria_results_valid": completion_request.get("criteria_results_valid"),
            } if completion_required else "NOT_REQUIRED",
            "required": "EXACT_ALL_CRITERIA_SATISFIED_WITH_EVIDENCE" if completion_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "COMPLETION_CLEANUP_VERIFIED",
            "status": "PASS" if (not completion_required or not request_context_provided or (completion_request.get("cleanup_verified") and completion_request.get("cleanup_checks_valid"))) else "FAIL",
            "observed": "VERIFIED_WITH_PASS_CHECKS" if completion_request.get("cleanup_verified") else (completion_request.get("status") if completion_required else "NOT_REQUIRED"),
            "required": "VERIFIED_WITH_NON_EMPTY_PASS_CLEANUP_CHECKS" if completion_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "COMPLETION_CRITICAL_DEPENDENCIES_CLEAR",
            "status": "PASS" if (not completion_required or not request_context_provided or completion_request.get("critical_dependencies_clear")) else "FAIL",
            "observed": completion_request.get("outstanding_critical_dependencies") if completion_required and request_context_provided else ("REQUEST_REQUIRED_AT_EXECUTION" if completion_required else "NOT_REQUIRED"),
            "required": 0 if completion_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "COMPLETION_EVIDENCE_REFS_BOUND",
            "status": "PASS" if (not completion_required or not request_context_provided or (completion_request.get("command_evidence_refs_present") and completion_request.get("nested_evidence_refs_bound"))) else "FAIL",
            "observed": "BOUND" if completion_request.get("nested_evidence_refs_bound") else (completion_request.get("status") if completion_required else "NOT_REQUIRED"),
            "required": "NON_EMPTY_COMMAND_EVIDENCE_REFS_CONTAIN_ALL_NESTED_COMPLETION_REFS" if completion_required else "NOT_REQUIRED",
        },
        {
            "guard_id": "TERMINAL_INTENT_TARGET_CONSISTENCY",
            "status": "PASS" if terminal_intent_target_ok else "FAIL",
            "observed": target_state if terminal_intent_required else "NOT_REQUIRED",
            "required": TERMINAL_COMMAND_TARGETS.get(command, "NOT_REQUIRED"),
            "terminal_command": command if terminal_intent_required else None,
        },
    ]
    failed = [item["guard_id"] for item in checks if item["status"] == "FAIL"]
    return {
        "schema_version": GUARD_MATRIX_SCHEMA_VERSION,
        "mode": GUARD_MATRIX_MODE,
        "mission_id": mission_id,
        "command": command,
        "from_state": from_state,
        "target_state": target_state,
        "allowed": not failed,
        "failed_guard_ids": failed,
        "checks": checks,
        "deferred_guards": list(DEFERRED_LIFECYCLE_GUARDS),
        "authority_semantics": GUARD_MATRIX_AUTHORITY_SEMANTICS,
        "authority_query_performed": False,
        "governance_decision_synthesized": False,
        "target_action_performed": False,
    }


def enforce_lifecycle_guard(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    command: str,
    target_state: str,
    state_transitions: list[Mapping[str, Any]] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    request_context_provided: bool = False,
) -> Dict[str, Any]:
    evaluation = evaluate_lifecycle_guard(
        mission_id=mission_id,
        envelope=envelope,
        current_state=current_state,
        command=command,
        target_state=target_state,
        state_transitions=state_transitions,
        request_metadata=request_metadata,
        evidence_refs=evidence_refs,
        request_context_provided=request_context_provided,
    )
    if not evaluation["allowed"]:
        # Preserve the Stage-3.1.2 public error contract for transitions that are
        # canonically illegal.  The state machine remains the topology authority;
        # Stage 3.2.2 only introduces an additional guard rejection when the
        # topology itself is legal but lifecycle semantics/prerequisites fail.
        topology = next(
            item for item in evaluation["checks"]
            if item["guard_id"] == "CANONICAL_TARGET_TOPOLOGY_LEGAL"
        )
        if topology["status"] == "FAIL":
            return evaluation
        failed = ",".join(evaluation["failed_guard_ids"])
        raise MissionLifecycleGuardRejected(
            f"lifecycle command {evaluation['command']} rejected by Stage-3.2.2 guard matrix "
            f"for {evaluation['from_state']}->{evaluation['target_state']}; failed_guard_ids={failed}"
        )
    return evaluation



def mission_activation_contract(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the Stage-3.2.3 local activation-readiness projection.

    Stage 3.2.3 does not fetch or authorize a PIP artifact. It proves that the
    immutable canonical Mission envelope already binds an exact PIP id/version
    and that the CREATED -> PIP_BOUND lifecycle activation can therefore be
    attempted through the existing guarded lifecycle command path.
    """

    bindings = envelope.get("bindings") if isinstance(envelope, Mapping) else None
    pip = bindings.get("pip") if isinstance(bindings, Mapping) else None
    pip = dict(pip) if isinstance(pip, Mapping) else {"pip_id": None, "pip_version": None}
    identity = envelope.get("identity") if isinstance(envelope, Mapping) else None
    identity = dict(identity) if isinstance(identity, Mapping) else {}
    integrity = envelope.get("integrity") if isinstance(envelope, Mapping) else None
    integrity = dict(integrity) if isinstance(integrity, Mapping) else {}

    from_state = str(current_state.get("state") or "").strip().upper()
    envelope_integrity_ok = verify_envelope(envelope)
    pip_complete = _pip_binding_complete(envelope)
    state_ready = from_state == ACTIVATION_FROM_STATE
    topology_ready = is_legal_transition(from_state, ACTIVATION_TO_STATE)
    activation_ready = bool(state_ready and topology_ready and pip_complete and envelope_integrity_ok)

    checks = [
        {
            "check_id": "ACTIVATION_SOURCE_STATE_CREATED",
            "status": "PASS" if state_ready else "FAIL",
            "observed": from_state,
            "required": ACTIVATION_FROM_STATE,
        },
        {
            "check_id": "ACTIVATION_TARGET_TOPOLOGY_PIP_BOUND",
            "status": "PASS" if topology_ready else "FAIL",
            "observed": f"{from_state}->{ACTIVATION_TO_STATE}",
            "required": f"{ACTIVATION_FROM_STATE}->{ACTIVATION_TO_STATE}",
        },
        {
            "check_id": "ACTIVATION_PIP_BINDING_COMPLETE",
            "status": "PASS" if pip_complete else "FAIL",
            "observed": "COMPLETE" if pip_complete else "MISSING_OR_INCOMPLETE",
            "required": "pip_id + pip_version",
        },
        {
            "check_id": "ACTIVATION_CANONICAL_ENVELOPE_INTEGRITY",
            "status": "PASS" if envelope_integrity_ok else "FAIL",
            "observed": "VERIFIED" if envelope_integrity_ok else "FAILED",
            "required": "VERIFIED",
        },
    ]

    return {
        "schema_version": ACTIVATION_SCHEMA_VERSION,
        "mode": ACTIVATION_MODE,
        "authority_semantics": ACTIVATION_AUTHORITY_SEMANTICS,
        "mission_id": mission_id,
        "activation_command": ACTIVATION_COMMAND,
        "from_state": ACTIVATION_FROM_STATE,
        "to_state": ACTIVATION_TO_STATE,
        "current_state": from_state,
        "activation_ready": activation_ready,
        "checks": checks,
        "pip_binding": {
            "pip_id": pip.get("pip_id"),
            "pip_version": pip.get("pip_version"),
            "binding_source": "IMMUTABLE_CANONICAL_MISSION_ENVELOPE",
        },
        "canonical_envelope": {
            "envelope_id": identity.get("envelope_id"),
            "envelope_version": identity.get("envelope_version"),
            "canonical_sha256": integrity.get("canonical_sha256"),
            "integrity_verified": envelope_integrity_ok,
        },
        "pip_artifact_query_performed": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def mission_activation_evidence(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
) -> Dict[str, Any]:
    projection = mission_activation_contract(
        mission_id=mission_id,
        envelope=envelope,
        current_state=current_state,
    )
    return {
        "schema_version": projection["schema_version"],
        "mode": projection["mode"],
        "activation_command": projection["activation_command"],
        "from_state": projection["current_state"],
        "to_state": projection["to_state"],
        "pip_binding": dict(projection["pip_binding"]),
        "canonical_envelope": dict(projection["canonical_envelope"]),
        "activation_ready": projection["activation_ready"],
        "authority_semantics": projection["authority_semantics"],
        "pip_artifact_query_performed": False,
        "governance_authorization_query_performed": False,
        "execution_authorized": False,
    }



def _canonical_pip_binding(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    bindings = envelope.get("bindings") if isinstance(envelope, Mapping) else None
    pip = bindings.get("pip") if isinstance(bindings, Mapping) else None
    if not isinstance(pip, Mapping):
        return {"pip_id": None, "pip_version": None}
    return {"pip_id": pip.get("pip_id"), "pip_version": pip.get("pip_version")}


def _canonical_envelope_snapshot(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    identity = envelope.get("identity") if isinstance(envelope, Mapping) else None
    identity = dict(identity) if isinstance(identity, Mapping) else {}
    integrity = envelope.get("integrity") if isinstance(envelope, Mapping) else None
    integrity = dict(integrity) if isinstance(integrity, Mapping) else {}
    return {
        "envelope_id": identity.get("envelope_id"),
        "envelope_version": identity.get("envelope_version"),
        "canonical_sha256": integrity.get("canonical_sha256"),
        "integrity_verified": verify_envelope(envelope),
    }


def _matching_transition(
    state_transitions: list[Mapping[str, Any]],
    *,
    from_state: str,
    to_state: str,
) -> Mapping[str, Any] | None:
    for transition in reversed(state_transitions):
        if (
            str(transition.get("from_state") or "").upper() == from_state
            and str(transition.get("to_state") or "").upper() == to_state
        ):
            return transition
    return None



def _waiting_dependency_declaration_request(command: str, metadata: Mapping[str, Any]) -> Dict[str, Any]:
    command = str(command or "").strip().upper()
    expected_kind = WAIT_COMMAND_KIND.get(command)
    if expected_kind is None:
        return {"valid": True, "status": "NOT_REQUIRED", "dependency_id": None, "kind": None}
    dependency = metadata.get("dependency") if isinstance(metadata, Mapping) else None
    if not isinstance(dependency, Mapping):
        return {"valid": False, "status": "MISSING", "dependency_id": None, "kind": expected_kind}
    dependency_id = dependency.get("dependency_id")
    kind = dependency.get("kind")
    description = dependency.get("description")
    if not isinstance(dependency_id, str) or not dependency_id.strip() or not _ID_RE.match(dependency_id.strip()):
        return {"valid": False, "status": "INVALID_DEPENDENCY_ID", "dependency_id": dependency_id, "kind": kind}
    dependency_id = dependency_id.strip()
    kind = str(kind or "").strip().upper()
    if kind != expected_kind:
        return {"valid": False, "status": "KIND_MISMATCH", "dependency_id": dependency_id, "kind": kind}
    if description is not None and (not isinstance(description, str) or len(description.strip()) > 1000):
        return {"valid": False, "status": "INVALID_DESCRIPTION", "dependency_id": dependency_id, "kind": kind}
    return {
        "valid": True,
        "status": "VALID",
        "dependency_id": dependency_id,
        "kind": kind,
        "description": description.strip() if isinstance(description, str) and description.strip() else None,
    }


def _waiting_dependency_resolution_request(
    metadata: Mapping[str, Any],
    active_dependency: Mapping[str, Any],
) -> Dict[str, Any]:
    resolution = metadata.get("dependency_resolution") if isinstance(metadata, Mapping) else None
    if not isinstance(resolution, Mapping):
        return {"valid": False, "status": "MISSING", "dependency_id": None}
    dependency_id = resolution.get("dependency_id")
    status = str(resolution.get("status") or "").strip().upper()
    resolved_by = resolution.get("resolved_by")
    if not isinstance(dependency_id, str) or not dependency_id.strip() or not _ID_RE.match(dependency_id.strip()):
        return {"valid": False, "status": "INVALID_DEPENDENCY_ID", "dependency_id": dependency_id}
    dependency_id = dependency_id.strip()
    if status != DEPENDENCY_RESOLUTION_STATUS:
        return {"valid": False, "status": "STATUS_NOT_SATISFIED", "dependency_id": dependency_id}
    if not isinstance(resolved_by, str) or not resolved_by.strip() or len(resolved_by.strip()) > 128:
        return {"valid": False, "status": "INVALID_RESOLVED_BY", "dependency_id": dependency_id}
    if not active_dependency.get("valid"):
        return {"valid": False, "status": "ACTIVE_DEPENDENCY_MISSING", "dependency_id": dependency_id}
    if dependency_id != active_dependency.get("dependency_id"):
        return {"valid": False, "status": "DEPENDENCY_ID_MISMATCH", "dependency_id": dependency_id}
    return {
        "valid": True,
        "status": "VALID",
        "dependency_id": dependency_id,
        "resolution_status": status,
        "resolved_by": resolved_by.strip(),
    }


def _waiting_dependency_lineage_proof(
    state_transitions: list[Mapping[str, Any]],
    waiting_state: str,
) -> Dict[str, Any]:
    waiting_state = str(waiting_state or "").strip().upper()
    expected_kind = WAIT_STATE_KIND.get(waiting_state)
    if expected_kind is None:
        return {"valid": False, "status": "NOT_IN_WAITING_STATE", "transition_id": None, "dependency_id": None}
    transition = None
    for candidate in reversed(state_transitions):
        if str(candidate.get("to_state") or "").strip().upper() == waiting_state:
            transition = candidate
            break
    if transition is None:
        return {"valid": False, "status": "MISSING", "transition_id": None, "dependency_id": None, "kind": expected_kind}
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = metadata.get("mission_waiting_dependency") if isinstance(metadata, Mapping) else None
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "MISSING_STAGE_3_2_5_EVIDENCE",
            "transition_id": transition.get("transition_id"),
            "dependency_id": None,
            "kind": expected_kind,
        }
    dependency_id = evidence.get("dependency_id")
    kind = str(evidence.get("kind") or "").strip().upper()
    expected_command = "WAIT_FOR_EVIDENCE" if expected_kind == "EVIDENCE" else "WAIT_FOR_APPROVAL"
    valid = bool(
        evidence.get("schema_version") == WAITING_DEPENDENCY_SCHEMA_VERSION
        and evidence.get("wait_command") == expected_command
        and evidence.get("to_state") == waiting_state
        and kind == expected_kind
        and isinstance(dependency_id, str)
        and dependency_id.strip()
        and evidence.get("dependency_declared") is True
        and evidence.get("governance_authorization_query_performed") is False
        and evidence.get("authorization_granted") is False
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID",
        "transition_id": transition.get("transition_id"),
        "to_state_version": transition.get("to_state_version"),
        "dependency_id": dependency_id,
        "kind": kind or expected_kind,
        "wait_command": evidence.get("wait_command") if isinstance(evidence, Mapping) else expected_command,
        "description": evidence.get("description") if isinstance(evidence, Mapping) else None,
    }


def waiting_dependency_contract(
    *,
    mission_id: str,
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    active = _waiting_dependency_lineage_proof(state_transitions, current)
    return {
        "schema_version": WAITING_DEPENDENCY_SCHEMA_VERSION,
        "mode": WAITING_DEPENDENCY_MODE,
        "authority_semantics": WAITING_DEPENDENCY_AUTHORITY_SEMANTICS,
        "mission_id": mission_id,
        "current_state": current,
        "waiting_state": current if current in WAIT_STATE_KIND else None,
        "active_dependency": active if current in WAIT_STATE_KIND else None,
        "wait_commands": {
            "WAIT_FOR_EVIDENCE": {
                "dependency_kind": "EVIDENCE",
                "target_state": "WAITING_EVIDENCE",
                "request_metadata_required": "metadata.dependency",
            },
            "WAIT_FOR_APPROVAL": {
                "dependency_kind": "APPROVAL",
                "target_state": "WAITING_APPROVAL",
                "request_metadata_required": "metadata.dependency",
            },
        },
        "return_command": {
            "command": "START",
            "from_states": ["WAITING_EVIDENCE", "WAITING_APPROVAL"],
            "target_state": "RUNNING",
            "request_metadata_required": "metadata.dependency_resolution",
            "resolution_status_required": DEPENDENCY_RESOLUTION_STATUS,
            "evidence_refs_required": True,
        },
        "approval_dependency_is_governance_authorization": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def waiting_dependency_declaration_evidence(
    *,
    mission_id: str,
    current_state: Mapping[str, Any],
    command: str,
    metadata: Mapping[str, Any],
    evidence_refs: list[str],
    actor: str,
) -> Dict[str, Any]:
    declaration = _waiting_dependency_declaration_request(command, metadata)
    if not declaration.get("valid"):
        raise MissionValidationError("invalid Stage-3.2.5 waiting dependency declaration")
    command = str(command or "").strip().upper()
    return {
        "schema_version": WAITING_DEPENDENCY_SCHEMA_VERSION,
        "mode": WAITING_DEPENDENCY_MODE,
        "mission_id": mission_id,
        "wait_command": command,
        "from_state": str(current_state.get("state") or "").strip().upper(),
        "to_state": FIXED_TARGETS[command],
        "dependency_id": declaration["dependency_id"],
        "kind": declaration["kind"],
        "description": declaration.get("description"),
        "declared_by": actor,
        "declaration_evidence_refs": list(evidence_refs or []),
        "dependency_declared": True,
        "authority_semantics": WAITING_DEPENDENCY_AUTHORITY_SEMANTICS,
        "approval_dependency_is_governance_authorization": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def waiting_dependency_resolution_evidence(
    *,
    mission_id: str,
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    evidence_refs: list[str],
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    active = _waiting_dependency_lineage_proof(state_transitions, current)
    resolution = _waiting_dependency_resolution_request(metadata, active)
    if not active.get("valid") or not resolution.get("valid") or not evidence_refs:
        raise MissionValidationError("invalid Stage-3.2.5 waiting dependency resolution")
    return {
        "schema_version": WAITING_DEPENDENCY_SCHEMA_VERSION,
        "mode": WAITING_DEPENDENCY_MODE,
        "mission_id": mission_id,
        "return_command": "START",
        "from_state": current,
        "to_state": "RUNNING",
        "dependency_id": active.get("dependency_id"),
        "kind": active.get("kind"),
        "wait_transition_id": active.get("transition_id"),
        "resolution_status": DEPENDENCY_RESOLUTION_STATUS,
        "resolved_by": resolution.get("resolved_by"),
        "resolution_evidence_refs": list(evidence_refs),
        "resolution_ready": True,
        "authority_semantics": WAITING_DEPENDENCY_AUTHORITY_SEMANTICS,
        "approval_dependency_is_governance_authorization": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def _derived_control_id(prefix: str, mission_id: str, state_version: Any) -> str:
    return f"{prefix}:{mission_id}:{int(state_version)}"


def _pause_lineage_proof(state_transitions: list[Mapping[str, Any]]) -> Dict[str, Any]:
    transition = None
    for candidate in reversed(state_transitions):
        if str(candidate.get("to_state") or "").strip().upper() == "PAUSED":
            transition = candidate
            break
    if transition is None:
        return {
            "valid": False,
            "status": "MISSING",
            "transition_id": None,
            "pause_id": None,
            "paused_from_state": None,
        }
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = metadata.get("mission_pause_control") if isinstance(metadata, Mapping) else None
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "MISSING_STAGE_3_2_6_EVIDENCE",
            "transition_id": transition.get("transition_id"),
            "pause_id": None,
            "paused_from_state": transition.get("from_state"),
        }
    pause_id = evidence.get("pause_id")
    paused_from_state = str(evidence.get("from_state") or "").strip().upper()
    valid = bool(
        evidence.get("schema_version") == PAUSE_RESUME_REPLAN_SCHEMA_VERSION
        and evidence.get("pause_command") == "PAUSE"
        and evidence.get("to_state") == "PAUSED"
        and isinstance(pause_id, str)
        and pause_id.strip()
        and paused_from_state == str(transition.get("from_state") or "").strip().upper()
        and evidence.get("governance_authorization_query_performed") is False
        and evidence.get("target_action_dispatch_enabled") is False
        and evidence.get("target_actuation") is False
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID",
        "transition_id": transition.get("transition_id"),
        "to_state_version": transition.get("to_state_version"),
        "pause_id": pause_id,
        "paused_from_state": paused_from_state,
        "active_waiting_dependency": evidence.get("active_waiting_dependency"),
        "active_replan": evidence.get("active_replan"),
    }


def _replan_lineage_proof(state_transitions: list[Mapping[str, Any]]) -> Dict[str, Any]:
    transition = None
    for candidate in reversed(state_transitions):
        if str(candidate.get("to_state") or "").strip().upper() == "REPLANNING":
            transition = candidate
            break
    if transition is None:
        return {
            "valid": False,
            "status": "MISSING",
            "transition_id": None,
            "replan_id": None,
        }
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = metadata.get("mission_replan_control") if isinstance(metadata, Mapping) else None
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "MISSING_STAGE_3_2_6_EVIDENCE",
            "transition_id": transition.get("transition_id"),
            "replan_id": None,
        }
    replan_id = evidence.get("replan_id")
    valid = bool(
        evidence.get("schema_version") == PAUSE_RESUME_REPLAN_SCHEMA_VERSION
        and evidence.get("to_state") == "REPLANNING"
        and isinstance(replan_id, str)
        and replan_id.strip()
        and evidence.get("planner_invocation_performed") is False
        and evidence.get("governance_authorization_query_performed") is False
        and evidence.get("target_action_dispatch_enabled") is False
        and evidence.get("target_actuation") is False
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID",
        "transition_id": transition.get("transition_id"),
        "to_state_version": transition.get("to_state_version"),
        "replan_id": replan_id,
        "from_state": evidence.get("from_state"),
        "origin": evidence.get("origin"),
        "abandoned_waiting_dependency": evidence.get("abandoned_waiting_dependency"),
    }


def _resume_prerequisite_proof(
    *,
    envelope: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    pause_lineage: Mapping[str, Any],
    target_state: str,
) -> Dict[str, Any]:
    if not pause_lineage.get("valid"):
        return {"valid": False, "status": "PAUSE_LINEAGE_MISSING", "transition_id": None, "required": "VALID_STAGE_3_2_6_PAUSE_LINEAGE"}
    paused_from = str(pause_lineage.get("paused_from_state") or "").strip().upper()
    target = str(target_state or "").strip().upper()
    if target not in PAUSED_SOURCE_RESUME_TARGETS.get(paused_from, ()):
        return {"valid": False, "status": "TARGET_POLICY_REJECTED", "transition_id": None, "required": list(PAUSED_SOURCE_RESUME_TARGETS.get(paused_from, ()))}
    if paused_from == "PIP_BOUND":
        proof = _pip_activation_lineage_proof(envelope, state_transitions)
        return {**proof, "required": "VALID_STAGE_3_2_3_PIP_ACTIVATION_LINEAGE"}
    if paused_from == "PLANNING":
        proof = _planning_activation_lineage_proof(envelope, state_transitions)
        return {**proof, "required": "VALID_STAGE_3_2_4_PLANNING_ACTIVATION_LINEAGE"}
    if paused_from == "RUNNING":
        proof = _run_activation_lineage_proof(envelope, state_transitions)
        return {**proof, "required": "VALID_STAGE_3_2_4_RUN_ACTIVATION_LINEAGE"}
    if paused_from == "REPLANNING":
        active_replan = pause_lineage.get("active_replan")
        valid = isinstance(active_replan, Mapping) and active_replan.get("valid") is True
        return {
            "valid": valid,
            "status": "VALID" if valid else "REPLAN_LINEAGE_MISSING_AT_PAUSE",
            "transition_id": active_replan.get("transition_id") if isinstance(active_replan, Mapping) else None,
            "required": "VALID_STAGE_3_2_6_REPLAN_LINEAGE",
        }
    if paused_from in WAIT_STATE_KIND:
        return {
            "valid": target == "REPLANNING",
            "status": "SAFE_REPLAN_CONTINUATION" if target == "REPLANNING" else "WAITING_DEPENDENCY_CANNOT_RESUME_TO_RUNNING",
            "transition_id": pause_lineage.get("transition_id"),
            "required": "REPLANNING_WITHOUT_DEPENDENCY_SATISFACTION_CLAIM",
        }
    return {"valid": False, "status": "NO_RESUME_PREREQUISITE_POLICY", "transition_id": None, "required": "NO_RESUMABLE_TARGET"}


def pause_resume_replan_contract(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    active_pause = _pause_lineage_proof(state_transitions) if current == "PAUSED" else None
    active_replan = _replan_lineage_proof(state_transitions) if current == "REPLANNING" else None
    paused_from = str((active_pause or {}).get("paused_from_state") or "").strip().upper()
    resume_targets = list(PAUSED_SOURCE_RESUME_TARGETS.get(paused_from, ())) if active_pause and active_pause.get("valid") else []
    return {
        "schema_version": PAUSE_RESUME_REPLAN_SCHEMA_VERSION,
        "mode": PAUSE_RESUME_REPLAN_MODE,
        "authority_semantics": PAUSE_RESUME_REPLAN_AUTHORITY_SEMANTICS,
        "mission_id": mission_id,
        "current_state": current,
        "pause": {
            "command": "PAUSE",
            "target_state": "PAUSED",
            "durable_context_generated": True,
            "active_pause": active_pause,
        },
        "resume": {
            "command": "RESUME",
            "source_state": "PAUSED",
            "target_state_required": True,
            "active_pause_required": True,
            "allowed_targets_for_active_pause": resume_targets,
            "source_target_policy": {state: list(targets) for state, targets in PAUSED_SOURCE_RESUME_TARGETS.items()},
            "waiting_pause_direct_running_resume_allowed": False,
        },
        "replan": {
            "command": "REPLAN",
            "target_state": "REPLANNING",
            "active_replan": active_replan,
            "return_command": "START",
            "return_target_state": "RUNNING",
            "readiness_status": REPLAN_READINESS_STATUS,
            "readiness_evidence_refs_required": True,
        },
        "canonical_envelope_integrity_verified": verify_envelope(envelope),
        "planner_invocation_performed": False,
        "plan_artifact_created": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def pause_control_evidence(
    *,
    mission_id: str,
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    actor: str,
    reason_code: str,
    reason: str | None,
    evidence_refs: list[str],
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    state_version = current_state.get("state_version")
    active_wait = _waiting_dependency_lineage_proof(state_transitions, current) if current in WAIT_STATE_KIND else None
    active_replan = _replan_lineage_proof(state_transitions) if current == "REPLANNING" else None
    return {
        "schema_version": PAUSE_RESUME_REPLAN_SCHEMA_VERSION,
        "mode": PAUSE_RESUME_REPLAN_MODE,
        "mission_id": mission_id,
        "pause_id": _derived_control_id("pause", mission_id, state_version),
        "pause_command": "PAUSE",
        "from_state": current,
        "to_state": "PAUSED",
        "from_state_version": state_version,
        "paused_by": actor,
        "reason_code": reason_code,
        "reason": reason,
        "pause_evidence_refs": list(evidence_refs or []),
        "active_waiting_dependency": active_wait if active_wait and active_wait.get("valid") else None,
        "active_replan": active_replan if active_replan and active_replan.get("valid") else None,
        "authority_semantics": PAUSE_RESUME_REPLAN_AUTHORITY_SEMANTICS,
        "planner_invocation_performed": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def replan_control_evidence(
    *,
    mission_id: str,
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    actor: str,
    reason_code: str,
    reason: str | None,
    evidence_refs: list[str],
    origin: str = "REPLAN_COMMAND",
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    state_version = current_state.get("state_version")
    active_wait = _waiting_dependency_lineage_proof(state_transitions, current) if current in WAIT_STATE_KIND else None
    return {
        "schema_version": PAUSE_RESUME_REPLAN_SCHEMA_VERSION,
        "mode": PAUSE_RESUME_REPLAN_MODE,
        "mission_id": mission_id,
        "replan_id": _derived_control_id("replan", mission_id, state_version),
        "replan_command": "REPLAN" if origin == "REPLAN_COMMAND" else "RESUME",
        "origin": origin,
        "from_state": current,
        "to_state": "REPLANNING",
        "from_state_version": state_version,
        "requested_by": actor,
        "trigger_code": reason_code,
        "reason": reason,
        "replan_evidence_refs": list(evidence_refs or []),
        "abandoned_waiting_dependency": active_wait if active_wait and active_wait.get("valid") else None,
        "planner_invocation_performed": False,
        "plan_artifact_created": False,
        "authority_semantics": PAUSE_RESUME_REPLAN_AUTHORITY_SEMANTICS,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def resume_control_evidence(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    target_state: str,
    actor: str,
    evidence_refs: list[str],
) -> Dict[str, Any]:
    pause = _pause_lineage_proof(state_transitions)
    prerequisite = _resume_prerequisite_proof(
        envelope=envelope,
        state_transitions=state_transitions,
        pause_lineage=pause,
        target_state=target_state,
    )
    if not pause.get("valid") or not prerequisite.get("valid"):
        raise MissionValidationError("invalid Stage-3.2.6 resume control evidence")
    paused_from = str(pause.get("paused_from_state") or "").strip().upper()
    return {
        "schema_version": PAUSE_RESUME_REPLAN_SCHEMA_VERSION,
        "mode": PAUSE_RESUME_REPLAN_MODE,
        "mission_id": mission_id,
        "resume_command": "RESUME",
        "pause_id": pause.get("pause_id"),
        "pause_transition_id": pause.get("transition_id"),
        "paused_from_state": paused_from,
        "from_state": "PAUSED",
        "to_state": str(target_state or "").strip().upper(),
        "resumed_by": actor,
        "resume_evidence_refs": list(evidence_refs or []),
        "resume_prerequisite": prerequisite,
        "waiting_dependency_abandoned": paused_from in WAIT_STATE_KIND,
        "active_waiting_dependency": pause.get("active_waiting_dependency"),
        "authority_semantics": PAUSE_RESUME_REPLAN_AUTHORITY_SEMANTICS,
        "planner_invocation_performed": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def replan_resolution_evidence(
    *,
    mission_id: str,
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    actor: str,
    evidence_refs: list[str],
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    active = _replan_lineage_proof(state_transitions)
    if current != "REPLANNING" or not active.get("valid") or not evidence_refs:
        raise MissionValidationError("invalid Stage-3.2.6 replanning readiness evidence")
    return {
        "schema_version": PAUSE_RESUME_REPLAN_SCHEMA_VERSION,
        "mode": PAUSE_RESUME_REPLAN_MODE,
        "mission_id": mission_id,
        "return_command": "START",
        "from_state": "REPLANNING",
        "to_state": "RUNNING",
        "replan_id": active.get("replan_id"),
        "replan_transition_id": active.get("transition_id"),
        "readiness_status": REPLAN_READINESS_STATUS,
        "resolved_by": actor,
        "readiness_evidence_refs": list(evidence_refs),
        "readiness_ready": True,
        "planner_invocation_performed": False,
        "plan_artifact_created": False,
        "authority_semantics": PAUSE_RESUME_REPLAN_AUTHORITY_SEMANTICS,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }



def _mission_success_criteria(envelope: Mapping[str, Any]) -> list[Any]:
    mission = envelope.get("mission") if isinstance(envelope, Mapping) else None
    criteria = mission.get("success_criteria") if isinstance(mission, Mapping) else None
    return list(criteria) if isinstance(criteria, list) else []


def _completion_request_evaluation(
    *,
    envelope: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
    evidence_refs: list[str] | None,
) -> Dict[str, Any]:
    """Validate caller-supplied completion evidence without consulting external authority.

    Stage 3.2.8 deliberately verifies the *shape, coverage, binding, and lifecycle
    provenance* of completion evidence. It does not independently execute target-side
    cleanup, query Governance, or reinterpret evidence content as authorization.
    """

    request_metadata = dict(metadata or {})
    completion = request_metadata.get("completion")
    expected_criteria = _mission_success_criteria(envelope)
    expected_indices = set(range(len(expected_criteria)))
    command_refs = list(evidence_refs or [])

    result: Dict[str, Any] = {
        "valid": False,
        "status": "MISSING",
        "completion_declaration_present": isinstance(completion, Mapping),
        "verification_status_ok": False,
        "objective_satisfied": False,
        "objective_evidence_refs": [],
        "success_criteria_satisfied": False,
        "success_criteria_count": len(expected_criteria),
        "criteria_results": [],
        "criteria_coverage_exact": False,
        "criteria_results_valid": False,
        "cleanup_verified": False,
        "cleanup_checks": [],
        "cleanup_checks_valid": False,
        "critical_dependencies_clear": False,
        "outstanding_critical_dependencies": None,
        "command_evidence_refs_present": bool(command_refs),
        "nested_evidence_refs_bound": False,
        "required_nested_evidence_refs": [],
        "command_evidence_refs": command_refs,
        "declaration": dict(completion) if isinstance(completion, Mapping) else None,
    }
    if not isinstance(completion, Mapping):
        return result

    verification_status = str(completion.get("verification_status") or "").strip().upper()
    objective_status = str(completion.get("objective_status") or "").strip().upper()
    criteria_status = str(completion.get("success_criteria_status") or "").strip().upper()
    cleanup_status = str(completion.get("cleanup_status") or "").strip().upper()
    result["verification_status_ok"] = verification_status == COMPLETION_VERIFICATION_STATUS
    result["objective_satisfied"] = objective_status == OBJECTIVE_COMPLETION_STATUS
    result["success_criteria_satisfied"] = criteria_status == SUCCESS_CRITERIA_COMPLETION_STATUS
    result["cleanup_verified"] = cleanup_status == CLEANUP_VERIFICATION_STATUS

    try:
        objective_refs = _normalize_evidence_refs(completion.get("objective_evidence_refs"))
    except MissionValidationError:
        objective_refs = []
    result["objective_evidence_refs"] = objective_refs
    result["objective_satisfied"] = bool(result["objective_satisfied"] and objective_refs)

    criteria_results_raw = completion.get("criteria_results")
    criteria_results_valid = isinstance(criteria_results_raw, list)
    normalized_criteria_results: list[Dict[str, Any]] = []
    seen_indices: set[int] = set()
    if isinstance(criteria_results_raw, list):
        for item in criteria_results_raw:
            if not isinstance(item, Mapping):
                criteria_results_valid = False
                continue
            try:
                index = int(item.get("criterion_index"))
            except (TypeError, ValueError):
                criteria_results_valid = False
                continue
            status = str(item.get("status") or "").strip().upper()
            try:
                refs = _normalize_evidence_refs(item.get("evidence_refs"))
            except MissionValidationError:
                refs = []
                criteria_results_valid = False
            if index in seen_indices or index not in expected_indices:
                criteria_results_valid = False
            seen_indices.add(index)
            if status != SUCCESS_CRITERIA_COMPLETION_STATUS or not refs:
                criteria_results_valid = False
            normalized_criteria_results.append(
                {"criterion_index": index, "status": status, "evidence_refs": refs}
            )
    else:
        criteria_results_valid = False

    coverage_exact = seen_indices == expected_indices and len(normalized_criteria_results) == len(expected_indices)
    if not expected_indices and criteria_results_raw == []:
        criteria_results_valid = True
        coverage_exact = True
    result["criteria_results"] = normalized_criteria_results
    result["criteria_coverage_exact"] = coverage_exact
    result["criteria_results_valid"] = bool(criteria_results_valid and coverage_exact)
    result["success_criteria_satisfied"] = bool(
        result["success_criteria_satisfied"] and result["criteria_results_valid"]
    )

    cleanup_checks_raw = completion.get("cleanup_checks")
    cleanup_checks_valid = isinstance(cleanup_checks_raw, list) and len(cleanup_checks_raw) > 0
    normalized_cleanup_checks: list[Dict[str, Any]] = []
    seen_check_ids: set[str] = set()
    if isinstance(cleanup_checks_raw, list):
        for item in cleanup_checks_raw:
            if not isinstance(item, Mapping):
                cleanup_checks_valid = False
                continue
            check_id = item.get("check_id")
            check_id = check_id.strip() if isinstance(check_id, str) else ""
            status = str(item.get("status") or "").strip().upper()
            try:
                refs = _normalize_evidence_refs(item.get("evidence_refs"))
            except MissionValidationError:
                refs = []
                cleanup_checks_valid = False
            if not check_id or check_id in seen_check_ids or status != CLEANUP_CHECK_STATUS or not refs:
                cleanup_checks_valid = False
            if check_id:
                seen_check_ids.add(check_id)
            normalized_cleanup_checks.append(
                {"check_id": check_id or None, "status": status, "evidence_refs": refs}
            )
    result["cleanup_checks"] = normalized_cleanup_checks
    result["cleanup_checks_valid"] = cleanup_checks_valid
    result["cleanup_verified"] = bool(result["cleanup_verified"] and cleanup_checks_valid)

    outstanding = completion.get("outstanding_critical_dependencies")
    if isinstance(outstanding, bool):
        parsed_outstanding = None
    else:
        try:
            parsed_outstanding = int(outstanding)
        except (TypeError, ValueError):
            parsed_outstanding = None
    result["outstanding_critical_dependencies"] = parsed_outstanding
    result["critical_dependencies_clear"] = parsed_outstanding == 0

    nested_refs: list[str] = []
    for ref in objective_refs:
        if ref not in nested_refs:
            nested_refs.append(ref)
    for item in normalized_criteria_results:
        for ref in item["evidence_refs"]:
            if ref not in nested_refs:
                nested_refs.append(ref)
    for item in normalized_cleanup_checks:
        for ref in item["evidence_refs"]:
            if ref not in nested_refs:
                nested_refs.append(ref)
    result["required_nested_evidence_refs"] = nested_refs
    result["nested_evidence_refs_bound"] = bool(
        command_refs and nested_refs and set(nested_refs).issubset(set(command_refs))
    )

    result["valid"] = bool(
        result["verification_status_ok"]
        and result["objective_satisfied"]
        and result["success_criteria_satisfied"]
        and result["criteria_results_valid"]
        and result["cleanup_verified"]
        and result["cleanup_checks_valid"]
        and result["critical_dependencies_clear"]
        and result["command_evidence_refs_present"]
        and result["nested_evidence_refs_bound"]
    )
    result["status"] = "VALID" if result["valid"] else "INVALID_STAGE_3_2_8_COMPLETION_DECLARATION"
    return result


def cleanup_control_evidence(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    actor: str,
    reason_code: str,
    reason: str | None,
    evidence_refs: list[str],
    metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    if current not in {"RUNNING", "PAUSED"}:
        raise MissionValidationError("cleanup control evidence requires RUNNING or PAUSED source state")
    run_proof = _run_activation_lineage_proof(envelope, state_transitions)
    if not run_proof.get("valid"):
        raise MissionValidationError("cleanup requires valid Stage-3.2.4 RUNNING activation lineage")

    active_pause = _pause_lineage_proof(state_transitions) if current == "PAUSED" else None
    blockers: list[str] = []
    if current == "PAUSED":
        if not active_pause or not active_pause.get("valid"):
            blockers.append("INVALID_PAUSE_LINEAGE")
        else:
            paused_from = str(active_pause.get("paused_from_state") or "").strip().upper()
            if paused_from in WAIT_STATE_KIND:
                blockers.append("UNRESOLVED_WAITING_DEPENDENCY")
            if paused_from == "REPLANNING" or active_pause.get("active_replan"):
                blockers.append("UNRESOLVED_REPLAN")
            if paused_from != "RUNNING" and paused_from not in WAIT_STATE_KIND and paused_from != "REPLANNING":
                blockers.append("PAUSED_SOURCE_NOT_RUNNING")

    cleanup_context = dict((metadata or {}).get("cleanup") or {}) if isinstance((metadata or {}).get("cleanup"), Mapping) else {}
    state_version = current_state.get("state_version")
    return {
        "schema_version": CLEANUP_COMPLETION_SCHEMA_VERSION,
        "mode": CLEANUP_COMPLETION_MODE,
        "mission_id": mission_id,
        "cleanup_id": _derived_control_id("cleanup", mission_id, state_version),
        "cleanup_command": CLEANUP_COMMAND,
        "from_state": current,
        "from_state_version": state_version,
        "to_state": CLEANUP_STATE,
        "initiated_by": actor,
        "reason_code": reason_code,
        "reason": reason,
        "cleanup_evidence_refs": list(evidence_refs or []),
        "cleanup_context": cleanup_context,
        "run_activation_proof": dict(run_proof),
        "active_pause": active_pause if active_pause and active_pause.get("valid") else None,
        "completion_blockers": blockers,
        "completion_prerequisites_ready": not blockers,
        "cleanup_started": True,
        "cleanup_verified": False,
        "success_claimed": False,
        "verified_completion_claimed": False,
        "authority_semantics": CLEANUP_COMPLETION_AUTHORITY_SEMANTICS,
        "cleanup_action_performed_by_orchestrator": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def _cleanup_lineage_proof(
    envelope: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    transition = None
    for candidate in reversed(list(state_transitions or [])):
        if str(candidate.get("to_state") or "").strip().upper() == CLEANUP_STATE:
            transition = candidate
            break
    if transition is None:
        return {
            "valid": False,
            "status": "MISSING",
            "transition_id": None,
            "cleanup_id": None,
            "completion_blockers": ["CLEANUP_LINEAGE_MISSING"],
        }
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = metadata.get("mission_cleanup_control") if isinstance(metadata, Mapping) else None
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "LEGACY_DIRECT_CLEANING_UP_NO_STAGE_3_2_8_EVIDENCE",
            "transition_id": transition.get("transition_id"),
            "cleanup_id": None,
            "completion_blockers": ["STAGE_3_2_8_CLEANUP_EVIDENCE_MISSING"],
        }
    run_proof = _run_activation_lineage_proof(envelope, state_transitions)
    evidence_run = evidence.get("run_activation_proof") if isinstance(evidence.get("run_activation_proof"), Mapping) else {}
    blockers = list(evidence.get("completion_blockers") or [])
    cleanup_id = evidence.get("cleanup_id")
    valid = bool(
        evidence.get("schema_version") == CLEANUP_COMPLETION_SCHEMA_VERSION
        and evidence.get("mode") == CLEANUP_COMPLETION_MODE
        and evidence.get("cleanup_command") == CLEANUP_COMMAND
        and str(evidence.get("from_state") or "").strip().upper() == str(transition.get("from_state") or "").strip().upper()
        and evidence.get("from_state_version") == transition.get("from_state_version")
        and evidence.get("to_state") == CLEANUP_STATE
        and evidence.get("initiated_by") == transition.get("actor")
        and evidence.get("reason_code") == transition.get("reason_code")
        and list(evidence.get("cleanup_evidence_refs") or []) == list(transition.get("evidence_refs") or [])
        and isinstance(cleanup_id, str)
        and bool(cleanup_id.strip())
        and evidence_run.get("transition_id") == run_proof.get("transition_id")
        and run_proof.get("valid") is True
        and evidence.get("cleanup_started") is True
        and evidence.get("verified_completion_claimed") is False
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID_STAGE_3_2_8_CLEANUP_LINEAGE",
        "transition_id": transition.get("transition_id"),
        "cleanup_id": cleanup_id,
        "from_state": transition.get("from_state"),
        "to_state_version": transition.get("to_state_version"),
        "completion_blockers": blockers,
        "completion_prerequisites_ready": bool(valid and not blockers),
        "evidence": dict(evidence),
    }


def completion_verification_evidence(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    actor: str,
    reason_code: str,
    reason: str | None,
    evidence_refs: list[str],
    metadata: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    if current != CLEANUP_STATE:
        raise MissionValidationError("completion verification requires CLEANING_UP state")
    cleanup = _cleanup_lineage_proof(envelope, state_transitions)
    if not cleanup.get("valid") or cleanup.get("completion_blockers"):
        raise MissionValidationError("completion verification requires valid unblocked Stage-3.2.8 cleanup lineage")
    request = _completion_request_evaluation(
        envelope=envelope,
        metadata=metadata,
        evidence_refs=evidence_refs,
    )
    if not request.get("valid"):
        raise MissionValidationError("completion verification declaration is incomplete or inconsistent")
    snapshot = _canonical_envelope_snapshot(envelope)
    run_proof = _run_activation_lineage_proof(envelope, state_transitions)
    state_version = current_state.get("state_version")
    return {
        "schema_version": CLEANUP_COMPLETION_SCHEMA_VERSION,
        "mode": CLEANUP_COMPLETION_MODE,
        "mission_id": mission_id,
        "completion_id": _derived_control_id("completion", mission_id, state_version),
        "completion_command": COMPLETION_COMMAND,
        "from_state": CLEANUP_STATE,
        "from_state_version": state_version,
        "to_state": COMPLETION_STATE,
        "verified_by": actor,
        "reason_code": reason_code,
        "reason": reason,
        "cleanup_id": cleanup.get("cleanup_id"),
        "cleanup_transition_id": cleanup.get("transition_id"),
        "run_activation_proof": dict(run_proof),
        "canonical_envelope": dict(snapshot),
        "completion_declaration": dict(request.get("declaration") or {}),
        "verification_status": COMPLETION_VERIFICATION_STATUS,
        "objective_status": OBJECTIVE_COMPLETION_STATUS,
        "objective_evidence_refs": list(request.get("objective_evidence_refs") or []),
        "success_criteria_status": SUCCESS_CRITERIA_COMPLETION_STATUS,
        "success_criteria_count": request.get("success_criteria_count"),
        "criteria_results": list(request.get("criteria_results") or []),
        "cleanup_status": CLEANUP_VERIFICATION_STATUS,
        "cleanup_checks": list(request.get("cleanup_checks") or []),
        "outstanding_critical_dependencies": 0,
        "completion_evidence_refs": list(evidence_refs or []),
        "nested_evidence_refs_bound": True,
        "success_claimed": True,
        "verified_completion_claimed": True,
        "cleanup_completion_gate_applied": True,
        "terminal_state_immutable": True,
        "outgoing_transition_allowed_after_terminal": False,
        "resume_allowed_after_terminal": False,
        "automatic_retry_allowed_after_terminal": False,
        "authority_semantics": CLEANUP_COMPLETION_AUTHORITY_SEMANTICS,
        "cleanup_action_performed_by_orchestrator": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def _completion_lineage_proof(
    envelope: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    transition = None
    for candidate in reversed(list(state_transitions or [])):
        if str(candidate.get("to_state") or "").strip().upper() == COMPLETION_STATE:
            transition = candidate
            break
    if transition is None:
        return {
            "valid": False,
            "status": "COMPLETION_TRANSITION_MISSING",
            "transition_id": None,
            "completion_id": None,
            "terminal_command": COMPLETION_COMMAND,
            "terminal_state": COMPLETION_STATE,
            "evidence": None,
        }
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = metadata.get("mission_completion_verification") if isinstance(metadata, Mapping) else None
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "LEGACY_DIRECT_COMPLETED_NO_STAGE_3_2_8_EVIDENCE",
            "transition_id": transition.get("transition_id"),
            "completion_id": None,
            "terminal_command": COMPLETION_COMMAND,
            "terminal_state": COMPLETION_STATE,
            "evidence": None,
        }
    cleanup = _cleanup_lineage_proof(envelope, state_transitions)
    declaration = evidence.get("completion_declaration") if isinstance(evidence.get("completion_declaration"), Mapping) else {}
    request = _completion_request_evaluation(
        envelope=envelope,
        metadata={"completion": dict(declaration)},
        evidence_refs=list(transition.get("evidence_refs") or []),
    )
    snapshot = _canonical_envelope_snapshot(envelope)
    evidence_envelope = evidence.get("canonical_envelope") if isinstance(evidence.get("canonical_envelope"), Mapping) else {}
    completion_id = evidence.get("completion_id")
    valid = bool(
        evidence.get("schema_version") == CLEANUP_COMPLETION_SCHEMA_VERSION
        and evidence.get("mode") == CLEANUP_COMPLETION_MODE
        and evidence.get("completion_command") == COMPLETION_COMMAND
        and evidence.get("from_state") == CLEANUP_STATE
        and evidence.get("from_state_version") == transition.get("from_state_version")
        and evidence.get("to_state") == COMPLETION_STATE
        and evidence.get("verified_by") == transition.get("actor")
        and evidence.get("reason_code") == transition.get("reason_code")
        and evidence.get("cleanup_id") == cleanup.get("cleanup_id")
        and evidence.get("cleanup_transition_id") == cleanup.get("transition_id")
        and cleanup.get("valid") is True
        and not cleanup.get("completion_blockers")
        and request.get("valid") is True
        and evidence_envelope.get("canonical_sha256") == snapshot.get("canonical_sha256")
        and snapshot.get("integrity_verified") is True
        and list(evidence.get("completion_evidence_refs") or []) == list(transition.get("evidence_refs") or [])
        and evidence.get("verified_completion_claimed") is True
        and evidence.get("cleanup_completion_gate_applied") is True
        and isinstance(completion_id, str)
        and bool(completion_id.strip())
    )
    return {
        "valid": valid,
        "status": "VALID_VERIFIED_COMPLETION" if valid else "INVALID_STAGE_3_2_8_COMPLETION_LINEAGE",
        "transition_id": transition.get("transition_id"),
        "completion_id": completion_id,
        "terminal_id": completion_id,
        "terminal_command": COMPLETION_COMMAND,
        "terminal_state": COMPLETION_STATE,
        "cleanup_id": evidence.get("cleanup_id"),
        "verified_completion_claimed": evidence.get("verified_completion_claimed") is True,
        "cleanup_completion_gate_applied": evidence.get("cleanup_completion_gate_applied") is True,
        "evidence": dict(evidence),
    }


def cleanup_completion_contract(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    cleanup = _cleanup_lineage_proof(envelope, state_transitions)
    completion = _completion_lineage_proof(envelope, state_transitions) if current == COMPLETION_STATE else None
    run_proof = _run_activation_lineage_proof(envelope, state_transitions)
    snapshot = _canonical_envelope_snapshot(envelope)
    completion_prerequisites_ready = bool(
        current == CLEANUP_STATE
        and cleanup.get("valid")
        and not cleanup.get("completion_blockers")
        and run_proof.get("valid")
        and snapshot.get("integrity_verified")
    )
    return {
        "schema_version": CLEANUP_COMPLETION_SCHEMA_VERSION,
        "mode": CLEANUP_COMPLETION_MODE,
        "authority_semantics": CLEANUP_COMPLETION_AUTHORITY_SEMANTICS,
        "mission_id": mission_id,
        "current_state": current,
        "cleanup_command": CLEANUP_COMMAND,
        "cleanup_transition": ["RUNNING", "PAUSED", CLEANUP_STATE],
        "completion_command": COMPLETION_COMMAND,
        "completion_transition": f"{CLEANUP_STATE}->{COMPLETION_STATE}",
        "cleanup_lineage": cleanup,
        "run_activation_lineage": run_proof,
        "canonical_envelope": snapshot,
        "completion_prerequisites_ready": completion_prerequisites_ready,
        "completion_request_required_at_execution": current == CLEANUP_STATE,
        "completion_request_contract": {
            "metadata_path": "metadata.completion",
            "verification_status": COMPLETION_VERIFICATION_STATUS,
            "objective_status": OBJECTIVE_COMPLETION_STATUS,
            "objective_evidence_refs_required": True,
            "success_criteria_status": SUCCESS_CRITERIA_COMPLETION_STATUS,
            "criteria_results_exact_coverage_required": True,
            "criteria_result_evidence_refs_required": True,
            "cleanup_status": CLEANUP_VERIFICATION_STATUS,
            "cleanup_checks_required": True,
            "cleanup_check_status": CLEANUP_CHECK_STATUS,
            "cleanup_check_evidence_refs_required": True,
            "outstanding_critical_dependencies": 0,
            "command_evidence_refs_required": True,
            "nested_evidence_refs_must_be_bound_to_command": True,
        },
        "verified_completion_lineage": completion,
        "verified_completion_claimed": bool(completion and completion.get("valid")),
        "cleanup_completion_gate_applied": bool(completion and completion.get("valid")),
        "cleanup_action_performed_by_orchestrator": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }

def _terminal_lineage_proof(
    envelope: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    current_state: str,
) -> Dict[str, Any]:
    current = str(current_state or "").strip().upper()
    if current not in TERMINAL_STATES:
        return {
            "valid": False,
            "status": "NOT_TERMINAL",
            "transition_id": None,
            "terminal_id": None,
            "terminal_command": None,
            "terminal_state": None,
            "evidence": None,
        }
    if current == "COMPLETED":
        return _completion_lineage_proof(envelope, state_transitions)

    transition = None
    for candidate in reversed(list(state_transitions or [])):
        if str(candidate.get("to_state") or "").strip().upper() == current:
            transition = candidate
            break
    if transition is None:
        return {
            "valid": False,
            "status": "TERMINAL_TRANSITION_MISSING",
            "transition_id": None,
            "terminal_id": None,
            "terminal_command": None,
            "terminal_state": current,
            "evidence": None,
        }

    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = metadata.get("mission_terminal_control") if isinstance(metadata, Mapping) else None
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "LEGACY_DIRECT_TERMINAL_TRANSITION_NO_STAGE_3_2_7_EVIDENCE",
            "transition_id": transition.get("transition_id"),
            "terminal_id": None,
            "terminal_command": None,
            "terminal_state": current,
            "evidence": None,
        }

    command = str(evidence.get("terminal_command") or "").strip().upper()
    terminal_state = str(evidence.get("terminal_state") or "").strip().upper()
    terminal_id = evidence.get("terminal_id")
    valid = bool(
        evidence.get("schema_version") == TERMINAL_SEMANTICS_SCHEMA_VERSION
        and evidence.get("mode") == TERMINAL_SEMANTICS_MODE
        and command in TERMINAL_COMMAND_TARGETS
        and TERMINAL_COMMAND_TARGETS.get(command) == terminal_state
        and terminal_state == current
        and str(evidence.get("from_state") or "").strip().upper()
        == str(transition.get("from_state") or "").strip().upper()
        and evidence.get("from_state_version") == transition.get("from_state_version")
        and evidence.get("terminated_by") == transition.get("actor")
        and evidence.get("reason_code") == transition.get("reason_code")
        and list(evidence.get("terminal_evidence_refs") or []) == list(transition.get("evidence_refs") or [])
        and isinstance(terminal_id, str)
        and bool(terminal_id.strip())
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID_STAGE_3_2_7_TERMINAL_LINEAGE",
        "transition_id": transition.get("transition_id"),
        "terminal_id": terminal_id,
        "terminal_command": command or None,
        "terminal_state": terminal_state or current,
        "evidence": dict(evidence),
    }


def terminal_semantics_contract(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    current = str(current_state.get("state") or "").strip().upper()
    terminal = current in TERMINAL_STATES
    lineage = _terminal_lineage_proof(envelope, state_transitions, current) if terminal else None
    return {
        "schema_version": TERMINAL_SEMANTICS_SCHEMA_VERSION,
        "mode": TERMINAL_SEMANTICS_MODE,
        "authority_semantics": TERMINAL_SEMANTICS_AUTHORITY_SEMANTICS,
        "mission_id": mission_id,
        "current_state": current,
        "is_terminal": terminal,
        "terminal_commands": dict(TERMINAL_COMMAND_TARGETS),
        "semantic_profiles": {
            command: dict(profile) for command, profile in TERMINAL_SEMANTIC_PROFILES.items()
        },
        "current_terminal_lineage": lineage,
        "terminal_state_immutable": terminal,
        "outgoing_transition_allowed_after_terminal": False,
        "resume_allowed_after_terminal": False,
        "automatic_retry_allowed_after_terminal": False,
        "recovery_semantics": TERMINAL_RECOVERY_SEMANTICS,
        "evidence_refs_required_for_fail_safe_terminal_exit": False,
        "pip_binding_required_for_fail_safe_terminal_exit": False,
        "verified_completion_claimed": bool(
            current == COMPLETION_STATE and lineage and lineage.get("valid")
        ),
        "cleanup_completion_gate_applied": bool(
            current == COMPLETION_STATE and lineage and lineage.get("valid")
        ),
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def terminal_control_evidence(
    *,
    mission_id: str,
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    command: str,
    actor: str,
    reason_code: str,
    reason: str | None,
    evidence_refs: list[str],
    metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    command = str(command or "").strip().upper()
    if command not in TERMINAL_COMMAND_TARGETS:
        raise MissionValidationError("terminal control evidence requires ABORT, FAIL, or EXPIRE")
    current = str(current_state.get("state") or "").strip().upper()
    if current in TERMINAL_STATES:
        raise MissionValidationError("terminal control evidence cannot originate from a terminal state")

    state_version = current_state.get("state_version")
    profile = TERMINAL_SEMANTIC_PROFILES[command]
    active_wait = (
        _waiting_dependency_lineage_proof(state_transitions, current)
        if current in WAIT_STATE_KIND
        else None
    )
    active_pause = _pause_lineage_proof(state_transitions) if current == "PAUSED" else None
    active_replan = _replan_lineage_proof(state_transitions) if current == "REPLANNING" else None
    abandoned_contexts: list[str] = []
    if active_wait and active_wait.get("valid"):
        abandoned_contexts.append("WAITING_DEPENDENCY")
    if active_pause and active_pause.get("valid"):
        abandoned_contexts.append("PAUSE")
        if active_pause.get("active_waiting_dependency"):
            abandoned_contexts.append("PAUSED_WAITING_DEPENDENCY")
        if active_pause.get("active_replan"):
            abandoned_contexts.append("PAUSED_REPLAN")
    if active_replan and active_replan.get("valid"):
        abandoned_contexts.append("REPLAN")

    request_metadata = dict(metadata or {})
    terminal_context = request_metadata.get("terminal")
    if not isinstance(terminal_context, Mapping):
        terminal_context = {}

    target = TERMINAL_COMMAND_TARGETS[command]
    return {
        "schema_version": TERMINAL_SEMANTICS_SCHEMA_VERSION,
        "mode": TERMINAL_SEMANTICS_MODE,
        "mission_id": mission_id,
        "terminal_id": _derived_control_id(f"terminal-{command.lower()}", mission_id, state_version),
        "terminal_command": command,
        "terminal_state": target,
        "cause_family": profile["cause_family"],
        "disposition": profile["disposition"],
        "meaning": profile["meaning"],
        "from_state": current,
        "from_state_version": state_version,
        "terminated_by": actor,
        "reason_code": reason_code,
        "reason": reason,
        "terminal_evidence_refs": list(evidence_refs or []),
        "terminal_context": dict(terminal_context),
        "active_waiting_dependency": active_wait if active_wait and active_wait.get("valid") else None,
        "active_pause": active_pause if active_pause and active_pause.get("valid") else None,
        "active_replan": active_replan if active_replan and active_replan.get("valid") else None,
        "abandoned_control_contexts": abandoned_contexts,
        "success_claimed": False,
        "verified_completion_claimed": False,
        "cleanup_completion_gate_applied": False,
        "terminal_state_immutable": True,
        "outgoing_transition_allowed_after_terminal": False,
        "resume_allowed_after_terminal": False,
        "automatic_retry_allowed_after_terminal": False,
        "recovery_semantics": TERMINAL_RECOVERY_SEMANTICS,
        "authority_semantics": TERMINAL_SEMANTICS_AUTHORITY_SEMANTICS,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def _pip_activation_lineage_proof(
    envelope: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    transition = _matching_transition(
        state_transitions,
        from_state=ACTIVATION_FROM_STATE,
        to_state=ACTIVATION_TO_STATE,
    )
    if transition is None:
        return {"valid": False, "status": "MISSING", "transition_id": None}
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    activation = metadata.get("mission_activation") if isinstance(metadata, Mapping) else None
    if not isinstance(activation, Mapping):
        return {
            "valid": False,
            "status": "MISSING_STAGE_3_2_3_EVIDENCE",
            "transition_id": transition.get("transition_id"),
        }

    pip = _canonical_pip_binding(envelope)
    snapshot = _canonical_envelope_snapshot(envelope)
    proof_pip = activation.get("pip_binding") if isinstance(activation.get("pip_binding"), Mapping) else {}
    proof_envelope = (
        activation.get("canonical_envelope")
        if isinstance(activation.get("canonical_envelope"), Mapping)
        else {}
    )
    valid = bool(
        activation.get("schema_version") == ACTIVATION_SCHEMA_VERSION
        and activation.get("activation_command") == ACTIVATION_COMMAND
        and activation.get("from_state") == ACTIVATION_FROM_STATE
        and activation.get("to_state") == ACTIVATION_TO_STATE
        and activation.get("activation_ready") is True
        and proof_pip.get("pip_id") == pip.get("pip_id")
        and proof_pip.get("pip_version") == pip.get("pip_version")
        and proof_envelope.get("canonical_sha256") == snapshot.get("canonical_sha256")
        and snapshot.get("integrity_verified") is True
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID",
        "transition_id": transition.get("transition_id"),
        "to_state_version": transition.get("to_state_version"),
    }


def _planning_activation_lineage_proof(
    envelope: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    transition = _matching_transition(
        state_transitions,
        from_state=PLANNING_ACTIVATION_FROM_STATE,
        to_state=PLANNING_ACTIVATION_TO_STATE,
    )
    if transition is None:
        return {"valid": False, "status": "MISSING", "transition_id": None}
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = (
        metadata.get("mission_planning_run_activation")
        if isinstance(metadata, Mapping)
        else None
    )
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "MISSING_STAGE_3_2_4_EVIDENCE",
            "transition_id": transition.get("transition_id"),
        }

    pip_proof = _pip_activation_lineage_proof(envelope, state_transitions)
    pip = _canonical_pip_binding(envelope)
    snapshot = _canonical_envelope_snapshot(envelope)
    evidence_pip = evidence.get("pip_binding") if isinstance(evidence.get("pip_binding"), Mapping) else {}
    evidence_envelope = (
        evidence.get("canonical_envelope")
        if isinstance(evidence.get("canonical_envelope"), Mapping)
        else {}
    )
    evidence_pip_proof = (
        evidence.get("pip_activation_proof")
        if isinstance(evidence.get("pip_activation_proof"), Mapping)
        else {}
    )
    valid = bool(
        evidence.get("schema_version") == PLANNING_RUN_ACTIVATION_SCHEMA_VERSION
        and evidence.get("phase") == "PLANNING"
        and evidence.get("activation_command") == PLANNING_ACTIVATION_COMMAND
        and evidence.get("from_state") == PLANNING_ACTIVATION_FROM_STATE
        and evidence.get("to_state") == PLANNING_ACTIVATION_TO_STATE
        and evidence.get("activation_ready") is True
        and evidence_pip.get("pip_id") == pip.get("pip_id")
        and evidence_pip.get("pip_version") == pip.get("pip_version")
        and evidence_envelope.get("canonical_sha256") == snapshot.get("canonical_sha256")
        and evidence_pip_proof.get("transition_id") == pip_proof.get("transition_id")
        and pip_proof.get("valid") is True
        and snapshot.get("integrity_verified") is True
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID",
        "transition_id": transition.get("transition_id"),
        "to_state_version": transition.get("to_state_version"),
        "pip_activation_transition_id": pip_proof.get("transition_id"),
    }


def _run_activation_lineage_proof(
    envelope: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    transition = _matching_transition(
        state_transitions,
        from_state=RUN_ACTIVATION_FROM_STATE,
        to_state=RUN_ACTIVATION_TO_STATE,
    )
    if transition is None:
        return {"valid": False, "status": "MISSING", "transition_id": None}
    metadata = transition.get("metadata") if isinstance(transition, Mapping) else None
    evidence = (
        metadata.get("mission_planning_run_activation")
        if isinstance(metadata, Mapping)
        else None
    )
    if not isinstance(evidence, Mapping):
        return {
            "valid": False,
            "status": "MISSING_STAGE_3_2_4_EVIDENCE",
            "transition_id": transition.get("transition_id"),
        }

    planning_proof = _planning_activation_lineage_proof(envelope, state_transitions)
    snapshot = _canonical_envelope_snapshot(envelope)
    evidence_envelope = (
        evidence.get("canonical_envelope")
        if isinstance(evidence.get("canonical_envelope"), Mapping)
        else {}
    )
    evidence_planning = (
        evidence.get("planning_activation_proof")
        if isinstance(evidence.get("planning_activation_proof"), Mapping)
        else {}
    )
    valid = bool(
        evidence.get("schema_version") == PLANNING_RUN_ACTIVATION_SCHEMA_VERSION
        and evidence.get("phase") == "RUNNING"
        and evidence.get("activation_command") == RUN_ACTIVATION_COMMAND
        and evidence.get("from_state") == RUN_ACTIVATION_FROM_STATE
        and evidence.get("to_state") == RUN_ACTIVATION_TO_STATE
        and evidence.get("activation_ready") is True
        and evidence_envelope.get("canonical_sha256") == snapshot.get("canonical_sha256")
        and evidence_planning.get("transition_id") == planning_proof.get("transition_id")
        and planning_proof.get("valid") is True
        and snapshot.get("integrity_verified") is True
    )
    return {
        "valid": valid,
        "status": "VALID" if valid else "INVALID",
        "transition_id": transition.get("transition_id"),
        "to_state_version": transition.get("to_state_version"),
        "planning_activation_transition_id": planning_proof.get("transition_id"),
    }


def planning_run_activation_contract(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return Stage-3.2.4 planning/run activation readiness and lineage proofs.

    The contract activates Mission lifecycle phases only. It does not invoke a
    planner, produce a plan artifact, ask Governance for authorization, dispatch
    target actions, or authorize execution. The proof chain is entirely local and
    derives from the immutable Mission envelope plus the append-only transition
    ledger created by Stage 3.2.3 and this stage.
    """

    current = str(current_state.get("state") or "").strip().upper()
    envelope_ok = verify_envelope(envelope)
    pip_complete = _pip_binding_complete(envelope)
    pip_proof = _pip_activation_lineage_proof(envelope, state_transitions)
    planning_proof = _planning_activation_lineage_proof(envelope, state_transitions)
    run_proof = _run_activation_lineage_proof(envelope, state_transitions)

    planning_state_ready = current == PLANNING_ACTIVATION_FROM_STATE
    planning_topology_ready = is_legal_transition(current, PLANNING_ACTIVATION_TO_STATE)
    planning_ready = bool(
        planning_state_ready
        and planning_topology_ready
        and envelope_ok
        and pip_complete
        and pip_proof["valid"]
    )

    run_state_ready = current == RUN_ACTIVATION_FROM_STATE
    run_topology_ready = is_legal_transition(current, RUN_ACTIVATION_TO_STATE)
    run_ready = bool(
        run_state_ready
        and run_topology_ready
        and envelope_ok
        and pip_complete
        and pip_proof["valid"]
        and planning_proof["valid"]
    )

    return {
        "schema_version": PLANNING_RUN_ACTIVATION_SCHEMA_VERSION,
        "mode": PLANNING_RUN_ACTIVATION_MODE,
        "authority_semantics": PLANNING_RUN_ACTIVATION_AUTHORITY_SEMANTICS,
        "mission_id": mission_id,
        "current_state": current,
        "planning_activation": {
            "command": PLANNING_ACTIVATION_COMMAND,
            "from_state": PLANNING_ACTIVATION_FROM_STATE,
            "to_state": PLANNING_ACTIVATION_TO_STATE,
            "activation_ready": planning_ready,
            "checks": [
                {
                    "check_id": "PLANNING_SOURCE_STATE_PIP_BOUND",
                    "status": "PASS" if planning_state_ready else "FAIL",
                },
                {
                    "check_id": "PLANNING_TARGET_TOPOLOGY_PLANNING",
                    "status": "PASS" if planning_topology_ready else "FAIL",
                },
                {
                    "check_id": "PLANNING_CANONICAL_ENVELOPE_INTEGRITY",
                    "status": "PASS" if envelope_ok else "FAIL",
                },
                {
                    "check_id": "PLANNING_PIP_BINDING_COMPLETE",
                    "status": "PASS" if pip_complete else "FAIL",
                },
                {
                    "check_id": "PLANNING_PIP_ACTIVATION_LINEAGE",
                    "status": "PASS" if pip_proof["valid"] else "FAIL",
                    "transition_id": pip_proof.get("transition_id"),
                },
            ],
        },
        "run_activation": {
            "command": RUN_ACTIVATION_COMMAND,
            "from_state": RUN_ACTIVATION_FROM_STATE,
            "to_state": RUN_ACTIVATION_TO_STATE,
            "activation_ready": run_ready,
            "checks": [
                {
                    "check_id": "RUN_SOURCE_STATE_PLANNING",
                    "status": "PASS" if run_state_ready else "FAIL",
                },
                {
                    "check_id": "RUN_TARGET_TOPOLOGY_RUNNING",
                    "status": "PASS" if run_topology_ready else "FAIL",
                },
                {
                    "check_id": "RUN_CANONICAL_ENVELOPE_INTEGRITY",
                    "status": "PASS" if envelope_ok else "FAIL",
                },
                {
                    "check_id": "RUN_PIP_ACTIVATION_LINEAGE",
                    "status": "PASS" if pip_proof["valid"] else "FAIL",
                    "transition_id": pip_proof.get("transition_id"),
                },
                {
                    "check_id": "RUN_PLANNING_ACTIVATION_LINEAGE",
                    "status": "PASS" if planning_proof["valid"] else "FAIL",
                    "transition_id": planning_proof.get("transition_id"),
                },
            ],
        },
        "activation_chain": {
            "pip_activation": pip_proof,
            "planning_activation": planning_proof,
            "run_activation": run_proof,
            "chain_complete": bool(pip_proof["valid"] and planning_proof["valid"] and run_proof["valid"]),
        },
        "pip_binding": {
            **_canonical_pip_binding(envelope),
            "binding_source": "IMMUTABLE_CANONICAL_MISSION_ENVELOPE",
        },
        "canonical_envelope": _canonical_envelope_snapshot(envelope),
        "planner_invocation_performed": False,
        "plan_artifact_created": False,
        "governance_authorization_query_performed": False,
        "authorization_granted": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }


def planning_run_activation_evidence(
    *,
    mission_id: str,
    envelope: Mapping[str, Any],
    current_state: Mapping[str, Any],
    state_transitions: list[Mapping[str, Any]],
    command: str,
) -> Dict[str, Any]:
    projection = planning_run_activation_contract(
        mission_id=mission_id,
        envelope=envelope,
        current_state=current_state,
        state_transitions=state_transitions,
    )
    command = str(command or "").strip().upper()
    if command == PLANNING_ACTIVATION_COMMAND:
        phase = "PLANNING"
        phase_projection = projection["planning_activation"]
        activation_proof = {
            "pip_activation_proof": dict(projection["activation_chain"]["pip_activation"]),
        }
    elif command == RUN_ACTIVATION_COMMAND and projection["current_state"] == RUN_ACTIVATION_FROM_STATE:
        phase = "RUNNING"
        phase_projection = projection["run_activation"]
        activation_proof = {
            "pip_activation_proof": dict(projection["activation_chain"]["pip_activation"]),
            "planning_activation_proof": dict(projection["activation_chain"]["planning_activation"]),
        }
    else:
        raise MissionValidationError("Stage-3.2.4 activation evidence only applies to START_PLANNING or initial START from PLANNING")

    return {
        "schema_version": projection["schema_version"],
        "mode": projection["mode"],
        "phase": phase,
        "activation_command": command,
        "from_state": phase_projection["from_state"],
        "to_state": phase_projection["to_state"],
        "activation_ready": phase_projection["activation_ready"],
        "pip_binding": dict(projection["pip_binding"]),
        "canonical_envelope": dict(projection["canonical_envelope"]),
        **activation_proof,
        "authority_semantics": projection["authority_semantics"],
        "planner_invocation_performed": False,
        "plan_artifact_created": False,
        "governance_authorization_query_performed": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }

def lifecycle_command_contract() -> Dict[str, Any]:
    return {
        "schema_version": LIFECYCLE_COMMAND_SCHEMA_VERSION,
        "mode": LIFECYCLE_COMMAND_MODE,
        "guarded_operation": LIFECYCLE_COMMAND_OPERATION,
        "required_request_fields": [
            "command_id",
            "idempotency_key",
            "command",
            "expected_version_sha256",
            "expected_state_version",
            "actor",
            "reason_code",
        ],
        "optional_request_fields": ["reason", "evidence_refs", "target_state", "metadata"],
        "commands": list(LIFECYCLE_COMMANDS),
        "fixed_target_states": dict(FIXED_TARGETS),
        "resume_target_states": list(RESUME_TARGETS),
        "version_vector_guard_required": True,
        "state_version_guard_required": True,
        "idempotency_required": True,
        "canonical_state_legality_delegated_to": "STAGE_3_1_2_CANONICAL_STATE_MACHINE",
        "stage3_2_2_guard_matrix_not_implemented": False,
        "guard_matrix_schema_version": GUARD_MATRIX_SCHEMA_VERSION,
        "guard_matrix_enabled": True,
        "guard_matrix_applies_to": GUARD_MATRIX_APPLIES_TO,
        "stage3_2_3_activation_contract_schema_version": ACTIVATION_SCHEMA_VERSION,
        "stage3_2_3_activation_mode": ACTIVATION_MODE,
        "stage3_2_3_activation_command": ACTIVATION_COMMAND,
        "stage3_2_4_planning_run_activation_schema_version": PLANNING_RUN_ACTIVATION_SCHEMA_VERSION,
        "stage3_2_4_planning_run_activation_mode": PLANNING_RUN_ACTIVATION_MODE,
        "stage3_2_4_planning_activation_command": PLANNING_ACTIVATION_COMMAND,
        "stage3_2_4_run_activation_command": RUN_ACTIVATION_COMMAND,
        "stage3_2_5_waiting_dependency_schema_version": WAITING_DEPENDENCY_SCHEMA_VERSION,
        "stage3_2_5_waiting_dependency_mode": WAITING_DEPENDENCY_MODE,
        "stage3_2_5_wait_commands": dict(WAIT_COMMAND_KIND),
        "stage3_2_5_waiting_return_command": "START",
        "stage3_2_5_waiting_resolution_status_required": DEPENDENCY_RESOLUTION_STATUS,
        "stage3_2_6_pause_resume_replan_schema_version": PAUSE_RESUME_REPLAN_SCHEMA_VERSION,
        "stage3_2_6_pause_resume_replan_mode": PAUSE_RESUME_REPLAN_MODE,
        "stage3_2_6_pause_command": "PAUSE",
        "stage3_2_6_resume_command": "RESUME",
        "stage3_2_6_replan_command": "REPLAN",
        "stage3_2_6_replan_return_command": "START",
        "stage3_2_6_replan_readiness_status": REPLAN_READINESS_STATUS,
        "stage3_2_7_terminal_semantics_schema_version": TERMINAL_SEMANTICS_SCHEMA_VERSION,
        "stage3_2_7_terminal_semantics_mode": TERMINAL_SEMANTICS_MODE,
        "stage3_2_7_terminal_commands": dict(TERMINAL_COMMAND_TARGETS),
        "stage3_2_7_terminal_recovery_semantics": TERMINAL_RECOVERY_SEMANTICS,
        "stage3_2_7_terminal_states_immutable": True,
        "stage3_2_7_terminal_evidence_refs_required": False,
        "stage3_2_8_cleanup_completion_schema_version": CLEANUP_COMPLETION_SCHEMA_VERSION,
        "stage3_2_8_cleanup_completion_mode": CLEANUP_COMPLETION_MODE,
        "stage3_2_8_cleanup_command": CLEANUP_COMMAND,
        "stage3_2_8_completion_command": COMPLETION_COMMAND,
        "stage3_2_8_completion_verification_status": COMPLETION_VERIFICATION_STATUS,
        "stage3_2_8_completion_evidence_refs_required": True,
        "stage3_2_8_exact_success_criteria_coverage_required": True,
        "stage3_2_8_cleanup_checks_required": True,
        "stage3_2_8_outstanding_critical_dependencies_required": 0,
        "authorization_authority_changed": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
