"""Autonomous Enumeration -> Vulnerability Hypothesis correlation (Stage 5.4).

Closes the hop that mission_cti_enumeration_delivery deliberately stops short of
("does NOT advance Vulnerability Hypothesis"): once an enumeration run is
COMPLETED (authoritative enumerated-asset model), this worker pulls real CVE
advisories from the local VulnDesk Pentest Enrichment API for the asset's CPEs,
projects them into Stage-5.4 knowledge_items, and runs the Vulnerability
Hypothesis correlation -- without an operator click.

Safety posture (why full-auto is acceptable here):
  * Modeling only. Never accesses a target, mints no authorization, performs no
    network I/O against a target, and creates no finding. Every hypothesis is
    OPEN/UNVALIDATED; controlled validation remains a Stage-6 authority.
  * The only outbound call is a loopback POST to VulnDesk resolve-cpe (read).
  * run_vulnerability_hypothesis re-validates boundary == immutable task,
    enumeration lineage hashes, and knowledge contracts server-side, so this
    worker cannot bypass a guard; a bad candidate is rejected, not executed.
  * Idempotent: exactly one hypothesis run per orchestration.

Enablement (this is the safest hop in the pipeline, so it defaults ON; opt-out):
  * APTS_AUTONOMOUS_CTI_HYPOTHESIS_CORRELATION=0  -> disable this sweep
  * APTS_CTI_HYPOTHESIS_CORRELATION_MODE=draft    -> compute knowledge_items but
    do NOT run the correlation; default mode 'auto' runs it.
"""
from __future__ import annotations

import hashlib
import logging
import os
from urllib.error import URLError

LOGGER = logging.getLogger(__name__)


def enabled() -> bool:
    return os.getenv("APTS_AUTONOMOUS_CTI_HYPOTHESIS_CORRELATION", "1").strip() != "0"


def _draft_mode() -> bool:
    return os.getenv("APTS_CTI_HYPOTHESIS_CORRELATION_MODE", "auto").strip() == "draft"


def _pentest_service(pentest):
    if pentest is not None:
        return pentest
    from pentest_subsystem.agentic_pentest_acceptance_service import AgenticPentestAcceptanceService
    return AgenticPentestAcceptanceService()


def deliver(service, mission_id: str, *, pentest=None) -> list[dict]:
    """Run (or draft) exactly one Stage-5.4 hypothesis correlation per eligible
    enumeration run of this mission. Never raises for ordinary ineligibility."""
    if service.get_mission_state(mission_id)["mission_state"]["state"] != "RUNNING":
        return [{"status": "deferred", "reason": "MISSION_NOT_RUNNING"}]

    from pentest_subsystem.vulnerability_hypothesis import (
        VULNERABILITY_HYPOTHESIS_RUN_REQUEST_SCHEMA_VERSION,
        VulnerabilityHypothesisAgentValidationError,
        VulnerabilityHypothesisAgentConflict,
        VulnerabilityHypothesisAgentRepositoryError,
        VulnerabilityHypothesisAgentIntegrityError,
    )
    from pentest_subsystem.cti_hypothesis_adapter import build_knowledge_items

    pentest = _pentest_service(pentest)
    runs = pentest.list_enumeration_runs(mission_id=mission_id, limit=500)
    if len(runs) > 500:
        return [{"status": "deferred", "reason": "ENUMERATION_RUN_LIMIT_EXCEEDED"}]

    outcome: list[dict] = []
    for summary in runs:
        if summary.get("run_status") != "COMPLETED":
            continue
        enumeration_run_id = summary.get("enumeration_run_id")
        orchestration_id = summary.get("orchestration_id")
        if not enumeration_run_id or not orchestration_id:
            continue
        # Idempotency: exactly one hypothesis run per orchestration.
        try:
            if pentest.get_orchestration_vulnerability_hypothesis_run(orchestration_id) is not None:
                outcome.append({"status": "replayed", "orchestration_id": orchestration_id})
                continue
        except VulnerabilityHypothesisAgentIntegrityError as exc:
            outcome.append({"status": "deferred", "orchestration_id": orchestration_id, "reason": str(exc)})
            continue

        run = pentest.get_enumeration_run(enumeration_run_id)
        if run is None or not (run.get("output", {}) or {}).get("enumerated_assets"):
            continue

        try:
            knowledge_items = build_knowledge_items(run)
        except (URLError, TimeoutError, ValueError, VulnerabilityHypothesisAgentValidationError) as exc:
            outcome.append({"status": "waiting", "enumeration_run_id": enumeration_run_id, "reason": str(exc)})
            LOGGER.info("Enumeration -> Hypothesis waiting enum=%s reason=%s", enumeration_run_id, exc)
            continue
        if not knowledge_items:
            outcome.append({"status": "no_knowledge", "orchestration_id": orchestration_id,
                            "enumeration_run_id": enumeration_run_id})
            continue
        if _draft_mode():
            outcome.append({"status": "drafted", "orchestration_id": orchestration_id,
                            "enumeration_run_id": enumeration_run_id,
                            "knowledge_item_count": len(knowledge_items)})
            continue

        digest = hashlib.sha256(("vh-auto:" + str(orchestration_id)).encode("utf-8")).hexdigest()[:48]
        payload = {
            "schema_version": VULNERABILITY_HYPOTHESIS_RUN_REQUEST_SCHEMA_VERSION,
            "request_id": "hypreq-" + digest,
            "idempotency_key": "idem-hypreq-" + digest,
            "actor": "mission-auto-cti-hypothesis",
            "boundary": run["request"]["boundary"],
            "enumeration_context": {
                "enumeration_run_id": run["enumeration_run_id"],
                "output_sha256": run["output"]["integrity"]["canonical_sha256"],
                "evidence_bundle_sha256": run["evidence_bundle"]["integrity"]["canonical_sha256"],
            },
            "knowledge_items": knowledge_items,
            "metadata": {"source": "mission_auto_cti_hypothesis", "bridge": "vulndesk_resolve_cpe"},
        }
        try:
            result = pentest.run_vulnerability_hypothesis(orchestration_id, payload)
        except (VulnerabilityHypothesisAgentConflict, VulnerabilityHypothesisAgentValidationError,
                VulnerabilityHypothesisAgentRepositoryError, VulnerabilityHypothesisAgentIntegrityError,
                ValueError) as exc:
            LOGGER.warning("Enumeration -> Hypothesis deferred enum=%s reason=%s", enumeration_run_id, exc)
            outcome.append({"status": "deferred", "enumeration_run_id": enumeration_run_id, "reason": str(exc)})
            continue

        run_obj = result.get("run") or {}
        output = run_obj.get("output") or {}
        outcome.append({
            "status": result.get("status"),
            "orchestration_id": orchestration_id,
            "enumeration_run_id": enumeration_run_id,
            "vulnerability_hypothesis_run_id": run_obj.get("vulnerability_hypothesis_run_id"),
            "knowledge_item_count": len(knowledge_items),
            "hypothesis_count": len(output.get("vulnerability_hypotheses", []) or []),
            "created": result.get("created", False),
            "target_actuation": False,
            "authorization_minted": False,
        })
        LOGGER.info("Enumeration -> Hypothesis %s enum=%s hyp=%s count=%s",
                    result.get("status"), enumeration_run_id,
                    run_obj.get("vulnerability_hypothesis_run_id"),
                    len(output.get("vulnerability_hypotheses", []) or []))
    return outcome


def sweep(service) -> None:
    """Replay-safe sweep over RUNNING missions; defaults on, opt-out via env."""
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
            LOGGER.exception("Enumeration -> Hypothesis correlation deferred mission=%s", mission_id)
