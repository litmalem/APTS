from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .replan_candidate import verify_replan_candidate_contract

REPLAN_COMMIT_STAGE_SCHEMA_VERSION = "apts-authoritative-replan-commit-authorization-successor-plan-materialization-v1"
REPLAN_COMMIT_CONTRACT_SCHEMA_VERSION = "apts-authoritative-replan-commit-contract-v1"
REPLAN_COMMIT_HASH_DOMAIN = "MISSION_AUTHORITATIVE_REPLAN_COMMIT_V1"
REPLAN_COMMIT_REQUEST_HASH_DOMAIN = "MISSION_AUTHORITATIVE_REPLAN_COMMIT_REQUEST_V1"
REPLAN_COMMIT_OPERATION_HASH_DOMAIN = "MISSION_AUTHORITATIVE_REPLAN_COMMIT_OPERATION_V1"
REPLAN_COMMIT_ID_PREFIX = "rpcom-"
REPLAN_COMMIT_EVENT_TYPE = "MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED"
REPLAN_COMMIT_STATUS = "COMMITTED_SUCCESSOR_PLAN"
REPLAN_COMMIT_AUTHORITY = "MISSION_ORCHESTRATOR_AUTHORITATIVE_REPLAN_COMMIT_AND_SUCCESSOR_PLAN_MATERIALIZATION"
REPLAN_COMMIT_MODE = (
    "AUTHORITATIVE_GOVERNANCE_REVALIDATION_THEN_ATOMIC_APPEND_ONLY_SUCCESSOR_PLAN_"
    "MATERIALIZATION_WITH_CAS_ACTIVE_HEAD_NO_LIFECYCLE_TRANSITION_NO_DISPATCH_NO_ACTUATION"
)
REPLAN_COMMIT_GOVERNANCE_ACTION_CLASS = "INTERNAL_REASONING"
REPLAN_COMMIT_GOVERNANCE_ACTION_NAME = "AUTHORIZE_REPLAN_COMMIT"
REPLAN_COMMIT_GOVERNANCE_RESOURCE_TYPE = "MISSION"

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_REQUEST_FIELDS = {
    "idempotency_key", "expected_replan_validation_id", "expected_replan_validation_sha256",
    "expected_replan_candidate_id", "expected_replan_candidate_sha256", "expected_candidate_payload_sha256",
    "expected_replan_snapshot_id", "expected_replan_snapshot_sha256",
    "expected_source_plan_version_record_id", "expected_source_plan_version", "expected_source_plan_sha256",
    "expected_source_state_version", "expected_source_version_sha256",
    "expected_scope_snapshot_id", "expected_scope_sha256",
    "expected_governance_binding_snapshot_id", "expected_governance_binding_version", "expected_governance_binding_sha256",
    "requested_by", "reason", "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_replan_commit_id() -> str:
    return f"{REPLAN_COMMIT_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_replan_commit_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("authoritative replan commit request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported authoritative replan commit field(s): " + ", ".join(unknown)
            + "; Stage 3.7.7 authorizes and materializes only the immutable Stage-3.7.6 validated candidate. "
              "Caller-supplied governance decisions, successor tasks, plan payloads, lifecycle transitions, routing, "
              "dispatch, execution, or target actuation fields are forbidden"
        )
    ids = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_replan_validation_id": _string(payload, "expected_replan_validation_id"),
        "expected_replan_candidate_id": _string(payload, "expected_replan_candidate_id"),
        "expected_replan_snapshot_id": _string(payload, "expected_replan_snapshot_id"),
        "expected_source_plan_version_record_id": _string(payload, "expected_source_plan_version_record_id"),
        "expected_scope_snapshot_id": _string(payload, "expected_scope_snapshot_id"),
        "expected_governance_binding_snapshot_id": _string(payload, "expected_governance_binding_snapshot_id"),
        "requested_by": _string(payload, "requested_by", 128),
    }
    for key, value in ids.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not ids["expected_replan_validation_id"].startswith("rpdec-"):
        raise MissionValidationError("expected_replan_validation_id must be a canonical rpdec-* identifier")
    if not ids["expected_replan_candidate_id"].startswith("rpcand-"):
        raise MissionValidationError("expected_replan_candidate_id must be a canonical rpcand-* identifier")
    if not ids["expected_replan_snapshot_id"].startswith("rpsnap-"):
        raise MissionValidationError("expected_replan_snapshot_id must be a canonical rpsnap-* identifier")
    if not ids["expected_source_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_source_plan_version_record_id must be a canonical pver-* identifier")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason in (None, ""):
        reason = None
    elif not isinstance(reason, str) or not reason.strip():
        raise MissionValidationError("reason must be a non-empty string when provided")
    else:
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    return {
        **ids,
        "expected_replan_validation_sha256": _sha(payload, "expected_replan_validation_sha256"),
        "expected_replan_candidate_sha256": _sha(payload, "expected_replan_candidate_sha256"),
        "expected_candidate_payload_sha256": _sha(payload, "expected_candidate_payload_sha256"),
        "expected_replan_snapshot_sha256": _sha(payload, "expected_replan_snapshot_sha256"),
        "expected_source_plan_version": _positive_int(payload, "expected_source_plan_version"),
        "expected_source_plan_sha256": _sha(payload, "expected_source_plan_sha256"),
        "expected_source_state_version": _positive_int(payload, "expected_source_state_version"),
        "expected_source_version_sha256": _sha(payload, "expected_source_version_sha256"),
        "expected_scope_sha256": _sha(payload, "expected_scope_sha256"),
        "expected_governance_binding_version": _positive_int(payload, "expected_governance_binding_version"),
        "expected_governance_binding_sha256": _sha(payload, "expected_governance_binding_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def replan_commit_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": REPLAN_COMMIT_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def deterministic_replan_commit_operation_id(request_sha256: str) -> str:
    return "rpcaop-" + sha256_hex({"hash_domain": REPLAN_COMMIT_OPERATION_HASH_DOMAIN, "request_sha256": request_sha256})[:48]


def materialize_successor_candidate_plan(candidate_contract: Mapping[str, Any]) -> Dict[str, Any]:
    if not verify_replan_candidate_contract(candidate_contract):
        raise MissionValidationError("Stage-3.7.5 ReplanCandidate failed integrity verification")
    cand = candidate_contract["candidate_successor_plan"]
    tasks = list(cand.get("candidate_tasks") or [])
    edges = list(cand.get("candidate_dependency_edges") or [])
    return {
        "status": "GENERATED_UNVALIDATED",
        "materialization_source": "STAGE3_7_5_VALIDATED_REPLAN_CANDIDATE",
        "replan_candidate_id": candidate_contract["identity"]["replan_candidate_id"],
        "replan_candidate_sha256": candidate_contract["canonical_sha256"],
        "candidate_payload_sha256": cand["candidate_payload_sha256"],
        "source_plan_version": int(cand["source_plan_version"]),
        "candidate_plan_version": int(cand["candidate_plan_version"]),
        "candidate_plan_generation": int(cand["candidate_plan_generation"]),
        "task_count": len(tasks),
        "dependency_edge_count": len(edges),
        "ordered_planned_task_ids": [x["source_planned_task_id"] for x in tasks],
        "tasks": tasks,
        "dependency_edges": edges,
        "satisfied_source_predecessors": list(cand.get("satisfied_source_predecessors") or []),
        "planner_profile": candidate_contract["planner_invocation"]["planner_profile"],
        "planning_strategy": cand["planning_strategy"],
        **({"cti_feedback_requirements":dict(cand["cti_feedback_requirements"])} if "cti_feedback_requirements" in cand else {}),
    }


def build_replan_commit_contract(*, commit_id: str, mission_id: str, request: Mapping[str, Any], request_sha256: str,
                                 operation_id: str, validation_record: Mapping[str, Any], candidate_record: Mapping[str, Any],
                                 snapshot_record: Mapping[str, Any], eligibility_record: Mapping[str, Any],
                                 scope_record: Mapping[str, Any], governance_binding: Mapping[str, Any],
                                 policy_decision: Mapping[str, Any], predecessor_plan: Mapping[str, Any],
                                 successor_plan: Mapping[str, Any], successor_candidate_plan: Mapping[str, Any],
                                 committed_at: str) -> Dict[str, Any]:
    validation = validation_record["replan_validation_contract"]
    candidate = candidate_record["replan_candidate_contract"]
    snapshot = snapshot_record["replan_snapshot_contract"]
    eligibility = eligibility_record["replan_eligibility_governance_contract"]
    src = validation["source_bindings"]
    gov = governance_binding["binding"]["governance_authority"]
    core = {
        "schema_version": REPLAN_COMMIT_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": REPLAN_COMMIT_STAGE_SCHEMA_VERSION,
        "identity": {
            "replan_commit_id": commit_id,
            "mission_id": mission_id,
            "adaptation_episode_id": validation["identity"]["adaptation_episode_id"],
            "replan_trigger_id": candidate["identity"]["replan_trigger_id"],
            "eligibility_gate_id": eligibility_record["eligibility_gate_id"],
            "replan_snapshot_id": snapshot_record["replan_snapshot_id"],
            "replan_candidate_id": candidate_record["replan_candidate_id"],
            "replan_validation_id": validation_record["replan_validation_id"],
        },
        "source_bindings": {
            "replan_validation_sha256": validation_record["canonical_sha256"],
            "replan_candidate_sha256": candidate_record["canonical_sha256"],
            "candidate_payload_sha256": candidate_record["candidate_payload_sha256"],
            "replan_snapshot_sha256": snapshot_record["canonical_sha256"],
            "eligibility_sha256": eligibility_record["canonical_sha256"],
            "eligibility_policy_decision_hash": eligibility["governance_decision"]["decision_hash"],
            "source_plan_version_record_id": src["source_plan_version_record_id"],
            "source_plan_version": int(src["source_plan_version"]),
            "source_plan_sha256": src["source_plan_sha256"],
            "source_state": src["source_state"],
            "source_state_version": int(src["source_state_version"]),
            "source_version_sha256": src["source_version_sha256"],
            "mission_scope_snapshot_id": scope_record["snapshot_id"],
            "mission_scope_sha256": scope_record["canonical_sha256"],
            "governance_binding_snapshot_id": governance_binding["binding_snapshot_id"],
            "governance_binding_version": int(governance_binding["binding_version"]),
            "governance_binding_sha256": governance_binding["canonical_sha256"],
            "governance_scope_contract_hash": governance_binding["governance_scope_contract_hash"],
        },
        "commit_authorization": {
            "operation_id": operation_id,
            "authority": "aptsGSS",
            "authority_component": "GOV-PLANE",
            "action_class": REPLAN_COMMIT_GOVERNANCE_ACTION_CLASS,
            "action_name": REPLAN_COMMIT_GOVERNANCE_ACTION_NAME,
            "resource_type": REPLAN_COMMIT_GOVERNANCE_RESOURCE_TYPE,
            "resource_value": mission_id,
            "scope_contract_id": gov["governance_scope_contract_id"],
            "scope_version": int(gov["governance_scope_version"]),
            "policy_set_id": gov["policy_set_id"],
            "decision_id": policy_decision["decision_id"],
            "request_id": policy_decision["request_id"],
            "decision": policy_decision["decision"],
            "decision_hash": policy_decision["decision_hash"],
            "policy_version": int(policy_decision["policy_version"]),
            "requires_human_approval": bool(policy_decision.get("requires_human_approval")),
            "approval_request_id": policy_decision.get("approval_request_id"),
            "reason_codes": list(policy_decision.get("reason_codes") or []),
            "constraints": dict(policy_decision.get("constraints") or {}),
            "governance_event_id": policy_decision.get("governance_event_id"),
            "authorized": policy_decision["decision"] == "ALLOW" and not bool(policy_decision.get("requires_human_approval")),
        },
        "successor_plan_materialization": {
            "commit_status": REPLAN_COMMIT_STATUS,
            "predecessor_plan_version_record_id": predecessor_plan["plan_version_record_id"],
            "predecessor_plan_version": int(predecessor_plan["plan_version"]),
            "predecessor_plan_sha256": predecessor_plan["canonical_sha256"],
            "successor_plan_version_record_id": successor_plan["plan_version_record_id"],
            "successor_plan_version": int(successor_plan["plan_version"]),
            "successor_plan_sha256": successor_plan["canonical_sha256"],
            "candidate_plan_version": int(src["candidate_plan_version"]),
            "candidate_plan_generation": int(src["candidate_plan_generation"]),
            "materialized_task_count": int(successor_candidate_plan["task_count"]),
            "materialized_dependency_edge_count": int(successor_candidate_plan["dependency_edge_count"]),
            "successor_plan_materialized": True,
            "active_head_advanced": True,
            "predecessor_effectively_superseded": True,
            "historical_plan_row_mutated": False,
        },
        "authority_boundary": {
            "authority": REPLAN_COMMIT_AUTHORITY,
            "mode": REPLAN_COMMIT_MODE,
            "authoritative_governance_revalidation_performed": True,
            "governance_query_performed": True,
            "replan_decision_committed": True,
            "successor_plan_created": True,
            "plan_supersession_performed": True,
            "active_plan_head_cas_performed": True,
            "historical_plan_mutation_performed": False,
            "mission_state_transition_performed": False,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "execution_attempt_created": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "requested_by": request["requested_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "committed_at": committed_at,
        },
    }
    return {**core, "canonical_sha256": sha256_hex({"hash_domain": REPLAN_COMMIT_HASH_DOMAIN, "contract": core})}


def verify_replan_commit_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != REPLAN_COMMIT_CONTRACT_SCHEMA_VERSION:
            return False
        if contract.get("stage_schema_version") != REPLAN_COMMIT_STAGE_SCHEMA_VERSION:
            return False
        digest = contract.get("canonical_sha256")
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if digest != sha256_hex({"hash_domain": REPLAN_COMMIT_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]; src = contract["source_bindings"]
        auth = contract["commit_authorization"]; mat = contract["successor_plan_materialization"]
        boundary = contract["authority_boundary"]
        if not str(ident.get("replan_commit_id", "")).startswith(REPLAN_COMMIT_ID_PREFIX): return False
        if not str(ident.get("replan_validation_id", "")).startswith("rpdec-"): return False
        if not str(ident.get("replan_candidate_id", "")).startswith("rpcand-"): return False
        if not str(ident.get("replan_snapshot_id", "")).startswith("rpsnap-"): return False
        for key in ("replan_validation_sha256", "replan_candidate_sha256", "candidate_payload_sha256", "replan_snapshot_sha256",
                    "eligibility_sha256", "eligibility_policy_decision_hash", "source_plan_sha256", "source_version_sha256",
                    "mission_scope_sha256", "governance_binding_sha256", "governance_scope_contract_hash"):
            if not _SHA_RE.match(str(src.get(key) or "")): return False
        if auth.get("decision") != "ALLOW" or auth.get("requires_human_approval") is not False or auth.get("authorized") is not True:
            return False
        if not _SHA_RE.match(str(auth.get("decision_hash") or "")): return False
        if mat.get("commit_status") != REPLAN_COMMIT_STATUS or mat.get("successor_plan_materialized") is not True:
            return False
        if int(mat.get("successor_plan_version", 0)) != int(mat.get("predecessor_plan_version", 0)) + 1:
            return False
        if int(mat.get("candidate_plan_version", 0)) != int(mat.get("successor_plan_version", 0)):
            return False
        if int(mat.get("materialized_task_count", 0)) < 1:
            return False
        if boundary.get("authority") != REPLAN_COMMIT_AUTHORITY or boundary.get("mode") != REPLAN_COMMIT_MODE:
            return False
        for key in ("authoritative_governance_revalidation_performed", "governance_query_performed", "replan_decision_committed",
                    "successor_plan_created", "plan_supersession_performed", "active_plan_head_cas_performed"):
            if boundary.get(key) is not True: return False
        for key in ("historical_plan_mutation_performed", "mission_state_transition_performed", "routing_performed", "delegation_performed",
                    "dispatch_performed", "execution_attempt_created", "target_action_dispatch_performed", "target_actuation"):
            if boundary.get(key) is not False: return False
        return True
    except Exception:
        return False


def canonical_replan_commit_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": REPLAN_COMMIT_STAGE_SCHEMA_VERSION,
        "contract_schema_version": REPLAN_COMMIT_CONTRACT_SCHEMA_VERSION,
        "identity_prefix": REPLAN_COMMIT_ID_PREFIX,
        "event_type": REPLAN_COMMIT_EVENT_TYPE,
        "commit_status": REPLAN_COMMIT_STATUS,
        "authority": REPLAN_COMMIT_AUTHORITY,
        "mode": REPLAN_COMMIT_MODE,
        "requires_stage376_validated_for_commit": True,
        "requires_exact_immutable_stage375_candidate": True,
        "requires_exact_stage374_snapshot": True,
        "requires_unchanged_mission_state_version": True,
        "requires_unchanged_active_plan_head": True,
        "requires_current_scope_and_governance_binding": True,
        "authoritative_governance_revalidation_performed": True,
        "governance_action_class": REPLAN_COMMIT_GOVERNANCE_ACTION_CLASS,
        "governance_action_name": REPLAN_COMMIT_GOVERNANCE_ACTION_NAME,
        "governance_resource_type": REPLAN_COMMIT_GOVERNANCE_RESOURCE_TYPE,
        "allow_without_human_approval_required": True,
        "atomic_successor_plan_materialization_and_head_cas": True,
        "successor_version_rule": "EXACT_PREDECESSOR_PLUS_ONE",
        "predecessor_artifact_mutated": False,
        "replan_decision_committed": True,
        "successor_plan_created": True,
        "plan_supersession_performed": True,
        "mission_state_transition_performed": False,
        "routing_performed": False,
        "delegation_performed": False,
        "dispatch_performed": False,
        "target_actuation": False,
        "idempotent_governance_operation_recovery_supported": True,
        "next_stage": "3.7.8",
    }
