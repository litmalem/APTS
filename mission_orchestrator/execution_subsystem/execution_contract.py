from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import re
from typing import Any, Mapping

from pentest_subsystem.agentic_pentest_acceptance_gate import (
    AGENTIC_PENTEST_ACCEPTANCE_CONTROL_VERSION,
    canonical_agentic_pentest_acceptance_gate_contract,
)

EXECUTION_REQUEST_CONTROL_VERSION = "stage6.1-canonical-execution-request-contract"
EXECUTION_REQUEST_CONTRACT_SCHEMA_VERSION = "apts-stage6.1-canonical-execution-request-contract-v1"
EXECUTION_REQUEST_SCHEMA_VERSION = "apts-execution-request-v1"
EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION = "apts-execution-request-intake-v1"
RECON_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION = "apts-execution-request-intake-v2"
ENUMERATION_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION = "apts-execution-request-intake-v3"
WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION = "apts-execution-request-intake-v4"
CANONICAL_ACTION_ENVELOPE_SCHEMA_VERSION = "apts-canonical-action-envelope-v1"
EXECUTION_REQUEST_HASH_DOMAIN = "APTS_STAGE6_1_EXECUTION_REQUEST_V1"
EXECUTION_REQUEST_CONTRACT_HASH_DOMAIN = "APTS_STAGE6_1_EXECUTION_REQUEST_CONTRACT_V1"
ACTION_ENVELOPE_HASH_DOMAIN = "APTS_STAGE6_1_CANONICAL_ACTION_ENVELOPE_V1"
EXECUTION_ID_HASH_DOMAIN = "APTS_STAGE6_1_EXECUTION_ID_V1"
EXECUTION_REPOSITORY_MIGRATION_LEVEL = 1
EXECUTION_REQUEST_NEXT_STAGE = "6.2"
EXECUTION_REQUEST_STATUS = "AWAITING_AUTHORIZATION"
MAX_INTAKE_BYTES = 65536

EXECUTION_REQUEST_FIELDS = (
    "execution_id", "mission_id", "task_id", "pentest_id", "proposing_agent",
    "action", "target", "parameters", "evidence_basis", "authorization_requirement",
)
REQUIRED_AUTHORIZATION_CHECKS = (
    "SCOPE", "ROE", "POLICY", "RISK", "EXPIRY", "REVOCATION", "TARGET", "TECHNIQUE",
)
REQUEST_SEMANTICS = {
    "request_is_authorization": False,
    "authorization_minted": False,
    "execution_authorized": False,
    "dispatch_performed": False,
    "tool_invocation_performed": False,
    "external_network_io_performed": False,
    "target_actuation": False,
    "action_result_created": False,
    "new_target_evidence_created": False,
}
SOURCE_BINDING_FIELDS = (
    "pentest_task_id", "task_artifact_sha256", "task_binding_sha256",
    "source_run_output_sha256", "source_run_evidence_bundle_sha256",
    "action_proposal_ref", "action_proposal_sha256", "orchestration_graph_sha256",
    "scope_sha256", "roe_sha256", "constraints_sha256", "policy_reference_sha256",
    "validation_decision_sha256", "exploitation_decision_sha256",
    "stage5_closure_contract_sha256",
)
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,199}$"
SHA_PATTERN = r"^[0-9a-f]{64}$"


class ExecutionRequestValidationError(ValueError):
    pass


class ExecutionRequestIntegrityError(RuntimeError):
    pass


class ExecutionRequestConflict(RuntimeError):
    pass


class ExecutionSourceUnavailable(RuntimeError):
    pass


class ExecutionSourceNotFound(RuntimeError):
    pass


class ExecutionSourceRejected(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def with_integrity(core: Mapping[str, Any], domain: str) -> dict[str, Any]:
    body = deepcopy(dict(core))
    return {
        **body,
        "integrity": {
            "algorithm": "SHA-256", "canonicalization": "UTF8_SORTED_JSON_V1",
            "hash_domain": domain,
            "canonical_sha256": sha256_hex({"hash_domain": domain, "core": body}),
        },
    }


def verify_integrity(item: Any, domain: str) -> bool:
    if not isinstance(item, dict):
        return False
    try:
        core = {key: value for key, value in item.items() if key != "integrity"}
        return canonical_json(item) == canonical_json(with_integrity(core, domain))
    except (TypeError, ValueError, RecursionError):
        return False


def require_object(value: Any, fields: tuple[str, ...] | set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ExecutionRequestValidationError(f"{field} must contain exactly: {', '.join(sorted(fields))}")
    return value


def require_id(value: Any, field: str, prefix: str = "") -> str:
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value) or not value.startswith(prefix):
        raise ExecutionRequestValidationError(f"{field} must be a canonical {prefix or 'identifier'} string")
    return value


def require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(SHA_PATTERN, value):
        raise ExecutionRequestValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def require_text(value: Any, field: str, max_length: int = 2000) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > max_length or any(ord(c) < 32 for c in value)):
        raise ExecutionRequestValidationError(f"{field} must be bounded text without surrounding whitespace or controls")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ExecutionRequestValidationError(f"{field} must be valid UTF-8 text") from exc
    return value


def normalize_execution_request_intake(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExecutionRequestValidationError("execution request intake must be an object")
    common = {"schema_version", "request_id", "idempotency_key"}
    version = payload.get("schema_version")
    if version == EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION:
        obj = require_object(payload, common | {"exploitation_run_id", "exploit_action_proposal_id", "proposal_sha256"}, "execution request intake")
        return {"schema_version": version,
                "request_id": require_id(obj["request_id"], "request_id", "ereq-"),
                "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key"),
                "exploitation_run_id": require_id(obj["exploitation_run_id"], "exploitation_run_id", "xplrun-"),
                "exploit_action_proposal_id": require_id(obj["exploit_action_proposal_id"], "exploit_action_proposal_id", "xplprop-"),
                "proposal_sha256": require_sha(obj["proposal_sha256"], "proposal_sha256")}
    if version == RECON_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION:
        obj = require_object(payload, common | {"source_type", "recon_action_id", "recon_request_sha256"}, "Recon execution request intake")
        if obj["source_type"] != "STAGE5_2_RECON_ACTION_REQUEST":
            raise ExecutionRequestValidationError("unsupported Stage 6.1 source_type")
        return {"schema_version": version, "source_type": obj["source_type"],
                "request_id": require_id(obj["request_id"], "request_id", "ereq-"),
                "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key"),
                "recon_action_id": require_id(obj["recon_action_id"], "recon_action_id", "rareq-"),
                "recon_request_sha256": require_sha(obj["recon_request_sha256"], "recon_request_sha256")}
    if version == ENUMERATION_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION:
        obj = require_object(payload, common | {"source_type", "enumeration_run_id", "enumeration_proposal_ref", "proposal_sha256"}, "Enumeration execution request intake")
        if obj["source_type"] != "STAGE5_3_ENUMERATION_ACTION_PROPOSAL":
            raise ExecutionRequestValidationError("unsupported Stage 6.1 source_type")
        return {"schema_version": version, "source_type": obj["source_type"],
                "request_id": require_id(obj["request_id"], "request_id", "ereq-"),
                "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key"),
                "enumeration_run_id": require_id(obj["enumeration_run_id"], "enumeration_run_id", "enumrun-"),
                "enumeration_proposal_ref": require_id(obj["enumeration_proposal_ref"], "enumeration_proposal_ref", "actp-"),
                "proposal_sha256": require_sha(obj["proposal_sha256"], "proposal_sha256")}
    if version == WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION:
        obj = require_object(payload, common | {"source_type", "wpt_intake_id", "wpt_intake_sha256"}, "WPT execution request intake")
        if obj["source_type"] != "WPT_GOVERNED_INTAKE":
            raise ExecutionRequestValidationError("unsupported Stage 6.1 WPT source_type")
        return {"schema_version": version, "source_type": obj["source_type"],
                "request_id": require_id(obj["request_id"], "request_id", "ereq-"),
                "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key", "idem-"),
                "wpt_intake_id": require_id(obj["wpt_intake_id"], "wpt_intake_id", "wptreq-"),
                "wpt_intake_sha256": require_sha(obj["wpt_intake_sha256"], "wpt_intake_sha256")}
    raise ExecutionRequestValidationError("unsupported execution request intake schema_version")


def deterministic_execution_id(mission_id: str, task_id: str, pentest_id: str, idempotency_key: str) -> str:
    for key, value in (("mission_id", mission_id), ("task_id", task_id),
                       ("pentest_id", pentest_id), ("idempotency_key", idempotency_key)):
        require_id(value, key)
    return "exec-" + sha256_hex({
        "hash_domain": EXECUTION_ID_HASH_DOMAIN, "mission_id": mission_id,
        "task_id": task_id, "pentest_id": pentest_id, "idempotency_key": idempotency_key,
    })[:32]


def normalize_execution_request(payload: Any) -> dict[str, Any]:
    obj = require_object(payload, set(EXECUTION_REQUEST_FIELDS) | {"schema_version"}, "ExecutionRequest")
    if obj["schema_version"] != EXECUTION_REQUEST_SCHEMA_VERSION:
        raise ExecutionRequestValidationError("unsupported ExecutionRequest schema_version")
    result = {"schema_version": EXECUTION_REQUEST_SCHEMA_VERSION}
    for key, prefix in (("execution_id", "exec-"), ("mission_id", "mission-gmo-"),
                        ("task_id", "ptask-"), ("pentest_id", "pentest-")):
        result[key] = require_id(obj[key], key, prefix)
    agent = require_object(obj["proposing_agent"], {"agent_id", "role", "orchestration_id", "subtask_id"}, "proposing_agent")
    result["proposing_agent"] = {key: require_id(value, f"proposing_agent.{key}") for key, value in agent.items()}
    action = require_object(obj["action"], {"action_class", "capability_id", "technique"}, "action")
    result["action"] = {
        "action_class": require_id(action["action_class"], "action.action_class"),
        "capability_id": require_id(action["capability_id"], "action.capability_id"),
        "technique": require_text(action["technique"], "action.technique"),
    }
    target = require_object(obj["target"], {"target_type", "target_value"}, "target")
    result["target"] = {
        "target_type": require_id(target["target_type"], "target.target_type"),
        "target_value": require_text(target["target_value"], "target.target_value"),
    }
    params = obj["parameters"]
    if not isinstance(params, dict) or set(params) not in (
            {"validation_task_id", "expected_evidence", "estimated_impact"},
            {"source_action_id", "expected_evidence", "estimated_impact"},
            {"source_proposal_id", "expected_evidence", "estimated_impact"},
            {"source_wpt_intake_id", "expected_evidence", "estimated_impact"}):
        raise ExecutionRequestValidationError("parameters must bind a validation task, persisted Recon/Enumeration proposal, or governed WPT intake")
    expected = params["expected_evidence"]
    if not isinstance(expected, list) or len(expected) > 100:
        raise ExecutionRequestValidationError("parameters.expected_evidence must be a bounded array")
    if (not isinstance(params["estimated_impact"], str)
            or params["estimated_impact"] not in {"NONE", "LOW", "MODERATE", "HIGH", "CRITICAL", "DESTRUCTIVE"}):
        raise ExecutionRequestValidationError("parameters.estimated_impact is unsupported")
    parameter_source_field = ("validation_task_id" if "validation_task_id" in params else
        "source_wpt_intake_id" if "source_wpt_intake_id" in params else
        "source_proposal_id" if "source_proposal_id" in params else "source_action_id")
    result["parameters"] = {
        parameter_source_field: require_id(params[parameter_source_field], f"parameters.{parameter_source_field}",
                                           "valtask-" if parameter_source_field == "validation_task_id" else
                                           "actp-" if parameter_source_field == "source_proposal_id" else
                                           "wptreq-" if parameter_source_field == "source_wpt_intake_id" else "rareq-"),
        "expected_evidence": [require_text(x, "parameters.expected_evidence[]") for x in expected],
        "estimated_impact": params["estimated_impact"],
    }
    refs = obj["evidence_basis"]
    if not isinstance(refs, list) or not 1 <= len(refs) <= 500:
        raise ExecutionRequestValidationError("evidence_basis must contain 1-500 evidence references")
    normalized_refs = []
    for ref in refs:
        require_object(ref, {"evidence_id", "canonical_sha256"}, "evidence_basis[]")
        normalized_refs.append({
            "evidence_id": require_id(ref["evidence_id"], "evidence_basis.evidence_id", "evi-"),
            "canonical_sha256": require_sha(ref["canonical_sha256"], "evidence_basis.canonical_sha256"),
        })
    if len({x["evidence_id"] for x in normalized_refs}) != len(normalized_refs):
        raise ExecutionRequestValidationError("evidence_basis must not contain duplicate evidence identities")
    result["evidence_basis"] = sorted(normalized_refs, key=lambda x: x["evidence_id"])
    auth = require_object(obj["authorization_requirement"], {
        "authority", "revalidation_required", "required_checks", "human_review_required", "policy_reference",
    }, "authorization_requirement")
    if auth["authority"] != "EXTERNAL_APTS_GSS" or auth["revalidation_required"] is not True:
        raise ExecutionRequestValidationError("external GSS revalidation is mandatory")
    if auth["required_checks"] != list(REQUIRED_AUTHORIZATION_CHECKS):
        raise ExecutionRequestValidationError("all Stage 6.2 authorization checks are mandatory")
    if type(auth["human_review_required"]) is not bool:
        raise ExecutionRequestValidationError("human_review_required must be boolean")
    policy = require_object(auth["policy_reference"], {
        "policy_decision_id", "policy_decision_hash", "policy_version", "reference_sha256",
    }, "authorization_requirement.policy_reference")
    if type(policy["policy_version"]) is not int or not 1 <= policy["policy_version"] <= 2**63 - 1:
        raise ExecutionRequestValidationError("policy_version must be a positive integer")
    result["authorization_requirement"] = {
        "authority": "EXTERNAL_APTS_GSS", "revalidation_required": True,
        "required_checks": list(REQUIRED_AUTHORIZATION_CHECKS),
        "human_review_required": auth["human_review_required"],
        "policy_reference": {
            "policy_decision_id": require_id(policy["policy_decision_id"], "policy_decision_id"),
            "policy_decision_hash": require_sha(policy["policy_decision_hash"], "policy_decision_hash"),
            "policy_version": policy["policy_version"],
            "reference_sha256": require_sha(policy["reference_sha256"], "reference_sha256"),
        },
    }
    return result


def seal_execution_request(payload: Any) -> dict[str, Any]:
    return with_integrity(normalize_execution_request(payload), EXECUTION_REQUEST_HASH_DOMAIN)


def verify_execution_request(request: Any) -> bool:
    try:
        core = {key: value for key, value in request.items() if key != "integrity"}
        return canonical_json(request) == canonical_json(seal_execution_request(core))
    except (AttributeError, TypeError, ValueError, RecursionError):
        return False


def execution_request_json_schema() -> dict[str, Any]:
    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": False,
                "required": list(properties), "properties": properties}
    ident = {"type": "string", "pattern": ID_PATTERN, "maxLength": 200}
    digest = {"type": "string", "pattern": SHA_PATTERN}
    text = {"type": "string", "minLength": 1, "maxLength": 2000,
            "pattern": r"^[^\s\x00-\x1f\ud800-\udfff](?:[^\x00-\x1f\ud800-\udfff]*[^\s\x00-\x1f\ud800-\udfff])?$"}
    def prefixed(prefix: str) -> dict[str, Any]:
        return {**ident, "pattern": "^" + prefix + r"[A-Za-z0-9._:@\-]*$"}
    schema = obj({
        "schema_version": {"const": EXECUTION_REQUEST_SCHEMA_VERSION},
        "execution_id": prefixed("exec-"), "mission_id": prefixed("mission-gmo-"),
        "task_id": prefixed("ptask-"), "pentest_id": prefixed("pentest-"),
        "proposing_agent": obj({key: ident for key in ("agent_id", "role", "orchestration_id", "subtask_id")}),
        "action": obj({"action_class": ident, "capability_id": ident, "technique": text}),
        "target": obj({"target_type": ident, "target_value": text}),
        "parameters": {"oneOf": [
            obj({"validation_task_id": prefixed("valtask-"),
                 "expected_evidence": {"type": "array", "maxItems": 100, "items": text},
                 "estimated_impact": {"enum": ["NONE", "LOW", "MODERATE", "HIGH", "CRITICAL", "DESTRUCTIVE"]}}),
            obj({"source_action_id": prefixed("rareq-"),
                 "expected_evidence": {"type": "array", "maxItems": 100, "items": text},
                 "estimated_impact": {"enum": ["NONE", "LOW", "MODERATE", "HIGH", "CRITICAL", "DESTRUCTIVE"]}}),
            obj({"source_proposal_id": prefixed("actp-"),
                 "expected_evidence": {"type": "array", "maxItems": 100, "items": text},
                 "estimated_impact": {"enum": ["NONE", "LOW", "MODERATE", "HIGH", "CRITICAL", "DESTRUCTIVE"]}}),
            obj({"source_wpt_intake_id": prefixed("wptreq-"),
                 "expected_evidence": {"type": "array", "maxItems": 100, "items": text},
                 "estimated_impact": {"enum": ["NONE", "LOW", "MODERATE", "HIGH", "CRITICAL", "DESTRUCTIVE"]}})]},
        "evidence_basis": {"type": "array", "minItems": 1, "maxItems": 500, "uniqueItems": True,
                           "items": obj({"evidence_id": prefixed("evi-"), "canonical_sha256": digest})},
        "authorization_requirement": obj({
            "authority": {"const": "EXTERNAL_APTS_GSS"}, "revalidation_required": {"const": True},
            "required_checks": {"const": list(REQUIRED_AUTHORIZATION_CHECKS)},
            "human_review_required": {"type": "boolean"},
            "policy_reference": obj({"policy_decision_id": ident, "policy_decision_hash": digest,
                                     "policy_version": {"type": "integer", "minimum": 1, "maximum": 2**63 - 1},
                                     "reference_sha256": digest}),
        }),
    })
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": EXECUTION_REQUEST_SCHEMA_VERSION, "title": "APTS ExecutionRequest core", **schema}


def canonical_action_envelope_json_schema() -> dict[str, Any]:
    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": False,
                "required": list(properties), "properties": properties}
    ident = {"type": "string", "pattern": ID_PATTERN, "maxLength": 200}
    digest = {"type": "string", "pattern": SHA_PATTERN}
    def integrity(domain: str) -> dict[str, Any]:
        return obj({"algorithm": {"const": "SHA-256"}, "canonicalization": {"const": "UTF8_SORTED_JSON_V1"},
                    "hash_domain": {"const": domain}, "canonical_sha256": digest})
    request = execution_request_json_schema()
    request.pop("$schema")
    request.pop("$id")
    request["properties"]["integrity"] = integrity(EXECUTION_REQUEST_HASH_DOMAIN)
    request["required"].append("integrity")
    binding = {key: digest if key.endswith("sha256") else ident for key in SOURCE_BINDING_FIELDS}
    schema = obj({
        "schema_version": {"const": CANONICAL_ACTION_ENVELOPE_SCHEMA_VERSION},
        "control_version": {"const": EXECUTION_REQUEST_CONTROL_VERSION}, "contract_sha256": digest,
        "intake": {"oneOf": [
            obj({"schema_version": {"const": EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION},
                 "request_id": ident, "idempotency_key": ident, "exploitation_run_id": ident,
                 "exploit_action_proposal_id": ident, "proposal_sha256": digest}),
            obj({"schema_version": {"const": RECON_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION},
                 "source_type": {"const": "STAGE5_2_RECON_ACTION_REQUEST"}, "request_id": ident,
                 "idempotency_key": ident, "recon_action_id": ident, "recon_request_sha256": digest}),
            obj({"schema_version": {"const": ENUMERATION_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION},
                 "source_type": {"const": "STAGE5_3_ENUMERATION_ACTION_PROPOSAL"}, "request_id": ident,
                 "idempotency_key": ident, "enumeration_run_id": ident, "enumeration_proposal_ref": ident,
                 "proposal_sha256": digest}),
            obj({"schema_version": {"const": WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION},
                 "source_type": {"const": "WPT_GOVERNED_INTAKE"}, "request_id": ident,
                 "idempotency_key": ident, "wpt_intake_id": ident, "wpt_intake_sha256": digest})]},
        "execution_request": request, "source_binding": obj(binding),
        "status": {"const": EXECUTION_REQUEST_STATUS},
        "semantics": {"const": dict(REQUEST_SEMANTICS)}, "integrity": integrity(ACTION_ENVELOPE_HASH_DOMAIN),
    })
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": CANONICAL_ACTION_ENVELOPE_SCHEMA_VERSION, "title": "APTS canonical action envelope", **schema}


@lru_cache(maxsize=1)
def _contract() -> dict[str, Any]:
    predecessor = canonical_agentic_pentest_acceptance_gate_contract()
    return with_integrity({
        "schema_version": EXECUTION_REQUEST_CONTRACT_SCHEMA_VERSION,
        "control_version": EXECUTION_REQUEST_CONTROL_VERSION,
        "mode": "CANONICAL_EXECUTION_REQUEST_NO_AUTHORIZATION_OR_DISPATCH",
        "predecessor": {"control": AGENTIC_PENTEST_ACCEPTANCE_CONTROL_VERSION,
                        "contract_sha256": predecessor["integrity"]["canonical_sha256"],
                        "pentest_repository_migration_level": 16},
        "deliverables": {"execution_request_schema": True, "canonical_action_envelope": True},
        "request_schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
        "envelope_schema_version": CANONICAL_ACTION_ENVELOPE_SCHEMA_VERSION,
        "required_execution_request_fields": list(EXECUTION_REQUEST_FIELDS),
        "execution_request_json_schema": execution_request_json_schema(),
        "canonical_action_envelope_json_schema": canonical_action_envelope_json_schema(),
        "intake_schema_version": EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
        "supported_proposal_source": "PERSISTED_STAGE5_6_EXPLOIT_ACTION_PROPOSAL",
        "additional_specialist_sources": ["STAGE5_2_RECON_ACTION_REQUEST", "STAGE5_3_ENUMERATION_ACTION_PROPOSAL"],
        "task_id_semantics": "IMMUTABLE_GLOBAL_MISSION_UPSTREAM_TASK_ID",
        "local_task_id_binding": "source_binding.pentest_task_id",
        "repository": {"migration_level": EXECUTION_REPOSITORY_MIGRATION_LEVEL,
                       "store": "execution_requests", "append_only": True, "idempotent": True,
                       "database_isolated_from_pentest": True, "pentest_read_only": True},
        "required_authorization_checks": list(REQUIRED_AUTHORIZATION_CHECKS),
        "request_status": EXECUTION_REQUEST_STATUS,
        "runtime": {"execution_request_creation_enabled": True,
                    "authoritative_source_binding_required": True, **REQUEST_SEMANTICS},
        "invariants": [
            "MISSION_ID_REMAINS_ROOT_LINEAGE", "TASK_ID_RETAINS_GLOBAL_UPSTREAM_TASK_ID",
            "AGENT_ROLE_AND_SUBTASK_ARE_DERIVED_FROM_PERSISTED_ASSIGNMENT",
            "ACTION_TARGET_PARAMETERS_AND_EVIDENCE_ARE_DERIVED_FROM_PERSISTED_PROPOSAL",
            "SCOPE_ROE_CONSTRAINTS_AND_POLICY_REFERENCE_ARE_HASH_BOUND",
            "LOCAL_ELIGIBILITY_IS_NOT_EXECUTION_AUTHORIZATION",
            "EVERY_REQUEST_REQUIRES_STAGE6_2_REVALIDATION",
            "BLOCKED_PROPOSALS_AND_FORGED_EVIDENCE_ARE_REJECTED",
            "CALLER_CANNOT_INJECT_EXECUTABLE_CONTENT_OR_AUTHORIZATION",
            "SPECIALISTS_RETAIN_NO_DIRECT_RAW_TARGET_ACCESS",
            "STAGE6_1_DOES_NOT_DISPATCH_OR_CREATE_TARGET_EVIDENCE",
            "SHA256_IS_CONTENT_INTEGRITY_NOT_AUTHENTICATION_OR_GOVERNANCE",
        ],
        "next_stage": EXECUTION_REQUEST_NEXT_STAGE,
    }, EXECUTION_REQUEST_CONTRACT_HASH_DOMAIN)


def canonical_execution_request_contract() -> dict[str, Any]:
    return deepcopy(_contract())


def verify_execution_request_contract(contract: Any) -> bool:
    try:
        return canonical_json(contract) == canonical_json(canonical_execution_request_contract())
    except (TypeError, ValueError):
        return False


def canonical_execution_request_definition() -> dict[str, Any]:
    c = canonical_execution_request_contract()
    return {"schema_version": c["schema_version"], "control_version": c["control_version"],
            "request_schema_version": EXECUTION_REQUEST_SCHEMA_VERSION,
            "envelope_schema_version": CANONICAL_ACTION_ENVELOPE_SCHEMA_VERSION,
        "intake_schema_versions": [EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
                                       RECON_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
                                       ENUMERATION_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
                                       WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION],
            "required_execution_request_fields": list(EXECUTION_REQUEST_FIELDS),
            "predecessor_control": c["predecessor"]["control"],
            "predecessor_contract_sha256": c["predecessor"]["contract_sha256"],
            "contract_sha256": c["integrity"]["canonical_sha256"],
            "execution_repository_migration_level": EXECUTION_REPOSITORY_MIGRATION_LEVEL,
            "pentest_repository_migration_level": 16, "next_stage": EXECUTION_REQUEST_NEXT_STAGE}


def build_canonical_action_envelope(*, intake: dict[str, Any], request: dict[str, Any],
                                    source_binding: dict[str, Any]) -> dict[str, Any]:
    envelope = with_integrity({
        "schema_version": CANONICAL_ACTION_ENVELOPE_SCHEMA_VERSION,
        "control_version": EXECUTION_REQUEST_CONTROL_VERSION,
        "contract_sha256": canonical_execution_request_contract()["integrity"]["canonical_sha256"],
        "intake": normalize_execution_request_intake(intake), "execution_request": deepcopy(request),
        "source_binding": deepcopy(source_binding), "status": EXECUTION_REQUEST_STATUS,
        "semantics": dict(REQUEST_SEMANTICS),
    }, ACTION_ENVELOPE_HASH_DOMAIN)
    if not verify_canonical_action_envelope(envelope):
        raise ExecutionRequestIntegrityError("canonical action envelope failed verification")
    return envelope


def verify_canonical_action_envelope(envelope: Any) -> bool:
    try:
        require_object(envelope, {"schema_version", "control_version", "contract_sha256", "intake",
                                 "execution_request", "source_binding", "status", "semantics", "integrity"}, "envelope")
        if not verify_integrity(envelope, ACTION_ENVELOPE_HASH_DOMAIN):
            return False
        request = envelope["execution_request"]
        if not verify_execution_request(request):
            return False
        intake = normalize_execution_request_intake(envelope["intake"])
        binding = require_object(envelope["source_binding"], SOURCE_BINDING_FIELDS, "source_binding")
        require_id(binding["pentest_task_id"], "pentest_task_id", "pentest-task-")
        require_id(binding["action_proposal_ref"], "action_proposal_ref", "actp-")
        for key, value in binding.items():
            if key.endswith("sha256"):
                require_sha(value, key)
        c = canonical_execution_request_contract()
        return (
            envelope["schema_version"] == CANONICAL_ACTION_ENVELOPE_SCHEMA_VERSION
            and envelope["control_version"] == EXECUTION_REQUEST_CONTROL_VERSION
            and envelope["contract_sha256"] == c["integrity"]["canonical_sha256"]
            and envelope["status"] == EXECUTION_REQUEST_STATUS
            and canonical_json(envelope["semantics"]) == canonical_json(REQUEST_SEMANTICS)
            and binding["stage5_closure_contract_sha256"] == c["predecessor"]["contract_sha256"]
            and binding["policy_reference_sha256"] == request["authorization_requirement"]["policy_reference"]["reference_sha256"]
            and ((intake["schema_version"] == RECON_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION
                  and request["parameters"].get("source_action_id") == intake["recon_action_id"])
                 or (intake["schema_version"] == ENUMERATION_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION
                     and request["parameters"].get("source_proposal_id") == intake["enumeration_proposal_ref"]
                     and binding["action_proposal_ref"] == intake["enumeration_proposal_ref"])
                 or (intake["schema_version"] == EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION
                     and "validation_task_id" in request["parameters"])
                 or (intake["schema_version"] == WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION
                     and request["parameters"].get("source_wpt_intake_id") == intake["wpt_intake_id"]
                     and binding["action_proposal_ref"] == "actp-wpt-" + intake["wpt_intake_sha256"][:32]))
            and request["execution_id"] == deterministic_execution_id(
                request["mission_id"], request["task_id"], request["pentest_id"], intake["idempotency_key"])
        )
    except (KeyError, TypeError, ValueError, ExecutionRequestValidationError, RecursionError):
        return False
