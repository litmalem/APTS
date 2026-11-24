"""Unit tests for the adaptive re-proposal policy (Jalur 2 core).

Deterministic, additive; does not touch the pinned cross_agent_feedback contract.
Run from mission_orchestrator/:  python -m pytest tests/test_adaptive_reproposal.py
"""
import pytest

from pentest_subsystem.adaptive_degradation import AdaptiveDegradationError
from pentest_subsystem.adaptive_reproposal import (
    LOCAL_REPLAN_DECISION_CLASSES,
    TARGET_CONDITION_DEGRADE_FEEDBACK_TYPE,
    derive_degraded_proposal,
    map_condition_to_replan_decision,
)

LIMITS = {"rate_window_seconds": 1.0, "timeout_seconds": 15.0, "max_network_requests": 6}


def _signal(signal_id="tcond-" + "a" * 48, **observed):
    base = {
        "rate_limited": False, "server_overload": False, "access_forbidden": False,
        "waf_indicator": False, "retry_after_seconds": None,
    }
    base.update(observed)
    return {"schema_version": "apts-target-condition-signal-v1", "signal_id": signal_id,
            "observed": base, "integrity": {"canonical_sha256": "d" * 64}}


def test_no_adverse_condition_is_no_change():
    out = map_condition_to_replan_decision(
        signal=_signal(), subject_capability="reconnaissance", current_limits=LIMITS)
    assert out["decision_class"] == "NO_CHANGE"
    assert out["restart_capability"] is None
    assert out["limits_delta"] == {}


def test_rate_limited_on_probing_triggers_replan_local():
    out = map_condition_to_replan_decision(
        signal=_signal(rate_limited=True), subject_capability="enumeration", current_limits=LIMITS)
    assert out["decision_class"] == "REPLAN_LOCAL"
    assert out["restart_capability"] == "enumeration"
    assert out["limits_delta"]["rate_window_seconds"] == 4.0
    assert out["proposed_feedback_type"] == TARGET_CONDITION_DEGRADE_FEEDBACK_TYPE


def test_adverse_on_non_probing_subject_is_no_change():
    out = map_condition_to_replan_decision(
        signal=_signal(rate_limited=True), subject_capability="exploitation", current_limits=LIMITS)
    assert out["decision_class"] == "NO_CHANGE"
    assert out["restart_capability"] is None


def test_repeated_overload_defers_to_stage6():
    out = map_condition_to_replan_decision(
        signal=_signal(server_overload=True), subject_capability="reconnaissance",
        current_limits=LIMITS, prior_degradation_count=2)
    assert out["decision_class"] == "DEFER_TO_STAGE6"
    assert out["restart_capability"] is None


def test_decision_never_escalates_governance():
    # Degradation must never raise intensity/scope.
    for observed in ({"rate_limited": True}, {"server_overload": True},
                     {"waf_indicator": True}, {"access_forbidden": True}):
        out = map_condition_to_replan_decision(
            signal=_signal(**observed), subject_capability="reconnaissance", current_limits=LIMITS)
        assert out["decision_class"] in LOCAL_REPLAN_DECISION_CLASSES
        assert out["decision_class"] != "ESCALATE_GOVERNANCE"


def test_decision_is_deterministic():
    sig = _signal(rate_limited=True, retry_after_seconds=20)
    a = map_condition_to_replan_decision(signal=sig, subject_capability="reconnaissance", current_limits=LIMITS)
    b = map_condition_to_replan_decision(signal=sig, subject_capability="reconnaissance", current_limits=LIMITS)
    assert a == b


def test_degraded_proposal_preserves_footprint():
    proposal = {"proposal_key": "p1", "technique": "TCP_CONNECT_SCAN",
                "rate_cost": 1, "active_concurrency": 1}
    out = derive_degraded_proposal(
        signal=_signal(rate_limited=True), subject_capability="reconnaissance",
        current_proposal=proposal, current_limits=LIMITS)
    dp = out["degraded_proposal"]
    assert dp["rate_cost"] == 1
    assert dp["active_concurrency"] == 1
    assert out["footprint_preserved"] is True
    assert out["pacing_hint"]["rate_window_seconds"] == 4.0
    assert dp["pacing_hint"]["rate_window_seconds"] == 4.0


def test_technique_downgrade_on_waf_for_reconnaissance():
    proposal = {"technique": "TCP_CONNECT_SCAN", "rate_cost": 1, "active_concurrency": 1}
    out = derive_degraded_proposal(
        signal=_signal(waf_indicator=True), subject_capability="reconnaissance",
        current_proposal=proposal, current_limits=LIMITS)
    assert out["technique_downgraded_to"] == "PASSIVE_DISCOVERY"
    assert out["degraded_proposal"]["technique"] == "PASSIVE_DISCOVERY"


def test_no_technique_downgrade_when_no_passive_available():
    # enumeration has no configured passive downgrade -> technique unchanged.
    proposal = {"technique": "SERVICE_ENUMERATION", "rate_cost": 1, "active_concurrency": 1}
    out = derive_degraded_proposal(
        signal=_signal(waf_indicator=True), subject_capability="enumeration",
        current_proposal=proposal, current_limits=LIMITS)
    assert out["technique_downgraded_to"] is None
    assert out["degraded_proposal"]["technique"] == "SERVICE_ENUMERATION"


def test_benign_signal_leaves_proposal_unchanged_apart_from_metadata():
    proposal = {"technique": "TCP_CONNECT_SCAN", "rate_cost": 1, "active_concurrency": 1}
    out = derive_degraded_proposal(
        signal=_signal(), subject_capability="reconnaissance",
        current_proposal=proposal, current_limits=LIMITS)
    assert out["decision_class"] == "NO_CHANGE"
    assert out["pacing_hint"] == {}
    assert "pacing_hint" not in out["degraded_proposal"]
    assert out["degraded_proposal"]["technique"] == "TCP_CONNECT_SCAN"


def test_invalid_signal_rejected():
    with pytest.raises(AdaptiveDegradationError):
        map_condition_to_replan_decision(
            signal={"observed": "nope"}, subject_capability="reconnaissance", current_limits=LIMITS)
    with pytest.raises(AdaptiveDegradationError):
        map_condition_to_replan_decision(
            signal=_signal(), subject_capability="", current_limits=LIMITS)
