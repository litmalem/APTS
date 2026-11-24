"""Stage 6.3 central gateway; sealed admissions are audit, never bearer permits."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .authorization_contract import (
    AUTHORIZATION_BOUNDARIES, EXECUTION_AUTHORIZATION_CONTROL_VERSION,
    canonical_execution_authorization_contract, parse_time, verify_authorization_record,
)
from .execution_contract import (
    ID_PATTERN, SHA_PATTERN, ExecutionRequestValidationError, canonical_json,
    require_id, require_object, require_sha, sha256_hex, verify_integrity, with_integrity,
)
from .gateway_policy import SUPPORTED_POLICY_CONSTRAINTS, admission_policy

EXECUTION_GATEWAY_CONTROL_VERSION = "stage6.3-controlled-execution-gateway"
GATEWAY_CONTRACT_SCHEMA = "apts-stage6.3-controlled-execution-gateway-v1"
GATEWAY_INTAKE_SCHEMA = "apts-execution-gateway-intake-v1"
GATEWAY_RECORD_SCHEMA = "apts-execution-gateway-record-v1"
GATEWAY_CONTRACT_DOMAIN = "APTS_STAGE6_3_GATEWAY_CONTRACT_V1"
GATEWAY_RECORD_DOMAIN = "APTS_STAGE6_3_GATEWAY_RECORD_V1"
GATEWAY_MIGRATION_LEVEL = 3
ADMITTED = "ADMITTED_AWAITING_ADAPTER"
GATEWAY_STATUSES = (ADMITTED, "DENIED", "REVIEW_REQUIRED", "BLOCKED_CONSTRAINTS",
                    "BLOCKED_BUDGET", "BLOCKED_DUPLICATE")


def normalize_gateway_intake(payload: Any) -> dict[str, Any]:
    obj = require_object(payload, {"schema_version", "submission_id", "idempotency_key",
                                 "execution_id", "envelope_sha256", "requested_by"}, "gateway intake")
    if obj["schema_version"] != GATEWAY_INTAKE_SCHEMA:
        raise ExecutionRequestValidationError("unsupported execution gateway intake schema")
    submission_id = require_id(obj["submission_id"], "submission_id", "gwreq-")
    execution_id = require_id(obj["execution_id"], "execution_id", "exec-")
    if submission_id == "gwreq-" or execution_id == "exec-":
        raise ExecutionRequestValidationError("gateway submission and execution identifiers require a nonempty suffix")
    return {"schema_version": GATEWAY_INTAKE_SCHEMA,
            "submission_id": submission_id,
            "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key"),
            "execution_id": execution_id,
            "envelope_sha256": require_sha(obj["envelope_sha256"], "envelope_sha256"),
            "requested_by": require_id(obj["requested_by"], "requested_by")}


def gateway_intake_json_schema() -> dict[str, Any]:
    props = {key: {"type": "string", "pattern": ID_PATTERN, "maxLength": 200}
             for key in ("submission_id", "idempotency_key", "execution_id", "requested_by")}
    props["submission_id"]["pattern"] = r"^gwreq-[A-Za-z0-9._:@\-]+$"
    props["execution_id"]["pattern"] = r"^exec-[A-Za-z0-9._:@\-]+$"
    props["schema_version"] = {"const": GATEWAY_INTAKE_SCHEMA}
    props["envelope_sha256"] = {"type": "string", "pattern": SHA_PATTERN}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "additionalProperties": False, "required": list(props), "properties": props}


def canonical_execution_gateway_contract() -> dict[str, Any]:
    return with_integrity({
        "schema_version": GATEWAY_CONTRACT_SCHEMA, "control_version": EXECUTION_GATEWAY_CONTROL_VERSION,
        "predecessor": {"control": EXECUTION_AUTHORIZATION_CONTROL_VERSION,
                        "contract_sha256": canonical_execution_authorization_contract()["integrity"]["canonical_sha256"]},
        "deliverables": {"execution_gateway": True, "central_execution_policy_enforcement": True},
        "authority": "EXTERNAL_APTS_GSS", "fail_closed": True,
        "invariant": "NO_SPECIALIST_AGENT_HAS_DIRECT_RAW_TARGET_ACCESS",
        "intake_schema_version": GATEWAY_INTAKE_SCHEMA, "record_schema_version": GATEWAY_RECORD_SCHEMA,
        "gateway_intake_json_schema": gateway_intake_json_schema(), "statuses": list(GATEWAY_STATUSES),
        "admission_pipeline": ["IMMUTABLE_REQUEST", "CURRENT_MISSION_PENTEST", "FRESH_EXTERNAL_REVALIDATION",
                               "AUTHORITATIVE_CONSTRAINTS", "FINAL_SOURCE_AND_EXPIRY_RECHECK",
                               "ATOMIC_BUDGET_AND_DEDUPLICATION", "SEALED_ADMISSION_AUDIT"],
        "policy": {"supported_gss_constraints": list(SUPPORTED_POLICY_CONSTRAINTS),
                   "unknown_or_malformed_constraint": "BLOCKED_CONSTRAINTS",
                   "empty_allowlist_denies_all": True, "max_actions_policy_scope": "MISSION",
                   "budget_accounting": "CONSERVATIVE_LIFETIME_ADMISSION_RESERVATIONS",
                   "sources_and_policy_constraints_preserved": True,
                   "runtime_controls_require_stage6_4": True},
        "repository": {"migration_level": GATEWAY_MIGRATION_LEVEL, "store": "execution_gateway_submissions",
                       "append_only": True, "one_admission_per_execution": True,
                       "one_submission_per_authorization": True, "atomic_budget_reservation": True},
        "fresh_revalidation_on_every_new_submission": True,
        "historical_allow_accepted_as_input": False,
        "replay_semantics": "HISTORICAL_AUDIT_ONLY_NO_ADMISSION_OR_DISPATCH",
        "adapter_boundary": {"registered_adapters": [], "target_dispatch_enabled": False,
                             "admission_is_dispatch_authority": False,
                             "fresh_revalidation_required_before_target_dispatch": True,
                             "caller_selected_adapter_or_command_allowed": False,
                             "recon_requires_exact_stage6_4_registry_match_before_admission": True},
        "source": {"mission_migration_level": 53, "pentest_migration_level": 16,
                   "mission_and_pentest_read_only": True},
        "runtime_self_certification": False, "runtime": dict(AUTHORIZATION_BOUNDARIES), "next_stage": "6.4",
    }, GATEWAY_CONTRACT_DOMAIN)


def verify_execution_gateway_contract(value: Any) -> bool:
    try:
        return canonical_json(value) == canonical_json(canonical_execution_gateway_contract())
    except (ValueError, TypeError, RecursionError):
        return False


def make_gateway_record(intake: dict[str, Any], authorization: dict[str, Any], *,
                        admitted_at: str, budget_before: dict[str, int], already_admitted: bool) -> dict[str, Any]:
    intake = normalize_gateway_intake(intake)
    if not verify_authorization_record(authorization):
        raise ExecutionRequestValidationError("gateway requires a verified external authorization record")
    auth_intake = authorization["intake"]
    if any(intake[key] != auth_intake[key] for key in ("execution_id", "envelope_sha256", "requested_by")):
        raise ExecutionRequestValidationError("gateway intake does not bind this authorization")
    now = parse_time(admitted_at, "admitted_at")
    if not parse_time(authorization["received_at"], "received_at") <= now < parse_time(authorization["valid_until"], "valid_until"):
        raise ExecutionRequestValidationError("authorization expired or gateway clock moved backwards")
    if (set(budget_before) != {"mission", "pentest", "task"}
            or any(type(n) is not int or not 0 <= n <= 2**63 - 1 for n in budget_before.values())
            or type(already_admitted) is not bool):
        raise ExecutionRequestValidationError("invalid gateway budget state")
    policy = admission_policy(authorization, now)
    reasons = []
    if authorization["decision"] == "DENY":
        status, reasons = "DENIED", ["AUTHORITATIVE_DENY"]
    elif authorization["decision"] == "REVIEW":
        status, reasons = "REVIEW_REQUIRED", ["AUTHORITATIVE_REVIEW"]
    elif policy["unsupported_constraints"] or policy["reason_codes"]:
        status = "BLOCKED_CONSTRAINTS"
        reasons = policy["reason_codes"] + ["UNSUPPORTED_POLICY_CONSTRAINT:" + x for x in policy["unsupported_constraints"]]
    elif policy["human_review_required"]:
        status, reasons = "REVIEW_REQUIRED", ["POLICY_REQUIRES_VERIFIED_HUMAN_APPROVAL"]
    elif already_admitted:
        status, reasons = "BLOCKED_DUPLICATE", ["EXECUTION_ALREADY_ADMITTED"]
    elif any(budget_before[key] >= maximum for key, maximum in policy["action_limits"].items()):
        status, reasons = "BLOCKED_BUDGET", ["ACTION_BUDGET_EXHAUSTED"]
    else:
        status, reasons = ADMITTED, ["ADMISSION_RESERVED_TARGET_DISPATCH_REQUIRES_STAGE6_4"]
    req = authorization["evaluation"]["execution_request"]
    return with_integrity({
        "schema_version": GATEWAY_RECORD_SCHEMA, "control_version": EXECUTION_GATEWAY_CONTROL_VERSION,
        "gateway_id": "egate-" + sha256_hex(intake)[:32], "intake": intake,
        "execution_id": req["execution_id"], "mission_id": req["mission_id"], "task_id": req["task_id"],
        "pentest_id": req["pentest_id"],
        "pentest_task_id": authorization["evaluation"]["source_binding"]["pentest_task_id"],
        "authorization_id": authorization["authorization_id"],
        "authorization_record_sha256": authorization["integrity"]["canonical_sha256"],
        "request_sha256": req["integrity"]["canonical_sha256"],
        "envelope_sha256": intake["envelope_sha256"],
        "context_sha256": sha256_hex(authorization["evaluation"]["current_context"]),
        "authorization_record": deepcopy(authorization), "admission_policy": policy,
        "budget_before": dict(budget_before), "already_admitted": already_admitted,
        "status": status, "reason_codes": reasons, "admitted_at": admitted_at,
        "admitted_at_evaluation": status == ADMITTED,
        "authorization_consumed_at_admission": status == ADMITTED,
        "admission_is_dispatch_authority": False,
        "fresh_revalidation_required_before_target_dispatch": True,
        "semantics": dict(AUTHORIZATION_BOUNDARIES),
    }, GATEWAY_RECORD_DOMAIN)


def verify_gateway_record(value: Any) -> bool:
    try:
        return (verify_integrity(value, GATEWAY_RECORD_DOMAIN)
                and canonical_json(value) == canonical_json(make_gateway_record(
                    value["intake"], value["authorization_record"], admitted_at=value["admitted_at"],
                    budget_before=value["budget_before"], already_admitted=value["already_admitted"])))
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        return False
