from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from typing import Any, Dict, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .errors import MissionSubsystemProtocolError, MissionSubsystemUnavailable, MissionValidationError
from .execution_attempt import (
    DISPATCH_COMMIT_STATUS,
    EXECUTION_ATTEMPT_STATUS,
    verify_execution_attempt_contract,
)

EXECUTION_DELIVERY_SCHEMA_VERSION = "apts-dispatch-delivery-execution-acknowledgement-v1"
EXECUTION_DELIVERY_HASH_DOMAIN = "MISSION_DISPATCH_DELIVERY_EXECUTION_ACKNOWLEDGEMENT_V1"
EXECUTION_DELIVERY_REQUEST_HASH_DOMAIN = "MISSION_DISPATCH_DELIVERY_EXECUTION_ACK_REQUEST_V1"
EXECUTION_DELIVERY_ID_PREFIX = "xack-"
EXECUTION_DELIVERY_MODE = "RUNTIME_DISPATCH_ENVELOPE_DELIVERY_WITH_EXECUTION_ACKNOWLEDGEMENT_PENDING_RUNNING"
EXECUTION_DELIVERY_AUTHORITY = "DOWNSTREAM_SUBSYSTEM_EXECUTION_INTAKE_ACKNOWLEDGEMENT"
EXECUTION_DELIVERY_ALLOWED_STATES = frozenset({"RUNNING"})
DELIVERY_STATUS = "DELIVERED_TO_RUNTIME"
ACKNOWLEDGEMENT_STATUS = "ACKNOWLEDGED_ACCEPTED_FOR_EXECUTION"
ACKNOWLEDGED_ATTEMPT_STATUS = "DELIVERED_ACKNOWLEDGED_PENDING_RUNNING"
DELIVERY_CHANNEL = "RUNTIME_SUBSYSTEM_EXECUTION_INTAKE"
REMOTE_ACCEPTED_STATUSES = frozenset({"accepted", "acknowledged"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_execution_attempt_id",
    "expected_execution_attempt_sha256",
    "expected_dispatch_envelope_id",
    "delivered_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_execution_delivery_id() -> str:
    return f"{EXECUTION_DELIVERY_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_execution_delivery_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("execution-delivery request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported execution delivery field(s): " + ", ".join(unknown)
            + "; Stage 3.5.5 derives runtime endpoint, health evidence, recipient identity, delivery payload, "
              "remote acknowledgement, execution-start state, and target-actuation state from authoritative sources. "
              "Caller-supplied runtime/delivery/acknowledgement/execution/actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_attempt_id": _string(payload, "expected_execution_attempt_id"),
        "expected_dispatch_envelope_id": _string(payload, "expected_dispatch_envelope_id"),
        "delivered_by": _string(payload, "delivered_by", 128),
    }
    for key in values:
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_execution_attempt_id"].startswith("xattempt-"):
        raise MissionValidationError("expected_execution_attempt_id must be a canonical xattempt-* identifier")
    if not values["expected_dispatch_envelope_id"].startswith("xenv-"):
        raise MissionValidationError("expected_dispatch_envelope_id must be a canonical xenv-* identifier")

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
        "expected_execution_attempt_sha256": _sha(payload, "expected_execution_attempt_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def execution_delivery_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": EXECUTION_DELIVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def normalize_runtime_health_response(response: Any, *, subsystem_id: str) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise MissionSubsystemProtocolError("runtime health response must be a JSON object")
    status = str(response.get("status") or "").strip().lower()
    if status not in {"ok", "healthy", "ready"}:
        raise MissionSubsystemUnavailable(f"runtime subsystem {subsystem_id} health is not ready")
    declared_subsystem = response.get("subsystem_id")
    if declared_subsystem not in (None, "", subsystem_id):
        raise MissionSubsystemProtocolError("runtime health subsystem_id does not match dispatch target")
    return {
        "status": status,
        "subsystem_id": subsystem_id,
        "component_id": None if response.get("component_id") in (None, "") else str(response.get("component_id")),
        "control_version": None if response.get("control_version") in (None, "") else str(response.get("control_version")),
    }


def build_runtime_dispatch_payload(*, mission_id: str, execution_attempt: Mapping[str, Any]) -> Dict[str, Any]:
    contract = execution_attempt["execution_attempt_contract"]
    if not verify_execution_attempt_contract(contract):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    envelope = contract["dispatch_envelope"]
    target = envelope["target"]
    return {
        "schema_version": "apts-runtime-execution-dispatch-envelope-v1",
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt["execution_attempt_id"],
        "dispatch_envelope_id": execution_attempt["dispatch_envelope_id"],
        "idempotency_key": execution_attempt["dispatch_envelope_id"],
        "execution_dispatch_id": execution_attempt["execution_dispatch_id"],
        "planned_task_id": execution_attempt["planned_task_id"],
        "task_key": execution_attempt["task_key"],
        "target": {
            "subsystem_id": target["subsystem_id"],
            "capability_id": target["capability_id"],
            "capability_version": int(target["capability_version"]),
        },
        "work_context": dict(envelope["work_context"]),
        "authorization": {
            "pre_dispatch_revalidation_id": execution_attempt["pre_dispatch_revalidation_id"],
            "policy_decision_id": execution_attempt["policy_decision_id"],
            "policy_decision_hash": execution_attempt["policy_decision_hash"],
            "policy_version": int(execution_attempt["policy_version"]),
            "execution_authorized": True,
        },
        "semantics": {
            "intake_only": True,
            "acknowledgement_required": True,
            "execution_start_is_separate": True,
            "target_actuation_requested": False,
        },
    }


def normalize_execution_acknowledgement(
    response: Any,
    *,
    mission_id: str,
    execution_attempt_id: str,
    dispatch_envelope_id: str,
    subsystem_id: str,
) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise MissionSubsystemProtocolError("execution delivery response must be a JSON object")
    status = str(response.get("status") or "").strip().lower()
    if status not in REMOTE_ACCEPTED_STATUSES:
        raise MissionSubsystemProtocolError("execution delivery response did not indicate accepted/acknowledged")
    bindings = {
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
    }
    for key, expected in bindings.items():
        if response.get(key) != expected:
            raise MissionSubsystemProtocolError(f"execution acknowledgement {key} does not match delivered envelope")
    acknowledgement_id = response.get("acknowledgement_id")
    if not isinstance(acknowledgement_id, str) or not acknowledgement_id.strip() or not _ID_RE.match(acknowledgement_id.strip()):
        raise MissionSubsystemProtocolError("execution acknowledgement_id is missing or invalid")
    ack_status = str(response.get("acknowledgement_status") or "").strip().upper()
    if ack_status != ACKNOWLEDGEMENT_STATUS:
        raise MissionSubsystemProtocolError("execution acknowledgement_status is not ACKNOWLEDGED_ACCEPTED_FOR_EXECUTION")
    acknowledged_by = str(response.get("acknowledged_by") or "").strip()
    if acknowledged_by != subsystem_id:
        raise MissionSubsystemProtocolError("execution acknowledgement acknowledged_by does not match target subsystem")
    if response.get("execution_started") is not False:
        raise MissionSubsystemProtocolError("Stage-3.5.5 acknowledgement must confirm execution_started=false")
    if response.get("target_actuation") is not False:
        raise MissionSubsystemProtocolError("Stage-3.5.5 acknowledgement must confirm target_actuation=false")
    normalized = {
        "status": status,
        "acknowledgement_id": acknowledgement_id.strip(),
        "acknowledgement_status": ACKNOWLEDGEMENT_STATUS,
        "acknowledged_by": acknowledged_by,
        "mission_id": mission_id,
        "execution_attempt_id": execution_attempt_id,
        "dispatch_envelope_id": dispatch_envelope_id,
        "execution_started": False,
        "target_actuation": False,
    }
    normalized["acknowledgement_sha256"] = sha256_hex(normalized)
    return normalized


def build_execution_delivery_contract(
    *,
    execution_delivery_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    execution_attempt: Mapping[str, Any],
    runtime_endpoint: str,
    runtime_health: Mapping[str, Any],
    acknowledgement: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    attempt_contract = execution_attempt["execution_attempt_contract"]
    if not verify_execution_attempt_contract(attempt_contract):
        raise MissionValidationError("Stage-3.5.4 execution-attempt contract failed integrity verification")
    if execution_attempt["dispatch_commit_status"] != DISPATCH_COMMIT_STATUS:
        raise MissionValidationError("Stage-3.5.4 dispatch commit is not COMMITTED_IDEMPOTENT_PENDING_DELIVERY")
    if execution_attempt["execution_attempt_status"] != EXECUTION_ATTEMPT_STATUS:
        raise MissionValidationError("Stage-3.5.4 execution attempt is not CREATED_NOT_DELIVERED")
    target = attempt_contract["dispatch_envelope"]["target"]
    runtime_health_sha256 = sha256_hex(dict(runtime_health))
    core = {
        "schema_version": EXECUTION_DELIVERY_SCHEMA_VERSION,
        "identity": {
            "execution_delivery_id": execution_delivery_id,
            "mission_id": mission_id,
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
            "pre_dispatch_revalidation_id": execution_attempt["pre_dispatch_revalidation_id"],
            "policy_decision_id": execution_attempt["policy_decision_id"],
            "policy_decision_hash": execution_attempt["policy_decision_hash"],
            "policy_version": int(execution_attempt["policy_version"]),
        },
        "runtime_binding": {
            "subsystem_id": target["subsystem_id"],
            "capability_id": target["capability_id"],
            "capability_version": int(target["capability_version"]),
            "runtime_endpoint": runtime_endpoint,
            "runtime_endpoint_resolution_performed": True,
            "runtime_health_probe_performed": True,
            "runtime_health_status": runtime_health["status"],
            "runtime_health_sha256": runtime_health_sha256,
        },
        "delivery": {
            "delivery_channel": DELIVERY_CHANNEL,
            "delivery_status": DELIVERY_STATUS,
            "target_delivery_performed": True,
            "external_target_network_io_performed": True,
            "remote_idempotency_key": execution_attempt["dispatch_envelope_id"],
            "dispatch_envelope_id": execution_attempt["dispatch_envelope_id"],
        },
        "acknowledgement": {
            "acknowledgement_status": ACKNOWLEDGEMENT_STATUS,
            "delivery_acknowledged": True,
            "acknowledgement_id": acknowledgement["acknowledgement_id"],
            "acknowledgement_sha256": acknowledgement["acknowledgement_sha256"],
            "acknowledged_by": acknowledgement["acknowledged_by"],
            "execution_started": False,
            "target_actuation": False,
        },
        "execution_attempt": {
            "execution_attempt_status": ACKNOWLEDGED_ATTEMPT_STATUS,
            "execution_authorized": True,
            "eligible_for_running_state": True,
            "execution_started": False,
        },
        "idempotency": {
            "idempotency_key": request["idempotency_key"],
            "request_sha256": request_sha256,
            "one_delivery_ack_per_execution_attempt": True,
            "remote_replay_key_is_dispatch_envelope_identity": True,
        },
        "semantics": {
            "mode": EXECUTION_DELIVERY_MODE,
            "requires_stage354_committed_execution_attempt": True,
            "requires_current_latest_stage353_allow": True,
            "authoritative_governance_query_performed": False,
            "runtime_endpoint_resolution_performed": True,
            "runtime_health_probe_performed": True,
            "target_delivery_performed": True,
            "delivery_acknowledgement_performed": True,
            "execution_start_acknowledged": True,
            "execution_started": False,
            "running_state_recorded": False,
            "heartbeat_recorded": False,
            "target_action_dispatch_performed": True,
            "target_actuation": False,
            "next_stage": "3.5.6",
        },
        "provenance": {
            "delivered_by": request["delivered_by"],
            "created_at": created_at,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
        },
    }
    digest = sha256_hex({"hash_domain": EXECUTION_DELIVERY_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_execution_delivery_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        semantics = contract["semantics"]
        return (
            contract["schema_version"] == EXECUTION_DELIVERY_SCHEMA_VERSION
            and str(identity["execution_delivery_id"]).startswith(EXECUTION_DELIVERY_ID_PREFIX)
            and str(identity["execution_attempt_id"]).startswith("xattempt-")
            and str(identity["dispatch_envelope_id"]).startswith("xenv-")
            and contract["delivery"]["delivery_status"] == DELIVERY_STATUS
            and contract["acknowledgement"]["acknowledgement_status"] == ACKNOWLEDGEMENT_STATUS
            and contract["execution_attempt"]["execution_attempt_status"] == ACKNOWLEDGED_ATTEMPT_STATUS
            and semantics["target_delivery_performed"] is True
            and semantics["delivery_acknowledgement_performed"] is True
            and semantics["execution_started"] is False
            and semantics["target_actuation"] is False
            and digest == sha256_hex({"hash_domain": EXECUTION_DELIVERY_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_execution_delivery_definition() -> Dict[str, Any]:
    return {
        "schema_version": EXECUTION_DELIVERY_SCHEMA_VERSION,
        "identity_prefix": EXECUTION_DELIVERY_ID_PREFIX,
        "mode": EXECUTION_DELIVERY_MODE,
        "authority": EXECUTION_DELIVERY_AUTHORITY,
        "allowed_source_states": sorted(EXECUTION_DELIVERY_ALLOWED_STATES),
        "requires_stage354_committed_execution_attempt": True,
        "requires_current_latest_stage353_allow": True,
        "one_delivery_ack_per_execution_attempt": True,
        "remote_replay_key_is_dispatch_envelope_identity": True,
        "governance_query_performed": False,
        "runtime_endpoint_resolution_performed": True,
        "runtime_health_probe_performed": True,
        "target_delivery_performed": True,
        "delivery_acknowledgement_performed": True,
        "execution_start_acknowledged": True,
        "execution_started": False,
        "running_state_recorded": False,
        "heartbeat_recorded": False,
        "target_action_dispatch_performed": True,
        "target_actuation": False,
        "next_stage": "3.5.6",
    }


class ExecutionDeliveryClient:
    """Fail-closed runtime adapter used by Stage 3.5.5.

    Canonical subsystem identity is resolved to a deployment endpoint only at this stage.
    Delivery uses the immutable xenv-* identity as the remote idempotency key, allowing
    response-loss retries without creating a second downstream intake record.
    """

    def __init__(self, timeout_seconds: Optional[float] = None):
        self.timeout_seconds = float(timeout_seconds or os.getenv("MISSION_EXECUTION_DELIVERY_TIMEOUT_SECONDS", "5.0"))

    def resolve_endpoint(self, subsystem_id: str) -> str:
        subsystem = str(subsystem_id or "").upper()
        if subsystem == "CTI":
            value = os.getenv("MISSION_CTI_EXECUTION_BASE_URL") or os.getenv("MISSION_CTI_BASE_URL") or "http://127.0.0.1:8765"
        elif subsystem == "PENTEST":
            value = os.getenv("MISSION_PENTEST_EXECUTION_BASE_URL") or os.getenv("MISSION_PENTEST_BASE_URL") or "http://127.0.0.1:8790"
        else:
            raise MissionSubsystemUnavailable(f"no runtime endpoint resolver for subsystem {subsystem_id}")
        value = value.strip().rstrip("/")
        if not (value.startswith("http://") or value.startswith("https://")):
            raise MissionSubsystemUnavailable(f"runtime endpoint for subsystem {subsystem_id} is not an HTTP(S) URL")
        return value

    def _request(self, method: str, url: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        body = None if payload is None else canonical_json(dict(payload)).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MissionSubsystemUnavailable(f"execution runtime HTTP {exc.code}: {detail[:500]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MissionSubsystemUnavailable(f"execution runtime unavailable: {exc}") from exc
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise MissionSubsystemProtocolError("execution runtime response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise MissionSubsystemProtocolError("execution runtime response must be a JSON object")
        return data

    def health(self, subsystem_id: str, endpoint: str) -> Dict[str, Any]:
        return self._request("GET", f"{endpoint}/health")

    def deliver(self, subsystem_id: str, endpoint: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        path = os.getenv("MISSION_EXECUTION_DISPATCH_PATH", "/api/execution/dispatches")
        if not path.startswith("/"):
            path = "/" + path
        return self._request("POST", f"{endpoint}{path}", payload)

    def execution_status(
        self,
        subsystem_id: str,
        endpoint: str,
        *,
        mission_id: str,
        execution_attempt_id: str,
        dispatch_envelope_id: str,
    ) -> Dict[str, Any]:
        template = os.getenv(
            "MISSION_EXECUTION_STATUS_PATH_TEMPLATE",
            "/api/execution/attempts/{execution_attempt_id}/status",
        )
        try:
            path = template.format(execution_attempt_id=quote(execution_attempt_id, safe=""))
        except (KeyError, ValueError) as exc:
            raise MissionSubsystemUnavailable("MISSION_EXECUTION_STATUS_PATH_TEMPLATE is invalid") from exc
        if not path.startswith("/"):
            path = "/" + path
        separator = "&" if "?" in path else "?"
        query = (
            f"mission_id={quote(mission_id, safe='')}"
            f"&dispatch_envelope_id={quote(dispatch_envelope_id, safe='')}"
        )
        return self._request("GET", f"{endpoint}{path}{separator}{query}")

    def execution_control(
        self,
        subsystem_id: str,
        endpoint: str,
        *,
        mission_id: str,
        execution_attempt_id: str,
        dispatch_envelope_id: str,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        template = os.getenv(
            "MISSION_EXECUTION_CONTROL_PATH_TEMPLATE",
            "/api/execution/attempts/{execution_attempt_id}/control",
        )
        try:
            path = template.format(execution_attempt_id=quote(execution_attempt_id, safe=""))
        except (KeyError, ValueError) as exc:
            raise MissionSubsystemUnavailable("MISSION_EXECUTION_CONTROL_PATH_TEMPLATE is invalid") from exc
        if not path.startswith("/"):
            path = "/" + path
        control_payload = dict(payload)
        control_payload.setdefault("mission_id", mission_id)
        control_payload.setdefault("execution_attempt_id", execution_attempt_id)
        control_payload.setdefault("dispatch_envelope_id", dispatch_envelope_id)
        return self._request("POST", f"{endpoint}{path}", control_payload)

    def execution_result(
        self,
        subsystem_id: str,
        endpoint: str,
        *,
        mission_id: str,
        execution_attempt_id: str,
        dispatch_envelope_id: str,
    ) -> Dict[str, Any]:
        template = os.getenv(
            "MISSION_EXECUTION_RESULT_PATH_TEMPLATE",
            "/api/execution/attempts/{execution_attempt_id}/result",
        )
        try:
            path = template.format(execution_attempt_id=quote(execution_attempt_id, safe=""))
        except (KeyError, ValueError) as exc:
            raise MissionSubsystemUnavailable("MISSION_EXECUTION_RESULT_PATH_TEMPLATE is invalid") from exc
        if not path.startswith("/"):
            path = "/" + path
        separator = "&" if "?" in path else "?"
        query = (
            f"mission_id={quote(mission_id, safe='')}"
            f"&dispatch_envelope_id={quote(dispatch_envelope_id, safe='')}"
        )
        return self._request("GET", f"{endpoint}{path}{separator}{query}")
