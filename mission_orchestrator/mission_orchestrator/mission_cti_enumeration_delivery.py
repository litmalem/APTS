"""Autonomous SEALED-CTI -> Enumeration handoff (Stage 5.3), opt-in & fail-closed.

Closes the one remaining manual hop in the mission pipeline: when a Recon run is
COMPLETED and its CTI enrichment is SEALED (verified via an authenticated local
WPT handoff), this worker builds the governed Stage-5.3 enumeration request and
submits it, instead of waiting for an operator to paste it on the Enumeration
Workspace page.

Safety posture (why full-auto is acceptable here):
  * This worker NEVER accesses a target, mints no authorization, and performs no
    network I/O against any target. It only produces an enumerated-asset model
    from already-SEALED, authorized observations.
  * The governed request is built by `cti_enumeration_context_for_recon_run`,
    which performs every lineage/integrity cross-check (WPT handoff match, CTI
    SEALED status, CTI target == task scope target, predecessor recon hashes).
    That draft carries `enumeration_proposals: []`, so NO governed action
    proposal is minted autonomously and nothing can flow into Stage 6 from here.
  * `EnumerationAgentService.run_enumeration` RE-validates every guard
    server-side (recon_context hashes, boundary == immutable task, enumeration
    subtask READY/RUNNING, scope). This worker therefore cannot bypass any
    guard; a wrong candidate is rejected by the agent, not executed.
  * The hop STOPS at the enumerated-asset model. It does not advance Vulnerability
    Hypothesis and does not touch Stage 6; controlled execution and the mission
    completion gate remain separate authorities.

Enablement is opt-in per hop, mirroring the sibling delivery sweeps:
  * APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY=1   -> enable this sweep
  * APTS_CTI_ENUMERATION_DELIVERY_MODE=draft     -> prepare the verified request
    but do NOT submit; a human submits it from the Enumeration Workspace page
    (fields pre-filled). Default mode is 'auto' (submit).
"""
from __future__ import annotations

import logging
import os
from urllib.error import URLError

from mission_orchestrator.canonical import sha256_hex

LOGGER = logging.getLogger(__name__)


def enabled() -> bool:
    return os.getenv("APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY", "").strip() == "1"


def _draft_mode() -> bool:
    return os.getenv("APTS_CTI_ENUMERATION_DELIVERY_MODE", "auto").strip() == "draft"


def deliver(service, mission_id: str, *, pentest=None) -> list[dict]:
    """Submit (or draft) one Stage-5.3 enumeration run per eligible Recon run.

    `service` is the Mission orchestrator service (mission state/scope/listing).
    `pentest` is the Pentest-side service that owns recon runs, orchestrations,
    tasks and the enumeration agent; defaults to EnumerationAgentService().
    Returns a per-candidate outcome list; never raises for ordinary ineligibility.
    """
    # --- Fail-closed guards (mirror mission_wpt_recon_delivery.deliver) ---
    if service.get_mission_state(mission_id)["mission_state"]["state"] != "RUNNING":
        return [{"status": "deferred", "reason": "MISSION_NOT_RUNNING"}]
    contract = service.get_mission_scope_contract(mission_id)["contract"]
    meta = contract.get("metadata", {}).get("gss_scope_sync") or {}
    if not meta.get("source_snapshot_sha256"):
        return [{"status": "deferred", "reason": "GSS_SCOPE_SOURCE_REQUIRED"}]
    from .gss_scope_sync import fetch
    if sha256_hex(fetch(service, mission_id)) != meta["source_snapshot_sha256"]:
        # Scope revoked/revised after snapshot -> never trigger enumeration on a stale scope.
        return [{"status": "deferred", "reason": "GSS_SCOPE_CHANGED"}]

    from pentest_subsystem.enumeration import EnumerationAgentService
    from pentest_subsystem.web_ui import cti_enumeration_context_for_recon_run
    pentest = pentest or EnumerationAgentService()

    # --- Discovery: COMPLETED parent Recon runs for this mission ---
    runs = pentest.list_recon_runs(mission_id=mission_id, limit=500)
    if len(runs) > 500:
        return [{"status": "deferred", "reason": "RECON_RUN_LIMIT_EXCEEDED"}]

    outcome: list[dict] = []
    for run in runs:
        if run.get("run_status") != "COMPLETED":
            continue
        # Derived Recon iterations are outputs of a handoff, never candidate parents.
        if run.get("parent_recon_run_id") is not None:
            continue
        recon_run_id = run["recon_run_id"]
        try:
            # Single source of truth for eligibility + governed request. Raises
            # ValueError if the WPT handoff / SEALED CTI / scope lineage is not
            # yet satisfied. The returned draft has enumeration_proposals == [].
            ctx = cti_enumeration_context_for_recon_run(pentest, recon_run_id)
        except (ValueError, URLError, TimeoutError) as exc:
            outcome.append({"status": "waiting", "recon_run_id": recon_run_id,
                            "reason": str(exc)})
            # Option C: a mission that keeps returning 'waiting' is NOT reaching
            # the Enumeration stage. Surface it at WARNING (not INFO) with the
            # mission id and the exact blocking reason so a persistent stall is
            # visible to operators/log UIs rather than looking healthy.
            LOGGER.warning(
                "CTI -> Enumeration not advancing (mission not reaching Enumeration stage) "
                "mission=%s recon=%s reason=%s", mission_id, recon_run_id, exc)
            continue

        orchestration_id = ctx["orchestration_id"]
        # Idempotency: exactly one enumeration run per orchestration.
        if pentest.get_orchestration_enumeration_run(orchestration_id) is not None:
            outcome.append({"status": "replayed", "orchestration_id": orchestration_id})
            continue

        if _draft_mode():
            # Mode B: leave the verified request for a human to submit from the UI.
            outcome.append({
                "status": "drafted",
                "orchestration_id": orchestration_id,
                "recon_run_id": recon_run_id,
                "request_id": ctx["enumeration_request_draft"]["request_id"],
            })
            continue

        # Mode A (default): submit. run_enumeration re-validates every guard and
        # neither mints authorization nor performs target I/O.
        # A stale/conflicting candidate must not starve other tasks in this mission.
        try:
            result = pentest.run_enumeration(orchestration_id, ctx["enumeration_request_draft"])
        except (ValueError, RuntimeError) as exc:
            LOGGER.warning("CTI -> Enumeration deferred recon=%s reason=%s", recon_run_id, exc)
            outcome.append({"status": "deferred", "recon_run_id": recon_run_id,
                            "reason": str(exc)})
            continue
        outcome.append({
            "status": result.get("status"),
            "orchestration_id": orchestration_id,
            "recon_run_id": recon_run_id,
            "enumeration_run_id": result.get("run", {}).get("enumeration_run_id"),
            "created": result.get("created", False),
            "target_actuation": False,
            "authorization_minted": False,
        })
        LOGGER.info("CTI -> Enumeration %s recon=%s enumeration=%s", result.get("status"),
                    recon_run_id, result.get("run", {}).get("enumeration_run_id"))
    return outcome


def sweep(service) -> None:
    """Replay-safe sweep over RUNNING missions; no-op unless explicitly enabled."""
    if not enabled():
        return
    offset, ids = 0, []
    while True:
        page = service.list_missions(state="RUNNING", limit=100, offset=offset)
        ids.extend(row["mission_id"] for row in page["missions"])
        offset += len(page["missions"])
        if not page["missions"] or offset >= page["mission_count"]:
            break
    for mission_id in ids:
        try:
            deliver(service, mission_id)
        except Exception:
            LOGGER.exception("CTI -> Enumeration delivery deferred mission=%s", mission_id)
