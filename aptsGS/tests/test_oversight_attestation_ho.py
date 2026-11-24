"""HO L4 oversight hooks (Fase 4): monitoring, periodic review, L3→L4 readiness.

Pure tests — no DB/server. Exercises 24/7 liveness alerting, fail-closed periodic
review (human-signed, tamper-aware), and the L3→L4 readiness accumulator.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.oversight_attestation import (
    L3_MIN_OPERATING_HOURS,
    OversightError,
    build_periodic_review_attestation,
    l3_to_l4_readiness,
    monitoring_alerts,
    verify_l3_to_l4_readiness,
    verify_periodic_review_attestation,
)

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
HEALTHY_WINDOW = {"total_decisions": 100, "ineligible": 10, "emergency_stops": 0,
                  "integrity_failures": 0, "downgrades": 0, "heartbeat_gap_seconds": 30}


def _sealed_record(status="ELIGIBLE"):
    return {"status": status, "integrity": {"canonical_sha256": "a" * 64}}


# --- 24/7 monitoring ----------------------------------------------------------

def test_healthy_window_has_no_alerts():
    assert monitoring_alerts(HEALTHY_WINDOW) == []


def test_missing_heartbeat_is_critical_stale_alert():
    alerts = monitoring_alerts({**HEALTHY_WINDOW, "heartbeat_gap_seconds": None})
    assert any(a["code"] == "MONITORING_STALE" and a["severity"] == "CRITICAL" for a in alerts)


def test_stale_heartbeat_gap_triggers_alert():
    alerts = monitoring_alerts({**HEALTHY_WINDOW, "heartbeat_gap_seconds": 10_000})
    assert alerts[0]["code"] == "MONITORING_STALE"  # critical sorted first


def test_emergency_and_integrity_and_spike_alerts():
    alerts = monitoring_alerts({**HEALTHY_WINDOW, "emergency_stops": 1,
                                "integrity_failures": 2, "ineligible": 90, "downgrades": 1})
    codes = {a["code"] for a in alerts}
    assert {"EMERGENCY_STOP_ACTIVE", "AUDIT_INTEGRITY_FAILURE",
            "INELIGIBLE_SPIKE", "AUTONOMY_DOWNGRADE"} <= codes
    # critical severities sort before warnings
    assert alerts[0]["severity"] == "CRITICAL"


# --- periodic review ----------------------------------------------------------

def test_clean_review_passes_and_is_tamper_evident():
    records = [_sealed_record("ELIGIBLE"), _sealed_record("INELIGIBLE")]
    att = build_periodic_review_attestation(
        records, period_start="2026-11-12T00:00:00Z", period_end="2026-11-19T00:00:00Z",
        reviewer="human:independent-auditor", monitoring_window=HEALTHY_WINDOW, now=NOW,
    )
    assert att["review_passed"] is True
    assert att["records_reviewed"] == 2
    assert att["status_counts"] == {"ELIGIBLE": 1, "INELIGIBLE": 1}
    assert verify_periodic_review_attestation(att) is True
    tampered = {**att, "review_passed": False}
    assert verify_periodic_review_attestation(tampered) is False


def test_missing_reviewer_fails_closed_and_requires_signoff():
    att = build_periodic_review_attestation(
        [_sealed_record()], period_start="2026-11-12T00:00:00Z",
        period_end="2026-11-19T00:00:00Z", reviewer="",
        monitoring_window=HEALTHY_WINDOW, now=NOW,
    )
    assert att["review_passed"] is False
    assert att["requires_human_signoff"] is True


def test_integrity_failure_in_batch_fails_review_closed():
    bad = {"status": "ELIGIBLE"}  # no integrity
    att = build_periodic_review_attestation(
        [_sealed_record(), bad], period_start="2026-11-12T00:00:00Z",
        period_end="2026-11-19T00:00:00Z", reviewer="human:auditor",
        monitoring_window=HEALTHY_WINDOW, now=NOW,
    )
    assert att["review_passed"] is False
    assert att["integrity_failed_indices"] == [1]


def test_critical_monitoring_alert_fails_review():
    att = build_periodic_review_attestation(
        [_sealed_record()], period_start="2026-11-12T00:00:00Z",
        period_end="2026-11-19T00:00:00Z", reviewer="human:auditor",
        monitoring_window={**HEALTHY_WINDOW, "emergency_stops": 1}, now=NOW,
    )
    assert att["review_passed"] is False


def test_review_uses_custom_verifier():
    att = build_periodic_review_attestation(
        [{"status": "ELIGIBLE"}], period_start="2026-11-12T00:00:00Z",
        period_end="2026-11-19T00:00:00Z", reviewer="human:auditor",
        monitoring_window=HEALTHY_WINDOW, now=NOW, verifier=lambda r: True,
    )
    assert att["integrity_failed_indices"] == []
    assert att["review_passed"] is True


def test_review_period_must_be_ordered():
    with pytest.raises(OversightError):
        build_periodic_review_attestation(
            [], period_start="2026-11-19T00:00:00Z", period_end="2026-11-12T00:00:00Z",
            reviewer="human:auditor", monitoring_window=HEALTHY_WINDOW, now=NOW,
        )


# --- L3 → L4 readiness --------------------------------------------------------

def _full_evidence(**overrides):
    base = {"l3_operating_hours": L3_MIN_OPERATING_HOURS, "containment_contained": True,
            "independent_review_passed": True, "monitoring_active": True,
            "incident_response_tested": True}
    return {**base, **overrides}


def test_all_prerequisites_met_is_ready():
    att = l3_to_l4_readiness(_full_evidence(), now=NOW)
    assert att["ready"] is True
    assert att["unmet_criteria"] == []
    assert verify_l3_to_l4_readiness(att) is True


def test_insufficient_hours_blocks_readiness():
    att = l3_to_l4_readiness(_full_evidence(l3_operating_hours=100), now=NOW)
    assert att["ready"] is False
    assert "L3-HOURS" in att["unmet_criteria"]


def test_each_missing_prerequisite_blocks_readiness():
    for key, crit in [("containment_contained", "ADVERSARIAL-SAFETY"),
                      ("independent_review_passed", "INDEPENDENT-REVIEW"),
                      ("monitoring_active", "MONITORING-24-7"),
                      ("incident_response_tested", "INCIDENT-RESPONSE")]:
        att = l3_to_l4_readiness(_full_evidence(**{key: False}), now=NOW)
        assert att["ready"] is False
        assert crit in att["unmet_criteria"]


def test_readiness_rejects_bad_hours():
    with pytest.raises(OversightError):
        l3_to_l4_readiness({"l3_operating_hours": -1}, now=NOW)
