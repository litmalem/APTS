"""Deterministic, replay-safe driver that carries one planned task from a routing
intent all the way to a dependency-aware task completion, and the per-mission loop
that drives every READY task and then finalizes the Mission.

Stages composed (all through the authoritative service API):

    Stage 3.4  routing intent -> routing eligibility gate -> route selection
               -> delegation authorization -> delegation -> delegation delivery
    Stage 3.5  produce_execution_evidence  (dispatch .. recovery checkpoint)
    Stage 3.6  complete_task                (outcome .. dependency-aware completion)
    Mission    finalize_mission            (aggregate .. verified completion)

The Stage-3.4 request builders here are ports of the canonical routing/delegation
contracts (whose only non-test home, `e2e_routing_delegation_governance_qualification`,
hardwires them to the acceptance e2e-mission scenario). They are reproduced with
production metadata and deterministic idempotency keys anchored on the planned
task id, so a replay after a crash resumes the same task lineage rather than
duplicating.

This driver mints no Governance authority of its own: `authorize_task_delegation`
and the Stage-3.5 pre-dispatch revalidation obtain authoritative ALLOW/DENY from
the service's injected Governance client, and execution evidence is pulled from
the injected runtime client. It performs no target I/O.

It is fail-closed: a task whose execution terminates non-success has its evidence
sealed (Stage 3.5) but is NOT driven into a completion commit, so the Mission does
not finalize -- `finalize_mission` sees a task that is not VERIFIED_COMPLETE and
stops with blockers. Reaching COMPLETED requires every task to succeed.

PRECONDITIONS: the Mission is RUNNING with an active Plan and an active task
readiness projection (Stage 3.3.8). Multi-wave dependency progression (a task
becoming READY only after its predecessors complete) advances across successive
idempotent `drive_mission` calls as the readiness projection is re-derived; this
module does not itself re-project readiness.
"""
from __future__ import annotations

import hashlib
import logging
import os

from mission_orchestrator.mission_completion_automation import complete_task, finalize_mission
from mission_orchestrator.mission_execution_evidence_automation import produce_execution_evidence

LOGGER = logging.getLogger(__name__)

_AUTOMATION = {"automation": "MISSION_AUTONOMOUS_TASK_DRIVE_V1"}


def _rt_key(planned_task_id: str, stage: str) -> str:
    """A deterministic, replay-stable idempotency key per planned task lineage."""
    seed = hashlib.sha256(planned_task_id.encode()).hexdigest()[:40]
    return "auto-route-" + seed + "-" + stage


def _anchors(service, mission_id: str, active: dict) -> dict:
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
# Stage 3.4 pure request builders (ported, scenario-neutral, production metadata)
# ---------------------------------------------------------------------------

def routing_intent_request(service, mission_id, active, readiness, planned_task_id):
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _rt_key(planned_task_id, "routing-intent"),
            "expected_task_readiness_projection_id": readiness["projection_id"],
            "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
            "planned_task_id": planned_task_id,
            "created_by": "mission-auto-task-drive",
            "reason": "Resolve canonical routing candidates for a READY planned task",
            "metadata": {"stage": "3.4.2", **_AUTOMATION}}


def routing_eligibility_request(service, mission_id, active, readiness, routing):
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _rt_key(routing["planned_task_id"], "routing-eligibility"),
            "expected_task_readiness_projection_id": readiness["projection_id"],
            "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
            "expected_routing_intent_id": routing["routing_intent_id"],
            "expected_routing_intent_sha256": routing["canonical_sha256"],
            "planned_task_id": routing["planned_task_id"],
            "created_by": "mission-auto-task-drive",
            "reason": "Evaluate static routing eligibility and compatibility",
            "metadata": {"stage": "3.4.3", **_AUTOMATION}}


def route_selection_request(service, mission_id, active, readiness, routing, eligibility):
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _rt_key(routing["planned_task_id"], "route-selection"),
            "expected_task_readiness_projection_id": readiness["projection_id"],
            "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
            "expected_routing_intent_id": routing["routing_intent_id"],
            "expected_routing_intent_sha256": routing["canonical_sha256"],
            "expected_eligibility_gate_id": eligibility["eligibility_gate_id"],
            "expected_eligibility_gate_sha256": eligibility["canonical_sha256"],
            "planned_task_id": routing["planned_task_id"],
            "created_by": "mission-auto-task-drive",
            "reason": "Select the deterministic logical route from eligible candidates",
            "metadata": {"stage": "3.4.4", **_AUTOMATION}}


def delegation_authorization_request(service, mission_id, active, route):
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _rt_key(route["planned_task_id"], "delegation-authorization"),
            "expected_route_decision_id": route["route_decision_id"],
            "expected_route_decision_sha256": route["canonical_sha256"],
            "planned_task_id": route["planned_task_id"],
            "requested_by": "mission-auto-task-drive",
            "reason": "Obtain authoritative pre-delegation Governance decision for the selected route",
            "metadata": {"stage": "3.4.5", **_AUTOMATION}}


def delegation_request(service, mission_id, active, route, authorization):
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _rt_key(route["planned_task_id"], "delegation"),
            "expected_delegation_authorization_id": authorization["delegation_authorization_id"],
            "expected_delegation_authorization_sha256": authorization["canonical_sha256"],
            "planned_task_id": route["planned_task_id"],
            "delegated_by": "mission-auto-task-drive",
            "reason": "Materialize immutable logical delegation and handoff envelope",
            "metadata": {"stage": "3.4.6", **_AUTOMATION}}


def delegation_delivery_request(service, mission_id, active, delegation):
    recipient = delegation["handoff_envelope"]["recipient"]
    return {**_anchors(service, mission_id, active),
            "idempotency_key": _rt_key(delegation["planned_task_id"], "delegation-delivery"),
            "expected_delegation_id": delegation["delegation_id"],
            "expected_delegation_sha256": delegation["canonical_sha256"],
            "expected_handoff_envelope_id": delegation["handoff_envelope_id"],
            "expected_handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
            "recipient_subsystem_id": recipient["subsystem_id"],
            "recipient_capability_id": recipient["capability_id"],
            "acknowledged_by": recipient["subsystem_id"],
            "ownership_accepted_by": recipient["subsystem_id"],
            "reason": "Record control-plane handoff acknowledgement and deterministic ownership without dispatch",
            "metadata": {"stage": "3.4.7", **_AUTOMATION}}


def route_and_delegate(service, mission_id: str, active: dict, readiness: dict, planned_task_id: str) -> dict:
    """Drive the Stage-3.4 routing/delegation chain for one task; return its rows.

    The returned ``delivery`` row is the Stage-3.5 input (`produce_execution_evidence`).
    """
    routing = service.create_task_routing_intent(
        mission_id, routing_intent_request(service, mission_id, active, readiness, planned_task_id))
    eligibility = service.create_task_routing_eligibility_gate(
        mission_id, routing_eligibility_request(service, mission_id, active, readiness, routing))
    route = service.create_task_route_selection_decision(
        mission_id, route_selection_request(service, mission_id, active, readiness, routing, eligibility))
    authorization = service.authorize_task_delegation(
        mission_id, delegation_authorization_request(service, mission_id, active, route))
    delegation = service.create_task_delegation(
        mission_id, delegation_request(service, mission_id, active, route, authorization))
    delivery = service.deliver_task_delegation(
        mission_id, delegation_delivery_request(service, mission_id, active, delegation))
    return {"routing": routing, "eligibility": eligibility, "route": route,
            "authorization": authorization, "delegation": delegation, "delivery": delivery}


def drive_task(service, mission_id: str, active: dict, readiness: dict, planned_task_id: str) -> dict:
    """Carry one READY task from routing intent to a dependency-aware completion.

    Fail-closed: if execution terminates non-success, the Stage-3.5 evidence is
    sealed but no completion is committed; the returned status is TERMINAL_NON_SUCCESS
    and the Mission will not finalize until the task succeeds on a later attempt.
    """
    # Stage 3.4 routing/delegation is only legal in PLANNING/REPLANNING. A task that
    # was already routed and delivered there (e.g. by the routing/handoff worker)
    # must be resumed from that immutable delivery, not re-routed while RUNNING.
    existing = [d for d in service.get_delegation_delivery_history(mission_id)["delegation_deliveries"]
                if d.get("planned_task_id") == planned_task_id
                and d.get("plan_version_record_id") == active["plan_version_record_id"]]
    if existing:
        routing = {"delivery": existing[-1], "reused_existing_delivery": True}
    else:
        routing = route_and_delegate(service, mission_id, active, readiness, planned_task_id)
    evidence = produce_execution_evidence(service, mission_id, active, routing["delivery"])

    if not evidence["succeeded"]:
        LOGGER.info("Task %s terminal non-success (%s); completion withheld (fail-closed)",
                    planned_task_id, evidence["execution_state"])
        return {"status": "TERMINAL_NON_SUCCESS", "planned_task_id": planned_task_id,
                "execution_state": evidence["execution_state"],
                "routing": routing, "evidence": evidence}

    completion = complete_task(service, mission_id, active, {
        "attempt": evidence["attempt"], "result": evidence["result"],
        "propagation": evidence["propagation"], "checkpoint": evidence["checkpoint"]})
    return {"status": "COMPLETED", "planned_task_id": planned_task_id,
            "routing": routing, "evidence": evidence, "completion": completion}


def drive_mission(service, mission_id: str) -> dict:
    """Drive every currently-READY task to completion, then attempt finalization.

    Idempotent and fail-closed: already-driven tasks replay without duplication, a
    non-success task leaves the Mission RUNNING with blockers, and finalization only
    declares completion when readiness is READY. Multi-wave missions advance across
    successive calls as the readiness projection is re-derived upstream.
    """
    active = service.get_active_plan_version(mission_id)
    readiness = service.get_active_task_readiness_projection(mission_id)
    ready_keys = list(readiness.get("ready_task_keys", []))

    key_to_id = {t["task_key"]: t["planned_task_id"]
                 for t in service.list_planned_tasks(mission_id)["planned_tasks"]}

    tasks = {}
    for task_key in ready_keys:
        planned_task_id = key_to_id.get(task_key)
        if planned_task_id is None:
            LOGGER.warning("READY task_key %s has no planned task id; skipping", task_key)
            continue
        try:
            tasks[task_key] = drive_task(service, mission_id, active, readiness, planned_task_id)
        except Exception:
            LOGGER.exception("Task drive deferred for %s/%s", mission_id, task_key)
            tasks[task_key] = {"status": "DEFERRED", "planned_task_id": planned_task_id}

    finalization = finalize_mission(service, mission_id)
    return {"mission_id": mission_id, "driven_task_count": len(tasks),
            "tasks": tasks, "finalization": finalization}


def enabled() -> bool:
    """Opt-in: the driver submits Stage-3.5 dispatch/Governance revalidation."""
    return os.getenv("APTS_AUTONOMOUS_TASK_DRIVE", "0").strip() == "1"


def sweep(service) -> None:
    """Drive every RUNNING mission's READY tasks, then attempt finalization.

    Fail-closed and idempotent; each mission is isolated so one failure never
    blocks the others. Multi-wave missions advance one wave per sweep cadence.
    """
    if not enabled():
        return
    ids, offset = [], 0
    while True:
        page = service.list_missions(state="RUNNING", limit=100, offset=offset)
        ids += [row["mission_id"] for row in page["missions"]]
        offset += len(page["missions"])
        if not page["missions"] or offset >= page["mission_count"]:
            break
    for mission_id in ids:
        try:
            drive_mission(service, mission_id)
        except Exception:
            LOGGER.exception("Autonomous task drive deferred for %s", mission_id)
