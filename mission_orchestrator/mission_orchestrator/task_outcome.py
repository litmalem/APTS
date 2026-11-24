from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .execution_lineage import verify_execution_recovery_checkpoint_contract
from .execution_result import verify_execution_result_capture_contract
from .execution_termination import verify_outcome_propagation_contract
from .execution_attempt import verify_execution_attempt_contract

TASK_OUTCOME_STAGE_SCHEMA_VERSION = "apts-task-outcome-contract-identity-v1"
TASK_OUTCOME_CONTRACT_SCHEMA_VERSION = "apts-canonical-task-outcome-contract-v1"
TASK_OUTCOME_HASH_DOMAIN = "MISSION_CANONICAL_TASK_OUTCOME_CONTRACT_V1"
TASK_OUTCOME_REQUEST_HASH_DOMAIN = "MISSION_TASK_OUTCOME_MATERIALIZATION_REQUEST_V1"
TASK_OUTCOME_ID_PREFIX = "toutcome-"
TASK_OUTCOME_MODE = "IMMUTABLE_TASK_OUTCOME_IDENTITY_BOUND_TO_VERIFIED_TERMINAL_EXECUTION_PENDING_ACCEPTANCE"
TASK_OUTCOME_AUTHORITY = "MISSION_ORCHESTRATOR_TASK_OUTCOME_MATERIALIZATION"
TASK_OUTCOME_CONTRACT_STATUS = "MATERIALIZED_PENDING_TASK_OUTCOME_ACCEPTANCE"
TASK_OUTCOME_ALLOWED_MISSION_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})
TASK_OUTCOME_SOURCE_STATUSES = frozenset({
    "VERIFIED_COMPLETED",
    "VERIFIED_FAILED",
    "VERIFIED_CANCELLED",
    "VERIFIED_TIMED_OUT",
})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_execution_attempt_id",
    "expected_execution_attempt_sha256",
    "expected_result_capture_id",
    "expected_result_capture_sha256",
    "expected_outcome_propagation_id",
    "expected_outcome_propagation_sha256",
    "expected_execution_recovery_checkpoint_id",
    "expected_execution_recovery_checkpoint_sha256",
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


def new_task_outcome_id() -> str:
    return f"{TASK_OUTCOME_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_task_outcome_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task outcome materialization request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task outcome materialization field(s): "
            + ", ".join(unknown)
            + "; Stage 3.6.1 derives task outcome classification/status/evidence and completion semantics from immutable Stage-3.5 artifacts. Caller-supplied outcome, acceptance, completion, dependency-release, readiness, mission-completion, runtime, Governance, dispatch, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_attempt_id": _string(payload, "expected_execution_attempt_id"),
        "expected_result_capture_id": _string(payload, "expected_result_capture_id"),
        "expected_outcome_propagation_id": _string(payload, "expected_outcome_propagation_id"),
        "expected_execution_recovery_checkpoint_id": _string(payload, "expected_execution_recovery_checkpoint_id"),
        "created_by": _string(payload, "created_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_execution_attempt_id"].startswith("xattempt-"):
        raise MissionValidationError("expected_execution_attempt_id must be a canonical xattempt-* identifier")
    if not values["expected_result_capture_id"].startswith("xresult-"):
        raise MissionValidationError("expected_result_capture_id must be a canonical xresult-* identifier")
    if not values["expected_outcome_propagation_id"].startswith("xprop-"):
        raise MissionValidationError("expected_outcome_propagation_id must be a canonical xprop-* identifier")
    if not values["expected_execution_recovery_checkpoint_id"].startswith("xrecover-"):
        raise MissionValidationError("expected_execution_recovery_checkpoint_id must be a canonical xrecover-* identifier")

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
        "expected_execution_attempt_sha256": _sha(payload, "expected_execution_attempt_sha256"),
        "expected_result_capture_sha256": _sha(payload, "expected_result_capture_sha256"),
        "expected_outcome_propagation_sha256": _sha(payload, "expected_outcome_propagation_sha256"),
        "expected_execution_recovery_checkpoint_sha256": _sha(payload, "expected_execution_recovery_checkpoint_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_outcome_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_OUTCOME_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_task_outcome_contract(
    *,
    task_outcome_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    execution_attempt: Mapping[str, Any],
    result_capture: Mapping[str, Any],
    outcome_propagation: Mapping[str, Any],
    recovery_checkpoint: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    if not verify_execution_attempt_contract(execution_attempt["execution_attempt_contract"]):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    if not verify_execution_result_capture_contract(result_capture["execution_result_capture_contract"]):
        raise MissionValidationError("Stage-3.5.7 execution-result capture failed integrity verification")
    if not verify_outcome_propagation_contract(outcome_propagation["outcome_propagation_contract"]):
        raise MissionValidationError("Stage-3.5.8 outcome-propagation contract failed integrity verification")
    if not verify_execution_recovery_checkpoint_contract(recovery_checkpoint["recovery_checkpoint"]):
        raise MissionValidationError("Stage-3.5.9 execution-recovery checkpoint failed integrity verification")

    prop_contract = outcome_propagation["outcome_propagation_contract"]
    outcome = prop_contract["outcome_verification"]
    if outcome["task_outcome_status"] not in TASK_OUTCOME_SOURCE_STATUSES:
        raise MissionValidationError("Stage-3.5.8 task outcome status is not canonical for Stage 3.6.1")

    core = {
        "schema_version": TASK_OUTCOME_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": TASK_OUTCOME_STAGE_SCHEMA_VERSION,
        "identity": {
            "task_outcome_id": task_outcome_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": execution_attempt["planned_task_id"],
            "task_key": execution_attempt["task_key"],
            "execution_attempt_id": execution_attempt["execution_attempt_id"],
            "result_capture_id": result_capture["result_capture_id"],
            "outcome_propagation_id": outcome_propagation["outcome_propagation_id"],
            "execution_recovery_checkpoint_id": recovery_checkpoint["checkpoint_id"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "execution_attempt_sha256": execution_attempt["canonical_sha256"],
            "result_capture_sha256": result_capture["canonical_sha256"],
            "outcome_propagation_sha256": outcome_propagation["canonical_sha256"],
            "execution_recovery_checkpoint_sha256": recovery_checkpoint["canonical_sha256"],
            "result_execution_state": result_capture["execution_state"],
            "source_task_outcome_status": outcome["task_outcome_status"],
            "outcome_classification": outcome["outcome_classification"],
            "evidence_manifest_sha256": result_capture["evidence_manifest_sha256"],
            "artifact_manifest_sha256": result_capture["artifact_manifest_sha256"],
        },
        "task_outcome": {
            "contract_status": TASK_OUTCOME_CONTRACT_STATUS,
            "execution_state": result_capture["execution_state"],
            "source_task_outcome_status": outcome["task_outcome_status"],
            "outcome_classification": outcome["outcome_classification"],
            "terminal_execution_outcome_bound": True,
            "evidence_manifest_bound": True,
            "artifact_manifest_bound": True,
            "execution_recovery_checkpoint_bound": True,
            "task_outcome_identity_materialized": True,
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
            "authority": TASK_OUTCOME_AUTHORITY,
            "mode": TASK_OUTCOME_MODE,
            "execution_result_is_task_outcome_identity": False,
            "outcome_propagation_is_task_completion_commit": False,
            "task_outcome_identity_is_task_acceptance": False,
            "task_outcome_identity_is_task_completion": False,
            "task_outcome_identity_is_dependency_release": False,
            "task_outcome_identity_is_mission_completion": False,
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
            "created_by": request["created_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "created_at": created_at,
        },
    }
    digest = sha256_hex({"hash_domain": TASK_OUTCOME_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_task_outcome_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        outcome = contract["task_outcome"]
        boundary = contract["authority_boundary"]
        return (
            contract["schema_version"] == TASK_OUTCOME_CONTRACT_SCHEMA_VERSION
            and contract["stage_schema_version"] == TASK_OUTCOME_STAGE_SCHEMA_VERSION
            and str(identity["task_outcome_id"]).startswith(TASK_OUTCOME_ID_PREFIX)
            and str(identity["plan_version_record_id"]).startswith("pver-")
            and str(identity["execution_attempt_id"]).startswith("xattempt-")
            and str(identity["result_capture_id"]).startswith("xresult-")
            and str(identity["outcome_propagation_id"]).startswith("xprop-")
            and str(identity["execution_recovery_checkpoint_id"]).startswith("xrecover-")
            and source["source_task_outcome_status"] in TASK_OUTCOME_SOURCE_STATUSES
            and outcome["source_task_outcome_status"] == source["source_task_outcome_status"]
            and outcome["contract_status"] == TASK_OUTCOME_CONTRACT_STATUS
            and outcome["task_outcome_identity_materialized"] is True
            and outcome["task_outcome_acceptance_performed"] is False
            and outcome["task_completion_commit_performed"] is False
            and outcome["dependency_release_performed"] is False
            and outcome["mission_success_completion_authority_exercised"] is False
            and boundary["authority"] == TASK_OUTCOME_AUTHORITY
            and boundary["mode"] == TASK_OUTCOME_MODE
            and boundary["governance_query_performed"] is False
            and boundary["runtime_query_performed"] is False
            and boundary["runtime_control_io_performed"] is False
            and boundary["dispatch_redelivery_performed"] is False
            and boundary["new_execution_attempt_created"] is False
            and boundary["new_target_action_dispatch_performed"] is False
            and boundary["external_network_io_performed"] is False
            and boundary["target_actuation"] is False
            and boundary["mission_state_transition_performed"] is False
            and digest == sha256_hex({"hash_domain": TASK_OUTCOME_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_task_outcome_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": TASK_OUTCOME_STAGE_SCHEMA_VERSION,
        "schema_version": TASK_OUTCOME_CONTRACT_SCHEMA_VERSION,
        "identity_prefix": TASK_OUTCOME_ID_PREFIX,
        "mode": TASK_OUTCOME_MODE,
        "authority": TASK_OUTCOME_AUTHORITY,
        "contract_status": TASK_OUTCOME_CONTRACT_STATUS,
        "allowed_mission_states": sorted(TASK_OUTCOME_ALLOWED_MISSION_STATES),
        "source_task_outcome_statuses": sorted(TASK_OUTCOME_SOURCE_STATUSES),
        "requires_stage3510_closed_runtime_release": True,
        "requires_active_plan_version": True,
        "requires_stage354_execution_attempt": True,
        "requires_stage357_terminal_result_capture": True,
        "requires_stage358_verified_outcome_propagation": True,
        "requires_stage359_execution_recovery_checkpoint": True,
        "one_task_outcome_identity_per_plan_task": True,
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
        "next_stage": "3.6.2",
    }
