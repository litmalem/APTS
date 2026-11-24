from __future__ import annotations

from typing import Any, Dict

OUTCOME_ACCEPTANCE_GATE_SCHEMA_VERSION = "apts-mission-stage3.6-outcome-acceptance-gate-v1"
OUTCOME_ACCEPTANCE_GATE_MODE = "FULL_REGRESSION_PLUS_CANONICAL_OUTCOME_INTEGRATION_AND_LIVE_COMPLETION_BOUNDARY_PROBES"
OUTCOME_ACCEPTANCE_GATE_BASELINE = "STAGE_3_6_1_THROUGH_3_6_9"
OUTCOME_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = "NO_NEW_OUTCOME_COMPLETION_AUTHORITY_RUNTIME_IO_OR_TARGET_ACTUATION"
OUTCOME_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
OUTCOME_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 44

REQUIRED_STAGE3_6_CONTROLS = (
    "stage3.6.1-canonical-task-outcome-contract-identity",
    "stage3.6.2-task-terminality-completion-eligibility",
    "stage3.6.3-evidence-binding-verification",
    "stage3.6.4-dependency-aware-task-completion",
    "stage3.6.5-mission-outcome-aggregation",
    "stage3.6.6-mission-success-criteria-evaluation",
    "stage3.6.7-completion-readiness-blockers",
    "stage3.6.8-verified-completion-declaration-lifecycle-handoff",
    "stage3.6.9-outcome-lineage-replay-recovery",
)

REQUIRED_OUTCOME_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "CANONICAL_PYTEST_INVENTORY",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_TASK_OUTCOME_CONTRACT_AND_IDENTITY",
    "TASK_TERMINALITY_AND_COMPLETION_ELIGIBILITY",
    "EVIDENCE_BINDING_VERIFICATION",
    "DEPENDENCY_AWARE_TASK_COMPLETION",
    "MISSION_OUTCOME_AGGREGATION",
    "MISSION_SUCCESS_CRITERIA_EVALUATION",
    "COMPLETION_READINESS_AND_BLOCKERS",
    "VERIFIED_COMPLETION_DECLARATION_AND_LIFECYCLE_HANDOFF",
    "OUTCOME_LINEAGE_REPLAY_AND_RECOVERY",
    "SUCCESS_AND_BLOCKED_NON_SUCCESS_TRAJECTORY_INTEGRATION",
    "RESTART_RECONSTRUCTION_WITHOUT_RUNTIME_GOVERNANCE_REDISPATCH_OR_RESUMPTION",
    "REPOSITORY_AND_EVENT_INTEGRITY",
    "FINAL_OUTCOME_COMPLETION_AUTHORITY_RUNTIME_IO_AND_ACTUATION_BOUNDARY",
)


def outcome_acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.6 closure contract.

    Stage 3.6.10 is a release/acceptance declaration only. It does not itself
    materialize a task outcome, classify terminality, verify evidence, commit a
    task completion, aggregate Mission outcome, evaluate success criteria, decide
    readiness, declare Mission success, perform lifecycle handoff, replay/recover
    work, query Governance/runtime services, dispatch or actuate a target, or add
    persistence.

    The operator-visible acceptance harness plus the full regression suite are
    the authoritative PASS/FAIL evidence for Stage 3.6.1 through Stage 3.6.9.
    """

    return {
        "schema_version": OUTCOME_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": OUTCOME_ACCEPTANCE_GATE_MODE,
        "baseline": OUTCOME_ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": OUTCOME_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": OUTCOME_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": OUTCOME_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_6_CONTROLS),
        "required_gates": list(REQUIRED_OUTCOME_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "stage36_task_outcome_boundary": "STAGE_3_6_1_CANONICAL_OUTCOME_MATERIALIZATION",
        "stage36_task_completion_boundary": "STAGE_3_6_4_DEPENDENCY_AWARE_COMPLETION_COMMIT",
        "stage36_mission_outcome_boundary": "STAGE_3_6_5_MISSION_OUTCOME_AGGREGATION",
        "stage36_success_evaluation_boundary": "STAGE_3_6_6_SUCCESS_CRITERIA_EVALUATION",
        "stage36_readiness_boundary": "STAGE_3_6_7_COMPLETION_READINESS_DECISION",
        "stage36_completion_authority_source": "STAGE_3_6_8_VERIFIED_COMPLETION_DECLARATION",
        "stage36_lifecycle_handoff_boundary": "STAGE_3_6_8_CANONICAL_STAGE3_2_LIFECYCLE_COMMAND_PATH",
        "stage36_replay_recovery_boundary": "STAGE_3_6_9_READ_ONLY_DURABLE_RECONSTRUCTION",
        "new_task_outcome_authority_added": False,
        "new_terminality_classification_authority_added": False,
        "new_evidence_verification_authority_added": False,
        "new_task_completion_authority_added": False,
        "new_mission_outcome_aggregation_added": False,
        "new_success_criteria_evaluation_added": False,
        "new_completion_readiness_decision_added": False,
        "new_mission_success_completion_authority_added": False,
        "new_lifecycle_transition_path_added": False,
        "new_governance_query_added": False,
        "new_runtime_query_added": False,
        "new_runtime_control_io_added": False,
        "new_external_network_io_added": False,
        "new_dispatch_redelivery_added": False,
        "new_execution_attempt_added": False,
        "new_target_action_dispatch_added": False,
        "new_target_actuation_added": False,
        "new_llm_reinterpretation_added": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "task_outcome_is_task_completion": False,
        "terminality_is_task_acceptance": False,
        "evidence_verification_is_task_completion": False,
        "task_completion_is_mission_completion": False,
        "aggregation_is_success_evaluation": False,
        "success_evaluation_is_completion_authority": False,
        "readiness_is_completion_authority": False,
        "verified_completion_is_mission_success_completion_authority": True,
        "verified_completion_direct_state_transition_bypass_used": False,
        "replay_is_outcome_processing": False,
        "recovery_is_completion_authority": False,
        "recovery_is_dispatch": False,
        "recovery_is_runtime_resumption": False,
        "recovery_is_lifecycle_transition": False,
        "closure_gate_is_outcome_processing": False,
        "closure_gate_is_completion_authority": False,
    }
