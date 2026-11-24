from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .adaptation_replan import (
    ADAPTATION_EPISODE_INITIAL_STATE,
    ADAPTATION_REPLAN_ALLOWED_MISSION_STATES,
    verify_adaptation_replan_contract,
)
from .adaptation_trigger import (
    ADAPTATION_TRIGGER_CLASSIFICATION_STATUS,
    verify_adaptation_trigger_classification_contract,
)
from .errors import MissionValidationError
from .governance_binding import verify_binding_contract
from .plan_versioning import verify_plan_version_contract
from .scope_contract import verify_contract

REPLAN_ELIGIBILITY_STAGE_SCHEMA_VERSION = "apts-replan-eligibility-governance-gate-v1"
REPLAN_ELIGIBILITY_CONTRACT_SCHEMA_VERSION = "apts-replan-eligibility-governance-contract-v1"
REPLAN_ELIGIBILITY_HASH_DOMAIN = "MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_V1"
REPLAN_ELIGIBILITY_REQUEST_HASH_DOMAIN = "MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_REQUEST_V1"
REPLAN_ELIGIBILITY_ID_PREFIX = "rpelig-"
REPLAN_ELIGIBILITY_OPERATION_PREFIX = "rpelig-op-"
REPLAN_ELIGIBILITY_MODE = (
    "STATIC_REPLAN_ELIGIBILITY_PLUS_AUTHORITATIVE_GOVERNANCE_FAIL_CLOSED_"
    "NO_REPLAN_COMMAND_NO_PLANNER_NO_SUPERSESSION_NO_ACTUATION"
)
REPLAN_ELIGIBILITY_AUTHORITY = "MISSION_ORCHESTRATOR_WITH_EXTERNAL_APTS_GSS"
REPLAN_ELIGIBILITY_EVENT_TYPE = "MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED"
REPLAN_ELIGIBILITY_STATIC_PASSED = "PASSED"
REPLAN_ELIGIBILITY_STATIC_FAILED = "FAILED"
REPLAN_ELIGIBLE_STATUS = "ELIGIBLE"
REPLAN_NOT_ELIGIBLE_STATUS = "NOT_ELIGIBLE"
REPLAN_REVIEW_REQUIRED_STATUS = "REVIEW_REQUIRED"
REPLAN_ELIGIBILITY_STATUSES = (
    REPLAN_ELIGIBLE_STATUS,
    REPLAN_NOT_ELIGIBLE_STATUS,
    REPLAN_REVIEW_REQUIRED_STATUS,
)
REPLAN_GOVERNANCE_ACTION_CLASS = "INTERNAL_REASONING"
REPLAN_GOVERNANCE_ACTION_NAME = "AUTHORIZE_REPLAN"
REPLAN_GOVERNANCE_RESOURCE_TYPE = "MISSION"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_adaptation_episode_id",
    "expected_classification_id",
    "expected_adaptation_replan_sha256",
    "expected_classification_sha256",
    "expected_classification_event_sha256",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_scope_snapshot_id",
    "expected_scope_sha256",
    "expected_governance_binding_snapshot_id",
    "expected_governance_binding_version",
    "expected_governance_binding_sha256",
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


def new_replan_eligibility_id() -> str:
    return f"{REPLAN_ELIGIBILITY_ID_PREFIX}{uuid.uuid4()}"


def deterministic_replan_eligibility_operation_id(request_sha256: str) -> str:
    return f"{REPLAN_ELIGIBILITY_OPERATION_PREFIX}{request_sha256[:40]}"


def _string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return value


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _string(payload, key, 64).lower()
    if not _SHA_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_replan_eligibility_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("replan eligibility/governance request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported replan eligibility/governance field(s): "
            + ", ".join(unknown)
            + "; Stage 3.7.3 derives static eligibility and the authoritative Governance PolicyDecision "
              "from canonical Mission artifacts. Caller-supplied eligibility results, Governance decisions, "
              "lifecycle REPLAN commands, snapshots, planner outputs, candidates, plan deltas, validation results, "
              "commit/supersession records, dispatch, execution, target actions, or actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_adaptation_episode_id": _string(payload, "expected_adaptation_episode_id"),
        "expected_classification_id": _string(payload, "expected_classification_id"),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_scope_snapshot_id": _string(payload, "expected_scope_snapshot_id"),
        "expected_governance_binding_snapshot_id": _string(payload, "expected_governance_binding_snapshot_id"),
        "requested_by": _string(payload, "requested_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_adaptation_episode_id"].startswith("adpt-"):
        raise MissionValidationError("expected_adaptation_episode_id must be a canonical adpt-* identifier")
    if not values["expected_classification_id"].startswith("rcls-"):
        raise MissionValidationError("expected_classification_id must be a canonical rcls-* identifier")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_scope_snapshot_id"].startswith("mscope-snap-"):
        raise MissionValidationError("expected_scope_snapshot_id must be a canonical mscope-snap-* identifier")
    if not values["expected_governance_binding_snapshot_id"].startswith("mgbind-snap-"):
        raise MissionValidationError(
            "expected_governance_binding_snapshot_id must be a canonical mgbind-snap-* identifier"
        )
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason not in (None, ""):
        if not isinstance(reason, str) or not reason.strip():
            raise MissionValidationError("reason must be a non-empty string when provided")
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    else:
        reason = None
    return {
        **values,
        "expected_adaptation_replan_sha256": _sha(payload, "expected_adaptation_replan_sha256"),
        "expected_classification_sha256": _sha(payload, "expected_classification_sha256"),
        "expected_classification_event_sha256": _sha(payload, "expected_classification_event_sha256"),
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_scope_sha256": _sha(payload, "expected_scope_sha256"),
        "expected_governance_binding_version": _positive_int(payload, "expected_governance_binding_version"),
        "expected_governance_binding_sha256": _sha(payload, "expected_governance_binding_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def replan_eligibility_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": REPLAN_ELIGIBILITY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def evaluate_replan_static_eligibility(
    *,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    adaptation_replan: Mapping[str, Any],
    classification: Mapping[str, Any],
    detection_event: Mapping[str, Any],
    classification_event: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
) -> Dict[str, Any]:
    repl = adaptation_replan.get("adaptation_replan_contract") or {}
    cls = classification.get("adaptation_trigger_classification_contract") or {}
    source = repl.get("source_bindings") or {}
    cls_source = cls.get("source_bindings") or {}
    checks: Dict[str, bool] = {
        "stage371_contract_integrity_valid": verify_adaptation_replan_contract(repl),
        "stage372_classification_integrity_valid": verify_adaptation_trigger_classification_contract(cls),
        "source_episode_is_detected": adaptation_replan.get("episode_state") == ADAPTATION_EPISODE_INITIAL_STATE,
        "classification_status_is_classified": classification.get("classification_status") == ADAPTATION_TRIGGER_CLASSIFICATION_STATUS,
        "classification_is_evidence_backed": bool((cls.get("trigger_classification") or {}).get("evidence_backed")),
        "classification_binds_source_episode": (
            classification.get("adaptation_episode_id") == adaptation_replan.get("adaptation_episode_id")
            and classification.get("replan_trigger_id") == adaptation_replan.get("replan_trigger_id")
            and classification.get("source_adaptation_replan_sha256") == adaptation_replan.get("canonical_sha256")
        ),
        "detection_event_binding_valid": (
            detection_event.get("event_type") == "MISSION_ADAPTATION_REPLAN_DETECTED"
            and detection_event.get("causation_id") == adaptation_replan.get("adaptation_episode_id")
            and classification.get("detection_event_id") == detection_event.get("event_id")
            and classification.get("detection_event_sha256") == detection_event.get("canonical_sha256")
        ),
        "classification_event_binding_valid": (
            classification_event.get("event_type") == "MISSION_ADAPTATION_TRIGGER_CLASSIFIED"
            and classification_event.get("causation_id") == classification.get("classification_id")
            and (classification_event.get("payload") or {}).get("canonical_sha256") == classification.get("canonical_sha256")
        ),
        "mission_state_is_replan_eligible": state.get("state") in ADAPTATION_REPLAN_ALLOWED_MISSION_STATES,
        "mission_state_unchanged_since_detection": (
            state.get("state") == source.get("source_state")
            and int(state.get("state_version") or 0) == int(source.get("source_state_version") or -1)
        ),
        "mission_version_unchanged_since_detection": (
            version_vector.get("version_vector_complete") is True
            and version_vector.get("version_sha256") == source.get("source_version_sha256")
            and version_vector.get("version_sha256") == classification.get("source_version_sha256")
        ),
        "active_plan_integrity_valid": verify_plan_version_contract(active_plan.get("plan_version_contract") or {}),
        "active_plan_matches_detection": (
            active_plan.get("plan_version_record_id") == source.get("source_plan_version_record_id")
            and int(active_plan.get("plan_version") or 0) == int(source.get("source_plan_version") or -1)
            and active_plan.get("canonical_sha256") == source.get("source_plan_sha256")
        ),
        "active_plan_matches_classification": (
            active_plan.get("plan_version_record_id") == cls_source.get("source_plan_version_record_id")
            and active_plan.get("canonical_sha256") == cls_source.get("source_plan_sha256")
        ),
        "canonical_scope_integrity_valid": verify_contract(scope_record.get("contract") or {}),
        "governance_binding_integrity_valid": verify_binding_contract(governance_binding.get("binding") or {}),
        "governance_binding_current_for_scope": (
            governance_binding.get("mission_scope_snapshot_id") == scope_record.get("snapshot_id")
            and governance_binding.get("mission_scope_sha256") == scope_record.get("canonical_sha256")
        ),
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    return {
        "status": REPLAN_ELIGIBILITY_STATIC_PASSED if not failed else REPLAN_ELIGIBILITY_STATIC_FAILED,
        "checks": checks,
        "failed_preconditions": failed,
        "failed_precondition_count": len(failed),
        "eligible_for_authoritative_governance_query": not failed,
    }


def _eligibility_status(policy_decision: Mapping[str, Any]) -> tuple[str, bool]:
    decision = str(policy_decision.get("decision") or "").upper()
    requires_approval = bool(policy_decision.get("requires_human_approval"))
    if decision == "ALLOW" and not requires_approval:
        return REPLAN_ELIGIBLE_STATUS, True
    if decision == "REVIEW" or requires_approval:
        return REPLAN_REVIEW_REQUIRED_STATUS, False
    return REPLAN_NOT_ELIGIBLE_STATUS, False


def build_replan_eligibility_contract(
    *,
    eligibility_gate_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    operation_id: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    adaptation_replan: Mapping[str, Any],
    classification: Mapping[str, Any],
    detection_event: Mapping[str, Any],
    classification_event: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
    static_eligibility: Mapping[str, Any],
    policy_decision: Mapping[str, Any],
    evaluated_at: str,
) -> Dict[str, Any]:
    if static_eligibility.get("status") != REPLAN_ELIGIBILITY_STATIC_PASSED:
        raise MissionValidationError("cannot build Stage-3.7.3 contract from failed static eligibility")
    status, eligible = _eligibility_status(policy_decision)
    gov = governance_binding["binding"]["governance_authority"]
    core = {
        "schema_version": REPLAN_ELIGIBILITY_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": REPLAN_ELIGIBILITY_STAGE_SCHEMA_VERSION,
        "identity": {
            "eligibility_gate_id": eligibility_gate_id,
            "mission_id": mission_id,
            "adaptation_episode_id": adaptation_replan["adaptation_episode_id"],
            "replan_trigger_id": adaptation_replan["replan_trigger_id"],
            "classification_id": classification["classification_id"],
        },
        "source_bindings": {
            "source_state": state["state"],
            "source_state_version": int(state["state_version"]),
            "source_version_sha256": version_vector["version_sha256"],
            "source_plan_version_record_id": active_plan["plan_version_record_id"],
            "source_plan_version": int(active_plan["plan_version"]),
            "source_plan_generation": int(active_plan["plan_version"]),
            "source_plan_sha256": active_plan["canonical_sha256"],
            "canonical_plan_id": active_plan["canonical_plan_id"],
            "adaptation_replan_sha256": adaptation_replan["canonical_sha256"],
            "classification_sha256": classification["canonical_sha256"],
            "detection_event_id": detection_event["event_id"],
            "detection_event_sha256": detection_event["canonical_sha256"],
            "classification_event_id": classification_event["event_id"],
            "classification_event_sha256": classification_event["canonical_sha256"],
            "mission_scope_snapshot_id": scope_record["snapshot_id"],
            "mission_scope_version": int(scope_record["contract_version"]),
            "mission_scope_sha256": scope_record["canonical_sha256"],
            "governance_binding_snapshot_id": governance_binding["binding_snapshot_id"],
            "governance_binding_version": int(governance_binding["binding_version"]),
            "governance_binding_sha256": governance_binding["canonical_sha256"],
            "governance_scope_contract_hash": governance_binding["governance_scope_contract_hash"],
        },
        "static_eligibility": dict(static_eligibility),
        "governance_request": {
            "operation_id": operation_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "action_class": REPLAN_GOVERNANCE_ACTION_CLASS,
            "action_name": REPLAN_GOVERNANCE_ACTION_NAME,
            "resource_type": REPLAN_GOVERNANCE_RESOURCE_TYPE,
            "resource_value": mission_id,
            "scope_contract_id": gov["governance_scope_contract_id"],
            "scope_version": int(gov["governance_scope_version"]),
            "scope_contract_hash": governance_binding["governance_scope_contract_hash"],
            "policy_set_id": gov["policy_set_id"],
            "requested_by": request["requested_by"],
        },
        "governance_decision": {
            "decision_id": policy_decision["decision_id"],
            "request_id": policy_decision["request_id"],
            "decision": policy_decision["decision"],
            "decision_hash": policy_decision["decision_hash"],
            "reason_codes": list(policy_decision.get("reason_codes") or []),
            "constraints": dict(policy_decision.get("constraints") or {}),
            "requires_human_approval": bool(policy_decision.get("requires_human_approval")),
            "approval_request_id": policy_decision.get("approval_request_id"),
            "policy_set_id": policy_decision["policy_set_id"],
            "policy_version": int(policy_decision["policy_version"]),
            "scope_contract_id": policy_decision["scope_contract_id"],
            "scope_version": int(policy_decision["scope_version"]),
            "valid_from": policy_decision["valid_from"],
            "valid_until": policy_decision["valid_until"],
            "governance_event_id": policy_decision.get("governance_event_id"),
        },
        "eligibility": {
            "eligibility_status": status,
            "eligibility_evaluation_performed": True,
            "static_eligibility_passed": True,
            "governance_authorization_performed": True,
            "replan_eligible": eligible,
            "effective_episode_state": "ELIGIBLE" if eligible else "CLASSIFIED",
        },
        "authority_boundary": {
            "authority": REPLAN_ELIGIBILITY_AUTHORITY,
            "mode": REPLAN_ELIGIBILITY_MODE,
            "eligibility_is_lifecycle_replan_command": False,
            "eligibility_is_replan_snapshot": False,
            "eligibility_is_planner_invocation": False,
            "eligibility_is_successor_plan": False,
            "eligibility_is_plan_validation": False,
            "eligibility_is_replan_commit": False,
            "eligibility_is_plan_supersession": False,
            "lifecycle_replan_requested": False,
            "replan_snapshot_bound": False,
            "planner_invocation_performed": False,
            "replan_candidate_created": False,
            "plan_delta_computed": False,
            "plan_validation_performed": False,
            "replan_decision_committed": False,
            "plan_supersession_performed": False,
            "historical_plan_mutation_performed": False,
            "mission_state_transition_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "dispatch_performed": False,
            "new_execution_attempt_created": False,
            "external_target_network_io_performed": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "requested_by": request["requested_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "evaluated_at": evaluated_at,
        },
    }
    digest = sha256_hex({"hash_domain": REPLAN_ELIGIBILITY_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_replan_eligibility_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != REPLAN_ELIGIBILITY_CONTRACT_SCHEMA_VERSION:
            return False
        if contract.get("stage_schema_version") != REPLAN_ELIGIBILITY_STAGE_SCHEMA_VERSION:
            return False
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if digest != sha256_hex({"hash_domain": REPLAN_ELIGIBILITY_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]
        src = contract["source_bindings"]
        static = contract["static_eligibility"]
        gov = contract["governance_decision"]
        eligibility = contract["eligibility"]
        boundary = contract["authority_boundary"]
        if not str(ident.get("eligibility_gate_id") or "").startswith(REPLAN_ELIGIBILITY_ID_PREFIX):
            return False
        if not str(ident.get("adaptation_episode_id") or "").startswith("adpt-"):
            return False
        if not str(ident.get("replan_trigger_id") or "").startswith("rpln-"):
            return False
        if not str(ident.get("classification_id") or "").startswith("rcls-"):
            return False
        for key in (
            "source_version_sha256", "source_plan_sha256", "adaptation_replan_sha256",
            "classification_sha256", "detection_event_sha256", "classification_event_sha256",
            "mission_scope_sha256", "governance_binding_sha256", "governance_scope_contract_hash",
        ):
            if not _SHA_RE.match(str(src.get(key) or "")):
                return False
        if src.get("source_state") not in ADAPTATION_REPLAN_ALLOWED_MISSION_STATES:
            return False
        if not str(src.get("source_plan_version_record_id") or "").startswith("pver-"):
            return False
        if int(src.get("source_plan_version") or 0) < 1 or int(src.get("source_plan_generation") or 0) < 1:
            return False
        if static.get("status") != REPLAN_ELIGIBILITY_STATIC_PASSED:
            return False
        checks = static.get("checks") or {}
        if not checks or not all(value is True for value in checks.values()):
            return False
        if static.get("eligible_for_authoritative_governance_query") is not True:
            return False
        if int(static.get("failed_precondition_count", -1)) != 0 or list(static.get("failed_preconditions") or []):
            return False
        if gov.get("decision") not in {"ALLOW", "DENY", "REVIEW"}:
            return False
        if not _SHA_RE.match(str(gov.get("decision_hash") or "")):
            return False
        expected_status, expected_eligible = _eligibility_status(gov)
        if eligibility.get("eligibility_status") != expected_status:
            return False
        if eligibility.get("eligibility_evaluation_performed") is not True:
            return False
        if eligibility.get("static_eligibility_passed") is not True:
            return False
        if eligibility.get("governance_authorization_performed") is not True:
            return False
        if eligibility.get("replan_eligible") is not expected_eligible:
            return False
        if eligibility.get("effective_episode_state") != ("ELIGIBLE" if expected_eligible else "CLASSIFIED"):
            return False
        if boundary.get("authority") != REPLAN_ELIGIBILITY_AUTHORITY or boundary.get("mode") != REPLAN_ELIGIBILITY_MODE:
            return False
        for key in (
            "eligibility_is_lifecycle_replan_command", "eligibility_is_replan_snapshot",
            "eligibility_is_planner_invocation", "eligibility_is_successor_plan",
            "eligibility_is_plan_validation", "eligibility_is_replan_commit",
            "eligibility_is_plan_supersession", "lifecycle_replan_requested", "replan_snapshot_bound",
            "planner_invocation_performed", "replan_candidate_created", "plan_delta_computed",
            "plan_validation_performed", "replan_decision_committed", "plan_supersession_performed",
            "historical_plan_mutation_performed", "mission_state_transition_performed",
            "runtime_query_performed", "runtime_control_io_performed", "dispatch_performed",
            "new_execution_attempt_created", "external_target_network_io_performed",
            "target_action_dispatch_performed", "target_actuation",
        ):
            if boundary.get(key) is not False:
                return False
        return True
    except Exception:
        return False


def canonical_replan_eligibility_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": REPLAN_ELIGIBILITY_STAGE_SCHEMA_VERSION,
        "contract_schema_version": REPLAN_ELIGIBILITY_CONTRACT_SCHEMA_VERSION,
        "mode": REPLAN_ELIGIBILITY_MODE,
        "authority": REPLAN_ELIGIBILITY_AUTHORITY,
        "identity_prefix": REPLAN_ELIGIBILITY_ID_PREFIX,
        "event_type": REPLAN_ELIGIBILITY_EVENT_TYPE,
        "eligibility_statuses": list(REPLAN_ELIGIBILITY_STATUSES),
        "requires_stage371_adaptation_replan": True,
        "requires_stage372_classification": True,
        "requires_exact_detection_and_classification_events": True,
        "requires_unchanged_mission_state_version": True,
        "requires_unchanged_active_plan_head": True,
        "requires_current_scope_and_governance_binding": True,
        "static_fail_closed_before_governance_query": True,
        "governance_authorization_authority": "aptsGSS",
        "governance_action_class": REPLAN_GOVERNANCE_ACTION_CLASS,
        "governance_action_name": REPLAN_GOVERNANCE_ACTION_NAME,
        "governance_resource_type": REPLAN_GOVERNANCE_RESOURCE_TYPE,
        "allow_without_human_approval_is_eligible": True,
        "deny_is_not_eligible": True,
        "review_or_human_approval_required_is_review_required": True,
        "one_gate_per_adaptation_episode": True,
        "idempotent_operation_recovery_supported": True,
        "lifecycle_replan_requested": False,
        "replan_snapshot_bound": False,
        "planner_invocation_performed": False,
        "replan_candidate_created": False,
        "plan_delta_computed": False,
        "plan_validation_performed": False,
        "replan_decision_committed": False,
        "plan_supersession_performed": False,
        "mission_state_transition_performed": False,
        "dispatch_performed": False,
        "target_actuation": False,
        "next_stage": "3.7.4",
    }
