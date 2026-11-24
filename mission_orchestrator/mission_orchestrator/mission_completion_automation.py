"""Deterministic, replay-safe driver for the Mission completion chain.

Given an active Plan whose tasks are all terminal and VERIFIED_COMPLETE, this
module drives the canonical Stage-3.6 finalization through the authoritative
service API, ending in RUNNING -> CLEANING_UP -> COMPLETED:

    aggregate_mission_outcome
      -> evaluate_mission_success_criteria
      -> evaluate_completion_readiness
      -> declare_verified_completion   (CLEANING_UP then COMPLETED)

It mints no Governance authority and performs no target I/O. Every call is
idempotent on a deterministic key derived from the mission and active Plan, so a
replay after a crash resumes rather than duplicating. It never forces completion:
when readiness is BLOCKED it returns the blockers and stops, fail-closed.

NOTE (scope boundary): reaching an all-VERIFIED_COMPLETE Plan first requires the
per-task lifecycle (Stage 3.4 routing/delegation -> Stage 3.5 dispatch/execution/
result/propagation/checkpoint -> Stage 3.6 outcome/eligibility/binding/completion).
That per-task driver is built separately; this module is the final mission-level
capstone and the payload-builder contract both stages share.
"""
from __future__ import annotations

import hashlib
import logging

LOGGER = logging.getLogger(__name__)


def _key(mission_id: str, active_plan_sha256: str, stage: str) -> str:
    """A deterministic, replay-stable idempotency key per mission + active Plan."""
    seed = hashlib.sha256((mission_id + "\0" + active_plan_sha256).encode()).hexdigest()[:40]
    return "auto-complete-" + seed + "-" + stage


def _base(service, mission_id: str, active: dict) -> dict:
    """Common optimistic-concurrency anchors every finalization call requires."""
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
    }


def aggregation_request(service, mission_id: str, active: dict) -> dict:
    key = _key(mission_id, active["canonical_sha256"], "agg")
    return {**_base(service, mission_id, active), "idempotency_key": key,
            "aggregated_by": "mission-auto-completion",
            "reason": "Aggregate active-Plan task outcomes for autonomous completion review",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def evaluation_request(service, mission_id: str, active: dict, aggregation: dict) -> dict:
    key = _key(mission_id, active["canonical_sha256"], "eval")
    return {**_base(service, mission_id, active), "idempotency_key": key,
            "expected_aggregation_id": aggregation["aggregation_id"],
            "expected_aggregation_sha256": aggregation["canonical_sha256"],
            "evaluated_by": "mission-auto-completion",
            "reason": "Evaluate immutable Mission success criteria against aggregated outcomes",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def readiness_request(service, mission_id: str, active: dict, evaluation: dict) -> dict:
    key = _key(mission_id, active["canonical_sha256"], "ready")
    return {**_base(service, mission_id, active), "idempotency_key": key,
            "expected_evaluation_id": evaluation["evaluation_id"],
            "expected_evaluation_sha256": evaluation["canonical_sha256"],
            "decided_by": "mission-auto-completion",
            "reason": "Derive fail-closed completion readiness and blockers",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def verified_completion_request(service, mission_id: str, active: dict, readiness: dict) -> dict:
    key = _key(mission_id, active["canonical_sha256"], "verified")
    return {**_base(service, mission_id, active), "idempotency_key": key,
            "expected_readiness_id": readiness["readiness_id"],
            "expected_readiness_sha256": readiness["canonical_sha256"],
            "declared_by": "mission-auto-completion",
            "reason": "Declare verified Mission completion and hand off through canonical lifecycle commands",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def finalize_mission(service, mission_id: str) -> dict:
    """Drive the Stage-3.6 finalization chain for one mission.

    Returns a status dict. Only declares completion when readiness is READY;
    otherwise returns the deterministic blockers and leaves the mission RUNNING.
    """
    active = service.get_active_plan_version(mission_id)

    aggregation = service.aggregate_mission_outcome(mission_id, aggregation_request(service, mission_id, active))
    if not (aggregation.get("all_tasks_terminal") and aggregation.get("all_tasks_verified_complete")
            and not aggregation.get("terminal_non_success_present")):
        return {"status": "NOT_READY", "stage": "aggregation",
                "all_tasks_terminal": aggregation.get("all_tasks_terminal"),
                "all_tasks_verified_complete": aggregation.get("all_tasks_verified_complete"),
                "terminal_non_success_present": aggregation.get("terminal_non_success_present")}

    evaluation = service.evaluate_mission_success_criteria(
        mission_id, evaluation_request(service, mission_id, active, aggregation))
    if evaluation.get("overall_result") != "SUCCESS_CRITERIA_SATISFIED":
        return {"status": "NOT_READY", "stage": "evaluation", "overall_result": evaluation.get("overall_result")}

    readiness = service.evaluate_completion_readiness(
        mission_id, readiness_request(service, mission_id, active, evaluation))
    if readiness.get("readiness_result") != "READY":
        return {"status": "BLOCKED", "stage": "readiness",
                "blockers": readiness.get("blockers", []), "blocker_count": readiness.get("blocker_count")}

    completion = service.declare_verified_completion(
        mission_id, verified_completion_request(service, mission_id, active, readiness))
    final_state = (completion.get("final_mission_state") or {}).get("state")
    return {"status": "COMPLETED" if final_state == "COMPLETED" else "DECLARED",
            "final_state": final_state, "completion": completion}


# ---------------------------------------------------------------------------
# Per-task Stage-3.6 completion chain: outcome -> eligibility -> evidence
# binding -> dependency-aware completion. Each builder is pure given the active
# Plan and the immutable Stage-3.5 execution evidence for one task.
#
# COUPLING BOUNDARY: `complete_task` consumes a dict of Stage-3.5 execution
# evidence refs (attempt, result, propagation, checkpoint). Producing those is
# the Stage-3.4 routing/delegation + Stage-3.5 dispatch/execution driver, which
# for recon/validation tasks runs through Governance (Stage 6) and the runtime.
# That driver is built on top of this contract; this layer is independent of how
# the evidence was produced and only accepts immutable, hash-bound references.
# ---------------------------------------------------------------------------

def _task_key(anchor_id: str, stage: str) -> str:
    return "auto-task-" + hashlib.sha256(anchor_id.encode()).hexdigest()[:40] + "-" + stage


def outcome_request(service, mission_id: str, active: dict, attempt: dict, result: dict,
                    propagation: dict, checkpoint: dict) -> dict:
    return {**_base(service, mission_id, active),
            "idempotency_key": _task_key(attempt["execution_attempt_id"], "outcome"),
            "expected_execution_attempt_id": attempt["execution_attempt_id"],
            "expected_execution_attempt_sha256": attempt["canonical_sha256"],
            "expected_result_capture_id": result["result_capture_id"],
            "expected_result_capture_sha256": result["canonical_sha256"],
            "expected_outcome_propagation_id": propagation["outcome_propagation_id"],
            "expected_outcome_propagation_sha256": propagation["canonical_sha256"],
            "expected_execution_recovery_checkpoint_id": checkpoint["checkpoint_id"],
            "expected_execution_recovery_checkpoint_sha256": checkpoint["canonical_sha256"],
            "created_by": "mission-auto-completion",
            "reason": "Materialize immutable canonical task outcome from durable Stage-3.5 evidence",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def eligibility_request(service, mission_id: str, active: dict, task_outcome: dict) -> dict:
    return {**_base(service, mission_id, active),
            "idempotency_key": _task_key(task_outcome["task_outcome_id"], "eligibility"),
            "expected_task_outcome_id": task_outcome["task_outcome_id"],
            "expected_task_outcome_sha256": task_outcome["canonical_sha256"],
            "evaluated_by": "mission-auto-completion",
            "reason": "Derive terminality and completion eligibility from the immutable task outcome",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def binding_request(service, mission_id: str, active: dict, task_outcome: dict,
                    gate: dict, result: dict) -> dict:
    return {**_base(service, mission_id, active),
            "idempotency_key": _task_key(task_outcome["task_outcome_id"], "binding"),
            "expected_task_outcome_id": task_outcome["task_outcome_id"],
            "expected_task_outcome_sha256": task_outcome["canonical_sha256"],
            "expected_eligibility_gate_id": gate["eligibility_gate_id"],
            "expected_eligibility_gate_sha256": gate["canonical_sha256"],
            "expected_result_capture_id": result["result_capture_id"],
            "expected_result_capture_sha256": result["canonical_sha256"],
            "verified_by": "mission-auto-completion",
            "reason": "Verify local immutable evidence/artifact reference and hash bindings",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def completion_request(service, mission_id: str, active: dict, evidence_binding: dict) -> dict:
    return {**_base(service, mission_id, active),
            "idempotency_key": _task_key(evidence_binding["verification_id"], "completion"),
            "expected_evidence_binding_verification_id": evidence_binding["verification_id"],
            "expected_evidence_binding_verification_sha256": evidence_binding["canonical_sha256"],
            "completed_by": "mission-auto-completion",
            "reason": "Accept verified terminal outcome only when active-Plan dependencies are complete",
            "metadata": {"automation": "MISSION_AUTONOMOUS_COMPLETION_V1"}}


def complete_task(service, mission_id: str, active: dict, execution: dict) -> dict:
    """Drive one task's Stage-3.6 chain to a dependency-aware completion commit.

    `execution` holds the immutable Stage-3.5 evidence refs for the task:
    {"attempt": ..., "result": ..., "propagation": ..., "checkpoint": ...}.
    Returns the four resulting contracts. Idempotent per task on the evidence ids.
    """
    outcome = service.create_task_outcome(mission_id, outcome_request(
        service, mission_id, active, execution["attempt"], execution["result"],
        execution["propagation"], execution["checkpoint"]))
    gate = service.evaluate_task_terminality_completion_eligibility(
        mission_id, eligibility_request(service, mission_id, active, outcome))
    evidence_binding = service.verify_task_evidence_binding(
        mission_id, binding_request(service, mission_id, active, outcome, gate, execution["result"]))
    completion = service.commit_dependency_aware_task_completion(
        mission_id, completion_request(service, mission_id, active, evidence_binding))
    return {"task_outcome": outcome, "eligibility_gate": gate,
            "evidence_binding": evidence_binding, "completion": completion}


def sweep(service) -> None:
    """Attempt finalization for every RUNNING mission whose Plan is fully complete.

    Fail-closed and idempotent: missions that are not yet complete simply return
    NOT_READY/BLOCKED and are retried on the next cadence without side effects.
    """
    offset = 0
    while True:
        page = service.list_missions(state="RUNNING", limit=100, offset=offset)
        for mission in page["missions"]:
            try:
                finalize_mission(service, mission["mission_id"])
            except Exception:
                LOGGER.exception("Autonomous mission completion deferred for %s", mission["mission_id"])
        offset += len(page["missions"])
        if not page["missions"] or offset >= page["mission_count"]:
            break
