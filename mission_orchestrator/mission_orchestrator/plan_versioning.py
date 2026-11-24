from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError

PLAN_VERSIONING_SCHEMA_VERSION = "apts-mission-plan-version-v1"
PLAN_VERSIONING_HASH_DOMAIN = "MISSION_PLAN_VERSION_V1"
PLAN_VERSIONING_REQUEST_HASH_DOMAIN = "MISSION_PLAN_VERSION_REQUEST_V1"
PLAN_VERSION_RECORD_ID_PREFIX = "pver-"
PLAN_VERSIONING_MODE = "APPEND_ONLY_PLAN_VERSIONS_WITH_CAS_ACTIVE_HEAD_AND_REPLAN_SUPERSESSION"
PLAN_VERSIONING_INITIAL_VERSION = 1
PLAN_VERSIONING_INITIAL_STATE_REQUIRED = "PLANNING"
PLAN_VERSIONING_REPLAN_STATE_REQUIRED = "REPLANNING"
PLAN_VERSIONING_ADAPTIVE_REPLAN_SOURCE_STATES = frozenset({"RUNNING", "WAITING_EVIDENCE", "WAITING_APPROVAL"})
PLAN_VERSIONING_ACTIVE_STATUS = "ACTIVE"
PLAN_VERSIONING_SUPERSEDED_STATUS = "SUPERSEDED"
PLAN_VERSIONING_INITIAL_ACTIVATION_TYPE = "INITIAL_VALIDATED_PLAN"
PLAN_VERSIONING_REPLAN_ACTIVATION_TYPE = "REPLAN_SUCCESSOR"
PLAN_VERSIONING_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_PLAN_LINEAGE_ONLY"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_COMMON_FIELDS = {"idempotency_key", "expected_version_sha256", "expected_state_version", "created_by", "reason", "metadata"}
_INITIAL_FIELDS = _COMMON_FIELDS | {"expected_plan_validation_id", "expected_plan_validation_sha256"}
_REPLAN_FIELDS = _COMMON_FIELDS | {"expected_active_plan_version", "expected_active_plan_sha256", "expected_replan_id"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_plan_version_record_id() -> str:
    return f"{PLAN_VERSION_RECORD_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(value: Any, key: str, max_len: int = 2000) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _positive_int(payload: Mapping[str, Any], key: str) -> int:
    raw = payload.get(key)
    if isinstance(raw, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 1:
        raise MissionValidationError(f"{key} must be >= 1")
    return value


def _normalize_common(payload: Mapping[str, Any]) -> Dict[str, Any]:
    idempotency_key = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idempotency_key):
        raise MissionValidationError("idempotency_key contains unsupported characters")
    expected = _require_string(payload, "expected_version_sha256", 64).lower()
    if not _SHA256_RE.match(expected):
        raise MissionValidationError("expected_version_sha256 must be a lowercase SHA-256 hex digest")
    created_by = _require_string(payload, "created_by")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    try:
        canonical_json(metadata)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError("metadata must contain JSON-serializable values") from exc
    return {
        "idempotency_key": idempotency_key,
        "expected_version_sha256": expected,
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "created_by": created_by,
        "reason": _optional_string(payload.get("reason"), "reason"),
        "metadata": dict(metadata),
    }


def normalize_initial_plan_activation_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("initial plan-version activation request body must be a JSON object")
    unknown = sorted(set(payload) - _INITIAL_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported initial plan-version activation field(s): " + ", ".join(unknown)
            + "; Stage 3.3.7 does not accept caller-supplied authorization, readiness, schedule, dispatch, execution, tasks, or planner output"
        )
    out = _normalize_common(payload)
    validation_id = _require_string(payload, "expected_plan_validation_id", 128)
    validation_sha = _require_string(payload, "expected_plan_validation_sha256", 64).lower()
    if not _SHA256_RE.match(validation_sha):
        raise MissionValidationError("expected_plan_validation_sha256 must be a lowercase SHA-256 hex digest")
    out.update({"operation": "ACTIVATE_INITIAL", "expected_plan_validation_id": validation_id, "expected_plan_validation_sha256": validation_sha})
    return out


def normalize_replan_successor_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("replan successor request body must be a JSON object")
    unknown = sorted(set(payload) - _REPLAN_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported replan successor field(s): " + ", ".join(unknown)
            + "; Stage 3.3.7 derives the successor from canonical planning artifacts and does not accept caller-supplied tasks, planner output, authorization, readiness, schedule, dispatch, or execution commands"
        )
    out = _normalize_common(payload)
    active_sha = _require_string(payload, "expected_active_plan_sha256", 64).lower()
    if not _SHA256_RE.match(active_sha):
        raise MissionValidationError("expected_active_plan_sha256 must be a lowercase SHA-256 hex digest")
    replan_id = _require_string(payload, "expected_replan_id", 128)
    out.update({
        "operation": "REPLAN_SUCCESSOR",
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": active_sha,
        "expected_replan_id": replan_id,
    })
    return out


def plan_version_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": PLAN_VERSIONING_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def candidate_plan_fingerprint(candidate_plan: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": "MISSION_PLAN_VERSION_CANDIDATE_V1", "candidate_plan": dict(candidate_plan)})


def build_plan_version_contract(*, plan_version_record_id: str, mission_id: str, canonical_plan_id: str, plan_version: int,
    request_sha256: str, source_state: Mapping[str, Any], source_version_sha256: str, base_plan_sha256: str,
    candidate_plan: Mapping[str, Any], candidate_plan_sha256: str, planner_profile: str, planner_engine: str,
    planner_engine_version: str, activation_type: str, predecessor: Optional[Mapping[str, Any]],
    plan_validation: Optional[Mapping[str, Any]], replan: Optional[Mapping[str, Any]], created_by: str,
    reason: Optional[str], metadata: Mapping[str, Any], created_at: str) -> Dict[str, Any]:
    if activation_type not in {PLAN_VERSIONING_INITIAL_ACTIVATION_TYPE, PLAN_VERSIONING_REPLAN_ACTIVATION_TYPE}:
        raise MissionValidationError("unsupported Stage-3.3.7 plan activation type")
    predecessor_binding = None if predecessor is None else {
        "plan_version_record_id": predecessor["plan_version_record_id"], "plan_version": int(predecessor["plan_version"]),
        "canonical_sha256": predecessor["canonical_sha256"],
    }
    validation_binding = None if plan_validation is None else {
        "plan_validation_id": plan_validation["plan_validation_id"], "validation_version": int(plan_validation["validation_version"]),
        "validation_status": plan_validation["status"], "feasible": bool(plan_validation["feasible"]),
        "canonical_sha256": plan_validation["canonical_sha256"], "generated_plan_id": plan_validation["generated_plan_id"],
    }
    replan_binding = None if replan is None else {
        "replan_id": replan["replan_id"], "replan_transition_id": replan["transition_id"], "trigger_code": replan.get("trigger_code"),
        "origin": replan.get("origin"), "from_state": replan.get("from_state"), "to_state": replan.get("to_state"),
    }
    core: Dict[str, Any] = {
        "schema_version": PLAN_VERSIONING_SCHEMA_VERSION,
        "identity": {"plan_version_record_id": plan_version_record_id, "mission_id": mission_id, "canonical_plan_id": canonical_plan_id,
                     "plan_version": int(plan_version), "created_by": created_by, "created_at": created_at},
        "activation": {"activation_type": activation_type, "effective_status_at_creation": PLAN_VERSIONING_ACTIVE_STATUS, "immutable_version_artifact": True},
        "lineage": {"predecessor": predecessor_binding, "validation": validation_binding, "replan": replan_binding},
        "source_bindings": {"state": source_state["state"], "state_version": int(source_state["state_version"]),
                            "source_version_sha256": source_version_sha256, "base_plan_sha256": base_plan_sha256,
                            "candidate_plan_sha256": candidate_plan_sha256},
        "planner": {"planner_profile": planner_profile, "planner_engine": planner_engine, "planner_engine_version": planner_engine_version,
                    "deterministic": True, "external_model_invocation_performed": False, "external_network_io_performed": False},
        "candidate_plan": dict(candidate_plan),
        "semantics": {"plan_versioning_mode": PLAN_VERSIONING_MODE, "plan_authority": PLAN_VERSIONING_AUTHORITY,
                      "plan_version_is_authorization": False, "feasible_is_authorized": False, "task_is_dispatch": False,
                      "readiness_is_permission": False, "planner_is_governance": False,
                      "governance_authorization_authority": "EXTERNAL_APTS_GSS", "governance_authorization_query_performed": False,
                      "scheduling_performed": False, "target_action_dispatch_enabled": False, "target_actuation": False,
                      "predecessor_artifact_mutated": False},
        "provenance": {"request_sha256": request_sha256, "reason": reason, "metadata": dict(metadata)},
    }
    digest = sha256_hex({"hash_domain": PLAN_VERSIONING_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "hash_domain": PLAN_VERSIONING_HASH_DOMAIN,
                                  "canonicalization": "UTF8_SORTED_JSON_V1", "canonical_sha256": digest}}


def verify_plan_version_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != PLAN_VERSIONING_SCHEMA_VERSION:
            return False
        identity, activation, lineage = contract["identity"], contract["activation"], contract["lineage"]
        source, semantics, planner, candidate = contract["source_bindings"], contract["semantics"], contract["planner"], contract["candidate_plan"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        integrity = contract["integrity"]
        version = int(identity["plan_version"])
        predecessor = lineage.get("predecessor")
        activation_type = activation.get("activation_type")
        lineage_ok = False
        if version == PLAN_VERSIONING_INITIAL_VERSION:
            lineage_ok = (predecessor is None and activation_type == PLAN_VERSIONING_INITIAL_ACTIVATION_TYPE
                          and lineage.get("validation") is not None
                          and lineage["validation"].get("validation_status") == "VALIDATED_FEASIBLE"
                          and lineage["validation"].get("feasible") is True and lineage.get("replan") is None)
        elif version > PLAN_VERSIONING_INITIAL_VERSION:
            lineage_ok = (predecessor is not None and int(predecessor.get("plan_version")) == version - 1
                          and str(predecessor.get("plan_version_record_id") or "").startswith(PLAN_VERSION_RECORD_ID_PREFIX)
                          and _SHA256_RE.match(str(predecessor.get("canonical_sha256") or "")) is not None
                          and activation_type == PLAN_VERSIONING_REPLAN_ACTIVATION_TYPE and lineage.get("replan") is not None
                          and isinstance(lineage["replan"].get("replan_id"), str) and bool(lineage["replan"]["replan_id"]))
        source_state = source.get("state")
        if version == PLAN_VERSIONING_INITIAL_VERSION:
            source_state_ok = source_state == PLAN_VERSIONING_INITIAL_STATE_REQUIRED
        elif activation_type == PLAN_VERSIONING_REPLAN_ACTIVATION_TYPE:
            replan_origin = (lineage.get("replan") or {}).get("origin")
            if replan_origin == "STAGE3_7_AUTHORITATIVE_REPLAN_COMMIT":
                source_state_ok = source_state in PLAN_VERSIONING_ADAPTIVE_REPLAN_SOURCE_STATES
            else:
                source_state_ok = source_state == PLAN_VERSIONING_REPLAN_STATE_REQUIRED
        else:
            source_state_ok = False
        return (
            integrity.get("hash_domain") == PLAN_VERSIONING_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex({"hash_domain": PLAN_VERSIONING_HASH_DOMAIN, "core": core})
            and str(identity.get("plan_version_record_id") or "").startswith(PLAN_VERSION_RECORD_ID_PREFIX)
            and str(identity.get("canonical_plan_id") or "").startswith("mplan-") and version >= 1
            and activation.get("effective_status_at_creation") == PLAN_VERSIONING_ACTIVE_STATUS
            and activation.get("immutable_version_artifact") is True
            and source_state_ok
            and int(source.get("state_version")) >= 1
            and _SHA256_RE.match(str(source.get("source_version_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("base_plan_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("candidate_plan_sha256") or "")) is not None
            and isinstance(candidate, Mapping) and candidate.get("status") == "GENERATED_UNVALIDATED" and int(candidate.get("task_count")) >= 1
            and planner.get("deterministic") is True and planner.get("external_model_invocation_performed") is False
            and planner.get("external_network_io_performed") is False
            and semantics.get("plan_version_is_authorization") is False and semantics.get("feasible_is_authorized") is False
            and semantics.get("task_is_dispatch") is False and semantics.get("readiness_is_permission") is False
            and semantics.get("planner_is_governance") is False and semantics.get("governance_authorization_authority") == "EXTERNAL_APTS_GSS"
            and semantics.get("governance_authorization_query_performed") is False and semantics.get("scheduling_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False and semantics.get("target_actuation") is False
            and semantics.get("predecessor_artifact_mutated") is False and lineage_ok
        )
    except Exception:
        return False


def canonical_plan_versioning_definition() -> Dict[str, Any]:
    return {
        "schema_version": PLAN_VERSIONING_SCHEMA_VERSION, "mode": PLAN_VERSIONING_MODE,
        "plan_version_record_id_prefix": PLAN_VERSION_RECORD_ID_PREFIX, "initial_plan_version": PLAN_VERSIONING_INITIAL_VERSION,
        "initial_activation_state_required": PLAN_VERSIONING_INITIAL_STATE_REQUIRED, "replan_successor_state_required": PLAN_VERSIONING_REPLAN_STATE_REQUIRED,
        "initial_activation_requires_stage3_3_6_validated_feasible": True, "replan_successor_requires_stage3_2_6_replan_lineage": True,
        "replan_successor_requires_active_plan_head_cas": True, "successor_version_rule": "EXACT_PREDECESSOR_PLUS_ONE",
        "single_active_head_per_mission": True, "old_version_rows_mutated_on_supersession": False,
        "effective_old_status": PLAN_VERSIONING_SUPERSEDED_STATUS, "planner_reinvocation_performed_for_replan": True,
        "planner_reinvocation_mode": "LOCAL_DETERMINISTIC_FROM_CANONICAL_STAGE3_3_2_TO_3_3_4_ARTIFACTS",
        "external_model_invocation_performed": False, "external_network_io_performed": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS", "plan_version_is_authorization": False,
        "task_is_dispatch": False, "readiness_is_permission": False, "planner_is_governance": False,
        "target_action_dispatch_enabled": False, "target_actuation": False,
    }
