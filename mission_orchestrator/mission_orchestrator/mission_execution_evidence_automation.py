"""Deterministic, replay-safe driver for the Stage-3.5 execution-evidence chain.

Given a RUNNING mission whose active Plan has a governed delegation *delivery*
for one planned task (produced by the Stage-3.4 routing/delegation chain), this
module drives the canonical Stage-3.5 sequence through the authoritative service
API and produces the four immutable evidence references that the Stage-3.6
per-task completion chain (`mission_completion_automation.complete_task`)
consumes:

    create_execution_dispatch_contract        (dispatch)
      -> create_dispatch_eligibility_gate     (gate)
      -> authorize_pre_dispatch_execution     (reval)      [authoritative ALLOW]
      -> commit_execution_attempt             (attempt)
      -> deliver_execution_attempt            (delivery)   [-> runtime intake]
      -> project_running_execution_state      (running)    [observe heartbeat]
      -> capture_execution_result             (result)     [pull runtime evidence]
      -> propagate_execution_outcome          (propagation)
      -> create_execution_recovery_checkpoint (checkpoint)

It mints no Governance authority of its own: the authoritative pre-dispatch
ALLOW is obtained through `authorize_pre_dispatch_execution`, which calls the
service's injected Governance client, and the execution evidence is pulled from
the service's injected runtime client (`service.execution_delivery_client`) --
in production the Stage-6.5 runtime bridge, in tests a fake. This driver never
fabricates evidence and performs no target I/O itself.

Every call is idempotent on a deterministic key derived from the task's
delegation-delivery lineage anchor, so a replay after a crash resumes rather than
duplicating. Result capture is deliberately *not* a task-completion authority:
this layer only materializes evidence (success or terminal failure alike); the
decision to complete a task belongs to the Stage-3.6 chain, which fails closed on
a terminal non-success outcome.

SCOPE BOUNDARY: the mission must already be RUNNING and the task's Stage-3.4
delegation `delivery` row must already exist. Producing that delivery is the
Stage-3.4 routing/delegation driver; reaching COMPLETED from the evidence this
module returns is `mission_completion_automation.complete_task` followed by
`finalize_mission`.
"""
from __future__ import annotations

import hashlib
import logging

LOGGER = logging.getLogger(__name__)

#: Terminal execution state that marks a task eligible for successful completion.
SUCCEEDED = "SUCCEEDED"

_AUTOMATION = {"automation": "MISSION_AUTONOMOUS_EXECUTION_EVIDENCE_V1"}


def _ev_key(lineage_anchor: str, stage: str) -> str:
    """A deterministic, replay-stable idempotency key per task evidence lineage.

    Anchored on the Stage-3.4 delegation delivery receipt, which is unique per
    delegated task, so keys never collide across tasks and always resume on replay.
    """
    seed = hashlib.sha256(lineage_anchor.encode()).hexdigest()[:40]
    return "auto-exec-" + seed + "-" + stage


def _anchors(service, mission_id: str, active: dict) -> dict:
    """Optimistic-concurrency anchors every Stage-3.5 call requires."""
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    return {
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
    }


# ---------------------------------------------------------------------------
# Pure request builders. Each is pure given the live service version anchors,
# the active Plan, and the immutable predecessor evidence rows. They mirror the
# canonical Stage-3.5 acceptance contracts but derive idempotency deterministically
# from the delegation-delivery lineage anchor instead of an ad-hoc run key.
# ---------------------------------------------------------------------------

def dispatch_request(service, mission_id: str, active: dict, delivery: dict) -> dict:
    anchor = delivery["delivery_receipt_id"]
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "dispatch"),
            "expected_delivery_receipt_id": delivery["delivery_receipt_id"],
            "expected_delivery_receipt_sha256": delivery["canonical_sha256"],
            "planned_task_id": delivery["planned_task_id"],
            "created_by": "mission-auto-execution",
            "reason": "Materialize canonical execution dispatch identity for a governed delegated task",
            "metadata": {"stage": "3.5.1", **_AUTOMATION}}


def eligibility_request(service, mission_id: str, active: dict, anchor: str, dispatch: dict) -> dict:
    readiness = service.get_active_task_readiness_projection(mission_id)
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "gate"),
            "expected_execution_dispatch_id": dispatch["execution_dispatch_id"],
            "expected_execution_dispatch_sha256": dispatch["canonical_sha256"],
            "expected_task_readiness_projection_id": readiness["projection_id"],
            "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
            "created_by": "mission-auto-execution",
            "reason": "Evaluate static dispatch eligibility and execution preconditions",
            "metadata": {"stage": "3.5.2", **_AUTOMATION}}


def revalidation_request(service, mission_id: str, active: dict, anchor: str,
                         dispatch: dict, gate: dict) -> dict:
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "reval2"),
            "expected_execution_dispatch_id": dispatch["execution_dispatch_id"],
            "expected_execution_dispatch_sha256": dispatch["canonical_sha256"],
            "expected_dispatch_eligibility_id": gate["dispatch_eligibility_id"],
            "expected_dispatch_eligibility_sha256": gate["canonical_sha256"],
            "requested_by": "mission-auto-execution",
            "reason": "Authoritative pre-dispatch Governance revalidation before execution",
            "metadata": {"stage": "3.5.3", **_AUTOMATION}}


def attempt_request(service, mission_id: str, active: dict, anchor: str,
                    dispatch: dict, gate: dict, reval: dict) -> dict:
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "attempt"),
            "expected_execution_dispatch_id": dispatch["execution_dispatch_id"],
            "expected_execution_dispatch_sha256": dispatch["canonical_sha256"],
            "expected_dispatch_eligibility_id": gate["dispatch_eligibility_id"],
            "expected_dispatch_eligibility_sha256": gate["canonical_sha256"],
            "expected_pre_dispatch_revalidation_id": reval["pre_dispatch_revalidation_id"],
            "expected_pre_dispatch_revalidation_sha256": reval["canonical_sha256"],
            "created_by": "mission-auto-execution",
            "reason": "Commit idempotent execution attempt identity under a fresh Governance ALLOW",
            "metadata": {"stage": "3.5.4", **_AUTOMATION}}


def execution_delivery_request(service, mission_id: str, active: dict, anchor: str, attempt: dict) -> dict:
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "exec-delivery"),
            "expected_execution_attempt_id": attempt["execution_attempt_id"],
            "expected_execution_attempt_sha256": attempt["canonical_sha256"],
            "expected_dispatch_envelope_id": attempt["dispatch_envelope_id"],
            "delivered_by": "mission-auto-execution",
            "reason": "Deliver immutable dispatch envelope to runtime intake and persist acknowledgement",
            "metadata": {"stage": "3.5.5", **_AUTOMATION}}


def running_request(service, mission_id: str, active: dict, anchor: str,
                    attempt: dict, delivery: dict) -> dict:
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "running"),
            "expected_execution_delivery_id": delivery["execution_delivery_id"],
            "expected_execution_delivery_sha256": delivery["canonical_sha256"],
            "expected_execution_attempt_id": attempt["execution_attempt_id"],
            "expected_execution_attempt_sha256": attempt["canonical_sha256"],
            "expected_dispatch_envelope_id": attempt["dispatch_envelope_id"],
            "projected_by": "mission-auto-execution",
            "reason": "Observe downstream RUNNING state and persist append-only heartbeat projection",
            "metadata": {"stage": "3.5.6", **_AUTOMATION}}


def result_request(service, mission_id: str, active: dict, anchor: str,
                   attempt: dict, delivery: dict, running: dict) -> dict:
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "result"),
            "expected_execution_delivery_id": delivery["execution_delivery_id"],
            "expected_execution_delivery_sha256": delivery["canonical_sha256"],
            "expected_execution_attempt_id": attempt["execution_attempt_id"],
            "expected_execution_attempt_sha256": attempt["canonical_sha256"],
            "expected_dispatch_envelope_id": attempt["dispatch_envelope_id"],
            "expected_running_projection_id": running["running_projection_id"],
            "expected_running_projection_sha256": running["canonical_sha256"],
            "captured_by": "mission-auto-execution",
            "reason": "Capture authoritative terminal result plus immutable evidence/artifact references",
            "metadata": {"stage": "3.5.7", **_AUTOMATION}}


def propagation_request(service, mission_id: str, active: dict, anchor: str,
                        attempt: dict, result: dict) -> dict:
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "propagation"),
            "expected_result_capture_id": result["result_capture_id"],
            "expected_result_capture_sha256": result["canonical_sha256"],
            "expected_execution_attempt_id": attempt["execution_attempt_id"],
            "expected_execution_attempt_sha256": attempt["canonical_sha256"],
            "propagated_by": "mission-auto-execution",
            "reason": "Verify terminal execution outcome and propagate non-success fail-fast",
            "metadata": {"stage": "3.5.8", **_AUTOMATION}}


def recovery_request(service, mission_id: str, active: dict, anchor: str,
                     attempt: dict, delivery: dict, running: dict, result: dict,
                     propagation: dict, *, termination_control_count: int = 0) -> dict:
    replay = service.get_execution_event_replay(mission_id)["replay"]
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _ev_key(anchor, "checkpoint"),
            "expected_execution_attempt_id": attempt["execution_attempt_id"],
            "expected_execution_attempt_sha256": attempt["canonical_sha256"],
            "expected_execution_delivery_id": delivery["execution_delivery_id"],
            "expected_execution_delivery_sha256": delivery["canonical_sha256"],
            "expected_running_projection_id": running["running_projection_id"],
            "expected_running_projection_sha256": running["canonical_sha256"],
            "expected_result_capture_id": result["result_capture_id"],
            "expected_result_capture_sha256": result["canonical_sha256"],
            "expected_outcome_propagation_id": propagation["outcome_propagation_id"],
            "expected_outcome_propagation_sha256": propagation["canonical_sha256"],
            "expected_termination_control_count": int(termination_control_count),
            "expected_execution_event_count": replay["execution_event_count"],
            "expected_execution_event_tip_sha256": replay["execution_event_tip_sha256"],
            "created_by": "mission-auto-execution",
            "reason": "Reconstruct terminal execution from durable evidence and seal a recovery checkpoint",
            "metadata": {"stage": "3.5.9", **_AUTOMATION}}


def produce_execution_evidence(service, mission_id: str, active: dict, delivery: dict) -> dict:
    """Drive the Stage-3.5 chain for one delegated task and return its evidence.

    Preconditions: the mission is RUNNING and ``delivery`` is the task's Stage-3.4
    delegation delivery receipt. Returns a dict of every intermediate row plus the
    four Stage-3.6 inputs under ``attempt``/``result``/``propagation``/``checkpoint``.

    Idempotent and replay-safe: every call carries a deterministic key anchored on
    the delivery receipt, so a re-run resumes the same evidence lineage. It drives
    the chain regardless of terminal state -- a terminal non-success ``result`` is
    still propagated and checkpointed as durable evidence; completion eligibility is
    decided later by the Stage-3.6 chain, which fails closed on non-success.
    """
    anchor = delivery["delivery_receipt_id"]

    dispatch = service.create_execution_dispatch_contract(
        mission_id, dispatch_request(service, mission_id, active, delivery))
    gate = service.create_dispatch_eligibility_gate(
        mission_id, eligibility_request(service, mission_id, active, anchor, dispatch))
    reval = service.authorize_pre_dispatch_execution(
        mission_id, revalidation_request(service, mission_id, active, anchor, dispatch, gate))
    attempt = service.commit_execution_attempt(
        mission_id, attempt_request(service, mission_id, active, anchor, dispatch, gate, reval))
    exec_delivery = service.deliver_execution_attempt(
        mission_id, execution_delivery_request(service, mission_id, active, anchor, attempt))
    running = service.project_running_execution_state(
        mission_id, running_request(service, mission_id, active, anchor, attempt, exec_delivery))
    result = service.capture_execution_result(
        mission_id, result_request(service, mission_id, active, anchor, attempt, exec_delivery, running))
    propagation = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, anchor, attempt, result))
    checkpoint = service.create_execution_recovery_checkpoint(
        mission_id, recovery_request(service, mission_id, active, anchor, attempt, exec_delivery,
                                     running, result, propagation))

    succeeded = result.get("execution_state") == SUCCEEDED
    if not succeeded:
        LOGGER.info("Task %s execution terminal non-success (%s); evidence sealed, completion deferred to Stage 3.6",
                    delivery.get("planned_task_id"), result.get("execution_state"))

    return {"dispatch": dispatch, "gate": gate, "reval": reval, "attempt": attempt,
            "execution_delivery": exec_delivery, "running": running, "result": result,
            "propagation": propagation, "checkpoint": checkpoint,
            "execution_state": result.get("execution_state"), "succeeded": succeeded}
