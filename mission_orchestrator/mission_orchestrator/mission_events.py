from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping, Optional

MISSION_EVENT_SCHEMA_VERSION = "apts-mission-event-v1"
MISSION_LINEAGE_SCHEMA_VERSION = "apts-mission-lineage-v1"
MISSION_EVENT_HASH_DOMAIN = "APTS_MISSION_EVENT_V1"
MISSION_EVENT_MODE = "DURABLE_APPEND_ONLY_HASH_CHAIN"
MISSION_LINEAGE_MODE = "MISSION_ROOT_TRACE_BUSINESS_CAUSATION_LOCAL_PARENT_CHAIN"
MISSION_EVENT_SOURCE_COMPONENT = "APTS-MO01"

CANONICAL_EVENT_TYPES = (
    "MISSION_REGISTERED",
    "MISSION_PIP_BOUND",
    "MISSION_STATE_TRANSITIONED",
    "MISSION_SCOPE_CONTRACT_COMMITTED",
    "MISSION_GOVERNANCE_BOUND",
    "MISSION_AUTHORIZATION_BOUND",
    "MISSION_ROUTING_TASK_CREATED",
    "MISSION_ROUTING_TASK_DISPATCHED",
    "MISSION_COMMAND_COMPLETED",
    "MISSION_PLAN_CONTRACT_REGISTERED",
    "MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED",
    "MISSION_TASK_DECOMPOSITION_REGISTERED",
    "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED",
    "MISSION_PLANNER_INVOKED",
    "MISSION_PLAN_GENERATED",
    "MISSION_PLAN_VALIDATED_FEASIBLE",
    "MISSION_PLAN_VERSION_ACTIVATED",
    "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED",
    "MISSION_TASK_READINESS_PROJECTED",
    "MISSION_TASK_ROUTING_CANDIDATES_RESOLVED",
    "MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED",
    "MISSION_TASK_ROUTE_DECISION_RECORDED",
    "MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED",
    "MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED",
    "MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED",
    "MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED",
    "MISSION_ROUTING_DELEGATION_RECOVERY_CHECKPOINTED",
    "MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED",
    "MISSION_DISPATCH_ELIGIBILITY_PRECONDITIONS_SATISFIED",
    "MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED",
    "MISSION_EXECUTION_ATTEMPT_COMMITTED",
    "MISSION_EXECUTION_DISPATCH_DELIVERED_ACKNOWLEDGED",
    "MISSION_EXECUTION_RUNNING_HEARTBEAT_PROJECTED",
    "MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURED",
    "MISSION_EXECUTION_TERMINATION_CONTROL_ACKNOWLEDGED",
    "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED",
    "MISSION_EXECUTION_RECOVERY_CHECKPOINTED",
    "MISSION_TASK_OUTCOME_MATERIALIZED",
    "MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED",
    "MISSION_TASK_EVIDENCE_BINDING_VERIFIED",
    "MISSION_TASK_COMPLETION_COMMITTED",
    "MISSION_OUTCOME_AGGREGATED",
    "MISSION_SUCCESS_CRITERIA_EVALUATED",
    "MISSION_COMPLETION_READINESS_EVALUATED",
    "MISSION_VERIFIED_COMPLETION_DECLARED",
    "MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED",
    "MISSION_OUTCOME_RECOVERY_CHECKPOINTED",
    "MISSION_ADAPTATION_REPLAN_DETECTED",
    "MISSION_ADAPTATION_TRIGGER_CLASSIFIED",
    "MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED",
    "MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND",
    "MISSION_REPLAN_CANDIDATE_GENERATED",
    "MISSION_REPLAN_DECISION_RECORDED",
    "MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED",
    "MISSION_REPLAN_HANDOFF_READY",
    "MISSION_REPLAN_RECOVERY_CHECKPOINTED",
    "MISSION_PLANNING_RECOVERY_CHECKPOINTED",
    "MISSION_LIFECYCLE_EVENT_RECEIVED",
    "MISSION_LIFECYCLE_EVENT_APPLIED",
    "MISSION_LIFECYCLE_EVENT_REJECTED",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_event_id() -> str:
    return f"mevent-{uuid.uuid4()}"


def event_hash_core(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable event material covered by the event digest.

    ``recorded_at`` and database sequence numbers are deliberately excluded.  The
    event digest therefore remains portable across repository reconstruction while
    ``previous_event_sha256`` binds each record to the preceding Mission event.
    """

    return {
        "schema_version": event["schema_version"],
        "event_id": event["event_id"],
        "mission_id": event["mission_id"],
        "trace_id": event["trace_id"],
        "correlation_id": event["correlation_id"],
        "causation_id": event.get("causation_id"),
        "parent_event_id": event.get("parent_event_id"),
        "source_component": event["source_component"],
        "event_type": event["event_type"],
        "state_version": event.get("state_version"),
        "plan_version": event.get("plan_version"),
        "policy_version": event.get("policy_version"),
        "payload": dict(event.get("payload") or {}),
        "previous_event_sha256": event.get("previous_event_sha256"),
        "occurred_at": event["occurred_at"],
    }


def compute_event_sha256(event: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": MISSION_EVENT_HASH_DOMAIN, "event": event_hash_core(event)})


def verify_event(event: Mapping[str, Any]) -> bool:
    try:
        return (
            event.get("schema_version") == MISSION_EVENT_SCHEMA_VERSION
            and isinstance(event.get("event_id"), str)
            and isinstance(event.get("mission_id"), str)
            and isinstance(event.get("trace_id"), str)
            and isinstance(event.get("correlation_id"), str)
            and event.get("source_component")
            and event.get("event_type") in CANONICAL_EVENT_TYPES
            and event.get("canonical_sha256") == compute_event_sha256(event)
        )
    except Exception:
        return False


def build_event_record(
    *,
    event_id: str,
    mission_id: str,
    correlation_id: str,
    event_type: str,
    payload: Optional[Mapping[str, Any]],
    occurred_at: str,
    previous_event: Optional[Mapping[str, Any]] = None,
    source_component: str = MISSION_EVENT_SOURCE_COMPONENT,
    state_version: Optional[int] = None,
    plan_version: Optional[Any] = None,
    policy_version: Optional[Any] = None,
    parent_event_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> dict[str, Any]:
    normalized_type = str(event_type or "").strip().upper()
    if normalized_type not in CANONICAL_EVENT_TYPES:
        raise ValueError(f"unsupported canonical mission event_type={normalized_type!r}")
    if not event_id or not mission_id or not correlation_id or not occurred_at:
        raise ValueError("event_id, mission_id, correlation_id, and occurred_at are required")

    previous = dict(previous_event or {})
    trace_id = str(previous.get("trace_id") or event_id)
    previous_event_id = previous.get("event_id")
    previous_sha = previous.get("canonical_sha256")
    if parent_event_id is None and previous_event_id:
        parent_event_id = str(previous_event_id)

    record: dict[str, Any] = {
        "schema_version": MISSION_EVENT_SCHEMA_VERSION,
        "event_id": str(event_id),
        "mission_id": str(mission_id),
        "trace_id": trace_id,
        "correlation_id": str(correlation_id),
        "causation_id": None if causation_id in (None, "") else str(causation_id),
        "parent_event_id": None if parent_event_id in (None, "") else str(parent_event_id),
        "source_component": str(source_component or MISSION_EVENT_SOURCE_COMPONENT),
        "event_type": normalized_type,
        "state_version": None if state_version is None else int(state_version),
        "plan_version": None if plan_version is None else str(plan_version),
        "policy_version": None if policy_version is None else str(policy_version),
        "payload": dict(payload or {}),
        "previous_event_sha256": None if previous_sha in (None, "") else str(previous_sha),
        "occurred_at": str(occurred_at),
    }
    record["canonical_sha256"] = compute_event_sha256(record)
    return record


def verify_event_chain(events: list[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    """Verify hash continuity, trace continuity, and local causation ordering."""

    errors: list[str] = []
    previous: Optional[Mapping[str, Any]] = None
    seen: set[str] = set()
    root_trace: Optional[str] = None

    for index, event in enumerate(events):
        event_id = str(event.get("event_id") or "")
        if not verify_event(event):
            errors.append(f"event[{index}] hash/schema verification failed")
        if event_id in seen:
            errors.append(f"duplicate event_id={event_id}")
        seen.add(event_id)

        if index == 0:
            root_trace = event_id
            if event.get("trace_id") != event_id:
                errors.append("root event trace_id must equal root event_id")
            if event.get("previous_event_sha256") not in (None, ""):
                errors.append("root event previous_event_sha256 must be null")
        else:
            assert previous is not None
            if event.get("trace_id") != root_trace:
                errors.append(f"event_id={event_id} trace_id diverges from root")
            if event.get("parent_event_id") != previous.get("event_id"):
                errors.append(f"event_id={event_id} parent_event_id is not the immediate local predecessor")
            if event.get("previous_event_sha256") != previous.get("canonical_sha256"):
                errors.append(f"event_id={event_id} previous_event_sha256 mismatch")

        previous = event

    return not errors, errors
