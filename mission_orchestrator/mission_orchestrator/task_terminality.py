from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .task_outcome import (
    TASK_OUTCOME_SOURCE_STATUSES,
    verify_task_outcome_contract,
)

TASK_TERMINALITY_STAGE_SCHEMA_VERSION = "apts-task-terminality-completion-eligibility-v1"
TASK_TERMINALITY_CONTRACT_SCHEMA_VERSION = "apts-task-terminality-completion-eligibility-contract-v1"
TASK_TERMINALITY_HASH_DOMAIN = "MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_V1"
TASK_TERMINALITY_REQUEST_HASH_DOMAIN = "MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_REQUEST_V1"
TASK_TERMINALITY_ID_PREFIX = "telig-"
TASK_TERMINALITY_MODE = "DETERMINISTIC_LOCAL_TERMINALITY_AND_COMPLETION_ELIGIBILITY_NO_COMPLETION_COMMIT"
TASK_TERMINALITY_AUTHORITY = "MISSION_ORCHESTRATOR_TASK_TERMINALITY_COMPLETION_ELIGIBILITY"
TASK_TERMINALITY_GATE_STATUS = "EVALUATED"
TASK_TERMINALITY_ALLOWED_MISSION_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})

TERMINALITY_BY_SOURCE_STATUS = {
    "VERIFIED_COMPLETED": {
        "terminality_status": "TERMINAL_SUCCESS",
        "terminality_reason_code": "VERIFIED_SUCCESSFUL_TERMINAL_EXECUTION",
        "completion_eligibility_status": "ELIGIBLE_FOR_COMPLETION_EVALUATION",
        "completion_eligible": True,
        "eligibility_reason_code": "VERIFIED_COMPLETED_OUTCOME",
    },
    "VERIFIED_FAILED": {
        "terminality_status": "TERMINAL_FAILURE",
        "terminality_reason_code": "VERIFIED_FAILED_TERMINAL_EXECUTION",
        "completion_eligibility_status": "NOT_ELIGIBLE_FOR_COMPLETION",
        "completion_eligible": False,
        "eligibility_reason_code": "FAILED_OUTCOME_CANNOT_SATISFY_COMPLETION",
    },
    "VERIFIED_CANCELLED": {
        "terminality_status": "TERMINAL_CANCELLED",
        "terminality_reason_code": "VERIFIED_CANCELLED_TERMINAL_EXECUTION",
        "completion_eligibility_status": "NOT_ELIGIBLE_FOR_COMPLETION",
        "completion_eligible": False,
        "eligibility_reason_code": "CANCELLED_OUTCOME_CANNOT_SATISFY_COMPLETION",
    },
    "VERIFIED_TIMED_OUT": {
        "terminality_status": "TERMINAL_TIMED_OUT",
        "terminality_reason_code": "VERIFIED_TIMED_OUT_TERMINAL_EXECUTION",
        "completion_eligibility_status": "NOT_ELIGIBLE_FOR_COMPLETION",
        "completion_eligible": False,
        "eligibility_reason_code": "TIMED_OUT_OUTCOME_CANNOT_SATISFY_COMPLETION",
    },
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_task_outcome_id",
    "expected_task_outcome_sha256",
    "evaluated_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_task_terminality_eligibility_id() -> str:
    return f"{TASK_TERMINALITY_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_task_terminality_eligibility_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task terminality/completion eligibility request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task terminality/completion eligibility field(s): "
            + ", ".join(unknown)
            + "; Stage 3.6.2 derives terminality and completion eligibility from the immutable Stage-3.6.1 task outcome. "
              "Caller-supplied terminality, eligibility, acceptance, completion, dependency-release, readiness, mission-completion, "
              "runtime, Governance, dispatch, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_task_outcome_id": _string(payload, "expected_task_outcome_id"),
        "evaluated_by": _string(payload, "evaluated_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_task_outcome_id"].startswith("toutcome-"):
        raise MissionValidationError("expected_task_outcome_id must be a canonical toutcome-* identifier")

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
        "expected_task_outcome_sha256": _sha(payload, "expected_task_outcome_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_terminality_eligibility_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_TERMINALITY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def classify_task_terminality_and_completion_eligibility(source_task_outcome_status: str) -> Dict[str, Any]:
    if source_task_outcome_status not in TERMINALITY_BY_SOURCE_STATUS:
        raise MissionValidationError(
            f"source_task_outcome_status={source_task_outcome_status!r} is not a canonical terminal Stage-3.6.1 status"
        )
    return dict(TERMINALITY_BY_SOURCE_STATUS[source_task_outcome_status])


def build_task_terminality_eligibility_contract(
    *,
    eligibility_gate_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    task_outcome: Mapping[str, Any],
    evaluated_at: str,
) -> Dict[str, Any]:
    contract = task_outcome["task_outcome_contract"]
    if not verify_task_outcome_contract(contract):
        raise MissionValidationError("Stage-3.6.1 task-outcome contract failed integrity verification")

    source_status = task_outcome["source_task_outcome_status"]
    if source_status not in TASK_OUTCOME_SOURCE_STATUSES:
        raise MissionValidationError("Stage-3.6.1 task outcome is not a canonical terminal source status")
    classification = classify_task_terminality_and_completion_eligibility(source_status)

    source_outcome = contract["task_outcome"]
    if source_outcome.get("task_outcome_identity_materialized") is not True:
        raise MissionValidationError("Stage-3.6.1 task-outcome identity was not materialized")
    if source_outcome.get("task_outcome_acceptance_performed") is not False:
        raise MissionValidationError("Stage-3.6.1 source unexpectedly claims task-outcome acceptance")
    if source_outcome.get("task_completion_commit_performed") is not False:
        raise MissionValidationError("Stage-3.6.1 source unexpectedly claims task completion")

    core = {
        "schema_version": TASK_TERMINALITY_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": TASK_TERMINALITY_STAGE_SCHEMA_VERSION,
        "identity": {
            "eligibility_gate_id": eligibility_gate_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": task_outcome["planned_task_id"],
            "task_key": task_outcome["task_key"],
            "task_outcome_id": task_outcome["task_outcome_id"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "task_outcome_sha256": task_outcome["canonical_sha256"],
            "task_outcome_contract_status": task_outcome["contract_status"],
            "execution_state": task_outcome["execution_state"],
            "source_task_outcome_status": source_status,
            "outcome_classification": task_outcome["outcome_classification"],
        },
        "terminality": {
            "gate_status": TASK_TERMINALITY_GATE_STATUS,
            "terminality_confirmed": True,
            "terminality_status": classification["terminality_status"],
            "terminality_reason_code": classification["terminality_reason_code"],
            "source_is_immutable_task_outcome": True,
            "source_is_terminal_execution_outcome": True,
        },
        "completion_eligibility": {
            "completion_eligibility_status": classification["completion_eligibility_status"],
            "completion_eligible": bool(classification["completion_eligible"]),
            "eligibility_reason_code": classification["eligibility_reason_code"],
            "eligibility_is_completion_commit": False,
            "eligibility_is_acceptance_decision": False,
            "task_outcome_acceptance_performed": False,
            "acceptance_criteria_evaluation_performed": False,
            "task_completion_commit_performed": False,
            "task_state_transition_performed": False,
            "dependency_release_performed": False,
            "readiness_recalculation_performed": False,
            "plan_progression_performed": False,
            "mission_success_completion_authority_exercised": False,
        },
        "authority_boundary": {
            "authority": TASK_TERMINALITY_AUTHORITY,
            "mode": TASK_TERMINALITY_MODE,
            "classification_is_deterministic_local_projection": True,
            "task_outcome_identity_is_mutated": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False,
            "new_target_action_dispatch_performed": False,
            "external_network_io_performed": False,
            "target_actuation": False,
            "mission_state_transition_performed": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "evaluated_by": request["evaluated_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "evaluated_at": evaluated_at,
        },
    }
    digest = sha256_hex({"hash_domain": TASK_TERMINALITY_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_task_terminality_eligibility_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        terminality = contract["terminality"]
        eligibility = contract["completion_eligibility"]
        boundary = contract["authority_boundary"]
        expected = classify_task_terminality_and_completion_eligibility(source["source_task_outcome_status"])
        return (
            contract["schema_version"] == TASK_TERMINALITY_CONTRACT_SCHEMA_VERSION
            and contract["stage_schema_version"] == TASK_TERMINALITY_STAGE_SCHEMA_VERSION
            and str(identity["eligibility_gate_id"]).startswith(TASK_TERMINALITY_ID_PREFIX)
            and str(identity["plan_version_record_id"]).startswith("pver-")
            and str(identity["task_outcome_id"]).startswith("toutcome-")
            and source["source_task_outcome_status"] in TASK_OUTCOME_SOURCE_STATUSES
            and terminality["gate_status"] == TASK_TERMINALITY_GATE_STATUS
            and terminality["terminality_confirmed"] is True
            and terminality["terminality_status"] == expected["terminality_status"]
            and terminality["terminality_reason_code"] == expected["terminality_reason_code"]
            and eligibility["completion_eligibility_status"] == expected["completion_eligibility_status"]
            and eligibility["completion_eligible"] is bool(expected["completion_eligible"])
            and eligibility["eligibility_reason_code"] == expected["eligibility_reason_code"]
            and eligibility["eligibility_is_completion_commit"] is False
            and eligibility["eligibility_is_acceptance_decision"] is False
            and eligibility["task_outcome_acceptance_performed"] is False
            and eligibility["acceptance_criteria_evaluation_performed"] is False
            and eligibility["task_completion_commit_performed"] is False
            and eligibility["dependency_release_performed"] is False
            and eligibility["mission_success_completion_authority_exercised"] is False
            and boundary["authority"] == TASK_TERMINALITY_AUTHORITY
            and boundary["mode"] == TASK_TERMINALITY_MODE
            and boundary["classification_is_deterministic_local_projection"] is True
            and boundary["task_outcome_identity_is_mutated"] is False
            and boundary["governance_query_performed"] is False
            and boundary["runtime_query_performed"] is False
            and boundary["runtime_control_io_performed"] is False
            and boundary["dispatch_redelivery_performed"] is False
            and boundary["new_execution_attempt_created"] is False
            and boundary["new_target_action_dispatch_performed"] is False
            and boundary["external_network_io_performed"] is False
            and boundary["target_actuation"] is False
            and boundary["mission_state_transition_performed"] is False
            and digest == sha256_hex({"hash_domain": TASK_TERMINALITY_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_task_terminality_eligibility_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": TASK_TERMINALITY_STAGE_SCHEMA_VERSION,
        "schema_version": TASK_TERMINALITY_CONTRACT_SCHEMA_VERSION,
        "identity_prefix": TASK_TERMINALITY_ID_PREFIX,
        "mode": TASK_TERMINALITY_MODE,
        "authority": TASK_TERMINALITY_AUTHORITY,
        "gate_status": TASK_TERMINALITY_GATE_STATUS,
        "allowed_mission_states": sorted(TASK_TERMINALITY_ALLOWED_MISSION_STATES),
        "source_task_outcome_statuses": sorted(TASK_OUTCOME_SOURCE_STATUSES),
        "classification_matrix": {
            key: dict(value) for key, value in sorted(TERMINALITY_BY_SOURCE_STATUS.items())
        },
        "requires_stage361_task_outcome_identity": True,
        "requires_active_plan_version": True,
        "one_eligibility_gate_per_task_outcome": True,
        "terminality_confirmed_from_immutable_source": True,
        "completion_eligible_only_for_verified_completed": True,
        "task_outcome_acceptance_performed": False,
        "acceptance_criteria_evaluation_performed": False,
        "task_completion_commit_performed": False,
        "task_state_transition_performed": False,
        "dependency_release_performed": False,
        "readiness_recalculation_performed": False,
        "plan_progression_performed": False,
        "mission_success_completion_authority_exercised": False,
        "governance_query_performed": False,
        "runtime_query_performed": False,
        "runtime_control_io_performed": False,
        "dispatch_redelivery_performed": False,
        "new_execution_attempt_created": False,
        "new_target_action_dispatch_performed": False,
        "external_network_io_performed": False,
        "target_actuation": False,
        "mission_state_transition_performed": False,
        "next_stage": "3.6.3",
    }
