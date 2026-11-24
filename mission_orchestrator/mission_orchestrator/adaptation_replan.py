from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional

from .errors import MissionValidationError
from .plan_versioning import verify_plan_version_contract

ADAPTATION_REPLAN_STAGE_SCHEMA_VERSION = "apts-adaptation-replan-contract-identity-v1"
ADAPTATION_REPLAN_CONTRACT_SCHEMA_VERSION = "apts-canonical-adaptation-replan-contract-v1"
ADAPTATION_REPLAN_HASH_DOMAIN = "MISSION_CANONICAL_ADAPTATION_REPLAN_CONTRACT_V1"
ADAPTATION_REPLAN_REQUEST_HASH_DOMAIN = "MISSION_ADAPTATION_REPLAN_MATERIALIZATION_REQUEST_V1"

ADAPTATION_EPISODE_ID_PREFIX = "adpt-"
REPLAN_TRIGGER_ID_PREFIX = "rpln-"
REPLAN_SNAPSHOT_ID_PREFIX = "rpsnap-"
REPLAN_CANDIDATE_ID_PREFIX = "rpcand-"
REPLAN_DECISION_ID_PREFIX = "rpdec-"
REPLAN_COMMIT_ID_PREFIX = "rpcom-"

ADAPTATION_REPLAN_MODE = (
    "IMMUTABLE_ADAPTATION_EPISODE_AND_REPLAN_TRIGGER_IDENTITY_"
    "BOUND_TO_CURRENT_NONTERMINAL_MISSION_AND_ACTIVE_PLAN_PENDING_CLASSIFICATION"
)
ADAPTATION_REPLAN_AUTHORITY = "MISSION_ORCHESTRATOR_ADAPTATION_REPLAN_MATERIALIZATION"
ADAPTATION_EPISODE_INITIAL_STATE = "DETECTED"
ADAPTATION_EPISODE_STATES = (
    "DETECTED",
    "CLASSIFIED",
    "ELIGIBILITY_PENDING",
    "ELIGIBLE",
    "SNAPSHOT_BOUND",
    "REPLAN_REQUESTED",
    "CANDIDATE_READY",
    "VALIDATED",
    "COMMITTED",
    "HANDOFF_READY",
)

# These are exactly the canonical Stage-3.2 source states from which REPLAN is
# semantically legal. Stage 3.7.1 deliberately cannot reopen terminal Missions
# and does not materialize a second episode once the lifecycle is already in
# REPLANNING.
ADAPTATION_REPLAN_ALLOWED_MISSION_STATES = frozenset({
    "RUNNING",
    "WAITING_EVIDENCE",
    "WAITING_APPROVAL",
})

REPLAN_TRIGGER_SOURCES = (
    "MISSION_EVENT",
    "OPERATOR_REQUEST",
    "SYSTEM_OBSERVATION",
    "EXTERNAL_SIGNAL",
)

# Stage 3.7.1 records why adaptation was detected, but does not perform the
# later trigger classification/eligibility decision. The code is therefore a
# bounded detection taxonomy, not a replan authorization decision.
REPLAN_TRIGGER_CODES = (
    "CTI_CHANGE",
    "TASK_FAILURE",
    "TASK_TIMEOUT",
    "AUTHORIZATION_REVOCATION",
    "MISSION_STATE_CHANGE",
    "EVIDENCE_CHANGE",
    "PIP_CHANGE",
    "DEPENDENCY_CHANGE",
    "POLICY_CHANGE",
    "RESOURCE_CHANGE",
    "OPERATOR_INTERVENTION",
    "OTHER",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "trigger_source",
    "trigger_code",
    "source_event_id",
    "expected_source_event_sha256",
    "evidence_refs",
    "detected_by",
    "reason",
    "metadata",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_adaptation_episode_id() -> str:
    return f"{ADAPTATION_EPISODE_ID_PREFIX}{uuid.uuid4()}"


def new_replan_trigger_id() -> str:
    return f"{REPLAN_TRIGGER_ID_PREFIX}{uuid.uuid4()}"


def _string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} is required and must be a non-empty string")
    value = value.strip()
    if len(value) > max_len:
        raise MissionValidationError(f"{key} exceeds {max_len} characters")
    return value


def _optional_string(payload: Mapping[str, Any], key: str, max_len: int = 160) -> Optional[str]:
    value = payload.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.strip():
        raise MissionValidationError(f"{key} must be a non-empty string when provided")
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


def _optional_sha(payload: Mapping[str, Any], key: str) -> Optional[str]:
    raw = payload.get(key)
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest when provided")
    value = raw.strip().lower()
    if not _SHA_RE.match(value):
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest when provided")
    return value


def _evidence_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MissionValidationError("evidence_refs must be an array")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MissionValidationError("evidence_refs entries must be non-empty strings")
        item = item.strip()
        if len(item) > 256:
            raise MissionValidationError("evidence_refs entry exceeds 256 characters")
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_adaptation_replan_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("adaptation/replan materialization request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported adaptation/replan materialization field(s): "
            + ", ".join(unknown)
            + "; Stage 3.7.1 materializes only the immutable adaptation episode and replan-trigger identities. "
              "Caller-supplied classification, eligibility, snapshot, lifecycle command, planner output, plan delta, "
              "candidate/decision/commit, Governance authorization, dispatch, execution, terminal reopening, or actuation fields are forbidden"
        )

    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "detected_by": _string(payload, "detected_by", 128),
    }
    for key, value in values.items():
        if not _ID_RE.match(value):
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")

    trigger_source = _string(payload, "trigger_source", 40).upper()
    if trigger_source not in REPLAN_TRIGGER_SOURCES:
        raise MissionValidationError(
            "trigger_source is not canonical; expected one of: " + ", ".join(REPLAN_TRIGGER_SOURCES)
        )
    trigger_code = _string(payload, "trigger_code", 80).upper()
    if trigger_code not in REPLAN_TRIGGER_CODES:
        raise MissionValidationError(
            "trigger_code is not canonical; expected one of: " + ", ".join(REPLAN_TRIGGER_CODES)
        )

    source_event_id = _optional_string(payload, "source_event_id")
    source_event_sha256 = _optional_sha(payload, "expected_source_event_sha256")
    if source_event_id is not None:
        if not source_event_id.startswith("mevent-") or not _ID_RE.match(source_event_id):
            raise MissionValidationError("source_event_id must be a canonical mevent-* identifier")
        if source_event_sha256 is None:
            raise MissionValidationError("expected_source_event_sha256 is required when source_event_id is provided")
    elif source_event_sha256 is not None:
        raise MissionValidationError("source_event_id is required when expected_source_event_sha256 is provided")
    if trigger_source == "MISSION_EVENT" and source_event_id is None:
        raise MissionValidationError("trigger_source MISSION_EVENT requires source_event_id and expected_source_event_sha256")
    if trigger_source != "MISSION_EVENT" and source_event_id is not None:
        raise MissionValidationError("source_event_id is only valid when trigger_source is MISSION_EVENT")

    evidence_refs = _evidence_refs(payload.get("evidence_refs"))
    if source_event_id is None and not evidence_refs:
        raise MissionValidationError(
            "adaptation/replan detection requires at least one evidence_refs entry when no source_event_id is bound"
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
        "trigger_source": trigger_source,
        "trigger_code": trigger_code,
        "source_event_id": source_event_id,
        "expected_source_event_sha256": source_event_sha256,
        "evidence_refs": evidence_refs,
        "reason": reason,
        "metadata": dict(metadata),
    }


def adaptation_replan_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": ADAPTATION_REPLAN_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def build_adaptation_replan_contract(
    *,
    adaptation_episode_id: str,
    replan_trigger_id: str,
    mission_id: str,
    request: Mapping[str, Any],
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    source_event: Optional[Mapping[str, Any]],
    detected_at: str,
) -> Dict[str, Any]:
    plan_contract = active_plan.get("plan_version_contract")
    if not isinstance(plan_contract, Mapping) or not verify_plan_version_contract(plan_contract):
        raise MissionValidationError("active Stage-3.3.7 Plan version failed integrity verification")
    if source_state.get("state") not in ADAPTATION_REPLAN_ALLOWED_MISSION_STATES:
        raise MissionValidationError("Stage-3.7.1 adaptation/replan identity requires a canonical REPLAN-eligible non-terminal Mission state")

    source_generation = int(active_plan["plan_version"])
    target_generation = source_generation + 1
    event_binding = None
    if source_event is not None:
        event_binding = {
            "event_id": source_event["event_id"],
            "event_type": source_event["event_type"],
            "canonical_sha256": source_event["canonical_sha256"],
            "state_version": source_event.get("state_version"),
            "plan_version": source_event.get("plan_version"),
            "occurred_at": source_event["occurred_at"],
        }

    core = {
        "schema_version": ADAPTATION_REPLAN_CONTRACT_SCHEMA_VERSION,
        "stage_schema_version": ADAPTATION_REPLAN_STAGE_SCHEMA_VERSION,
        "identity": {
            "adaptation_episode_id": adaptation_episode_id,
            "replan_trigger_id": replan_trigger_id,
            "mission_id": mission_id,
        },
        "source_bindings": {
            "source_state": source_state["state"],
            "source_state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "source_plan_version_record_id": active_plan["plan_version_record_id"],
            "source_plan_version": source_generation,
            "source_plan_generation": source_generation,
            "target_plan_generation": target_generation,
            "source_plan_sha256": active_plan["canonical_sha256"],
            "source_event": event_binding,
        },
        "replan_trigger": {
            "trigger_source": request["trigger_source"],
            "trigger_code": request["trigger_code"],
            "evidence_refs": list(request.get("evidence_refs") or []),
            "evidence_ref_count": len(request.get("evidence_refs") or []),
            "source_event_bound": event_binding is not None,
            "detection_materialized": True,
            "classification_performed": False,
            "eligibility_evaluation_performed": False,
        },
        "adaptation_episode": {
            "episode_state": ADAPTATION_EPISODE_INITIAL_STATE,
            "adaptation_episode_identity_materialized": True,
            "replan_trigger_identity_materialized": True,
            "classification_performed": False,
            "eligibility_evaluation_performed": False,
            "replan_snapshot_bound": False,
            "lifecycle_replan_requested": False,
            "planner_invocation_performed": False,
            "replan_candidate_created": False,
            "plan_delta_computed": False,
            "plan_validation_performed": False,
            "replan_decision_committed": False,
            "plan_supersession_performed": False,
            "lifecycle_handoff_ready": False,
            "terminal_state_reopening_performed": False,
        },
        "authority_boundary": {
            "authority": ADAPTATION_REPLAN_AUTHORITY,
            "mode": ADAPTATION_REPLAN_MODE,
            "adaptation_identity_is_lifecycle_replan_command": False,
            "replan_trigger_is_replan_authorization": False,
            "adaptation_identity_is_planner_invocation": False,
            "adaptation_identity_is_successor_plan": False,
            "adaptation_identity_is_plan_supersession": False,
            "historical_plan_mutation_performed": False,
            "terminal_state_reopening_performed": False,
            "mission_state_transition_performed": False,
            "governance_query_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "dispatch_performed": False,
            "new_execution_attempt_created": False,
            "external_network_io_performed": False,
            "target_action_dispatch_performed": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "idempotency_key": request["idempotency_key"],
            "detected_by": request["detected_by"],
            "reason": request.get("reason"),
            "metadata": dict(request.get("metadata") or {}),
            "detected_at": detected_at,
        },
    }
    digest = sha256_hex({"hash_domain": ADAPTATION_REPLAN_HASH_DOMAIN, "contract": core})
    return {**core, "canonical_sha256": digest}


def verify_adaptation_replan_contract(contract: Mapping[str, Any]) -> bool:
    try:
        digest = contract["canonical_sha256"]
        core = {k: v for k, v in contract.items() if k != "canonical_sha256"}
        identity = contract["identity"]
        source = contract["source_bindings"]
        trigger = contract["replan_trigger"]
        episode = contract["adaptation_episode"]
        boundary = contract["authority_boundary"]
        event = source.get("source_event")
        event_ok = event is None or (
            str(event.get("event_id", "")).startswith("mevent-")
            and bool(_SHA_RE.match(str(event.get("canonical_sha256", ""))))
        )
        return (
            contract["schema_version"] == ADAPTATION_REPLAN_CONTRACT_SCHEMA_VERSION
            and contract["stage_schema_version"] == ADAPTATION_REPLAN_STAGE_SCHEMA_VERSION
            and str(identity["adaptation_episode_id"]).startswith(ADAPTATION_EPISODE_ID_PREFIX)
            and str(identity["replan_trigger_id"]).startswith(REPLAN_TRIGGER_ID_PREFIX)
            and source["source_state"] in ADAPTATION_REPLAN_ALLOWED_MISSION_STATES
            and str(source["source_plan_version_record_id"]).startswith("pver-")
            and int(source["source_plan_version"]) >= 1
            and int(source["source_plan_generation"]) == int(source["source_plan_version"])
            and int(source["target_plan_generation"]) == int(source["source_plan_generation"]) + 1
            and bool(_SHA_RE.match(str(source["source_plan_sha256"])))
            and event_ok
            and trigger["trigger_source"] in REPLAN_TRIGGER_SOURCES
            and trigger["trigger_code"] in REPLAN_TRIGGER_CODES
            and int(trigger["evidence_ref_count"]) == len(trigger["evidence_refs"])
            and bool(trigger["source_event_bound"]) == (event is not None)
            and trigger["detection_materialized"] is True
            and trigger["classification_performed"] is False
            and trigger["eligibility_evaluation_performed"] is False
            and episode["episode_state"] == ADAPTATION_EPISODE_INITIAL_STATE
            and episode["adaptation_episode_identity_materialized"] is True
            and episode["replan_trigger_identity_materialized"] is True
            and episode["classification_performed"] is False
            and episode["eligibility_evaluation_performed"] is False
            and episode["replan_snapshot_bound"] is False
            and episode["lifecycle_replan_requested"] is False
            and episode["planner_invocation_performed"] is False
            and episode["replan_candidate_created"] is False
            and episode["plan_delta_computed"] is False
            and episode["plan_validation_performed"] is False
            and episode["replan_decision_committed"] is False
            and episode["plan_supersession_performed"] is False
            and episode["lifecycle_handoff_ready"] is False
            and episode["terminal_state_reopening_performed"] is False
            and boundary["authority"] == ADAPTATION_REPLAN_AUTHORITY
            and boundary["mode"] == ADAPTATION_REPLAN_MODE
            and boundary["adaptation_identity_is_lifecycle_replan_command"] is False
            and boundary["replan_trigger_is_replan_authorization"] is False
            and boundary["adaptation_identity_is_planner_invocation"] is False
            and boundary["adaptation_identity_is_successor_plan"] is False
            and boundary["adaptation_identity_is_plan_supersession"] is False
            and boundary["historical_plan_mutation_performed"] is False
            and boundary["terminal_state_reopening_performed"] is False
            and boundary["mission_state_transition_performed"] is False
            and boundary["governance_query_performed"] is False
            and boundary["runtime_query_performed"] is False
            and boundary["runtime_control_io_performed"] is False
            and boundary["dispatch_performed"] is False
            and boundary["new_execution_attempt_created"] is False
            and boundary["external_network_io_performed"] is False
            and boundary["target_action_dispatch_performed"] is False
            and boundary["target_actuation"] is False
            and digest == sha256_hex({"hash_domain": ADAPTATION_REPLAN_HASH_DOMAIN, "contract": core})
        )
    except Exception:
        return False


def canonical_adaptation_replan_definition() -> Dict[str, Any]:
    return {
        "stage_schema_version": ADAPTATION_REPLAN_STAGE_SCHEMA_VERSION,
        "schema_version": ADAPTATION_REPLAN_CONTRACT_SCHEMA_VERSION,
        "adaptation_episode_identity_prefix": ADAPTATION_EPISODE_ID_PREFIX,
        "replan_trigger_identity_prefix": REPLAN_TRIGGER_ID_PREFIX,
        "reserved_future_identity_prefixes": {
            "replan_snapshot": REPLAN_SNAPSHOT_ID_PREFIX,
            "replan_candidate": REPLAN_CANDIDATE_ID_PREFIX,
            "replan_decision": REPLAN_DECISION_ID_PREFIX,
            "replan_commit": REPLAN_COMMIT_ID_PREFIX,
        },
        "mode": ADAPTATION_REPLAN_MODE,
        "authority": ADAPTATION_REPLAN_AUTHORITY,
        "episode_initial_state": ADAPTATION_EPISODE_INITIAL_STATE,
        "episode_state_model": list(ADAPTATION_EPISODE_STATES),
        "allowed_mission_states": sorted(ADAPTATION_REPLAN_ALLOWED_MISSION_STATES),
        "trigger_sources": list(REPLAN_TRIGGER_SOURCES),
        "trigger_codes": list(REPLAN_TRIGGER_CODES),
        "requires_current_active_plan_head": True,
        "source_plan_generation_rule": "ACTIVE_PLAN_VERSION",
        "target_plan_generation_rule": "SOURCE_PLAN_GENERATION_PLUS_ONE",
        "historical_plans_immutable": True,
        "new_plan_supersedes_old_only_after_future_replan_commit": True,
        "terminal_mission_reopening_allowed": False,
        "adaptation_episode_identity_materialized": True,
        "replan_trigger_identity_materialized": True,
        "classification_performed": False,
        "eligibility_evaluation_performed": False,
        "replan_snapshot_bound": False,
        "lifecycle_replan_requested": False,
        "planner_invocation_performed": False,
        "replan_candidate_created": False,
        "plan_delta_computed": False,
        "plan_validation_performed": False,
        "replan_decision_committed": False,
        "plan_supersession_performed": False,
        "mission_state_transition_performed": False,
        "governance_query_performed": False,
        "runtime_query_performed": False,
        "runtime_control_io_performed": False,
        "dispatch_performed": False,
        "new_execution_attempt_created": False,
        "external_network_io_performed": False,
        "target_action_dispatch_performed": False,
        "target_actuation": False,
        "next_stage": "3.7.2",
    }
