from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .adaptation_replan import verify_adaptation_replan_contract
from .adaptation_trigger import verify_adaptation_trigger_classification_contract
from .e2e_completion_outcome_qualification import (
    COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES,
    COMPLETION_OUTCOME_EXPECTED_NONZERO_COUNTS,
    canonical_completion_outcome_contract,
)
from .e2e_mission_acceptance import E2E_MISSION_SCENARIO_ID
from .replan_candidate import verify_replan_candidate_contract
from .replan_commit import verify_replan_commit_contract
from .replan_eligibility import verify_replan_eligibility_contract
from .replan_handoff import REPLAN_HANDOFF_NEXT_CONTROL, verify_replan_handoff_contract
from .replan_lineage import REPLAN_EVENT_TYPES
from .replan_snapshot import verify_replan_snapshot_contract
from .replan_validation import verify_replan_validation_contract

ADAPTATION_REPLANNING_SCHEMA_VERSION = "apts-stage3.9-adaptation-replanning-e2e-scenario-v1"
ADAPTATION_REPLANNING_HASH_DOMAIN = "MISSION_STAGE3_9_7_ADAPTATION_REPLANNING_E2E_SCENARIO_V1"
ADAPTATION_REPLANNING_MODE = (
    "EXISTING_STAGE3_7_1_THROUGH_3_7_8_AUTHORITIES_E2E_REPLAN_CONTINUITY_VERIFICATION"
)
ADAPTATION_REPLANNING_PREDECESSOR_CONTROL = "stage3.9.6-task-completion-mission-outcome-closure"
ADAPTATION_REPLANNING_EXPECTED_MIGRATION_LEVEL = 53
ADAPTATION_REPLANNING_NEXT_STAGE = "3.9.8"
ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES = tuple(REPLAN_EVENT_TYPES[:-1])
ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES = (
    *COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES,
    *ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES,
)
ADAPTATION_REPLANNING_EXPECTED_NONZERO_COUNTS = {
    **COMPLETION_OUTCOME_EXPECTED_NONZERO_COUNTS,
    "mission_events": len(ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES),
    "mission_plan_versions": 2,
    "mission_adaptation_replan_contracts": 1,
    "mission_adaptation_trigger_classifications": 1,
    "mission_replan_eligibility_governance_gates": 1,
    "mission_replan_snapshots": 1,
    "mission_replan_candidates": 1,
    "mission_replan_decisions": 1,
    "mission_replan_commits": 1,
    "mission_replan_handoffs": 1,
}


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_adaptation_replanning_contract() -> dict[str, Any]:
    predecessor = canonical_completion_outcome_contract()
    core = {
        "schema_version": ADAPTATION_REPLANNING_SCHEMA_VERSION,
        "mode": ADAPTATION_REPLANNING_MODE,
        "predecessor_control": ADAPTATION_REPLANNING_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": predecessor["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": ADAPTATION_REPLANNING_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "persistence_mode": "EXISTING_STAGE3_7_STORES_ONLY",
        "existing_authority_sequence": [
            "STAGE3_7_1_ADAPTATION_TRIGGER_CONTRACT",
            "STAGE3_7_2_TRIGGER_CLASSIFICATION",
            "STAGE3_7_3_REPLAN_ELIGIBILITY_GOVERNANCE_GATE",
            "STAGE3_7_4_REPLAN_SNAPSHOT_CONTEXT_BINDING",
            "STAGE3_7_5_DETERMINISTIC_REPLAN_CANDIDATE",
            "STAGE3_7_6_REPLAN_VALIDATION_FEASIBILITY_GATE",
            "STAGE3_7_7_AUTHORITATIVE_REPLAN_COMMIT",
            "STAGE3_7_8_ATOMIC_SUPERSESSION_HANDOFF",
        ],
        "trigger_semantics": {
            "trigger_source": "MISSION_EVENT",
            "trigger_code": "EVIDENCE_CHANGE",
            "reason_code": "PLAN_STALE",
            "severity": "MEDIUM",
            "source_stage": "STAGE3_6_OUTCOME_COMPLETION",
            "replan_scope_level": "LEVEL_3_PARTIAL_PLAN",
            "source_event": "MISSION_COMPLETION_READINESS_EVALUATED",
        },
        "qualified_segment_head": {
            "state": "RUNNING",
            "state_version": 4,
            "predecessor_plan_version": 1,
            "successor_plan_version": 2,
            "active_plan_version": 2,
            "completed_source_task_key": "collect-cti",
            "successor_task_keys": ["analyze-cti", "report-findings"],
            "candidate_task_count": 2,
            "candidate_dependency_edge_count": 1,
            "satisfied_predecessor_count": 1,
            "eligibility_status": "ELIGIBLE",
            "validation_status": "VALIDATED_FOR_COMMIT",
            "commit_status": "COMMITTED_SUCCESSOR_PLAN",
            "handoff_status": "HANDOFF_READY",
            "next_control": REPLAN_HANDOFF_NEXT_CONTROL,
            "replan_event_count": len(ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES),
            "recovery_checkpoint_performed": False,
        },
        "expected_event_types": list(ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES),
        "expected_replan_event_types": list(ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(ADAPTATION_REPLANNING_EXPECTED_NONZERO_COUNTS),
        "continuity_requirements": {
            "blocked_stage3_9_6_readiness_is_bound_as_trigger_source": True,
            "replan_requires_authoritative_governance_allow": True,
            "replan_snapshot_is_immutable_planning_input": True,
            "completed_source_task_is_not_regenerated": True,
            "unfinished_remainder_dag_is_retained_deterministically": True,
            "validated_candidate_precedes_authoritative_commit": True,
            "successor_plan_v2_is_materialized_atomically": True,
            "predecessor_plan_v1_remains_historical_and_effectively_superseded": True,
            "handoff_stops_before_new_routing_dispatch_execution": True,
            "stage3_7_9_recovery_checkpoint_is_reserved_for_stage3_9_8": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True,
            "governance_query_performed_by_verifier": False,
            "planner_invocation_performed_by_verifier": False,
            "replan_commit_performed_by_verifier": False,
            "routing_performed_after_handoff": False,
            "dispatch_performed_after_handoff": False,
            "new_execution_attempt_created_after_handoff": False,
            "mission_state_transition_performed_by_replan": False,
            "target_actuation": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "new_replan_authority_added": False,
        },
        "next_stage": ADAPTATION_REPLANNING_NEXT_STAGE,
    }
    return {
        **core,
        "integrity": {
            "hash_domain": ADAPTATION_REPLANNING_HASH_DOMAIN,
            "canonical_sha256": _sha({"hash_domain": ADAPTATION_REPLANNING_HASH_DOMAIN, "core": core}),
        },
    }


def verify_adaptation_replanning_contract(contract: Mapping[str, Any]) -> bool:
    try:
        return dict(contract) == canonical_adaptation_replanning_contract()
    except Exception:
        return False


def canonical_adaptation_replanning_definition() -> dict[str, Any]:
    contract = canonical_adaptation_replanning_contract()
    return {
        "schema_version": ADAPTATION_REPLANNING_SCHEMA_VERSION,
        "mode": ADAPTATION_REPLANNING_MODE,
        "predecessor_control": ADAPTATION_REPLANNING_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": ADAPTATION_REPLANNING_EXPECTED_MIGRATION_LEVEL,
        "runtime_verifier_read_only": True,
        "authoritative_governance_required": True,
        "successor_plan_version_expected": 2,
        "handoff_next_control": REPLAN_HANDOFF_NEXT_CONTROL,
        "stage3_7_9_recovery_checkpoint_expected": False,
        "new_database_migration_added": False,
        "new_durable_store_added": False,
        "new_replan_authority_added": False,
        "next_stage": ADAPTATION_REPLANNING_NEXT_STAGE,
    }


def _one(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return rows[0] if len(rows) == 1 else {}


def _valid(row: Mapping[str, Any], field: str, verifier: Any) -> bool:
    contract = row.get(field)
    if not isinstance(contract, Mapping) or not verifier(contract):
        return False
    digest = contract.get("canonical_sha256") or contract.get("integrity", {}).get("canonical_sha256")
    return row.get("canonical_sha256") == digest


def evaluate_adaptation_replanning_qualification(
    *, mission_id: str, state: Mapping[str, Any], active_plan: Mapping[str, Any] | None,
    plan_versions: Sequence[Mapping[str, Any]], predecessor_qualification: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]], repository_counts: Mapping[str, int],
    event_integrity_status: str, repository_integrity_status: str,
    adaptations: Sequence[Mapping[str, Any]], classifications: Sequence[Mapping[str, Any]],
    eligibility_gates: Sequence[Mapping[str, Any]], snapshots: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]], validations: Sequence[Mapping[str, Any]],
    commits: Sequence[Mapping[str, Any]], handoffs: Sequence[Mapping[str, Any]],
    recovery_checkpoints: Sequence[Mapping[str, Any]], replan_replay: Mapping[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def check(check_id: str, ok: bool) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if ok else "FAIL"})

    adaptation = _one(adaptations); classification = _one(classifications)
    eligibility = _one(eligibility_gates); snapshot = _one(snapshots); candidate = _one(candidates)
    validation = _one(validations); commit = _one(commits); handoff = _one(handoffs)

    check("STAGE3_9_6_PREDECESSOR_QUALIFIED", predecessor_qualification.get("qualified") is True)
    check("MISSION_AND_REPOSITORY_INTEGRITY", event_integrity_status == "PASS" and repository_integrity_status == "PASS")
    check("EXACT_EVENT_TRAJECTORY", [x.get("event_type") for x in events] == list(ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES))
    check("EXACT_NONZERO_REPOSITORY_FOOTPRINT", {k: v for k, v in repository_counts.items() if int(v)} == ADAPTATION_REPLANNING_EXPECTED_NONZERO_COUNTS)
    check("EXACT_SINGLE_ARTIFACT_CARDINALITY", all(len(rows) == 1 for rows in (
        adaptations, classifications, eligibility_gates, snapshots, candidates, validations, commits, handoffs,
    )) and len(recovery_checkpoints) == 0)
    check("CANONICAL_REPLAN_ARTIFACT_INTEGRITY", all((
        _valid(adaptation, "adaptation_replan_contract", verify_adaptation_replan_contract),
        _valid(classification, "adaptation_trigger_classification_contract", verify_adaptation_trigger_classification_contract),
        _valid(eligibility, "replan_eligibility_governance_contract", verify_replan_eligibility_contract),
        _valid(snapshot, "replan_snapshot_contract", verify_replan_snapshot_contract),
        _valid(candidate, "replan_candidate_contract", verify_replan_candidate_contract),
        _valid(validation, "replan_validation_contract", verify_replan_validation_contract),
        _valid(commit, "replan_commit_contract", verify_replan_commit_contract),
        _valid(handoff, "replan_handoff_contract", verify_replan_handoff_contract),
    )))

    predecessor_terminal_event = events[len(COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES) - 1] if len(events) >= len(COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES) else {}
    check("BLOCKED_COMPLETION_EVENT_BINDS_ADAPTATION_TRIGGER", bool(
        predecessor_terminal_event.get("event_type") == "MISSION_COMPLETION_READINESS_EVALUATED"
        and adaptation.get("source_event_id") == predecessor_terminal_event.get("event_id")
        and adaptation.get("source_event_sha256") == predecessor_terminal_event.get("canonical_sha256")
        and adaptation.get("trigger_source") == "MISSION_EVENT"
        and adaptation.get("trigger_code") == "EVIDENCE_CHANGE"
        and int(adaptation.get("source_plan_version") or 0) == 1
        and int(adaptation.get("target_plan_generation") or 0) == 2
    ))
    check("TRIGGER_CLASSIFIES_TO_LEVEL3_PARTIAL_PLAN", bool(
        classification.get("reason_code") == "PLAN_STALE"
        and classification.get("severity") == "MEDIUM"
        and classification.get("source_stage") == "STAGE3_6_OUTCOME_COMPLETION"
        and classification.get("replan_scope_level") == "LEVEL_3_PARTIAL_PLAN"
        and classification.get("classification_status") == "CLASSIFIED"
    ))
    decision = eligibility.get("replan_eligibility_governance_contract", {}).get("governance_decision", {})
    check("AUTHORITATIVE_REPLAN_ELIGIBILITY_ALLOW", bool(
        eligibility.get("eligibility_status") == "ELIGIBLE" and eligibility.get("replan_eligible") is True
        and eligibility.get("static_eligibility_status") == "PASSED"
        and decision.get("decision") == "ALLOW" and decision.get("requires_human_approval") is False
        and eligibility.get("policy_decision_hash") == decision.get("decision_hash")
    ))
    task_ctx = snapshot.get("replan_snapshot_contract", {}).get("task_dependency_outcome_context", {})
    completed = task_ctx.get("task_completions") or []
    check("IMMUTABLE_SNAPSHOT_BINDS_COMPLETED_ROOT_AND_SOURCE_PLAN", bool(
        snapshot.get("snapshot_status") == "SNAPSHOT_BOUND"
        and int(snapshot.get("source_plan_version") or 0) == 1
        and int(snapshot.get("target_plan_generation") or 0) == 2
        and int(task_ctx.get("task_count") or 0) == 3
        and int(task_ctx.get("task_completion_count") or 0) == 1
        and len(completed) == 1
        and completed[0].get("planned_task_id") == next((x.get("planned_task_id") for x in (task_ctx.get("tasks") or []) if x.get("task_key") == "collect-cti"), None)
    ))
    cand = candidate.get("replan_candidate_contract", {}).get("candidate_successor_plan", {})
    cand_tasks = cand.get("candidate_tasks") or []
    check("DETERMINISTIC_REMAINDER_DAG_CANDIDATE", bool(
        candidate.get("candidate_status") == "CANDIDATE_GENERATED"
        and int(cand.get("candidate_plan_version") or 0) == 2
        and int(cand.get("candidate_task_count") or 0) == 2
        and [x.get("task_key") for x in cand_tasks] == ["analyze-cti", "report-findings"]
        and int(cand.get("completed_source_task_count") or 0) == 1
        and int(cand.get("candidate_dependency_edge_count") or 0) == 1
        and int(cand.get("satisfied_predecessor_count") or 0) == 1
        and cand.get("planning_strategy") == "RETAIN_UNFINISHED_SOURCE_TASKS_PRESERVE_REMAINING_DAG_V1"
    ))
    check("CANDIDATE_VALIDATED_BEFORE_COMMIT", bool(
        validation.get("validation_status") == "VALIDATED_FOR_COMMIT" and validation.get("feasible") is True
        and int(validation.get("failed_check_count") or 0) == 0
        and validation.get("replan_candidate_id") == candidate.get("replan_candidate_id")
    ))
    plans_by_version = {int(x.get("plan_version") or 0): x for x in plan_versions}
    predecessor_plan = plans_by_version.get(1, {}); successor_plan = plans_by_version.get(2, {})
    plan_integrity = bool(
        predecessor_plan and successor_plan
        and predecessor_plan.get("canonical_sha256") == commit.get("source_plan_sha256")
        and successor_plan.get("canonical_sha256") == commit.get("successor_plan_sha256")
        and successor_plan.get("predecessor_plan_version_record_id") == predecessor_plan.get("plan_version_record_id")
    )
    check("AUTHORITATIVE_COMMIT_MATERIALIZES_ATOMIC_SUCCESSOR_V2", bool(
        commit.get("commit_status") == "COMMITTED_SUCCESSOR_PLAN"
        and int(commit.get("predecessor_plan_version") or 0) == 1
        and int(commit.get("successor_plan_version") or 0) == 2
        and commit.get("governance_decision") == "ALLOW"
        and predecessor_plan.get("effective_status") == "SUPERSEDED"
        and successor_plan.get("effective_status") == "ACTIVE"
        and plan_integrity
        and (active_plan or {}).get("plan_version_record_id") == successor_plan.get("plan_version_record_id")
        and int((active_plan or {}).get("plan_version") or 0) == 2
    ))
    task_handoff = handoff.get("replan_handoff_contract", {}).get("task_handoff", {})
    successor_handoff = handoff.get("replan_handoff_contract", {}).get("successor_handoff", {})
    dispositions = task_handoff.get("dispositions") or []
    check("HANDOFF_READY_STOPS_BEFORE_SUCCESSOR_ROUTING_OR_DISPATCH", bool(
        handoff.get("handoff_status") == "HANDOFF_READY"
        and successor_handoff.get("next_control") == REPLAN_HANDOFF_NEXT_CONTROL
        and int(handoff.get("task_disposition_count") or 0) == 3
        and int(handoff.get("keep_count") or 0) == 3
        and all(x.get("disposition") == "KEEP" for x in dispositions)
        and task_handoff.get("cancellation_io_performed") is False
        and successor_handoff.get("routing_performed") is False
        and successor_handoff.get("dispatch_performed") is False
        and successor_handoff.get("execution_attempt_created") is False
    ))
    replay_events = replan_replay.get("events") or []
    check("REPLAN_EVENT_REPLAY_PRECHECKPOINT_IS_EXACT", bool(
        replan_replay.get("read_only") is True and replan_replay.get("side_effects_performed") is False
        and int(replan_replay.get("replan_event_count") or 0) == len(ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES)
        and [x.get("event_type") for x in replay_events] == list(ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES)
        and len(recovery_checkpoints) == 0
    ))
    check("MISSION_REMAINS_RUNNING_FOR_STAGE398_RECOVERY", bool(
        state.get("state") == "RUNNING" and int(state.get("state_version") or 0) == 4
        and state.get("terminal") is False and len(recovery_checkpoints) == 0
    ))

    contract = canonical_adaptation_replanning_contract()
    failures = [x["check_id"] for x in checks if x["status"] != "PASS"]
    return {
        "schema_version": ADAPTATION_REPLANNING_SCHEMA_VERSION,
        "segment": "ADAPTATION_REPLANNING_E2E_SCENARIO",
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "qualification_contract_sha256": contract["integrity"]["canonical_sha256"],
        "mission_id": mission_id,
        "status": "QUALIFIED" if not failures else "REJECTED",
        "qualified": not failures,
        "failed_check_ids": failures,
        "checks": checks,
        "segment_head": {
            "state": state.get("state"), "state_version": state.get("state_version"),
            "predecessor_plan_version": commit.get("predecessor_plan_version"),
            "successor_plan_version": commit.get("successor_plan_version"),
            "active_plan_version": (active_plan or {}).get("plan_version"),
            "adaptation_episode_id": adaptation.get("adaptation_episode_id"),
            "classification_id": classification.get("classification_id"),
            "eligibility_gate_id": eligibility.get("eligibility_gate_id"),
            "replan_snapshot_id": snapshot.get("replan_snapshot_id"),
            "replan_candidate_id": candidate.get("replan_candidate_id"),
            "replan_validation_id": validation.get("replan_validation_id"),
            "replan_commit_id": commit.get("replan_commit_id"),
            "replan_handoff_id": handoff.get("replan_handoff_id"),
            "handoff_status": handoff.get("handoff_status"),
            "next_control": successor_handoff.get("next_control"),
            "candidate_task_keys": [x.get("task_key") for x in cand_tasks],
            "replan_event_count": replan_replay.get("replan_event_count"),
            "event_count": len(events),
        },
        "authority_boundary": {
            "verification_read_only": True,
            "governance_query_performed_by_verifier": False,
            "planner_invocation_performed_by_verifier": False,
            "replan_commit_performed_by_verifier": False,
            "recovery_checkpoint_performed": False,
            "routing_performed_after_handoff": False,
            "dispatch_performed_after_handoff": False,
            "new_execution_attempt_created_after_handoff": False,
            "mission_state_transition_performed_by_replan": False,
            "target_actuation": False,
        },
    }
