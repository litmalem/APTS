from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping

from .errors import MissionValidationError
from .mission_success_evaluation import verify_mission_success_evaluation_contract

COMPLETION_READINESS_STAGE_SCHEMA_VERSION = "apts-mission-completion-readiness-blockers-v1"
COMPLETION_READINESS_CONTRACT_SCHEMA_VERSION = "apts-mission-completion-readiness-blockers-contract-v1"
COMPLETION_READINESS_HASH_DOMAIN = "MISSION_COMPLETION_READINESS_BLOCKERS_V1"
COMPLETION_READINESS_REQUEST_HASH_DOMAIN = "MISSION_COMPLETION_READINESS_BLOCKERS_REQUEST_V1"
COMPLETION_READINESS_ID_PREFIX = "mready-"
COMPLETION_READINESS_MODE = "DETERMINISTIC_FAIL_CLOSED_COMPLETION_READINESS_AND_BLOCKER_DERIVATION_NO_STATE_TRANSITION_AUTHORITY"
COMPLETION_READINESS_AUTHORITY = "MISSION_ORCHESTRATOR_COMPLETION_READINESS_EVALUATION"
COMPLETION_READINESS_STATUS = "MISSION_COMPLETION_READINESS_EVALUATED"
COMPLETION_READINESS_ALLOWED_MISSION_STATES = frozenset({"RUNNING", "FAILED", "ABORTED"})
READINESS_RESULTS = ("READY", "BLOCKED")
BLOCKER_CODES = (
    "MISSION_STATE_NOT_RUNNING",
    "SUCCESS_CRITERIA_NOT_SATISFIED",
    "SUCCESS_CRITERIA_INDETERMINATE",
    "TASKS_NOT_ALL_TERMINAL",
    "TASKS_NOT_ALL_VERIFIED_COMPLETE",
    "TERMINAL_NON_SUCCESS_PRESENT",
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key", "expected_version_sha256", "expected_state_version",
    "expected_active_plan_version_record_id", "expected_active_plan_version", "expected_active_plan_sha256",
    "expected_evaluation_id", "expected_evaluation_sha256", "decided_by", "reason", "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_completion_readiness_id() -> str:
    return f"{COMPLETION_READINESS_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_completion_readiness_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("completion readiness request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported completion readiness field(s): " + ", ".join(unknown) +
            "; Stage 3.6.7 derives readiness and blockers from authoritative Mission/Plan state and one exact Stage-3.6.6 evaluation. "
            "Caller-supplied readiness, blocker, Mission completion, state transition, Plan progression, Governance/runtime, dispatch, execution, or actuation fields are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_evaluation_id": _string(payload, "expected_evaluation_id"),
        "decided_by": _string(payload, "decided_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_evaluation_id"].startswith("msceval-"):
        raise MissionValidationError("expected_evaluation_id must be a canonical msceval-* identifier")
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
        "expected_evaluation_sha256": _sha(payload, "expected_evaluation_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def completion_readiness_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": COMPLETION_READINESS_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def derive_completion_readiness(*, mission_state: str, evaluation: Mapping[str, Any]) -> Dict[str, Any]:
    contract = evaluation.get("mission_success_evaluation_contract")
    if not isinstance(contract, Mapping) or not verify_mission_success_evaluation_contract(contract):
        raise MissionValidationError("referenced Stage-3.6.6 mission success evaluation failed integrity verification")
    ev = contract["success_criteria_evaluation"]
    agg = ev
    # The Stage-3.6.6 result contains the exact aggregate-derived criterion outcome; its source
    # aggregation remains bound by id/hash in the predecessor contract. Completion-readiness
    # intentionally does not reinterpret arbitrary natural-language success criteria.
    blockers = []
    def add(code: str, detail: str, evidence: Any = None) -> None:
        blockers.append({"code": code, "detail": detail, "evidence": evidence})

    if mission_state != "RUNNING":
        add("MISSION_STATE_NOT_RUNNING", "Mission lifecycle state must be RUNNING before successful completion may be declared", mission_state)
    overall = ev["overall_result"]
    if overall == "SUCCESS_CRITERIA_NOT_SATISFIED":
        add("SUCCESS_CRITERIA_NOT_SATISFIED", "At least one canonical Mission success criterion is not satisfied", overall)
    elif overall == "SUCCESS_CRITERIA_INDETERMINATE":
        add("SUCCESS_CRITERIA_INDETERMINATE", "Canonical Mission success criteria cannot be proven satisfied deterministically", overall)

    # Criterion evidence for canonical task-completion invariants, when present, is consumed
    # directly. Missing mandatory proof is fail-closed via success-criteria indeterminacy or
    # explicit blocker below when a supported criterion exposes a negative observation.
    observations = {x.get("evidence_field"): x.get("observed") for x in ev.get("criteria_results", []) if x.get("evidence_field")}
    if observations.get("all_tasks_terminal") is False:
        add("TASKS_NOT_ALL_TERMINAL", "The active Plan still contains non-terminal tasks", False)
    if observations.get("all_tasks_verified_complete") is False:
        add("TASKS_NOT_ALL_VERIFIED_COMPLETE", "The active Plan does not have verified completion for every task", False)
    if observations.get("terminal_non_success_present") is True:
        add("TERMINAL_NON_SUCCESS_PRESENT", "At least one terminal task ended in a non-success outcome", True)

    # De-duplicate while preserving deterministic priority order.
    by_code = {b["code"]: b for b in blockers}
    ordered = [by_code[c] for c in BLOCKER_CODES if c in by_code]
    result = "READY" if not ordered else "BLOCKED"
    return {
        "readiness_status": COMPLETION_READINESS_STATUS,
        "readiness_result": result,
        "completion_ready": result == "READY",
        "blocker_count": len(ordered),
        "blockers": ordered,
        "source_evaluation_id": evaluation["evaluation_id"],
        "source_evaluation_sha256": evaluation["canonical_sha256"],
        "source_aggregation_id": evaluation["aggregation_id"],
        "success_criteria_overall_result": overall,
    }


def build_completion_readiness_contract(*, readiness_id: str, mission_id: str, request: Mapping[str, Any], request_sha256: str, source_state: Mapping[str, Any], source_version_sha256: str, active_plan: Mapping[str, Any], evaluation: Mapping[str, Any], decided_at: str) -> Dict[str, Any]:
    readiness = derive_completion_readiness(mission_state=source_state["state"], evaluation=evaluation)
    core = {
        "schema_version": COMPLETION_READINESS_CONTRACT_SCHEMA_VERSION,
        "identity": {"readiness_id": readiness_id, "mission_id": mission_id},
        "request": dict(request),
        "request_sha256": request_sha256,
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "active_plan_sha256": active_plan["canonical_sha256"],
            "evaluation_id": evaluation["evaluation_id"],
            "evaluation_sha256": evaluation["canonical_sha256"],
            "aggregation_id": evaluation["aggregation_id"],
        },
        "completion_readiness": readiness,
        "authority_boundary": {
            "completion_readiness_decision_performed": True,
            "blocker_derivation_performed": True,
            "mission_success_completion_authority_exercised": False,
            "mission_state_transition_performed": False,
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
        "decided_at": decided_at,
    }
    return {**core, "canonical_sha256": sha256_hex({"hash_domain": COMPLETION_READINESS_HASH_DOMAIN, "contract": core})}


def verify_completion_readiness_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != COMPLETION_READINESS_CONTRACT_SCHEMA_VERSION:
            return False
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        if contract.get("canonical_sha256") != sha256_hex({"hash_domain": COMPLETION_READINESS_HASH_DOMAIN, "contract": core}):
            return False
        ident = contract["identity"]
        r = contract["completion_readiness"]
        b = contract["authority_boundary"]
        return (
            str(ident["readiness_id"]).startswith(COMPLETION_READINESS_ID_PREFIX)
            and r["readiness_status"] == COMPLETION_READINESS_STATUS
            and r["readiness_result"] in READINESS_RESULTS
            and bool(r["completion_ready"]) == (r["readiness_result"] == "READY")
            and int(r["blocker_count"]) == len(r["blockers"])
            and all(x.get("code") in BLOCKER_CODES for x in r["blockers"])
            and b["completion_readiness_decision_performed"] is True
            and b["blocker_derivation_performed"] is True
            and b["mission_success_completion_authority_exercised"] is False
            and b["mission_state_transition_performed"] is False
            and b["external_network_io_performed"] is False
            and b["target_actuation"] is False
        )
    except Exception:
        return False


def canonical_completion_readiness_definition() -> Dict[str, Any]:
    return {
        "schema_version": COMPLETION_READINESS_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": COMPLETION_READINESS_STAGE_SCHEMA_VERSION,
        "identity_prefix": COMPLETION_READINESS_ID_PREFIX,
        "mode": COMPLETION_READINESS_MODE,
        "authority": COMPLETION_READINESS_AUTHORITY,
        "readiness_status": COMPLETION_READINESS_STATUS,
        "readiness_results": list(READINESS_RESULTS),
        "blocker_codes": list(BLOCKER_CODES),
        "consumes_stage366_success_criteria_evaluation": True,
        "requires_current_active_plan_head": True,
        "lifecycle_constraint": "Mission must be RUNNING for READY; FAILED/ABORTED deterministically produce a lifecycle blocker",
        "fail_closed": True,
        "completion_readiness_decision_performed": True,
        "mission_success_completion_authority_exercised": False,
        "mission_state_transition_performed": False,
        "next_stage": "3.6.8",
    }
