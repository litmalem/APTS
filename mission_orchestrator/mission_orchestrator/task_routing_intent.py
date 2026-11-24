from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError
from .task_decomposition import PLANNED_TASK_SCHEMA_VERSION

TASK_ROUTING_INTENT_SCHEMA_VERSION = "apts-task-routing-intent-candidate-resolution-v1"
TASK_ROUTING_INTENT_HASH_DOMAIN = "MISSION_TASK_ROUTING_INTENT_CANDIDATE_RESOLUTION_V1"
TASK_ROUTING_INTENT_REQUEST_HASH_DOMAIN = "MISSION_TASK_ROUTING_INTENT_REQUEST_V1"
TASK_ROUTING_INTENT_ID_PREFIX = "rint-"
TASK_ROUTING_INTENT_MODE = "IMMUTABLE_READY_TASK_INTENT_WITH_EXACT_REGISTRY_CAPABILITY_CANDIDATE_RESOLUTION"
TASK_ROUTING_INTENT_ALLOWED_STATES = frozenset({"PLANNING", "REPLANNING"})
CANDIDATE_RESOLUTION_MODE = "EXACT_REQUIRED_CAPABILITY_AND_REQUIRED_SUBSYSTEM"
RESOLUTION_CANDIDATES_FOUND = "CANDIDATES_RESOLVED"
RESOLUTION_NO_CANDIDATE = "NO_REGISTERED_CANDIDATE"
TASK_READY = "READY"

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_task_readiness_projection_id",
    "expected_task_readiness_projection_sha256",
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


def new_task_routing_intent_id() -> str:
    return f"{TASK_ROUTING_INTENT_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_task_routing_intent_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("task routing intent request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported task routing intent field(s): " + ", ".join(unknown)
            + "; Stage 3.4.2 derives required subsystem/capability and candidate subsystems from the active canonical Plan, active READY projection, and canonical registry. Caller-supplied eligibility, ranking, selected route, endpoint, health, resource assignment, authorization, delegation, dispatch, execution, or target-action fields are forbidden"
        )
    idem = _require_string(payload, "idempotency_key", 128)
    task_id = _require_string(payload, "planned_task_id", 160)
    plan_record_id = _require_string(payload, "expected_active_plan_version_record_id", 160)
    readiness_id = _require_string(payload, "expected_task_readiness_projection_id", 160)
    for key, value in (("idempotency_key", idem), ("planned_task_id", task_id), ("expected_active_plan_version_record_id", plan_record_id), ("expected_task_readiness_projection_id", readiness_id)):
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
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
        "idempotency_key": idem,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version_record_id": plan_record_id,
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_task_readiness_projection_id": readiness_id,
        "expected_task_readiness_projection_sha256": _sha(payload, "expected_task_readiness_projection_sha256"),
        "planned_task_id": task_id,
        "created_by": _require_string(payload, "created_by", 128),
        "reason": reason,
        "metadata": dict(metadata),
    }


def task_routing_intent_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": TASK_ROUTING_INTENT_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def resolve_candidate_subsystems(planned_task: Mapping[str, Any], registry_snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    required_subsystem = str(planned_task.get("required_subsystem") or "")
    required_capability = str(planned_task.get("required_capability") or "")
    task_schema = str(planned_task.get("schema_version") or PLANNED_TASK_SCHEMA_VERSION)

    subsystem_by_id = {
        item["identity"]["subsystem_id"]: item
        for item in registry_snapshot.get("subsystems", [])
    }
    capability_matches = [
        item for item in registry_snapshot.get("capabilities", [])
        if item.get("identity", {}).get("capability_id") == required_capability
    ]
    candidates = []
    exclusions = []
    for capability in capability_matches:
        identity = capability["identity"]
        subsystem_id = identity["subsystem_id"]
        subsystem = subsystem_by_id.get(subsystem_id)
        reasons = []
        if subsystem_id != required_subsystem:
            reasons.append("REQUIRED_SUBSYSTEM_MISMATCH")
        if subsystem is None:
            reasons.append("SUBSYSTEM_NOT_REGISTERED")
        else:
            if subsystem.get("registration", {}).get("status") != "REGISTERED" or subsystem.get("registration", {}).get("enabled") is not True:
                reasons.append("SUBSYSTEM_NOT_ENABLED")
            if task_schema not in subsystem.get("contract", {}).get("accepted_task_schema_versions", []):
                reasons.append("SUBSYSTEM_TASK_SCHEMA_INCOMPATIBLE")
        if capability.get("registration", {}).get("status") != "REGISTERED" or capability.get("registration", {}).get("enabled") is not True:
            reasons.append("CAPABILITY_NOT_ENABLED")
        compatibility = capability.get("compatibility", {})
        if compatibility.get("required_capability_match") != "EXACT_CAPABILITY_ID":
            reasons.append("CAPABILITY_MATCH_MODE_NOT_EXACT")
        if compatibility.get("required_subsystem") != required_subsystem:
            reasons.append("CAPABILITY_REQUIRED_SUBSYSTEM_MISMATCH")
        if task_schema not in compatibility.get("accepted_task_schema_versions", []):
            reasons.append("CAPABILITY_TASK_SCHEMA_INCOMPATIBLE")

        if reasons:
            exclusions.append({
                "subsystem_id": subsystem_id,
                "capability_id": identity["capability_id"],
                "reasons": sorted(set(reasons)),
            })
            continue

        candidates.append({
            "subsystem_id": subsystem_id,
            "subsystem_type": subsystem["classification"]["subsystem_type"],
            "capability_id": identity["capability_id"],
            "capability_version": int(identity["capability_version"]),
            "capability_kind": capability["classification"]["capability_kind"],
            "side_effect_class": capability["classification"]["side_effect_class"],
            "subsystem_contract_sha256": subsystem["integrity"]["canonical_sha256"],
            "capability_contract_sha256": capability["integrity"]["canonical_sha256"],
            "match": {
                "task_schema_version": task_schema,
                "required_subsystem_match": True,
                "required_capability_exact_match": True,
                "schema_compatible": True,
                "registered": True,
            },
            "runtime": {
                "endpoint_resolved": False,
                "health_probed": False,
                "availability": "UNKNOWN_NOT_PROBED",
            },
        })

    candidates.sort(key=lambda x: (x["subsystem_id"], x["capability_id"], int(x["capability_version"])))
    for index, candidate in enumerate(candidates, 1):
        candidate["candidate_index"] = index
    exclusions.sort(key=lambda x: (x["subsystem_id"], x["capability_id"]))
    return {
        "mode": CANDIDATE_RESOLUTION_MODE,
        "resolution_status": RESOLUTION_CANDIDATES_FOUND if candidates else RESOLUTION_NO_CANDIDATE,
        "capability_match_count_before_subsystem_filter": len(capability_matches),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "excluded_matches": exclusions,
    }


def build_task_routing_intent_contract(
    *, routing_intent_id: str, mission_id: str, request_sha256: str,
    source_state: Mapping[str, Any], source_version_sha256: str,
    active_plan: Mapping[str, Any], readiness_projection: Mapping[str, Any],
    planned_task: Mapping[str, Any], readiness_item: Mapping[str, Any],
    registry_snapshot: Mapping[str, Any], created_by: str,
    reason: Optional[str], metadata: Mapping[str, Any], created_at: str,
) -> Dict[str, Any]:
    resolution = resolve_candidate_subsystems(planned_task, registry_snapshot)
    candidate_plan = active_plan["plan_version_contract"]["candidate_plan"]
    core = {
        "schema_version": TASK_ROUTING_INTENT_SCHEMA_VERSION,
        "identity": {
            "routing_intent_id": routing_intent_id,
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": planned_task["planned_task_id"],
            "task_key": planned_task["task_key"],
            "created_by": created_by,
            "created_at": created_at,
        },
        "source_bindings": {
            "state": source_state["state"],
            "state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "candidate_plan_sha256": active_plan["candidate_plan_sha256"],
            "task_readiness_projection_id": readiness_projection["projection_id"],
            "task_readiness_projection_sha256": readiness_projection["canonical_sha256"],
            "registry_id": registry_snapshot["identity"]["registry_id"],
            "registry_version": int(registry_snapshot["identity"]["registry_version"]),
            "registry_sha256": registry_snapshot["integrity"]["canonical_sha256"],
        },
        "routing_intent": {
            "task_schema_version": planned_task.get("schema_version", PLANNED_TASK_SCHEMA_VERSION),
            "task_type": planned_task["task_type"],
            "required_subsystem": planned_task["required_subsystem"],
            "required_capability": planned_task["required_capability"],
            "readiness_status": readiness_item["readiness_status"],
            **resolution,
        },
        "semantics": {
            "mode": TASK_ROUTING_INTENT_MODE,
            "routing_intent_created": True,
            "candidate_resolution_performed": True,
            "candidate_resolution_local_registry_only": True,
            "candidate_is_eligibility_decision": False,
            "eligibility_gate_performed": False,
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
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
            "active_plan_task_count": len(candidate_plan.get("plan_steps") or []),
        },
    }
    digest = sha256_hex({"hash_domain": TASK_ROUTING_INTENT_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": TASK_ROUTING_INTENT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_task_routing_intent_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        intent = contract["routing_intent"]
        semantics = contract["semantics"]
        candidates = list(intent["candidates"])
        ordered = sorted(candidates, key=lambda x: (x["subsystem_id"], x["capability_id"], int(x["capability_version"])))
        candidate_ok = candidates == ordered
        for index, candidate in enumerate(candidates, 1):
            candidate_ok = candidate_ok and int(candidate["candidate_index"]) == index
            candidate_ok = candidate_ok and candidate["subsystem_id"] == intent["required_subsystem"]
            candidate_ok = candidate_ok and candidate["capability_id"] == intent["required_capability"]
            candidate_ok = candidate_ok and candidate["match"]["required_subsystem_match"] is True
            candidate_ok = candidate_ok and candidate["match"]["required_capability_exact_match"] is True
            candidate_ok = candidate_ok and candidate["runtime"]["endpoint_resolved"] is False
            candidate_ok = candidate_ok and candidate["runtime"]["health_probed"] is False
        expected_status = RESOLUTION_CANDIDATES_FOUND if candidates else RESOLUTION_NO_CANDIDATE
        return (
            contract.get("schema_version") == TASK_ROUTING_INTENT_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == TASK_ROUTING_INTENT_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256") == sha256_hex({"hash_domain": TASK_ROUTING_INTENT_HASH_DOMAIN, "core": core})
            and str(identity.get("routing_intent_id") or "").startswith(TASK_ROUTING_INTENT_ID_PREFIX)
            and str(identity.get("plan_version_record_id") or "").startswith("pver-")
            and int(identity.get("plan_version")) >= 1
            and str(identity.get("planned_task_id") or "").startswith("ptask-")
            and source.get("state") in TASK_ROUTING_INTENT_ALLOWED_STATES
            and int(source.get("state_version")) >= 1
            and all(_SHA256_RE.match(str(source.get(k) or "")) for k in (
                "source_version_sha256", "active_plan_sha256", "candidate_plan_sha256",
                "task_readiness_projection_sha256", "registry_sha256",
            ))
            and intent.get("task_schema_version") == PLANNED_TASK_SCHEMA_VERSION
            and intent.get("readiness_status") == TASK_READY
            and intent.get("mode") == CANDIDATE_RESOLUTION_MODE
            and intent.get("resolution_status") == expected_status
            and int(intent.get("candidate_count")) == len(candidates)
            and candidate_ok
            and semantics.get("mode") == TASK_ROUTING_INTENT_MODE
            and semantics.get("routing_intent_created") is True
            and semantics.get("candidate_resolution_performed") is True
            and semantics.get("candidate_resolution_local_registry_only") is True
            and semantics.get("candidate_is_eligibility_decision") is False
            and semantics.get("eligibility_gate_performed") is False
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
            and semantics.get("governance_authorization_authority") == "EXTERNAL_APTS_GSS"
        )
    except Exception:
        return False


def canonical_task_routing_intent_definition() -> Dict[str, Any]:
    return {
        "schema_version": TASK_ROUTING_INTENT_SCHEMA_VERSION,
        "mode": TASK_ROUTING_INTENT_MODE,
        "routing_intent_id_prefix": TASK_ROUTING_INTENT_ID_PREFIX,
        "allowed_source_states": sorted(TASK_ROUTING_INTENT_ALLOWED_STATES),
        "requires_active_plan_version": True,
        "requires_active_task_readiness_projection": True,
        "requires_ready_task": True,
        "candidate_resolution_mode": CANDIDATE_RESOLUTION_MODE,
        "candidate_resolution_source": "CANONICAL_SUBSYSTEM_REGISTRY_ONLY",
        "candidate_is_eligibility_decision": False,
        "eligibility_gate_performed": False,
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
