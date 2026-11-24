from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, Mapping, Sequence

from .errors import MissionValidationError
from .task_outcome import TASK_OUTCOME_ID_PREFIX, verify_task_outcome_contract
from .task_terminality import TASK_TERMINALITY_ID_PREFIX, verify_task_terminality_eligibility_contract
from .task_evidence_binding import TASK_EVIDENCE_BINDING_ID_PREFIX, verify_task_evidence_binding_verification_contract
from .task_completion import TASK_COMPLETION_ID_PREFIX, verify_task_completion_contract
from .mission_outcome_aggregation import verify_mission_outcome_aggregation_contract
from .mission_success_evaluation import verify_mission_success_evaluation_contract
from .completion_readiness import verify_completion_readiness_contract
from .verified_completion import verify_verified_completion_contract

OUTCOME_EVENT_LINEAGE_SCHEMA_VERSION = "apts-outcome-event-lineage-v1"
OUTCOME_EVENT_REPLAY_SCHEMA_VERSION = "apts-outcome-event-replay-v1"
OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION = "apts-outcome-recovery-checkpoint-v1"
OUTCOME_RECOVERY_CHECKPOINT_HASH_DOMAIN = "MISSION_OUTCOME_RECOVERY_CHECKPOINT_V1"
OUTCOME_RECOVERY_REQUEST_HASH_DOMAIN = "MISSION_OUTCOME_RECOVERY_REQUEST_V1"
OUTCOME_REPLAY_HASH_DOMAIN = "MISSION_OUTCOME_EVENT_REPLAY_V1"
OUTCOME_RECOVERY_CHECKPOINT_ID_PREFIX = "orecover-"
OUTCOME_EVENT_LINEAGE_MODE = "CANONICAL_STAGE36_OUTCOME_EVENT_SUBCHAIN_WITH_EVIDENCE_CAUSATION_BINDINGS"
OUTCOME_REPLAY_MODE = "READ_ONLY_DETERMINISTIC_ORDERED_OUTCOME_REPLAY_NO_SIDE_EFFECTS"
OUTCOME_RECOVERY_MODE = "DURABLE_OUTCOME_RECONSTRUCTION_NO_REEXECUTION_NO_REDISPATCH_NO_GOVERNANCE_OR_RUNTIME_QUERY"
OUTCOME_RECOVERY_EVENT_TYPE = "MISSION_OUTCOME_RECOVERY_CHECKPOINTED"
OUTCOME_RECOVERY_ALLOWED_STATES = frozenset({"COMPLETED"})

OUTCOME_EVENT_TYPES = (
    "MISSION_TASK_OUTCOME_MATERIALIZED",
    "MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED",
    "MISSION_TASK_EVIDENCE_BINDING_VERIFIED",
    "MISSION_TASK_COMPLETION_COMMITTED",
    "MISSION_OUTCOME_AGGREGATED",
    "MISSION_SUCCESS_CRITERIA_EVALUATED",
    "MISSION_COMPLETION_READINESS_EVALUATED",
    "MISSION_VERIFIED_COMPLETION_DECLARED",
    "MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED",
    OUTCOME_RECOVERY_EVENT_TYPE,
)

_ARTIFACT_ID_FIELDS = {
    "MISSION_TASK_OUTCOME_MATERIALIZED": "task_outcome_id",
    "MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED": "eligibility_gate_id",
    "MISSION_TASK_EVIDENCE_BINDING_VERIFIED": "verification_id",
    "MISSION_TASK_COMPLETION_COMMITTED": "task_completion_id",
    "MISSION_OUTCOME_AGGREGATED": "aggregation_id",
    "MISSION_SUCCESS_CRITERIA_EVALUATED": "evaluation_id",
    "MISSION_COMPLETION_READINESS_EVALUATED": "readiness_id",
    "MISSION_VERIFIED_COMPLETION_DECLARED": "declaration_id",
    "MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED": "declaration_id",
    OUTCOME_RECOVERY_EVENT_TYPE: "checkpoint_id",
}

_REQUEST_FIELDS = {
    "idempotency_key",
    "expected_version_sha256",
    "expected_state_version",
    "expected_active_plan_version_record_id",
    "expected_active_plan_version",
    "expected_active_plan_sha256",
    "expected_declaration_id",
    "expected_declaration_sha256",
    "expected_outcome_event_count",
    "expected_outcome_event_tip_sha256",
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


def new_outcome_recovery_checkpoint_id() -> str:
    return f"{OUTCOME_RECOVERY_CHECKPOINT_ID_PREFIX}{uuid.uuid4()}"


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


def normalize_outcome_recovery_request(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MissionValidationError("outcome recovery checkpoint request body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise MissionValidationError(
            "unsupported outcome recovery checkpoint field(s): " + ", ".join(unknown)
            + "; Stage 3.6.9 reconstructs exclusively from canonical durable Stage-3.6.1 through Stage-3.6.8 artifacts and the verified Mission event ledger. Caller-supplied outcome state, task results, criteria decisions, readiness decisions, lifecycle commands, Governance/runtime observations, dispatch commands, or target actions are forbidden"
        )
    values = {
        "idempotency_key": _string(payload, "idempotency_key", 128),
        "expected_active_plan_version_record_id": _string(payload, "expected_active_plan_version_record_id"),
        "expected_declaration_id": _string(payload, "expected_declaration_id"),
        "created_by": _string(payload, "created_by", 128),
    }
    for key, value in values.items():
        if _ID_RE.match(value) is None:
            raise MissionValidationError(f"{key} contains unsupported characters")
    if not values["expected_active_plan_version_record_id"].startswith("pver-"):
        raise MissionValidationError("expected_active_plan_version_record_id must be a canonical pver-* identifier")
    if not values["expected_declaration_id"].startswith("mdecl-"):
        raise MissionValidationError("expected_declaration_id must be a canonical mdecl-* identifier")
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
        "expected_active_plan_version": _positive_int(payload, "expected_active_plan_version"),
        "expected_active_plan_sha256": _sha(payload, "expected_active_plan_sha256"),
        "expected_declaration_sha256": _sha(payload, "expected_declaration_sha256"),
        "expected_outcome_event_count": _positive_int(payload, "expected_outcome_event_count"),
        "expected_outcome_event_tip_sha256": _sha(payload, "expected_outcome_event_tip_sha256"),
        "reason": reason,
        "metadata": dict(metadata),
    }


def outcome_recovery_request_fingerprint(normalized: Mapping[str, Any]) -> str:
    return sha256_hex({"hash_domain": OUTCOME_RECOVERY_REQUEST_HASH_DOMAIN, "request": dict(normalized)})


def is_outcome_event(event: Mapping[str, Any]) -> bool:
    return str(event.get("event_type") or "") in OUTCOME_EVENT_TYPES


def build_outcome_event_replay(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    selected = [dict(event) for event in events if is_outcome_event(event)]
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
            "artifact_sha256": payload.get("canonical_sha256"),
            "event_sha256": event.get("canonical_sha256"),
            "previous_event_sha256": event.get("previous_event_sha256"),
            "occurred_at": event.get("occurred_at"),
        })
    core = {
        "schema_version": OUTCOME_EVENT_REPLAY_SCHEMA_VERSION,
        "mode": OUTCOME_REPLAY_MODE,
        "outcome_event_count": len(replay_events),
        "events": replay_events,
    }
    digest = sha256_hex({"hash_domain": OUTCOME_REPLAY_HASH_DOMAIN, "replay": core})
    tip = None if not selected else selected[-1]
    return {
        **core,
        "replay_sha256": digest,
        "outcome_event_tip_event_id": None if tip is None else tip.get("event_id"),
        "outcome_event_tip_sha256": None if tip is None else tip.get("canonical_sha256"),
        "read_only": True,
        "side_effects_performed": False,
    }


def _ref(row: Mapping[str, Any], key: str) -> Dict[str, Any]:
    return {"id": row[key], "canonical_sha256": row["canonical_sha256"]}


def _task_lineage(
    *,
    plan_version_record_id: str,
    task_outcomes: Sequence[Mapping[str, Any]],
    terminality_gates: Sequence[Mapping[str, Any]],
    evidence_bindings: Sequence[Mapping[str, Any]],
    task_completions: Sequence[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    outcomes = {x["planned_task_id"]: x for x in task_outcomes if x.get("plan_version_record_id") == plan_version_record_id}
    gates = {x["planned_task_id"]: x for x in terminality_gates if x.get("plan_version_record_id") == plan_version_record_id}
    bindings = {x["planned_task_id"]: x for x in evidence_bindings if x.get("plan_version_record_id") == plan_version_record_id}
    completions = {x["planned_task_id"]: x for x in task_completions if x.get("plan_version_record_id") == plan_version_record_id}
    if not outcomes:
        raise MissionValidationError("Stage-3.6.9 requires at least one canonical Stage-3.6.1 task outcome for the active Plan")
    if set(outcomes) != set(gates) or set(outcomes) != set(bindings) or set(outcomes) != set(completions):
        raise MissionValidationError("Stage-3.6.9 requires a complete Stage-3.6.1 through Stage-3.6.4 chain for every active-Plan task outcome")
    items: list[Dict[str, Any]] = []
    for task_id in sorted(outcomes):
        outcome = outcomes[task_id]
        gate = gates[task_id]
        binding = bindings[task_id]
        completion = completions[task_id]
        if not verify_task_outcome_contract(outcome["task_outcome_contract"]):
            raise MissionValidationError("Stage-3.6.1 task outcome failed integrity verification")
        if not verify_task_terminality_eligibility_contract(gate["task_terminality_eligibility_contract"]):
            raise MissionValidationError("Stage-3.6.2 terminality/eligibility contract failed integrity verification")
        if not verify_task_evidence_binding_verification_contract(binding["task_evidence_binding_verification_contract"]):
            raise MissionValidationError("Stage-3.6.3 evidence-binding contract failed integrity verification")
        if not verify_task_completion_contract(completion["task_completion_contract"]):
            raise MissionValidationError("Stage-3.6.4 task completion contract failed integrity verification")
        if gate.get("task_outcome_id") != outcome.get("task_outcome_id"):
            raise MissionValidationError("Stage-3.6.2 gate is not bound to the exact Stage-3.6.1 task outcome")
        if binding.get("eligibility_gate_id") != gate.get("eligibility_gate_id") or binding.get("task_outcome_id") != outcome.get("task_outcome_id"):
            raise MissionValidationError("Stage-3.6.3 evidence binding does not bind the exact Stage-3.6.1/3.6.2 chain")
        if completion.get("evidence_binding_verification_id") != binding.get("verification_id"):
            raise MissionValidationError("Stage-3.6.4 completion is not bound to the exact Stage-3.6.3 verification")
        items.append({
            "planned_task_id": task_id,
            "task_key": outcome.get("task_key"),
            "task_outcome": _ref(outcome, "task_outcome_id"),
            "terminality_eligibility": _ref(gate, "eligibility_gate_id"),
            "evidence_binding": _ref(binding, "verification_id"),
            "task_completion": _ref(completion, "task_completion_id"),
        })
    return items


def build_outcome_recovery_checkpoint_contract(
    *,
    checkpoint_id: str,
    checkpoint_version: int,
    mission_id: str,
    request_sha256: str,
    source_state: Mapping[str, Any],
    source_version_sha256: str,
    active_plan: Mapping[str, Any],
    declaration: Mapping[str, Any],
    readiness: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    aggregation: Mapping[str, Any],
    task_outcomes: Sequence[Mapping[str, Any]],
    terminality_gates: Sequence[Mapping[str, Any]],
    evidence_bindings: Sequence[Mapping[str, Any]],
    task_completions: Sequence[Mapping[str, Any]],
    replay: Mapping[str, Any],
    created_by: str,
    reason: str | None,
    metadata: Mapping[str, Any],
    created_at: str,
) -> Dict[str, Any]:
    if source_state.get("state") not in OUTCOME_RECOVERY_ALLOWED_STATES:
        raise MissionValidationError("Stage-3.6.9 outcome recovery requires Mission state COMPLETED")
    if not verify_verified_completion_contract(declaration["verified_completion_contract"]):
        raise MissionValidationError("Stage-3.6.8 verified completion declaration failed integrity verification")
    if not verify_completion_readiness_contract(readiness["completion_readiness_contract"]):
        raise MissionValidationError("Stage-3.6.7 completion readiness contract failed integrity verification")
    if not verify_mission_success_evaluation_contract(evaluation["mission_success_evaluation_contract"]):
        raise MissionValidationError("Stage-3.6.6 success evaluation contract failed integrity verification")
    if not verify_mission_outcome_aggregation_contract(aggregation["mission_outcome_aggregation_contract"]):
        raise MissionValidationError("Stage-3.6.5 outcome aggregation contract failed integrity verification")

    src = declaration["verified_completion_contract"]["source_bindings"]
    if declaration.get("plan_version_record_id") != active_plan.get("plan_version_record_id"):
        raise MissionValidationError("Stage-3.6.8 declaration is not bound to the active Plan")
    if src.get("readiness_id") != readiness.get("readiness_id") or src.get("readiness_sha256") != readiness.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.6.8 declaration readiness binding is inconsistent")
    if src.get("evaluation_id") != evaluation.get("evaluation_id") or src.get("evaluation_sha256") != evaluation.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.6.8 declaration evaluation binding is inconsistent")
    if src.get("aggregation_id") != aggregation.get("aggregation_id") or src.get("aggregation_sha256") != aggregation.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.6.8 declaration aggregation binding is inconsistent")
    ready_src = readiness["completion_readiness_contract"]["source_bindings"]
    eval_src = evaluation["mission_success_evaluation_contract"]["source_bindings"]
    if ready_src.get("evaluation_id") != evaluation.get("evaluation_id") or ready_src.get("evaluation_sha256") != evaluation.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.6.7 readiness does not bind the exact Stage-3.6.6 evaluation")
    if eval_src.get("aggregation_id") != aggregation.get("aggregation_id") or eval_src.get("aggregation_sha256") != aggregation.get("canonical_sha256"):
        raise MissionValidationError("Stage-3.6.6 evaluation does not bind the exact Stage-3.6.5 aggregation")

    task_lineage = _task_lineage(
        plan_version_record_id=active_plan["plan_version_record_id"],
        task_outcomes=task_outcomes,
        terminality_gates=terminality_gates,
        evidence_bindings=evidence_bindings,
        task_completions=task_completions,
    )
    agg = aggregation["mission_outcome_aggregation_contract"]["mission_outcome_aggregation"]
    if int(agg.get("task_count", -1)) != len(task_lineage) or agg.get("all_tasks_terminal") is not True or agg.get("all_tasks_verified_complete") is not True or agg.get("terminal_non_success_present") is not False:
        raise MissionValidationError("Stage-3.6.5 aggregation is not a complete verified-success outcome for the active Plan")

    core = {
        "schema_version": OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
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
            "active_plan": _ref(active_plan, "plan_version_record_id"),
            "verified_completion_declaration": _ref(declaration, "declaration_id"),
            "completion_readiness": _ref(readiness, "readiness_id"),
            "success_criteria_evaluation": _ref(evaluation, "evaluation_id"),
            "mission_outcome_aggregation": _ref(aggregation, "aggregation_id"),
            "task_lineage_count": len(task_lineage),
            "task_lineage": task_lineage,
            "outcome_event_count": int(replay["outcome_event_count"]),
            "outcome_event_tip_event_id": replay["outcome_event_tip_event_id"],
            "outcome_event_tip_sha256": replay["outcome_event_tip_sha256"],
            "outcome_replay_sha256": replay["replay_sha256"],
        },
        "recovery_state": {
            "mission_state": "COMPLETED",
            "mission_success_verified": True,
            "verified_completion_declaration_id": declaration["declaration_id"],
            "readiness_id": readiness["readiness_id"],
            "evaluation_id": evaluation["evaluation_id"],
            "aggregation_id": aggregation["aggregation_id"],
            "task_count": int(agg["task_count"]),
            "all_tasks_terminal": True,
            "all_tasks_verified_complete": True,
            "terminal_non_success_present": False,
            "success_criteria_satisfied": True,
            "completion_ready": True,
            "completion_blocker_count": 0,
            "outcome_trajectory_reconstructed": True,
        },
        "replay": {
            "schema_version": replay["schema_version"],
            "mode": replay["mode"],
            "outcome_event_count": int(replay["outcome_event_count"]),
            "outcome_event_tip_event_id": replay["outcome_event_tip_event_id"],
            "outcome_event_tip_sha256": replay["outcome_event_tip_sha256"],
            "replay_sha256": replay["replay_sha256"],
            "event_ids": [x["event_id"] for x in replay["events"]],
        },
        "semantics": {
            "lineage_mode": OUTCOME_EVENT_LINEAGE_MODE,
            "replay_mode": OUTCOME_REPLAY_MODE,
            "recovery_mode": OUTCOME_RECOVERY_MODE,
            "durable_repository_is_source_of_truth": True,
            "requires_stage368_verified_completion_declaration": True,
            "requires_completed_mission_state": True,
            "replay_read_only": True,
            "replay_is_execution": False,
            "recovery_is_execution": False,
            "recovery_is_dispatch": False,
            "recovery_is_runtime_resumption": False,
            "recovery_is_governance_authorization": False,
            "recovery_is_lifecycle_transition": False,
            "llm_reinterpretation_performed": False,
            "runtime_query_performed": False,
            "runtime_control_io_performed": False,
            "governance_query_performed": False,
            "external_network_io_performed": False,
            "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False,
            "new_target_action_dispatch_performed": False,
            "mission_state_transition_performed": False,
            "mission_success_completion_authority_exercised": False,
            "target_actuation": False,
        },
        "provenance": {
            "request_sha256": request_sha256,
            "reason": reason,
            "metadata": dict(metadata),
        },
    }
    digest = sha256_hex({"hash_domain": OUTCOME_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core})
    return {**core, "integrity": {"algorithm": "SHA-256", "hash_domain": OUTCOME_RECOVERY_CHECKPOINT_HASH_DOMAIN, "canonicalization": "UTF8_SORTED_JSON_V1", "canonical_sha256": digest}}


def verify_outcome_recovery_checkpoint_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION:
            return False
        ident = contract["identity"]
        source = contract["source_bindings"]
        recovery = contract["recovery_state"]
        replay = contract["replay"]
        semantics = contract["semantics"]
        integrity = contract["integrity"]
        core = {k: v for k, v in contract.items() if k != "integrity"}
        lineage = list(source.get("task_lineage") or [])
        refs = ("active_plan", "verified_completion_declaration", "completion_readiness", "success_criteria_evaluation", "mission_outcome_aggregation")
        return (
            str(ident.get("checkpoint_id") or "").startswith(OUTCOME_RECOVERY_CHECKPOINT_ID_PREFIX)
            and int(ident.get("checkpoint_version") or 0) >= 1
            and str(ident.get("plan_version_record_id") or "").startswith("pver-")
            and int(ident.get("plan_version") or 0) >= 1
            and source.get("state") == "COMPLETED"
            and int(source.get("state_version") or 0) >= 1
            and _SHA_RE.match(str(source.get("source_version_sha256") or "")) is not None
            and all(isinstance(source.get(k), Mapping) and _SHA_RE.match(str(source[k].get("canonical_sha256") or "")) is not None for k in refs)
            and str(source["active_plan"].get("id") or "").startswith("pver-")
            and str(source["verified_completion_declaration"].get("id") or "").startswith("mdecl-")
            and str(source["completion_readiness"].get("id") or "").startswith("mready-")
            and str(source["success_criteria_evaluation"].get("id") or "").startswith("msceval-")
            and str(source["mission_outcome_aggregation"].get("id") or "").startswith("moutcome-")
            and int(source.get("task_lineage_count") or 0) == len(lineage) and len(lineage) >= 1
            and all(str(x.get("task_outcome", {}).get("id") or "").startswith(TASK_OUTCOME_ID_PREFIX) for x in lineage)
            and all(str(x.get("terminality_eligibility", {}).get("id") or "").startswith(TASK_TERMINALITY_ID_PREFIX) for x in lineage)
            and all(str(x.get("evidence_binding", {}).get("id") or "").startswith(TASK_EVIDENCE_BINDING_ID_PREFIX) for x in lineage)
            and all(str(x.get("task_completion", {}).get("id") or "").startswith(TASK_COMPLETION_ID_PREFIX) for x in lineage)
            and int(source.get("outcome_event_count") or 0) >= 9
            and _SHA_RE.match(str(source.get("outcome_event_tip_sha256") or "")) is not None
            and _SHA_RE.match(str(source.get("outcome_replay_sha256") or "")) is not None
            and recovery.get("mission_state") == "COMPLETED"
            and recovery.get("mission_success_verified") is True
            and recovery.get("all_tasks_terminal") is True
            and recovery.get("all_tasks_verified_complete") is True
            and recovery.get("terminal_non_success_present") is False
            and recovery.get("success_criteria_satisfied") is True
            and recovery.get("completion_ready") is True
            and int(recovery.get("completion_blocker_count", -1)) == 0
            and recovery.get("outcome_trajectory_reconstructed") is True
            and replay.get("schema_version") == OUTCOME_EVENT_REPLAY_SCHEMA_VERSION
            and replay.get("mode") == OUTCOME_REPLAY_MODE
            and int(replay.get("outcome_event_count") or 0) == int(source.get("outcome_event_count") or 0)
            and replay.get("outcome_event_tip_sha256") == source.get("outcome_event_tip_sha256")
            and replay.get("replay_sha256") == source.get("outcome_replay_sha256")
            and len(replay.get("event_ids") or []) == int(source.get("outcome_event_count") or 0)
            and semantics.get("durable_repository_is_source_of_truth") is True
            and semantics.get("requires_stage368_verified_completion_declaration") is True
            and semantics.get("requires_completed_mission_state") is True
            and semantics.get("replay_read_only") is True
            and semantics.get("replay_is_execution") is False
            and semantics.get("recovery_is_execution") is False
            and semantics.get("recovery_is_dispatch") is False
            and semantics.get("recovery_is_runtime_resumption") is False
            and semantics.get("recovery_is_governance_authorization") is False
            and semantics.get("recovery_is_lifecycle_transition") is False
            and semantics.get("llm_reinterpretation_performed") is False
            and semantics.get("runtime_query_performed") is False
            and semantics.get("runtime_control_io_performed") is False
            and semantics.get("governance_query_performed") is False
            and semantics.get("external_network_io_performed") is False
            and semantics.get("dispatch_redelivery_performed") is False
            and semantics.get("new_execution_attempt_created") is False
            and semantics.get("new_target_action_dispatch_performed") is False
            and semantics.get("mission_state_transition_performed") is False
            and semantics.get("mission_success_completion_authority_exercised") is False
            and semantics.get("target_actuation") is False
            and integrity.get("hash_domain") == OUTCOME_RECOVERY_CHECKPOINT_HASH_DOMAIN
            and integrity.get("canonical_sha256") == sha256_hex({"hash_domain": OUTCOME_RECOVERY_CHECKPOINT_HASH_DOMAIN, "core": core})
        )
    except Exception:
        return False


def canonical_outcome_event_lineage_definition() -> Dict[str, Any]:
    return {
        "lineage_schema_version": OUTCOME_EVENT_LINEAGE_SCHEMA_VERSION,
        "replay_schema_version": OUTCOME_EVENT_REPLAY_SCHEMA_VERSION,
        "recovery_checkpoint_schema_version": OUTCOME_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
        "lineage_mode": OUTCOME_EVENT_LINEAGE_MODE,
        "replay_mode": OUTCOME_REPLAY_MODE,
        "recovery_mode": OUTCOME_RECOVERY_MODE,
        "checkpoint_id_prefix": OUTCOME_RECOVERY_CHECKPOINT_ID_PREFIX,
        "allowed_states": sorted(OUTCOME_RECOVERY_ALLOWED_STATES),
        "outcome_event_types": list(OUTCOME_EVENT_TYPES),
        "binds_stage361_through_stage368_evidence_chain": True,
        "requires_stage368_verified_completion_declaration": True,
        "requires_completed_mission_state": True,
        "one_immutable_checkpoint_per_verified_completion_declaration": True,
        "replay_read_only": True,
        "restart_recovery_from_durable_repository": True,
        "llm_reinterpretation_on_recovery": False,
        "runtime_query_on_recovery": False,
        "runtime_control_io_on_recovery": False,
        "governance_query_on_recovery": False,
        "external_network_io_on_recovery": False,
        "dispatch_redelivery_on_recovery": False,
        "new_execution_attempt_on_recovery": False,
        "new_target_action_dispatch_on_recovery": False,
        "mission_state_transition_on_recovery": False,
        "mission_success_completion_authority_exercised": False,
        "replay_is_execution": False,
        "recovery_is_execution": False,
        "recovery_is_dispatch": False,
        "recovery_is_runtime_resumption": False,
        "recovery_is_governance_authorization": False,
        "recovery_is_lifecycle_transition": False,
        "target_actuation": False,
        "next_stage": "3.6.10",
    }
