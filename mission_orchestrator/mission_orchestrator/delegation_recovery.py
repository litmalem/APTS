from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .delegation_delivery import verify_delivery_receipt_contract
from .delegation_handoff import verify_delegation_contract
from .errors import MissionValidationError
from .task_route_selection import verify_task_route_selection_contract

RECOVERY_CONTROL_SCHEMA_VERSION = "apts-canonical-delegation-retry-fallback-reassignment-conflict-control-v1"
RECOVERY_CONTROL_HASH_DOMAIN = "MISSION_CANONICAL_DELEGATION_RETRY_FALLBACK_REASSIGNMENT_CONFLICT_CONTROL_V1"
RECOVERY_REQUEST_HASH_DOMAIN = "MISSION_CANONICAL_DELEGATION_RECOVERY_CONTROL_REQUEST_V1"
RECOVERY_CONTROL_ID_PREFIX = "dctrl-"
RECOVERY_CONTROL_MODE = "CONTROL_PLANE_RETRY_FALLBACK_REASSIGNMENT_CONFLICT_CONTROL_NO_DISPATCH"
RECOVERY_ALLOWED_STATES = frozenset({"PLANNING", "REPLANNING"})

ACTION_RETRY_CURRENT_OWNER = "RETRY_CURRENT_OWNER"
ACTION_FALLBACK_NEXT_ELIGIBLE = "FALLBACK_NEXT_ELIGIBLE"
ACTION_REASSIGN_NEXT_ELIGIBLE = "REASSIGN_NEXT_ELIGIBLE"
ACTION_FREEZE_OWNERSHIP_CONFLICT = "FREEZE_OWNERSHIP_CONFLICT"
RECOVERY_ACTIONS = frozenset(
    {
        ACTION_RETRY_CURRENT_OWNER,
        ACTION_FALLBACK_NEXT_ELIGIBLE,
        ACTION_REASSIGN_NEXT_ELIGIBLE,
        ACTION_FREEZE_OWNERSHIP_CONFLICT,
    }
)

OUTCOME_RETRY_ADMITTED = "RETRY_ADMITTED_CURRENT_OWNER"
OUTCOME_RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED_FAIL_CLOSED"
OUTCOME_FALLBACK_PROPOSED = "FALLBACK_PROPOSED_RESELECTION_REAUTHORIZATION_REQUIRED"
OUTCOME_REASSIGNMENT_PROPOSED = "REASSIGNMENT_PROPOSED_RESELECTION_REAUTHORIZATION_REQUIRED"
OUTCOME_NO_ALTERNATE = "NO_ALTERNATE_ELIGIBLE_CANDIDATE_FAIL_CLOSED"
OUTCOME_CONFLICT_FROZEN = "OWNERSHIP_CONFLICT_FROZEN_FAIL_CLOSED"

CONFLICT_STATUS_CLEAR = "NO_CONFLICT_DETECTED"
CONFLICT_STATUS_FROZEN = "CONFLICT_FROZEN_FAIL_CLOSED"
MAX_RETRY_ATTEMPTS = 3

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_route_decision_id",
    "expected_route_decision_sha256",
    "expected_delegation_id",
    "expected_delegation_sha256",
    "expected_delivery_receipt_id",
    "expected_delivery_receipt_sha256",
    "expected_control_count",
    "control_action",
    "requested_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_recovery_control_id() -> str:
    return f"{RECOVERY_CONTROL_ID_PREFIX}{uuid.uuid4()}"


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


def _non_negative_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise MissionValidationError(f"{key} must be an integer")
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise MissionValidationError(f"{key} is required and must be an integer") from exc
    if value < 0:
        raise MissionValidationError(f"{key} must be >= 0")
    return value


def _sha(payload: Mapping[str, Any], key: str) -> str:
    value = _string(payload, key, 64).lower()
    if not _SHA_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_recovery_control_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("delegation recovery-control request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported delegation recovery-control field(s): "
            + ", ".join(unknown)
            + "; Stage 3.4.8 derives retry ordinal, fallback/reassignment candidate, ownership/conflict state, and all routing provenance from immutable Stage-3.4.4 through Stage-3.4.7 artifacts. "
              "Caller-supplied candidate/recipient override, runtime endpoint, health result, worker/resource assignment, Governance decision, dispatch instruction, execution authorization, command payload, or target-action fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_route_decision_id": _string(payload, "expected_route_decision_id"),
        "expected_delegation_id": _string(payload, "expected_delegation_id"),
        "expected_delivery_receipt_id": _string(payload, "expected_delivery_receipt_id"),
        "requested_by": _string(payload, "requested_by", 128),
    }
    for key in (
        "idempotency_key",
        "expected_active_plan_version_record_id",
        "expected_route_decision_id",
        "expected_delegation_id",
        "expected_delivery_receipt_id",
    ):
        if not _ID_RE.match(values[key]):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_route_decision_id"].startswith("rdec-"):
        raise MissionValidationError("expected_route_decision_id must be a canonical rdec-* identifier")
    if not values["expected_delegation_id"].startswith("deleg-"):
        raise MissionValidationError("expected_delegation_id must be a canonical deleg-* identifier")
    if not values["expected_delivery_receipt_id"].startswith("drecv-"):
        raise MissionValidationError("expected_delivery_receipt_id must be a canonical drecv-* identifier")

    action = _string(payload, "control_action", 64).upper()
    if action not in RECOVERY_ACTIONS:
        raise MissionValidationError(
            "control_action must be one of: " + ", ".join(sorted(RECOVERY_ACTIONS))
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
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_route_decision_sha256": _sha(payload, "expected_route_decision_sha256"),
        "expected_delegation_sha256": _sha(payload, "expected_delegation_sha256"),
        "expected_delivery_receipt_sha256": _sha(payload, "expected_delivery_receipt_sha256"),
        "expected_control_count": _non_negative_int(payload, "expected_control_count"),
        "control_action": action,
        "reason": reason,
        "metadata": dict(metadata),
    }


def recovery_control_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": RECOVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def _candidate_identity(candidate: Mapping[str, Any]) -> tuple[str, str, int]:
    return (
        str(candidate.get("subsystem_id") or ""),
        str(candidate.get("capability_id") or ""),
        int(candidate.get("capability_version") or 0),
    )


def select_next_eligible_candidate(
    route_decision_contract: Mapping[str, Any],
    *,
    current_subsystem: str,
    current_capability: str,
    current_capability_version: int,
) -> Optional[Dict[str, Any]]:
    """Return the next immutable Stage-3.4.4 ranked candidate after the current owner.

    This function never expands/re-resolves the candidate set and never consults runtime
    availability.  It only reads the immutable ranked Stage-3.4.4 decision.
    """
    if not verify_task_route_selection_contract(route_decision_contract):
        raise MissionValidationError("Stage-3.4.4 route-selection contract failed integrity verification")
    ranked = list(route_decision_contract["route_decision"].get("ranked_candidates") or [])
    current = (str(current_subsystem), str(current_capability), int(current_capability_version))
    current_rank: Optional[int] = None
    for item in ranked:
        if _candidate_identity(item) == current:
            current_rank = int(item.get("rank") or 0)
            break
    if current_rank is None:
        # Stage-3.4.7 owner must originate from the selected Stage-3.4.4 route.
        return None
    for item in sorted(ranked, key=lambda x: int(x.get("rank") or 0)):
        if int(item.get("rank") or 0) <= current_rank:
            continue
        if _candidate_identity(item) == current:
            continue
        return {
            "rank": int(item["rank"]),
            "candidate_index": int(item["candidate_index"]),
            "subsystem_id": item["subsystem_id"],
            "capability_id": item["capability_id"],
            "capability_version": int(item["capability_version"]),
            "side_effect_class": item.get("side_effect_class"),
            "source": "IMMUTABLE_STAGE344_RANKED_ELIGIBLE_CANDIDATES",
            "runtime_endpoint_resolved": False,
            "runtime_health_probed": False,
        }
    return None


def derive_recovery_decision(
    *,
    action: str,
    prior_controls: list[Mapping[str, Any]],
    route_decision_contract: Mapping[str, Any],
    current_owner: Mapping[str, Any],
) -> Dict[str, Any]:
    retry_count = sum(
        1
        for item in prior_controls
        if item.get("control_action") == ACTION_RETRY_CURRENT_OWNER
        and item.get("control_outcome") == OUTCOME_RETRY_ADMITTED
    )
    current = {
        "subsystem_id": str(current_owner["subsystem_id"]),
        "capability_id": str(current_owner["capability_id"]),
        "capability_version": int(current_owner["capability_version"]),
    }
    base = {
        "requested_action": action,
        "current_owner": current,
        "retry_budget": MAX_RETRY_ATTEMPTS,
        "retry_count_before": retry_count,
        "retry_ordinal": None,
        "retry_admitted": False,
        "fallback_candidate": None,
        "reassignment_candidate": None,
        "ownership_transition_pending": False,
        "ownership_transfer_performed": False,
        "conflict_status": CONFLICT_STATUS_CLEAR,
        "conflict_frozen": False,
        "route_reselection_required": False,
        "fresh_governance_authorization_required": False,
        "new_delegation_handoff_required": False,
    }

    if action == ACTION_RETRY_CURRENT_OWNER:
        ordinal = retry_count + 1
        if ordinal <= MAX_RETRY_ATTEMPTS:
            return {
                **base,
                "control_outcome": OUTCOME_RETRY_ADMITTED,
                "retry_ordinal": ordinal,
                "retry_admitted": True,
            }
        return {
            **base,
            "control_outcome": OUTCOME_RETRY_BUDGET_EXHAUSTED,
            "retry_ordinal": ordinal,
        }

    if action in {ACTION_FALLBACK_NEXT_ELIGIBLE, ACTION_REASSIGN_NEXT_ELIGIBLE}:
        candidate = select_next_eligible_candidate(
            route_decision_contract,
            current_subsystem=current["subsystem_id"],
            current_capability=current["capability_id"],
            current_capability_version=current["capability_version"],
        )
        if candidate is None:
            return {**base, "control_outcome": OUTCOME_NO_ALTERNATE}
        key = "fallback_candidate" if action == ACTION_FALLBACK_NEXT_ELIGIBLE else "reassignment_candidate"
        outcome = OUTCOME_FALLBACK_PROPOSED if action == ACTION_FALLBACK_NEXT_ELIGIBLE else OUTCOME_REASSIGNMENT_PROPOSED
        return {
            **base,
            "control_outcome": outcome,
            key: candidate,
            "ownership_transition_pending": True,
            "route_reselection_required": True,
            "fresh_governance_authorization_required": True,
            "new_delegation_handoff_required": True,
        }

    if action == ACTION_FREEZE_OWNERSHIP_CONFLICT:
        return {
            **base,
            "control_outcome": OUTCOME_CONFLICT_FROZEN,
            "conflict_status": CONFLICT_STATUS_FROZEN,
            "conflict_frozen": True,
        }

    raise MissionValidationError(f"unsupported Stage-3.4.8 recovery action {action!r}")


def build_recovery_control_contract(
    *,
    recovery_control_id: str,
    mission_id: str,
    control_sequence: int,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    route_decision: Mapping[str, Any],
    delegation: Mapping[str, Any],
    delivery: Mapping[str, Any],
    prior_controls: list[Mapping[str, Any]],
    created_at: str,
) -> Dict[str, Any]:
    delegation_contract = delegation["delegation_contract"]
    delivery_contract = delivery["delivery_receipt_contract"]
    route_contract = route_decision["route_selection_contract"]
    if not verify_delegation_contract(delegation_contract):
        raise MissionValidationError("Stage-3.4.6 delegation contract failed integrity verification")
    if not verify_delivery_receipt_contract(delivery_contract):
        raise MissionValidationError("Stage-3.4.7 delivery receipt failed integrity verification")
    if not verify_task_route_selection_contract(route_contract):
        raise MissionValidationError("Stage-3.4.4 route-selection contract failed integrity verification")

    recipient = delivery_contract["delivery"]
    current_owner = {
        "subsystem_id": recipient["recipient_subsystem_id"],
        "capability_id": recipient["recipient_capability_id"],
        "capability_version": int(recipient["recipient_capability_version"]),
    }
    decision = derive_recovery_decision(
        action=request["control_action"],
        prior_controls=prior_controls,
        route_decision_contract=route_contract,
        current_owner=current_owner,
    )
    previous = prior_controls[-1] if prior_controls else None

    core = {
        "schema_version": RECOVERY_CONTROL_SCHEMA_VERSION,
        "identity": {
            "recovery_control_id": recovery_control_id,
            "mission_id": mission_id,
            "control_sequence": int(control_sequence),
            "delivery_receipt_id": delivery["delivery_receipt_id"],
            "delegation_id": delegation["delegation_id"],
            "route_decision_id": route_decision["route_decision_id"],
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
            "planned_task_id": delegation["planned_task_id"],
            "task_key": delegation["task_key"],
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "active_plan_sha256": active_plan["canonical_sha256"],
            "route_decision_sha256": route_decision["canonical_sha256"],
            "delegation_sha256": delegation["canonical_sha256"],
            "handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
            "delivery_receipt_sha256": delivery["canonical_sha256"],
            "previous_recovery_control_id": None if previous is None else previous["recovery_control_id"],
            "previous_recovery_control_sha256": None if previous is None else previous["canonical_sha256"],
        },
        "recovery_control": decision,
        "semantics": {
            "mode": RECOVERY_CONTROL_MODE,
            "control_plane_only": True,
            "consumes_stage347_ownership_receipt": True,
            "preserves_stage346_and_stage347_immutability": True,
            "retry_is_dispatch": False,
            "fallback_is_dispatch": False,
            "reassignment_is_ownership_transfer": False,
            "conflict_freeze_is_terminal_execution_authority": False,
            "runtime_endpoint_resolution_performed": False,
            "runtime_health_probe_performed": False,
            "resource_assignment_performed": False,
            "external_network_io_performed": False,
            "governance_query_performed": False,
            "authorization_reused_as_execution_grant": False,
            "dispatch_performed": False,
            "execution_authorized": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
            "pre_dispatch_governance_revalidation_required": True,
            "version_vector_extension_performed": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "requested_by": request["requested_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "created_at": created_at,
        },
    }
    digest = sha256_hex({"hash_domain": RECOVERY_CONTROL_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": RECOVERY_CONTROL_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_recovery_control_contract(contract: Mapping[str, Any]) -> bool:
    try:
        core = {k: v for k, v in contract.items() if k != "integrity"}
        ident = contract["identity"]
        source = contract["source_bindings"]
        decision = contract["recovery_control"]
        sem = contract["semantics"]
        action = decision.get("requested_action")
        outcome = decision.get("control_outcome")
        action_outcome_ok = (
            (action == ACTION_RETRY_CURRENT_OWNER and outcome in {OUTCOME_RETRY_ADMITTED, OUTCOME_RETRY_BUDGET_EXHAUSTED})
            or (action == ACTION_FALLBACK_NEXT_ELIGIBLE and outcome in {OUTCOME_FALLBACK_PROPOSED, OUTCOME_NO_ALTERNATE})
            or (action == ACTION_REASSIGN_NEXT_ELIGIBLE and outcome in {OUTCOME_REASSIGNMENT_PROPOSED, OUTCOME_NO_ALTERNATE})
            or (action == ACTION_FREEZE_OWNERSHIP_CONFLICT and outcome == OUTCOME_CONFLICT_FROZEN)
        )
        candidate = decision.get("fallback_candidate") or decision.get("reassignment_candidate")
        candidate_ok = True
        if candidate is not None:
            candidate_ok = (
                int(candidate.get("rank") or 0) >= 1
                and int(candidate.get("candidate_index") or 0) >= 1
                and bool(candidate.get("subsystem_id"))
                and bool(candidate.get("capability_id"))
                and int(candidate.get("capability_version") or 0) >= 1
                and candidate.get("runtime_endpoint_resolved") is False
                and candidate.get("runtime_health_probed") is False
            )
        return (
            contract.get("schema_version") == RECOVERY_CONTROL_SCHEMA_VERSION
            and contract["integrity"].get("hash_domain") == RECOVERY_CONTROL_HASH_DOMAIN
            and contract["integrity"].get("canonical_sha256")
            == sha256_hex({"hash_domain": RECOVERY_CONTROL_HASH_DOMAIN, "core": core})
            and str(ident.get("recovery_control_id") or "").startswith(RECOVERY_CONTROL_ID_PREFIX)
            and str(ident.get("delivery_receipt_id") or "").startswith("drecv-")
            and str(ident.get("delegation_id") or "").startswith("deleg-")
            and str(ident.get("route_decision_id") or "").startswith("rdec-")
            and str(ident.get("plan_version_record_id") or "").startswith("pver-")
            and str(ident.get("planned_task_id") or "").startswith("ptask-")
            and int(ident.get("control_sequence") or 0) >= 1
            and source.get("source_state") in RECOVERY_ALLOWED_STATES
            and int(source.get("source_state_version") or 0) >= 1
            and all(
                _SHA_RE.match(str(source.get(key) or ""))
                for key in (
                    "source_version_sha256",
                    "active_plan_sha256",
                    "route_decision_sha256",
                    "delegation_sha256",
                    "handoff_envelope_sha256",
                    "delivery_receipt_sha256",
                )
            )
            and ((source.get("previous_recovery_control_id") is None and source.get("previous_recovery_control_sha256") is None)
                 or (str(source.get("previous_recovery_control_id") or "").startswith(RECOVERY_CONTROL_ID_PREFIX)
                     and _SHA_RE.match(str(source.get("previous_recovery_control_sha256") or ""))))
            and action in RECOVERY_ACTIONS
            and action_outcome_ok
            and candidate_ok
            and int(decision.get("retry_budget") or 0) == MAX_RETRY_ATTEMPTS
            and int(decision.get("retry_count_before") or 0) >= 0
            and decision.get("ownership_transfer_performed") is False
            and sem.get("mode") == RECOVERY_CONTROL_MODE
            and sem.get("control_plane_only") is True
            and sem.get("consumes_stage347_ownership_receipt") is True
            and sem.get("preserves_stage346_and_stage347_immutability") is True
            and sem.get("retry_is_dispatch") is False
            and sem.get("fallback_is_dispatch") is False
            and sem.get("reassignment_is_ownership_transfer") is False
            and sem.get("runtime_endpoint_resolution_performed") is False
            and sem.get("runtime_health_probe_performed") is False
            and sem.get("resource_assignment_performed") is False
            and sem.get("external_network_io_performed") is False
            and sem.get("governance_query_performed") is False
            and sem.get("authorization_reused_as_execution_grant") is False
            and sem.get("dispatch_performed") is False
            and sem.get("execution_authorized") is False
            and sem.get("target_action_dispatch_enabled") is False
            and sem.get("target_actuation") is False
            and sem.get("pre_dispatch_governance_revalidation_required") is True
            and sem.get("version_vector_extension_performed") is False
        )
    except Exception:
        return False


def canonical_recovery_control_definition() -> Dict[str, Any]:
    return {
        "schema_version": RECOVERY_CONTROL_SCHEMA_VERSION,
        "mode": RECOVERY_CONTROL_MODE,
        "recovery_control_id_prefix": RECOVERY_CONTROL_ID_PREFIX,
        "allowed_source_states": sorted(RECOVERY_ALLOWED_STATES),
        "actions": sorted(RECOVERY_ACTIONS),
        "max_retry_attempts": MAX_RETRY_ATTEMPTS,
        "requires_stage347_ownership_receipt": True,
        "requires_exact_stage344_route_decision": True,
        "requires_current_active_plan": True,
        "requires_current_mission_state_and_version_vector": True,
        "optimistic_conflict_control": "EXPECTED_CONTROL_COUNT_PLUS_TRANSACTIONAL_SEQUENCE_GUARD",
        "fallback_candidate_source": "IMMUTABLE_STAGE344_RANKED_ELIGIBLE_CANDIDATES_ONLY",
        "caller_selected_fallback_forbidden": True,
        "retry_retains_current_owner": True,
        "fallback_or_reassignment_transfers_ownership": False,
        "fallback_or_reassignment_requires_fresh_route_and_governance_control": True,
        "conflict_freeze_is_fail_closed": True,
        "runtime_endpoint_resolution_performed": False,
        "runtime_health_probe_performed": False,
        "resource_assignment_performed": False,
        "external_network_io_performed": False,
        "governance_query_performed": False,
        "dispatch_performed": False,
        "execution_authorized": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
        "pre_dispatch_governance_revalidation_required": True,
        "version_vector_extension_performed": False,
    }
