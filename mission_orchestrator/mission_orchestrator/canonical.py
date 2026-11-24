from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from .errors import MissionValidationError

SCHEMA_VERSION = "apts-global-mission-envelope-v1"
CANONICALIZATION = "UTF8_SORTED_JSON_V1"
HASH_DOMAIN = "MISSION_ENVELOPE_CORE_V1"
MISSION_ID_PREFIX = "mission-gmo-"
ENVELOPE_ID_PREFIX = "menv-"
CORRELATION_ID_PREFIX = "corr-"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")

_TOP_LEVEL_FIELDS = {
    "idempotency_key",
    "source_system",
    "created_by",
    "client_request_id",
    "client_mission_ref",
    "mission_kind",
    "objective",
    "success_criteria",
    "budgets",
    "required_subsystems",
    "scope_binding",
    "pip_binding",
    "governance_binding",
    "parent_mission_id",
    "correlation_id",
    "metadata",
    # Compatibility aliases used by current Stage-2 services/scripts.
    "scope_contract_id",
    "scope_version",
    "scope_snapshot_id",
    "roe_version",
    "pip_id",
    "pip_version",
    "policy_version",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def new_mission_id() -> str:
    return f"{MISSION_ID_PREFIX}{uuid.uuid4()}"


def new_envelope_id() -> str:
    return f"{ENVELOPE_ID_PREFIX}{uuid.uuid4()}"


def new_correlation_id() -> str:
    return f"{CORRELATION_ID_PREFIX}{uuid.uuid4()}"


def canonical_json(value: Any) -> str:
    """Canonical JSON used by Stage 3.1.1 hash domains.

    This is intentionally named UTF8_SORTED_JSON_V1 rather than RFC 8785/JCS.
    Numbers are therefore constrained to ordinary JSON-compatible input and the
    implementation contract is exactly json.dumps(sort_keys=True, compact UTF-8).
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_string(obj: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_identifier(value: Any, key: str) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise MissionValidationError(f"{key} must be a string when provided")
    value = value.strip()
    if not _ID_RE.match(value):
        raise MissionValidationError(f"{key} contains unsupported characters or is too long")
    return value


def _normalize_string_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError(f"{key} must be an array")
    normalized: list[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError(f"{key} entries must be non-empty strings")
        item = item.strip()
        if len(item) > 128:
            raise MissionValidationError(f"{key} entry exceeds 128 characters")
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _require_json_object(value: Any, key: str, *, allow_empty: bool = True) -> Dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise MissionValidationError(f"{key} must be a JSON object")
    if not allow_empty and not value:
        raise MissionValidationError(f"{key} must not be empty")
    # Force serialization here so NaN/Infinity and non-JSON Python objects fail early.
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} must contain JSON-serializable values") from exc
    return dict(value)


def _normalize_scope_binding(payload: Mapping[str, Any]) -> Dict[str, Any]:
    scope = _require_json_object(payload.get("scope_binding"), "scope_binding")
    scope_contract_id = scope.get("scope_contract_id", payload.get("scope_contract_id"))
    scope_version = scope.get("scope_version", payload.get("scope_version"))
    scope_snapshot_id = scope.get("scope_snapshot_id", payload.get("scope_snapshot_id"))
    roe_version = scope.get("roe_version", payload.get("roe_version"))

    if scope_contract_id is not None:
        scope_contract_id = _optional_identifier(scope_contract_id, "scope_contract_id")
    if scope_snapshot_id is not None:
        scope_snapshot_id = _optional_identifier(scope_snapshot_id, "scope_snapshot_id")
    if roe_version is not None:
        roe_version = _optional_identifier(str(roe_version), "roe_version")

    if scope_version is not None:
        try:
            scope_version = int(scope_version)
        except (TypeError, ValueError) as exc:
            raise MissionValidationError("scope_version must be an integer") from exc
        if scope_version < 1:
            raise MissionValidationError("scope_version must be >= 1")

    # Current aptsGSS exposes scope_contract_id + scope_version. Until a separate
    # immutable snapshot id exists, Stage 3.1.1 canonicalizes that pair explicitly.
    if scope_snapshot_id is None and scope_contract_id and scope_version:
        scope_snapshot_id = f"{scope_contract_id}@v{scope_version}"

    return {
        "scope_contract_id": scope_contract_id,
        "scope_version": scope_version,
        "scope_snapshot_id": scope_snapshot_id,
        "roe_version": roe_version,
    }


def _normalize_pip_binding(payload: Mapping[str, Any]) -> Dict[str, Any]:
    pip = _require_json_object(payload.get("pip_binding"), "pip_binding")
    pip_id = pip.get("pip_id", payload.get("pip_id"))
    pip_version = pip.get("pip_version", payload.get("pip_version"))
    return {
        "pip_id": _optional_identifier(pip_id, "pip_id") if pip_id is not None else None,
        "pip_version": _optional_identifier(str(pip_version), "pip_version") if pip_version is not None else None,
    }


def _normalize_governance_binding(payload: Mapping[str, Any]) -> Dict[str, Any]:
    gov = _require_json_object(payload.get("governance_binding"), "governance_binding")
    policy_version = gov.get("policy_version", payload.get("policy_version"))
    authority = gov.get("authority", "aptsGSS")
    authority_component = gov.get("authority_component", "GOV-PLANE")
    return {
        "policy_version": _optional_identifier(str(policy_version), "policy_version") if policy_version is not None else None,
        "authority": _optional_identifier(str(authority), "governance_binding.authority") if authority is not None else None,
        "authority_component": _optional_identifier(str(authority_component), "governance_binding.authority_component") if authority_component is not None else None,
    }


def normalize_create_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("request body must be a JSON object")

    unknown = sorted(set(payload.keys()) - _TOP_LEVEL_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported top-level field(s): " + ", ".join(unknown) + "; put extensions under metadata"
        )

    idempotency_key = _require_string(payload, "idempotency_key")
    source_system = _require_string(payload, "source_system", 64)
    created_by = _require_string(payload, "created_by")
    mission_kind = _require_string(payload, "mission_kind", 64).upper()

    objective = _require_json_object(payload.get("objective"), "objective", allow_empty=False)
    success_criteria = payload.get("success_criteria", [])
    if not isinstance(success_criteria, list):
        raise MissionValidationError("success_criteria must be an array")
    try:
        canonical_json(success_criteria)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("success_criteria must contain JSON-serializable values") from exc

    budgets = _require_json_object(payload.get("budgets"), "budgets")
    metadata = _require_json_object(payload.get("metadata"), "metadata")
    required_subsystems = [s.upper() for s in _normalize_string_list(payload.get("required_subsystems"), "required_subsystems")]

    client_request_id = payload.get("client_request_id")
    client_mission_ref = payload.get("client_mission_ref")
    parent_mission_id = payload.get("parent_mission_id")
    correlation_id = payload.get("correlation_id")

    normalized = {
        "idempotency_key": idempotency_key,
        "source_system": source_system,
        "created_by": created_by,
        "client_request_id": _optional_identifier(client_request_id, "client_request_id") if client_request_id is not None else None,
        "client_mission_ref": _optional_identifier(client_mission_ref, "client_mission_ref") if client_mission_ref is not None else None,
        "mission_kind": mission_kind,
        "objective": objective,
        "success_criteria": success_criteria,
        "budgets": budgets,
        "required_subsystems": required_subsystems,
        "scope_binding": _normalize_scope_binding(payload),
        "pip_binding": _normalize_pip_binding(payload),
        "governance_binding": _normalize_governance_binding(payload),
        "parent_mission_id": _optional_identifier(parent_mission_id, "parent_mission_id") if parent_mission_id is not None else None,
        "correlation_id": _optional_identifier(correlation_id, "correlation_id") if correlation_id is not None else None,
        "metadata": metadata,
    }
    return normalized


def request_fingerprint(normalized: Mapping[str, Any]) -> str:
    # correlation_id is intentionally part of the request only when explicitly supplied.
    # If absent, it remains None in the normalized request, making retry fingerprints stable.
    return sha256_hex({"hash_domain": "MISSION_CREATE_REQUEST_V1", "request": dict(normalized)})


def build_envelope_core(
    normalized: Mapping[str, Any],
    *,
    mission_id: str,
    envelope_id: str,
    correlation_id: str,
    created_at: str,
    envelope_version: int = 1,
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "mission_id": mission_id,
            "envelope_id": envelope_id,
            "envelope_version": envelope_version,
            "correlation_id": correlation_id,
            "parent_mission_id": normalized.get("parent_mission_id"),
        },
        "provenance": {
            "source_system": normalized["source_system"],
            "created_by": normalized["created_by"],
            "client_request_id": normalized.get("client_request_id"),
            "client_mission_ref": normalized.get("client_mission_ref"),
            "idempotency_key": normalized["idempotency_key"],
            "created_at": created_at,
        },
        "mission": {
            "mission_kind": normalized["mission_kind"],
            "objective": normalized["objective"],
            "success_criteria": normalized["success_criteria"],
            "budgets": normalized["budgets"],
            "required_subsystems": normalized["required_subsystems"],
        },
        "bindings": {
            "scope": normalized["scope_binding"],
            "pip": normalized["pip_binding"],
            "governance": normalized["governance_binding"],
        },
        "metadata": normalized["metadata"],
    }


def build_envelope(core: Mapping[str, Any]) -> Dict[str, Any]:
    core_copy = json.loads(canonical_json(core))
    digest = sha256_hex({"hash_domain": HASH_DOMAIN, "core": core_copy})
    core_copy["integrity"] = {
        "hash_domain": HASH_DOMAIN,
        "canonicalization": CANONICALIZATION,
        "canonical_sha256": digest,
    }
    return core_copy


def verify_envelope(envelope: Mapping[str, Any]) -> bool:
    envelope_copy = dict(envelope)
    integrity = envelope_copy.pop("integrity", None)
    if not isinstance(integrity, dict):
        return False
    expected = integrity.get("canonical_sha256")
    if not isinstance(expected, str):
        return False
    actual = sha256_hex({"hash_domain": HASH_DOMAIN, "core": envelope_copy})
    return actual == expected
