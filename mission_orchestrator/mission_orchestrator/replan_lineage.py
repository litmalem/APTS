from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError
from .adaptation_replan import verify_adaptation_replan_contract
from .adaptation_trigger import verify_adaptation_trigger_classification_contract
from .replan_eligibility import verify_replan_eligibility_contract
from .replan_snapshot import verify_replan_snapshot_contract
from .replan_candidate import verify_replan_candidate_contract
from .replan_validation import verify_replan_validation_contract
from .replan_commit import verify_replan_commit_contract
from .replan_handoff import verify_replan_handoff_contract
from .plan_versioning import verify_plan_version_contract

REPLAN_EVENT_LINEAGE_SCHEMA_VERSION = "apts-replan-event-lineage-v1"
REPLAN_EVENT_REPLAY_SCHEMA_VERSION = "apts-replan-event-replay-v1"
REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION = "apts-replan-recovery-checkpoint-v1"
REPLAN_RECOVERY_CHECKPOINT_HASH_DOMAIN = "MISSION_REPLAN_RECOVERY_CHECKPOINT_V1"
REPLAN_RECOVERY_REQUEST_HASH_DOMAIN = "MISSION_REPLAN_RECOVERY_REQUEST_V1"
REPLAN_REPLAY_HASH_DOMAIN = "MISSION_REPLAN_EVENT_REPLAY_V1"
REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX = "rplin-"
REPLAN_EVENT_LINEAGE_MODE = "CANONICAL_STAGE37_ADAPT_REPLAN_EVENT_SUBCHAIN_WITH_ARTIFACT_CAUSATION_BINDINGS"
REPLAN_REPLAY_MODE = "READ_ONLY_DETERMINISTIC_ORDERED_REPLAN_REPLAY_NO_SIDE_EFFECTS"
REPLAN_RECOVERY_MODE = "DURABLE_ADAPT_REPLAN_RECONSTRUCTION_NO_REEXECUTION_NO_REDISPATCH_NO_GOVERNANCE_OR_RUNTIME_QUERY"
REPLAN_RECOVERY_EVENT_TYPE = "MISSION_REPLAN_RECOVERY_CHECKPOINTED"

REPLAN_EVENT_TYPES = (
    "MISSION_ADAPTATION_REPLAN_DETECTED",
    "MISSION_ADAPTATION_TRIGGER_CLASSIFIED",
    "MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED",
    "MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND",
    "MISSION_REPLAN_CANDIDATE_GENERATED",
    "MISSION_REPLAN_DECISION_RECORDED",
    "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED",
    "MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED",
    "MISSION_REPLAN_HANDOFF_READY",
    REPLAN_RECOVERY_EVENT_TYPE,
)

_ARTIFACT_ID_FIELDS = {
    "MISSION_ADAPTATION_REPLAN_DETECTED": "adaptation_episode_id",
    "MISSION_ADAPTATION_TRIGGER_CLASSIFIED": "classification_id",
    "MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED": "eligibility_gate_id",
    "MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND": "replan_snapshot_id",
    "MISSION_REPLAN_CANDIDATE_GENERATED": "replan_candidate_id",
    "MISSION_REPLAN_DECISION_RECORDED": "replan_validation_id",
    "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED": "successor_plan_version_record_id",
    "MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED": "replan_commit_id",
    "MISSION_REPLAN_HANDOFF_READY": "replan_handoff_id",
    REPLAN_RECOVERY_EVENT_TYPE: "checkpoint_id",
}

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_adaptation_episode_id",
    "expected_replan_handoff_id",
    "expected_replan_handoff_sha256",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_replan_event_count",
    "expected_replan_event_tip_sha256",
    "created_by",
    "reason",
    "metadata",
}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@\-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_replan_recovery_checkpoint_id() -> str:
    return f"{REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX}{uuid.uuid4()}"


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
    if _SHA_RE.match(value) is None:
        raise MissionValidationError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


def normalize_replan_recovery_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("replan recovery checkpoint request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported replan recovery checkpoint field(s): " + ", ".join(unknown)
            + "; Stage 3.7.9 reconstructs exclusively from canonical durable Stage-3.7.1 through Stage-3.7.8 artifacts and the Mission event ledger. Caller-supplied replacement plans, lifecycle transitions, Governance/runtime observations, cancellation commands, routing/delegation/dispatch commands, execution attempts, or target actions are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_adaptation_episode_id": _string(payload, "expected_adaptation_episode_id"),
        "expected_replan_handoff_id": _string(payload, "expected_replan_handoff_id"),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "created_by": _string(payload, "created_by", 128),
    }
    for key, value in values.items():
        if _ID_RE.match(value) is None:
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_adaptation_episode_id"].startswith("adpt-"):
        raise MissionValidationError("expected_adaptation_episode_id must be a canonical adpt-* identifier")
    if not values["expected_replan_handoff_id"].startswith("rphof-"):
        raise MissionValidationError("expected_replan_handoff_id must be a canonical rphof-* identifier")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MissionValidationError("metadata must be a JSON object")
    canonical_json(metadata)
    reason = payload.get("reason")
    if reason in (None, ""):
        reason = None
    else:
        if not isinstance(reason, str) or not reason.strip():
            raise MissionValidationError("reason must be a non-empty string when provided")
        reason = reason.strip()
        if len(reason) > 2000:
            raise MissionValidationError("reason exceeds 2000 characters")
    return {
        **values,
        "expected_version_sha256": _sha(payload, "expected_version_sha256"),
        "expected_state_version": _positive_int(payload, "expected_state_version"),
        "expected_replan_handoff_sha256": _sha(payload, "expected_replan_handoff_sha256"),
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_replan_event_count": _positive_int(payload, "expected_replan_event_count"),
        "expected_replan_event_tip_sha256": _sha(payload, "expected_replan_event_tip_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def replan_recovery_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": REPLAN_RECOVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def is_replan_event(event: Mapping[str, Any]) -> bool:
    return str(event.get("event_type") or "") in REPLAN_EVENT_TYPES


def build_replan_event_replay(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    selected = [dict(event) for event in events if is_replan_event(event)]
    replay_events = []
    for seq, event in enumerate(selected, 1):
        payload = dict(event.get("payload") or {})
        event_type = str(event.get("event_type") or "")
        field = _ARTIFACT_ID_FIELDS.get(event_type)
        replay_events.append({
            "replay_sequence": seq,
            "event_id": event.get("event_id"),
            "event_type": event_type,
            "causation_id": event.get("causation_id"),
            "state_version": event.get("state_version"),
            "plan_version": event.get("plan_version"),
            "policy_version": event.get("policy_version"),
            "artifact_id": None if field is None else payload.get(field),
            "artifact_sha256": payload.get("canonical_sha256") or payload.get("successor_plan_sha256"),
            "event_sha256": event.get("canonical_sha256"),
            "previous_event_sha256": event.get("previous_event_sha256"),
            "occurred_at": event.get("occurred_at"),
        })
    core = {
        "schema_version": REPLAN_EVENT_REPLAY_SCHEMA_VERSION,
        "mode": REPLAN_REPLAY_MODE,
        "replan_event_count": len(replay_events),
        "events": replay_events,
    }
    digest = sha256_hex({"hash_domain": REPLAN_REPLAY_HASH_DOMAIN, "replay": core})
    tip = None if not selected else selected[-1]
    return {
        **core,
        "replay_sha256": digest,
        "replan_event_tip_event_id": None if tip is None else tip.get("event_id"),
        "replan_event_tip_sha256": None if tip is None else tip.get("canonical_sha256"),
        "read_only": True,
        "side_effects_performed": False,
    }


def _ref(row: Mapping[str, Any], key: str) -> Dict[str, Any]:
    return {"id": row[key], "canonical_sha256": row["canonical_sha256"]}


def _verify_chain(
    *, adaptation: Mapping[str, Any], classification: Mapping[str, Any], eligibility: Mapping[str, Any],
    snapshot: Mapping[str, Any], candidate: Mapping[str, Any], validation: Mapping[str, Any],
    commit: Mapping[str, Any], handoff: Mapping[str, Any], predecessor_plan: Mapping[str, Any],
    successor_plan: Mapping[str, Any], active_plan: Mapping[str, Any],
) -> None:
    checks = (
        (verify_adaptation_replan_contract, adaptation, "adaptation_replan_contract", "Stage-3.7.1 adaptation/replan"),
        (verify_adaptation_trigger_classification_contract, classification, "adaptation_trigger_classification_contract", "Stage-3.7.2 classification"),
        (verify_replan_eligibility_contract, eligibility, "replan_eligibility_governance_contract", "Stage-3.7.3 eligibility"),
        (verify_replan_snapshot_contract, snapshot, "replan_snapshot_contract", "Stage-3.7.4 snapshot"),
        (verify_replan_candidate_contract, candidate, "replan_candidate_contract", "Stage-3.7.5 candidate"),
        (verify_replan_validation_contract, validation, "replan_validation_contract", "Stage-3.7.6 validation"),
        (verify_replan_commit_contract, commit, "replan_commit_contract", "Stage-3.7.7 commit"),
        (verify_replan_handoff_contract, handoff, "replan_handoff_contract", "Stage-3.7.8 handoff"),
    )
    for verifier, row, key, label in checks:
        if not verifier(row.get(key) or {}):
            raise MissionValidationError(f"{label} failed integrity verification")
    for label, plan in (("predecessor", predecessor_plan), ("successor", successor_plan), ("active", active_plan)):
        if not verify_plan_version_contract(plan.get("plan_version_contract") or {}):
            raise MissionValidationError(f"{label} Plan version failed integrity verification")

    mission_id = handoff["mission_id"]
    episode_id = handoff["adaptation_episode_id"]
    trigger_id = handoff["replan_trigger_id"]
    for row in (adaptation, classification, eligibility, snapshot, candidate, validation, commit, handoff):
        if row.get("mission_id") != mission_id or row.get("adaptation_episode_id") != episode_id:
            raise MissionValidationError("Stage-3.7 artifact chain mission/episode identity mismatch")
    for row in (adaptation, classification, eligibility, commit, handoff):
        if row.get("replan_trigger_id") != trigger_id:
            raise MissionValidationError("Stage-3.7 artifact chain trigger identity mismatch")

    if classification.get("source_adaptation_replan_sha256") != adaptation.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.2 classification does not bind the exact Stage-3.7.1 artifact")
    if eligibility.get("source_adaptation_replan_sha256") != adaptation.get("canonical_sha256") or eligibility.get("source_classification_sha256") != classification.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.3 eligibility does not bind the exact Stage-3.7.1/3.7.2 chain")
    if snapshot.get("source_adaptation_replan_sha256") != adaptation.get("canonical_sha256") or snapshot.get("source_classification_sha256") != classification.get("canonical_sha256") or snapshot.get("source_eligibility_sha256") != eligibility.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.4 snapshot does not bind the exact eligibility chain")
    if candidate.get("source_replan_snapshot_sha256") != snapshot.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.5 candidate does not bind the exact Stage-3.7.4 snapshot")
    if validation.get("source_replan_candidate_sha256") != candidate.get("canonical_sha256") or validation.get("source_replan_snapshot_sha256") != snapshot.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.6 validation does not bind the exact candidate/snapshot")
    if commit.get("source_replan_validation_sha256") != validation.get("canonical_sha256") or commit.get("source_replan_candidate_sha256") != candidate.get("canonical_sha256") or commit.get("source_replan_snapshot_sha256") != snapshot.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.7 commit does not bind the exact validation/candidate/snapshot")
    if handoff.get("source_replan_commit_sha256") != commit.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.8 handoff does not bind the exact Stage-3.7.7 commit")

    if handoff.get("predecessor_plan_version_record_id") != predecessor_plan.get("plan_version_record_id") or handoff.get("predecessor_plan_sha256") != predecessor_plan.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.8 predecessor Plan binding is inconsistent")
    if handoff.get("successor_plan_version_record_id") != successor_plan.get("plan_version_record_id") or handoff.get("successor_plan_sha256") != successor_plan.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.8 successor Plan binding is inconsistent")
    if commit.get("successor_plan_version_record_id") != successor_plan.get("plan_version_record_id") or commit.get("successor_plan_sha256") != successor_plan.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.7.7 successor Plan materialization binding is inconsistent")
    if successor_plan.get("predecessor_plan_version_record_id") != predecessor_plan.get("plan_version_record_id") or successor_plan.get("replan_transition_id") != commit.get("replan_commit_id"):
        raise MissionValidationError("successor Plan causal predecessor/replan binding is inconsistent")
    if active_plan.get("plan_version_record_id") != successor_plan.get("plan_version_record_id") or int(active_plan.get("plan_version", 0)) != int(successor_plan.get("plan_version", -1)) or active_plan.get("canonical_sha256") != successor_plan.get("canonical_sha256"):
        raise MissionValidationError("active Plan head is not the Stage-3.7.7/3.7.8 successor")


def build_replan_recovery_checkpoint_contract(
    *, checkpoint_id: str, checkpoint_version: int, mission_id: str, request_sha256: str,
    source_state: Mapping[str, Any], source_version_sha256: str,
    adaptation: Mapping[str, Any], classification: Mapping[str, Any], eligibility: Mapping[str, Any],
    snapshot: Mapping[str, Any], candidate: Mapping[str, Any], validation: Mapping[str, Any],
    commit: Mapping[str, Any], handoff: Mapping[str, Any], predecessor_plan: Mapping[str, Any],
    successor_plan: Mapping[str, Any], active_plan: Mapping[str, Any], replay: Mapping[str, Any],
    created_by: str, reason: str | None, metadata: Mapping[str, Any], created_at: str,
) -> Dict[str, Any]:
    _verify_chain(
        adaptation=adaptation, classification=classification, eligibility=eligibility, snapshot=snapshot,
        candidate=candidate, validation=validation, commit=commit, handoff=handoff,
        predecessor_plan=predecessor_plan, successor_plan=successor_plan, active_plan=active_plan,
    )
    if source_state.get("state") != handoff.get("source_state") or int(source_state.get("state_version", -1)) != int(handoff.get("source_state_version", -2)):
        raise MissionValidationError("Mission state/version no longer matches the immutable Stage-3.7.8 handoff source state")
    hcontract = handoff["replan_handoff_contract"]
    task_handoff = hcontract["task_handoff"]
    core = {
        "schema_version": REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "identity": {
            "checkpoint_id": checkpoint_id,
            "checkpoint_version": int(checkpoint_version),
            "mission_id": mission_id,
            "adaptation_episode_id": handoff["adaptation_episode_id"],
            "replan_trigger_id": handoff["replan_trigger_id"],
            "replan_handoff_id": handoff["replan_handoff_id"],
            "successor_plan_version_record_id": successor_plan["plan_version_record_id"],
            "successor_plan_version": int(successor_plan["plan_version"]),
            "created_by": created_by,
            "created_at": created_at,
        },
        "source_bindings": {
            "state": source_state["state"],
            "state_version": int(source_state["state_version"]),
            "source_version_sha256": source_version_sha256,
            "adaptation_replan": _ref(adaptation, "adaptation_episode_id"),
            "trigger_classification": _ref(classification, "classification_id"),
            "eligibility_governance": _ref(eligibility, "eligibility_gate_id"),
            "replan_snapshot": _ref(snapshot, "replan_snapshot_id"),
            "replan_candidate": _ref(candidate, "replan_candidate_id"),
            "replan_validation": _ref(validation, "replan_validation_id"),
            "replan_commit": _ref(commit, "replan_commit_id"),
            "replan_handoff": _ref(handoff, "replan_handoff_id"),
            "predecessor_plan": _ref(predecessor_plan, "plan_version_record_id"),
            "successor_plan": _ref(successor_plan, "plan_version_record_id"),
            "active_plan": _ref(active_plan, "plan_version_record_id"),
            "replan_event_count": int(replay["replan_event_count"]),
            "replan_event_tip_event_id": replay["replan_event_tip_event_id"],
            "replan_event_tip_sha256": replay["replan_event_tip_sha256"],
            "replan_replay_sha256": replay["replay_sha256"],
        },
        "recovery_state": {
            "mission_state": source_state["state"],
            "mission_state_version": int(source_state["state_version"]),
            "adaptation_episode_id": handoff["adaptation_episode_id"],
            "replan_trigger_id": handoff["replan_trigger_id"],
            "effective_episode_state": "HANDOFF_READY",
            "trigger_detected": True,
            "trigger_classified": True,
            "replan_eligible": True,
            "snapshot_bound": True,
            "candidate_generated": True,
            "candidate_validated_for_commit": True,
            "successor_plan_materialized": True,
            "active_head_verified_as_successor": True,
            "handoff_ready": True,
            "predecessor_plan_version_record_id": predecessor_plan["plan_version_record_id"],
            "predecessor_plan_version": int(predecessor_plan["plan_version"]),
            "successor_plan_version_record_id": successor_plan["plan_version_record_id"],
            "successor_plan_version": int(successor_plan["plan_version"]),
            "replan_handoff_id": handoff["replan_handoff_id"],
            "task_disposition_count": int(task_handoff["task_disposition_count"]),
            "keep_count": int(task_handoff["keep_count"]),
            "drain_count": int(task_handoff["drain_count"]),
            "cancel_count": int(task_handoff["cancel_count"]),
            "supersede_count": int(task_handoff["supersede_count"]),
            "replace_count": int(task_handoff["replace_count"]),
            "adapt_replan_trajectory_reconstructed": True,
        },
        "replay": {
            "schema_version": replay["schema_version"],
            "mode": replay["mode"],
            "replan_event_count": int(replay["replan_event_count"]),
            "replan_event_tip_event_id": replay["replan_event_tip_event_id"],
            "replan_event_tip_sha256": replay["replan_event_tip_sha256"],
            "replay_sha256": replay["replay_sha256"],
            "event_ids": [x["event_id"] for x in replay["events"]],
        },
        "semantics": {
            "lineage_mode": REPLAN_EVENT_LINEAGE_MODE,
            "replay_mode": REPLAN_REPLAY_MODE,
            "recovery_mode": REPLAN_RECOVERY_MODE,
            "durable_repository_is_source_of_truth": True,
            "requires_stage371_through_stage378_chain": True,
            "requires_stage378_handoff_ready": True,
            "requires_successor_active_plan_head": True,
            "replay_read_only": True,
            "replay_is_execution": False,
            "recovery_is_execution": False,
            "recovery_is_dispatch": False,
            "recovery_is_runtime_resumption": False,
            "recovery_is_governance_authorization": False,
            "recovery_is_lifecycle_transition": False,
            "planner_rerun_performed": False,
            "llm_reinterpretation_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "governance_query_performed": False,
            "external_network_io_performed": False,
            "cancellation_io_performed": False,
            "routing_performed": False,
            "delegation_performed": False,
            "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False,
            "new_target_action_dispatch_performed": False,
            "mission_state_transition_performed": False,
            "historical_plan_mutation_performed": False,
            "active_plan_head_cas_performed": False,
            "target_actuation": False,
        },
        "provenance": {"request_sha256": request_sha256, "reason": reason, "metadata": dict(metadata)},
    }
    digest = sha256_hex({"hash_domain": REPLAN_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "hash_domain": REPLAN_RECOVERY_CHECKPOINT_HASH_DOMAIN, "canonicalization": "UTF8_SORTED_JSON_V1", "canonical_sha256": digest}}


def verify_replan_recovery_checkpoint_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION:
            return False
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        ident = contract["identity"]
        src = contract["source_bindings"]
        rec = contract["recovery_state"]
        replay = contract["replay"]
        sem = contract["semantics"]
        if integrity.get("hash_domain") != REPLAN_RECOVERY_CHECKPOINT_HASH_DOMAIN:
            return False
        if integrity.get("canonical_sha256") != sha256_hex({"hash_domain": REPLAN_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core}):
            return False
        if not str(ident.get("checkpoint_id", "")).startswith(REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX): return False
        if not str(ident.get("adaptation_episode_id", "")).startswith("adpt-"): return False
        if not str(ident.get("replan_handoff_id", "")).startswith("rphof-"): return False
        if not str(ident.get("successor_plan_version_record_id", "")).startswith("pver-"): return False
        if replay.get("schema_version") != REPLAN_EVENT_REPLAY_SCHEMA_VERSION or replay.get("mode") != REPLAN_REPLAY_MODE: return False
        if int(replay.get("replan_event_count", -1)) != int(src.get("replan_event_count", -2)): return False
        if replay.get("replan_event_tip_sha256") != src.get("replan_event_tip_sha256"): return False
        if replay.get("replay_sha256") != src.get("replan_replay_sha256"): return False
        if rec.get("effective_episode_state") != "HANDOFF_READY" or rec.get("adapt_replan_trajectory_reconstructed") is not True: return False
        for k in ("trigger_detected", "trigger_classified", "replan_eligible", "snapshot_bound", "candidate_generated", "candidate_validated_for_commit", "successor_plan_materialized", "active_head_verified_as_successor", "handoff_ready"):
            if rec.get(k) is not True: return False
        if sem.get("lineage_mode") != REPLAN_EVENT_LINEAGE_MODE or sem.get("replay_mode") != REPLAN_REPLAY_MODE or sem.get("recovery_mode") != REPLAN_RECOVERY_MODE: return False
        for k in ("planner_rerun_performed", "llm_reinterpretation_performed", "runtime_query_performed", "runtime_control_io_performed", "governance_query_performed", "external_network_io_performed", "cancellation_io_performed", "routing_performed", "delegation_performed", "dispatch_redelivery_performed", "new_execution_attempt_created", "new_target_action_dispatch_performed", "mission_state_transition_performed", "historical_plan_mutation_performed", "active_plan_head_cas_performed", "target_actuation"):
            if sem.get(k) is not False: return False
        return True
    except Exception:
        return False


def canonical_replan_event_lineage_definition() -> Dict[str, Any]:
    return {
        "lineage_schema_version": REPLAN_EVENT_LINEAGE_SCHEMA_VERSION,
        "replay_schema_version": REPLAN_EVENT_REPLAY_SCHEMA_VERSION,
        "recovery_checkpoint_schema_version": REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_identity_prefix": REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX,
        "lineage_mode": REPLAN_EVENT_LINEAGE_MODE,
        "replay_mode": REPLAN_REPLAY_MODE,
        "recovery_mode": REPLAN_RECOVERY_MODE,
        "canonical_event_types": list(REPLAN_EVENT_TYPES),
        "source_stages": ["3.7.1", "3.7.2", "3.7.3", "3.7.4", "3.7.5", "3.7.6", "3.7.7", "3.7.8"],
        "requires_stage378_handoff_ready": True,
        "requires_successor_active_plan_head": True,
        "replay_read_only": True,
        "recovery_reconstructs_from_durable_repository": True,
        "planner_rerun_performed": False,
        "governance_query_performed": False,
        "runtime_query_performed": False,
        "runtime_control_io_performed": False,
        "cancellation_io_performed": False,
        "routing_performed": False,
        "delegation_performed": False,
        "dispatch_performed": False,
        "execution_attempt_created": False,
        "mission_state_transition_performed": False,
        "historical_plan_mutation_performed": False,
        "active_plan_head_cas_performed": False,
        "target_actuation": False,
        "next_stage": "3.7.10",
    }
