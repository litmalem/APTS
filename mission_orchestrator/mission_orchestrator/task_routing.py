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

TASK_SCHEMA_VERSION = "apts-governed-task-routing-v1"
TASK_HASH_DOMAIN = "MISSION_GOVERNED_TASK_ROUTING_V1"
TASK_ID_PREFIX = "mtask-"
DISPATCH_ATTEMPT_ID_PREFIX = "mdispatch-"

INTERNAL_ROUTABLE_ACTIONS = frozenset({"INTERNAL_REASONING", "REPORTING"})
SUPPORTED_SUBSYSTEMS = frozenset({"CTI"})
ROUTABLE_MISSION_STATES = frozenset({"PLANNING", "RUNNING", "REPLANNING"})
DISPATCHABLE_MISSION_STATES = frozenset({"RUNNING", "REPLANNING"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_TASK_FIELDS = {
    "idempotency_key",
    "capability_id",
    "task_input",
    "requested_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


def new_task_id() -> str:
    return _new(TASK_ID_PREFIX)


def new_dispatch_attempt_id() -> str:
    return _new(DISPATCH_ATTEMPT_ID_PREFIX)


def _require_string(obj: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _object(value: Any, key: str) -> Dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def normalize_task_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("governed task request body must be a JSON object")
    unknown = sorted(set(payload) - _TASK_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported governed task field(s): " + ", ".join(unknown) + "; put extensions under metadata"
        )
    idempotency_key = _require_string(payload, "idempotency_key")
    capability_id = _require_string(payload, "capability_id")
    if not _ID_RE.match(capability_id):
        raise MissionValidationError("capability_id contains unsupported characters")
    requested_by = _require_string(payload, "requested_by")
    task_input = _object(payload.get("task_input"), "task_input")
    metadata = _object(payload.get("metadata"), "metadata")
    reason = payload.get("reason")
    if reason not in (None, ""):
        if not isinstance(reason, str):
            raise MissionValidationError("reason must be a string when provided")
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    else:
        reason = None
    return {
        "idempotency_key": idempotency_key,
        "capability_id": capability_id,
        "task_input": task_input,
        "requested_by": requested_by,
        "reason": reason,
        "metadata": metadata,
    }


def route_for_subject(subject_component: str) -> Dict[str, str]:
    subject = str(subject_component or "").strip().upper()
    if subject.startswith("CTI-"):
        return {
            "destination_subsystem": "CTI",
            "destination_component": subject,
            "transport": "HTTP",
            "dispatch_operation": "CTI_MISSION_START",
            "dispatch_path": "/api/cti/missions/start",
            "status_path_template": "/api/cti/missions/{mission_id}",
            "lineage_path_template": "/api/cti/missions/{mission_id}/lineage",
        }
    raise MissionValidationError(
        f"no governed Stage-3.1.5 subsystem route is registered for subject_component={subject_component}"
    )


def task_request_fingerprint(
    normalized: Mapping[str, Any],
    *,
    governance_binding_version: int,
    scope_snapshot_id: str,
    capability: Mapping[str, Any],
    route: Mapping[str, Any],
) -> str:
    return sha256_hex(
        {
            "hash_domain": "MISSION_GOVERNED_TASK_REQUEST_V1",
            "request": dict(normalized),
            "governance_binding_version": int(governance_binding_version),
            "scope_snapshot_id": scope_snapshot_id,
            "capability": dict(capability),
            "route": dict(route),
        }
    )


def build_task_contract(
    *,
    task_id: str,
    mission_id: str,
    governance_binding: Mapping[str, Any],
    scope_contract: Mapping[str, Any],
    capability: Mapping[str, Any],
    route: Mapping[str, Any],
    request: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    binding = governance_binding["binding"]
    core = {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "mission_id": mission_id,
        "task_kind": "SUBSYSTEM_MISSION_ROUTING",
        "canonical_scope_binding": {
            "mission_scope_contract_id": scope_contract["mission_scope_contract_id"],
            "mission_scope_snapshot_id": scope_contract["snapshot_id"],
            "mission_scope_version": scope_contract["contract_version"],
            "mission_scope_sha256": scope_contract["canonical_sha256"],
        },
        "governance_binding": {
            "mission_governance_binding_id": binding["identity"]["mission_governance_binding_id"],
            "governance_binding_version": binding["identity"]["binding_version"],
            "binding_snapshot_id": governance_binding["binding_snapshot_id"],
            "binding_canonical_sha256": governance_binding["canonical_sha256"],
            "governance_authority": binding["governance_authority"]["authorization_authority"],
            "governance_authority_component": binding["governance_authority"]["authorization_authority_component"],
        },
        "capability": dict(capability),
        "routing": dict(route),
        "task_input": dict(request["task_input"]),
        "semantics": {
            "routing_authority": "APTS-MO01",
            "authorization_mode": capability["authorization_mode"],
            "target_execution_authority": "DOWNSTREAM_SUBSYSTEM_PLUS_APTS_GSS",
            "target_action_dispatch": False,
            "target_actuation": False,
            "downstream_governance_revalidation_required_for_target_actions": True,
            "destination_is_derived_from_bound_subject_component": True,
            "fail_closed": True,
        },
        "requested_by": request["requested_by"],
        "reason": request.get("reason"),
        "metadata": dict(request.get("metadata") or {}),
        "created_at": created_at,
    }
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": TASK_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": sha256_hex(core),
        },
    }


def verify_task_contract(contract: Mapping[str, Any]) -> bool:
    try:
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        return (
            integrity.get("hash_domain") == TASK_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex(core)
        )
    except Exception:
        return False


def build_cti_dispatch_payload(task_contract: Mapping[str, Any]) -> Dict[str, Any]:
    payload = dict(task_contract.get("task_input") or {})
    # Reserved lineage fields are always overwritten from the immutable task contract.
    payload["mission_id"] = task_contract["mission_id"]
    payload["global_task_id"] = task_contract["task_id"]
    payload["mission_orchestrator_routing"] = {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_id": task_contract["task_id"],
        "task_contract_sha256": task_contract["integrity"]["canonical_sha256"],
        "scope_snapshot_id": task_contract["canonical_scope_binding"]["mission_scope_snapshot_id"],
        "scope_sha256": task_contract["canonical_scope_binding"]["mission_scope_sha256"],
        "governance_binding_version": task_contract["governance_binding"]["governance_binding_version"],
        "capability_id": task_contract["capability"]["capability_id"],
        "source_component": "APTS-MO01",
    }
    return payload


class CtiSubsystemClient:
    """Fail-closed adapter for the existing VulnDesk CTI runtime."""

    def __init__(self, base_url: Optional[str] = None, timeout_seconds: Optional[float] = None):
        self.base_url = (base_url or os.getenv("MISSION_CTI_BASE_URL", "http://127.0.0.1:8765")).rstrip("/")
        self.timeout_seconds = float(timeout_seconds or os.getenv("MISSION_CTI_TIMEOUT_SECONDS", "5.0"))

    def _request(self, method: str, path: str, payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = None if payload is None else canonical_json(dict(payload)).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MissionSubsystemUnavailable(f"CTI HTTP {exc.code}: {detail[:500]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise MissionSubsystemUnavailable(f"CTI subsystem unavailable: {exc}") from exc
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise MissionSubsystemProtocolError("CTI response is not valid JSON") from exc
        if not isinstance(data, dict):
            raise MissionSubsystemProtocolError("CTI response must be a JSON object")
        return data

    def get_pip(self, pip_id: str) -> Dict[str, Any]:
        response = self._request("GET", f"/api/cti/pip/{quote(pip_id, safe='')}")
        if response.get("status") != "completed" or not isinstance(response.get("pip"), dict):
            raise MissionSubsystemProtocolError("CTI PIP response is malformed")
        return response["pip"]

    def build_pip(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        response = self._request("POST", "/api/cti/pip/build", payload)
        if response.get("status") != "completed" or not isinstance(response.get("pip"), dict):
            raise MissionSubsystemProtocolError("CTI did not publish a PIP")
        return response

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def start_mission(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        response = self._request("POST", "/api/cti/missions/start", payload)
        if response.get("status") not in {"accepted", "completed"}:
            raise MissionSubsystemProtocolError("CTI mission-start response did not indicate accepted/completed")
        if not response.get("mission_id"):
            raise MissionSubsystemProtocolError("CTI mission-start response is missing mission_id")
        return response

    def get_mission(self, mission_id: str) -> Dict[str, Any]:
        response = self._request("GET", f"/api/cti/missions/{quote(mission_id, safe='')}")
        if response.get("status") != "completed" or not isinstance(response.get("mission"), dict):
            raise MissionSubsystemProtocolError("CTI mission-status response envelope is malformed")
        return dict(response["mission"])

    def get_lineage(self, mission_id: str) -> Dict[str, Any]:
        response = self._request("GET", f"/api/cti/missions/{quote(mission_id, safe='')}/lineage")
        if response.get("status") != "completed" or not isinstance(response.get("lineage"), dict):
            raise MissionSubsystemProtocolError("CTI mission-lineage response envelope is malformed")
        return dict(response["lineage"])
