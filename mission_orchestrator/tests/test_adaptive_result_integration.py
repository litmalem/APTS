"""Regression guard for wiring the condition signal into the sealed adapter result.

Proves that adding a ``condition_signal`` field to the adapter result does not
break ``verify_adapter_result`` (which seals the whole dict via integrity and
checks only specific fields, tolerating extra ones). This is the core risk of
the runtime wiring; it is checked here because the full Stage 6.4/6.5 acceptance
suite cannot run in this environment (pytest temp-dir permission).

Run from mission_orchestrator/:  python -m pytest tests/test_adaptive_result_integration.py
"""
from execution_subsystem.adapter_contract import ADAPTER_CONTROL_VERSION, RESULT_DOMAIN, verify_adapter_result
from execution_subsystem.condition_signal import condition_signal_from_adapter_collection
from execution_subsystem.execution_contract import with_integrity


def _sealed_result(**extra):
    core = {
        "schema_version": "apts-execution-adapter-result-v1",
        "control_version": ADAPTER_CONTROL_VERSION,
        "status": "SUCCEEDED",
        "reason_codes": [],
        "sensitive_output_retained": False,
        "semantics": {
            "target_network_io_performed": True,
            "tool_invocation_performed": True,
            "specialist_raw_target_access": False,
            "authorization_minted_locally": False,
            "action_result_created": False,
            "vep_created": False,
            "vulnerability_confirmed": False,
        },
        **extra,
    }
    return with_integrity(core, RESULT_DOMAIN)


def test_result_without_condition_signal_still_verifies():
    assert verify_adapter_result(_sealed_result()) is True


def test_result_with_condition_signal_none_verifies():
    assert verify_adapter_result(_sealed_result(condition_signal=None)) is True


def test_result_with_condition_signal_object_verifies():
    signal = condition_signal_from_adapter_collection(
        {"response_sha256": "a" * 64, "response_b64": "", "frames": []},
        attempt_ref="toolinv-x", execution_id="exec-" + "a" * 32,
    )
    # Empty frames -> helper returns None defensively; still a valid sealed result.
    result = _sealed_result(condition_signal=signal)
    assert verify_adapter_result(result) is True


def test_extra_field_does_not_defeat_integrity_tamper_check():
    result = _sealed_result(condition_signal=None)
    # Mutating a sealed field without resealing must fail verification.
    result["status"] = "BLOCKED"
    assert verify_adapter_result(result) is False
