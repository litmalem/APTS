"""Stage 6.2: bind fresh external authority to an immutable execution request.

Hashes detect content changes. The configured Governance transport supplies
authority; neither a caller nor a historical ALLOW supplies a current permit.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from typing import Any

from .execution_contract import (
    EXECUTION_REQUEST_CONTROL_VERSION, REQUIRED_AUTHORIZATION_CHECKS,
    ExecutionRequestValidationError, canonical_execution_request_contract,
    canonical_json, require_id, require_object, require_sha, require_text,
    sha256_hex, verify_integrity, with_integrity, ID_PATTERN, SHA_PATTERN,
)

EXECUTION_AUTHORIZATION_CONTROL_VERSION = "stage6.2-authoritative-execution-authorization"
AUTHORIZATION_CONTRACT_SCHEMA = "apts-stage6.2-authoritative-execution-authorization-v1"
AUTHORIZATION_INTAKE_SCHEMA = "apts-execution-authorization-intake-v1"
AUTHORIZATION_EVALUATION_SCHEMA = "apts-execution-authorization-evaluation-v1"
AUTHORIZATION_ATTESTATION_SCHEMA = "apts-gss-execution-revalidation-v1"
AUTHORIZATION_RECORD_SCHEMA = "apts-execution-authorization-record-v1"
AUTHORIZATION_CONTRACT_DOMAIN = "APTS_STAGE6_2_AUTHORIZATION_CONTRACT_V1"
AUTHORIZATION_EVALUATION_DOMAIN = "APTS_STAGE6_2_AUTHORIZATION_EVALUATION_V1"
AUTHORIZATION_RECORD_DOMAIN = "APTS_STAGE6_2_AUTHORIZATION_RECORD_V1"
AUTHORIZATION_MIGRATION_LEVEL = 2
MAX_AUTHORIZATION_TTL_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 5
AUTHORIZATION_BOUNDARIES = {
    "authorization_minted_locally": False, "authorization_is_dispatch": False,
    "dispatch_performed": False, "tool_invocation_performed": False,
    "target_network_io_performed": False, "target_actuation": False,
    "action_result_created": False, "new_target_evidence_created": False,
    "specialist_raw_target_access": False,
}


class ExecutionGovernanceUnavailable(RuntimeError):
    pass


class ExecutionGovernanceProtocolError(RuntimeError):
    pass


def utc_timestamp(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ExecutionRequestValidationError("authorization clock must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ExecutionGovernanceProtocolError(f"{field} must be an explicit timezone-aware timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone missing")
        return dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise ExecutionGovernanceProtocolError(f"invalid {field}") from exc


def normalize_authorization_intake(payload: Any) -> dict[str, Any]:
    obj = require_object(payload, {"schema_version", "revalidation_id", "idempotency_key",
                                 "execution_id", "envelope_sha256", "requested_by"}, "authorization intake")
    if obj["schema_version"] != AUTHORIZATION_INTAKE_SCHEMA:
        raise ExecutionRequestValidationError("unsupported execution authorization intake schema")
    return {
        "schema_version": AUTHORIZATION_INTAKE_SCHEMA,
        "revalidation_id": require_id(obj["revalidation_id"], "revalidation_id", "eauthreq-"),
        "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key"),
        "execution_id": require_id(obj["execution_id"], "execution_id", "exec-"),
        "envelope_sha256": require_sha(obj["envelope_sha256"], "envelope_sha256"),
        "requested_by": require_id(obj["requested_by"], "requested_by"),
    }


def authorization_intake_json_schema() -> dict[str, Any]:
    props = {key: {"type": "string", "pattern": ID_PATTERN, "maxLength": 200}
             for key in ("revalidation_id", "idempotency_key", "execution_id", "requested_by")}
    props["schema_version"] = {"const": AUTHORIZATION_INTAKE_SCHEMA}
    props["revalidation_id"]["pattern"] = r"^eauthreq-[A-Za-z0-9._:@\-]+$"
    props["execution_id"]["pattern"] = r"^exec-[A-Za-z0-9._:@\-]+$"
    props["envelope_sha256"] = {"type": "string", "pattern": SHA_PATTERN}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "additionalProperties": False, "required": list(props), "properties": props}


def gss_revalidation_json_schema() -> dict[str, Any]:
    props = {key: {"type": "string", "pattern": SHA_PATTERN}
             for key in ("evaluation_sha256", "request_sha256", "envelope_sha256", "context_sha256")}
    props.update({"schema_version": {"const": AUTHORIZATION_ATTESTATION_SCHEMA},
                  "nonce": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                  "execution_id": {"type": "string", "pattern": r"^exec-[A-Za-z0-9._:@\-]+$", "maxLength": 200},
                  "checked_at": {"type": "string", "format": "date-time"},
                  "checks": {"type": "object", "additionalProperties": False,
                             "required": list(REQUIRED_AUTHORIZATION_CHECKS),
                             "properties": {key: {"enum": ["PASS", "FAIL", "REVIEW"]} for key in REQUIRED_AUTHORIZATION_CHECKS}},
                  **{key: {"type": "boolean"} for key in ("revoked", "emergency_stop", "human_approval_verified")}})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "additionalProperties": False, "required": list(props), "properties": props}


def canonical_execution_authorization_contract() -> dict[str, Any]:
    return with_integrity({
        "schema_version": AUTHORIZATION_CONTRACT_SCHEMA,
        "control_version": EXECUTION_AUTHORIZATION_CONTROL_VERSION,
        "predecessor": {"control": EXECUTION_REQUEST_CONTROL_VERSION,
                        "contract_sha256": canonical_execution_request_contract()["integrity"]["canonical_sha256"]},
        "authority": "EXTERNAL_APTS_GSS", "fail_closed": True,
        "deliverables": {"execution_authorization_gate": True},
        "decisions": ["ALLOW", "DENY", "REVIEW"],
        "required_checks": list(REQUIRED_AUTHORIZATION_CHECKS),
        "intake_schema_version": AUTHORIZATION_INTAKE_SCHEMA,
        "evaluation_schema_version": AUTHORIZATION_EVALUATION_SCHEMA,
        "gss_attestation_schema_version": AUTHORIZATION_ATTESTATION_SCHEMA,
        "authorization_intake_json_schema": authorization_intake_json_schema(),
        "gss_execution_revalidation_json_schema": gss_revalidation_json_schema(),
        "record_schema_version": AUTHORIZATION_RECORD_SCHEMA,
        "transport": {"endpoint": "/api/governance/authorization/evaluate",
                      "response": "status=completed / policy_decision.execution_revalidation",
                      "configured_endpoint_only": True, "redirects_allowed": False,
                      "remote_https_required": True, "hash_is_authentication": False},
        "source": {"mission_migration_level": 53, "pentest_migration_level": 16,
                   "supported_source_types": ["PERSISTED_STAGE5_6_EXPLOIT_ACTION_PROPOSAL",
                                              "STAGE5_2_RECON_ACTION_REQUEST",
                                              "STAGE5_3_ENUMERATION_ACTION_PROPOSAL",
                                              "WPT_GOVERNED_INTAKE"],
                   "mission_and_pentest_read_only": True, "mission_state_required": "RUNNING",
                   "recheck_sources_after_governance": True},
        "repository": {"migration_level": AUTHORIZATION_MIGRATION_LEVEL,
                       "store": "execution_authorizations", "append_only": True,
                       "request_store_unchanged": True},
        "max_authorization_ttl_seconds": MAX_AUTHORIZATION_TTL_SECONDS,
        "max_clock_skew_seconds": MAX_CLOCK_SKEW_SECONDS,
        "replay_semantics": "HISTORICAL_AUDIT_ONLY_NEW_KEY_REQUIRED_FOR_FRESH_REVALIDATION",
        "dispatch_requires_fresh_revalidation": True,
        "runtime_self_certification": False, "runtime": dict(AUTHORIZATION_BOUNDARIES),
        "next_stage": "6.3",
    }, AUTHORIZATION_CONTRACT_DOMAIN)


def verify_execution_authorization_contract(value: Any) -> bool:
    try:
        return canonical_json(value) == canonical_json(canonical_execution_authorization_contract())
    except (TypeError, ValueError, RecursionError):
        return False


def build_evaluation(envelope: dict[str, Any], intake: dict[str, Any], context: dict[str, Any],
                     local_checks: dict[str, str], *, nonce: str, submitted_at: str) -> dict[str, Any]:
    request = envelope["execution_request"]
    return with_integrity({
        "schema_version": AUTHORIZATION_EVALUATION_SCHEMA,
        "revalidation_id": intake["revalidation_id"], "nonce": nonce,
        "submitted_at": submitted_at, "intake": deepcopy(intake),
        "execution_request": deepcopy(request), "envelope_sha256": intake["envelope_sha256"],
        "source_binding": deepcopy(envelope["source_binding"]),
        "current_context": deepcopy(context), "local_checks": dict(local_checks),
        "required_checks": list(REQUIRED_AUTHORIZATION_CHECKS),
    }, AUTHORIZATION_EVALUATION_DOMAIN)


def validate_authoritative_decision(response: Any, evaluation: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Fail closed on missing proof, stale decisions and partial/ambiguous checks."""
    try:
        if not isinstance(response, dict):
            raise ExecutionRequestValidationError("PolicyDecision must be an object")
        decision = deepcopy(response)
        for key in ("decision_id", "request_id", "mission_id", "scope_contract_id", "policy_set_id"):
            require_id(decision.get(key), key)
        require_sha(decision.get("decision_hash"), "decision_hash")
        for key in ("scope_version", "policy_version"):
            if type(decision.get(key)) is not int or not 1 <= decision[key] <= 2**63 - 1:
                raise ExecutionRequestValidationError(f"invalid {key}")
        if decision.get("decision") not in ("ALLOW", "DENY", "REVIEW"):
            raise ExecutionRequestValidationError("invalid PolicyDecision decision")
        if type(decision.get("requires_human_approval")) is not bool:
            raise ExecutionRequestValidationError("explicit requires_human_approval is mandatory")
        require_object(decision.get("constraints"), set(decision.get("constraints", {})) if isinstance(decision.get("constraints"), dict) else set(), "constraints")
        reasons = decision.get("reason_codes")
        if not isinstance(reasons, list) or len(reasons) > 100:
            raise ExecutionRequestValidationError("reason_codes must be a bounded list")
        for reason in reasons:
            require_text(reason, "reason_codes[]")
        proof = require_object(decision.get("execution_revalidation"), {
            "schema_version", "evaluation_sha256", "nonce", "execution_id",
            "request_sha256", "envelope_sha256", "context_sha256", "checked_at",
            "checks", "revoked", "emergency_stop", "human_approval_verified",
        }, "execution_revalidation")
        if proof["schema_version"] != AUTHORIZATION_ATTESTATION_SCHEMA:
            raise ExecutionRequestValidationError("unsupported GSS execution revalidation protocol")
        request = evaluation["execution_request"]
        context = evaluation["current_context"]
        gov = context["governance_authority"]
        expected = {
            "evaluation_sha256": evaluation["integrity"]["canonical_sha256"],
            "nonce": evaluation["nonce"], "execution_id": request["execution_id"],
            "request_sha256": request["integrity"]["canonical_sha256"],
            "envelope_sha256": evaluation["envelope_sha256"],
            "context_sha256": sha256_hex(context),
        }
        if any(proof[key] != value for key, value in expected.items()):
            raise ExecutionRequestValidationError("PolicyDecision execution/request/nonce/context correlation mismatch")
        if (decision["mission_id"] != request["mission_id"]
                or decision["scope_contract_id"] != gov["governance_scope_contract_id"]
                or decision["scope_version"] != gov["governance_scope_version"]
                or decision["policy_set_id"] != gov["policy_set_id"]):
            raise ExecutionRequestValidationError("PolicyDecision current mission/scope/policy binding mismatch")
        old_policy = request["authorization_requirement"]["policy_reference"]
        if (decision["decision_id"] == old_policy["policy_decision_id"]
                or decision["policy_version"] < old_policy["policy_version"]):
            raise ExecutionRequestValidationError("historical decision or policy downgrade cannot authorize execution")
        checks = require_object(proof["checks"], REQUIRED_AUTHORIZATION_CHECKS, "checks")
        if any(type(value) is not str or value not in ("PASS", "FAIL", "REVIEW") for value in checks.values()):
            raise ExecutionRequestValidationError("every authorization check requires an explicit PASS/FAIL/REVIEW result")
        for key in ("revoked", "emergency_stop", "human_approval_verified"):
            if type(proof[key]) is not bool:
                raise ExecutionRequestValidationError(f"{key} must be an explicit boolean")
        start = parse_time(decision.get("valid_from"), "valid_from")
        end = parse_time(decision.get("valid_until"), "valid_until")
        checked = parse_time(proof["checked_at"], "checked_at")
        submitted = parse_time(evaluation["submitted_at"], "submitted_at")
        skew = timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
        if end <= start or not start <= now < end:
            raise ExecutionRequestValidationError("PolicyDecision is expired or not yet valid")
        if (checked < submitted - skew or checked > now + skew or not start <= checked < end
                or (now - submitted).total_seconds() > MAX_AUTHORIZATION_TTL_SECONDS
                or now < submitted - skew):
            raise ExecutionRequestValidationError("PolicyDecision freshness check failed")
        # Canonical JSON also rejects non-finite values anywhere in the response.
        canonical_json(decision)
        return decision
    except (ExecutionRequestValidationError, KeyError, TypeError, ValueError, RecursionError) as exc:
        raise ExecutionGovernanceProtocolError(str(exc)) from exc


def make_authorization_record(evaluation: dict[str, Any], decision: dict[str, Any], *, received_at: str) -> dict[str, Any]:
    require_object(evaluation, {"schema_version", "revalidation_id", "nonce", "submitted_at", "intake",
                               "execution_request", "envelope_sha256", "source_binding", "current_context",
                               "local_checks", "required_checks", "integrity"}, "authorization evaluation")
    intake = normalize_authorization_intake(evaluation["intake"])
    request = evaluation["execution_request"]
    from .execution_contract import verify_execution_request
    if (not verify_integrity(evaluation, AUTHORIZATION_EVALUATION_DOMAIN)
            or not verify_execution_request(request)
            or evaluation["schema_version"] != AUTHORIZATION_EVALUATION_SCHEMA
            or evaluation["required_checks"] != list(REQUIRED_AUTHORIZATION_CHECKS)
            or evaluation["revalidation_id"] != intake["revalidation_id"]
            or evaluation["envelope_sha256"] != intake["envelope_sha256"]
            or request["execution_id"] != intake["execution_id"]
            or evaluation["current_context"]["mission_id"] != request["mission_id"]
            or evaluation["current_context"]["mission_state"] != "RUNNING"
            or not isinstance(evaluation["nonce"], str) or len(evaluation["nonce"]) != 32
            or any(c not in "0123456789abcdef" for c in evaluation["nonce"])):
        raise ExecutionRequestValidationError("invalid authorization evaluation binding")
    decision = validate_authoritative_decision(decision, evaluation, parse_time(received_at, "received_at"))
    proof = decision["execution_revalidation"]
    req = evaluation["execution_request"]
    checks = proof["checks"]
    denied = (decision["decision"] == "DENY" or "FAIL" in checks.values()
              or proof["revoked"] or proof["emergency_stop"])
    current_review = any(req["action"]["action_class"] in ctx.get("roe", {}).get("human_approval_required_for", [])
                         for ctx in (evaluation["current_context"]["mission_scope"],
                                     evaluation["current_context"]["pentest_context"]["boundary"]))
    needs_review = (decision["decision"] == "REVIEW" or "REVIEW" in checks.values()
                    or decision["requires_human_approval"]
                    or ((req["authorization_requirement"]["human_review_required"] or current_review)
                        and not proof["human_approval_verified"]))
    result = "DENY" if denied else "REVIEW" if needs_review else "ALLOW"
    deadline = min(parse_time(decision["valid_until"], "valid_until"),
                   parse_time(received_at, "received_at") + timedelta(seconds=MAX_AUTHORIZATION_TTL_SECONDS))
    return with_integrity({
        "schema_version": AUTHORIZATION_RECORD_SCHEMA,
        "control_version": EXECUTION_AUTHORIZATION_CONTROL_VERSION,
        "authorization_id": "eauth-" + sha256_hex(evaluation["intake"])[:32],
        "execution_id": req["execution_id"], "mission_id": req["mission_id"],
        "task_id": req["task_id"], "pentest_id": req["pentest_id"],
        "intake": deepcopy(evaluation["intake"]), "evaluation": deepcopy(evaluation),
        "policy_decision": decision, "decision": result,
        "execution_authorized_at_evaluation": result == "ALLOW",
        "valid_until": utc_timestamp(deadline), "received_at": received_at,
        "checks": deepcopy(checks), "authority": "EXTERNAL_APTS_GSS",
        "revalidation_required_before_dispatch": True,
        "semantics": dict(AUTHORIZATION_BOUNDARIES),
    }, AUTHORIZATION_RECORD_DOMAIN)


def verify_authorization_record(value: Any) -> bool:
    try:
        if not verify_integrity(value, AUTHORIZATION_RECORD_DOMAIN):
            return False
        evaluation = value["evaluation"]
        if not verify_integrity(evaluation, AUTHORIZATION_EVALUATION_DOMAIN):
            return False
        from .execution_contract import verify_execution_request
        if (not verify_execution_request(evaluation["execution_request"])
                or normalize_authorization_intake(evaluation["intake"]) != evaluation["intake"]
                or evaluation["schema_version"] != AUTHORIZATION_EVALUATION_SCHEMA
                or evaluation["required_checks"] != list(REQUIRED_AUTHORIZATION_CHECKS)
                or evaluation["local_checks"] != {k: "PASS" for k in ("SCOPE", "ROE", "RISK", "TARGET", "TECHNIQUE")}):
            return False
        return canonical_json(value) == canonical_json(make_authorization_record(
            evaluation, value["policy_decision"], received_at=value["received_at"]))
    except (ExecutionGovernanceProtocolError, TypeError, ValueError, KeyError, RecursionError):
        return False
