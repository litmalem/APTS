from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError
from .mission_outcome_aggregation import verify_mission_outcome_aggregation_contract

MISSION_SUCCESS_EVALUATION_STAGE_SCHEMA_VERSION = "apts-mission-success-criteria-evaluation-v1"
MISSION_SUCCESS_EVALUATION_CONTRACT_SCHEMA_VERSION = "apts-mission-success-criteria-evaluation-contract-v1"
MISSION_SUCCESS_EVALUATION_HASH_DOMAIN = "MISSION_SUCCESS_CRITERIA_EVALUATION_V1"
MISSION_SUCCESS_EVALUATION_REQUEST_HASH_DOMAIN = "MISSION_SUCCESS_CRITERIA_EVALUATION_REQUEST_V1"
MISSION_SUCCESS_CRITERIA_SNAPSHOT_HASH_DOMAIN = "MISSION_SUCCESS_CRITERIA_SNAPSHOT_V1"
MISSION_SUCCESS_EVALUATION_ID_PREFIX = "msceval-"
MISSION_SUCCESS_EVALUATION_MODE = "DETERMINISTIC_EVIDENCE_BOUND_SUCCESS_CRITERIA_EVALUATION_NO_MISSION_COMPLETION_AUTHORITY"
MISSION_SUCCESS_EVALUATION_AUTHORITY = "MISSION_ORCHESTRATOR_SUCCESS_CRITERIA_EVALUATION"
MISSION_SUCCESS_EVALUATION_STATUS = "MISSION_SUCCESS_CRITERIA_EVALUATED"
MISSION_SUCCESS_ALLOWED_MISSION_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})
CRITERION_RESULTS = ("SATISFIED", "NOT_SATISFIED", "INDETERMINATE")
OVERALL_RESULTS = ("SUCCESS_CRITERIA_SATISFIED", "SUCCESS_CRITERIA_NOT_SATISFIED", "SUCCESS_CRITERIA_INDETERMINATE")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {"idempotency_key", "expected_version_sha256", "expected_state_version", "expected_active_plan_version_record_id", "expected_active_plan_version", "expected_active_plan_sha256", "expected_aggregation_id", "expected_aggregation_sha256", "evaluated_by", "reason", "metadata"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_mission_success_evaluation_id() -> str:
    return f"{MISSION_SUCCESS_EVALUATION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_mission_success_evaluation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("mission success criteria evaluation request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError("unsupported mission success criteria evaluation field(s): " + ", ".join(unknown) + "; Stage 3.6.6 derives criterion results from the immutable Mission success criteria and the referenced Stage-3.6.5 aggregate. Caller-supplied criterion results, completion readiness, Mission completion, Plan progression, Governance/runtime, dispatch, execution, or actuation fields are forbidden")
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_aggregation_id": _string(payload, "expected_aggregation_id"),
        "evaluated_by": _string(payload, "evaluated_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_aggregation_id"].startswith("moutcome-"):
        raise MissionValidationError("expected_aggregation_id must be a canonical moutcome-* identifier")
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
    return {**values, "expected_version_sha256": _sha(payload, "expected_version_sha256"), "expected_state_version": _positive_int(payload, "expected_state_version"), "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"), "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"), "expected_aggregation_sha256": _sha(payload, "expected_aggregation_sha256"), "reason": reason, "metadata": dict(metadata)}


def mission_success_evaluation_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": MISSION_SUCCESS_EVALUATION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _criterion_result(criterion: Any, aggregate: Mapping[str, Any]) -> Dict[str, Any]:
    criterion_sha = sha256_hex({"criterion": criterion})
    if not isinstance(criterion, Mapping):
        return {"criterion_sha256": criterion_sha, "criterion": criterion, "result": "INDETERMINATE", "observed": None, "expected": None, "evidence_field": None, "reason": "criterion is not an object with a supported deterministic metric"}
    metric = criterion.get("metric")
    expected = criterion.get("expected")
    aliases = {
        "all_tasks_verified_complete": "all_tasks_verified_complete",
        "all_tasks_terminal": "all_tasks_terminal",
        "terminal_non_success_present": "terminal_non_success_present",
        "task_count": "task_count",
        "terminal_task_count": "terminal_task_count",
        "verified_complete_count": "verified_complete_count",
        "failed_count": "failed_count",
        "cancelled_count": "cancelled_count",
        "timed_out_count": "timed_out_count",
        "running_count": "running_count",
        "blocked_count": "blocked_count",
        "pending_count": "pending_count",
        "mission_execution_outcome_summary": "mission_execution_outcome_summary",
    }
    if not isinstance(metric, str) or metric not in aliases or "expected" not in criterion:
        return {"criterion_sha256": criterion_sha, "criterion": dict(criterion), "result": "INDETERMINATE", "observed": None, "expected": expected, "evidence_field": metric if isinstance(metric, str) else None, "reason": "criterion metric is not supported by Stage-3.6.6 deterministic evidence mapping"}
    field = aliases[metric]
    observed = aggregate.get(field)
    result = "SATISFIED" if observed == expected else "NOT_SATISFIED"
    return {"criterion_sha256": criterion_sha, "criterion": dict(criterion), "result": result, "observed": observed, "expected": expected, "evidence_field": field, "reason": "deterministic comparison against Stage-3.6.5 aggregate"}


def derive_mission_success_evaluation(*, success_criteria: Sequence[Any], aggregation: Mapping[str, Any]) -> Dict[str, Any]:
    contract = aggregation.get("mission_outcome_aggregation_contract")
    if not isinstance(contract, Mapping) or not verify_mission_outcome_aggregation_contract(contract):
        raise MissionValidationError("referenced Stage-3.6.5 mission outcome aggregation failed integrity verification")
    agg = contract["mission_outcome_aggregation"]
    criteria = list(success_criteria)
    results = []
    for idx, criterion in enumerate(criteria):
        result = _criterion_result(criterion, agg)
        result["criterion_index"] = idx
        results.append(result)
    sat = sum(x["result"] == "SATISFIED" for x in results)
    not_sat = sum(x["result"] == "NOT_SATISFIED" for x in results)
    ind = sum(x["result"] == "INDETERMINATE" for x in results)
    if not criteria or ind:
        overall = "SUCCESS_CRITERIA_INDETERMINATE"
    elif not_sat:
        overall = "SUCCESS_CRITERIA_NOT_SATISFIED"
    else:
        overall = "SUCCESS_CRITERIA_SATISFIED"
    criteria_sha = sha256_hex({"hash_domain": MISSION_SUCCESS_CRITERIA_SNAPSHOT_HASH_DOMAIN, "success_criteria": criteria})
    return {"evaluation_status": MISSION_SUCCESS_EVALUATION_STATUS, "overall_result": overall, "criterion_count": len(criteria), "satisfied_count": sat, "not_satisfied_count": not_sat, "indeterminate_count": ind, "success_criteria_sha256": criteria_sha, "criteria_results": results, "source_aggregation_id": aggregation["aggregation_id"], "source_aggregation_sha256": aggregation["canonical_sha256"], "source_aggregation_snapshot_sha256": aggregation["source_snapshot_sha256"]}


def build_mission_success_evaluation_contract(*, evaluation_id: str, mission_id: str, request: Mapping[str, Any], request_sha256: str, source_state: Mapping[str, Any], source_version_sha256: str, active_plan: Mapping[str, Any], aggregation: Mapping[str, Any], success_criteria: Sequence[Any], evaluated_at: str) -> Dict[str, Any]:
    evaluation = derive_mission_success_evaluation(success_criteria=success_criteria, aggregation=aggregation)
    core = {
        "schema_version": MISSION_SUCCESS_EVALUATION_CONTRACT_SCHEMA_VERSION,
        "identity": {"evaluation_id": evaluation_id, "mission_id": mission_id},
        "request": dict(request),
        "request_sha256": request_sha256,
        "source_bindings": {"source_state": source_state["state"], "source_state_version": int(source_state["state_version"]), "source_version_sha256": source_version_sha256, "plan_version_record_id": active_plan["plan_version_record_id"], "plan_version": int(active_plan["plan_version"]), "active_plan_sha256": active_plan["canonical_sha256"], "aggregation_id": aggregation["aggregation_id"], "aggregation_sha256": aggregation["canonical_sha256"]},
        "success_criteria_evaluation": evaluation,
        "authority_boundary": {"success_criteria_evaluation_performed": True, "mission_completion_readiness_decision_performed": False, "mission_success_completion_authority_exercised": False, "dependency_release_performed": False, "readiness_recalculation_performed": False, "plan_progression_performed": False, "governance_query_performed": False, "runtime_query_performed": False, "runtime_control_io_performed": False, "external_network_io_performed": False, "target_actuation": False, "mission_state_transition_performed": False},
        "evaluated_at": evaluated_at,
    }
    return {**core, "canonical_sha256": sha256_hex({"hash_domain": MISSION_SUCCESS_EVALUATION_HASH_DOMAIN, "contract": core})}


def verify_mission_success_evaluation_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != MISSION_SUCCESS_EVALUATION_CONTRACT_SCHEMA_VERSION:
            return False
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if contract.get("canonical_sha256") != sha256_hex({"hash_domain": MISSION_SUCCESS_EVALUATION_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]; ev = contract["success_criteria_evaluation"]; b = contract["authority_boundary"]
        return (
            str(ident["evaluation_id"]).startswith(MISSION_SUCCESS_EVALUATION_ID_PREFIX)
            and ev["evaluation_status"] == MISSION_SUCCESS_EVALUATION_STATUS
            and ev["overall_result"] in OVERALL_RESULTS
            and int(ev["criterion_count"]) == len(ev["criteria_results"])
            and int(ev["criterion_count"]) == int(ev["satisfied_count"]) + int(ev["not_satisfied_count"]) + int(ev["indeterminate_count"])
            and all(x["result"] in CRITERION_RESULTS for x in ev["criteria_results"])
            and b["success_criteria_evaluation_performed"] is True
            and b["mission_completion_readiness_decision_performed"] is False
            and b["mission_success_completion_authority_exercised"] is False
            and b["mission_state_transition_performed"] is False
            and b["external_network_io_performed"] is False
            and b["target_actuation"] is False
        )
    except Exception:
        return False


def canonical_mission_success_evaluation_definition() -> Dict[str, Any]:
    return {"schema_version": MISSION_SUCCESS_EVALUATION_CONTRACT_SCHEMA_VERSION, "stage_schema_version": MISSION_SUCCESS_EVALUATION_STAGE_SCHEMA_VERSION, "identity_prefix": MISSION_SUCCESS_EVALUATION_ID_PREFIX, "mode": MISSION_SUCCESS_EVALUATION_MODE, "authority": MISSION_SUCCESS_EVALUATION_AUTHORITY, "evaluation_status": MISSION_SUCCESS_EVALUATION_STATUS, "criterion_results": list(CRITERION_RESULTS), "overall_results": list(OVERALL_RESULTS), "consumes_stage365_mission_outcome_aggregation": True, "mission_success_criteria_are_authoritative": True, "unsupported_criteria_fail_closed_as_indeterminate": True, "mission_completion_readiness_decision_performed": False, "mission_success_completion_authority_exercised": False, "mission_state_transition_performed": False, "next_stage": "3.6.7"}
