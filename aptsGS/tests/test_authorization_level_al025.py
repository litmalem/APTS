"""AL-025 autonomy-level re-authorization + incident downgrade (Fase 3).

Pure contract tests — no DB, no server, no temp dir — for the time-bounded
level grant, fail-closed evaluation, incident downgrade, human re-authorization,
and tamper-evident lineage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.authorization_level import (
    AuthorizationLevelError,
    GRANT_ACTIVE,
    GRANT_DOWNGRADED,
    build_authorization_level_grant,
    downgrade_on_incident,
    evaluate_level_authorization,
    level_gate_reason_codes,
    reauthorize_level,
    verify_authorization_level_grant,
    verify_authorization_level_transition,
    verify_level_authorization_decision,
)

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
YEAR = timedelta(days=365)


def _grant(level=3, *, start=None, end=None, status=GRANT_ACTIVE, requires_reauth=False):
    start = start or (NOW - timedelta(days=1))
    end = end or (NOW + YEAR)
    return build_authorization_level_grant(
        grant_id="grant-001",
        mission_id="mission-abc",
        scope_contract_id="scope-xyz",
        authorized_level=level,
        approver="human:ciso",
        authorization_reference="decision-al025-001",
        valid_from=start,
        valid_until=end,
        status=status,
        requires_reauthorization=requires_reauth,
    )


# --- grant + evaluation -------------------------------------------------------

def test_valid_grant_in_ceiling_is_eligible_and_non_executing():
    d = evaluate_level_authorization(_grant(level=3), requested_level=3, now=NOW)
    assert d["status"] == "ELIGIBLE"
    assert d["failed_rule_ids"] == []
    assert d["fail_closed"] is True
    # never authorizes or executes
    assert all(v is False for v in d["semantics"].values())
    assert verify_level_authorization_decision(d) is True


def test_request_below_ceiling_is_eligible():
    d = evaluate_level_authorization(_grant(level=3), requested_level=2, now=NOW)
    assert d["status"] == "ELIGIBLE"


def test_request_above_ceiling_fails_closed():
    d = evaluate_level_authorization(_grant(level=2), requested_level=4, now=NOW)
    assert d["status"] == "INELIGIBLE"
    assert "LEVEL-CEILING" in d["failed_rule_ids"]


def test_expired_window_fails_closed():
    g = _grant(level=4, start=NOW - 2 * YEAR, end=NOW - timedelta(days=1))
    d = evaluate_level_authorization(g, requested_level=1, now=NOW)
    assert d["status"] == "INELIGIBLE"
    assert "GRANT-WINDOW" in d["failed_rule_ids"]


def test_not_yet_valid_fails_closed():
    g = _grant(level=4, start=NOW + timedelta(days=1), end=NOW + YEAR)
    d = evaluate_level_authorization(g, requested_level=1, now=NOW)
    assert d["status"] == "INELIGIBLE"
    assert "GRANT-WINDOW" in d["failed_rule_ids"]


def test_missing_grant_is_denied():
    d = evaluate_level_authorization(None, requested_level=1, now=NOW)
    assert d["status"] == "INELIGIBLE"
    assert "GRANT-INTEGRITY" in d["failed_rule_ids"]
    assert d["requires_reauthorization"] is True


def test_emergency_stop_preempts_even_valid_grant():
    d = evaluate_level_authorization(_grant(level=4), requested_level=1, now=NOW, emergency_active=True)
    assert d["status"] == "INELIGIBLE"
    assert "EMERGENCY-STOP" in d["failed_rule_ids"]


def test_tampered_grant_fails_integrity():
    g = dict(_grant(level=2))
    g["authorized_level"] = 4  # privilege-escalation attempt
    assert verify_authorization_level_grant(g) is False
    d = evaluate_level_authorization(g, requested_level=4, now=NOW)
    assert d["status"] == "INELIGIBLE"
    assert "GRANT-INTEGRITY" in d["failed_rule_ids"]


# --- incident downgrade -------------------------------------------------------

def test_downgrade_lowers_ceiling_and_records_linked_transition():
    g = _grant(level=4)
    downgraded, transition = downgrade_on_incident(
        g, signal="DEGRADE", to_level=2, now=NOW,
        transition_id="tr-001", downgraded_grant_id="grant-002",
    )
    assert downgraded["authorized_level"] == 2
    assert downgraded["status"] == GRANT_ACTIVE
    assert downgraded["requires_reauthorization"] is True
    assert verify_authorization_level_grant(downgraded) is True
    # lineage: transition links old -> new, hash-bound
    assert transition["transition_type"] == "DOWNGRADE"
    assert transition["from_grant_sha256"] == g["integrity"]["canonical_sha256"]
    assert transition["to_grant_sha256"] == downgraded["integrity"]["canonical_sha256"]
    assert transition["from_level"] == 4 and transition["to_level"] == 2
    assert transition["signal"] == "DEGRADE"
    assert verify_authorization_level_transition(transition) is True


def test_post_downgrade_request_above_new_ceiling_is_denied():
    g = _grant(level=4)
    downgraded, _ = downgrade_on_incident(
        g, signal="HALT", to_level=1, now=NOW,
        transition_id="tr-002", downgraded_grant_id="grant-003",
    )
    assert evaluate_level_authorization(downgraded, requested_level=3, now=NOW)["status"] == "INELIGIBLE"
    assert evaluate_level_authorization(downgraded, requested_level=1, now=NOW)["status"] == "ELIGIBLE"


def test_downgrade_must_strictly_lower_level():
    g = _grant(level=2)
    with pytest.raises(AuthorizationLevelError):
        downgrade_on_incident(g, signal="DEGRADE", to_level=2, now=NOW,
                              transition_id="tr", downgraded_grant_id="g")
    with pytest.raises(AuthorizationLevelError):
        downgrade_on_incident(g, signal="DEGRADE", to_level=3, now=NOW,
                              transition_id="tr", downgraded_grant_id="g")


def test_unknown_incident_signal_is_rejected():
    with pytest.raises(AuthorizationLevelError):
        downgrade_on_incident(_grant(level=3), signal="LOL", to_level=1, now=NOW,
                              transition_id="tr", downgraded_grant_id="g")


# --- re-authorization ---------------------------------------------------------

def test_reauthorize_supersedes_downgraded_grant():
    g = _grant(level=4)
    downgraded, _ = downgrade_on_incident(
        g, signal="ESCALATE", to_level=1, now=NOW,
        transition_id="tr-004", downgraded_grant_id="grant-004",
    )
    # mark the downgraded grant as closed before re-auth (operator action)
    closed = build_authorization_level_grant(
        grant_id=downgraded["grant_id"], mission_id=downgraded["mission_id"],
        scope_contract_id=downgraded["scope_contract_id"],
        authorized_level=downgraded["authorized_level"], approver=downgraded["approver"],
        authorization_reference=downgraded["authorization_reference"],
        valid_from=downgraded["valid_from"], valid_until=downgraded["valid_until"],
        status=GRANT_DOWNGRADED, requires_reauthorization=True,
    )
    new_grant, transition = reauthorize_level(
        closed, approver="human:ciso", authorized_level=3,
        authorization_reference="decision-al025-002",
        valid_from=NOW, valid_until=NOW + YEAR, now=NOW,
        grant_id="grant-005", transition_id="tr-005",
    )
    assert new_grant["status"] == GRANT_ACTIVE
    assert new_grant["authorized_level"] == 3
    assert new_grant["requires_reauthorization"] is False
    assert new_grant["predecessor_grant_sha256"] == closed["integrity"]["canonical_sha256"]
    assert transition["transition_type"] == "REAUTHORIZE"
    assert transition["approver"] == "human:ciso"
    assert evaluate_level_authorization(new_grant, requested_level=3, now=NOW)["status"] == "ELIGIBLE"


# --- integration seam + validation -------------------------------------------

def test_level_gate_reason_codes_match_evaluation():
    assert level_gate_reason_codes(_grant(level=3), requested_level=3, now=NOW) == []
    codes = level_gate_reason_codes(_grant(level=1), requested_level=4, now=NOW)
    assert codes == ["LEVEL_AUTHORIZATION_FAILED:LEVEL-CEILING"]


def test_invalid_level_is_rejected_fail_closed():
    with pytest.raises(AuthorizationLevelError):
        _grant(level=5)
    with pytest.raises(AuthorizationLevelError):
        _grant(level=0)


def test_valid_until_must_follow_valid_from():
    with pytest.raises(AuthorizationLevelError):
        _grant(start=NOW, end=NOW - timedelta(days=1))
