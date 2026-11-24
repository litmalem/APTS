from __future__ import annotations

import base64
import hashlib
import time

import pytest

from execution_subsystem.adapter_policy import DEFAULT_LIMITS
from execution_subsystem.execution_contract import ExecutionSourceRejected
from execution_subsystem.sandbox_runtime import ResourceSandbox, _validate_web_fingerprint_result


def _broker_observation(response: bytes, target="https://example.test/"):
    return {"connected": True, "peer_ip": "93.184.216.34", "response_bytes": len(response),
            "response_sha256": hashlib.sha256(response).hexdigest(),
            "response_b64": base64.b64encode(response).decode("ascii"),
            "byte_limit_reached": False, "target": target}


def test_fixed_worker_returns_allowlisted_fingerprints_without_raw_page_data():
    response = (b"HTTP/1.1 200 OK\r\nServer: nginx/1.25\r\nContent-Type: text/html\r\n"
                b"Set-Cookie: session=secret-token\r\n\r\n<html><script src='/_next/static/app.js'></script>"
                b"<p>private page text</p></html>")
    with ResourceSandbox(DEFAULT_LIMITS) as worker:
        result = worker.parse("WEB_PROFILE_FINGERPRINT", _broker_observation(response),
                              deadline=time.monotonic() + 5)
    assert result["target"] == "https://example.test/"
    assert {item["technology"] for item in result["technology_findings"]} == {"nginx", "Next.js"}
    assert b"private page text" not in repr(result).encode()
    assert b"secret-token" not in repr(result).encode()
    assert result["scan_metrics"]["requests_planned"] == 1


def test_fixed_worker_does_not_follow_redirects():
    response = b"HTTP/1.1 302 Found\r\nLocation: https://outside.invalid/\r\n\r\n"
    with ResourceSandbox(DEFAULT_LIMITS) as worker:
        result = worker.parse("WEB_PROFILE_FINGERPRINT", _broker_observation(response),
                              deadline=time.monotonic() + 5)
    assert result["observations"] == [{"status_code": 302, "redirect_blocked": True}]
    assert result["scan_metrics"]["redirects_blocked"] == 1


def test_profile_result_contract_rejects_unexpected_raw_fields():
    value = {"schema_version": "web-technology-observation-v3", "target": "https://example.test/",
        "mode": "fingerprinting", "observations": [{"status_code": 200}], "technology_findings": [],
        "scan_metrics": {"scan_status": "COMPLETED", "requests_planned": 1, "responses_received": 1,
            "response_rate_percent": 100, "request_errors": 0, "fingerprints_matched": 0,
            "redirects_blocked": 0}, "raw_body": "must-not-be-retained"}
    with pytest.raises(ExecutionSourceRejected, match="INVALID_WEB_FINGERPRINT_RESULT"):
        _validate_web_fingerprint_result(value)
