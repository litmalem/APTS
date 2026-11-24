from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Optional, Sequence

from .errors import MissionValidationError

PLANNING_EVENT_LINEAGE_SCHEMA_VERSION = "apts-planning-event-lineage-v1"
PLANNING_EVENT_REPLAY_SCHEMA_VERSION = "apts-planning-event-replay-v1"
PLANNING_RECOVERY_CHECKPOINT_SCHEMA_VERSION = "apts-planning-recovery-checkpoint-v1"
PLANNING_RECOVERY_CHECKPOINT_HASH_DOMAIN = "MISSION_PLANNING_RECOVERY_CHECKPOINT_V1"
PLANNING_RECOVERY_REQUEST_HASH_DOMAIN = "MISSION_PLANNING_RECOVERY_REQUEST_V1"
PLANNING_REPLAY_HASH_DOMAIN = "MISSION_PLANNING_EVENT_REPLAY_V1"
PLANNING_RECOVERY_CHECKPOINT_ID_PREFIX = "precover-"
PLANNING_EVENT_LINEAGE_MODE = "CANONICAL_MISSION_EVENT_SUBCHAIN_WITH_ARTIFACT_CAUSATION_BINDINGS"
PLANNING_REPLAY_MODE = "READ_ONLY_DETERMINISTIC_ORDERED_EVENT_REPLAY_NO_SIDE_EFFECTS"
PLANNING_RECOVERY_MODE = "DURABLE_ARTIFACT_RECONSTRUCTION_NO_PLANNER_RERUN_NO_EXTERNAL_READS"
PLANNING_RECOVERY_REQUIRED_STATES = frozenset({"PLANNING", "REPLANNING"})
PLANNING_RECOVERY_EVENT_TYPE = "MISSION_PLANNING_RECOVERY_CHECKPOINTED"

PLANNING_ARTIFACT_EVENT_TYPES = (
    "MISSION_PLAN_CONTRACT_REGISTERED",
    "MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED",
    "MISSION_TASK_DECOMPOSITION_REGISTERED",
    "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED",
    "MISSION_PLANNER_INVOKED",
    "MISSION_PLAN_GENERATED",
    "MISSION_PLAN_VALIDATED_FEASIBLE",
    "MISSION_PLAN_VERSION_ACTIVATED",
    "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED",
    "MISSION_TASK_READINESS_PROJECTED",
    PLANNING_RECOVERY_EVENT_TYPE,
)

_ARTIFACT_ID_FIELDS = {
    "MISSION_PLAN_CONTRACT_REGISTERED": "plan_id",
    "MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED": "snapshot_id",
    "MISSION_TASK_DECOMPOSITION_REGISTERED": "decomposition_id",
    "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED": "graph_id",
    "MISSION_PLANNER_INVOKED": "planner_invocation_id",
    "MISSION_PLAN_GENERATED": "generated_plan_id",
    "MISSION_PLAN_VALIDATED_FEASIBLE": "plan_validation_id",
    "MISSION_PLAN_VERSION_ACTIVATED": "plan_version_record_id",
    "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED": "successor_plan_version_record_id",
    "MISSION_TASK_READINESS_PROJECTED": "projection_id",
    PLANNING_RECOVERY_EVENT_TYPE: "checkpoint_id",
}

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_task_readiness_projection_id",
    "expected_task_readiness_projection_sha256",
    "expected_planning_event_count",
    "expected_planning_event_tip_sha256",
    "created_by",
    "reason",
    "metadata",
}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_planning_recovery_checkpoint_id() -> str:
    return f"{PLANNING_RECOVERY_CHECKPOINT_ID_PREFIX}{uuid.uuid4()}"


def _require_string(payload: Mapping[str, Any], key: str, max_len: int = 128) -> str:
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


def normalize_planning_recovery_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("planning recovery checkpoint request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported planning recovery checkpoint field(s): " + ", ".join(unknown)
            + "; Stage 3.3.9 reconstructs replay/recovery exclusively from canonical durable planning artifacts and does not accept caller-supplied plan, task, readiness, authorization, dispatch, execution, recovery-state, or replay content"
        )
    idem = _require_string(payload, "idempotency_key")
    if not _ID_RE.match(idem):
        raise MissionValidationError("idempotency_key contains unsupported characters")
    plan_record = _require_string(payload, "expected_active_plan_version_record_id")
    projection_id = _require_string(payload, "expected_task_readiness_projection_id")
    if not _ID_RE.match(plan_record):
        raise MissionValidationError("expected_active_plan_version_record_id contains unsupported characters")
    if not _ID_RE.match(projection_id):
        raise MissionValidationError("expected_task_readiness_projection_id contains unsupported characters")
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
        "expected_active_plan_version_record_id": plan_record,
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_task_readiness_projection_id": projection_id,
        "expected_task_readiness_projection_sha256": _sha(payload, "expected_task_readiness_projection_sha256"),
        "expected_planning_event_count": _positive_int(payload, "expected_planning_event_count"),
        "expected_planning_event_tip_sha256": _sha(payload, "expected_planning_event_tip_sha256"),
        "created_by": _require_string(payload, "created_by"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def planning_recovery_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": PLANNING_RECOVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def is_planning_event(event: Mapping[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    if event_type in PLANNING_ARTIFACT_EVENT_TYPES:
        return True
    if event_type == "MISSION_STATE_TRANSITIONED":
        payload = event.get("payload") or {}
        return str(payload.get("from_state") or "") in PLANNING_RECOVERY_REQUIRED_STATES or str(payload.get("to_state") or "") in PLANNING_RECOVERY_REQUIRED_STATES
    return False


def build_planning_event_replay(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    selected = [dict(event) for event in events if is_planning_event(event)]
    replay_events = []
    for seq, event in enumerate(selected, 1):
        payload = dict(event.get("payload") or {})
        artifact_id_field = _ARTIFACT_ID_FIELDS.get(str(event.get("event_type") or ""))
        artifact_id = None if artifact_id_field is None else payload.get(artifact_id_field)
        artifact_sha256 = payload.get("canonical_sha256")
        replay_events.append({
            "replay_sequence": seq,
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "causation_id": event.get("causation_id"),
            "state_version": event.get("state_version"),
            "plan_version": event.get("plan_version"),
            "artifact_id": artifact_id,
            "artifact_sha256": artifact_sha256,
            "event_sha256": event.get("canonical_sha256"),
            "previous_event_sha256": event.get("previous_event_sha256"),
            "occurred_at": event.get("occurred_at"),
        })
    replay_core = {
        "schema_version": PLANNING_EVENT_REPLAY_SCHEMA_VERSION,
        "mode": PLANNING_REPLAY_MODE,
        "planning_event_count": len(replay_events),
        "events": replay_events,
    }
    replay_sha = sha256_hex({"hash_domain": PLANNING_REPLAY_HASH_DOMAIN, "replay": replay_core})
    tip = None if not selected else selected[-1]
    return {
        **replay_core,
        "replay_sha256": replay_sha,
        "planning_event_tip_event_id": None if tip is None else tip.get("event_id"),
        "planning_event_tip_sha256": None if tip is None else tip.get("canonical_sha256"),
        "read_only": True,
        "side_effects_performed": False,
    }


def build_planning_recovery_checkpoint_contract(
    *,
    checkpoint_id: str,
    checkpoint_version: int,
    mission_id: str,
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    readiness_projection: Mapping[str, Any],
    replay: Mapping[str, Any],
    created_by: str,
    reason: Optional[str],
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    projection_contract = readiness_projection["projection_contract"]
    projection = projection_contract["projection"]
    core: Dict[str, Any] = {
        "schema_version": PLANNING_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "identity": {
            "checkpoint_id": checkpoint_id,
            "checkpoint_version": int(checkpoint_version),
            "mission_id": mission_id,
            "plan_version_record_id": active_plan["plan_version_record_id"],
            "plan_version": int(active_plan["plan_version"]),
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
            "planning_event_count": int(replay["planning_event_count"]),
            "planning_event_tip_event_id": replay["planning_event_tip_event_id"],
            "planning_event_tip_sha256": replay["planning_event_tip_sha256"],
            "planning_replay_sha256": replay["replay_sha256"],
        },
        "recovery_state": {
            "active_plan_version_record_id": active_plan["plan_version_record_id"],
            "active_plan_version": int(active_plan["plan_version"]),
            "active_plan_sha256": active_plan["canonical_sha256"],
            "candidate_plan_sha256": active_plan["candidate_plan_sha256"],
            "task_readiness_projection_id": readiness_projection["projection_id"],
            "task_readiness_projection_sha256": readiness_projection["canonical_sha256"],
            "task_count": int(readiness_projection["task_count"]),
            "ready_task_count": int(readiness_projection["ready_task_count"]),
            "blocked_task_count": int(readiness_projection["blocked_task_count"]),
            "wave_count": int(readiness_projection["wave_count"]),
            "ready_task_keys": list(projection["ready_task_keys"]),
            "blocked_task_keys": list(projection["blocked_task_keys"]),
            "scheduling_projection": dict(projection["scheduling_projection"]),
        },
        "replay": {
            "schema_version": replay["schema_version"],
            "mode": replay["mode"],
            "planning_event_count": int(replay["planning_event_count"]),
            "planning_event_tip_event_id": replay["planning_event_tip_event_id"],
            "planning_event_tip_sha256": replay["planning_event_tip_sha256"],
            "replay_sha256": replay["replay_sha256"],
            "event_ids": [item["event_id"] for item in replay["events"]],
        },
        "semantics": {
            "lineage_mode": PLANNING_EVENT_LINEAGE_MODE,
            "replay_mode": PLANNING_REPLAY_MODE,
            "recovery_mode": PLANNING_RECOVERY_MODE,
            "durable_repository_is_source_of_truth": True,
            "planner_rerun_performed": False,
            "external_model_invocation_performed": False,
            "external_network_io_performed": False,
            "governance_authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_authorization_query_performed": False,
            "replay_is_execution": False,
            "recovery_is_authorization": False,
            "readiness_is_permission": False,
            "task_is_dispatch": False,
            "target_action_dispatch_enabled": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": PLANNING_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core})
    return {
        **core,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": PLANNING_RECOVERY_CHECKPOINT_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_planning_recovery_checkpoint_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != PLANNING_RECOVERY_CHECKPOINT_SCHEMA_VERSION:
            return False
        identity = contract["identity"]
        source = contract["source_bindings"]
        recovery = contract["recovery_state"]
        replay = contract["replay"]
        semantics = contract["semantics"]
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        return (
            str(identity.get("checkpoint_id") or "").startswith(PLANNING_RECOVERY_CHECKPOINT_ID_PREFIX)
            and int(identity.get("checkpoint_version") or 0) >= 1
            and int(identity.get("plan_version") or 0) >= 1
            and source.get("state") in PLANNING_RECOVERY_REQUIRED_STATES
            and int(source.get("state_version") or 0) >= 1
            and _SHA256_RE.match(str(source.get("source_version_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("active_plan_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("candidate_plan_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("task_readiness_projection_sha256") or "")) is not None
            and int(source.get("planning_event_count") or 0) >= 1
            and _SHA256_RE.match(str(source.get("planning_event_tip_sha256") or "")) is not None
            and _SHA256_RE.match(str(source.get("planning_replay_sha256") or "")) is not None
            and recovery.get("active_plan_version_record_id") == identity.get("plan_version_record_id")
            and int(recovery.get("active_plan_version") or 0) == int(identity.get("plan_version") or 0)
            and recovery.get("active_plan_sha256") == source.get("active_plan_sha256")
            and recovery.get("task_readiness_projection_id") == source.get("task_readiness_projection_id")
            and recovery.get("task_readiness_projection_sha256") == source.get("task_readiness_projection_sha256")
            and int(recovery.get("task_count") or 0) >= 1
            and int(recovery.get("ready_task_count") or 0) + int(recovery.get("blocked_task_count") or 0) == int(recovery.get("task_count") or 0)
            and replay.get("schema_version") == PLANNING_EVENT_REPLAY_SCHEMA_VERSION
            and replay.get("mode") == PLANNING_REPLAY_MODE
            and int(replay.get("planning_event_count") or 0) == int(source.get("planning_event_count") or 0)
            and replay.get("planning_event_tip_sha256") == source.get("planning_event_tip_sha256")
            and replay.get("replay_sha256") == source.get("planning_replay_sha256")
            and len(replay.get("event_ids") or []) == int(source.get("planning_event_count") or 0)
            and semantics.get("durable_repository_is_source_of_truth") is True
            and semantics.get("planner_rerun_performed") is False
            and semantics.get("external_model_invocation_performed") is False
            and semantics.get("external_network_io_performed") is False
            and semantics.get("governance_authorization_authority") == "EXTERNAL_APTS_GSS"
            and semantics.get("governance_authorization_query_performed") is False
            and semantics.get("replay_is_execution") is False
            and semantics.get("recovery_is_authorization") is False
            and semantics.get("readiness_is_permission") is False
            and semantics.get("task_is_dispatch") is False
            and semantics.get("target_action_dispatch_enabled") is False
            and semantics.get("target_actuation") is False
            and integrity.get("hash_domain") == PLANNING_RECOVERY_CHECKPOINT_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex({"hash_domain": PLANNING_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core})
        )
    except Exception:
        return False


def canonical_planning_event_lineage_definition() -> Dict[str, Any]:
    return {
        "lineage_schema_version": PLANNING_EVENT_LINEAGE_SCHEMA_VERSION,
        "replay_schema_version": PLANNING_EVENT_REPLAY_SCHEMA_VERSION,
        "recovery_checkpoint_schema_version": PLANNING_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "lineage_mode": PLANNING_EVENT_LINEAGE_MODE,
        "replay_mode": PLANNING_REPLAY_MODE,
        "recovery_mode": PLANNING_RECOVERY_MODE,
        "checkpoint_id_prefix": PLANNING_RECOVERY_CHECKPOINT_ID_PREFIX,
        "allowed_states": sorted(PLANNING_RECOVERY_REQUIRED_STATES),
        "planning_artifact_event_types": list(PLANNING_ARTIFACT_EVENT_TYPES),
        "state_transition_events_touching_planning_or_replanning_included": True,
        "requires_active_stage3_3_7_plan_version": True,
        "requires_active_stage3_3_8_readiness_projection": True,
        "one_immutable_checkpoint_per_plan_version": True,
        "replay_read_only": True,
        "restart_recovery_from_durable_repository": True,
        "planner_rerun_on_recovery": False,
        "external_model_invocation_on_recovery": False,
        "external_network_io_on_recovery": False,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "governance_authorization_query_performed": False,
        "recovery_is_authorization": False,
        "replay_is_execution": False,
        "readiness_is_permission": False,
        "task_is_dispatch": False,
        "target_action_dispatch_enabled": False,
        "target_actuation": False,
    }
