"""Tests for Jalur 1 pacing integration into adapter_policy (Component C).

Covers the pure tighten-only helper and the compile_runtime_policy wiring point.
Run from mission_orchestrator/:  python -m pytest tests/test_adaptive_pacing_policy.py
"""
import inspect

import pytest

from execution_subsystem.adapter_policy import apply_observed_tightening, compile_runtime_policy
from execution_subsystem.execution_contract import ExecutionSourceRejected


def _limits():
    return {"rate_window_seconds": 1.0, "timeout_seconds": 15.0,
            "max_network_requests": 6, "maximum_concurrency": 1, "rate_requests": 1}


def test_none_is_noop():
    limits = _limits()
    assert apply_observed_tightening(limits, None) == _limits()


def test_empty_is_noop():
    limits = _limits()
    assert apply_observed_tightening(limits, {}) == _limits()


def test_window_lengthens():
    limits = apply_observed_tightening(_limits(), {"rate_window_seconds": 4.0})
    assert limits["rate_window_seconds"] == 4.0


def test_window_never_shrinks():
    # A shorter window would loosen pacing -> ignored (max keeps the current 1.0).
    limits = apply_observed_tightening(_limits(), {"rate_window_seconds": 0.5})
    assert limits["rate_window_seconds"] == 1.0


def test_timeout_shortens():
    limits = apply_observed_tightening(_limits(), {"timeout_seconds": 7.5})
    assert limits["timeout_seconds"] == 7.5


def test_timeout_never_grows():
    # A longer timeout would loosen the deadline -> ignored (min keeps 15.0).
    limits = apply_observed_tightening(_limits(), {"timeout_seconds": 99.0})
    assert limits["timeout_seconds"] == 15.0


def test_budget_and_concurrency_are_never_touched():
    limits = apply_observed_tightening(_limits(), {
        "max_network_requests": 1, "maximum_concurrency": 9, "rate_cost": 5,
        "rate_window_seconds": 4.0,
    })
    # Only the window changed; footprint fields are untouched.
    assert limits["max_network_requests"] == 6
    assert limits["maximum_concurrency"] == 1
    assert "rate_cost" not in limits
    assert limits["rate_window_seconds"] == 4.0


def test_malformed_rejected():
    with pytest.raises(ExecutionSourceRejected):
        apply_observed_tightening(_limits(), "nope")
    with pytest.raises(ExecutionSourceRejected):
        apply_observed_tightening(_limits(), {"rate_window_seconds": "slow"})


def test_compile_runtime_policy_exposes_observed_tightening_kwarg():
    sig = inspect.signature(compile_runtime_policy)
    assert "observed_tightening" in sig.parameters
    param = sig.parameters["observed_tightening"]
    assert param.default is None
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
