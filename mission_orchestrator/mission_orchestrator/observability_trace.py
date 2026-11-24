from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

OBSERVABILITY_TRACE_SCHEMA_VERSION = "apts-canonical-observability-trace-identity-v1"
OBSERVABILITY_TRACE_CONTEXT_SCHEMA_VERSION = "apts-observability-trace-context-v1"
OBSERVABILITY_TRACE_HASH_DOMAIN = "MISSION_CANONICAL_OBSERVABILITY_TRACE_IDENTITY_V1"
OBSERVABILITY_TRACE_MODE = (
    "DETERMINISTIC_IMMUTABLE_MISSION_ROOT_TRACE_IDENTITY_FROM_CANONICAL_MISSION_ENVELOPE_"
    "READ_ONLY_NO_TELEMETRY_EXPORT_NO_RUNTIME_MUTATION"
)
OBSERVABILITY_TRACE_AUTHORITY = "MISSION_ORCHESTRATOR_CANONICAL_TRACE_IDENTITY"
OBSERVABILITY_TRACE_IDENTITY_ALGORITHM = "SHA256_DOMAIN_SEPARATED_TRUNCATION"
OBSERVABILITY_TRACE_ID_FORMAT = "W3C_TRACE_ID_COMPATIBLE_32_LOWERCASE_HEX"
OBSERVABILITY_ROOT_SPAN_ID_FORMAT = "W3C_SPAN_ID_COMPATIBLE_16_LOWERCASE_HEX"
OBSERVABILITY_TRACE_FLAGS_DEFAULT = "00"
OBSERVABILITY_TRACE_STATE_DEFAULT = ""
OBSERVABILITY_TRACE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
OBSERVABILITY_TRACE_PERSISTENCE_MODE = "DERIVED_FROM_EXISTING_DURABLE_CANONICAL_MISSION_ENVELOPE"
OBSERVABILITY_TRACE_EXPORT_MODE = "DISABLED_STAGE_3_8_1"

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _derive_hex(label: str, mission_id: str, envelope_sha256: str, width: int) -> str:
    digest = sha256_hex({
        "hash_domain": OBSERVABILITY_TRACE_HASH_DOMAIN,
        "label": label,
        "mission_id": mission_id,
        "envelope_sha256": envelope_sha256,
    })
    value = digest[:width]
    # W3C trace/span ids cannot be all zero. SHA-256 makes this practically impossible,
    # but retain an explicit deterministic guard so the contract is total.
    if set(value) == {"0"}:
        value = ("1" + value[1:])
    return value


def derive_trace_id(mission_id: str, envelope_sha256: str) -> str:
    return _derive_hex("MISSION_ROOT_TRACE", mission_id, envelope_sha256, 32)


def derive_root_span_id(mission_id: str, envelope_sha256: str) -> str:
    return _derive_hex("MISSION_ROOT_SPAN", mission_id, envelope_sha256, 16)


def build_observability_trace_identity_contract(*, identity: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    mission_id = str(identity["mission_id"])
    envelope_id = str(identity["envelope_id"])
    envelope_version = int(identity["envelope_version"])
    correlation_id = str(identity["correlation_id"])
    envelope_sha256 = str(envelope["integrity"]["canonical_sha256"]).lower()
    if not _HEX64.match(envelope_sha256):
        raise ValueError("canonical mission envelope hash must be a lowercase SHA-256 digest")

    trace_id = derive_trace_id(mission_id, envelope_sha256)
    root_span_id = derive_root_span_id(mission_id, envelope_sha256)
    core = {
        "schema_version": OBSERVABILITY_TRACE_SCHEMA_VERSION,
        "mode": OBSERVABILITY_TRACE_MODE,
        "authority": OBSERVABILITY_TRACE_AUTHORITY,
        "identity": {
            "mission_id": mission_id,
            "trace_id": trace_id,
            "root_span_id": root_span_id,
            "correlation_id": correlation_id,
        },
        "source_bindings": {
            "envelope_id": envelope_id,
            "envelope_version": envelope_version,
            "envelope_sha256": envelope_sha256,
        },
        "trace_context": {
            "schema_version": OBSERVABILITY_TRACE_CONTEXT_SCHEMA_VERSION,
            "trace_id": trace_id,
            "span_id": root_span_id,
            "trace_flags": OBSERVABILITY_TRACE_FLAGS_DEFAULT,
            "trace_state": OBSERVABILITY_TRACE_STATE_DEFAULT,
            "is_remote": False,
            "sampled": False,
        },
        "semantics": {
            "mission_root_trace": True,
            "deterministic_identity": True,
            "restart_stable": True,
            "read_only_projection": True,
            "trace_identity_is_authorization": False,
            "trace_identity_is_execution_authority": False,
            "trace_identity_is_governance_decision": False,
            "telemetry_export_performed": False,
            "external_network_io_performed": False,
            "runtime_probe_performed": False,
            "mission_state_transition_performed": False,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "execution_attempt_created": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
            "database_migration_added": False,
            "durable_store_added": False,
        },
    }
    canonical_sha256 = sha256_hex({"hash_domain": OBSERVABILITY_TRACE_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "hash_domain": OBSERVABILITY_TRACE_HASH_DOMAIN,
            "canonical_sha256": canonical_sha256,
        },
    }


def verify_observability_trace_identity_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != OBSERVABILITY_TRACE_SCHEMA_VERSION:
            return False
        identity = contract["identity"]
        bindings = contract["source_bindings"]
        trace_context = contract["trace_context"]
        integrity = contract["integrity"]
        mission_id = identity["mission_id"]
        envelope_sha256 = bindings["envelope_sha256"]
        trace_id = identity["trace_id"]
        root_span_id = identity["root_span_id"]
        if not _HEX64.match(envelope_sha256):
            return False
        if not _HEX32.match(trace_id) or not _HEX16.match(root_span_id):
            return False
        if trace_id == "0" * 32 or root_span_id == "0" * 16:
            return False
        if trace_id != derive_trace_id(mission_id, envelope_sha256):
            return False
        if root_span_id != derive_root_span_id(mission_id, envelope_sha256):
            return False
        if trace_context.get("trace_id") != trace_id or trace_context.get("span_id") != root_span_id:
            return False
        if trace_context.get("trace_flags") != OBSERVABILITY_TRACE_FLAGS_DEFAULT:
            return False
        core = dict(contract)
        core.pop("integrity", None)
        expected = sha256_hex({"hash_domain": OBSERVABILITY_TRACE_HASH_DOMAIN, "core": core})
        return integrity.get("hash_domain") == OBSERVABILITY_TRACE_HASH_DOMAIN and integrity.get("canonical_sha256") == expected
    except (KeyError, TypeError, ValueError):
        return False


def canonical_observability_trace_definition() -> dict[str, Any]:
    return {
        "schema_version": OBSERVABILITY_TRACE_SCHEMA_VERSION,
        "context_schema_version": OBSERVABILITY_TRACE_CONTEXT_SCHEMA_VERSION,
        "mode": OBSERVABILITY_TRACE_MODE,
        "authority": OBSERVABILITY_TRACE_AUTHORITY,
        "identity_algorithm": OBSERVABILITY_TRACE_IDENTITY_ALGORITHM,
        "trace_id_format": OBSERVABILITY_TRACE_ID_FORMAT,
        "root_span_id_format": OBSERVABILITY_ROOT_SPAN_ID_FORMAT,
        "database_change_mode": OBSERVABILITY_TRACE_DATABASE_CHANGE_MODE,
        "persistence_mode": OBSERVABILITY_TRACE_PERSISTENCE_MODE,
        "export_mode": OBSERVABILITY_TRACE_EXPORT_MODE,
        "identity_binding": "MISSION_ID_PLUS_IMMUTABLE_CANONICAL_ENVELOPE_SHA256",
        "trace_tree_scope": "MISSION_ROOT_ONLY_STAGE_3_8_1",
        "future_child_span_propagation_authority": "NOT_IMPLEMENTED_IN_STAGE_3_8_1",
        "runtime_side_effects": False,
    }
