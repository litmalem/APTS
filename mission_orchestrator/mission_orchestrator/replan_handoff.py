from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError
from .replan_commit import verify_replan_commit_contract

REPLAN_HANDOFF_STAGE_SCHEMA_VERSION = "apts-atomic-replan-commit-supersession-handoff-v1"
REPLAN_HANDOFF_CONTRACT_SCHEMA_VERSION = "apts-replan-supersession-handoff-contract-v1"
REPLAN_HANDOFF_HASH_DOMAIN = "MISSION_REPLAN_SUPERSESSION_HANDOFF_V1"
REPLAN_HANDOFF_REQUEST_HASH_DOMAIN = "MISSION_REPLAN_SUPERSESSION_HANDOFF_REQUEST_V1"
REPLAN_HANDOFF_ID_PREFIX = "rphof-"
REPLAN_HANDOFF_EVENT_TYPE = "MISSION_REPLAN_HANDOFF_READY"
REPLAN_HANDOFF_STATUS = "HANDOFF_READY"
REPLAN_HANDOFF_AUTHORITY = "MISSION_ORCHESTRATOR_ATOMIC_REPLAN_SUPERSESSION_HANDOFF"
REPLAN_HANDOFF_MODE = (
    "VERIFY_STAGE377_ATOMIC_COMMIT_AND_ACTIVE_HEAD_THEN_DERIVE_IN_FLIGHT_DISPOSITIONS_"
    "AND_DECLARE_SUCCESSOR_HANDOFF_READY_NO_PLAN_MUTATION_NO_MISSION_TRANSITION_"
    "NO_CANCELLATION_IO_NO_ROUTING_NO_DISPATCH_NO_ACTUATION"
)
REPLAN_HANDOFF_NEXT_CONTROL = "STAGE3_4_ROUTING_THEN_STAGE3_5_DISPATCH"
REPLAN_TASK_DISPOSITIONS = ("KEEP", "DRAIN", "CANCEL", "SUPERSEDE", "REPLACE")

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_replan_commit_id",
    "expected_replan_commit_sha256",
    "expected_predecessor_plan_version_record_id",
    "expected_predecessor_plan_version",
    "expected_predecessor_plan_sha256",
    "expected_successor_plan_version_record_id",
    "expected_successor_plan_version",
    "expected_successor_plan_sha256",
    "expected_source_state_version",
    "handed_off_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_replan_handoff_id() -> str:
    return f"{REPLAN_HANDOFF_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_replan_handoff_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("atomic replan supersession handoff request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported atomic replan handoff field(s): " + ", ".join(unknown)
            + "; Stage 3.7.8 derives task dispositions from durable state and never accepts caller-supplied "
              "task disposition, cancellation, routing, dispatch, execution, or actuation instructions"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_replan_commit_id": _string(payload, "expected_replan_commit_id"),
        "expected_predecessor_plan_version_record_id": _string(payload, "expected_predecessor_plan_version_record_id"),
        "expected_successor_plan_version_record_id": _string(payload, "expected_successor_plan_version_record_id"),
        "handed_off_by": _string(payload, "handed_off_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_replan_commit_id"].startswith("rpcom-"):
        raise MissionValidationError("expected_replan_commit_id must be a canonical rpcom-* identifier")
    for key in ("expected_predecessor_plan_version_record_id", "expected_successor_plan_version_record_id"):
        if not values[key].startswith("pver-"):
            raise MissionValidationError(f"{key} must be a canonical pver-* identifier")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason in (None, ""):
        reason = None
    elif not isinstance(reason, str) or not reason.strip():
        raise MissionValidationError("reason must be a non-empty string when provided")
    else:
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    return {
        **values,
        "expected_replan_commit_sha256": _sha(payload, "expected_replan_commit_sha256"),
        "expected_predecessor_plan_version": _positive_int(payload, "expected_predecessor_plan_version"),
        "expected_predecessor_plan_sha256": _sha(payload, "expected_predecessor_plan_sha256"),
        "expected_successor_plan_version": _positive_int(payload, "expected_successor_plan_version"),
        "expected_successor_plan_sha256": _sha(payload, "expected_successor_plan_sha256"),
        "expected_source_state_version": _positive_int(payload, "expected_source_state_version"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def replan_handoff_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": REPLAN_HANDOFF_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def derive_task_dispositions(
    *, snapshot_contract: Mapping[str, Any], candidate_contract: Mapping[str, Any],
    execution_attempts: Sequence[Mapping[str, Any]], execution_deliveries: Sequence[Mapping[str, Any]],
    execution_running_projections: Sequence[Mapping[str, Any]], execution_result_captures: Sequence[Mapping[str, Any]],
    execution_termination_controls: Sequence[Mapping[str, Any]], predecessor_plan_version_record_id: str,
) -> list[Dict[str, Any]]:
    ctx = snapshot_contract["task_dependency_outcome_context"]
    tasks = list(ctx.get("tasks") or [])
    completed = {x.get("planned_task_id") for x in (ctx.get("task_completions") or []) if x.get("planned_task_id")}
    cand = candidate_contract["candidate_successor_plan"]
    retained = {x["source_planned_task_id"] for x in (cand.get("candidate_tasks") or [])}

    attempts = [x for x in execution_attempts if x.get("plan_version_record_id") == predecessor_plan_version_record_id]
    deliveries_by_attempt = {x["execution_attempt_id"]: x for x in execution_deliveries if x.get("execution_attempt_id")}
    results_by_attempt = {x["execution_attempt_id"]: x for x in execution_result_captures if x.get("execution_attempt_id")}
    terminations_by_attempt = {x["execution_attempt_id"]: x for x in execution_termination_controls if x.get("execution_attempt_id")}
    running_by_attempt: dict[str, Mapping[str, Any]] = {}
    for x in execution_running_projections:
        aid = x.get("execution_attempt_id")
        if not aid:
            continue
        prev = running_by_attempt.get(aid)
        if prev is None or int(x.get("heartbeat_sequence") or 0) >= int(prev.get("heartbeat_sequence") or 0):
            running_by_attempt[aid] = x

    attempts_by_task: dict[str, list[Mapping[str, Any]]] = {}
    for attempt in attempts:
        attempts_by_task.setdefault(str(attempt.get("planned_task_id")), []).append(attempt)

    output: list[Dict[str, Any]] = []
    for task in sorted(tasks, key=lambda x: int(x.get("task_index") or 0)):
        tid = task["planned_task_id"]
        task_attempts = attempts_by_task.get(tid, [])
        active_attempt_ids: list[str] = []
        delivered = False
        running = False
        for attempt in task_attempts:
            aid = attempt["execution_attempt_id"]
            if aid in results_by_attempt or aid in terminations_by_attempt:
                continue
            active_attempt_ids.append(aid)
            delivered = delivered or aid in deliveries_by_attempt
            running = running or aid in running_by_attempt

        is_completed = tid in completed
        is_retained = tid in retained
        in_flight = bool(active_attempt_ids)
        if is_completed:
            disposition = "KEEP"
            reason_code = "COMPLETED_TASK_PRESERVED"
        elif is_retained and in_flight:
            disposition = "DRAIN"
            reason_code = "VALID_IN_FLIGHT_TASK_DRAINS_UNDER_SUCCESSOR"
        elif is_retained:
            disposition = "KEEP"
            reason_code = "UNFINISHED_TASK_RETAINED_BY_SUCCESSOR"
        elif in_flight:
            disposition = "CANCEL"
            reason_code = "INVALIDATED_IN_FLIGHT_TASK_REQUIRES_STAGE35_CANCELLATION"
        else:
            disposition = "SUPERSEDE"
            reason_code = "INVALIDATED_NON_RUNNING_TASK_SUPERSEDED"
        output.append({
            "source_planned_task_id": tid,
            "task_key": task["task_key"],
            "source_task_index": int(task["task_index"]),
            "disposition": disposition,
            "reason_code": reason_code,
            "completed_before_replan": bool(is_completed),
            "retained_in_successor": bool(is_retained),
            "in_flight_execution": bool(in_flight),
            "delivered_execution": bool(delivered),
            "running_execution": bool(running),
            "active_execution_attempt_ids": sorted(active_attempt_ids),
            "cancellation_io_performed": False,
            "stage35_termination_control_required": disposition == "CANCEL",
            "new_dispatch_required": disposition == "KEEP" and is_retained and not is_completed and not in_flight,
            "replacement_identity_created": False,
        })
    return output


def build_replan_handoff_contract(
    *, handoff_id: str, mission_id: str, request: Mapping[str, Any], request_sha256: str,
    commit_record: Mapping[str, Any], predecessor_plan: Mapping[str, Any], successor_plan: Mapping[str, Any],
    task_dispositions: Sequence[Mapping[str, Any]], handed_off_at: str,
) -> Dict[str, Any]:
    commit_contract = commit_record["replan_commit_contract"]
    if not verify_replan_commit_contract(commit_contract):
        raise MissionValidationError("Stage-3.7.7 ReplanCommit failed integrity verification")
    counts = {name: 0 for name in REPLAN_TASK_DISPOSITIONS}
    for item in task_dispositions:
        disp = str(item.get("disposition"))
        if disp not in counts:
            raise MissionValidationError(f"unsupported replan task disposition: {disp}")
        counts[disp] += 1
    core = {
        "schema_version": REPLAN_HANDOFF_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": REPLAN_HANDOFF_STAGE_SCHEMA_VERSION,
        "identity": {
            "replan_handoff_id": handoff_id,
            "mission_id": mission_id,
            "adaptation_episode_id": commit_record["adaptation_episode_id"],
            "replan_trigger_id": commit_record["replan_trigger_id"],
            "replan_commit_id": commit_record["replan_commit_id"],
            "replan_validation_id": commit_record["replan_validation_id"],
        },
        "atomic_commit_binding": {
            "replan_commit_sha256": commit_record["canonical_sha256"],
            "commit_status": commit_record["commit_status"],
            "predecessor_plan_version_record_id": predecessor_plan["plan_version_record_id"],
            "predecessor_plan_version": int(predecessor_plan["plan_version"]),
            "predecessor_plan_sha256": predecessor_plan["canonical_sha256"],
            "successor_plan_version_record_id": successor_plan["plan_version_record_id"],
            "successor_plan_version": int(successor_plan["plan_version"]),
            "successor_plan_sha256": successor_plan["canonical_sha256"],
            "active_head_verified_as_successor": True,
            "predecessor_effective_status": "SUPERSEDED",
            "successor_effective_status": "ACTIVE",
            "historical_plan_row_mutated": False,
        },
        "task_handoff": {
            "supported_dispositions": list(REPLAN_TASK_DISPOSITIONS),
            "task_disposition_count": len(task_dispositions),
            "keep_count": counts["KEEP"],
            "drain_count": counts["DRAIN"],
            "cancel_count": counts["CANCEL"],
            "supersede_count": counts["SUPERSEDE"],
            "replace_count": counts["REPLACE"],
            "dispositions": [dict(x) for x in task_dispositions],
            "cancellation_io_performed": False,
            "replacement_materialization_performed": False,
        },
        "successor_handoff": {
            "handoff_status": REPLAN_HANDOFF_STATUS,
            "effective_episode_state": "HANDOFF_READY",
            "next_control": REPLAN_HANDOFF_NEXT_CONTROL,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "execution_attempt_created": False,
        },
        "authority_boundary": {
            "authority": REPLAN_HANDOFF_AUTHORITY,
            "mode": REPLAN_HANDOFF_MODE,
            "stage377_atomic_commit_verified": True,
            "active_plan_head_verified": True,
            "plan_supersession_verified": True,
            "in_flight_dispositions_derived": True,
            "handoff_ready_declared": True,
            "historical_plan_mutation_performed": False,
            "mission_state_transition_performed": False,
            "governance_query_performed": False,
            "cancellation_io_performed": False,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "execution_attempt_created": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "handed_off_by": request["handed_off_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "source_state": commit_record["source_state"],
            "source_state_version": int(commit_record["source_state_version"]),
            "handed_off_at": handed_off_at,
        },
    }
    return {**core, "canonical_sha256": sha256_hex({"hash_domain": REPLAN_HANDOFF_HASH_DOMAIN, "contract": core})}


def verify_replan_handoff_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != REPLAN_HANDOFF_CONTRACT_SCHEMA_VERSION:
            return False
        if contract.get("stage_schema_version") != REPLAN_HANDOFF_STAGE_SCHEMA_VERSION:
            return False
        digest = contract.get("canonical_sha256")
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if digest != sha256_hex({"hash_domain": REPLAN_HANDOFF_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]
        if not str(ident.get("replan_handoff_id", "")).startswith(REPLAN_HANDOFF_ID_PREFIX):
            return False
        if not str(ident.get("replan_commit_id", "")).startswith("rpcom-"):
            return False
        bind = contract["atomic_commit_binding"]
        for key in ("replan_commit_sha256", "predecessor_plan_sha256", "successor_plan_sha256"):
            if not _SHA_RE.match(str(bind.get(key) or "")):
                return False
        if int(bind.get("successor_plan_version", 0)) != int(bind.get("predecessor_plan_version", 0)) + 1:
            return False
        if bind.get("active_head_verified_as_successor") is not True:
            return False
        hand = contract["task_handoff"]
        dispositions = list(hand.get("dispositions") or [])
        if int(hand.get("task_disposition_count", -1)) != len(dispositions):
            return False
        observed = {x: 0 for x in REPLAN_TASK_DISPOSITIONS}
        for item in dispositions:
            disp = item.get("disposition")
            if disp not in observed:
                return False
            observed[disp] += 1
            if item.get("cancellation_io_performed") is not False:
                return False
        if int(hand.get("keep_count", -1)) != observed["KEEP"]: return False
        if int(hand.get("drain_count", -1)) != observed["DRAIN"]: return False
        if int(hand.get("cancel_count", -1)) != observed["CANCEL"]: return False
        if int(hand.get("supersede_count", -1)) != observed["SUPERSEDE"]: return False
        if int(hand.get("replace_count", -1)) != observed["REPLACE"]: return False
        successor = contract["successor_handoff"]
        if successor.get("handoff_status") != REPLAN_HANDOFF_STATUS or successor.get("effective_episode_state") != "HANDOFF_READY":
            return False
        boundary = contract["authority_boundary"]
        if boundary.get("authority") != REPLAN_HANDOFF_AUTHORITY or boundary.get("mode") != REPLAN_HANDOFF_MODE:
            return False
        for key in ("stage377_atomic_commit_verified", "active_plan_head_verified", "plan_supersession_verified", "in_flight_dispositions_derived", "handoff_ready_declared"):
            if boundary.get(key) is not True: return False
        for key in ("historical_plan_mutation_performed", "mission_state_transition_performed", "governance_query_performed", "cancellation_io_performed", "routing_performed", "delegation_performed", "dispatch_performed", "execution_attempt_created", "target_action_dispatch_performed", "target_actuation"):
            if boundary.get(key) is not False: return False
        return True
    except Exception:
        return False


def canonical_replan_handoff_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": REPLAN_HANDOFF_STAGE_SCHEMA_VERSION,
        "contract_schema_version": REPLAN_HANDOFF_CONTRACT_SCHEMA_VERSION,
        "identity_prefix": REPLAN_HANDOFF_ID_PREFIX,
        "event_type": REPLAN_HANDOFF_EVENT_TYPE,
        "handoff_status": REPLAN_HANDOFF_STATUS,
        "authority": REPLAN_HANDOFF_AUTHORITY,
        "mode": REPLAN_HANDOFF_MODE,
        "requires_stage377_committed_successor_plan": True,
        "requires_active_head_exactly_successor": True,
        "requires_predecessor_and_successor_integrity": True,
        "requires_unchanged_mission_state_version": True,
        "supported_task_dispositions": list(REPLAN_TASK_DISPOSITIONS),
        "completed_tasks": "KEEP",
        "valid_in_flight_tasks": "DRAIN",
        "invalidated_in_flight_tasks": "CANCEL_DECLARATION_ONLY_STAGE35_EXECUTES",
        "invalidated_non_running_tasks": "SUPERSEDE",
        "replacement_tasks": "REPLACE_RESERVED_WITH_NEW_IDENTITY",
        "cancellation_io_performed": False,
        "historical_plan_mutation_performed": False,
        "mission_state_transition_performed": False,
        "routing_performed": False,
        "delegation_performed": False,
        "dispatch_performed": False,
        "target_actuation": False,
        "effective_episode_state": "HANDOFF_READY",
        "next_control": REPLAN_HANDOFF_NEXT_CONTROL,
        "idempotent_recovery_supported": True,
        "next_stage": "3.7.9",
    }
