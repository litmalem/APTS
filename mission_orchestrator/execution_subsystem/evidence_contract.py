"""Stage 6.6 capture contracts; hashes establish integrity, never authority or findings."""
from __future__ import annotations

import hashlib

from .authorization_contract import parse_time
from .execution_contract import (canonical_json, require_id, require_sha,
    verify_integrity, with_integrity)
from .runtime_contract import RUNTIME_CONTROL_VERSION, TERMINAL, canonical_runtime_contract

EVIDENCE_CONTROL_VERSION = "stage6.6-artifact-evidence-capture"
CONTRACT_SCHEMA = "apts-stage6.6-artifact-evidence-capture-v1"
SESSION_SCHEMA = "apts-execution-capture-session-v1"
ARTIFACT_SCHEMA = "apts-execution-artifact-v1"
EVIDENCE_SCHEMA = "apts-execution-evidence-capture-v1"
CONTRACT_DOMAIN = "APTS_STAGE6_6_ARTIFACT_EVIDENCE_CAPTURE_V1"
SESSION_DOMAIN = "APTS_EXECUTION_CAPTURE_SESSION_V1"
ARTIFACT_DOMAIN = "APTS_EXECUTION_ARTIFACT_V1"
EVIDENCE_DOMAIN = "APTS_EXECUTION_EVIDENCE_CAPTURE_V1"
MAX_ARTIFACT_BYTES = 131072
MAX_ATTEMPT_BYTES = 524288
KINDS = ("TOOL_IDENTITY", "ACTION_PARAMETERS", "BEFORE_STATE", "STDOUT", "STDERR",
         "NETWORK_OBSERVATION", "TARGET_RESPONSE", "RESULT", "AFTER_STATE")
LINK_FIELDS = ("attempt_id", "invocation_id", "execution_id", "task_id", "pentest_id",
               "pentest_task_id", "mission_id", "authorization_id", "recon_action_id", "proposal_ref")
SEMANTICS = {"execution_authorized": False, "usable_for_dispatch": False,
    "replay_performs_io": False, "vep_created": False, "vulnerability_confirmed": False}
SESSION_FIELDS = set(LINK_FIELDS) | {"schema_version", "control_version", "attempt_sha256",
    "claim_sha256", "envelope_sha256", "contract_sha256", "enrolled_at", "integrity"}
ARTIFACT_FIELDS = set(LINK_FIELDS) | {"schema_version", "control_version", "session_sha256", "kind",
    "media_type", "producer", "privacy_policy", "captured_at", "content_sha256", "size_bytes",
    "captured_sha256", "captured_size_bytes", "redacted", "capture_complete", "artifact_id", "integrity"}
EVIDENCE_FIELDS = set(LINK_FIELDS) | {"schema_version", "control_version", "session_sha256", "attempt_sha256",
    "claim_sha256", "envelope_sha256", "state", "sealed_at", "authorized_at", "started_at", "runtime_event_count",
    "terminal_event_id", "terminal_event_sha256", "adapter_result_sha256", "boundary_authorization_id",
    "capture_status", "target_io_uncertain", "coverage", "artifacts", "stored_bytes", "semantics", "evidence_id", "integrity"}


def bytes_sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_evidence_contract():
    return with_integrity({"schema_version": CONTRACT_SCHEMA, "control_version": EVIDENCE_CONTROL_VERSION,
        "predecessor": {"control": RUNTIME_CONTROL_VERSION,
            "contract_sha256": canonical_runtime_contract()["integrity"]["canonical_sha256"]},
        "repository": {"migration_level": 6, "mission_migration": 53, "pentest_migration": 16,
            "backend": "EXECUTION_SQLITE_BLOBS", "append_only": True,
            "terminal_manifest_and_result_atomic": True, "caller_paths_supported": False},
        "capture": {"producer": "SERVER_RUNTIME_AND_TRUSTED_BROKER", "kinds": list(KINDS),
            "link_fields": list(LINK_FIELDS), "caller_upload_supported": False,
            "specialist_proposal_action_authorization_binding": True,
            "recon_action_id_is_null_for_enumeration_proposals": True,
            "screenshots": "NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS",
            "target_before_after_state": "NOT_MEASURED_BY_CURRENT_FIXED_ADAPTERS",
            "runtime_before_after_state": "CAPTURED", "partial_failures": "EXPLICIT_COVERAGE",
            "legacy_history": "NOT_CAPTURED_NO_RETROACTIVE_TARGET_IO",
            "crash_recovery": "SEAL_DURABLE_PARTIAL_CAPTURE_WITH_EXPLICIT_GAPS"},
        "limits": {"max_artifact_bytes": MAX_ARTIFACT_BYTES, "max_attempt_bytes": MAX_ATTEMPT_BYTES,
            "max_artifacts_per_attempt": len(KINDS), "upstream_network_output_quotas_preserved": True},
        "privacy": {"policy": "METADATA_ALLOWLIST_V1", "raw_target_bytes_retained": False,
            "raw_stderr_retained": False, "authorization_header_retained": False,
            "stdout": "FIXED_WORKER_ALLOWLIST_METADATA", "response": "STATUS_LENGTH_DIGEST_ONLY",
            "separate_captured_and_stored_hashes": True},
        "boundaries": {"mission_pentest_writes": False, "additional_target_io": False,
            "authorization_minted_locally": False, "specialist_raw_target_access": False,
            "hashes_are_authorization": False, "vep_created": False},
        "semantics": dict(SEMANTICS), "runtime_self_certification": False, "next_stage": "6.7"}, CONTRACT_DOMAIN)


def verify_evidence_contract(value):
    try:
        return canonical_json(value) == canonical_json(canonical_evidence_contract())
    except (TypeError, ValueError, RecursionError):
        return False


def _identity(prefix, core):
    from .execution_contract import sha256_hex
    return prefix + sha256_hex(core)[:32]


def seal_artifact(core):
    return with_integrity({**core, "artifact_id": _identity("xartifact-", core)}, ARTIFACT_DOMAIN)


def seal_evidence(core):
    return with_integrity({**core, "evidence_id": _identity("xevidence-", core)}, EVIDENCE_DOMAIN)


def verify_links(value):
    prefixes = {"attempt_id":"xattempt-", "invocation_id":"toolinv-", "execution_id":"exec-",
        "task_id":"ptask-", "pentest_id":"pentest-", "pentest_task_id":"", "mission_id":"mission-gmo-",
        "authorization_id":"eauth-", "recon_action_id":"rareq-", "proposal_ref":"actp-"}
    for key, prefix in prefixes.items():
        if key in {"recon_action_id", "proposal_ref"} and value[key] is None:
            continue
        require_id(value[key], key, prefix)


def verify_session(value):
    try:
        if set(value) != SESSION_FIELDS:
            return False
        verify_links(value)
        parse_time(value["enrolled_at"], "enrolled_at")
        for field in ("attempt_sha256", "claim_sha256", "envelope_sha256"):
            require_sha(value[field], field)
        return (verify_integrity(value, SESSION_DOMAIN) and value["schema_version"] == SESSION_SCHEMA
            and value["control_version"] == EVIDENCE_CONTROL_VERSION
            and value["contract_sha256"] == canonical_evidence_contract()["integrity"]["canonical_sha256"])
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False


def verify_artifact(value, payload=None):
    try:
        if set(value) != ARTIFACT_FIELDS:
            return False
        core = {k:v for k,v in value.items() if k not in {"artifact_id", "integrity"}}
        verify_links(value)
        require_sha(value["content_sha256"], "content_sha256")
        require_sha(value["captured_sha256"], "captured_sha256")
        require_sha(value["session_sha256"], "session_sha256")
        parse_time(value["captured_at"], "captured_at")
        return (verify_integrity(value, ARTIFACT_DOMAIN) and value["schema_version"] == ARTIFACT_SCHEMA
            and value["control_version"] == EVIDENCE_CONTROL_VERSION
            and value["artifact_id"] == _identity("xartifact-", core) and value["kind"] in KINDS
            and value["media_type"] == "application/json" and value["producer"] == "SERVER_RUNTIME"
            and value["privacy_policy"] == "METADATA_ALLOWLIST_V1"
            and type(value["size_bytes"]) is int and 0 <= value["size_bytes"] <= MAX_ARTIFACT_BYTES
            and type(value["captured_size_bytes"]) is int and value["captured_size_bytes"] >= 0
            and type(value["capture_complete"]) is bool and type(value["redacted"]) is bool
            and (payload is None or isinstance(payload, bytes) and len(payload) == value["size_bytes"]
                 and bytes_sha256(payload) == value["content_sha256"]))
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False


def verify_evidence(value):
    try:
        if set(value) != EVIDENCE_FIELDS:
            return False
        core = {k:v for k,v in value.items() if k not in {"evidence_id", "integrity"}}
        verify_links(value)
        sealed = parse_time(value["sealed_at"], "sealed_at")
        authorized = parse_time(value["authorized_at"], "authorized_at")
        if sealed < authorized or value["started_at"] is not None and not authorized <= parse_time(value["started_at"], "started_at") <= sealed:
            return False
        for field in ("attempt_sha256", "claim_sha256", "envelope_sha256"):
            require_sha(value[field], field)
        if value["adapter_result_sha256"] is not None:
            require_sha(value["adapter_result_sha256"], "adapter_result_sha256")
        require_sha(value["terminal_event_sha256"], "terminal_event_sha256")
        require_sha(value["session_sha256"], "session_sha256")
        artifacts = value["artifacts"]
        return (verify_integrity(value, EVIDENCE_DOMAIN) and value["schema_version"] == EVIDENCE_SCHEMA
            and value["control_version"] == EVIDENCE_CONTROL_VERSION
            and value["evidence_id"] == _identity("xevidence-", core) and value["semantics"] == SEMANTICS
            and value["state"] in TERMINAL and value["capture_status"] in {"CAPTURED", "PARTIAL", "RECOVERED_PARTIAL"}
            and type(value["target_io_uncertain"]) is bool and type(value["runtime_event_count"]) is int and value["runtime_event_count"] >= 2
            and type(value["stored_bytes"]) is int
            and set(value["coverage"]) == set(KINDS) | {"SCREENSHOTS", "TARGET_BEFORE_STATE", "TARGET_AFTER_STATE"}
            and isinstance(artifacts, list) and len(artifacts) <= len(KINDS)
            and len({a["kind"] for a in artifacts}) == len(artifacts)
            and all(verify_artifact(a) and all(a[k] == value[k] for k in LINK_FIELDS)
                    and a["session_sha256"] == value["session_sha256"] for a in artifacts)
            and value["stored_bytes"] == sum(a["size_bytes"] for a in artifacts)
            and value["stored_bytes"] <= MAX_ATTEMPT_BYTES
            and value["artifacts"] == sorted(artifacts, key=lambda a:a["kind"]))
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False


def observation_network_binding(observation):
    if isinstance(observation,dict) and observation.get("schema_version")=="web-technology-observation-v4":
        return observation["network_binding"]
    return observation
