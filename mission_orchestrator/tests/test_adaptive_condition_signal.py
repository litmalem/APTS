"""Unit tests for the adaptive degradation target condition signal (Component A).

Pure extractor: deterministic, no I/O, derives only from sealed evidence.
Run from the mission_orchestrator/ directory:  python -m pytest tests/test_adaptive_condition_signal.py
"""
import base64
import hashlib

import pytest

from execution_subsystem.condition_signal import (
    TARGET_CONDITION_SIGNAL_HASH_DOMAIN,
    TARGET_CONDITION_SIGNAL_SCHEMA_VERSION,
    TargetConditionSignalValidationError,
    condition_signal_from_adapter_collection,
    deterministic_condition_signal_id,
    extract_target_condition_signal,
    verify_target_condition_signal,
)
from execution_subsystem.execution_contract import verify_integrity

EXEC_ID = "exec-" + "a" * 32
ATTEMPT = "attempt-" + "b" * 16
EVID_SHA = "c" * 64


def _http(status_line, headers=(), body=b""):
    head = status_line.encode("latin-1") + b"\r\n"
    for name, value in headers:
        head += f"{name}: {value}".encode("latin-1") + b"\r\n"
    return head + b"\r\n" + body


def _collection(responses, *, errors=None, byte_limit_reached=False,
                requests_performed=None, request_budget=None):
    """Assemble a sealed-style collection result from raw response byte blocks."""
    frames = []
    offset = 0
    for index, raw in enumerate(responses):
        frames.append({
            "offset": offset, "length": len(raw), "probe": index,
            "url": f"http://t/{index}", "redirect_count": 0,
            "redirect_blocked": False, "truncated": False,
        })
        offset += len(raw)
    combined = b"".join(responses)
    result = {
        "response_b64": base64.b64encode(combined).decode(),
        "response_sha256": hashlib.sha256(combined).hexdigest(),
        "response_bytes": len(combined),
        "byte_limit_reached": byte_limit_reached,
        "target": "http://t/",
        "frames": frames,
        "collection_errors": errors or [],
    }
    if requests_performed is not None:
        result["requests_performed"] = requests_performed
    if request_budget is not None:
        result["request_budget"] = request_budget
    return result


def _extract(result):
    return extract_target_condition_signal(
        collection_result=result, attempt_ref=ATTEMPT,
        execution_id=EXEC_ID, source_evidence_sha256=EVID_SHA,
    )


def test_rate_limited_with_retry_after():
    result = _collection([
        _http("HTTP/1.1 429 Too Many Requests", [("Retry-After", "30")]),
    ], requests_performed=1, request_budget=2)
    signal = _extract(result)
    obs = signal["observed"]
    assert obs["rate_limited"] is True
    assert obs["retry_after_seconds"] == 30
    assert obs["status_codes"] == [429]
    assert obs["status_classes"] == ["4xx"]
    assert obs["server_overload"] is False


def test_server_overload_detected():
    result = _collection([_http("HTTP/1.1 503 Service Unavailable")])
    obs = _extract(result)["observed"]
    assert obs["server_overload"] is True
    assert obs["rate_limited"] is False
    assert 503 in obs["status_codes"]


def test_mixed_statuses_and_forbidden():
    result = _collection([
        _http("HTTP/1.1 200 OK"),
        _http("HTTP/1.1 403 Forbidden"),
    ])
    obs = _extract(result)["observed"]
    assert obs["status_codes"] == [200, 403]
    assert obs["status_classes"] == ["2xx", "4xx"]
    assert obs["access_forbidden"] is True


def test_waf_header_heuristic():
    result = _collection([_http("HTTP/1.1 200 OK", [("CF-RAY", "abc123-SIN")])])
    assert _extract(result)["observed"]["waf_indicator"] is True


def test_no_waf_header_is_false():
    result = _collection([_http("HTTP/1.1 200 OK", [("Server", "Apache/2.4.58")])])
    assert _extract(result)["observed"]["waf_indicator"] is False


def test_collection_errors_surface():
    result = _collection(
        [_http("HTTP/1.1 200 OK")],
        errors=[{"probe": 1, "error_code": "BUDGET_EXHAUSTED"},
                {"probe": 0, "error_code": "CONNECTION_FAILED"}],
    )
    obs = _extract(result)["observed"]
    assert obs["budget_exhausted"] is True
    assert obs["connection_failed"] is True


def test_body_with_literal_status_line_not_miscounted():
    # A 200 response whose body contains "HTTP/1.1 500" must not be read as 500.
    result = _collection([
        _http("HTTP/1.1 200 OK", [("Content-Type", "text/plain")], body=b"HTTP/1.1 500 x"),
    ])
    obs = _extract(result)["observed"]
    assert obs["status_codes"] == [200]
    assert obs["server_overload"] is False


def test_truncation_flagged():
    result = _collection([_http("HTTP/1.1 200 OK")], byte_limit_reached=True)
    assert _extract(result)["observed"]["truncated"] is True


def test_deterministic_and_integrity():
    result = _collection([_http("HTTP/1.1 429 Too Many Requests", [("Retry-After", "10")])])
    a = _extract(result)
    b = _extract(result)
    assert a == b
    assert a["integrity"]["canonical_sha256"] == b["integrity"]["canonical_sha256"]
    assert a["signal_id"] == deterministic_condition_signal_id(EVID_SHA)
    assert verify_integrity(a, TARGET_CONDITION_SIGNAL_HASH_DOMAIN)
    assert verify_target_condition_signal(a) is True


def test_signal_semantics_are_non_executing():
    result = _collection([_http("HTTP/1.1 200 OK")])
    signal = _extract(result)
    assert signal["schema_version"] == TARGET_CONDITION_SIGNAL_SCHEMA_VERSION
    sem = signal["semantics"]
    assert sem["new_target_io_performed"] is False
    assert sem["is_authorization"] is False
    assert sem["is_decision"] is False
    assert sem["derived_from_sealed_evidence"] is True


def test_tampered_signal_fails_verification():
    signal = _extract(_collection([_http("HTTP/1.1 200 OK")]))
    signal["observed"]["rate_limited"] = True  # forge without re-sealing
    assert verify_target_condition_signal(signal) is False


def test_retry_after_http_date_ignored():
    # Only numeric delta-seconds are honored; an HTTP-date form yields None.
    result = _collection([
        _http("HTTP/1.1 429 Too Many Requests",
              [("Retry-After", "Wed, 21 Oct 2026 07:28:00 GMT")]),
    ])
    obs = _extract(result)["observed"]
    assert obs["rate_limited"] is True
    assert obs["retry_after_seconds"] is None


def test_bad_base64_rejected():
    result = _collection([_http("HTTP/1.1 200 OK")])
    result["response_b64"] = "!!!not-base64!!!"
    with pytest.raises(TargetConditionSignalValidationError):
        _extract(result)


def test_bad_execution_id_prefix_rejected():
    with pytest.raises(TargetConditionSignalValidationError):
        extract_target_condition_signal(
            collection_result=_collection([_http("HTTP/1.1 200 OK")]),
            attempt_ref=ATTEMPT, execution_id="wrong-prefix", source_evidence_sha256=EVID_SHA,
        )


def test_bad_evidence_sha_rejected():
    with pytest.raises(TargetConditionSignalValidationError):
        extract_target_condition_signal(
            collection_result=_collection([_http("HTTP/1.1 200 OK")]),
            attempt_ref=ATTEMPT, execution_id=EXEC_ID, source_evidence_sha256="short",
        )


# --- Integration helper: condition_signal_from_adapter_collection ---

def test_from_adapter_collection_binds_response_digest():
    # collect_profile-shaped result carries its own combined response_sha256.
    result = _collection([_http("HTTP/1.1 429 Too Many Requests", [("Retry-After", "15")])])
    signal = condition_signal_from_adapter_collection(
        result, attempt_ref="toolinv-" + "a" * 20, execution_id=EXEC_ID)
    assert signal is not None
    assert signal["source_evidence_sha256"] == result["response_sha256"]
    assert signal["observed"]["rate_limited"] is True
    assert signal["observed"]["retry_after_seconds"] == 15
    assert verify_target_condition_signal(signal)


def test_from_adapter_collection_returns_none_without_digest():
    result = _collection([_http("HTTP/1.1 200 OK")])
    del result["response_sha256"]
    assert condition_signal_from_adapter_collection(
        result, attempt_ref="toolinv-x", execution_id=EXEC_ID) is None


def test_from_adapter_collection_never_raises_on_garbage():
    # Defensive contract: any malformed input yields None, never an exception.
    for bad in (None, 42, {}, {"response_sha256": 123}, {"response_sha256": "z" * 64}):
        assert condition_signal_from_adapter_collection(
            bad, attempt_ref="toolinv-x", execution_id=EXEC_ID) is None
