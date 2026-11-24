from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError
from .task_routing_eligibility import (
    CANDIDATE_ELIGIBLE,
    ELIGIBILITY_GATE_PASSED,
    ELIGIBILITY_STATUS_ELIGIBLE,
    verify_task_routing_eligibility_contract,
)

TASK_ROUTE_SELECTION_SCHEMA_VERSION = "apts-task-deterministic-route-selection-decision-v1"
TASK_ROUTE_SELECTION_HASH_DOMAIN = "MISSION_TASK_DETERMINISTIC_ROUTE_SELECTION_DECISION_V1"
TASK_ROUTE_SELECTION_REQUEST_HASH_DOMAIN = "MISSION_TASK_ROUTE_SELECTION_REQUEST_V1"
TASK_ROUTE_SELECTION_ID_PREFIX = "rdec-"
TASK_ROUTE_SELECTION_MODE = "DETERMINISTIC_ELIGIBLE_CANDIDATE_ROUTE_SELECTION_WITH_IMMUTABLE_DECISION_RECORD"
TASK_ROUTE_SELECTION_ALLOWED_STATES = frozenset({"PLANNING", "REPLANNING"})
ROUTE_SELECTION_POLICY = "STAGE343_ELIGIBLE_CANONICAL_TUPLE_ASC_V1"
ROUTE_DECISION_SELECTED = "ROUTE_SELECTED"
ROUTE_DECISION_NO_ROUTE = "NO_ELIGIBLE_ROUTE"

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
    "expected_eligibility_gate_id",
    "expected_eligibility_gate_sha256",
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


def new_task_route_decision_id() -> str:
    return f"{TASK_ROUTE_SELECTION_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_task_route_selection_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task route-selection request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task route-selection field(s): " + ", ".join(unknown)
            + "; Stage 3.4.4 derives ranking and selection exclusively from the immutable Stage-3.4.3 eligible-candidate set. "
            "Caller-supplied candidates, rank/score/priority, selected route/subsystem/capability, endpoint, health, resource assignment, "
            "authorization, delegation, dispatch, execution, or target-action fields are forbidden"
        )

    values = {
        "idempotency_key": _require_string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _require_string(payload, "expected_active_plan_version_record_id", 160),
        "expected_task_readiness_projection_id": _require_string(payload, "expected_task_readiness_projection_id", 160),
        "expected_routing_intent_id": _require_string(payload, "expected_routing_intent_id", 160),
        "expected_eligibility_gate_id": _require_string(payload, "expected_eligibility_gate_id", 160),
        "planned_task_id": _require_string(payload, "planned_task_id", 160),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_routing_intent_id"].startswith("rint-"):
        raise MissionValidationError("expected_routing_intent_id must be a canonical rint-* identifier")
    if not values["expected_eligibility_gate_id"].startswith("relig-"):
        raise MissionValidationError("expected_eligibility_gate_id must be a canonical relig-* identifier")
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
        "expected_eligibility_gate_sha256": _sha(payload, "expected_eligibility_gate_sha256"),
        "created_by": _require_string(payload, "created_by", 128),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_route_selection_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_ROUTE_SELECTION_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _selection_key(candidate: Mapping[str, Any]) -> tuple[int, str, str, int]:
    return (
        int(candidate.get("candidate_index") or 0),
        str(candidate.get("subsystem_id") or ""),
        str(candidate.get("capability_id") or ""),
        int(candidate.get("capability_version") or 0),
    )


def deterministically_select_route(eligibility_contract: Mapping[str, Any]) -> Dict[str, Any]:
    """Rank only Stage-3.4.3 ELIGIBLE candidates and deterministically select rank 1.

    The policy is deliberately static and local. It performs no endpoint resolution,
    runtime health probe, resource assignment, Governance query, authorization,
    delegation, dispatch, or execution.
    """
    if not verify_task_routing_eligibility_contract(eligibility_contract):
        raise MissionValidationError("eligibility_contract failed Stage-3.4.3 integrity verification")

    gate = eligibility_contract["eligibility_gate"]
    eligible = list(gate.get("eligible_candidates") or [])
    # Never expand or resurrect the candidate set: only the persisted ELIGIBLE projection is consumed.
    if any(item.get("eligibility_status") != CANDIDATE_ELIGIBLE for item in eligible):
        raise MissionValidationError("Stage-3.4.3 eligible_candidates contains a non-ELIGIBLE candidate")

    identities = [
        (
            str(item.get("subsystem_id") or ""),
            str(item.get("capability_id") or ""),
            int(item.get("capability_version") or 0),
            int(item.get("candidate_index") or 0),
        )
        for item in eligible
    ]
    if len(set(identities)) != len(identities):
        raise MissionValidationError("Stage-3.4.3 eligible candidate set contains duplicate canonical candidate identities")

    ordered = sorted(eligible, key=_selection_key)
    ranked_candidates: list[Dict[str, Any]] = []
    for rank, item in enumerate(ordered, start=1):
        key = _selection_key(item)
        ranked_candidates.append(
            {
                "rank": rank,
                "selection_key": {
                    "candidate_index": key[0],
                    "subsystem_id": key[1],
                    "capability_id": key[2],
                    "capability_version": key[3],
                },
                "candidate_index": key[0],
                "subsystem_id": key[1],
                "capability_id": key[2],
                "capability_version": key[3],
                "side_effect_class": item.get("side_effect_class"),
                "eligibility_status": item.get("eligibility_status"),
                "runtime": {
                    "endpoint_resolved": False,
                    "health_probed": False,
                    "availability": "UNKNOWN_NOT_PROBED",
                },
            }
        )

    selected = ranked_candidates[0] if ranked_candidates else None
    route_selected = selected is not None
    if route_selected:
        selected_route: Optional[Dict[str, Any]] = {
            "rank": int(selected["rank"]),
            "candidate_index": int(selected["candidate_index"]),
            "subsystem_id": selected["subsystem_id"],
            "capability_id": selected["capability_id"],
            "capability_version": int(selected["capability_version"]),
            "side_effect_class": selected.get("side_effect_class"),
            "logical_route_only": True,
            "runtime": {
                "endpoint_resolved": False,
                "health_probed": False,
                "availability": "UNKNOWN_NOT_PROBED",
            },
        }
        decision_status = ROUTE_DECISION_SELECTED
        decision_reasons = ["DETERMINISTIC_RANK_1_FROM_STAGE343_ELIGIBLE_CANDIDATES"]
    else:
        selected_route = None
        decision_status = ROUTE_DECISION_NO_ROUTE
        decision_reasons = ["NO_STAGE343_ELIGIBLE_CANDIDATE"]

    return {
        "selection_policy": ROUTE_SELECTION_POLICY,
        "eligible_candidate_count": len(ranked_candidates),
        "ranked_candidate_count": len(ranked_candidates),
        "ranked_candidates": ranked_candidates,
        "decision_status": decision_status,
        "route_selected": route_selected,
        "selected_route": selected_route,
        "selected_subsystem": None if selected_route is None else selected_route["subsystem_id"],
        "selected_capability": None if selected_route is None else selected_route["capability_id"],
        "decision_reasons": decision_reasons,
        "runtime_availability_considered": False,
        "governance_authorization_considered": False,
    }


def build_task_route_selection_contract(
    *,
    route_decision_id: str,
    mission_id: str,
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    readiness_projection: Mapping[str, Any],
    routing_intent: Mapping[str, Any],
    eligibility_gate: Mapping[str, Any],
    registry_snapshot: Mapping[str, Any],
    created_by: str,
    reason: Optional[str],
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    eligibility_contract = eligibility_gate["eligibility_contract"]
    decision = deterministically_select_route(eligibility_contract)
    identity = eligibility_contract["identity"]
    core = {
        "schema_version": TASK_ROUTE_SELECTION_SCHEMA_VERSION,
        "identity": {
            "route_decision_id": route_decision_id,
            "mission_id": mission_id,
            "eligibility_gate_id": eligibility_gate["eligibility_gate_id"],
            "routing_intent_id": routing_intent["routing_intent_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": identity["planned_task_id"],
            "task_key": identity["task_key"],
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
            "eligibility_gate_id": eligibility_gate["eligibility_gate_id"],
            "eligibility_gate_sha256": eligibility_gate["canonical_sha256"],
            "registry_id": registry_snapshot["identity"]["registry_id"],
            "registry_version": int(registry_snapshot["identity"]["registry_version"]),
            "registry_sha256": registry_snapshot["integrity"]["canonical_sha256"],
        },
        "route_decision": {
            "required_subsystem": eligibility_contract["eligibility_gate"]["required_subsystem"],
            "required_capability": eligibility_contract["eligibility_gate"]["required_capability"],
            "source_gate_result": eligibility_gate["gate_result"],
            "source_eligibility_status": eligibility_gate["eligibility_status"],
            **decision,
        },
        "semantics": {
            "mode": TASK_ROUTE_SELECTION_MODE,
            "eligibility_source_is_stage343_only": True,
            "route_ranking_performed": True,
            "route_selection_decision_performed": True,
            "route_selected": bool(decision["route_selected"]),
            "selected_route_is_logical_only": True,
            "selection_is_authorization": False,
            "selection_is_runtime_availability": False,
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
    digest = sha256_hex({"hash_domain": TASK_ROUTE_SELECTION_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": TASK_ROUTE_SELECTION_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_task_route_selection_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        decision = contract["route_decision"]
        semantics = contract["semantics"]
        ranked = list(decision.get("ranked_candidates") or [])
        selected = decision.get("selected_route")
        expected_selected = ranked[0] if ranked else None
        ranks_ok = [int(x.get("rank") or 0) for x in ranked] == list(range(1, len(ranked) + 1))
        ordered_ok = ranked == sorted(ranked, key=lambda x: (
            int(x.get("candidate_index") or 0),
            str(x.get("subsystem_id") or ""),
            str(x.get("capability_id") or ""),
            int(x.get("capability_version") or 0),
        ))
        selected_ok = (
            (expected_selected is None and selected is None and decision.get("route_selected") is False
             and decision.get("decision_status") == ROUTE_DECISION_NO_ROUTE
             and decision.get("selected_subsystem") is None and decision.get("selected_capability") is None)
            or
            (expected_selected is not None and isinstance(selected, dict) and decision.get("route_selected") is True
             and decision.get("decision_status") == ROUTE_DECISION_SELECTED
             and selected.get("rank") == 1
             and selected.get("candidate_index") == expected_selected.get("candidate_index")
             and selected.get("subsystem_id") == expected_selected.get("subsystem_id")
             and selected.get("capability_id") == expected_selected.get("capability_id")
             and int(selected.get("capability_version") or 0) == int(expected_selected.get("capability_version") or 0)
             and decision.get("selected_subsystem") == selected.get("subsystem_id")
             and decision.get("selected_capability") == selected.get("capability_id")
             and selected.get("logical_route_only") is True
             and selected.get("runtime", {}).get("endpoint_resolved") is False
             and selected.get("runtime", {}).get("health_probed") is False)
        )
        source_gate_allows_selected = (
            (not decision.get("route_selected"))
            or (decision.get("source_gate_result") == ELIGIBILITY_GATE_PASSED
                and decision.get("source_eligibility_status") == ELIGIBILITY_STATUS_ELIGIBLE)
        )
        return (
            contract.get("schema_version") == TASK_ROUTE_SELECTION_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == TASK_ROUTE_SELECTION_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256")
            == sha256_hex({"hash_domain": TASK_ROUTE_SELECTION_HASH_DOMAIN, "core": core})
            and str(identity.get("route_decision_id") or "").startswith(TASK_ROUTE_SELECTION_ID_PREFIX)
            and str(identity.get("eligibility_gate_id") or "").startswith("relig-")
            and str(identity.get("routing_intent_id") or "").startswith("rint-")
            and str(identity.get("plan_version_record_id") or "").startswith("pver-")
            and str(identity.get("planned_task_id") or "").startswith("ptask-")
            and int(identity.get("plan_version") or 0) >= 1
            and source.get("state") in TASK_ROUTE_SELECTION_ALLOWED_STATES
            and int(source.get("state_version") or 0) >= 1
            and all(_SHA256_RE.match(str(source.get(key) or "")) for key in (
                "source_version_sha256",
                "active_plan_sha256",
                "task_readiness_projection_sha256",
                "routing_intent_sha256",
                "eligibility_gate_sha256",
                "registry_sha256",
            ))
            and source.get("eligibility_gate_id") == identity.get("eligibility_gate_id")
            and source.get("routing_intent_id") == identity.get("routing_intent_id")
            and decision.get("selection_policy") == ROUTE_SELECTION_POLICY
            and int(decision.get("eligible_candidate_count") or 0) == len(ranked)
            and int(decision.get("ranked_candidate_count") or 0) == len(ranked)
            and all(item.get("eligibility_status") == CANDIDATE_ELIGIBLE for item in ranked)
            and all(item.get("runtime", {}).get("endpoint_resolved") is False for item in ranked)
            and all(item.get("runtime", {}).get("health_probed") is False for item in ranked)
            and ranks_ok
            and ordered_ok
            and selected_ok
            and source_gate_allows_selected
            and decision.get("runtime_availability_considered") is False
            and decision.get("governance_authorization_considered") is False
            and semantics.get("mode") == TASK_ROUTE_SELECTION_MODE
            and semantics.get("eligibility_source_is_stage343_only") is True
            and semantics.get("route_ranking_performed") is True
            and semantics.get("route_selection_decision_performed") is True
            and semantics.get("route_selected") == bool(decision.get("route_selected"))
            and semantics.get("selected_route_is_logical_only") is True
            and semantics.get("selection_is_authorization") is False
            and semantics.get("selection_is_runtime_availability") is False
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


def canonical_task_route_selection_definition() -> Dict[str, Any]:
    return {
        "schema_version": TASK_ROUTE_SELECTION_SCHEMA_VERSION,
        "mode": TASK_ROUTE_SELECTION_MODE,
        "route_decision_id_prefix": TASK_ROUTE_SELECTION_ID_PREFIX,
        "allowed_source_states": sorted(TASK_ROUTE_SELECTION_ALLOWED_STATES),
        "selection_policy": ROUTE_SELECTION_POLICY,
        "requires_active_plan_version": True,
        "requires_active_task_readiness_projection": True,
        "requires_ready_task": True,
        "requires_stage342_routing_intent": True,
        "requires_stage343_eligibility_gate": True,
        "eligible_candidate_source": "STAGE343_ELIGIBLE_CANDIDATES_ONLY",
        "route_ranking_performed": True,
        "route_selection_decision_performed": True,
        "selected_route_is_logical_only": True,
        "selection_is_authorization": False,
        "selection_is_runtime_availability": False,
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
