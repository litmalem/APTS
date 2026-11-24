"""Configured authority transport; no caller-selected URL or redirect fallback."""
from __future__ import annotations

import ipaddress
import json
import math
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .authorization_contract import ExecutionGovernanceProtocolError, ExecutionGovernanceUnavailable
from .execution_contract import ExecutionRequestValidationError, canonical_json


def strict_json(raw: bytes) -> dict[str, Any]:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    def invalid_constant(value):
        raise ValueError("non-finite JSON")

    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)
        if not isinstance(decoded, dict):
            raise ValueError("Governance response must be an object")
        canonical_json(decoded)
        return decoded
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ExecutionGovernanceProtocolError("Governance returned invalid or ambiguous JSON") from exc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ExecutionGovernanceProtocolError("Governance redirects are forbidden")


class ExecutionGovernanceClient:
    def __init__(self, base_url: str | None = None, timeout_seconds: float | None = None):
        self.base_url = (base_url or os.getenv("APTS_EXECUTION_GOVERNANCE_URL")
                         or os.getenv("MISSION_GOVERNANCE_BASE_URL", "http://127.0.0.1:8770")).rstrip("/")
        parsed = urlsplit(self.base_url)
        try:
            local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            local = False
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")
                or (parsed.scheme == "http" and not local)):
            raise ExecutionRequestValidationError("Governance URL requires loopback HTTP or authenticated trusted HTTPS")
        try:
            parsed.port
            self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None
                                         else os.getenv("APTS_EXECUTION_GOVERNANCE_TIMEOUT", "5"))
        except ValueError as exc:
            raise ExecutionRequestValidationError("invalid Governance port/timeout") from exc
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 30:
            raise ExecutionRequestValidationError("Governance timeout must be finite and between 0 and 30 seconds")
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
        body = None if payload is None else canonical_json(payload).encode("utf-8")
        req = Request(self.base_url + path, data=body, method=method,
                      headers={"Accept": "application/json", "Content-Type": "application/json",
                               "User-Agent": "APTSExecutionSubsystem/6.2"})
        try:
            with self._opener.open(req, timeout=self.timeout_seconds) as response:
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise ExecutionGovernanceProtocolError("Governance requires HTTP 200 application/json")
                raw = response.read(1048577)
                if len(raw) > 1048576:
                    raise ExecutionGovernanceProtocolError("Governance response exceeds 1 MiB")
        except HTTPError as exc:
            raise ExecutionGovernanceUnavailable(f"Governance returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ExecutionGovernanceUnavailable("authoritative Governance unavailable") from exc
        return strict_json(raw)

    def evaluate_authorization(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", "/api/governance/authorization/evaluate", payload)
        if response.get("status") != "completed" or not isinstance(response.get("policy_decision"), dict):
            raise ExecutionGovernanceProtocolError("Governance must return status=completed and policy_decision")
        return response["policy_decision"]
