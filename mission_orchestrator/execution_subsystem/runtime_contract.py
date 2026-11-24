"""Stage 6.5 contracts. Runtime state never confers target authority."""
from __future__ import annotations

from .adapter_contract import ADAPTER_CONTROL_VERSION, canonical_adapter_contract, normalize_adapter_intake
from .execution_contract import (ExecutionRequestValidationError, canonical_json, require_id,
    require_object, require_sha, require_text, sha256_hex, verify_integrity, with_integrity)

RUNTIME_CONTROL_VERSION = "stage6.5-execution-runtime-control"
RUNTIME_SCHEMA = "apts-stage6.5-execution-runtime-control-v1"
START_SCHEMA = "apts-execution-runtime-start-v1"
RETRY_SCHEMA = "apts-execution-runtime-retry-v1"
CANCEL_SCHEMA = "apts-execution-runtime-cancel-v1"
KILL_SCHEMA = "apts-execution-runtime-kill-v1"
ATTEMPT_DOMAIN = "APTS_EXECUTION_RUNTIME_ATTEMPT_V1"
EVENT_DOMAIN = "APTS_EXECUTION_RUNTIME_EVENT_V1"
COMMAND_DOMAIN = "APTS_EXECUTION_RUNTIME_COMMAND_V1"
CONTRACT_DOMAIN = "APTS_STAGE6_5_EXECUTION_RUNTIME_CONTROL_V1"
TERMINAL = frozenset({"SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED", "ABORTED"})
STATES = ("AUTHORIZED", "DISPATCHED", "RUNNING", "SUCCEEDED", "FAILED", "TIMEOUT", "CANCELLED", "ABORTED")
MAX_ATTEMPTS = 3
HEARTBEAT_SECONDS = 0.5
HEARTBEAT_TIMEOUT_SECONDS = 10.0
REVALIDATION_PROBE_TIMEOUT_SECONDS = 8.0
POLL_SECONDS = 0.05
REVALIDATE_SECONDS = 0.5
# The supervisor reads the authority/context sources inline each revalidation
# cycle. That read is bounded by its own monitored worker so a stalled source
# surfaces a dedicated terminal reason instead of a misleading heartbeat loss,
# and always resolves strictly before the HEARTBEAT_TIMEOUT watchdog window.
SOURCE_READ_TIMEOUT_SECONDS = REVALIDATION_PROBE_TIMEOUT_SECONDS
# Terminal ABORTED reasons that provably occur before, or without, any target
# I/O. An attempt stopped for one of these, whose sealed result additionally
# proves no network I/O and whose resources are closed, is eligible for an
# explicit, freshly-authorized recovery attempt. This is deliberately NOT the
# general automatic-retry set (retry_policy.retryable_states stays FAILED,
# TIMEOUT); intentional halts (emergency kill, shutdown), clock/integrity
# anomalies, and I/O-uncertain orphan aborts are excluded.
RECOVERABLE_ABORT_REASONS = frozenset({
    "RUNTIME_HEARTBEAT_LOST", "RUNTIME_SOURCE_READ_TIMEOUT", "RUNTIME_SOURCE_UNREADABLE",
    "RUNTIME_SOURCE_CHANGED_OR_REVOKED", "RUNTIME_GOVERNANCE_REVALIDATION_STALE",
    "RUNTIME_GOVERNANCE_REVALIDATION_FAILED",
})


def normalize_start(payload, *, retry=False):
    fields = {"schema_version", "invocation_request_id", "idempotency_key", "execution_id", "envelope_sha256", "requested_by"}
    if retry:
        fields |= {"retry_of_attempt_id", "expected_head_sha256"}
    obj = require_object(payload, fields, "runtime retry" if retry else "runtime start")
    schema = RETRY_SCHEMA if retry else START_SCHEMA
    if obj["schema_version"] != schema:
        raise ExecutionRequestValidationError("unsupported runtime intake schema")
    base = normalize_adapter_intake({**{k:v for k,v in obj.items() if k not in {"retry_of_attempt_id", "expected_head_sha256"}},
                                    "schema_version": "apts-execution-adapter-intake-v1"})
    normalized = {**base, "schema_version": schema}
    if retry:
        normalized.update({"retry_of_attempt_id": require_id(obj["retry_of_attempt_id"], "retry_of_attempt_id", "xattempt-"),
                           "expected_head_sha256": require_sha(obj["expected_head_sha256"], "expected_head_sha256")})
    return normalized


def adapter_intake(intake):
    return {**{k:v for k,v in intake.items() if k not in {"retry_of_attempt_id", "expected_head_sha256"}},
            "schema_version": "apts-execution-adapter-intake-v1"}


def normalize_command(payload, *, kill=False):
    fields = {"schema_version", "command_request_id", "idempotency_key", "requested_by", "reason"}
    fields |= {"mission_id"} if kill else {"attempt_id", "attempt_sha256"}
    obj = require_object(payload, fields, "runtime command")
    schema = KILL_SCHEMA if kill else CANCEL_SCHEMA
    if obj["schema_version"] != schema:
        raise ExecutionRequestValidationError("unsupported runtime command schema")
    result = {"schema_version": schema,
        "command_request_id": require_id(obj["command_request_id"], "command_request_id", "rtcmd-"),
        "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key"),
        "requested_by": require_text(obj["requested_by"], "requested_by", 200),
        "reason": require_text(obj["reason"], "reason", 500)}
    if kill:
        result["mission_id"] = require_id(obj["mission_id"], "mission_id", "mission-gmo-")
    else:
        result.update({"attempt_id": require_id(obj["attempt_id"], "attempt_id", "xattempt-"),
                       "attempt_sha256": require_sha(obj["attempt_sha256"], "attempt_sha256")})
    return result


def intake_json_schema(*, retry=False, command=False, kill=False):
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    if command:
        fields = {"schema_version", "command_request_id", "idempotency_key", "requested_by", "reason"}
        fields |= {"mission_id"} if kill else {"attempt_id", "attempt_sha256"}
        schema = KILL_SCHEMA if kill else CANCEL_SCHEMA
    else:
        fields = {"schema_version", "invocation_request_id", "idempotency_key", "execution_id", "envelope_sha256", "requested_by"}
        if retry:
            fields |= {"retry_of_attempt_id", "expected_head_sha256"}
        schema = RETRY_SCHEMA if retry else START_SCHEMA
    properties = {k:{"type":"string", "pattern":ID_PATTERN} for k in fields}
    properties["schema_version"] = {"const":schema}
    for key in fields & {"attempt_sha256", "envelope_sha256", "expected_head_sha256"}:
        properties[key] = {"type":"string", "pattern":SHA_PATTERN}
    properties["requested_by"] = {"type":"string", "minLength":1, "maxLength":200}
    if command:
        properties["reason"] = {"type":"string", "minLength":1, "maxLength":500}
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object",
            "additionalProperties":False, "required":sorted(fields), "properties":properties}


def allowed_transition(before, after, event_type):
    if before is None:
        return after == event_type == "AUTHORIZED"
    if before in TERMINAL:
        return False
    if event_type in {"HEARTBEAT", "STOP_REQUESTED"}:
        return after == before and (event_type != "HEARTBEAT" or before == "RUNNING")
    if after in TERMINAL:
        return event_type == after
    return (before, after, event_type) in {("AUTHORIZED", "DISPATCHED", "DISPATCHED"), ("DISPATCHED", "RUNNING", "RUNNING")}


def canonical_runtime_contract():
    return with_integrity({"schema_version": RUNTIME_SCHEMA, "control_version": RUNTIME_CONTROL_VERSION,
        "predecessor": {"control": ADAPTER_CONTROL_VERSION,
                        "contract_sha256": canonical_adapter_contract()["integrity"]["canonical_sha256"]},
        "repository": {"migration_level": 5, "mission_migration": 53, "pentest_migration": 16,
                       "attempts_events_commands_append_only": True, "terminal_result_atomic": True},
        "states": list(STATES), "terminal_states": sorted(TERMINAL),
        "liveness": {"heartbeat_seconds": HEARTBEAT_SECONDS, "heartbeat_timeout_seconds": HEARTBEAT_TIMEOUT_SECONDS,
                     "revalidation_probe_timeout_seconds": REVALIDATION_PROBE_TIMEOUT_SECONDS,
                     "control_poll_seconds": POLL_SECONDS, "revalidation_seconds": REVALIDATE_SECONDS,
                     "heartbeat_producer": "SERVER_SUPERVISOR", "caller_heartbeat_supported": False},
        "retry_policy": {"max_attempts": MAX_ATTEMPTS, "automatic_retry": False,
                         "retryable_states": ["FAILED", "TIMEOUT"], "requires_proven_no_target_io": True,
                         "requires_latest_terminal_head": True, "fresh_gss_required": True,
                         "all_attempts_charge_lifetime_budget": True, "credential_lease_single_use": True},
        "stop_policy": {"cancel_scope": "EXACT_ATTEMPT", "emergency_kill_scope": "MISSION",
                        "kill_latched_durably": True, "kill_reset_supported": False,
                        "closes_broker_socket_and_native_worker": True,
                        "terminal_after_resources_closed": True, "completed_side_effects_reversible": False},
        "recovery": {"exclusive_os_owner_lock": True, "orphan_attempt_terminal": "ABORTED",
                     "redispatch": False, "target_io_uncertain_blocks_retry": True,
                     "legacy_v4_orphans_remain_quarantined": True},
        "boundaries": {"specialist_raw_target_access": False, "caller_result_supported": False,
                       "authorization_minted_locally": False, "mission_pentest_writes": False,
                       "vep_created": False, "evidence_repository_stage": "6.6"},
        "intake_schemas": {"start":intake_json_schema(), "retry":intake_json_schema(retry=True),
                           "cancel":intake_json_schema(command=True), "kill":intake_json_schema(command=True,kill=True)},
        "runtime_self_certification": False, "next_stage": "6.6"}, CONTRACT_DOMAIN)


def verify_runtime_contract(value):
    try:
        return canonical_json(value) == canonical_json(canonical_runtime_contract())
    except (TypeError, ValueError, RecursionError):
        return False


def attempt_id(invocation_id):
    return "xattempt-" + sha256_hex({"invocation_id": invocation_id})[:32]


def verify_attempt(value):
    try:
        intake = normalize_start(value["runtime_intake"], retry=value["runtime_intake"]["schema_version"] == RETRY_SCHEMA)
        return (verify_integrity(value, ATTEMPT_DOMAIN) and value["control_version"] == RUNTIME_CONTROL_VERSION
            and value["attempt_id"] == attempt_id(value["invocation_id"])
            and type(value["attempt_number"]) is int and 1 <= value["attempt_number"] <= MAX_ATTEMPTS
            and intake["execution_id"] == value["execution_id"]
            and value["retry_of_attempt_id"] == intake.get("retry_of_attempt_id")
            and value["state"] == "AUTHORIZED")
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False


def verify_event(value):
    try:
        core = {k:v for k,v in value.items() if k not in {"event_id", "integrity"}}
        return (verify_integrity(value, EVENT_DOMAIN) and value["control_version"] == RUNTIME_CONTROL_VERSION
            and value["event_id"] == "xevent-" + sha256_hex(core)[:32]
            and type(value["event_sequence"]) is int and value["event_sequence"] >= 1
            and allowed_transition(value["state_before"], value["state_after"], value["event_type"]))
    except (KeyError, TypeError, ValueError):
        return False


def verify_command(value):
    try:
        intake = normalize_command(value["intake"], kill=value["operation"] == "KILL")
        return (verify_integrity(value, COMMAND_DOMAIN) and value["control_version"] == RUNTIME_CONTROL_VERSION
            and value["command_id"] == "xcommand-" + sha256_hex(intake)[:32]
            and value["operation"] in {"CANCEL", "KILL"} and intake == value["intake"])
    except (KeyError, TypeError, ValueError, RuntimeError):
        return False
