from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionSubsystemProtocolError, MissionValidationError
from .execution_running import (
    RUNNING_EXECUTION_ATTEMPT_STATUS,
    RUNNING_EXECUTION_STATE,
    verify_running_execution_projection_contract,
)
from .execution_delivery import verify_execution_delivery_contract
from .execution_attempt import verify_execution_attempt_contract

EXECUTION_RESULT_SCHEMA_VERSION = "apts-execution-result-evidence-artifact-capture-v1"
EXECUTION_RESULT_HASH_DOMAIN = "MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURE_V1"
EXECUTION_RESULT_REQUEST_HASH_DOMAIN = "MISSION_EXECUTION_RESULT_CAPTURE_REQUEST_V1"
EXECUTION_RESULT_ID_PREFIX = "xresult-"
EXECUTION_RESULT_MODE = "AUTHORITATIVE_RUNTIME_TERMINAL_RESULT_WITH_IMMUTABLE_EVIDENCE_ARTIFACT_MANIFEST"
EXECUTION_RESULT_AUTHORITY = "DOWNSTREAM_SUBSYSTEM_RUNTIME_EXECUTION_RESULT"
EXECUTION_RESULT_ALLOWED_STATES = frozenset({"RUNNING"})
TERMINAL_EXECUTION_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"})
EXECUTION_RESULT_ATTEMPT_STATUS = "TERMINAL_RESULT_CAPTURED"
RUNTIME_RESULT_CHANNEL = "RUNTIME_EXECUTION_TERMINAL_RESULT_READ"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_INLINE_FIELDS = frozenset({"content", "data", "payload", "bytes", "body", "base64", "blob"})
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_execution_delivery_id",
    "expected_execution_delivery_sha256",
    "expected_execution_attempt_id",
    "expected_execution_attempt_sha256",
    "expected_dispatch_envelope_id",
    "expected_running_projection_id",
    "expected_running_projection_sha256",
    "captured_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_execution_result_capture_id() -> str:
    return f"{EXECUTION_RESULT_ID_PREFIX}{uuid.uuid4()}"


def _string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return value


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _string(payload, key, 64).lower()
    if not _SHA_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_execution_result_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("execution result capture request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported execution result capture field(s): " + ", ".join(unknown)
            + "; Stage 3.5.7 derives terminal result, evidence, artifacts, runtime endpoint, and completion time from authoritative downstream runtime observation. Caller-supplied result/evidence/artifact/runtime fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_delivery_id": _string(payload, "expected_execution_delivery_id"),
        "expected_execution_attempt_id": _string(payload, "expected_execution_attempt_id"),
        "expected_dispatch_envelope_id": _string(payload, "expected_dispatch_envelope_id"),
        "expected_running_projection_id": _string(payload, "expected_running_projection_id"),
        "captured_by": _string(payload, "captured_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_execution_delivery_id"].startswith("xack-"):
        raise MissionValidationError("expected_execution_delivery_id must be a canonical xack-* identifier")
    if not values["expected_execution_attempt_id"].startswith("xattempt-"):
        raise MissionValidationError("expected_execution_attempt_id must be a canonical xattempt-* identifier")
    if not values["expected_dispatch_envelope_id"].startswith("xenv-"):
        raise MissionValidationError("expected_dispatch_envelope_id must be a canonical xenv-* identifier")
    if not values["expected_running_projection_id"].startswith("xrun-"):
        raise MissionValidationError("expected_running_projection_id must be a canonical xrun-* identifier")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason not in (None, ""):
        if not isinstance(reason, str) or not reason.strip():
            raise MissionValidationError("reason must be a non-empty string when provided")
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    else:
        reason = None

    return {
        **values,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_execution_delivery_sha256": _sha(payload, "expected_execution_delivery_sha256"),
        "expected_execution_attempt_sha256": _sha(payload, "expected_execution_attempt_sha256"),
        "expected_running_projection_sha256": _sha(payload, "expected_running_projection_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def execution_result_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": EXECUTION_RESULT_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _runtime_string(response: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = response.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionSubsystemProtocolError(f"runtime execution-result {key} is missing or invalid")
    value = value.strip()
    if len(value) > max_len:
        raise MissionSubsystemProtocolError(f"runtime execution-result {key} exceeds {max_len} characters")
    return value


def _normalize_manifest_item(item: Any, *, kind: str, index: int) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] must be a JSON object")
    forbidden = sorted(set(item) & _FORBIDDEN_INLINE_FIELDS)
    if forbidden:
        raise MissionSubsystemProtocolError(
            f"runtime {kind}[{index}] contains forbidden inline payload field(s): " + ", ".join(forbidden)
        )
    item_id = _runtime_string(item, "evidence_id" if kind == "evidence" else "artifact_id")
    if not _ID_RE.match(item_id):
        raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] identifier contains unsupported characters")
    item_type = _runtime_string(item, "type", 120)
    uri = _runtime_string(item, "uri", 1000)
    digest = _runtime_string(item, "sha256", 64).lower()
    if not _SHA_RE.match(digest):
        raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] sha256 must be a lowercase SHA-256 hex digest")
    media_type = item.get("media_type")
    if media_type in (None, ""):
        media_type = None
    elif not isinstance(media_type, str) or not media_type.strip() or len(media_type.strip()) > 160:
        raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] media_type is invalid")
    else:
        media_type = media_type.strip()
    raw_size = item.get("size_bytes")
    size_bytes = None
    if raw_size is not None:
        if isinstance(raw_size, bool):
            raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] size_bytes must be an integer")
        try:
            size_bytes = int(raw_size)
        except (TypeError, ValueError) as exc:
            raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] size_bytes must be an integer") from exc
        if size_bytes < 0:
            raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] size_bytes must be >= 0")
    metadata = item.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionSubsystemProtocolError(f"runtime {kind}[{index}] metadata must be a JSON object")
    canonical_json(metadata)
    return {
        "id": item_id,
        "type": item_type,
        "uri": uri,
        "sha256": digest,
        "media_type": media_type,
        "size_bytes": size_bytes,
        "metadata": dict(metadata),
    }


def normalize_runtime_execution_result(
    response: Any,
    *,
    mission_id: str,
    execution_attempt_id: str,
    dispatch_envelope_id: str,
    subsystem_id: str,
) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise MissionSubsystemProtocolError("runtime execution-result response must be a JSON object")
    status = str(response.get("status") or "").strip().lower()
    if status not in {"ok", "completed", "result"}:
        raise MissionSubsystemProtocolError("runtime execution-result response did not indicate a terminal result")
    for key, expected in {
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
    }.items():
        if response.get(key) != expected:
            raise MissionSubsystemProtocolError(f"runtime execution-result {key} does not match Stage-3.5.4/3.5.5 binding")
    observed_by = _runtime_string(response, "observed_by")
    if observed_by != subsystem_id:
        raise MissionSubsystemProtocolError("runtime execution-result observed_by does not match target subsystem")
    execution_state = str(response.get("execution_state") or "").strip().upper()
    if execution_state not in TERMINAL_EXECUTION_STATES:
        raise MissionSubsystemProtocolError(
            "Stage-3.5.7 requires terminal execution_state in " + ", ".join(sorted(TERMINAL_EXECUTION_STATES))
        )
    if response.get("execution_started") is not True:
        raise MissionSubsystemProtocolError("Stage-3.5.7 requires execution_started=true")
    completed_at = _runtime_string(response, "completed_at", 80)
    summary = response.get("summary")
    if summary in (None, ""):
        summary = None
    elif not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 4000:
        raise MissionSubsystemProtocolError("runtime execution-result summary is invalid")
    else:
        summary = summary.strip()

    evidence_raw = response.get("evidence")
    if not isinstance(evidence_raw, list) or not evidence_raw:
        raise MissionSubsystemProtocolError("Stage-3.5.7 requires at least one authoritative evidence reference")
    artifact_raw = response.get("artifacts", [])
    if not isinstance(artifact_raw, list):
        raise MissionSubsystemProtocolError("runtime execution-result artifacts must be a JSON array")

    evidence = [_normalize_manifest_item(item, kind="evidence", index=i) for i, item in enumerate(evidence_raw)]
    artifacts = [_normalize_manifest_item(item, kind="artifacts", index=i) for i, item in enumerate(artifact_raw)]
    if len({x["id"] for x in evidence}) != len(evidence):
        raise MissionSubsystemProtocolError("runtime evidence identifiers must be unique")
    if len({x["id"] for x in artifacts}) != len(artifacts):
        raise MissionSubsystemProtocolError("runtime artifact identifiers must be unique")

    evidence_manifest_sha256 = sha256_hex({"items": evidence})
    artifact_manifest_sha256 = sha256_hex({"items": artifacts})
    normalized = {
        "status": status,
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
        "observed_by": observed_by,
        "execution_state": execution_state,
        "execution_started": True,
        "completed_at": completed_at,
        "summary": summary,
        "evidence": evidence,
        "evidence_manifest_sha256": evidence_manifest_sha256,
        "artifacts": artifacts,
        "artifact_manifest_sha256": artifact_manifest_sha256,
    }
    normalized["result_observation_sha256"] = sha256_hex(normalized)
    return normalized


def build_execution_result_capture_contract(
    *,
    result_capture_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    execution_attempt: Mapping[str, Any],
    execution_delivery: Mapping[str, Any],
    running_projection: Mapping[str, Any],
    runtime_health: Mapping[str, Any],
    runtime_result: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    if not verify_execution_attempt_contract(execution_attempt["execution_attempt_contract"]):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    if not verify_execution_delivery_contract(execution_delivery["execution_delivery_contract"]):
        raise MissionValidationError("Stage-3.5.5 execution-delivery contract failed integrity verification")
    if not verify_running_execution_projection_contract(running_projection["running_execution_projection_contract"]):
        raise MissionValidationError("Stage-3.5.6 running projection failed integrity verification")
    if running_projection["execution_state"] != RUNNING_EXECUTION_STATE:
        raise MissionValidationError("Stage-3.5.6 source projection is not RUNNING")
    if running_projection["execution_attempt_status"] != RUNNING_EXECUTION_ATTEMPT_STATUS:
        raise MissionValidationError("Stage-3.5.6 source attempt status is not RUNNING_HEARTBEAT_CONFIRMED")

    core = {
        "schema_version": EXECUTION_RESULT_SCHEMA_VERSION,
        "identity": {
            "result_capture_id": result_capture_id,
            "mission_id": mission_id,
            "running_projection_id": running_projection["running_projection_id"],
            "execution_delivery_id": execution_delivery["execution_delivery_id"],
            "execution_attempt_id": execution_attempt["execution_attempt_id"],
            "dispatch_envelope_id": execution_attempt["dispatch_envelope_id"],
            "execution_dispatch_id": execution_attempt["execution_dispatch_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": execution_attempt["planned_task_id"],
            "task_key": execution_attempt["task_key"],
        },
        "source_bindings": {
            "source_state": state["state"],
            "source_state_version": int(state["state_version"]),
            "source_version_sha256": version_vector["version_sha256"],
            "active_plan_sha256": active_plan["canonical_sha256"],
            "execution_attempt_sha256": execution_attempt["canonical_sha256"],
            "execution_delivery_sha256": execution_delivery["canonical_sha256"],
            "running_projection_sha256": running_projection["canonical_sha256"],
            "running_heartbeat_sequence": int(running_projection["heartbeat_sequence"]),
            "pre_dispatch_revalidation_id": execution_attempt["pre_dispatch_revalidation_id"],
            "policy_decision_id": execution_attempt["policy_decision_id"],
            "policy_decision_hash": execution_attempt["policy_decision_hash"],
            "policy_version": int(execution_attempt["policy_version"]),
        },
        "runtime_binding": {
            "subsystem_id": execution_delivery["recipient_subsystem_id"],
            "capability_id": execution_delivery["recipient_capability_id"],
            "runtime_endpoint": execution_delivery["runtime_endpoint"],
            "runtime_endpoint_reused_from_stage355": True,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": True,
            "runtime_health_status": runtime_health["status"],
            "runtime_health_sha256": sha256_hex(dict(runtime_health)),
            "result_channel": RUNTIME_RESULT_CHANNEL,
            "result_observation_sha256": runtime_result["result_observation_sha256"],
        },
        "terminal_result": {
            "execution_state": runtime_result["execution_state"],
            "execution_attempt_status": EXECUTION_RESULT_ATTEMPT_STATUS,
            "execution_started": True,
            "completed_at": runtime_result["completed_at"],
            "summary": runtime_result.get("summary"),
            "terminal_result_captured": True,
        },
        "evidence_manifest": {
            "required": True,
            "evidence_count": len(runtime_result["evidence"]),
            "manifest_sha256": runtime_result["evidence_manifest_sha256"],
            "items": list(runtime_result["evidence"]),
            "inline_payload_persisted": False,
        },
        "artifact_manifest": {
            "optional": True,
            "artifact_count": len(runtime_result["artifacts"]),
            "manifest_sha256": runtime_result["artifact_manifest_sha256"],
            "items": list(runtime_result["artifacts"]),
            "inline_payload_persisted": False,
        },
        "idempotency": {
            "idempotency_key": request["idempotency_key"],
            "request_sha256": request_sha256,
            "one_terminal_result_per_execution_attempt": True,
        },
        "semantics": {
            "mode": EXECUTION_RESULT_MODE,
            "authority": EXECUTION_RESULT_AUTHORITY,
            "requires_latest_stage356_running_projection": True,
            "runtime_endpoint_reused_from_stage355": True,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": True,
            "runtime_terminal_result_query_performed": True,
            "governance_query_performed": False,
            "dispatch_redelivery_performed": False,
            "target_action_dispatch_performed": False,
            "evidence_capture_performed": True,
            "artifact_capture_performed": bool(runtime_result["artifacts"]),
            "evidence_required": True,
            "artifact_optional": True,
            "inline_artifact_payload_persisted": False,
            "result_capture_is_not_task_completion_authority": True,
            "mission_state_transition_performed": False,
            "next_stage": "3.5.8",
        },
        "provenance": {
            "captured_by": request["captured_by"],
            "created_at": created_at,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
        },
    }
    digest = sha256_hex({"hash_domain": EXECUTION_RESULT_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_execution_result_capture_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        result = contract["terminal_result"]
        evidence = contract["evidence_manifest"]
        artifacts = contract["artifact_manifest"]
        semantics = contract["semantics"]
        return (
            contract["schema_version"] == EXECUTION_RESULT_SCHEMA_VERSION
            and str(identity["result_capture_id"]).startswith(EXECUTION_RESULT_ID_PREFIX)
            and str(identity["running_projection_id"]).startswith("xrun-")
            and str(identity["execution_delivery_id"]).startswith("xack-")
            and str(identity["execution_attempt_id"]).startswith("xattempt-")
            and str(identity["dispatch_envelope_id"]).startswith("xenv-")
            and result["execution_state"] in TERMINAL_EXECUTION_STATES
            and result["execution_attempt_status"] == EXECUTION_RESULT_ATTEMPT_STATUS
            and result["execution_started"] is True
            and result["terminal_result_captured"] is True
            and int(evidence["evidence_count"]) >= 1
            and evidence["required"] is True
            and evidence["inline_payload_persisted"] is False
            and int(artifacts["artifact_count"]) >= 0
            and artifacts["optional"] is True
            and artifacts["inline_payload_persisted"] is False
            and evidence["manifest_sha256"] == sha256_hex({"items": evidence["items"]})
            and artifacts["manifest_sha256"] == sha256_hex({"items": artifacts["items"]})
            and semantics["runtime_terminal_result_query_performed"] is True
            and semantics["governance_query_performed"] is False
            and semantics["dispatch_redelivery_performed"] is False
            and semantics["target_action_dispatch_performed"] is False
            and semantics["result_capture_is_not_task_completion_authority"] is True
            and semantics["mission_state_transition_performed"] is False
            and digest == sha256_hex({"hash_domain": EXECUTION_RESULT_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_execution_result_definition() -> Dict[str, Any]:
    return {
        "schema_version": EXECUTION_RESULT_SCHEMA_VERSION,
        "identity_prefix": EXECUTION_RESULT_ID_PREFIX,
        "mode": EXECUTION_RESULT_MODE,
        "authority": EXECUTION_RESULT_AUTHORITY,
        "allowed_source_states": sorted(EXECUTION_RESULT_ALLOWED_STATES),
        "terminal_execution_states": sorted(TERMINAL_EXECUTION_STATES),
        "execution_attempt_status": EXECUTION_RESULT_ATTEMPT_STATUS,
        "requires_latest_stage356_running_projection": True,
        "one_terminal_result_per_execution_attempt": True,
        "runtime_endpoint_reused_from_stage355": True,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": True,
        "runtime_terminal_result_query_performed": True,
        "governance_query_performed": False,
        "dispatch_redelivery_performed": False,
        "target_action_dispatch_performed": False,
        "evidence_required": True,
        "artifact_optional": True,
        "inline_artifact_payload_persisted": False,
        "result_capture_is_not_task_completion_authority": True,
        "mission_state_transition_performed": False,
        "next_stage": "3.5.8",
    }
