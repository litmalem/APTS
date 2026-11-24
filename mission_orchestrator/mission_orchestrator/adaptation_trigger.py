from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .adaptation_replan import (
    ADAPTATION_EPISODE_INITIAL_STATE,
    REPLAN_TRIGGER_CODES,
    verify_adaptation_replan_contract,
)
from .errors import MissionValidationError
from .plan_versioning import verify_plan_version_contract

ADAPTATION_TRIGGER_CLASSIFICATION_STAGE_SCHEMA_VERSION = "apts-adaptation-trigger-detection-classification-v1"
ADAPTATION_TRIGGER_CLASSIFICATION_CONTRACT_SCHEMA_VERSION = "apts-adaptation-trigger-classification-contract-v1"
ADAPTATION_TRIGGER_CLASSIFICATION_HASH_DOMAIN = "MISSION_ADAPTATION_TRIGGER_CLASSIFICATION_V1"
ADAPTATION_TRIGGER_CLASSIFICATION_REQUEST_HASH_DOMAIN = "MISSION_ADAPTATION_TRIGGER_CLASSIFICATION_REQUEST_V1"
ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX = "rcls-"
ADAPTATION_TRIGGER_CLASSIFICATION_MODE = (
    "EVIDENCE_BOUND_DETERMINISTIC_ADAPTATION_TRIGGER_CLASSIFICATION_"
    "NO_ELIGIBILITY_NO_REPLAN_NO_PLANNER_NO_ACTUATION"
)
ADAPTATION_TRIGGER_CLASSIFICATION_AUTHORITY = "MISSION_ORCHESTRATOR_ADAPTATION_TRIGGER_CLASSIFICATION"
ADAPTATION_TRIGGER_CLASSIFICATION_STATUS = "CLASSIFIED"
ADAPTATION_TRIGGER_CLASSIFICATION_EVENT_TYPE = "MISSION_ADAPTATION_TRIGGER_CLASSIFIED"

ADAPTATION_TRIGGER_SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ADAPTATION_TRIGGER_SOURCE_STAGES = (
    "STAGE3_3_PLANNING",
    "STAGE3_4_ROUTING_DELEGATION",
    "STAGE3_5_EXECUTION",
    "STAGE3_6_OUTCOME_COMPLETION",
    "MISSION_LIFECYCLE",
    "GOVERNANCE",
    "ENVIRONMENT",
    "OPERATOR",
    "OTHER",
)

# Agreed Stage-3.7.2 classification vocabulary. These are observations/reasons,
# not authorization decisions. Eligibility remains a later-stage concern.
ADAPTATION_TRIGGER_REASON_CODES = (
    "EXECUTION_FAILURE",
    "EXECUTION_TIMEOUT_EXHAUSTED",
    "TASK_OUTCOME_REJECTED",
    "DEPENDENCY_INVALIDATED",
    "RESOURCE_UNAVAILABLE",
    "AGENT_CAPABILITY_CHANGED",
    "ENVIRONMENT_STATE_CHANGED",
    "MISSION_CONSTRAINT_CHANGED",
    "BUDGET_PRESSURE",
    "DEADLINE_RISK",
    "POLICY_CHANGED",
    "EVIDENCE_CONTRADICTION",
    "PLAN_STALE",
)

REPLAN_SCOPE_LEVEL_3 = "LEVEL_3_PARTIAL_PLAN"
REPLAN_SCOPE_LEVEL_4 = "LEVEL_4_MISSION"
ADAPTATION_TRIGGER_REPLAN_SCOPE_LEVELS = (REPLAN_SCOPE_LEVEL_3, REPLAN_SCOPE_LEVEL_4)

_REASON_SCOPE = {
    "EXECUTION_FAILURE": REPLAN_SCOPE_LEVEL_3,
    "EXECUTION_TIMEOUT_EXHAUSTED": REPLAN_SCOPE_LEVEL_3,
    "TASK_OUTCOME_REJECTED": REPLAN_SCOPE_LEVEL_3,
    "DEPENDENCY_INVALIDATED": REPLAN_SCOPE_LEVEL_3,
    "RESOURCE_UNAVAILABLE": REPLAN_SCOPE_LEVEL_3,
    "AGENT_CAPABILITY_CHANGED": REPLAN_SCOPE_LEVEL_3,
    "PLAN_STALE": REPLAN_SCOPE_LEVEL_3,
    "ENVIRONMENT_STATE_CHANGED": REPLAN_SCOPE_LEVEL_4,
    "MISSION_CONSTRAINT_CHANGED": REPLAN_SCOPE_LEVEL_4,
    "BUDGET_PRESSURE": REPLAN_SCOPE_LEVEL_4,
    "DEADLINE_RISK": REPLAN_SCOPE_LEVEL_4,
    "POLICY_CHANGED": REPLAN_SCOPE_LEVEL_4,
    "EVIDENCE_CONTRADICTION": REPLAN_SCOPE_LEVEL_4,
}

# A Stage-3.7.1 trigger code is intentionally coarse. Stage 3.7.2 may refine it
# only into a compatible evidence-backed reason. OTHER remains an escape hatch,
# but still requires the Stage-3.7.1 evidence/event binding and an explicit
# canonical reason code.
_TRIGGER_REASON_COMPATIBILITY = {
    "CTI_CHANGE": {"ENVIRONMENT_STATE_CHANGED", "POLICY_CHANGED", "EVIDENCE_CONTRADICTION", "PLAN_STALE"},
    "TASK_FAILURE": {"EXECUTION_FAILURE", "TASK_OUTCOME_REJECTED", "PLAN_STALE"},
    "TASK_TIMEOUT": {"EXECUTION_TIMEOUT_EXHAUSTED", "DEADLINE_RISK", "PLAN_STALE"},
    "AUTHORIZATION_REVOCATION": {"POLICY_CHANGED", "MISSION_CONSTRAINT_CHANGED", "PLAN_STALE"},
    "MISSION_STATE_CHANGE": {"MISSION_CONSTRAINT_CHANGED", "PLAN_STALE", "ENVIRONMENT_STATE_CHANGED"},
    "EVIDENCE_CHANGE": {"EVIDENCE_CONTRADICTION", "ENVIRONMENT_STATE_CHANGED", "PLAN_STALE"},
    "PIP_CHANGE": {"MISSION_CONSTRAINT_CHANGED", "POLICY_CHANGED", "ENVIRONMENT_STATE_CHANGED", "PLAN_STALE"},
    "DEPENDENCY_CHANGE": {"DEPENDENCY_INVALIDATED", "PLAN_STALE"},
    "POLICY_CHANGE": {"POLICY_CHANGED", "MISSION_CONSTRAINT_CHANGED", "PLAN_STALE"},
    "RESOURCE_CHANGE": {"RESOURCE_UNAVAILABLE", "AGENT_CAPABILITY_CHANGED", "BUDGET_PRESSURE", "PLAN_STALE"},
    "OPERATOR_INTERVENTION": {"MISSION_CONSTRAINT_CHANGED", "BUDGET_PRESSURE", "DEADLINE_RISK", "PLAN_STALE"},
    "OTHER": set(ADAPTATION_TRIGGER_REASON_CODES),
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_adaptation_episode_id",
    "expected_replan_trigger_id",
    "expected_adaptation_replan_sha256",
    "expected_detection_event_sha256",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "reason_code",
    "severity",
    "source_stage",
    "classified_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_adaptation_trigger_classification_id() -> str:
    return f"{ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_adaptation_trigger_classification_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("adaptation trigger classification request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported adaptation trigger classification field(s): "
            + ", ".join(unknown)
            + "; Stage 3.7.2 classifies an existing evidence-backed Stage-3.7.1 trigger only. "
              "Caller-supplied eligibility, snapshot, lifecycle REPLAN, planner output, candidate, plan delta, "
              "decision/commit, Governance authorization, dispatch, execution, plan supersession, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_adaptation_episode_id": _string(payload, "expected_adaptation_episode_id"),
        "expected_replan_trigger_id": _string(payload, "expected_replan_trigger_id"),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "classified_by": _string(payload, "classified_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_adaptation_episode_id"].startswith("adpt-"):
        raise MissionValidationError("expected_adaptation_episode_id must be a canonical adpt-* identifier")
    if not values["expected_replan_trigger_id"].startswith("rpln-"):
        raise MissionValidationError("expected_replan_trigger_id must be a canonical rpln-* identifier")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")

    reason_code = _string(payload, "reason_code", 80).upper()
    if reason_code not in ADAPTATION_TRIGGER_REASON_CODES:
        raise MissionValidationError(
            "reason_code is not canonical; expected one of: " + ", ".join(ADAPTATION_TRIGGER_REASON_CODES)
        )
    severity = _string(payload, "severity", 20).upper()
    if severity not in ADAPTATION_TRIGGER_SEVERITIES:
        raise MissionValidationError(
            "severity is not canonical; expected one of: " + ", ".join(ADAPTATION_TRIGGER_SEVERITIES)
        )
    source_stage = _string(payload, "source_stage", 80).upper()
    if source_stage not in ADAPTATION_TRIGGER_SOURCE_STAGES:
        raise MissionValidationError(
            "source_stage is not canonical; expected one of: " + ", ".join(ADAPTATION_TRIGGER_SOURCE_STAGES)
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
        "expected_detection_event_sha256": _sha(payload, "expected_detection_event_sha256"),
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "reason_code": reason_code,
        "severity": severity,
        "source_stage": source_stage,
        "reason": reason,
        "metadata": dict(metadata),
    }


def adaptation_trigger_classification_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({
        "hash_domain": ADAPTATION_TRIGGER_CLASSIFICATION_REQUEST_HASH_DOMAIN,
        "request": dict(normalized),
    })


def classify_adaptation_trigger(*, trigger_code: str, reason_code: str) -> Dict[str, str]:
    if trigger_code not in REPLAN_TRIGGER_CODES:
        raise MissionValidationError(f"trigger_code={trigger_code!r} is not a canonical Stage-3.7.1 trigger code")
    if reason_code not in ADAPTATION_TRIGGER_REASON_CODES:
        raise MissionValidationError(f"reason_code={reason_code!r} is not a canonical Stage-3.7.2 reason code")
    if reason_code not in _TRIGGER_REASON_COMPATIBILITY[trigger_code]:
        allowed = ", ".join(sorted(_TRIGGER_REASON_COMPATIBILITY[trigger_code]))
        raise MissionValidationError(
            f"reason_code={reason_code!r} is incompatible with Stage-3.7.1 trigger_code={trigger_code!r}; allowed: {allowed}"
        )
    level = _REASON_SCOPE[reason_code]
    return {
        "classification_status": ADAPTATION_TRIGGER_CLASSIFICATION_STATUS,
        "reason_code": reason_code,
        "replan_scope_level": level,
        "replan_scope": "PARTIAL_PLAN" if level == REPLAN_SCOPE_LEVEL_3 else "MISSION_LEVEL",
    }


def build_adaptation_trigger_classification_contract(
    *,
    classification_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    adaptation_replan: Mapping[str, Any],
    detection_event: Mapping[str, Any],
    current_state: Mapping[str, Any],
    current_version_sha256: str,
    active_plan: Mapping[str, Any],
    classified_at: str,
) -> Dict[str, Any]:
    source_contract = adaptation_replan.get("adaptation_replan_contract")
    if not isinstance(source_contract, Mapping) or not verify_adaptation_replan_contract(source_contract):
        raise MissionValidationError("referenced Stage-3.7.1 adaptation/replan contract failed integrity verification")
    plan_contract = active_plan.get("plan_version_contract")
    if not isinstance(plan_contract, Mapping) or not verify_plan_version_contract(plan_contract):
        raise MissionValidationError("active Stage-3.3.7 Plan version failed integrity verification")

    if source_contract["adaptation_episode"]["episode_state"] != ADAPTATION_EPISODE_INITIAL_STATE:
        raise MissionValidationError("Stage-3.7.2 requires the immutable source adaptation episode to be DETECTED")
    if source_contract["adaptation_episode"]["classification_performed"] is not False:
        raise MissionValidationError("Stage-3.7.1 source contract unexpectedly claims classification")

    trigger = source_contract["replan_trigger"]
    source = source_contract["source_bindings"]
    classification = classify_adaptation_trigger(
        trigger_code=trigger["trigger_code"],
        reason_code=request["reason_code"],
    )
    source_event = source.get("source_event")
    evidence_refs = list(trigger.get("evidence_refs") or [])
    evidence_backed = bool(evidence_refs) or source_event is not None
    if not evidence_backed:
        raise MissionValidationError("Stage-3.7.2 classification requires evidence-backed Stage-3.7.1 detection material")

    core = {
        "schema_version": ADAPTATION_TRIGGER_CLASSIFICATION_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": ADAPTATION_TRIGGER_CLASSIFICATION_STAGE_SCHEMA_VERSION,
        "identity": {
            "classification_id": classification_id,
            "adaptation_episode_id": adaptation_replan["adaptation_episode_id"],
            "replan_trigger_id": adaptation_replan["replan_trigger_id"],
            "mission_id": mission_id,
        },
        "source_bindings": {
            "source_stage371_contract_sha256": adaptation_replan["canonical_sha256"],
            "detection_event": {
                "event_id": detection_event["event_id"],
                "event_type": detection_event["event_type"],
                "canonical_sha256": detection_event["canonical_sha256"],
                "occurred_at": detection_event["occurred_at"],
            },
            "source_state": current_state["state"],
            "source_state_version": int(current_state["state_version"]),
            "source_version_sha256": current_version_sha256,
            "source_plan_version_record_id": active_plan["plan_version_record_id"],
            "canonical_plan_id": active_plan["canonical_plan_id"],
            "source_plan_version": int(active_plan["plan_version"]),
            "source_plan_generation": int(active_plan["plan_version"]),
            "source_plan_sha256": active_plan["canonical_sha256"],
            "source_event": None if source_event is None else dict(source_event),
        },
        "trigger_classification": {
            "trigger_id": adaptation_replan["replan_trigger_id"],
            "mission_id": mission_id,
            "plan_id": active_plan["canonical_plan_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_generation": int(active_plan["plan_version"]),
            "source_stage": request["source_stage"],
            "source_event_id": None if source_event is None else source_event.get("event_id"),
            "trigger_code": adaptation_replan["trigger_code"],
            "reason_code": classification["reason_code"],
            "observed_at": adaptation_replan["detected_at"],
            "state_version": int(adaptation_replan["source_state_version"]),
            "evidence_refs": evidence_refs,
            "evidence_ref_count": len(evidence_refs),
            "evidence_backed": True,
            "severity": request["severity"],
            "classification_status": classification["classification_status"],
            "replan_scope_level": classification["replan_scope_level"],
            "replan_scope": classification["replan_scope"],
            "detection_materialized": True,
            "classification_performed": True,
            "eligibility_evaluation_performed": False,
        },
        "adaptation_episode_projection": {
            "source_episode_state": ADAPTATION_EPISODE_INITIAL_STATE,
            "episode_state": ADAPTATION_TRIGGER_CLASSIFICATION_STATUS,
            "detection_materialized": True,
            "classification_performed": True,
            "eligibility_evaluation_performed": False,
            "replan_snapshot_bound": False,
            "lifecycle_replan_requested": False,
            "planner_invocation_performed": False,
            "replan_candidate_created": False,
            "plan_delta_computed": False,
            "plan_validation_performed": False,
            "replan_decision_committed": False,
            "plan_supersession_performed": False,
            "lifecycle_handoff_ready": False,
            "terminal_state_reopening_performed": False,
        },
        "authority_boundary": {
            "authority": ADAPTATION_TRIGGER_CLASSIFICATION_AUTHORITY,
            "mode": ADAPTATION_TRIGGER_CLASSIFICATION_MODE,
            "classification_is_replan_eligibility": False,
            "classification_is_replan_authorization": False,
            "classification_is_lifecycle_replan_command": False,
            "classification_is_planner_invocation": False,
            "classification_is_successor_plan": False,
            "classification_is_plan_supersession": False,
            "historical_plan_mutation_performed": False,
            "terminal_state_reopening_performed": False,
            "mission_state_transition_performed": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "dispatch_performed": False,
            "new_execution_attempt_created": False,
            "external_network_io_performed": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "classified_by": request["classified_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "classified_at": classified_at,
        },
    }
    digest = sha256_hex({"hash_domain": ADAPTATION_TRIGGER_CLASSIFICATION_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_adaptation_trigger_classification_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != ADAPTATION_TRIGGER_CLASSIFICATION_CONTRACT_SCHEMA_VERSION:
            return False
        if contract.get("stage_schema_version") != ADAPTATION_TRIGGER_CLASSIFICATION_STAGE_SCHEMA_VERSION:
            return False
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if contract.get("canonical_sha256") != sha256_hex({
            "hash_domain": ADAPTATION_TRIGGER_CLASSIFICATION_HASH_DOMAIN,
            "contract": core,
        }):
            return False
        ident = contract["identity"]
        source = contract["source_bindings"]
        c = contract["trigger_classification"]
        episode = contract["adaptation_episode_projection"]
        boundary = contract["authority_boundary"]
        derived = classify_adaptation_trigger(trigger_code=c["trigger_code"], reason_code=c["reason_code"])
        source_event = source.get("source_event")
        source_event_ok = source_event is None or (
            str(source_event.get("event_id", "")).startswith("mevent-")
            and bool(_SHA_RE.match(str(source_event.get("canonical_sha256", ""))))
        )
        return (
            str(ident["classification_id"]).startswith(ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX)
            and str(ident["adaptation_episode_id"]).startswith("adpt-")
            and str(ident["replan_trigger_id"]).startswith("rpln-")
            and bool(_SHA_RE.match(str(source["source_stage371_contract_sha256"])))
            and source["detection_event"]["event_type"] == "MISSION_ADAPTATION_REPLAN_DETECTED"
            and str(source["detection_event"]["event_id"]).startswith("mevent-")
            and bool(_SHA_RE.match(str(source["detection_event"]["canonical_sha256"])))
            and str(source["source_plan_version_record_id"]).startswith("pver-")
            and str(source["canonical_plan_id"]).startswith("mplan-")
            and int(source["source_plan_version"]) >= 1
            and int(source["source_plan_generation"]) == int(source["source_plan_version"])
            and bool(_SHA_RE.match(str(source["source_plan_sha256"])))
            and source_event_ok
            and c["trigger_id"] == ident["replan_trigger_id"]
            and c["mission_id"] == ident["mission_id"]
            and c["plan_id"] == source["canonical_plan_id"]
            and int(c["plan_generation"]) == int(source["source_plan_generation"])
            and c["source_stage"] in ADAPTATION_TRIGGER_SOURCE_STAGES
            and c["reason_code"] in ADAPTATION_TRIGGER_REASON_CODES
            and c["severity"] in ADAPTATION_TRIGGER_SEVERITIES
            and c["classification_status"] == ADAPTATION_TRIGGER_CLASSIFICATION_STATUS
            and c["replan_scope_level"] == derived["replan_scope_level"]
            and c["replan_scope"] == derived["replan_scope"]
            and int(c["evidence_ref_count"]) == len(c["evidence_refs"])
            and c["evidence_backed"] is True
            and (bool(c["evidence_refs"]) or source_event is not None)
            and c["detection_materialized"] is True
            and c["classification_performed"] is True
            and c["eligibility_evaluation_performed"] is False
            and episode["source_episode_state"] == ADAPTATION_EPISODE_INITIAL_STATE
            and episode["episode_state"] == ADAPTATION_TRIGGER_CLASSIFICATION_STATUS
            and episode["classification_performed"] is True
            and episode["eligibility_evaluation_performed"] is False
            and episode["replan_snapshot_bound"] is False
            and episode["lifecycle_replan_requested"] is False
            and episode["planner_invocation_performed"] is False
            and episode["replan_candidate_created"] is False
            and episode["plan_delta_computed"] is False
            and episode["plan_validation_performed"] is False
            and episode["replan_decision_committed"] is False
            and episode["plan_supersession_performed"] is False
            and episode["terminal_state_reopening_performed"] is False
            and boundary["authority"] == ADAPTATION_TRIGGER_CLASSIFICATION_AUTHORITY
            and boundary["mode"] == ADAPTATION_TRIGGER_CLASSIFICATION_MODE
            and boundary["classification_is_replan_eligibility"] is False
            and boundary["classification_is_replan_authorization"] is False
            and boundary["classification_is_lifecycle_replan_command"] is False
            and boundary["classification_is_planner_invocation"] is False
            and boundary["classification_is_successor_plan"] is False
            and boundary["classification_is_plan_supersession"] is False
            and boundary["historical_plan_mutation_performed"] is False
            and boundary["terminal_state_reopening_performed"] is False
            and boundary["mission_state_transition_performed"] is False
            and boundary["governance_query_performed"] is False
            and boundary["runtime_query_performed"] is False
            and boundary["runtime_control_io_performed"] is False
            and boundary["dispatch_performed"] is False
            and boundary["new_execution_attempt_created"] is False
            and boundary["external_network_io_performed"] is False
            and boundary["target_action_dispatch_performed"] is False
            and boundary["target_actuation"] is False
        )
    except Exception:
        return False


def canonical_adaptation_trigger_classification_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": ADAPTATION_TRIGGER_CLASSIFICATION_STAGE_SCHEMA_VERSION,
        "schema_version": ADAPTATION_TRIGGER_CLASSIFICATION_CONTRACT_SCHEMA_VERSION,
        "classification_identity_prefix": ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX,
        "mode": ADAPTATION_TRIGGER_CLASSIFICATION_MODE,
        "authority": ADAPTATION_TRIGGER_CLASSIFICATION_AUTHORITY,
        "classification_status": ADAPTATION_TRIGGER_CLASSIFICATION_STATUS,
        "classification_event_type": ADAPTATION_TRIGGER_CLASSIFICATION_EVENT_TYPE,
        "reason_codes": list(ADAPTATION_TRIGGER_REASON_CODES),
        "severities": list(ADAPTATION_TRIGGER_SEVERITIES),
        "source_stages": list(ADAPTATION_TRIGGER_SOURCE_STAGES),
        "replan_scope_levels": list(ADAPTATION_TRIGGER_REPLAN_SCOPE_LEVELS),
        "reason_scope_mapping": dict(_REASON_SCOPE),
        "trigger_reason_compatibility": {k: sorted(v) for k, v in _TRIGGER_REASON_COMPATIBILITY.items()},
        "requires_stage371_detected_episode": True,
        "requires_stage371_contract_hash_binding": True,
        "requires_detection_event_hash_binding": True,
        "requires_current_mission_version_binding": True,
        "requires_current_active_plan_head": True,
        "evidence_backed_only": True,
        "unauthoritative_ai_thinks_replan_trigger_allowed": False,
        "episode_effective_state_after_classification": ADAPTATION_TRIGGER_CLASSIFICATION_STATUS,
        "historical_stage371_contract_mutated": False,
        "classification_performed": True,
        "eligibility_evaluation_performed": False,
        "replan_snapshot_bound": False,
        "lifecycle_replan_requested": False,
        "planner_invocation_performed": False,
        "replan_candidate_created": False,
        "plan_delta_computed": False,
        "plan_validation_performed": False,
        "replan_decision_committed": False,
        "plan_supersession_performed": False,
        "mission_state_transition_performed": False,
        "governance_query_performed": False,
        "runtime_query_performed": False,
        "runtime_control_io_performed": False,
        "dispatch_performed": False,
        "new_execution_attempt_created": False,
        "external_network_io_performed": False,
        "target_action_dispatch_performed": False,
        "target_actuation": False,
        "next_stage": "3.7.3",
    }
