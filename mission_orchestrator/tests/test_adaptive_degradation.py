"""Unit tests for the adaptive degradation policy (Component B).

Deterministic, tighten-only. Run from mission_orchestrator/:
    python -m pytest tests/test_adaptive_degradation.py
"""
import pytest

from pentest_subsystem.adaptive_degradation import (
    HALT_PRIOR_DEGRADATION_THRESHOLD,
    OVERLOAD_TIMEOUT_FACTOR,
    RATE_LIMIT_WINDOW_FACTOR,
    AdaptiveDegradationError,
    derive_degradation_delta,
    is_tightening_only,
)

BASE_LIMITS = {
    "rate_window_seconds": 1.0,
    "timeout_seconds": 15.0,
    "max_network_requests": 6,
    "rate_cost": 1,
    "active_concurrency": 1,
}


def _signal(**observed):
    base = {
        "rate_limited": False, "server_overload": False, "access_forbidden": False,
        "waf_indicator": False, "retry_after_seconds": None,
    }
    base.update(observed)
    return {"schema_version": "apts-target-condition-signal-v1", "observed": base}


def test_no_adverse_condition_yields_empty_delta():
    out = derive_degradation_delta(signal=_signal(), current_limits=BASE_LIMITS)
    assert out["limits_delta"] == {}
    assert out["triggers"] == []
    assert out["recommend_halt"] is False
    assert out["recommend_technique_downgrade"] is False


def test_rate_limited_lengthens_window():
    out = derive_degradation_delta(signal=_signal(rate_limited=True), current_limits=BASE_LIMITS)
    assert out["limits_delta"]["rate_window_seconds"] == 1.0 * RATE_LIMIT_WINDOW_FACTOR
    assert "RATE_LIMITED" in out["triggers"]
    assert is_tightening_only(out["limits_delta"], BASE_LIMITS)


def test_retry_after_overrides_factor_when_larger():
    out = derive_degradation_delta(
        signal=_signal(rate_limited=True, retry_after_seconds=30), current_limits=BASE_LIMITS
    )
    # factor would give 4s; Retry-After asks for 30s -> take the larger (gentler).
    assert out["limits_delta"]["rate_window_seconds"] == 30.0
    assert "RETRY_AFTER" in out["triggers"]


def test_retry_after_ignored_when_smaller_than_factor():
    limits = {**BASE_LIMITS, "rate_window_seconds": 10.0}
    out = derive_degradation_delta(
        signal=_signal(rate_limited=True, retry_after_seconds=5), current_limits=limits
    )
    # factor gives 40s, Retry-After only 5s -> keep the larger 40s.
    assert out["limits_delta"]["rate_window_seconds"] == 40.0


def test_server_overload_shrinks_timeout_and_requests():
    out = derive_degradation_delta(signal=_signal(server_overload=True), current_limits=BASE_LIMITS)
    d = out["limits_delta"]
    assert d["timeout_seconds"] == 15.0 * OVERLOAD_TIMEOUT_FACTOR
    assert d["max_network_requests"] == 5
    assert isinstance(d["max_network_requests"], int)
    assert "SERVER_OVERLOAD" in out["triggers"]
    assert is_tightening_only(d, BASE_LIMITS)


def test_timeout_floor_respected():
    limits = {**BASE_LIMITS, "timeout_seconds": 1.0}
    out = derive_degradation_delta(signal=_signal(server_overload=True), current_limits=limits)
    # current already at the floor -> shrinking to 0.5 is clamped out, no change.
    assert "timeout_seconds" not in out["limits_delta"]


def test_requests_not_lowered_below_one():
    limits = {**BASE_LIMITS, "max_network_requests": 1}
    out = derive_degradation_delta(signal=_signal(server_overload=True), current_limits=limits)
    assert "max_network_requests" not in out["limits_delta"]


def test_waf_and_forbidden_recommend_technique_downgrade():
    out = derive_degradation_delta(signal=_signal(waf_indicator=True), current_limits=BASE_LIMITS)
    assert out["recommend_technique_downgrade"] is True
    assert "WAF_OR_FORBIDDEN" in out["triggers"]
    # recommendation only; no limit change from WAF alone.
    assert out["limits_delta"] == {}


def test_halt_recommended_after_threshold():
    out = derive_degradation_delta(
        signal=_signal(server_overload=True), current_limits=BASE_LIMITS,
        prior_degradation_count=HALT_PRIOR_DEGRADATION_THRESHOLD,
    )
    assert out["recommend_halt"] is True


def test_halt_not_recommended_before_threshold():
    out = derive_degradation_delta(
        signal=_signal(server_overload=True), current_limits=BASE_LIMITS,
        prior_degradation_count=HALT_PRIOR_DEGRADATION_THRESHOLD - 1,
    )
    assert out["recommend_halt"] is False


def test_never_emits_footprint_raising_keys():
    out = derive_degradation_delta(
        signal=_signal(rate_limited=True, server_overload=True), current_limits=BASE_LIMITS
    )
    assert "rate_cost" not in out["limits_delta"]
    assert "active_concurrency" not in out["limits_delta"]
    assert "maximum_concurrency" not in out["limits_delta"]


def test_absent_limit_keys_are_left_untouched():
    out = derive_degradation_delta(
        signal=_signal(server_overload=True), current_limits={"rate_window_seconds": 1.0}
    )
    # no timeout/max_network_requests reference -> cannot tighten them.
    assert out["limits_delta"] == {}


def test_deterministic():
    sig = _signal(rate_limited=True, retry_after_seconds=12)
    a = derive_degradation_delta(signal=sig, current_limits=BASE_LIMITS)
    b = derive_degradation_delta(signal=sig, current_limits=BASE_LIMITS)
    assert a == b


def test_property_tighten_only_across_conditions():
    # For every combination of adverse conditions, the delta must only tighten.
    import itertools
    flags = ["rate_limited", "server_overload", "access_forbidden", "waf_indicator"]
    for bits in itertools.product([False, True], repeat=len(flags)):
        observed = dict(zip(flags, bits))
        for retry in (None, 2, 99):
            out = derive_degradation_delta(
                signal=_signal(retry_after_seconds=retry, **observed),
                current_limits=BASE_LIMITS,
            )
            assert is_tightening_only(out["limits_delta"], BASE_LIMITS), (observed, retry)


def test_adversarial_signal_cannot_loosen():
    # A hostile signal with absurd retry_after cannot SHRINK the window (grow-only),
    # and nothing it carries can raise a quota. Output stays tighten-only.
    out = derive_degradation_delta(
        signal=_signal(rate_limited=True, retry_after_seconds=0), current_limits=BASE_LIMITS
    )
    # retry_after 0 < factor result 4 -> window still grows to 4, never shrinks.
    assert out["limits_delta"]["rate_window_seconds"] == 4.0
    assert is_tightening_only(out["limits_delta"], BASE_LIMITS)


def test_is_tightening_only_rejects_loosening():
    assert is_tightening_only({"rate_window_seconds": 0.5}, BASE_LIMITS) is False  # window shrank
    assert is_tightening_only({"timeout_seconds": 99.0}, BASE_LIMITS) is False     # timeout grew
    assert is_tightening_only({"max_network_requests": 99}, BASE_LIMITS) is False  # quota grew
    assert is_tightening_only({"rate_cost": 1}, BASE_LIMITS) is False              # forbidden key
    assert is_tightening_only({"unknown_key": 1}, BASE_LIMITS) is False            # not a target
    assert is_tightening_only({"rate_window_seconds": 4.0}, BASE_LIMITS) is True


def test_invalid_inputs_rejected():
    with pytest.raises(AdaptiveDegradationError):
        derive_degradation_delta(signal={"observed": "nope"}, current_limits=BASE_LIMITS)
    with pytest.raises(AdaptiveDegradationError):
        derive_degradation_delta(signal=_signal(), current_limits="nope")
    with pytest.raises(AdaptiveDegradationError):
        derive_degradation_delta(signal=_signal(), current_limits=BASE_LIMITS, prior_degradation_count=-1)
