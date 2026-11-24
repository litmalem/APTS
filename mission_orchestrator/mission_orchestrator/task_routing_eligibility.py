from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence

from .errors import MissionValidationError
from .subsystem_registry import verify_capability_contract, verify_subsystem_contract
from .task_decomposition import PLANNED_TASK_SCHEMA_VERSION
from .task_routing_intent import verify_task_routing_intent_contract

TASK_ROUTING_ELIGIBILITY_SCHEMA_VERSION = "apts-task-routing-eligibility-compatibility-gate-v1"
TASK_ROUTING_ELIGIBILITY_HASH_DOMAIN = "MISSION_TASK_ROUTING_ELIGIBILITY_COMPATIBILITY_GATE_V1"
TASK_ROUTING_ELIGIBILITY_REQUEST_HASH_DOMAIN = "MISSION_TASK_ROUTING_ELIGIBILITY_REQUEST_V1"
TASK_ROUTING_ELIGIBILITY_ID_PREFIX = "relig-"
TASK_ROUTING_ELIGIBILITY_MODE = "FAIL_CLOSED_CANONICAL_CANDIDATE_ELIGIBILITY_AND_COMPATIBILITY_GATE"
TASK_ROUTING_ELIGIBILITY_ALLOWED_STATES = frozenset({"PLANNING", "REPLANNING"})
ELIGIBILITY_EVALUATION_MODE = "STATIC_CANONICAL_CONTRACT_COMPATIBILITY_ONLY"
ELIGIBILITY_STATUS_ELIGIBLE = "ELIGIBLE_CANDIDATES_AVAILABLE"
ELIGIBILITY_STATUS_NONE = "NO_ELIGIBLE_CANDIDATE"
ELIGIBILITY_GATE_PASSED = "PASSED"
ELIGIBILITY_GATE_FAILED_CLOSED = "FAILED_CLOSED"
CANDIDATE_ELIGIBLE = "ELIGIBLE"
CANDIDATE_INELIGIBLE = "INELIGIBLE"

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_task_readiness_projection_id",
    "expected_task_readiness_projection_sha256",
    "expected_routing_intent_id",
    "expected_routing_intent_sha256",
    "planned_task_id",
    "created_by",
    "reason",
    "metadata",
}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_task_routing_eligibility_id() -> str:
    return f"{TASK_ROUTING_ELIGIBILITY_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
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


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _require_string(payload, key, 64).lower()
    if not _SHA256_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_task_routing_eligibility_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task routing eligibility request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task routing eligibility field(s): " + ", ".join(unknown)
            + "; Stage 3.4.3 derives candidate eligibility exclusively from the active canonical Plan, active READY projection, immutable Stage-3.4.2 routing intent, immutable Mission required_subsystems, and canonical Stage-3.4.1 registry. Caller-supplied eligibility result, eligible candidates, ranking, selected route, endpoint, health, resource assignment, authorization, delegation, dispatch, execution, or target-action fields are forbidden"
        )

    values = {
        "idempotency_key": _require_string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _require_string(payload, "expected_active_plan_version_record_id", 160),
        "expected_task_readiness_projection_id": _require_string(payload, "expected_task_readiness_projection_id", 160),
        "expected_routing_intent_id": _require_string(payload, "expected_routing_intent_id", 160),
        "planned_task_id": _require_string(payload, "planned_task_id", 160),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_routing_intent_id"].startswith("rint-"):
        raise MissionValidationError("expected_routing_intent_id must be a canonical rint-* identifier")
    if not values["planned_task_id"].startswith("ptask-"):
        raise MissionValidationError("planned_task_id must be a canonical ptask-* identifier")

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
        "expected_task_readiness_projection_sha256": _sha(payload, "expected_task_readiness_projection_sha256"),
        "expected_routing_intent_sha256": _sha(payload, "expected_routing_intent_sha256"),
        "created_by": _require_string(payload, "created_by", 128),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_routing_eligibility_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_ROUTING_ELIGIBILITY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _candidate_registry_records(
    registry_snapshot: Mapping[str, Any], subsystem_id: str, capability_id: str
) -> tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
    subsystem = next(
        (
            item
            for item in registry_snapshot.get("subsystems", [])
            if item.get("identity", {}).get("subsystem_id") == subsystem_id
        ),
        None,
    )
    capability = next(
        (
            item
            for item in registry_snapshot.get("capabilities", [])
            if item.get("identity", {}).get("subsystem_id") == subsystem_id
            and item.get("identity", {}).get("capability_id") == capability_id
        ),
        None,
    )
    return subsystem, capability


def evaluate_routing_eligibility(
    routing_intent_contract: Mapping[str, Any],
    registry_snapshot: Mapping[str, Any],
    mission_required_subsystems: Sequence[str],
) -> Dict[str, Any]:
    """Evaluate only static, canonical eligibility/compatibility predicates.

    No runtime endpoint lookup, health probe, resource assignment, Governance query,
    authorization, route ranking/selection, delegation, dispatch, or target actuation is
    performed here. Stage 3.4.3 can therefore deterministically re-evaluate the result
    from durable canonical artifacts.
    """

    if not verify_task_routing_intent_contract(routing_intent_contract):
        raise MissionValidationError("routing_intent_contract failed Stage-3.4.2 integrity verification")

    intent = routing_intent_contract["routing_intent"]
    required_subsystem = str(intent["required_subsystem"])
    required_capability = str(intent["required_capability"])
    task_schema = str(intent.get("task_schema_version") or PLANNED_TASK_SCHEMA_VERSION)
    mission_subsystems = {str(x).upper() for x in mission_required_subsystems}

    candidate_evaluations: list[Dict[str, Any]] = []
    eligible_candidates: list[Dict[str, Any]] = []
    ineligible_candidates: list[Dict[str, Any]] = []

    for candidate in list(intent.get("candidates") or []):
        subsystem_id = str(candidate.get("subsystem_id") or "")
        capability_id = str(candidate.get("capability_id") or "")
        subsystem, capability = _candidate_registry_records(registry_snapshot, subsystem_id, capability_id)

        checks: Dict[str, bool] = {
            "candidate_originates_from_stage342": True,
            "required_subsystem_exact_match": subsystem_id == required_subsystem,
            "required_capability_exact_match": capability_id == required_capability,
            "mission_declares_required_subsystem": subsystem_id in mission_subsystems,
            "subsystem_contract_present": subsystem is not None,
            "capability_contract_present": capability is not None,
            "subsystem_contract_integrity_valid": subsystem is not None and verify_subsystem_contract(subsystem),
            "capability_contract_integrity_valid": capability is not None and verify_capability_contract(capability),
            "subsystem_contract_hash_matches_candidate": subsystem is not None
            and subsystem.get("integrity", {}).get("canonical_sha256") == candidate.get("subsystem_contract_sha256"),
            "capability_contract_hash_matches_candidate": capability is not None
            and capability.get("integrity", {}).get("canonical_sha256") == candidate.get("capability_contract_sha256"),
            "subsystem_registered_and_enabled": subsystem is not None
            and subsystem.get("registration", {}).get("status") == "REGISTERED"
            and subsystem.get("registration", {}).get("enabled") is True,
            "capability_registered_and_enabled": capability is not None
            and capability.get("registration", {}).get("status") == "REGISTERED"
            and capability.get("registration", {}).get("enabled") is True,
            "subsystem_accepts_task_schema": subsystem is not None
            and task_schema in subsystem.get("contract", {}).get("accepted_task_schema_versions", []),
            "capability_accepts_task_schema": capability is not None
            and task_schema in capability.get("compatibility", {}).get("accepted_task_schema_versions", []),
            "capability_match_mode_exact": capability is not None
            and capability.get("compatibility", {}).get("required_capability_match") == "EXACT_CAPABILITY_ID",
            "capability_required_subsystem_matches": capability is not None
            and capability.get("compatibility", {}).get("required_subsystem") == required_subsystem,
            "capability_declares_delegation_eligible": capability is not None
            and capability.get("semantics", {}).get("delegation_eligible") is True,
            "candidate_runtime_endpoint_unresolved": candidate.get("runtime", {}).get("endpoint_resolved") is False,
            "candidate_runtime_health_unprobed": candidate.get("runtime", {}).get("health_probed") is False,
        }

        reason_map = {
            "required_subsystem_exact_match": "REQUIRED_SUBSYSTEM_MISMATCH",
            "required_capability_exact_match": "REQUIRED_CAPABILITY_MISMATCH",
            "mission_declares_required_subsystem": "SUBSYSTEM_OUTSIDE_MISSION_REQUIRED_SUBSYSTEMS",
            "subsystem_contract_present": "SUBSYSTEM_CONTRACT_NOT_FOUND",
            "capability_contract_present": "CAPABILITY_CONTRACT_NOT_FOUND",
            "subsystem_contract_integrity_valid": "SUBSYSTEM_CONTRACT_INTEGRITY_INVALID",
            "capability_contract_integrity_valid": "CAPABILITY_CONTRACT_INTEGRITY_INVALID",
            "subsystem_contract_hash_matches_candidate": "SUBSYSTEM_CONTRACT_HASH_MISMATCH",
            "capability_contract_hash_matches_candidate": "CAPABILITY_CONTRACT_HASH_MISMATCH",
            "subsystem_registered_and_enabled": "SUBSYSTEM_NOT_REGISTERED_OR_ENABLED",
            "capability_registered_and_enabled": "CAPABILITY_NOT_REGISTERED_OR_ENABLED",
            "subsystem_accepts_task_schema": "SUBSYSTEM_TASK_SCHEMA_INCOMPATIBLE",
            "capability_accepts_task_schema": "CAPABILITY_TASK_SCHEMA_INCOMPATIBLE",
            "capability_match_mode_exact": "CAPABILITY_MATCH_MODE_NOT_EXACT",
            "capability_required_subsystem_matches": "CAPABILITY_REQUIRED_SUBSYSTEM_MISMATCH",
            "capability_declares_delegation_eligible": "CAPABILITY_NOT_DECLARED_DELEGATION_ELIGIBLE",
            "candidate_runtime_endpoint_unresolved": "STAGE342_CANDIDATE_ALREADY_RUNTIME_BOUND",
            "candidate_runtime_health_unprobed": "STAGE342_CANDIDATE_ALREADY_RUNTIME_PROBED",
        }
        reasons = [reason_map[key] for key, ok in checks.items() if not ok and key in reason_map]
        status = CANDIDATE_ELIGIBLE if not reasons else CANDIDATE_INELIGIBLE
        evaluation = {
            "candidate_index": int(candidate.get("candidate_index") or 0),
            "subsystem_id": subsystem_id,
            "capability_id": capability_id,
            "capability_version": int(candidate.get("capability_version") or 0),
            "side_effect_class": candidate.get("side_effect_class"),
            "eligibility_status": status,
            "compatibility_checks": checks,
            "rejection_reasons": reasons,
            "runtime": {
                "endpoint_resolved": False,
                "health_probed": False,
                "availability": "UNKNOWN_NOT_PROBED",
                "runtime_availability_is_eligibility": False,
            },
        }
        candidate_evaluations.append(evaluation)
        target = eligible_candidates if status == CANDIDATE_ELIGIBLE else ineligible_candidates
        target.append(evaluation)

    candidate_evaluations.sort(key=lambda x: (x["candidate_index"], x["subsystem_id"], x["capability_id"]))
    eligible_candidates.sort(key=lambda x: (x["candidate_index"], x["subsystem_id"], x["capability_id"]))
    ineligible_candidates.sort(key=lambda x: (x["candidate_index"], x["subsystem_id"], x["capability_id"]))

    if not candidate_evaluations:
        gate_reasons = ["NO_STAGE342_CANDIDATE"]
    elif not eligible_candidates:
        gate_reasons = ["ALL_STAGE342_CANDIDATES_INELIGIBLE"]
    else:
        gate_reasons = []

    eligibility_status = ELIGIBILITY_STATUS_ELIGIBLE if eligible_candidates else ELIGIBILITY_STATUS_NONE
    gate_result = ELIGIBILITY_GATE_PASSED if eligible_candidates else ELIGIBILITY_GATE_FAILED_CLOSED
    return {
        "mode": ELIGIBILITY_EVALUATION_MODE,
        "gate_result": gate_result,
        "eligibility_status": eligibility_status,
        "candidate_count": len(candidate_evaluations),
        "eligible_candidate_count": len(eligible_candidates),
        "ineligible_candidate_count": len(ineligible_candidates),
        "candidate_evaluations": candidate_evaluations,
        "eligible_candidates": eligible_candidates,
        "ineligible_candidates": ineligible_candidates,
        "gate_rejection_reasons": gate_reasons,
        "runtime_availability_considered": False,
        "governance_authorization_considered": False,
    }


def build_task_routing_eligibility_contract(
    *,
    eligibility_gate_id: str,
    mission_id: str,
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    readiness_projection: Mapping[str, Any],
    routing_intent: Mapping[str, Any],
    registry_snapshot: Mapping[str, Any],
    mission_required_subsystems: Sequence[str],
    created_by: str,
    reason: Optional[str],
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    routing_contract = routing_intent["routing_intent_contract"]
    evaluation = evaluate_routing_eligibility(routing_contract, registry_snapshot, mission_required_subsystems)
    routing_identity = routing_contract["identity"]
    core = {
        "schema_version": TASK_ROUTING_ELIGIBILITY_SCHEMA_VERSION,
        "identity": {
            "eligibility_gate_id": eligibility_gate_id,
            "mission_id": mission_id,
            "routing_intent_id": routing_intent["routing_intent_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": routing_identity["planned_task_id"],
            "task_key": routing_identity["task_key"],
            "created_by": created_by,
            "created_at": created_at,
        },
        "source_bindings": {
            "state": source_state["state"],
            "state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "task_readiness_projection_id": readiness_projection["projection_id"],
            "task_readiness_projection_sha256": readiness_projection["canonical_sha256"],
            "routing_intent_id": routing_intent["routing_intent_id"],
            "routing_intent_sha256": routing_intent["canonical_sha256"],
            "registry_id": registry_snapshot["identity"]["registry_id"],
            "registry_version": int(registry_snapshot["identity"]["registry_version"]),
            "registry_sha256": registry_snapshot["integrity"]["canonical_sha256"],
            "mission_required_subsystems": sorted({str(x).upper() for x in mission_required_subsystems}),
            "mission_required_subsystems_sha256": sha256_hex(
                {"required_subsystems": sorted({str(x).upper() for x in mission_required_subsystems})}
            ),
        },
        "eligibility_gate": {
            "task_schema_version": routing_contract["routing_intent"]["task_schema_version"],
            "task_type": routing_contract["routing_intent"]["task_type"],
            "required_subsystem": routing_contract["routing_intent"]["required_subsystem"],
            "required_capability": routing_contract["routing_intent"]["required_capability"],
            **evaluation,
        },
        "semantics": {
            "mode": TASK_ROUTING_ELIGIBILITY_MODE,
            "candidate_resolution_inherited_from_stage342": True,
            "eligibility_gate_performed": True,
            "compatibility_gate_performed": True,
            "eligibility_gate_static_contract_only": True,
            "eligible_candidate_is_selected_route": False,
            "eligibility_is_authorization": False,
            "eligibility_is_runtime_availability": False,
            "route_selection_performed": False,
            "route_ranking_performed": False,
            "selected_subsystem": None,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "governance_query_performed": False,
            "authorization_granted": False,
            "delegation_performed": False,
            "dispatch_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "version_vector_extension_performed": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": TASK_ROUTING_ELIGIBILITY_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": TASK_ROUTING_ELIGIBILITY_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_task_routing_eligibility_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        gate = contract["eligibility_gate"]
        semantics = contract["semantics"]
        evaluations = list(gate["candidate_evaluations"])
        eligible = list(gate["eligible_candidates"])
        ineligible = list(gate["ineligible_candidates"])
        expected_gate = ELIGIBILITY_GATE_PASSED if eligible else ELIGIBILITY_GATE_FAILED_CLOSED
        expected_status = ELIGIBILITY_STATUS_ELIGIBLE if eligible else ELIGIBILITY_STATUS_NONE
        counts_ok = (
            int(gate["candidate_count"]) == len(evaluations)
            and int(gate["eligible_candidate_count"]) == len(eligible)
            and int(gate["ineligible_candidate_count"]) == len(ineligible)
            and len(evaluations) == len(eligible) + len(ineligible)
        )
        eval_ok = all(
            item.get("eligibility_status") in {CANDIDATE_ELIGIBLE, CANDIDATE_INELIGIBLE}
            and item.get("runtime", {}).get("endpoint_resolved") is False
            and item.get("runtime", {}).get("health_probed") is False
            and item.get("runtime", {}).get("runtime_availability_is_eligibility") is False
            for item in evaluations
        )
        return (
            contract.get("schema_version") == TASK_ROUTING_ELIGIBILITY_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == TASK_ROUTING_ELIGIBILITY_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256")
            == sha256_hex({"hash_domain": TASK_ROUTING_ELIGIBILITY_HASH_DOMAIN, "core": core})
            and str(identity.get("eligibility_gate_id") or "").startswith(TASK_ROUTING_ELIGIBILITY_ID_PREFIX)
            and str(identity.get("routing_intent_id") or "").startswith("rint-")
            and str(identity.get("plan_version_record_id") or "").startswith("pver-")
            and str(identity.get("planned_task_id") or "").startswith("ptask-")
            and int(identity.get("plan_version")) >= 1
            and source.get("state") in TASK_ROUTING_ELIGIBILITY_ALLOWED_STATES
            and int(source.get("state_version")) >= 1
            and all(
                _SHA256_RE.match(str(source.get(key) or ""))
                for key in (
                    "source_version_sha256",
                    "active_plan_sha256",
                    "task_readiness_projection_sha256",
                    "routing_intent_sha256",
                    "registry_sha256",
                    "mission_required_subsystems_sha256",
                )
            )
            and source.get("routing_intent_id") == identity.get("routing_intent_id")
            and gate.get("task_schema_version") == PLANNED_TASK_SCHEMA_VERSION
            and gate.get("mode") == ELIGIBILITY_EVALUATION_MODE
            and gate.get("gate_result") == expected_gate
            and gate.get("eligibility_status") == expected_status
            and counts_ok
            and eval_ok
            and gate.get("runtime_availability_considered") is False
            and gate.get("governance_authorization_considered") is False
            and semantics.get("mode") == TASK_ROUTING_ELIGIBILITY_MODE
            and semantics.get("candidate_resolution_inherited_from_stage342") is True
            and semantics.get("eligibility_gate_performed") is True
            and semantics.get("compatibility_gate_performed") is True
            and semantics.get("eligibility_gate_static_contract_only") is True
            and semantics.get("eligible_candidate_is_selected_route") is False
            and semantics.get("eligibility_is_authorization") is False
            and semantics.get("eligibility_is_runtime_availability") is False
            and semantics.get("route_selection_performed") is False
            and semantics.get("route_ranking_performed") is False
            and semantics.get("selected_subsystem") is None
            and semantics.get("runtime_endpoint_resolution_performed") is False
            and semantics.get("runtime_health_probe_performed") is False
            and semantics.get("resource_assignment_performed") is False
            and semantics.get("governance_query_performed") is False
            and semantics.get("authorization_granted") is False
            and semantics.get("delegation_performed") is False
            and semantics.get("dispatch_performed") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
            and semantics.get("version_vector_extension_performed") is False
            and semantics.get("governance_authorization_authority") == "EXTERNAL_APTS_GSS"
        )
    except Exception:
        return False


def canonical_task_routing_eligibility_definition() -> Dict[str, Any]:
    return {
        "schema_version": TASK_ROUTING_ELIGIBILITY_SCHEMA_VERSION,
        "mode": TASK_ROUTING_ELIGIBILITY_MODE,
        "eligibility_gate_id_prefix": TASK_ROUTING_ELIGIBILITY_ID_PREFIX,
        "allowed_source_states": sorted(TASK_ROUTING_ELIGIBILITY_ALLOWED_STATES),
        "evaluation_mode": ELIGIBILITY_EVALUATION_MODE,
        "requires_active_plan_version": True,
        "requires_active_task_readiness_projection": True,
        "requires_ready_task": True,
        "requires_stage342_routing_intent": True,
        "requires_current_registry_snapshot": True,
        "requires_mission_required_subsystem_membership": True,
        "candidate_resolution_inherited_from_stage342": True,
        "eligibility_gate_performed": True,
        "compatibility_gate_performed": True,
        "eligibility_gate_static_contract_only": True,
        "eligible_candidate_is_selected_route": False,
        "eligibility_is_authorization": False,
        "eligibility_is_runtime_availability": False,
        "route_selection_performed": False,
        "route_ranking_performed": False,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "governance_query_performed": False,
        "authorization_granted": False,
        "delegation_performed": False,
        "dispatch_performed": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "version_vector_extension_performed": False,
    }
