from __future__ import annotations

import ipaddress
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

from .errors import MissionValidationError

CONTRACT_SCHEMA_VERSION = "apts-mission-scope-roe-constraint-v1"
CONTRACT_HASH_DOMAIN = "MISSION_SCOPE_ROE_CONSTRAINT_CONTRACT_V1"
CONTRACT_ID_PREFIX = "mscope-"
SNAPSHOT_ID_PREFIX = "mscope-snap-"

ACTION_CLASSES = frozenset(
    {
        "INTERNAL_REASONING",
        "REPORTING",
        "CTI_SOURCE_READ",
        "TARGET_RECON",
        "TARGET_ENUMERATION",
        "VULNERABILITY_VALIDATION",
        "CONTROLLED_EXPLOITATION",
        "POST_EXPLOITATION",
        "CREDENTIAL_USE",
        "PRIVILEGE_ESCALATION",
        "LATERAL_MOVEMENT",
        "DATA_ACCESS",
        "DESTRUCTIVE_ACTION",
    }
)
RISK_LEVELS = frozenset({"LOW", "MODERATE", "HIGH", "CRITICAL"})
TARGET_TYPES = frozenset({"IP", "CIDR", "HOST", "DOMAIN", "URL", "APPLICATION", "OTHER"})
SERVICE_PROTOCOLS = frozenset({"TCP", "UDP", "HTTP", "HTTPS", "OTHER"})

_CONTRACT_FIELDS = {
    "expected_contract_version",
    "idempotency_key",
    "actor",
    "scope",
    "roe",
    "constraints",
    "reason",
    "metadata",
}
_SCOPE_FIELDS = {"targets", "excluded_targets", "network_ranges", "domains", "services"}
_ROE_FIELDS = {
    "allowed_action_classes",
    "prohibited_action_classes",
    "allowed_time_window",
    "maximum_concurrency",
    "destructive_actions_allowed",
    "credential_usage_allowed",
    "persistence_allowed",
    "human_approval_required_for",
}
_CONSTRAINT_FIELDS = {
    "max_actions",
    "max_duration",
    "risk_threshold",
    "resource_budget",
    "data_handling_policy",
}
_TARGET_FIELDS = {"target_type", "target_value", "environment", "metadata"}
_SERVICE_FIELDS = {"name", "protocol", "port", "target_ref", "metadata"}
_TIME_WINDOW_FIELDS = {"start_at", "end_at"}
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?))*\.?$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    import hashlib

    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_contract_id() -> str:
    return f"{CONTRACT_ID_PREFIX}{uuid.uuid4()}"


def new_snapshot_id() -> str:
    return f"{SNAPSHOT_ID_PREFIX}{uuid.uuid4()}"


def _unknown_fields(obj: Mapping[str, Any], allowed: set[str], key: str) -> None:
    unknown = sorted(set(obj.keys()) - allowed)
    if unknown:
        raise MissionValidationError(f"unsupported {key} field(s): {', '.join(unknown)}")


def _require_object(value: Any, key: str, *, allow_empty: bool = True) -> Dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    if not allow_empty and not value:
        raise MissionValidationError(f"{key} must not be empty")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def _require_string(obj: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 512) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _non_negative_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must be an integer") from exc
    if result < 0:
        raise MissionValidationError(f"{key} must be >= 0")
    return result


def _positive_int(value: Any, key: str) -> int:
    result = _non_negative_int(value, key)
    if result < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return result


def _normalize_action_classes(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError(f"{key} must be an array")
    out: list[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError(f"{key} entries must be non-empty strings")
        normalized = item.strip().upper()
        if normalized not in ACTION_CLASSES:
            raise MissionValidationError(f"{key} contains unsupported action class: {normalized}")
        if normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _normalize_target(item: Any, key: str) -> Dict[str, Any]:
    if isinstance(item, str):
        item = {"target_type": "OTHER", "target_value": item}
    if not isinstance(item, dict):
        raise MissionValidationError(f"{key} entries must be objects or strings")
    _unknown_fields(item, _TARGET_FIELDS, key)
    target_type = _require_string(item, "target_type", 32).upper()
    if target_type not in TARGET_TYPES:
        raise MissionValidationError(f"{key}.target_type must be one of: {', '.join(sorted(TARGET_TYPES))}")
    target_value = _require_string(item, "target_value", 1000)
    environment = _optional_string(item.get("environment"), f"{key}.environment", 64)
    metadata = _require_object(item.get("metadata"), f"{key}.metadata")

    if target_type == "IP":
        try:
            target_value = str(ipaddress.ip_address(target_value))
        except ValueError as exc:
            raise MissionValidationError(f"{key}.target_value is not a valid IP address") from exc
    elif target_type == "CIDR":
        try:
            target_value = str(ipaddress.ip_network(target_value, strict=False))
        except ValueError as exc:
            raise MissionValidationError(f"{key}.target_value is not a valid CIDR") from exc
    elif target_type == "DOMAIN":
        target_value = _normalize_domain(target_value, f"{key}.target_value")
    elif target_type == "URL":
        parsed = urlsplit(target_value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise MissionValidationError(f"{key}.target_value must be an absolute http/https URL")
        target_value = target_value.strip()

    return {
        "target_type": target_type,
        "target_value": target_value,
        "environment": environment.upper() if environment else None,
        "metadata": metadata,
    }


def _normalize_target_list(value: Any, key: str) -> list[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError(f"{key} must be an array")
    out: list[Dict[str, Any]] = []
    seen = set()
    for item in value:
        normalized = _normalize_target(item, key)
        signature = (normalized["target_type"], normalized["target_value"], normalized["environment"])
        if signature not in seen:
            out.append(normalized)
            seen.add(signature)
    return out


def _normalize_network_ranges(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError("scope.network_ranges must be an array")
    out: list[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError("scope.network_ranges entries must be non-empty CIDR strings")
        try:
            normalized = str(ipaddress.ip_network(item.strip(), strict=False))
        except ValueError as exc:
            raise MissionValidationError(f"scope.network_ranges contains invalid CIDR: {item}") from exc
        if normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _normalize_domain(value: str, key: str) -> str:
    value = value.strip().lower().rstrip(".")
    if not value or not _DOMAIN_RE.match(value):
        raise MissionValidationError(f"{key} is not a valid domain/host name")
    return value


def _normalize_domains(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError("scope.domains must be an array")
    out: list[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise MissionValidationError("scope.domains entries must be strings")
        normalized = _normalize_domain(item, "scope.domains entry")
        if normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out


def _normalize_services(value: Any) -> list[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError("scope.services must be an array")
    out: list[Dict[str, Any]] = []
    seen = set()
    for item in value:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            raise MissionValidationError("scope.services entries must be objects or strings")
        _unknown_fields(item, _SERVICE_FIELDS, "scope.services")
        name = _optional_string(item.get("name"), "scope.services.name", 128)
        protocol = _optional_string(item.get("protocol"), "scope.services.protocol", 16)
        protocol = (protocol or "OTHER").upper()
        if protocol not in SERVICE_PROTOCOLS:
            raise MissionValidationError(
                f"scope.services.protocol must be one of: {', '.join(sorted(SERVICE_PROTOCOLS))}"
            )
        port = item.get("port")
        if port is not None:
            port = _positive_int(port, "scope.services.port")
            if port > 65535:
                raise MissionValidationError("scope.services.port must be <= 65535")
        target_ref = _optional_string(item.get("target_ref"), "scope.services.target_ref", 256)
        metadata = _require_object(item.get("metadata"), "scope.services.metadata")
        if name is None and port is None:
            raise MissionValidationError("scope.services entry requires name or port")
        normalized = {
            "name": name,
            "protocol": protocol,
            "port": port,
            "target_ref": target_ref,
            "metadata": metadata,
        }
        signature = (name, protocol, port, target_ref)
        if signature not in seen:
            out.append(normalized)
            seen.add(signature)
    return out


def _parse_utc_timestamp(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be an ISO-8601 timestamp")
    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise MissionValidationError(f"{key} must be an ISO-8601 timestamp") from exc
    if dt.tzinfo is None:
        raise MissionValidationError(f"{key} must include a timezone offset or Z")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_time_window(value: Any) -> Optional[Dict[str, str]]:
    if value is None:
        return None
    obj = _require_object(value, "roe.allowed_time_window", allow_empty=False)
    _unknown_fields(obj, _TIME_WINDOW_FIELDS, "roe.allowed_time_window")
    start_at = _parse_utc_timestamp(obj.get("start_at"), "roe.allowed_time_window.start_at")
    end_at = _parse_utc_timestamp(obj.get("end_at"), "roe.allowed_time_window.end_at")
    start_dt = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
    if end_dt <= start_dt:
        raise MissionValidationError("roe.allowed_time_window.end_at must be later than start_at")
    return {"start_at": start_at, "end_at": end_at}


def _normalize_scope(value: Any) -> Dict[str, Any]:
    scope = _require_object(value, "scope", allow_empty=False)
    _unknown_fields(scope, _SCOPE_FIELDS, "scope")
    targets = _normalize_target_list(scope.get("targets"), "scope.targets")
    excluded_targets = _normalize_target_list(scope.get("excluded_targets"), "scope.excluded_targets")
    target_signatures = {(i["target_type"], i["target_value"], i["environment"]) for i in targets}
    excluded_signatures = {(i["target_type"], i["target_value"], i["environment"]) for i in excluded_targets}
    direct_conflicts = target_signatures & excluded_signatures
    if direct_conflicts:
        raise MissionValidationError("scope contains the same explicit target in targets and excluded_targets")
    return {
        "targets": targets,
        "excluded_targets": excluded_targets,
        "network_ranges": _normalize_network_ranges(scope.get("network_ranges")),
        "domains": _normalize_domains(scope.get("domains")),
        "services": _normalize_services(scope.get("services")),
    }


def _normalize_roe(value: Any) -> Dict[str, Any]:
    roe = _require_object(value, "roe", allow_empty=False)
    _unknown_fields(roe, _ROE_FIELDS, "roe")
    allowed = _normalize_action_classes(roe.get("allowed_action_classes"), "roe.allowed_action_classes")
    prohibited = _normalize_action_classes(roe.get("prohibited_action_classes"), "roe.prohibited_action_classes")
    overlap = sorted(set(allowed) & set(prohibited))
    if overlap:
        raise MissionValidationError("action classes cannot be both allowed and prohibited: " + ", ".join(overlap))

    approval = _normalize_action_classes(
        roe.get("human_approval_required_for"), "roe.human_approval_required_for"
    )
    not_allowed = sorted(set(approval) - set(allowed))
    if not_allowed:
        raise MissionValidationError(
            "roe.human_approval_required_for must be a subset of allowed_action_classes: " + ", ".join(not_allowed)
        )

    max_concurrency = _positive_int(roe.get("maximum_concurrency", 1), "roe.maximum_concurrency")
    if max_concurrency > 1024:
        raise MissionValidationError("roe.maximum_concurrency must be <= 1024")

    destructive = roe.get("destructive_actions_allowed", False)
    credential = roe.get("credential_usage_allowed", False)
    persistence = roe.get("persistence_allowed", False)
    for value_bool, key in (
        (destructive, "roe.destructive_actions_allowed"),
        (credential, "roe.credential_usage_allowed"),
        (persistence, "roe.persistence_allowed"),
    ):
        if not isinstance(value_bool, bool):
            raise MissionValidationError(f"{key} must be boolean")

    if not destructive and "DESTRUCTIVE_ACTION" in allowed:
        raise MissionValidationError(
            "DESTRUCTIVE_ACTION cannot be allowed when roe.destructive_actions_allowed is false"
        )
    if not credential and "CREDENTIAL_USE" in allowed:
        raise MissionValidationError(
            "CREDENTIAL_USE cannot be allowed when roe.credential_usage_allowed is false"
        )

    return {
        "allowed_action_classes": allowed,
        "prohibited_action_classes": prohibited,
        "allowed_time_window": _normalize_time_window(roe.get("allowed_time_window")),
        "maximum_concurrency": max_concurrency,
        "destructive_actions_allowed": destructive,
        "credential_usage_allowed": credential,
        "persistence_allowed": persistence,
        "human_approval_required_for": approval,
    }


def _normalize_constraints(value: Any) -> Dict[str, Any]:
    constraints = _require_object(value, "constraints", allow_empty=False)
    _unknown_fields(constraints, _CONSTRAINT_FIELDS, "constraints")
    max_actions = _positive_int(constraints.get("max_actions"), "constraints.max_actions")
    max_duration = _positive_int(constraints.get("max_duration"), "constraints.max_duration")
    risk_threshold = _require_string(constraints, "risk_threshold", 16).upper()
    if risk_threshold == "MEDIUM":
        risk_threshold = "MODERATE"
    if risk_threshold not in RISK_LEVELS:
        raise MissionValidationError(
            f"constraints.risk_threshold must be one of: {', '.join(sorted(RISK_LEVELS))}"
        )
    resource_budget = _require_object(constraints.get("resource_budget"), "constraints.resource_budget")
    data_handling_policy = _require_object(
        constraints.get("data_handling_policy"), "constraints.data_handling_policy", allow_empty=False
    )
    return {
        "max_actions": max_actions,
        "max_duration": max_duration,
        "risk_threshold": risk_threshold,
        "resource_budget": resource_budget,
        "data_handling_policy": data_handling_policy,
    }


def normalize_contract_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("request body must be a JSON object")
    _unknown_fields(payload, _CONTRACT_FIELDS, "scope contract")
    expected_version = _non_negative_int(payload.get("expected_contract_version"), "expected_contract_version")
    idempotency_key = _require_string(payload, "idempotency_key")
    actor = _require_string(payload, "actor")
    reason = _optional_string(payload.get("reason"), "reason", 2000)
    metadata = _require_object(payload.get("metadata"), "metadata")
    return {
        "expected_contract_version": expected_version,
        "idempotency_key": idempotency_key,
        "actor": actor,
        "scope": _normalize_scope(payload.get("scope")),
        "roe": _normalize_roe(payload.get("roe")),
        "constraints": _normalize_constraints(payload.get("constraints")),
        "reason": reason,
        "metadata": metadata,
    }


def request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": "MISSION_SCOPE_CONTRACT_REQUEST_V1", "request": dict(normalized)})


def build_contract(
    normalized: Mapping[str, Any],
    *,
    mission_id: str,
    contract_id: str,
    contract_version: int,
    snapshot_id: str,
    created_at: str,
) -> Dict[str, Any]:
    core = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "identity": {
            "mission_id": mission_id,
            "mission_scope_contract_id": contract_id,
            "contract_version": int(contract_version),
            "snapshot_id": snapshot_id,
        },
        "scope": normalized["scope"],
        "roe": normalized["roe"],
        "constraints": normalized["constraints"],
        "provenance": {
            "actor": normalized["actor"],
            "idempotency_key": normalized["idempotency_key"],
            "reason": normalized.get("reason"),
            "created_at": created_at,
        },
        "metadata": normalized["metadata"],
    }
    digest = sha256_hex({"hash_domain": CONTRACT_HASH_DOMAIN, "core": core})
    core["integrity"] = {
        "hash_domain": CONTRACT_HASH_DOMAIN,
        "canonicalization": "UTF8_SORTED_JSON_V1",
        "canonical_sha256": digest,
    }
    return core


def verify_contract(contract: Mapping[str, Any]) -> bool:
    copy = dict(contract)
    integrity = copy.pop("integrity", None)
    if not isinstance(integrity, dict):
        return False
    expected = integrity.get("canonical_sha256")
    if not isinstance(expected, str):
        return False
    actual = sha256_hex({"hash_domain": CONTRACT_HASH_DOMAIN, "core": copy})
    return actual == expected
