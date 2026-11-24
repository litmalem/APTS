from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError
from .plan_versioning import verify_plan_version_contract
from .task_completion import TASK_COMPLETION_STATUS, verify_task_completion_contract
from .task_outcome import TASK_OUTCOME_SOURCE_STATUSES, verify_task_outcome_contract

MISSION_OUTCOME_AGGREGATION_STAGE_SCHEMA_VERSION = "apts-mission-outcome-aggregation-v1"
MISSION_OUTCOME_AGGREGATION_CONTRACT_SCHEMA_VERSION = "apts-mission-outcome-aggregation-contract-v1"
MISSION_OUTCOME_AGGREGATION_HASH_DOMAIN = "MISSION_OUTCOME_AGGREGATION_V1"
MISSION_OUTCOME_AGGREGATION_REQUEST_HASH_DOMAIN = "MISSION_OUTCOME_AGGREGATION_REQUEST_V1"
MISSION_OUTCOME_SOURCE_SNAPSHOT_HASH_DOMAIN = "MISSION_OUTCOME_SOURCE_SNAPSHOT_V1"
MISSION_OUTCOME_AGGREGATION_ID_PREFIX = "moutcome-"
MISSION_OUTCOME_AGGREGATION_MODE = (
    "DETERMINISTIC_ACTIVE_PLAN_TASK_OUTCOME_AGGREGATION_"
    "NO_SUCCESS_CRITERIA_EVALUATION_NO_PLAN_OR_MISSION_COMPLETION"
)
MISSION_OUTCOME_AGGREGATION_AUTHORITY = "MISSION_ORCHESTRATOR_MISSION_OUTCOME_AGGREGATION"
MISSION_OUTCOME_AGGREGATION_STATUS = "MISSION_EXECUTION_OUTCOME_AGGREGATED"
MISSION_OUTCOME_ALLOWED_MISSION_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})
MISSION_OUTCOME_TASK_CLASSIFICATIONS = (
    "VERIFIED_COMPLETE",
    "FAILED",
    "CANCELLED",
    "TIMED_OUT",
    "RUNNING",
    "BLOCKED",
    "PENDING",
)
TERMINAL_MISSION_OUTCOME_TASK_CLASSIFICATIONS = frozenset({
    "VERIFIED_COMPLETE", "FAILED", "CANCELLED", "TIMED_OUT"
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
    "aggregated_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_mission_outcome_aggregation_id() -> str:
    return f"{MISSION_OUTCOME_AGGREGATION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_mission_outcome_aggregation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("mission outcome aggregation request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported mission outcome aggregation field(s): "
            + ", ".join(unknown)
            + "; Stage 3.6.5 derives the active-Plan task set, task classifications, counts, and source bindings from durable Mission Orchestrator state. Caller-supplied classifications, success-criteria decisions, completion readiness, Plan/Mission progression, Governance/runtime, dispatch, execution, or actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "aggregated_by": _string(payload, "aggregated_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
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
        "reason": reason,
        "metadata": dict(metadata),
    }


def mission_outcome_aggregation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": MISSION_OUTCOME_AGGREGATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _validate_same_plan(item: Mapping[str, Any], active_plan: Mapping[str, Any], kind: str) -> None:
    if item.get("plan_version_record_id") != active_plan.get("plan_version_record_id"):
        raise MissionValidationError(f"{kind} is from a stale/superseded Plan")
    if int(item.get("plan_version", -1)) != int(active_plan.get("plan_version", -2)):
        raise MissionValidationError(f"{kind} Plan version mismatch")


def derive_mission_outcome_aggregation(
    *,
    active_plan: Mapping[str, Any],
    task_outcomes: Sequence[Mapping[str, Any]],
    task_completions: Sequence[Mapping[str, Any]],
    running_projections: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    plan_contract = active_plan.get("plan_version_contract")
    if not isinstance(plan_contract, Mapping) or not verify_plan_version_contract(plan_contract):
        raise MissionValidationError("active Stage-3.3.7 Plan version failed integrity verification")
    steps = sorted(list(plan_contract["candidate_plan"].get("plan_steps") or []), key=lambda x: int(x["step_index"]))
    if not steps:
        raise MissionValidationError("active Plan candidate has no plan_steps")
    by_key = {str(step["task_key"]): step for step in steps}
    if len(by_key) != len(steps):
        raise MissionValidationError("active Plan task keys are not unique")

    completion_by_task: Dict[str, Mapping[str, Any]] = {}
    for item in task_completions:
        _validate_same_plan(item, active_plan, "Stage-3.6.4 task completion")
        if not verify_task_completion_contract(item["task_completion_contract"]):
            raise MissionValidationError("Stage-3.6.4 task completion failed integrity verification")
        if item.get("completion_status") != TASK_COMPLETION_STATUS or item.get("task_completion_committed") is not True:
            raise MissionValidationError("Stage-3.6.4 task completion is not canonically committed")
        task_id = str(item.get("planned_task_id") or "")
        if task_id in completion_by_task:
            raise MissionValidationError("duplicate Stage-3.6.4 completion for active Plan task")
        completion_by_task[task_id] = item

    outcome_by_task: Dict[str, Mapping[str, Any]] = {}
    for item in task_outcomes:
        _validate_same_plan(item, active_plan, "Stage-3.6.1 task outcome")
        if not verify_task_outcome_contract(item["task_outcome_contract"]):
            raise MissionValidationError("Stage-3.6.1 task outcome failed integrity verification")
        if item.get("source_task_outcome_status") not in TASK_OUTCOME_SOURCE_STATUSES:
            raise MissionValidationError("Stage-3.6.1 task outcome has unsupported source status")
        task_id = str(item.get("planned_task_id") or "")
        if task_id in outcome_by_task:
            raise MissionValidationError("duplicate Stage-3.6.1 outcome for active Plan task")
        outcome_by_task[task_id] = item

    latest_running_by_task: Dict[str, Mapping[str, Any]] = {}
    for item in running_projections:
        if item.get("plan_version_record_id") != active_plan.get("plan_version_record_id") or int(item.get("plan_version", -1)) != int(active_plan.get("plan_version", -2)):
            continue
        task_id = str(item.get("planned_task_id") or "")
        previous = latest_running_by_task.get(task_id)
        if previous is None or int(item.get("heartbeat_sequence", 0)) >= int(previous.get("heartbeat_sequence", 0)):
            latest_running_by_task[task_id] = item

    completed_keys = {
        str(item["task_key"])
        for item in completion_by_task.values()
        if item.get("completion_status") == TASK_COMPLETION_STATUS and item.get("task_completion_committed") is True
    }
    status_map = {
        "VERIFIED_FAILED": "FAILED",
        "VERIFIED_CANCELLED": "CANCELLED",
        "VERIFIED_TIMED_OUT": "TIMED_OUT",
    }
    task_items: list[Dict[str, Any]] = []
    counts = {name: 0 for name in MISSION_OUTCOME_TASK_CLASSIFICATIONS}
    for step in steps:
        task_id = str(step["planned_task_id"])
        task_key = str(step["task_key"])
        dependencies = list(step.get("dependency_task_keys") or [])
        unknown = [key for key in dependencies if key not in by_key]
        if unknown:
            raise MissionValidationError("active Plan task references unknown dependency: " + ", ".join(unknown))
        unmet = [key for key in dependencies if key not in completed_keys]
        completion = completion_by_task.get(task_id)
        outcome = outcome_by_task.get(task_id)
        running = latest_running_by_task.get(task_id)
        source_kind = "ACTIVE_PLAN"
        source_id = None
        source_sha256 = None
        reason_code = "NO_TERMINAL_OR_RUNNING_OUTCOME"
        if completion is not None:
            classification = "VERIFIED_COMPLETE"
            source_kind = "STAGE3_6_4_TASK_COMPLETION"
            source_id = completion["task_completion_id"]
            source_sha256 = completion["canonical_sha256"]
            reason_code = "CANONICAL_TASK_COMPLETION_COMMITTED"
        elif outcome is not None and outcome["source_task_outcome_status"] in status_map:
            classification = status_map[outcome["source_task_outcome_status"]]
            source_kind = "STAGE3_6_1_TASK_OUTCOME"
            source_id = outcome["task_outcome_id"]
            source_sha256 = outcome["canonical_sha256"]
            reason_code = outcome["source_task_outcome_status"]
        elif outcome is not None and outcome["source_task_outcome_status"] == "VERIFIED_COMPLETED":
            classification = "BLOCKED"
            source_kind = "STAGE3_6_1_TASK_OUTCOME"
            source_id = outcome["task_outcome_id"]
            source_sha256 = outcome["canonical_sha256"]
            reason_code = "VERIFIED_SUCCESS_NOT_YET_CANONICALLY_COMPLETED"
        elif running is not None:
            classification = "RUNNING"
            source_kind = "STAGE3_5_6_RUNNING_PROJECTION"
            source_id = running["running_projection_id"]
            source_sha256 = running["canonical_sha256"]
            reason_code = "RUNNING_EXECUTION_OBSERVED"
        elif unmet:
            classification = "BLOCKED"
            reason_code = "UNSATISFIED_ACTIVE_PLAN_DEPENDENCIES"
        else:
            classification = "PENDING"
            reason_code = "READY_OR_NOT_STARTED_NO_TERMINAL_OUTCOME"
        counts[classification] += 1
        task_items.append({
            "planned_task_id": task_id,
            "task_key": task_key,
            "step_index": int(step["step_index"]),
            "dependency_task_keys": dependencies,
            "unmet_dependency_task_keys": unmet,
            "classification": classification,
            "classification_reason_code": reason_code,
            "source_kind": source_kind,
            "source_id": source_id,
            "source_sha256": source_sha256,
            "terminal": classification in TERMINAL_MISSION_OUTCOME_TASK_CLASSIFICATIONS,
            "verified_complete": classification == "VERIFIED_COMPLETE",
        })

    terminal_count = sum(counts[k] for k in TERMINAL_MISSION_OUTCOME_TASK_CLASSIFICATIONS)
    all_terminal = terminal_count == len(task_items)
    all_verified_complete = counts["VERIFIED_COMPLETE"] == len(task_items)
    if counts["FAILED"] or counts["CANCELLED"] or counts["TIMED_OUT"]:
        summary = "TERMINAL_NON_SUCCESS_PRESENT"
    elif all_verified_complete:
        summary = "ALL_TASKS_VERIFIED_COMPLETE"
    elif counts["RUNNING"]:
        summary = "IN_PROGRESS"
    else:
        summary = "INCOMPLETE"
    source_snapshot_sha256 = sha256_hex({
        "hash_domain": MISSION_OUTCOME_SOURCE_SNAPSHOT_HASH_DOMAIN,
        "plan_version_record_id": active_plan["plan_version_record_id"],
        "plan_version": int(active_plan["plan_version"]),
        "tasks": task_items,
    })
    return {
        "aggregation_status": MISSION_OUTCOME_AGGREGATION_STATUS,
        "mission_execution_outcome_summary": summary,
        "task_count": len(task_items),
        "terminal_task_count": terminal_count,
        "verified_complete_count": counts["VERIFIED_COMPLETE"],
        "failed_count": counts["FAILED"],
        "cancelled_count": counts["CANCELLED"],
        "timed_out_count": counts["TIMED_OUT"],
        "running_count": counts["RUNNING"],
        "blocked_count": counts["BLOCKED"],
        "pending_count": counts["PENDING"],
        "all_tasks_terminal": all_terminal,
        "all_tasks_verified_complete": all_verified_complete,
        "terminal_non_success_present": bool(counts["FAILED"] or counts["CANCELLED"] or counts["TIMED_OUT"]),
        "task_outcomes": task_items,
        "source_snapshot_sha256": source_snapshot_sha256,
    }


def build_mission_outcome_aggregation_contract(
    *,
    aggregation_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    task_outcomes: Sequence[Mapping[str, Any]],
    task_completions: Sequence[Mapping[str, Any]],
    running_projections: Sequence[Mapping[str, Any]],
    aggregated_at: str,
) -> Dict[str, Any]:
    aggregation = derive_mission_outcome_aggregation(
        active_plan=active_plan,
        task_outcomes=task_outcomes,
        task_completions=task_completions,
        running_projections=running_projections,
    )
    core = {
        "schema_version": MISSION_OUTCOME_AGGREGATION_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": MISSION_OUTCOME_AGGREGATION_STAGE_SCHEMA_VERSION,
        "identity": {
            "aggregation_id": aggregation_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "source_snapshot_sha256": aggregation["source_snapshot_sha256"],
        },
        "mission_outcome_aggregation": aggregation,
        "authority_boundary": {
            "authority": MISSION_OUTCOME_AGGREGATION_AUTHORITY,
            "mode": MISSION_OUTCOME_AGGREGATION_MODE,
            "active_plan_outcome_aggregation_performed": True,
            "task_outcome_mutation_performed": False,
            "task_completion_mutation_performed": False,
            "success_criteria_evaluation_performed": False,
            "mission_completion_readiness_decision_performed": False,
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
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "aggregated_by": request["aggregated_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "aggregated_at": aggregated_at,
        },
    }
    digest = sha256_hex({"hash_domain": MISSION_OUTCOME_AGGREGATION_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_mission_outcome_aggregation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        agg = contract["mission_outcome_aggregation"]
        boundary = contract["authority_boundary"]
        items = list(agg.get("task_outcomes") or [])
        counts = {name: sum(1 for x in items if x.get("classification") == name) for name in MISSION_OUTCOME_TASK_CLASSIFICATIONS}
        terminal_count = sum(counts[k] for k in TERMINAL_MISSION_OUTCOME_TASK_CLASSIFICATIONS)
        return (
            contract.get("schema_version") == MISSION_OUTCOME_AGGREGATION_CONTRACT_SCHEMA_VERSION
            and contract.get("stage_schema_version") == MISSION_OUTCOME_AGGREGATION_STAGE_SCHEMA_VERSION
            and str(identity.get("aggregation_id") or "").startswith(MISSION_OUTCOME_AGGREGATION_ID_PREFIX)
            and bool(identity.get("mission_id"))
            and str(identity.get("plan_version_record_id") or "").startswith("pver-")
            and int(identity.get("plan_version")) >= 1
            and source.get("source_state") in MISSION_OUTCOME_ALLOWED_MISSION_STATES
            and int(source.get("source_state_version")) >= 1
            and all(_SHA_RE.match(str(source.get(k) or "")) is not None for k in (
                "source_version_sha256", "active_plan_sha256", "source_snapshot_sha256"
            ))
            and agg.get("aggregation_status") == MISSION_OUTCOME_AGGREGATION_STATUS
            and int(agg.get("task_count")) == len(items)
            and int(agg.get("terminal_task_count")) == terminal_count
            and int(agg.get("verified_complete_count")) == counts["VERIFIED_COMPLETE"]
            and int(agg.get("failed_count")) == counts["FAILED"]
            and int(agg.get("cancelled_count")) == counts["CANCELLED"]
            and int(agg.get("timed_out_count")) == counts["TIMED_OUT"]
            and int(agg.get("running_count")) == counts["RUNNING"]
            and int(agg.get("blocked_count")) == counts["BLOCKED"]
            and int(agg.get("pending_count")) == counts["PENDING"]
            and bool(agg.get("all_tasks_terminal")) == (terminal_count == len(items))
            and bool(agg.get("all_tasks_verified_complete")) == (counts["VERIFIED_COMPLETE"] == len(items))
            and source.get("source_snapshot_sha256") == agg.get("source_snapshot_sha256")
            and boundary.get("authority") == MISSION_OUTCOME_AGGREGATION_AUTHORITY
            and boundary.get("mode") == MISSION_OUTCOME_AGGREGATION_MODE
            and boundary.get("active_plan_outcome_aggregation_performed") is True
            and boundary.get("task_outcome_mutation_performed") is False
            and boundary.get("task_completion_mutation_performed") is False
            and boundary.get("success_criteria_evaluation_performed") is False
            and boundary.get("mission_completion_readiness_decision_performed") is False
            and boundary.get("task_state_transition_performed") is False
            and boundary.get("dependency_release_performed") is False
            and boundary.get("readiness_recalculation_performed") is False
            and boundary.get("plan_progression_performed") is False
            and boundary.get("mission_success_completion_authority_exercised") is False
            and boundary.get("governance_query_performed") is False
            and boundary.get("runtime_query_performed") is False
            and boundary.get("runtime_control_io_performed") is False
            and boundary.get("dispatch_redelivery_performed") is False
            and boundary.get("new_execution_attempt_created") is False
            and boundary.get("new_target_action_dispatch_performed") is False
            and boundary.get("external_network_io_performed") is False
            and boundary.get("target_actuation") is False
            and boundary.get("mission_state_transition_performed") is False
            and contract.get("canonical_sha256") == sha256_hex({"hash_domain": MISSION_OUTCOME_AGGREGATION_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_mission_outcome_aggregation_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": MISSION_OUTCOME_AGGREGATION_STAGE_SCHEMA_VERSION,
        "schema_version": MISSION_OUTCOME_AGGREGATION_CONTRACT_SCHEMA_VERSION,
        "identity_prefix": MISSION_OUTCOME_AGGREGATION_ID_PREFIX,
        "mode": MISSION_OUTCOME_AGGREGATION_MODE,
        "authority": MISSION_OUTCOME_AGGREGATION_AUTHORITY,
        "aggregation_status": MISSION_OUTCOME_AGGREGATION_STATUS,
        "allowed_mission_states": sorted(MISSION_OUTCOME_ALLOWED_MISSION_STATES),
        "task_classifications": list(MISSION_OUTCOME_TASK_CLASSIFICATIONS),
        "requires_active_stage337_plan_version": True,
        "consumes_stage361_task_outcomes": True,
        "consumes_stage364_task_completions": True,
        "observes_stage356_running_projections": True,
        "active_plan_task_set_is_authoritative": True,
        "aggregation_is_deterministic_local_projection": True,
        "success_criteria_evaluation_performed": False,
        "mission_completion_readiness_decision_performed": False,
        "dependency_release_performed": False,
        "readiness_recalculation_performed": False,
        "plan_progression_performed": False,
        "mission_success_completion_authority_exercised": False,
        "governance_query_performed": False,
        "runtime_query_performed": False,
        "runtime_control_io_performed": False,
        "external_network_io_performed": False,
        "target_actuation": False,
        "mission_state_transition_performed": False,
        "next_stage": "3.6.6",
    }
