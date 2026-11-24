from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .completion_readiness import verify_completion_readiness_contract
from .e2e_dispatch_execution_evidence_qualification import (
    DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES,
    DISPATCH_EXECUTION_EVIDENCE_EXPECTED_NONZERO_COUNTS,
    canonical_dispatch_execution_evidence_contract,
)
from .e2e_mission_acceptance import E2E_MISSION_SCENARIO_ID
from .execution_lineage import verify_execution_recovery_checkpoint_contract
from .execution_termination import verify_outcome_propagation_contract
from .mission_outcome_aggregation import verify_mission_outcome_aggregation_contract
from .mission_success_evaluation import verify_mission_success_evaluation_contract
from .task_completion import verify_task_completion_contract
from .task_evidence_binding import verify_task_evidence_binding_verification_contract
from .task_outcome import verify_task_outcome_contract
from .task_terminality import verify_task_terminality_eligibility_contract

COMPLETION_OUTCOME_SCHEMA_VERSION = "apts-stage3.9-task-completion-mission-outcome-closure-v1"
COMPLETION_OUTCOME_HASH_DOMAIN = "MISSION_STAGE3_9_6_TASK_COMPLETION_MISSION_OUTCOME_CLOSURE_V1"
COMPLETION_OUTCOME_MODE = "EXISTING_STAGE3_5_8_3_5_9_AND_STAGE3_6_1_THROUGH_3_6_7_AUTHORITIES_READ_ONLY_CONTINUITY_VERIFICATION"
COMPLETION_OUTCOME_PREDECESSOR_CONTROL = "stage3.9.5-dispatch-execution-evidence-continuity"
COMPLETION_OUTCOME_EXPECTED_MIGRATION_LEVEL = 53
COMPLETION_OUTCOME_NEXT_STAGE = "3.9.7"
COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES = (
    *DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES,
    "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED",
    "MISSION_EXECUTION_RECOVERY_CHECKPOINTED",
    "MISSION_TASK_OUTCOME_MATERIALIZED",
    "MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED",
    "MISSION_TASK_EVIDENCE_BINDING_VERIFIED",
    "MISSION_TASK_COMPLETION_COMMITTED",
    "MISSION_OUTCOME_AGGREGATED",
    "MISSION_SUCCESS_CRITERIA_EVALUATED",
    "MISSION_COMPLETION_READINESS_EVALUATED",
)
COMPLETION_OUTCOME_EXPECTED_NONZERO_COUNTS = {
    **DISPATCH_EXECUTION_EVIDENCE_EXPECTED_NONZERO_COUNTS,
    "mission_events": len(COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES),
    "mission_execution_outcome_propagations": 1,
    "mission_execution_recovery_checkpoints": 1,
    "mission_task_outcomes": 1,
    "mission_task_terminality_eligibility_gates": 1,
    "mission_task_evidence_binding_verifications": 1,
    "mission_task_completion_commits": 1,
    "mission_outcome_aggregations": 1,
    "mission_success_criteria_evaluations": 1,
    "mission_completion_readiness_decisions": 1,
}


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_completion_outcome_contract() -> dict[str, Any]:
    predecessor = canonical_dispatch_execution_evidence_contract()
    core = {
        "schema_version": COMPLETION_OUTCOME_SCHEMA_VERSION,
        "mode": COMPLETION_OUTCOME_MODE,
        "predecessor_control": COMPLETION_OUTCOME_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": predecessor["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": COMPLETION_OUTCOME_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "persistence_mode": "EXISTING_STAGE3_1_THROUGH_STAGE3_6_STORES_ONLY",
        "existing_authority_sequence": [
            "STAGE3_5_8_TERMINAL_OUTCOME_PROPAGATION",
            "STAGE3_5_9_EXECUTION_RECOVERY_CHECKPOINT",
            "STAGE3_6_1_TASK_OUTCOME_IDENTITY",
            "STAGE3_6_2_TERMINALITY_COMPLETION_ELIGIBILITY",
            "STAGE3_6_3_EVIDENCE_BINDING_VERIFICATION",
            "STAGE3_6_4_DEPENDENCY_AWARE_TASK_COMPLETION",
            "STAGE3_6_5_MISSION_OUTCOME_AGGREGATION",
            "STAGE3_6_6_MISSION_SUCCESS_CRITERIA_EVALUATION",
            "STAGE3_6_7_COMPLETION_READINESS_BLOCKERS",
        ],
        "qualified_segment_head": {
            "state": "RUNNING",
            "state_version": 4,
            "active_plan_version": 1,
            "completed_task_key": "collect-cti",
            "remaining_task_keys": ["analyze-cti", "report-findings"],
            "task_completion_status": "COMPLETED_DEPENDENCY_CONSISTENT",
            "all_tasks_terminal": False,
            "all_tasks_verified_complete": False,
            "terminal_non_success_present": False,
            "success_criteria_result": "SUCCESS_CRITERIA_NOT_SATISFIED",
            "completion_readiness_result": "BLOCKED",
            "completion_blocker_count": 2,
            "verified_completion_performed": False,
            "mission_lifecycle_completion_performed": False,
            "adaptation_replan_handoff_required": True,
        },
        "expected_event_types": list(COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(COMPLETION_OUTCOME_EXPECTED_NONZERO_COUNTS),
        "continuity_requirements": {
            "terminal_success_is_propagated_before_task_outcome_materialization": True,
            "execution_recovery_checkpoint_is_bound_before_task_outcome_materialization": True,
            "terminality_and_evidence_binding_precede_task_completion": True,
            "task_completion_is_dependency_aware": True,
            "mission_outcome_aggregation_follows_task_completion": True,
            "success_criteria_evaluation_follows_aggregation": True,
            "completion_readiness_fails_closed_when_active_plan_tasks_remain": True,
            "blocked_readiness_does_not_invoke_verified_completion": True,
            "mission_remains_nonterminal_for_stage3_9_7_adaptation_replanning": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True,
            "governance_query_performed": False,
            "runtime_io_performed": False,
            "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False,
            "verified_completion_performed": False,
            "mission_state_transition_performed": False,
            "target_actuation": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "new_governance_authority_added": False,
            "new_dispatch_authority_added": False,
            "new_execution_authority_added": False,
            "new_completion_authority_added": False,
        },
        "next_stage": COMPLETION_OUTCOME_NEXT_STAGE,
    }
    return {**core, "integrity": {"hash_domain": COMPLETION_OUTCOME_HASH_DOMAIN, "canonical_sha256": _sha({"hash_domain": COMPLETION_OUTCOME_HASH_DOMAIN, "core": core})}}


def verify_completion_outcome_contract(contract: Mapping[str, Any]) -> bool:
    try:
        return dict(contract) == canonical_completion_outcome_contract()
    except Exception:
        return False


def canonical_completion_outcome_definition() -> dict[str, Any]:
    contract = canonical_completion_outcome_contract()
    return {
        "schema_version": COMPLETION_OUTCOME_SCHEMA_VERSION,
        "mode": COMPLETION_OUTCOME_MODE,
        "predecessor_control": COMPLETION_OUTCOME_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": COMPLETION_OUTCOME_EXPECTED_MIGRATION_LEVEL,
        "runtime_verifier_read_only": True,
        "verified_completion_expected": False,
        "blocked_readiness_expected": True,
        "adaptation_replan_handoff_required": True,
        "new_database_migration_added": False,
        "new_durable_store_added": False,
        "new_completion_authority_added": False,
        "next_stage": COMPLETION_OUTCOME_NEXT_STAGE,
    }


def _one(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return rows[0] if len(rows) == 1 else {}


def _valid(row: Mapping[str, Any], field: str, verifier: Any) -> bool:
    contract = row.get(field)
    if not isinstance(contract, Mapping) or not verifier(contract):
        return False
    digest = contract.get("canonical_sha256") or contract.get("integrity", {}).get("canonical_sha256")
    return row.get("canonical_sha256") == digest


def evaluate_completion_outcome_qualification(
    *, mission_id: str, state: Mapping[str, Any], active_plan: Mapping[str, Any] | None,
    predecessor_qualification: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
    repository_counts: Mapping[str, int], event_integrity_status: str, repository_integrity_status: str,
    outcome_propagations: Sequence[Mapping[str, Any]], execution_recovery_checkpoints: Sequence[Mapping[str, Any]],
    task_outcomes: Sequence[Mapping[str, Any]], terminality_gates: Sequence[Mapping[str, Any]],
    evidence_bindings: Sequence[Mapping[str, Any]], task_completions: Sequence[Mapping[str, Any]],
    aggregations: Sequence[Mapping[str, Any]], evaluations: Sequence[Mapping[str, Any]],
    readiness_decisions: Sequence[Mapping[str, Any]], verified_completion_declarations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    def check(check_id: str, ok: bool) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if ok else "FAIL"})

    prop = _one(outcome_propagations); checkpoint = _one(execution_recovery_checkpoints)
    outcome = _one(task_outcomes); gate = _one(terminality_gates); binding = _one(evidence_bindings)
    completion = _one(task_completions); aggregation = _one(aggregations); evaluation = _one(evaluations)
    readiness = _one(readiness_decisions)

    check("STAGE3_9_5_PREDECESSOR_QUALIFIED", predecessor_qualification.get("qualified") is True)
    check("MISSION_AND_REPOSITORY_INTEGRITY", event_integrity_status == "PASS" and repository_integrity_status == "PASS")
    check("EXACT_EVENT_TRAJECTORY", [x.get("event_type") for x in events] == list(COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES))
    check("EXACT_NONZERO_REPOSITORY_FOOTPRINT", {k: v for k, v in repository_counts.items() if int(v)} == COMPLETION_OUTCOME_EXPECTED_NONZERO_COUNTS)
    check("EXACT_SINGLE_ARTIFACT_CARDINALITY", all(len(rows) == 1 for rows in (
        outcome_propagations, execution_recovery_checkpoints, task_outcomes, terminality_gates,
        evidence_bindings, task_completions, aggregations, evaluations, readiness_decisions,
    )) and len(verified_completion_declarations) == 0)
    check("CANONICAL_OUTCOME_ARTIFACT_INTEGRITY", all((
        _valid(prop, "outcome_propagation_contract", verify_outcome_propagation_contract),
        _valid(checkpoint, "recovery_checkpoint", verify_execution_recovery_checkpoint_contract),
        _valid(outcome, "task_outcome_contract", verify_task_outcome_contract),
        _valid(gate, "task_terminality_eligibility_contract", verify_task_terminality_eligibility_contract),
        _valid(binding, "task_evidence_binding_verification_contract", verify_task_evidence_binding_verification_contract),
        _valid(completion, "task_completion_contract", verify_task_completion_contract),
        _valid(aggregation, "mission_outcome_aggregation_contract", verify_mission_outcome_aggregation_contract),
        _valid(evaluation, "mission_success_evaluation_contract", verify_mission_success_evaluation_contract),
        _valid(readiness, "completion_readiness_contract", verify_completion_readiness_contract),
    )))
    active_id = (active_plan or {}).get("plan_version_record_id")
    task_id = outcome.get("planned_task_id")
    check("EXECUTION_TERMINAL_SUCCESS_AND_RECOVERY_BOUND", bool(
        prop.get("mission_id") == mission_id and prop.get("plan_version_record_id") == active_id
        and prop.get("task_key") == "collect-cti" and prop.get("execution_state") == "SUCCEEDED"
        and prop.get("task_outcome_status") == "VERIFIED_COMPLETED" and prop.get("outcome_classification") == "VERIFIED_SUCCESS"
        and checkpoint.get("outcome_propagation_id") == prop.get("outcome_propagation_id")
        and checkpoint.get("planned_task_id") == task_id and checkpoint.get("result_capture_id") == prop.get("result_capture_id")
    ))
    check("TASK_OUTCOME_TERMINALITY_EVIDENCE_COMPLETION_CHAIN", bool(
        outcome.get("execution_recovery_checkpoint_id") == checkpoint.get("checkpoint_id")
        and outcome.get("outcome_propagation_id") == prop.get("outcome_propagation_id")
        and outcome.get("source_task_outcome_status") == "VERIFIED_COMPLETED"
        and outcome.get("outcome_classification") == "VERIFIED_SUCCESS"
        and gate.get("task_outcome_id") == outcome.get("task_outcome_id") and gate.get("completion_eligible") is True
        and binding.get("task_outcome_id") == outcome.get("task_outcome_id") and binding.get("eligibility_gate_id") == gate.get("eligibility_gate_id")
        and binding.get("verification_status") == "VERIFIED"
        and completion.get("task_outcome_id") == outcome.get("task_outcome_id")
        and completion.get("evidence_binding_verification_id") == binding.get("verification_id")
        and completion.get("completion_status") == "COMPLETED_DEPENDENCY_CONSISTENT"
        and completion.get("task_completion_committed") is True
    ))
    check("MISSION_OUTCOME_AGGREGATES_ACTIVE_PLAN_WITH_REMAINING_TASKS", bool(
        aggregation.get("mission_id") == mission_id and aggregation.get("plan_version_record_id") == active_id
        and aggregation.get("task_count") == 3 and aggregation.get("verified_complete_count") == 1
        and aggregation.get("terminal_task_count") == 1 and aggregation.get("pending_count") == 1 and aggregation.get("blocked_count") == 1
        and aggregation.get("all_tasks_terminal") is False and aggregation.get("all_tasks_verified_complete") is False
        and aggregation.get("failed_count") == 0 and aggregation.get("cancelled_count") == 0 and aggregation.get("timed_out_count") == 0
    ))
    check("SUCCESS_CRITERIA_FAIL_CLOSED_NOT_SATISFIED", bool(
        evaluation.get("aggregation_id") == aggregation.get("aggregation_id")
        and evaluation.get("overall_result") == "SUCCESS_CRITERIA_NOT_SATISFIED"
        and evaluation.get("criterion_count") == 2 and evaluation.get("satisfied_count") == 1
        and evaluation.get("not_satisfied_count") == 1 and evaluation.get("indeterminate_count") == 0
    ))
    blocker_codes = [x.get("code") for x in readiness.get("completion_readiness_contract", {}).get("completion_readiness", {}).get("blockers", [])]
    check("COMPLETION_READINESS_BLOCKED_WITH_CANONICAL_BLOCKERS", bool(
        readiness.get("evaluation_id") == evaluation.get("evaluation_id")
        and readiness.get("readiness_result") == "BLOCKED" and readiness.get("completion_ready") is False
        and readiness.get("blocker_count") == 2
        and blocker_codes == ["SUCCESS_CRITERIA_NOT_SATISFIED", "TASKS_NOT_ALL_VERIFIED_COMPLETE"]
    ))
    check("NO_PREMATURE_VERIFIED_COMPLETION_OR_LIFECYCLE_CLOSURE", bool(
        state.get("state") == "RUNNING" and int(state.get("state_version") or 0) == 4
        and len(verified_completion_declarations) == 0
        and int(repository_counts.get("mission_verified_completion_declarations", 0)) == 0
        and int(repository_counts.get("mission_outcome_recovery_checkpoints", 0)) == 0
    ))
    check("ADAPTATION_REPLAN_HANDOFF_IS_NONTERMINAL", state.get("terminal") is False and readiness.get("readiness_result") == "BLOCKED")

    contract = canonical_completion_outcome_contract()
    failures = [x["check_id"] for x in checks if x["status"] != "PASS"]
    return {
        "schema_version": COMPLETION_OUTCOME_SCHEMA_VERSION,
        "segment": "TASK_COMPLETION_TO_MISSION_OUTCOME_CLOSURE",
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
            "active_plan_version": (active_plan or {}).get("plan_version"),
            "planned_task_id": task_id, "task_key": outcome.get("task_key"),
            "outcome_propagation_id": prop.get("outcome_propagation_id"),
            "execution_recovery_checkpoint_id": checkpoint.get("checkpoint_id"),
            "task_outcome_id": outcome.get("task_outcome_id"), "eligibility_gate_id": gate.get("eligibility_gate_id"),
            "evidence_binding_verification_id": binding.get("verification_id"), "task_completion_id": completion.get("task_completion_id"),
            "aggregation_id": aggregation.get("aggregation_id"), "evaluation_id": evaluation.get("evaluation_id"),
            "readiness_id": readiness.get("readiness_id"), "readiness_result": readiness.get("readiness_result"),
            "blocker_count": readiness.get("blocker_count"), "all_tasks_terminal": aggregation.get("all_tasks_terminal"),
            "all_tasks_verified_complete": aggregation.get("all_tasks_verified_complete"), "event_count": len(events),
        },
        "authority_boundary": {
            "verification_read_only": True, "governance_query_performed": False, "runtime_io_performed": False,
            "dispatch_redelivery_performed": False, "new_execution_attempt_created": False,
            "verified_completion_performed": False, "mission_state_transition_performed": False, "target_actuation": False,
        },
    }
