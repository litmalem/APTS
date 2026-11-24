"""HO (Human Oversight) L4 — periodic review, 24/7 monitoring, L3→L4 readiness.

GOV-PLANE oversight instrumentation (Fase 4). The traceability review found HO at
L4 is a `gap`: the platform has per-action human approval (HUMAN-LAYER `review` +
GOV-D03 Approval Record) but no *periodic* independent review, no 24/7 monitoring
signal, and no tested incident-response / tabletop. Those are largely procedural;
this module provides the concrete **code hooks** so the procedures have machine-
checkable, hash-bound evidence instead of being purely manual:

  * `monitoring_alerts()`        — 24/7 liveness + anomaly alerts over a metrics
                                   window (staleness = missing heartbeat).
  * `build_periodic_review_attestation()` — a hash-bound, human-signed review record
                                   over a batch of governance decision records,
                                   fail-closed on any integrity failure.
  * `l3_to_l4_readiness()`       — accumulates the §6 L3→L4 prerequisites (≥500h L3,
                                   adversarial/containment testing, independent
                                   review, active monitoring, tested IR) into a
                                   hash-bound readiness attestation.

Pure functions (no I/O, no DB): callers feed aggregates/records computed from the
audit hash-chain and decision store. No record here authorizes or executes; it only
attests. Human sign-off (`reviewer`, `approver`) stays a human responsibility —
this module records it, it does not synthesize it.

NOTE (honesty). Implementing these hooks does NOT by itself make HO L4 `met`: that
needs the procedures actually operated (real 24/7 monitoring, real periodic reviews,
real tabletop exercises) with the evidence these functions attest. See the runbook
and checklist under `aptsGS/docs/oversight/`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from .utils import sha256_json

SCHEMA_REVIEW = "apts-gss-periodic-review-attestation-v1"
SCHEMA_READINESS = "apts-gss-l3-l4-readiness-attestation-v1"
SCHEMA_SNAPSHOT = "apts-gss-monitoring-snapshot-v1"
REVIEW_DOMAIN = "APTS_HO_PERIODIC_REVIEW_ATTESTATION_V1"
READINESS_DOMAIN = "APTS_HO_L3_L4_READINESS_ATTESTATION_V1"
SNAPSHOT_DOMAIN = "APTS_HO_MONITORING_SNAPSHOT_V1"

# §6 L3→L4 progression prerequisite: minimum hours of L3 operation.
L3_MIN_OPERATING_HOURS = 500

# Default 24/7 monitoring thresholds (callers may override).
DEFAULT_THRESHOLDS = {
    "ineligible_ratio": 0.5,          # share of decisions denied in the window
    "max_heartbeat_gap_seconds": 300,  # liveness: no monitoring sample => stale
    "max_emergency_stops": 0,          # any active emergency stop is an alert
    "max_integrity_failures": 0,       # any tampered/invalid record is an alert
}

_SEVERITY = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


class OversightError(ValueError):
    """Raised on malformed oversight input; callers treat it as fail-closed."""


# --- sealing (same convention as authorization_level / execution_revalidation) --

def _seal(core: Mapping[str, Any], *, domain: str) -> dict[str, Any]:
    body = {k: v for k, v in core.items() if k != "integrity"}
    return {
        **body,
        "integrity": {
            "algorithm": "SHA-256",
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "hash_domain": domain,
            "canonical_sha256": sha256_json({"hash_domain": domain, "core": body}),
        },
    }


def _verify(record: Mapping[str, Any], *, domain: str) -> bool:
    if not isinstance(record, Mapping):
        return False
    integrity = record.get("integrity")
    if not isinstance(integrity, Mapping) or integrity.get("hash_domain") != domain:
        return False
    body = {k: v for k, v in record.items() if k != "integrity"}
    expected = {
        "algorithm": "SHA-256",
        "canonicalization": "UTF8_SORTED_JSON_V1",
        "hash_domain": domain,
        "canonical_sha256": sha256_json({"hash_domain": domain, "core": body}),
    }
    return dict(integrity) == expected


def _instant(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value:
        raise OversightError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OversightError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise OversightError(f"{field} requires a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OversightError(f"{field} must be a non-negative integer")
    return value


# --- 24/7 monitoring ----------------------------------------------------------

def monitoring_alerts(
    window: Mapping[str, Any],
    *,
    thresholds: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return alerts for a monitoring window. Empty list = healthy.

    ``window`` keys: total_decisions, ineligible, emergency_stops,
    integrity_failures, downgrades, heartbeat_gap_seconds (seconds since the last
    monitoring sample — the 24/7 liveness signal).
    """
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    total = _nonneg_int(window.get("total_decisions", 0), "total_decisions")
    ineligible = _nonneg_int(window.get("ineligible", 0), "ineligible")
    emergency = _nonneg_int(window.get("emergency_stops", 0), "emergency_stops")
    integrity_failures = _nonneg_int(window.get("integrity_failures", 0), "integrity_failures")
    downgrades = _nonneg_int(window.get("downgrades", 0), "downgrades")
    gap = window.get("heartbeat_gap_seconds")

    alerts: list[dict[str, Any]] = []

    if gap is None or float(gap) > float(t["max_heartbeat_gap_seconds"]):
        alerts.append({"code": "MONITORING_STALE", "severity": "CRITICAL",
                       "detail": "no monitoring heartbeat within expected interval (24/7 liveness)"})
    if integrity_failures > int(t["max_integrity_failures"]):
        alerts.append({"code": "AUDIT_INTEGRITY_FAILURE", "severity": "CRITICAL",
                       "detail": f"{integrity_failures} tamper/integrity failures"})
    if emergency > int(t["max_emergency_stops"]):
        alerts.append({"code": "EMERGENCY_STOP_ACTIVE", "severity": "CRITICAL",
                       "detail": f"{emergency} emergency stop(s) in window"})
    ratio = (ineligible / total) if total else 0.0
    if ratio > float(t["ineligible_ratio"]):
        alerts.append({"code": "INELIGIBLE_SPIKE", "severity": "WARNING",
                       "detail": f"denied ratio {ratio:.2f} exceeds {t['ineligible_ratio']}"})
    if downgrades > 0:
        alerts.append({"code": "AUTONOMY_DOWNGRADE", "severity": "WARNING",
                       "detail": f"{downgrades} autonomy-level downgrade(s) in window"})

    alerts.sort(key=lambda a: _SEVERITY[a["severity"]], reverse=True)
    return alerts


def build_monitoring_snapshot(
    window: Mapping[str, Any],
    *,
    sampled_at: Any,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal a monitoring sample: the window metrics + its alerts + a healthy flag.

    This is the 24/7 liveness/anomaly record a monitoring loop produces each tick;
    `healthy` is False when any alert fires, `critical` lists CRITICAL ones.
    """
    alerts = monitoring_alerts(window, thresholds=thresholds)
    critical = [a["code"] for a in alerts if a["severity"] == "CRITICAL"]
    core = {
        "schema_version": SCHEMA_SNAPSHOT,
        "sampled_at": _iso(_instant(sampled_at, "sampled_at")),
        "window": dict(window),
        "alerts": alerts,
        "critical_alert_codes": critical,
        "healthy": not alerts,
        "fail_closed": True,
    }
    return _seal(core, domain=SNAPSHOT_DOMAIN)


def verify_monitoring_snapshot(record: Mapping[str, Any]) -> bool:
    return _verify(record, domain=SNAPSHOT_DOMAIN)


# --- periodic independent review ---------------------------------------------

def build_periodic_review_attestation(
    records: Sequence[Mapping[str, Any]],
    *,
    period_start: Any,
    period_end: Any,
    reviewer: str,
    monitoring_window: Mapping[str, Any],
    now: Any,
    verifier: Callable[[Mapping[str, Any]], bool] | None = None,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A hash-bound, human-signed periodic review over decision ``records``.

    Fail-closed: any record failing integrity (``verifier`` or a present
    ``integrity.canonical_sha256``), or a missing ``reviewer``, or any CRITICAL
    monitoring alert, makes ``review_passed`` False. Does not mint authority.
    """
    start = _instant(period_start, "period_start")
    end = _instant(period_end, "period_end")
    if end <= start:
        raise OversightError("period_end must be after period_start")

    def _ok(rec: Mapping[str, Any]) -> bool:
        if verifier is not None:
            try:
                return bool(verifier(rec))
            except Exception:
                return False
        integ = rec.get("integrity") if isinstance(rec, Mapping) else None
        return isinstance(integ, Mapping) and bool(integ.get("canonical_sha256"))

    total = len(records)
    integrity_failed = [i for i, r in enumerate(records) if not _ok(r)]
    status_counts: dict[str, int] = {}
    for r in records:
        key = str(r.get("status", "UNKNOWN"))
        status_counts[key] = status_counts.get(key, 0) + 1

    window = {**dict(monitoring_window), "integrity_failures": len(integrity_failed)}
    alerts = monitoring_alerts(window, thresholds=thresholds)
    critical = [a for a in alerts if a["severity"] == "CRITICAL"]

    reviewer_ok = isinstance(reviewer, str) and bool(reviewer)
    review_passed = reviewer_ok and not integrity_failed and not critical

    core = {
        "schema_version": SCHEMA_REVIEW,
        "period_start": _iso(start),
        "period_end": _iso(end),
        "reviewer": reviewer if reviewer_ok else None,
        "reviewed_at": _iso(_instant(now, "now")),
        "records_reviewed": total,
        "status_counts": status_counts,
        "integrity_failed_indices": integrity_failed,
        "monitoring_alerts": alerts,
        "review_passed": bool(review_passed),
        "requires_human_signoff": not reviewer_ok,
        "fail_closed": True,
        "semantics": {"decision_is_authorization": False, "authorization_minted": False,
                      "execution_started": False},
    }
    return _seal(core, domain=REVIEW_DOMAIN)


def verify_periodic_review_attestation(record: Mapping[str, Any]) -> bool:
    return _verify(record, domain=REVIEW_DOMAIN)


# --- L3 → L4 readiness --------------------------------------------------------

def l3_to_l4_readiness(
    evidence: Mapping[str, Any],
    *,
    now: Any,
) -> dict[str, Any]:
    """Accumulate the §6 L3→L4 prerequisites into a hash-bound readiness attestation.

    ``evidence`` keys:
      l3_operating_hours (number), containment_contained (bool, from Fase 2 harness),
      independent_review_passed (bool, from a periodic review attestation),
      monitoring_active (bool), incident_response_tested (bool, tabletop evidence).
    ``ready`` is True only when every criterion is met. Never grants L4 by itself —
    it is an audit gate for a human authorization decision.
    """
    hours = evidence.get("l3_operating_hours", 0)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours < 0:
        raise OversightError("l3_operating_hours must be a non-negative number")

    criteria = [
        {"id": "L3-HOURS", "met": float(hours) >= L3_MIN_OPERATING_HOURS,
         "detail": f"{hours}h of required {L3_MIN_OPERATING_HOURS}h L3 operation"},
        {"id": "ADVERSARIAL-SAFETY", "met": bool(evidence.get("containment_contained")),
         "detail": "containment/adversarial harness reports contained (Fase 2)"},
        {"id": "INDEPENDENT-REVIEW", "met": bool(evidence.get("independent_review_passed")),
         "detail": "a periodic review attestation passed (independent reviewer)"},
        {"id": "MONITORING-24-7", "met": bool(evidence.get("monitoring_active")),
         "detail": "continuous monitoring is active with no stale heartbeat"},
        {"id": "INCIDENT-RESPONSE", "met": bool(evidence.get("incident_response_tested")),
         "detail": "incident-response runbook exercised (tabletop evidence)"},
    ]
    unmet = [c["id"] for c in criteria if not c["met"]]
    core = {
        "schema_version": SCHEMA_READINESS,
        "assessed_at": _iso(_instant(now, "now")),
        "l3_operating_hours": hours,
        "criteria": criteria,
        "unmet_criteria": unmet,
        "ready": not unmet,
        "fail_closed": True,
        "note": "readiness is an audit gate; L4 authorization remains a human decision",
    }
    return _seal(core, domain=READINESS_DOMAIN)


def verify_l3_to_l4_readiness(record: Mapping[str, Any]) -> bool:
    return _verify(record, domain=READINESS_DOMAIN)


__all__ = [
    "OversightError", "L3_MIN_OPERATING_HOURS", "DEFAULT_THRESHOLDS",
    "monitoring_alerts", "build_monitoring_snapshot", "verify_monitoring_snapshot",
    "build_periodic_review_attestation", "verify_periodic_review_attestation",
    "l3_to_l4_readiness", "verify_l3_to_l4_readiness",
]
