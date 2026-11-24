from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .completion_readiness import verify_completion_readiness_contract
from .mission_success_evaluation import verify_mission_success_evaluation_contract
from .mission_outcome_aggregation import verify_mission_outcome_aggregation_contract

VERIFIED_COMPLETION_STAGE_SCHEMA_VERSION = "apts-mission-verified-completion-declaration-lifecycle-handoff-v1"
VERIFIED_COMPLETION_CONTRACT_SCHEMA_VERSION = "apts-mission-verified-completion-declaration-lifecycle-handoff-contract-v1"
VERIFIED_COMPLETION_HASH_DOMAIN = "MISSION_VERIFIED_COMPLETION_DECLARATION_LIFECYCLE_HANDOFF_V1"
VERIFIED_COMPLETION_REQUEST_HASH_DOMAIN = "MISSION_VERIFIED_COMPLETION_DECLARATION_LIFECYCLE_HANDOFF_REQUEST_V1"
VERIFIED_COMPLETION_ID_PREFIX = "mdecl-"
VERIFIED_COMPLETION_MODE = "VERIFIED_COMPLETION_DECLARATION_THEN_CANONICAL_STAGE32_LIFECYCLE_HANDOFF_FAIL_CLOSED"
VERIFIED_COMPLETION_AUTHORITY = "MISSION_ORCHESTRATOR_VERIFIED_COMPLETION_DECLARATION"
VERIFIED_COMPLETION_STATUS = "MISSION_VERIFIED_COMPLETION_DECLARED"
VERIFIED_COMPLETION_ALLOWED_SOURCE_STATE = "RUNNING"
VERIFIED_COMPLETION_FINAL_STATE = "COMPLETED"
LIFECYCLE_HANDOFF_COMMANDS = ("BEGIN_CLEANUP", "COMPLETE")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_readiness_id",
    "expected_readiness_sha256",
    "declared_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_verified_completion_declaration_id() -> str:
    return f"{VERIFIED_COMPLETION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_verified_completion_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("verified completion declaration request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported verified completion field(s): " + ", ".join(unknown)
            + "; Stage 3.6.8 derives completion evidence and lifecycle handoff from the exact Stage-3.6.7 READY decision. "
              "Caller-supplied completion status, criteria results, cleanup result, lifecycle command, target state, "
              "Governance/runtime, dispatch, execution, or target-actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_readiness_id": _string(payload, "expected_readiness_id"),
        "declared_by": _string(payload, "declared_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_readiness_id"].startswith("mready-"):
        raise MissionValidationError("expected_readiness_id must be a canonical mready-* identifier")
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
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_readiness_sha256": _sha(payload, "expected_readiness_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def verified_completion_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": VERIFIED_COMPLETION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _validate_ready_chain(*, readiness: Mapping[str, Any], evaluation: Mapping[str, Any], aggregation: Mapping[str, Any]) -> Dict[str, Any]:
    readiness_contract = readiness.get("completion_readiness_contract")
    if not isinstance(readiness_contract, Mapping) or not verify_completion_readiness_contract(readiness_contract):
        raise MissionValidationError("referenced Stage-3.6.7 readiness decision failed integrity verification")
    ready = readiness_contract["completion_readiness"]
    if ready.get("readiness_result") != "READY" or ready.get("completion_ready") is not True or int(ready.get("blocker_count", -1)) != 0:
        raise MissionValidationError("Stage-3.6.7 readiness decision is not READY or still contains blockers")
    if readiness_contract["source_bindings"].get("evaluation_id") != evaluation.get("evaluation_id"):
        raise MissionValidationError("Stage-3.6.7 readiness decision does not bind the referenced Stage-3.6.6 evaluation")
    if readiness_contract["source_bindings"].get("evaluation_sha256") != evaluation.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.6.7 readiness evaluation hash binding is inconsistent")

    evaluation_contract = evaluation.get("mission_success_evaluation_contract")
    if not isinstance(evaluation_contract, Mapping) or not verify_mission_success_evaluation_contract(evaluation_contract):
        raise MissionValidationError("referenced Stage-3.6.6 success criteria evaluation failed integrity verification")
    ev = evaluation_contract["success_criteria_evaluation"]
    if ev.get("overall_result") != "SUCCESS_CRITERIA_SATISFIED":
        raise MissionValidationError("Stage-3.6.6 success criteria are not fully SATISFIED")
    if int(ev.get("criterion_count", -1)) <= 0:
        raise MissionValidationError("verified completion requires at least one authoritative Mission success criterion")
    if any(x.get("result") != "SATISFIED" for x in ev.get("criteria_results", [])):
        raise MissionValidationError("every Stage-3.6.6 criterion must be SATISFIED before verified completion declaration")
    agg_contract = aggregation.get("mission_outcome_aggregation_contract")
    if not isinstance(agg_contract, Mapping) or not verify_mission_outcome_aggregation_contract(agg_contract):
        raise MissionValidationError("referenced Stage-3.6.5 mission outcome aggregation failed integrity verification")
    if evaluation_contract["source_bindings"].get("aggregation_id") != aggregation.get("aggregation_id"):
        raise MissionValidationError("Stage-3.6.6 evaluation does not bind the referenced Stage-3.6.5 aggregation")
    if evaluation_contract["source_bindings"].get("aggregation_sha256") != aggregation.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.6.6 aggregation hash binding is inconsistent")
    agg = agg_contract["mission_outcome_aggregation"]
    if agg.get("all_tasks_terminal") is not True:
        raise MissionValidationError("verified completion requires all active-Plan tasks to be terminal")
    if agg.get("all_tasks_verified_complete") is not True:
        raise MissionValidationError("verified completion requires verified completion for every active-Plan task")
    if agg.get("terminal_non_success_present") is not False:
        raise MissionValidationError("verified completion rejects any terminal non-success task outcome")
    return {**dict(ev), "source_aggregation": dict(agg)}


def build_verified_completion_contract(
    *,
    declaration_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    readiness: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    aggregation: Mapping[str, Any],
    declared_at: str,
) -> Dict[str, Any]:
    if str(source_state.get("state") or "").upper() != VERIFIED_COMPLETION_ALLOWED_SOURCE_STATE:
        raise MissionValidationError("verified completion declaration requires Mission state RUNNING")
    ev = _validate_ready_chain(readiness=readiness, evaluation=evaluation, aggregation=aggregation)
    if readiness.get("plan_version_record_id") != active_plan.get("plan_version_record_id"):
        raise MissionValidationError("Stage-3.6.7 readiness decision belongs to a stale/superseded Plan")
    if int(readiness.get("plan_version", -1)) != int(active_plan.get("plan_version", -2)):
        raise MissionValidationError("Stage-3.6.7 readiness Plan version does not match active Plan")

    criteria_evidence = [
        {
            "criterion_index": int(item["criterion_index"]),
            "criterion_sha256": item["criterion_sha256"],
            "status": "SATISFIED",
            "evidence_field": item.get("evidence_field"),
            "observed": item.get("observed"),
            "expected": item.get("expected"),
        }
        for item in ev["criteria_results"]
    ]
    cleanup_command_id = f"lc-cleanup-{declaration_id[len(VERIFIED_COMPLETION_ID_PREFIX):]}"
    complete_command_id = f"lc-complete-{declaration_id[len(VERIFIED_COMPLETION_ID_PREFIX):]}"
    core = {
        "schema_version": VERIFIED_COMPLETION_CONTRACT_SCHEMA_VERSION,
        "identity": {"declaration_id": declaration_id, "mission_id": mission_id},
        "request": dict(request),
        "request_sha256": request_sha256,
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "active_plan_sha256": active_plan["canonical_sha256"],
            "readiness_id": readiness["readiness_id"],
            "readiness_sha256": readiness["canonical_sha256"],
            "evaluation_id": evaluation["evaluation_id"],
            "evaluation_sha256": evaluation["canonical_sha256"],
            "aggregation_id": aggregation["aggregation_id"],
            "aggregation_sha256": aggregation["canonical_sha256"],
        },
        "verified_completion": {
            "declaration_status": VERIFIED_COMPLETION_STATUS,
            "verification_status": "VERIFIED",
            "readiness_result": "READY",
            "objective_status": "SATISFIED",
            "success_criteria_status": "SATISFIED",
            "success_criteria_count": int(ev["criterion_count"]),
            "criteria_results": criteria_evidence,
            "outstanding_critical_dependencies": 0,
            "completion_blocker_count": 0,
            "all_tasks_terminal": True,
            "all_tasks_verified_complete": True,
            "terminal_non_success_present": False,
        },
        "lifecycle_handoff_plan": {
            "handoff_protocol": "CANONICAL_STAGE_3_2_LIFECYCLE_COMMAND_PATH",
            "commands": list(LIFECYCLE_HANDOFF_COMMANDS),
            "begin_cleanup_command_id": cleanup_command_id,
            "begin_cleanup_idempotency_key": cleanup_command_id,
            "complete_command_id": complete_command_id,
            "complete_idempotency_key": complete_command_id,
            "expected_final_state": VERIFIED_COMPLETION_FINAL_STATE,
            "direct_state_transition_bypass_allowed": False,
        },
        "authority_boundary": {
            "verified_completion_declaration_performed": True,
            "mission_success_completion_authority_exercised": True,
            "stage32_lifecycle_handoff_required": True,
            "direct_state_transition_bypass_used": False,
            "plan_progression_performed": False,
            "dependency_release_performed": False,
            "readiness_recalculation_performed": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "dispatch_performed": False,
            "external_network_io_performed": False,
            "target_actuation": False,
        },
        "declared_at": declared_at,
    }
    return {**core, "canonical_sha256": sha256_hex({"hash_domain": VERIFIED_COMPLETION_HASH_DOMAIN, "contract": core})}


def verify_verified_completion_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != VERIFIED_COMPLETION_CONTRACT_SCHEMA_VERSION:
            return False
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if contract.get("canonical_sha256") != sha256_hex({"hash_domain": VERIFIED_COMPLETION_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]
        vc = contract["verified_completion"]
        plan = contract["lifecycle_handoff_plan"]
        boundary = contract["authority_boundary"]
        criteria = vc["criteria_results"]
        return (
            str(ident["declaration_id"]).startswith(VERIFIED_COMPLETION_ID_PREFIX)
            and vc["declaration_status"] == VERIFIED_COMPLETION_STATUS
            and vc["verification_status"] == "VERIFIED"
            and vc["readiness_result"] == "READY"
            and vc["objective_status"] == "SATISFIED"
            and vc["success_criteria_status"] == "SATISFIED"
            and int(vc["success_criteria_count"]) == len(criteria)
            and len(criteria) > 0
            and all(x.get("status") == "SATISFIED" for x in criteria)
            and int(vc["outstanding_critical_dependencies"]) == 0
            and int(vc["completion_blocker_count"]) == 0
            and vc["all_tasks_terminal"] is True
            and vc["all_tasks_verified_complete"] is True
            and vc["terminal_non_success_present"] is False
            and plan["commands"] == list(LIFECYCLE_HANDOFF_COMMANDS)
            and plan["expected_final_state"] == VERIFIED_COMPLETION_FINAL_STATE
            and plan["direct_state_transition_bypass_allowed"] is False
            and boundary["verified_completion_declaration_performed"] is True
            and boundary["mission_success_completion_authority_exercised"] is True
            and boundary["stage32_lifecycle_handoff_required"] is True
            and boundary["direct_state_transition_bypass_used"] is False
            and boundary["external_network_io_performed"] is False
            and boundary["target_actuation"] is False
        )
    except Exception:
        return False


def completion_evidence_refs(contract: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a Stage-3.6.8 declaration into the exact Stage-3.2.8 completion evidence shape."""
    if not verify_verified_completion_contract(contract):
        raise MissionValidationError("verified completion declaration failed integrity verification")
    ident = contract["identity"]
    source = contract["source_bindings"]
    vc = contract["verified_completion"]
    plan = contract["lifecycle_handoff_plan"]
    declaration_ref = f"stage3.6.8:declaration:{ident['declaration_id']}:{contract['canonical_sha256']}"
    readiness_ref = f"stage3.6.7:readiness:{source['readiness_id']}:{source['readiness_sha256']}"
    criteria_results = []
    for item in vc["criteria_results"]:
        ref = f"stage3.6.6:evaluation:{source['evaluation_id']}:criterion:{int(item['criterion_index'])}:{item['criterion_sha256']}"
        criteria_results.append({"criterion_index": int(item["criterion_index"]), "status": "SATISFIED", "evidence_refs": [ref]})
    cleanup_ref = f"stage3.2.8:cleanup-command:{plan['begin_cleanup_command_id']}"
    nested = [declaration_ref, readiness_ref]
    for item in criteria_results:
        nested.extend(item["evidence_refs"])
    nested.append(cleanup_ref)
    # preserve order and uniqueness
    evidence_refs = list(dict.fromkeys(nested))
    return {
        "evidence_refs": evidence_refs,
        "completion": {
            "verification_status": "VERIFIED",
            "objective_status": "SATISFIED",
            "objective_evidence_refs": [declaration_ref, readiness_ref],
            "success_criteria_status": "SATISFIED",
            "criteria_results": criteria_results,
            "cleanup_status": "VERIFIED",
            "cleanup_checks": [{"check_id": "STAGE3_2_8_CLEANUP_LINEAGE", "status": "PASS", "evidence_refs": [cleanup_ref]}],
            "outstanding_critical_dependencies": 0,
        },
    }


def canonical_verified_completion_definition() -> Dict[str, Any]:
    return {
        "schema_version": VERIFIED_COMPLETION_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": VERIFIED_COMPLETION_STAGE_SCHEMA_VERSION,
        "identity_prefix": VERIFIED_COMPLETION_ID_PREFIX,
        "mode": VERIFIED_COMPLETION_MODE,
        "authority": VERIFIED_COMPLETION_AUTHORITY,
        "declaration_status": VERIFIED_COMPLETION_STATUS,
        "source_state_required": VERIFIED_COMPLETION_ALLOWED_SOURCE_STATE,
        "final_state": VERIFIED_COMPLETION_FINAL_STATE,
        "consumes_stage367_completion_readiness": True,
        "revalidates_stage366_success_criteria_evaluation": True,
        "revalidates_stage365_all_tasks_terminal_and_verified_complete": True,
        "requires_ready_without_blockers": True,
        "persists_declaration_before_lifecycle_handoff": True,
        "lifecycle_handoff_commands": list(LIFECYCLE_HANDOFF_COMMANDS),
        "uses_canonical_stage32_lifecycle_command_path": True,
        "direct_state_transition_bypass_used": False,
        "restart_safe_partial_handoff_resume": True,
        "mission_success_completion_authority_exercised": True,
        "external_network_io_performed": False,
        "target_actuation": False,
        "next_stage": "3.6.9",
    }
