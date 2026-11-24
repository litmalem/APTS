"""Stage 6 adaptive degradation — target condition signal (Component A).

This module derives a hash-bound ``target_condition_signal`` from a SEALED web
profile collection result. It is a PURE extractor:

* It performs no network I/O (``new_target_io_performed`` is always False).
* It is deterministic: the same sealed evidence yields the same signal and the
  same ``canonical_sha256``.
* It only reads metadata that already exists in the sealed evidence (HTTP status
  lines, ``Retry-After`` headers, request counts, truncation, collection errors,
  and a conservative WAF header heuristic). It never stores response bodies,
  cookie values, query tokens, or authentication headers.

The signal is DATA, not a decision and not an authorization. The deterministic
degradation policy (Component B) consumes this signal; see
``docs/probing-adaptif-degradasi-otomatis-20261107.md``.

Note on latency: the current collection result does not record per-hop timing,
so this module does not emit a latency field. Capturing latency requires a
separate enhancement to the collection layer and is intentionally out of scope
for this step rather than fabricated here.
"""
from __future__ import annotations

import base64
import re
from typing import Any, Mapping

from .execution_contract import (
    ExecutionRequestValidationError,
    require_id,
    require_sha,
    sha256_hex,
    verify_integrity,
    with_integrity,
)

TARGET_CONDITION_SIGNAL_SCHEMA_VERSION = "apts-target-condition-signal-v1"
TARGET_CONDITION_SIGNAL_HASH_DOMAIN = "APTS_ADAPTIVE_TARGET_CONDITION_SIGNAL_V1"
TARGET_CONDITION_SIGNAL_ID_HASH_DOMAIN = "APTS_ADAPTIVE_TARGET_CONDITION_SIGNAL_ID_V1"
TARGET_CONDITION_SIGNAL_ID_PREFIX = "tcond-"

# Conservative, case-insensitive WAF/CDN response-header fingerprints. Presence
# is a heuristic hint only; it never relaxes any limit.
_WAF_HEADER_SIGNATURES = (
    b"cf-ray",
    b"x-sucuri-id",
    b"x-datadome",
    b"x-akamai-",
    b"x-amz-cf-id",
    b"x-sourcefire",
    b"server: cloudflare",
    b"server: awselb",
    b"x-iinfo",
)

_STATUS_RE = re.compile(rb"^HTTP/1\.[01] ([1-5][0-9]{2})")
_RETRY_AFTER_RE = re.compile(rb"^retry-after:\s*([0-9]{1,6})\s*$", re.IGNORECASE)


class TargetConditionSignalValidationError(ExecutionRequestValidationError):
    pass


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TargetConditionSignalValidationError(f"{field} must be an object")
    return value


def _header_block(frame_bytes: bytes) -> bytes:
    """Return the header block (before the body) of one HTTP response frame."""
    return frame_bytes.partition(b"\r\n\r\n")[0]


def _iter_frame_headers(combined: bytes, frames: list[Mapping[str, Any]]):
    """Yield the header block for each frame, anchored at the frame offset.

    The status line must sit at the very start of the frame slice; this avoids
    mistaking literal ``HTTP/1.1`` bytes inside a response body for a status
    line.
    """
    total = len(combined)
    for index, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise TargetConditionSignalValidationError(f"frames[{index}] must be an object")
        offset = frame.get("offset")
        length = frame.get("length")
        if type(offset) is not int or type(length) is not int or offset < 0 or length < 0:
            raise TargetConditionSignalValidationError(
                f"frames[{index}] must carry integer offset and length"
            )
        start = min(offset, total)
        end = min(offset + length, total)
        yield _header_block(combined[start:end])


def _status_code(header: bytes) -> int | None:
    match = _STATUS_RE.match(header)
    return int(match.group(1)) if match else None


def _retry_after_seconds(header: bytes) -> int | None:
    best: int | None = None
    for line in header.split(b"\r\n"):
        match = _RETRY_AFTER_RE.match(line)
        if match:
            value = int(match.group(1))
            best = value if best is None else max(best, value)
    return best


def _has_waf_signature(header: bytes) -> bool:
    lowered = header.lower()
    return any(sig in lowered for sig in _WAF_HEADER_SIGNATURES)


def _observed_from_collection(collection_result: Mapping[str, Any]) -> dict[str, Any]:
    response_b64 = collection_result.get("response_b64")
    if not isinstance(response_b64, str):
        raise TargetConditionSignalValidationError("collection_result.response_b64 must be a base64 string")
    try:
        combined = base64.b64decode(response_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise TargetConditionSignalValidationError("collection_result.response_b64 is not valid base64") from exc

    frames = collection_result.get("frames")
    if not isinstance(frames, list):
        raise TargetConditionSignalValidationError("collection_result.frames must be an array")

    codes: list[int] = []
    retry_after: int | None = None
    waf_indicator = False
    for header in _iter_frame_headers(combined, frames):
        code = _status_code(header)
        if code is not None:
            codes.append(code)
        seconds = _retry_after_seconds(header)
        if seconds is not None:
            retry_after = seconds if retry_after is None else max(retry_after, seconds)
        waf_indicator = waf_indicator or _has_waf_signature(header)

    errors = collection_result.get("collection_errors", [])
    if not isinstance(errors, list):
        raise TargetConditionSignalValidationError("collection_result.collection_errors must be an array")
    error_codes = {e.get("error_code") for e in errors if isinstance(e, Mapping)}

    truncated = bool(collection_result.get("byte_limit_reached")) or any(
        isinstance(f, Mapping) and bool(f.get("truncated")) for f in frames
    )

    requests_performed = collection_result.get("requests_performed")
    request_budget = collection_result.get("request_budget")
    if requests_performed is not None and type(requests_performed) is not int:
        raise TargetConditionSignalValidationError("collection_result.requests_performed must be an integer")
    if request_budget is not None and type(request_budget) is not int:
        raise TargetConditionSignalValidationError("collection_result.request_budget must be an integer")

    unique_codes = sorted(set(codes))
    status_classes = sorted({f"{code // 100}xx" for code in unique_codes})
    return {
        "status_codes": unique_codes,
        "status_classes": status_classes,
        "rate_limited": 429 in unique_codes,
        "server_overload": 503 in unique_codes,
        "access_forbidden": 403 in unique_codes,
        "retry_after_seconds": retry_after,
        "waf_indicator": waf_indicator,
        "truncated": truncated,
        "connection_failed": "CONNECTION_FAILED" in error_codes,
        "budget_exhausted": "BUDGET_EXHAUSTED" in error_codes,
        "frames_observed": len(frames),
        "requests_performed": requests_performed,
        "request_budget": request_budget,
    }


def deterministic_condition_signal_id(source_evidence_sha256: str) -> str:
    require_sha(source_evidence_sha256, "source_evidence_sha256")
    digest = sha256_hex({
        "hash_domain": TARGET_CONDITION_SIGNAL_ID_HASH_DOMAIN,
        "source_evidence_sha256": source_evidence_sha256,
    })
    return f"{TARGET_CONDITION_SIGNAL_ID_PREFIX}{digest[:48]}"


def extract_target_condition_signal(
    *,
    collection_result: Mapping[str, Any],
    attempt_ref: str,
    execution_id: str,
    source_evidence_sha256: str,
) -> dict[str, Any]:
    """Derive a hash-bound target condition signal from a sealed collection result.

    Pure and deterministic; performs no I/O. The returned record is integrity
    sealed with :data:`TARGET_CONDITION_SIGNAL_HASH_DOMAIN`.
    """
    _require_mapping(collection_result, "collection_result")
    try:
        require_id(attempt_ref, "attempt_ref")
        require_id(execution_id, "execution_id", "exec-")
        require_sha(source_evidence_sha256, "source_evidence_sha256")
    except ExecutionRequestValidationError as exc:
        raise TargetConditionSignalValidationError(str(exc)) from exc

    observed = _observed_from_collection(collection_result)
    core = {
        "schema_version": TARGET_CONDITION_SIGNAL_SCHEMA_VERSION,
        "signal_id": deterministic_condition_signal_id(source_evidence_sha256),
        "attempt_ref": attempt_ref,
        "execution_id": execution_id,
        "source_evidence_sha256": source_evidence_sha256,
        "observed": observed,
        "semantics": {
            "derived_from_sealed_evidence": True,
            "new_target_io_performed": False,
            "is_decision": False,
            "is_authorization": False,
            "degradation_input_only": True,
        },
    }
    return with_integrity(core, TARGET_CONDITION_SIGNAL_HASH_DOMAIN)


def condition_signal_from_adapter_collection(
    collection_result: Any, *, attempt_ref: str, execution_id: str
) -> dict[str, Any] | None:
    """Best-effort extraction for the IO path, bound to the combined response digest.

    Returns ``None`` on ANY problem instead of raising, so a caller inside the
    execution path can never be disrupted by signal extraction. The signal is
    bound to ``collection_result['response_sha256']`` (the sealed combined
    response digest), which is the exact evidence the conditions are read from.
    """
    try:
        if not isinstance(collection_result, Mapping):
            return None
        digest = collection_result.get("response_sha256")
        if not isinstance(digest, str):
            return None
        return extract_target_condition_signal(
            collection_result=collection_result,
            attempt_ref=attempt_ref,
            execution_id=execution_id,
            source_evidence_sha256=digest,
        )
    except Exception:
        # Intentional broad catch: signal extraction must never affect the
        # outcome, validity, or sealing of an execution attempt.
        return None


def verify_target_condition_signal(signal: Any) -> bool:
    """Structural + integrity verification for a target condition signal."""
    try:
        if not isinstance(signal, dict):
            return False
        if signal.get("schema_version") != TARGET_CONDITION_SIGNAL_SCHEMA_VERSION:
            return False
        semantics = signal.get("semantics")
        if not isinstance(semantics, dict):
            return False
        if semantics.get("new_target_io_performed") is not False:
            return False
        if semantics.get("is_authorization") is not False:
            return False
        observed = signal.get("observed")
        if not isinstance(observed, dict):
            return False
        require_id(signal.get("signal_id", ""), "signal_id", TARGET_CONDITION_SIGNAL_ID_PREFIX)
        require_sha(signal.get("source_evidence_sha256", ""), "source_evidence_sha256")
        if signal["signal_id"] != deterministic_condition_signal_id(signal["source_evidence_sha256"]):
            return False
        return verify_integrity(signal, TARGET_CONDITION_SIGNAL_HASH_DOMAIN)
    except (ExecutionRequestValidationError, KeyError, TypeError, ValueError):
        return False
