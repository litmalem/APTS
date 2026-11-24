from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence

from .delegation_authorization import AUTH_STATUS_AUTHORIZED, verify_delegation_authorization_contract
from .delegation_delivery import (
    ACKNOWLEDGEMENT_STATUS,
    DELIVERY_STATUS,
    OWNERSHIP_STATUS,
    verify_delivery_receipt_contract,
)
from .delegation_handoff import verify_delegation_contract, verify_handoff_envelope
from .errors import MissionValidationError
from .execution_dispatch import (
    EXECUTION_AUTHORIZATION_STATUS,
    EXECUTION_DISPATCH_STATUS,
    verify_execution_dispatch_contract,
)
from .scope_contract import verify_contract
from .governance_binding import verify_binding_contract
from .subsystem_registry import verify_capability_contract, verify_registry_snapshot, verify_subsystem_contract
from .task_readiness_projection import TASK_READY, verify_task_readiness_projection_contract
from .task_route_selection import ROUTE_DECISION_SELECTED, verify_task_route_selection_contract

DISPATCH_ELIGIBILITY_SCHEMA_VERSION = "apts-dispatch-eligibility-execution-preconditions-v1"
DISPATCH_ELIGIBILITY_HASH_DOMAIN = "MISSION_DISPATCH_ELIGIBILITY_EXECUTION_PRECONDITIONS_V1"
DISPATCH_ELIGIBILITY_REQUEST_HASH_DOMAIN = "MISSION_DISPATCH_ELIGIBILITY_EXECUTION_PRECONDITIONS_REQUEST_V1"
DISPATCH_ELIGIBILITY_ID_PREFIX = "xelig-"
DISPATCH_ELIGIBILITY_MODE = "FAIL_CLOSED_CANONICAL_DISPATCH_ELIGIBILITY_AND_EXECUTION_PRECONDITIONS"
DISPATCH_ELIGIBILITY_ALLOWED_STATES = frozenset({"RUNNING"})
DISPATCH_ELIGIBILITY_GATE_PASSED = "PASSED"
DISPATCH_ELIGIBILITY_STATUS = "ELIGIBLE_FOR_PRE_DISPATCH_GOVERNANCE_REVALIDATION"
DISPATCH_ELIGIBILITY_AUTHORITY = "GLOBAL_MISSION_ORCHESTRATOR_DISPATCH_ELIGIBILITY_GATE"
EXECUTION_PRECONDITION_STATUS = "SATISFIED_PENDING_PRE_DISPATCH_AUTHORIZATION"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_execution_dispatch_id",
    "expected_execution_dispatch_sha256",
    "expected_task_readiness_projection_id",
    "expected_task_readiness_projection_sha256",
    "created_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_dispatch_eligibility_id() -> str:
    return f"{DISPATCH_ELIGIBILITY_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_dispatch_eligibility_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("dispatch eligibility request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported dispatch eligibility field(s): "
            + ", ".join(unknown)
            + "; Stage 3.5.2 derives dispatch eligibility and execution preconditions from the immutable Stage-3.5.1 dispatch contract and current canonical Mission artifacts. "
              "Caller-supplied eligibility result, precondition result, Governance decision, execution grant, runtime endpoint, health result, resource assignment, execution payload, dispatch attempt, target action, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_execution_dispatch_id": _string(payload, "expected_execution_dispatch_id"),
        "expected_task_readiness_projection_id": _string(payload, "expected_task_readiness_projection_id"),
        "created_by": _string(payload, "created_by", 128),
    }
    for key in ("idempotency_key", "expected_active_plan_version_record_id", "expected_execution_dispatch_id", "expected_task_readiness_projection_id"):
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_execution_dispatch_id"].startswith("xdispatch-"):
        raise MissionValidationError("expected_execution_dispatch_id must be a canonical xdispatch-* identifier")
    if not values["expected_task_readiness_projection_id"].startswith("rproj-"):
        raise MissionValidationError("expected_task_readiness_projection_id must be a canonical rproj-* identifier")

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
        "expected_execution_dispatch_sha256": _sha(payload, "expected_execution_dispatch_sha256"),
        "expected_task_readiness_projection_sha256": _sha(payload, "expected_task_readiness_projection_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def dispatch_eligibility_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": DISPATCH_ELIGIBILITY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _registry_records(registry_snapshot: Mapping[str, Any], subsystem_id: str, capability_id: str):
    subsystem = next(
        (item for item in registry_snapshot.get("subsystems", []) if item.get("identity", {}).get("subsystem_id") == subsystem_id),
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


def evaluate_dispatch_execution_preconditions(
    *,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    readiness_projection: Mapping[str, Any],
    execution_dispatch: Mapping[str, Any],
    delivery: Mapping[str, Any],
    delegation: Mapping[str, Any],
    route: Mapping[str, Any],
    delegation_authorization: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
    recovery_controls: Sequence[Mapping[str, Any]],
    registry_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate static/durable dispatch eligibility only.

    This function deliberately performs no external Governance query, endpoint resolution,
    health probe, resource assignment, network I/O, dispatch attempt, execution grant, or
    target actuation. Its positive result means only that the dispatch identity is eligible
    to proceed to the later authoritative pre-dispatch Governance revalidation stage.
    """

    dispatch_contract = execution_dispatch.get("execution_dispatch_contract") or {}
    dispatch_source = dispatch_contract.get("source_bindings") or {}
    dispatch_target = dispatch_contract.get("dispatch_target") or {}
    dispatch_authority = dispatch_contract.get("authority_context") or {}
    dispatch_state = dispatch_contract.get("dispatch") or {}

    readiness_contract = readiness_projection.get("projection_contract") or {}
    readiness_items = list(readiness_contract.get("projection", {}).get("task_readiness") or [])
    planned_task_id = execution_dispatch.get("planned_task_id")
    readiness_item = next((item for item in readiness_items if item.get("planned_task_id") == planned_task_id), None)

    delivery_contract = delivery.get("delivery_receipt_contract") or delivery.get("delivery_receipt") or {}
    delegation_contract = delegation.get("delegation_contract") or {}
    handoff = delegation_contract.get("handoff_envelope") or {}
    route_contract = route.get("route_selection_contract") or {}
    route_decision = route_contract.get("route_decision") or {}
    selected_route = route_decision.get("selected_route") or {}
    auth_contract = delegation_authorization.get("delegation_authorization_contract") or {}

    latest_recovery: Optional[Mapping[str, Any]] = recovery_controls[-1] if recovery_controls else None
    subsystem, capability = _registry_records(
        registry_snapshot,
        str(dispatch_target.get("subsystem_id") or ""),
        str(dispatch_target.get("capability_id") or ""),
    )

    checks: Dict[str, bool] = {
        "mission_state_running": state.get("state") in DISPATCH_ELIGIBILITY_ALLOWED_STATES,
        "mission_version_vector_complete": version_vector.get("version_vector_complete") is True,
        "active_plan_matches_stage351_dispatch": (
            execution_dispatch.get("plan_version_record_id") == active_plan.get("plan_version_record_id")
            and int(execution_dispatch.get("plan_version") or 0) == int(active_plan.get("plan_version") or -1)
            and dispatch_source.get("active_plan_sha256") == active_plan.get("canonical_sha256")
        ),
        "stage351_dispatch_contract_integrity_valid": verify_execution_dispatch_contract(dispatch_contract),
        "stage351_dispatch_materialized_pending_authorization": (
            dispatch_state.get("status") == EXECUTION_DISPATCH_STATUS
            and dispatch_state.get("dispatch_contract_materialized") is True
            and dispatch_state.get("dispatch_identity_allocated") is True
        ),
        "execution_authorization_not_evaluated": (
            dispatch_authority.get("execution_authorization_status") == EXECUTION_AUTHORIZATION_STATUS
            and dispatch_authority.get("execution_authorized") is False
            and dispatch_authority.get("target_action_authorized") is False
        ),
        "no_dispatch_attempt_or_target_actuation": (
            dispatch_state.get("dispatch_attempt_started") is False
            and dispatch_state.get("dispatch_performed") is False
            and dispatch_state.get("external_network_io_performed") is False
            and dispatch_state.get("target_action_dispatch_enabled") is False
            and dispatch_state.get("target_actuation") is False
        ),
        "active_readiness_projection_integrity_valid": verify_task_readiness_projection_contract(readiness_contract),
        "planned_task_structurally_ready": (
            readiness_item is not None
            and readiness_item.get("readiness_status") == TASK_READY
            and readiness_item.get("structurally_ready") is True
            and not list(readiness_item.get("unmet_dependency_task_keys") or [])
        ),
        "delivery_receipt_integrity_valid": verify_delivery_receipt_contract(delivery_contract),
        "delivery_acknowledgement_ownership_accepted": (
            delivery_contract.get("delivery", {}).get("delivery_status") == DELIVERY_STATUS
            and delivery_contract.get("delivery", {}).get("handoff_transmitted") is True
            and delivery_contract.get("acknowledgement", {}).get("acknowledgement_status") == ACKNOWLEDGEMENT_STATUS
            and delivery_contract.get("acknowledgement", {}).get("handoff_acknowledged") is True
            and delivery_contract.get("ownership", {}).get("ownership_status") == OWNERSHIP_STATUS
            and delivery_contract.get("ownership", {}).get("ownership_accepted") is True
        ),
        "delivery_receipt_matches_stage351_dispatch": (
            delivery.get("delivery_receipt_id") == execution_dispatch.get("delivery_receipt_id")
            and delivery.get("canonical_sha256") == dispatch_source.get("delivery_receipt_sha256")
        ),
        "delegation_and_handoff_integrity_valid": (
            verify_delegation_contract(delegation_contract)
            and verify_handoff_envelope(handoff)
        ),
        "delegation_matches_stage351_dispatch": (
            delegation.get("delegation_id") == execution_dispatch.get("delegation_id")
            and delegation.get("canonical_sha256") == dispatch_source.get("delegation_sha256")
            and delegation.get("handoff_envelope_id") == execution_dispatch.get("handoff_envelope_id")
            and delegation.get("handoff_envelope_sha256") == dispatch_source.get("handoff_envelope_sha256")
        ),
        "route_decision_integrity_and_selection_valid": (
            verify_task_route_selection_contract(route_contract)
            and route.get("decision_status") == ROUTE_DECISION_SELECTED
            and route.get("route_selected") is True
        ),
        "route_matches_stage351_target": (
            route.get("route_decision_id") == execution_dispatch.get("route_decision_id")
            and route.get("canonical_sha256") == dispatch_source.get("route_decision_sha256")
            and selected_route.get("subsystem_id") == dispatch_target.get("subsystem_id")
            and selected_route.get("capability_id") == dispatch_target.get("capability_id")
            and int(selected_route.get("capability_version") or 0) == int(dispatch_target.get("capability_version") or -1)
        ),
        "delegation_authorization_integrity_valid": verify_delegation_authorization_contract(auth_contract),
        "delegation_authorization_remains_delegation_only": (
            delegation_authorization.get("delegation_authorization_id") == execution_dispatch.get("delegation_authorization_id")
            and delegation_authorization.get("canonical_sha256") == dispatch_source.get("delegation_authorization_sha256")
            and delegation_authorization.get("authorization_status") == AUTH_STATUS_AUTHORIZED
            and delegation_authorization.get("authorization_granted") is True
            and auth_contract.get("semantics", {}).get("authorization_is_delegation") is False
            and auth_contract.get("semantics", {}).get("execution_authorized") is False
        ),
        "mission_scope_binding_current": (
            verify_contract(scope_record.get("contract") or {})
            and scope_record.get("snapshot_id") == dispatch_source.get("mission_scope_snapshot_id")
            and scope_record.get("canonical_sha256") == dispatch_source.get("mission_scope_sha256")
        ),
        "governance_binding_current": (
            verify_binding_contract(governance_binding.get("binding") or {})
            and int(governance_binding.get("binding_version") or 0) == int(dispatch_source.get("governance_binding_version") or -1)
            and governance_binding.get("canonical_sha256") == dispatch_source.get("governance_binding_sha256")
        ),
        "recovery_control_set_unchanged_since_stage351": (
            len(recovery_controls) == int(dispatch_source.get("recovery_control_count") or 0)
            and (
                latest_recovery is None
                or (
                    latest_recovery.get("recovery_control_id") == dispatch_source.get("latest_recovery_control_id")
                    and latest_recovery.get("canonical_sha256") == dispatch_source.get("latest_recovery_control_sha256")
                )
            )
        ),
        "canonical_subsystem_registry_integrity_valid": verify_registry_snapshot(registry_snapshot),
        "target_subsystem_registered_enabled": (
            subsystem is not None
            and verify_subsystem_contract(subsystem)
            and subsystem.get("registration", {}).get("status") == "REGISTERED"
            and subsystem.get("registration", {}).get("enabled") is True
        ),
        "target_capability_registered_enabled": (
            capability is not None
            and verify_capability_contract(capability)
            and capability.get("registration", {}).get("status") == "REGISTERED"
            and capability.get("registration", {}).get("enabled") is True
            and capability.get("semantics", {}).get("delegation_eligible") is True
            and int(capability.get("identity", {}).get("capability_version") or 0) == int(dispatch_target.get("capability_version") or -1)
        ),
        "runtime_endpoint_resolution_still_deferred": (
            dispatch_target.get("logical_target_only") is True
            and dispatch_target.get("runtime_endpoint") is None
            and dispatch_target.get("runtime_endpoint_resolution_performed") is False
            and dispatch_target.get("runtime_health_probe_performed") is False
            and dispatch_target.get("resource_assignment_performed") is False
        ),
    }

    failed = [name for name, ok in checks.items() if not ok]
    return {
        "gate_result": DISPATCH_ELIGIBILITY_GATE_PASSED if not failed else "FAILED_CLOSED",
        "eligibility_status": DISPATCH_ELIGIBILITY_STATUS if not failed else "NOT_ELIGIBLE",
        "execution_precondition_status": EXECUTION_PRECONDITION_STATUS if not failed else "UNSATISFIED",
        "precondition_count": len(checks),
        "satisfied_precondition_count": len(checks) - len(failed),
        "failed_precondition_count": len(failed),
        "checks": checks,
        "failed_preconditions": failed,
        "eligible_for_pre_dispatch_governance_revalidation": not failed,
        "eligible_for_execution": False,
    }


def build_dispatch_eligibility_contract(
    *,
    dispatch_eligibility_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    state: Mapping[str, Any],
    version_vector: Mapping[str, Any],
    active_plan: Mapping[str, Any],
    readiness_projection: Mapping[str, Any],
    execution_dispatch: Mapping[str, Any],
    delivery: Mapping[str, Any],
    delegation: Mapping[str, Any],
    route: Mapping[str, Any],
    delegation_authorization: Mapping[str, Any],
    scope_record: Mapping[str, Any],
    governance_binding: Mapping[str, Any],
    recovery_controls: Sequence[Mapping[str, Any]],
    registry_snapshot: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    evaluation = evaluate_dispatch_execution_preconditions(
        state=state,
        version_vector=version_vector,
        active_plan=active_plan,
        readiness_projection=readiness_projection,
        execution_dispatch=execution_dispatch,
        delivery=delivery,
        delegation=delegation,
        route=route,
        delegation_authorization=delegation_authorization,
        scope_record=scope_record,
        governance_binding=governance_binding,
        recovery_controls=recovery_controls,
        registry_snapshot=registry_snapshot,
    )
    dispatch_contract = execution_dispatch["execution_dispatch_contract"]
    target = dispatch_contract["dispatch_target"]
    source = dispatch_contract["source_bindings"]
    latest_recovery: Optional[Mapping[str, Any]] = recovery_controls[-1] if recovery_controls else None

    core: Dict[str, Any] = {
        "schema_version": DISPATCH_ELIGIBILITY_SCHEMA_VERSION,
        "identity": {
            "dispatch_eligibility_id": dispatch_eligibility_id,
            "mission_id": mission_id,
            "execution_dispatch_id": execution_dispatch["execution_dispatch_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": execution_dispatch["planned_task_id"],
            "task_key": execution_dispatch["task_key"],
            "created_by": request["created_by"],
            "created_at": created_at,
        },
        "source_bindings": {
            "source_state": state["state"],
            "source_state_version": int(state["state_version"]),
            "source_version_sha256": version_vector["version_sha256"],
            "active_plan_sha256": active_plan["canonical_sha256"],
            "task_readiness_projection_id": readiness_projection["projection_id"],
            "task_readiness_projection_sha256": readiness_projection["canonical_sha256"],
            "execution_dispatch_sha256": execution_dispatch["canonical_sha256"],
            "delivery_receipt_id": execution_dispatch["delivery_receipt_id"],
            "delivery_receipt_sha256": delivery["canonical_sha256"],
            "delegation_id": execution_dispatch["delegation_id"],
            "delegation_sha256": delegation["canonical_sha256"],
            "route_decision_id": execution_dispatch["route_decision_id"],
            "route_decision_sha256": route["canonical_sha256"],
            "delegation_authorization_id": execution_dispatch["delegation_authorization_id"],
            "delegation_authorization_sha256": delegation_authorization["canonical_sha256"],
            "mission_scope_snapshot_id": scope_record["snapshot_id"],
            "mission_scope_sha256": scope_record["canonical_sha256"],
            "governance_binding_version": int(governance_binding["binding_version"]),
            "governance_binding_sha256": governance_binding["canonical_sha256"],
            "registry_id": registry_snapshot["identity"]["registry_id"],
            "registry_version": int(registry_snapshot["identity"]["registry_version"]),
            "registry_sha256": registry_snapshot["integrity"]["canonical_sha256"],
            "recovery_control_count": len(recovery_controls),
            "latest_recovery_control_id": None if latest_recovery is None else latest_recovery.get("recovery_control_id"),
            "latest_recovery_control_sha256": None if latest_recovery is None else latest_recovery.get("canonical_sha256"),
            "stage351_recovery_control_count": int(source.get("recovery_control_count") or 0),
            "stage351_latest_recovery_control_id": source.get("latest_recovery_control_id"),
            "stage351_latest_recovery_control_sha256": source.get("latest_recovery_control_sha256"),
        },
        "dispatch_target": {
            "subsystem_id": target["subsystem_id"],
            "capability_id": target["capability_id"],
            "capability_version": int(target["capability_version"]),
            "logical_target_only": True,
            "runtime_endpoint": None,
            "runtime_availability": "UNKNOWN_NOT_PROBED",
        },
        "eligibility_gate": evaluation,
        "authority_context": {
            "dispatch_eligibility_authority": DISPATCH_ELIGIBILITY_AUTHORITY,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "pre_dispatch_governance_revalidation_required": True,
            "governance_query_performed": False,
            "execution_authorization_status": EXECUTION_AUTHORIZATION_STATUS,
            "execution_authorization_performed": False,
            "execution_authorized": False,
            "target_action_authorized": False,
        },
        "semantics": {
            "mode": DISPATCH_ELIGIBILITY_MODE,
            "eligibility_gate_performed": True,
            "execution_preconditions_evaluated": True,
            "static_canonical_preconditions_only": True,
            "eligibility_is_execution_authorization": False,
            "preconditions_are_execution_authorization": False,
            "eligible_for_execution": False,
            "eligible_for_pre_dispatch_governance_revalidation": evaluation["eligible_for_pre_dispatch_governance_revalidation"],
            "pre_dispatch_governance_revalidation_required": True,
            "governance_query_performed": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "execution_authorization_performed": False,
            "dispatch_attempt_started": False,
            "dispatch_performed": False,
            "external_network_io_performed": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "version_vector_extension_performed": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "created_at": created_at,
        },
    }
    return {
        "hash_domain": DISPATCH_ELIGIBILITY_HASH_DOMAIN,
        **core,
        "canonical_sha256": sha256_hex({"hash_domain": DISPATCH_ELIGIBILITY_HASH_DOMAIN, "core": core}),
    }


def verify_dispatch_eligibility_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != DISPATCH_ELIGIBILITY_SCHEMA_VERSION:
            return False
        if contract.get("hash_domain") != DISPATCH_ELIGIBILITY_HASH_DOMAIN:
            return False
        core = {k: v for k, v in contract.items() if k not in {"hash_domain", "canonical_sha256"}}
        if contract.get("canonical_sha256") != sha256_hex({"hash_domain": DISPATCH_ELIGIBILITY_HASH_DOMAIN, "core": core}):
            return False
        ident = contract["identity"]
        src = contract["source_bindings"]
        target = contract["dispatch_target"]
        gate = contract["eligibility_gate"]
        authority = contract["authority_context"]
        semantics = contract["semantics"]
        if not str(ident.get("dispatch_eligibility_id") or "").startswith(DISPATCH_ELIGIBILITY_ID_PREFIX):
            return False
        if not str(ident.get("execution_dispatch_id") or "").startswith("xdispatch-"):
            return False
        if not str(ident.get("plan_version_record_id") or "").startswith("pver-"):
            return False
        if not str(ident.get("planned_task_id") or "").startswith("ptask-"):
            return False
        if src.get("source_state") not in DISPATCH_ELIGIBILITY_ALLOWED_STATES:
            return False
        sha_fields = (
            "source_version_sha256",
            "active_plan_sha256",
            "task_readiness_projection_sha256",
            "execution_dispatch_sha256",
            "delivery_receipt_sha256",
            "delegation_sha256",
            "route_decision_sha256",
            "delegation_authorization_sha256",
            "mission_scope_sha256",
            "governance_binding_sha256",
            "registry_sha256",
        )
        if any(not _SHA_RE.match(str(src.get(k) or "")) for k in sha_fields):
            return False
        for key in ("latest_recovery_control_sha256", "stage351_latest_recovery_control_sha256"):
            if src.get(key) not in (None, "") and not _SHA_RE.match(str(src[key])):
                return False
        if not target.get("subsystem_id") or not target.get("capability_id"):
            return False
        if target.get("logical_target_only") is not True or target.get("runtime_endpoint") is not None:
            return False
        if target.get("runtime_availability") != "UNKNOWN_NOT_PROBED":
            return False
        if gate.get("gate_result") != DISPATCH_ELIGIBILITY_GATE_PASSED:
            return False
        if gate.get("eligibility_status") != DISPATCH_ELIGIBILITY_STATUS:
            return False
        if gate.get("execution_precondition_status") != EXECUTION_PRECONDITION_STATUS:
            return False
        checks = gate.get("checks") or {}
        if not checks or not all(value is True for value in checks.values()):
            return False
        if int(gate.get("precondition_count") or 0) != len(checks):
            return False
        if int(gate.get("satisfied_precondition_count") or 0) != len(checks):
            return False
        if int(gate.get("failed_precondition_count", -1)) != 0 or list(gate.get("failed_preconditions") or []):
            return False
        if gate.get("eligible_for_pre_dispatch_governance_revalidation") is not True:
            return False
        if gate.get("eligible_for_execution") is not False:
            return False
        if authority.get("dispatch_eligibility_authority") != DISPATCH_ELIGIBILITY_AUTHORITY:
            return False
        if authority.get("governance_authorization_authority") != "EXTERNAL_APTS_GSS":
            return False
        if authority.get("pre_dispatch_governance_revalidation_required") is not True:
            return False
        if authority.get("governance_query_performed") is not False:
            return False
        if authority.get("execution_authorization_status") != EXECUTION_AUTHORIZATION_STATUS:
            return False
        if any(authority.get(k) is not False for k in ("execution_authorization_performed", "execution_authorized", "target_action_authorized")):
            return False
        if semantics.get("mode") != DISPATCH_ELIGIBILITY_MODE:
            return False
        required_true = (
            "eligibility_gate_performed",
            "execution_preconditions_evaluated",
            "static_canonical_preconditions_only",
            "eligible_for_pre_dispatch_governance_revalidation",
            "pre_dispatch_governance_revalidation_required",
        )
        if not all(semantics.get(k) is True for k in required_true):
            return False
        required_false = (
            "eligibility_is_execution_authorization",
            "preconditions_are_execution_authorization",
            "eligible_for_execution",
            "governance_query_performed",
            "runtime_endpoint_resolution_performed",
            "runtime_health_probe_performed",
            "resource_assignment_performed",
            "execution_authorization_performed",
            "dispatch_attempt_started",
            "dispatch_performed",
            "external_network_io_performed",
            "target_action_dispatch_enabled",
            "target_actuation",
            "version_vector_extension_performed",
        )
        if any(semantics.get(k) is not False for k in required_false):
            return False
        return True
    except Exception:
        return False


def canonical_dispatch_eligibility_definition() -> Dict[str, Any]:
    return {
        "schema_version": DISPATCH_ELIGIBILITY_SCHEMA_VERSION,
        "mode": DISPATCH_ELIGIBILITY_MODE,
        "dispatch_eligibility_id_prefix": DISPATCH_ELIGIBILITY_ID_PREFIX,
        "allowed_source_states": sorted(DISPATCH_ELIGIBILITY_ALLOWED_STATES),
        "gate_result": DISPATCH_ELIGIBILITY_GATE_PASSED,
        "eligibility_status": DISPATCH_ELIGIBILITY_STATUS,
        "execution_precondition_status": EXECUTION_PRECONDITION_STATUS,
        "dispatch_eligibility_authority": DISPATCH_ELIGIBILITY_AUTHORITY,
        "requires_stage351_execution_dispatch_contract": True,
        "requires_current_running_mission_state_and_version_vector": True,
        "requires_current_active_plan": True,
        "requires_current_task_readiness_projection": True,
        "requires_structurally_ready_planned_task": True,
        "requires_current_stage347_owned_handoff": True,
        "requires_current_route_delegation_provenance": True,
        "requires_current_scope_and_governance_binding": True,
        "requires_unchanged_recovery_control_set": True,
        "requires_current_canonical_target_capability": True,
        "eligibility_is_execution_authorization": False,
        "preconditions_are_execution_authorization": False,
        "eligible_for_execution": False,
        "eligible_for_pre_dispatch_governance_revalidation": True,
        "pre_dispatch_governance_revalidation_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "governance_query_performed": False,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "execution_authorization_performed": False,
        "dispatch_attempt_started": False,
        "dispatch_performed": False,
        "external_network_io_performed": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "version_vector_extension_performed": False,
    }
