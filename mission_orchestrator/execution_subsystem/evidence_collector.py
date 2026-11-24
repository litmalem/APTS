"""Allowlist-only capture of bytes already produced by authorized fixed adapters."""
from __future__ import annotations

import base64
import ipaddress
import json
import re

from .authorization_contract import utc_timestamp
from .evidence_contract import bytes_sha256
from .execution_contract import ExecutionRequestIntegrityError


def safe_worker_messages(raw):
    messages = []
    omitted = 0
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
            if set(obj) == {"ready", "backend", "pid"}:
                if (obj["ready"] is not True or obj["backend"] not in {"SECCOMP_RLIMIT", "JOB_OBJECT_FIXED_WORKER"}
                    or type(obj["pid"]) is not int or obj["pid"] <= 0):
                    raise ValueError("invalid readiness")
            elif set(obj) == {"result", "backend"}:
                v = obj["result"]
                expected = {"connected", "peer_ip", "response_bytes", "response_sha256", "byte_limit_reached",
                    "http_status", "server_header_present", "server_header_sha256", "validation_verdict", "expected_evidence_confirmed"}
                if (set(v) != expected or obj["backend"] not in {"SECCOMP_RLIMIT", "JOB_OBJECT_FIXED_WORKER"}
                    or any(type(v[k]) is not bool for k in ("connected", "byte_limit_reached", "server_header_present"))
                    or type(v["response_bytes"]) is not int or v["response_bytes"] < 0
                    or not re.fullmatch(r"[0-9a-f]{64}", v["response_sha256"])
                    or v["server_header_sha256"] is not None and not re.fullmatch(r"[0-9a-f]{64}", v["server_header_sha256"])
                    or v["http_status"] is not None and (type(v["http_status"]) is not int or not 100 <= v["http_status"] <= 599)
                    or v["validation_verdict"] != "UNDETERMINED" or v["expected_evidence_confirmed"] is not False):
                    raise ValueError("invalid result")
                ipaddress.ip_address(v["peer_ip"])
            else:
                raise ValueError("unrecognized worker message")
            messages.append(obj)
        except (ValueError, TypeError, KeyError):
            omitted += 1
    return {"stream": "stdout", "messages": messages, "omitted_line_count": omitted,
            "raw_retained": False}


class EvidenceCollector:
    def __init__(self, repository, attempt_id, owner_id, clock):
        self.repository = repository
        self.attempt_id = attempt_id
        self.owner_id = owner_id
        self.clock = clock
        self.failed = False

    def _store(self, kind, value, **metadata):
        try:
            return self.repository.store_capture(self.attempt_id, self.owner_id, kind, value,
                utc_timestamp(self.clock()), **metadata)
        except BaseException:
            self.failed = True
            raise

    def worker_output(self, stdout, stderr_sha256, stderr_size, exit_code, *, complete):
        self._store("STDOUT", safe_worker_messages(stdout), captured_sha256=bytes_sha256(stdout),
                    captured_size_bytes=len(stdout), redacted=True, complete=complete)
        self._store("STDERR", {"stream": "stderr", "raw_retained": False,
            "captured_bytes": stderr_size, "exit_code": exit_code}, captured_sha256=stderr_sha256,
            captured_size_bytes=stderr_size, redacted=True, complete=complete)

    def observe_target(self, observation, *, complete):
        try:
            raw = base64.b64decode(observation["response_b64"], validate=True)
            if bytes_sha256(raw) != observation["response_sha256"] or len(raw) != observation["response_bytes"]:
                raise ExecutionRequestIntegrityError("capture response digest mismatch")
            peer = str(ipaddress.ip_address(observation["peer_ip"]))
            network = {"connected": observation["connected"], "peer_ip": peer,
                "response_bytes": len(raw), "response_sha256": bytes_sha256(raw),
                "byte_limit_reached": observation["byte_limit_reached"], "observation_complete": complete}
            if type(network["connected"]) is not bool or type(network["byte_limit_reached"]) is not bool:
                raise ExecutionRequestIntegrityError("invalid captured network observation")
            self._store("NETWORK_OBSERVATION", network, complete=complete)
            first = raw.split(b"\r\n", 1)[0]
            match = re.match(rb"^HTTP/1\.[01] ([1-5][0-9]{2})(?: |$)", first)
            self._store("TARGET_RESPONSE", {"http_status": None if match is None else int(match[1]),
                "response_bytes": len(raw), "response_sha256": bytes_sha256(raw), "raw_retained": False},
                captured_sha256=bytes_sha256(raw), captured_size_bytes=len(raw), redacted=True,
                complete=complete and not observation["byte_limit_reached"])
        except BaseException:
            self.failed = True
            raise
