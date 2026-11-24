"""Exact post-action reports bind preserved VEPs to trusted local resource receipts."""
from __future__ import annotations

from .authorization_contract import parse_time
from .execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    canonical_json, require_id, require_object, require_sha, sha256_hex, verify_integrity, with_integrity)
from .cleanup_resources import resources_verified
from .tool_registry import legacy_adapter_definitions as adapter_definitions, legacy_registry_sha256 as registry_sha256
from .vep_contract import VEP_CONTROL_VERSION, canonical_vep_contract, verify_vep, verify_vep_export

CONTROL_VERSION = "stage6.8-cleanup-rollback-post-action-verification"
CONTRACT_SCHEMA = "apts-stage6.8-cleanup-rollback-post-action-verification-v1"
INTAKE_SCHEMA = "apts-execution-post-action-intake-v1"
REPORT_SCHEMA = "apts-execution-post-action-report-v1"
RECEIPT_SCHEMA = "apts-execution-local-cleanup-receipt-v1"
REVOCATION_SCHEMA = "apts-execution-local-credential-revocation-v1"
EXPORT_SCHEMA = "apts-post-action-offline-export-v1"
CONTRACT_DOMAIN = "APTS_STAGE6_8_CLEANUP_ROLLBACK_POST_ACTION_VERIFICATION_V1"
REPORT_DOMAIN = "APTS_EXECUTION_POST_ACTION_REPORT_V1"
RECEIPT_DOMAIN = "APTS_EXECUTION_LOCAL_CLEANUP_RECEIPT_V1"
REVOCATION_DOMAIN = "APTS_EXECUTION_LOCAL_CREDENTIAL_REVOCATION_V1"
MAX_REPORT_BYTES = 65536
MAX_RECEIPT_BYTES = 16384
INTAKE_FIELDS = {"schema_version", "attempt_id", "envelope_sha256", "evidence_sha256",
    "expected_head_sha256", "vep_id", "vep_sha256"}
PHASES = ["VERIFY_EFFECT", "CLEANUP_TEMPORARY_ARTIFACTS", "REVOKE_TEMPORARY_CREDENTIALS",
    "RESTORE_REQUIRED_STATE", "VERIFY_CLEANUP", "CLOSE_EXECUTION"]
SEMANTICS = {"execution_authorized":False, "authorization_current":False,
    "usable_for_dispatch":False, "additional_target_io":False, "replay_performs_io":False,
    "mission_pentest_writes":False, "evidence_deleted":False, "vep_modified":False,
    "target_state_verified":False, "target_rollback_performed":False,
    "issuer_credential_revocation_proven":False, "vulnerability_confirmed":False,
    "impact_confirmed":False, "cti_feedback_written":False}


def intake_json_schema():
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object",
        "additionalProperties":False, "required":sorted(INTAKE_FIELDS), "properties":{
            "schema_version":{"const":INTAKE_SCHEMA},
            **{k:{"type":"string", "pattern":ID_PATTERN} for k in ("attempt_id", "vep_id")},
            **{k:{"type":"string", "pattern":SHA_PATTERN} for k in INTAKE_FIELDS - {"schema_version", "attempt_id", "vep_id"}}}}


def normalize_intake(payload):
    obj = require_object(payload, INTAKE_FIELDS, "post-action intake")
    if obj["schema_version"] != INTAKE_SCHEMA:
        raise ExecutionRequestValidationError("unsupported post-action intake schema")
    return {"schema_version":INTAKE_SCHEMA,
        "attempt_id":require_id(obj["attempt_id"], "attempt_id", "xattempt-"),
        "vep_id":require_id(obj["vep_id"], "vep_id", "xvep-"),
        **{k:require_sha(obj[k], k) for k in INTAKE_FIELDS - {"schema_version", "attempt_id", "vep_id"}}}


def report_json_schema():
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    ids = ("post_action_id", "attempt_id", "execution_id", "mission_id", "pentest_id", "vep_id")
    hashes = ("vep_sha256", "envelope_sha256", "evidence_sha256", "terminal_event_sha256", "contract_sha256")
    properties = {k:{"type":"string", "pattern":ID_PATTERN} for k in ids}
    properties.update({k:{"type":"string", "pattern":SHA_PATTERN} for k in hashes})
    properties.update({k:{"anyOf":[{"type":"null"},{"type":"string", "pattern":SHA_PATTERN}]}
        for k in ("receipt_sha256", "revocation_sha256")})
    properties.update({"schema_version":{"const":REPORT_SCHEMA}, "control_version":{"const":CONTROL_VERSION},
        "receipt_result_binding":{"enum":["ABSENT", "PRETERMINAL_RESULT_NOT_DURABLE", "EXACT_DURABLE_RESULT"]},
        "state":{"enum":["CLOSED_LOCAL_RESOURCES", "BLOCKED_REQUIRES_REVIEW"]},
        "execution_closed":{"type":"boolean"}, "cleanup_verified":{"type":"boolean"},
        "closure_scope":{"const":"EXACT_ATTEMPT_LOCAL_RESOURCES"}, "blocking_reasons":{"type":"array", "items":{"type":"string"}},
        "effect_verification":{"type":"object"}, "rollback":{"type":"object"}, "credentials":{"type":"object"},
        "phases":{"type":"array", "minItems":6, "maxItems":6}, "evaluated_at":{"type":"string", "format":"date-time"},
        "semantics":{"const":SEMANTICS}, "integrity":{"type":"object"}})
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object", "additionalProperties":False,
        "required":sorted(properties), "properties":properties,
        "description":"Interchange structure only. verify_report and verify_post_action_export check exact nested fields, derived state, source binding and retained bytes."}


def canonical_cleanup_contract():
    return with_integrity({"schema_version":CONTRACT_SCHEMA, "control_version":CONTROL_VERSION,
        "predecessor":{"control":VEP_CONTROL_VERSION,
            "contract_sha256":canonical_vep_contract()["integrity"]["canonical_sha256"]},
        "repository":{"migration_level":8, "mission_migration":53, "pentest_migration":16,
            "append_only":True, "one_report_per_terminal_attempt":True,
            "atomic_local_revocation_and_receipt":True, "atomic_report":True},
        "workflow":{"phases":PHASES, "intake":"EXACT_TERMINAL_VEP_REFERENCES",
            "resource_cleanup":"AUTOMATIC_DURING_OWNED_RUNTIME_TERMINATION",
            "report":"EXPLICIT_AFTER_VEP_CONSTRUCTION", "closure_scope":"LOCAL_EXECUTION_RESOURCES",
            "blocked_report":"RETAIN_NO_CALLER_OVERRIDE_NO_REDISPATCH",
            "legacy":"BLOCK_MISSING_RECEIPT_NO_BACKFILL", "recovery":"BLOCK_UNPROVEN_RESOURCES_AND_TARGET_UNCERTAINTY"},
        "rollback":{"mechanism":"BOUNDED_COMPENSATION_OF_EXACT_OWNED_OBJECTS",
            "restored_baseline":"NO_WORKER_PIPES_SOCKETS_JOB_OR_TEMP_DIRECTORY",
            "caller_paths_commands_pids":False, "retained_evidence_deleted":False,
            "target_state_restore_supported":False, "target_mutation_adapters":False,
            "fixed_read_primitives":adapter_definitions(), "registry_sha256":registry_sha256()},
        "credentials":{"local_lease_revocation":"DURABLE_EXECUTION_SCOPED_DENY",
            "issuer_revocation_supported":False, "acquired_lease_blocks_closure":True,
            "secret_bytes_retained":False, "process_environment_modified":False},
        "verification":{"owned_process_wait":True, "pipes_and_sockets_closed":True,
            "readers_stopped":True, "job_handle_released":True, "temporary_directory_absent":True,
            "vep_and_retained_bytes":True, "caller_attestation_supported":False,
            "target_state_measurement":"NOT_SUPPORTED", "independent_signature":False},
        "limits":{"max_report_bytes":MAX_REPORT_BYTES, "max_receipt_bytes":MAX_RECEIPT_BYTES,
            "max_workers":1, "max_sockets":2},
        "intake_schema":intake_json_schema(), "semantics":dict(SEMANTICS),
        "runtime_self_certification":False, "next_stage":"6.9"}, CONTRACT_DOMAIN)


def verify_cleanup_contract(value):
    try:
        return canonical_json(value) == canonical_json(canonical_cleanup_contract())
    except (TypeError, ValueError, RecursionError):
        return False


def verify_resource_snapshot(value):
    try:
        if set(value) != {"workers", "socket_count", "sockets_closed", "runtime_closers_detached"}:
            return False
        if (type(value["socket_count"]) is not int or not 0 <= value["socket_count"] <= 2
            or not isinstance(value["workers"], list) or len(value["workers"]) > 1
            or any(type(value[k]) is not bool for k in ("sockets_closed", "runtime_closers_detached"))):
            return False
        for w in value["workers"]:
            if set(w) != {"ordinal", "backend", "process_started", "worker_exit_confirmed", "return_code",
                "pipes_closed", "readers_stopped", "temporary_directory_removed", "job_handle_released"}:
                return False
            if (type(w["ordinal"]) is not int or w["ordinal"] != 1
                or w["backend"] not in {None, "SECCOMP_RLIMIT", "JOB_OBJECT_FIXED_WORKER"}
                or any(type(w[k]) is not bool for k in ("process_started", "worker_exit_confirmed",
                    "pipes_closed", "readers_stopped", "temporary_directory_removed", "job_handle_released"))
                or w["return_code"] is not None and type(w["return_code"]) is not int
                or not w["process_started"] and (w["return_code"] is not None or w["backend"] is not None)
                or w["process_started"] and w["worker_exit_confirmed"] and w["return_code"] is None):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def verify_receipt(value):
    try:
        fields = {"schema_version", "control_version", "attempt_id", "execution_id", "owner_id",
            "attempt_sha256", "claim_sha256", "adapter_result_sha256", "contract_sha256",
            "verified_at", "resources", "local_resources_verified", "integrity"}
        if (set(value) != fields or value["schema_version"] != RECEIPT_SCHEMA
            or value["control_version"] != CONTROL_VERSION or not verify_integrity(value, RECEIPT_DOMAIN)
            or value["contract_sha256"] != canonical_cleanup_contract()["integrity"]["canonical_sha256"]
            or len(canonical_json(value).encode("utf-8")) > MAX_RECEIPT_BYTES):
            return False
        for key,prefix in (("attempt_id","xattempt-"), ("execution_id","exec-"), ("owner_id","runtime-owner-")):
            require_id(value[key], key, prefix)
        for key in ("attempt_sha256", "claim_sha256", "adapter_result_sha256", "contract_sha256"):
            require_sha(value[key], key)
        parse_time(value["verified_at"], "verified_at")
        r = value["resources"]
        if set(r) != {"before_rollback", "after_rollback", "rollback_attempted", "rollback_errors", "interrupt_cleanup_errors"}:
            return False
        if (not verify_resource_snapshot(r["before_rollback"]) or not verify_resource_snapshot(r["after_rollback"])
            or type(r["rollback_attempted"]) is not bool
            or r["rollback_attempted"] != (not resources_verified(r["before_rollback"]))):
            return False
        for key in ("rollback_errors", "interrupt_cleanup_errors"):
            if (not isinstance(r[key], list) or len(r[key]) > 8
                or any(not isinstance(x,str) or not x.isidentifier() or len(x)>100 for x in r[key])):
                return False
        if len(r["before_rollback"]["workers"]) != len(r["after_rollback"]["workers"]) or r["before_rollback"]["socket_count"] != r["after_rollback"]["socket_count"]:
            return False
        expected = resources_verified(r["after_rollback"]) and not r["rollback_errors"] and not r["interrupt_cleanup_errors"]
        return type(value["local_resources_verified"]) is bool and value["local_resources_verified"] == expected
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def build_revocation(attempt, lease_id, at):
    require_id(lease_id, "lease_id", "credlease-")
    parse_time(at, "revoked_at")
    return with_integrity({"schema_version":REVOCATION_SCHEMA, "control_version":CONTROL_VERSION,
        "lease_id":lease_id, "execution_id":attempt["execution_id"], "attempt_id":attempt["attempt_id"],
        "attempt_sha256":attempt["integrity"]["canonical_sha256"], "revoked_at":at,
        "scope":"LOCAL_EXECUTION_LEASE_ACCESS", "issuer_revocation_proven":False,
        "secret_persisted":False}, REVOCATION_DOMAIN)


def verify_revocation(value):
    try:
        if (set(value) != {"schema_version", "control_version", "lease_id", "execution_id", "attempt_id",
                "attempt_sha256", "revoked_at", "scope", "issuer_revocation_proven", "secret_persisted", "integrity"}
            or not verify_integrity(value, REVOCATION_DOMAIN)
            or value["schema_version"] != REVOCATION_SCHEMA or value["control_version"] != CONTROL_VERSION
            or value["scope"] != "LOCAL_EXECUTION_LEASE_ACCESS"
            or value["issuer_revocation_proven"] is not False or value["secret_persisted"] is not False):
            return False
        require_id(value["lease_id"], "lease_id", "credlease-")
        require_id(value["execution_id"], "execution_id", "exec-")
        require_id(value["attempt_id"], "attempt_id", "xattempt-")
        require_sha(value["attempt_sha256"], "attempt_sha256")
        parse_time(value["revoked_at"], "revoked_at")
        return True
    except (KeyError, TypeError, ValueError):
        return False


def validate_receipt_binding(vep, receipt):
    if not verify_receipt(receipt):
        raise ExecutionRequestIntegrityError("invalid trusted cleanup receipt")
    snapshot = vep["execution_snapshot"]
    attempt, result, events = (snapshot[k] for k in ("attempt", "adapter_result", "events"))
    expected = {"attempt_id":vep["attempt_id"], "execution_id":vep["execution_id"], "owner_id":attempt["owner_id"],
        "attempt_sha256":attempt["integrity"]["canonical_sha256"], "claim_sha256":attempt["claim_sha256"]}
    if result is not None:
        expected["adapter_result_sha256"] = result["integrity"]["canonical_sha256"]
    if (any(receipt[k] != v for k,v in expected.items())
        or events[0]["data"].get("cleanup_contract_sha256") != receipt["contract_sha256"]
        or result is None and events[-1]["data"].get("recovery_owner_fenced") is not True
        or not parse_time(attempt["authorized_at"] if result is None else result["completed_at"], "cleanup_lower_bound")
            <= parse_time(receipt["verified_at"], "verified_at") <= parse_time(events[-1]["occurred_at"], "terminal_at")):
        raise ExecutionRequestIntegrityError("cleanup receipt result/attempt/contract/time binding mismatch")
    workers = receipt["resources"]["after_rollback"]["workers"]
    running = [e for e in events if e["event_type"] == "RUNNING"]
    if (running and (len(workers) != 1 or not workers[0]["process_started"]
        or workers[0]["backend"] != running[0]["data"]["sandbox_backend"])):
        raise ExecutionRequestIntegrityError("cleanup receipt lacks exact native worker")
    if (result is not None and result["observation"] is not None and result["observation"].get("connected") is True
        and receipt["resources"]["after_rollback"]["socket_count"] == 0):
        raise ExecutionRequestIntegrityError("observed connection without tracked broker socket")


def build_report(vep, receipt, revocation, at):
    if not verify_vep(vep):
        raise ExecutionRequestIntegrityError("post-action requires a verified VEP")
    when = parse_time(at, "evaluated_at")
    if when < parse_time(vep["timestamps"]["constructed_at"], "constructed_at"):
        raise ExecutionRequestIntegrityError("post-action clock predates VEP")
    snapshot = vep["execution_snapshot"]
    claim, result, events = (snapshot[k] for k in ("claim", "adapter_result", "events"))
    lease = claim["controls"]["credential_lease_id"]
    acquired = (result["credential_lease"] is not None) if result is not None else None if lease else False
    if receipt is not None:
        validate_receipt_binding(vep, receipt)
    if revocation is not None:
        if (not verify_revocation(revocation) or revocation["lease_id"] != lease
            or revocation["execution_id"] != vep["execution_id"] or when < parse_time(revocation["revoked_at"], "revoked_at")):
            raise ExecutionRequestIntegrityError("post-action credential revocation mismatch")
    local_verified = receipt is not None and receipt["local_resources_verified"]
    reasons = []
    if receipt is None:
        reasons.append("LOCAL_RESOURCE_RECEIPT_MISSING_NO_BACKFILL")
    elif not local_verified:
        reasons.append("LOCAL_RESOURCE_CLEANUP_UNPROVEN")
    if receipt is not None and result is None:
        reasons.append("CLEANUP_RECEIPT_PRETERMINAL_RESULT_NOT_DURABLE")
    if vep["observed_result"]["target_io_uncertain"]:
        reasons.append("RECOVERY_TARGET_IO_UNCERTAIN")
    if lease and revocation is None:
        reasons.append("LOCAL_CREDENTIAL_REVOCATION_MISSING")
    if acquired:
        reasons.append("ISSUER_CREDENTIAL_REVOCATION_NOT_PROVEN")
    elif acquired is None:
        reasons.append("CREDENTIAL_ACQUISITION_UNCERTAIN")
    closed = not reasons
    rollback = None if receipt is None else receipt["resources"]
    method = vep["validation_method"]
    record = {"schema_version":REPORT_SCHEMA, "control_version":CONTROL_VERSION,
        **{k:vep[k] for k in ("attempt_id", "execution_id", "mission_id", "pentest_id", "vep_id")},
        "vep_sha256":vep["integrity"]["canonical_sha256"],
        "envelope_sha256":snapshot["envelope"]["integrity"]["canonical_sha256"],
        "evidence_sha256":vep["evidence"]["integrity"]["canonical_sha256"],
        "terminal_event_sha256":events[-1]["integrity"]["canonical_sha256"],
        "receipt_sha256":None if receipt is None else receipt["integrity"]["canonical_sha256"],
        "receipt_result_binding":"ABSENT" if receipt is None else "PRETERMINAL_RESULT_NOT_DURABLE" if result is None else "EXACT_DURABLE_RESULT",
        "revocation_sha256":None if revocation is None else revocation["integrity"]["canonical_sha256"],
        "contract_sha256":canonical_cleanup_contract()["integrity"]["canonical_sha256"],
        "state":"CLOSED_LOCAL_RESOURCES" if closed else "BLOCKED_REQUIRES_REVIEW",
        "execution_closed":closed, "cleanup_verified":local_verified,
        "closure_scope":"EXACT_ATTEMPT_LOCAL_RESOURCES", "blocking_reasons":reasons,
        "effect_verification":{"status":"RETAINED_OBSERVATION_REVIEWED", "runtime_state":events[-1]["state_after"],
            "adapter_status":None if result is None else result["status"],
            "capture_status":vep["evidence"]["capture_status"],
            "target_io_uncertain":vep["observed_result"]["target_io_uncertain"],
            "target_state":"NOT_MEASURED", "vulnerability_confirmed":False, "impact_confirmed":False},
        "rollback":{"scope":"OWNED_LOCAL_RESOURCES", "baseline_restored":local_verified,
            "compensation_attempted":False if rollback is None else rollback["rollback_attempted"],
            "target_restore":"NOT_SUPPORTED_BY_CURRENT_READ_PRIMITIVES",
            "target_operation":method["operation"], "target_state_restored":False},
        "credentials":{"lease_id":lease, "lease_acquired":acquired,
            "local_access":"NOT_REQUIRED" if not lease else "REVOKED" if revocation else "UNPROVEN",
            "issuer_revocation":"NOT_PROVEN" if acquired else "NOT_PROVEN_ACQUISITION_UNCERTAIN" if acquired is None else "NOT_REQUIRED_NO_LEASE_ACQUIRED",
            "secret_persisted":False},
        "phases":[{"phase":name, "status":status} for name,status in zip(PHASES, [
            "REVIEWED", "VERIFIED" if local_verified else "UNPROVEN",
            "BLOCKED_ISSUER_REVOCATION" if acquired else "BLOCKED_ACQUISITION_UNCERTAIN" if acquired is None else "REVOKED_LOCAL" if lease and revocation else "UNPROVEN" if lease else "NOT_REQUIRED",
            "LOCAL_BASELINE_RESTORED" if local_verified else "UNPROVEN",
            "VERIFIED_LOCAL" if local_verified else "UNPROVEN", "CLOSED_LOCAL_RESOURCES" if closed else "BLOCKED"])],
        "evaluated_at":at, "semantics":dict(SEMANTICS)}
    record["post_action_id"] = "xcleanup-" + sha256_hex({"attempt_id":vep["attempt_id"],
        "vep_sha256":record["vep_sha256"], "contract_sha256":record["contract_sha256"]})[:32]
    value = with_integrity(record, REPORT_DOMAIN)
    if len(canonical_json(value).encode("utf-8")) > MAX_REPORT_BYTES:
        raise ExecutionRequestIntegrityError("post-action report quota exceeded")
    return value


def verify_report(value, vep, receipt, revocation):
    try:
        return canonical_json(value) == canonical_json(build_report(vep, receipt, revocation, value["evaluated_at"]))
    except (ExecutionRequestIntegrityError, KeyError, TypeError, ValueError, RecursionError):
        return False


def verify_post_action_export(value):
    try:
        return (set(value) == {"schema_version", "report", "vep_export", "receipt", "revocation"}
            and value["schema_version"] == EXPORT_SCHEMA and verify_vep_export(value["vep_export"])
            and verify_report(value["report"], value["vep_export"]["vep"], value["receipt"], value["revocation"]))
    except (KeyError, TypeError, ValueError, RecursionError):
        return False
