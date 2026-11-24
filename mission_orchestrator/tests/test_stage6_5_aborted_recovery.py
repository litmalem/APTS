"""Unit coverage for the explicit proven-no-I/O ABORTED recovery predicate.

These are pure predicate tests over the runtime attempt item structure, so they
run without the real socket/native-worker fixtures. They lock in that recovery
is strictly separate from automatic retry: retryable() stays FAILED/TIMEOUT-only
while an ABORTED attempt that provably stopped before any target I/O becomes
eligible for an explicit, freshly-authorized recovery attempt.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
from execution_subsystem.runtime_contract import RECOVERABLE_ABORT_REASONS


def _item(state, *, reason, resources_closed=True, target_io_uncertain=False,
          result_io=False, has_result=True):
    result = None
    if has_result:
        result = {"semantics": {"target_network_io_performed": result_io}}
    return {
        "state": state,
        "target_io_uncertain": target_io_uncertain,
        "events": [{"data": {"reason_code": reason, "resources_closed": resources_closed}}],
        "invocation": {"result": result},
    }


def test_proven_no_io_aborted_is_recoverable_but_not_retryable():
    item = _item("ABORTED", reason="RUNTIME_HEARTBEAT_LOST")
    assert ExecutionRuntimeRepository.recoverable_aborted(item) is True
    assert ExecutionRuntimeRepository.recoverable(item) is True
    # Automatic retry is deliberately NOT widened.
    assert ExecutionRuntimeRepository.retryable(item) is False


def test_all_source_and_heartbeat_reasons_recoverable():
    for reason in RECOVERABLE_ABORT_REASONS:
        assert ExecutionRuntimeRepository.recoverable_aborted(_item("ABORTED", reason=reason)) is True


def test_aborted_after_target_io_not_recoverable():
    item = _item("ABORTED", reason="RUNTIME_HEARTBEAT_LOST", result_io=True)
    assert ExecutionRuntimeRepository.recoverable_aborted(item) is False
    assert ExecutionRuntimeRepository.recoverable(item) is False


def test_intentional_or_anomalous_abort_reasons_not_recoverable():
    for reason in ("MISSION_EMERGENCY_KILL", "RUNTIME_SHUTDOWN",
                   "RUNTIME_CLOCK_MOVED_BACKWARDS", "RUNTIME_SUPERVISION_INTEGRITY_FAILURE"):
        assert ExecutionRuntimeRepository.recoverable_aborted(_item("ABORTED", reason=reason)) is False


def test_io_uncertain_orphan_abort_not_recoverable():
    # Orphan recovery aborts leave target_io_uncertain=True and no result.
    item = _item("ABORTED", reason="RUNTIME_HEARTBEAT_LOST",
                 target_io_uncertain=True, has_result=False)
    assert ExecutionRuntimeRepository.recoverable_aborted(item) is False


def test_unclosed_or_resultless_abort_not_recoverable():
    assert ExecutionRuntimeRepository.recoverable_aborted(
        _item("ABORTED", reason="RUNTIME_HEARTBEAT_LOST", resources_closed=False)) is False
    assert ExecutionRuntimeRepository.recoverable_aborted(
        _item("ABORTED", reason="RUNTIME_HEARTBEAT_LOST", has_result=False)) is False


def test_failed_no_io_is_retryable_and_recoverable_but_not_aborted_recovery():
    item = _item("FAILED", reason="ADAPTER_WALL_TIMEOUT")
    assert ExecutionRuntimeRepository.retryable(item) is True
    assert ExecutionRuntimeRepository.recoverable(item) is True
    assert ExecutionRuntimeRepository.recoverable_aborted(item) is False


def test_succeeded_and_cancelled_never_recoverable():
    for state in ("SUCCEEDED", "CANCELLED", "TIMEOUT"):
        # TIMEOUT with target I/O is a real completion, not a pre-I/O abort.
        item = _item(state, reason="ANY", result_io=True)
        assert ExecutionRuntimeRepository.recoverable_aborted(item) is False
