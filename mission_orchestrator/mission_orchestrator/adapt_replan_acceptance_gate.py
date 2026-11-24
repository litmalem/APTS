from __future__ import annotations

from typing import Any, Dict

ADAPT_REPLAN_ACCEPTANCE_GATE_SCHEMA_VERSION = "apts-mission-stage3.7-adapt-replan-acceptance-gate-v1"
ADAPT_REPLAN_ACCEPTANCE_GATE_MODE = (
    "FULL_REGRESSION_PLUS_CANONICAL_ADAPT_REPLAN_INTEGRATION_AND_LIVE_BOUNDARY_PROBES"
)
ADAPT_REPLAN_ACCEPTANCE_GATE_BASELINE = "STAGE_3_7_1_THROUGH_3_7_9"
ADAPT_REPLAN_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = (
    "NO_NEW_ADAPT_REPLAN_AUTHORITY_RUNTIME_IO_PLAN_MUTATION_OR_TARGET_ACTUATION"
)
ADAPT_REPLAN_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
ADAPT_REPLAN_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 53

REQUIRED_STAGE3_7_CONTROLS = (
    "stage3.7.1-canonical-adaptation-replan-contract-identity",
    "stage3.7.2-adaptation-trigger-detection-classification",
    "stage3.7.3-replan-eligibility-governance-gate",
    "stage3.7.4-canonical-replan-snapshot-context-binding",
    "stage3.7.5-deterministic-replan-candidate-generation",
    "stage3.7.6-replan-candidate-validation-delta-feasibility-gate",
    "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization",
    "stage3.7.8-atomic-replan-commit-supersession-handoff",
    "stage3.7.9-adapt-replan-lineage-replay-recovery",
)

REQUIRED_ADAPT_REPLAN_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "CANONICAL_PYTEST_INVENTORY",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_ADAPTATION_REPLAN_CONTRACT_AND_IDENTITY",
    "ADAPTATION_TRIGGER_DETECTION_AND_CLASSIFICATION",
    "REPLAN_ELIGIBILITY_AND_GOVERNANCE_GATE",
    "CANONICAL_REPLAN_SNAPSHOT_CONTEXT_BINDING",
    "DETERMINISTIC_REPLAN_CANDIDATE_GENERATION",
    "REPLAN_CANDIDATE_VALIDATION_AND_DELTA_FEASIBILITY",
    "AUTHORITATIVE_REPLAN_COMMIT_AND_SUCCESSOR_PLAN_MATERIALIZATION",
    "ATOMIC_REPLAN_SUPERSESSION_AND_HANDOFF",
    "ADAPT_REPLAN_LINEAGE_REPLAY_AND_RECOVERY",
    "END_TO_END_ADAPT_REPLAN_TRAJECTORY_INTEGRATION",
    "RESTART_RECONSTRUCTION_WITHOUT_PLANNER_GOVERNANCE_RUNTIME_REDISPATCH_OR_ACTUATION",
    "REPOSITORY_AND_EVENT_INTEGRITY",
    "FINAL_ADAPT_REPLAN_AUTHORITY_RUNTIME_IO_PLAN_MUTATION_AND_ACTUATION_BOUNDARY",
)


def adapt_replan_acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.7 closure contract.

    Stage 3.7.10 is a release/acceptance declaration only. It does not itself
    detect an adaptation episode, classify a trigger, authorize replanning,
    bind a snapshot, invoke the deterministic planner, validate a candidate,
    commit or supersede a Plan, create a handoff, replay/recover work, query
    Governance/runtime services, route/delegate/dispatch, mutate Mission state,
    actuate a target, or add persistence.

    The operator-visible acceptance harness plus the full regression suite are
    the authoritative PASS/FAIL evidence for Stage 3.7.1 through Stage 3.7.9.
    """

    return {
        "schema_version": ADAPT_REPLAN_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": ADAPT_REPLAN_ACCEPTANCE_GATE_MODE,
        "baseline": ADAPT_REPLAN_ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": ADAPT_REPLAN_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": ADAPT_REPLAN_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": ADAPT_REPLAN_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_7_CONTROLS),
        "required_gates": list(REQUIRED_ADAPT_REPLAN_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "stage37_detection_boundary": "STAGE_3_7_1_CANONICAL_ADAPTATION_REPLAN_EPISODE_MATERIALIZATION",
        "stage37_classification_boundary": "STAGE_3_7_2_DETERMINISTIC_TRIGGER_CLASSIFICATION",
        "stage37_eligibility_boundary": "STAGE_3_7_3_FAIL_CLOSED_ELIGIBILITY_AND_EXTERNAL_GOVERNANCE_AUTHORIZATION",
        "stage37_snapshot_boundary": "STAGE_3_7_4_CANONICAL_DURABLE_CONTEXT_SNAPSHOT",
        "stage37_candidate_boundary": "STAGE_3_7_5_DETERMINISTIC_LOCAL_REPLAN_CANDIDATE_GENERATION",
        "stage37_validation_boundary": "STAGE_3_7_6_DELTA_FEASIBILITY_VALIDATION",
        "stage37_commit_authority_source": "STAGE_3_7_7_AUTHORITATIVE_GOVERNANCE_REVALIDATION_AND_SUCCESSOR_PLAN_MATERIALIZATION",
        "stage37_handoff_authority_source": "STAGE_3_7_8_ATOMIC_SUPERSESSION_HANDOFF_READY",
        "stage37_replay_recovery_boundary": "STAGE_3_7_9_READ_ONLY_DURABLE_RECONSTRUCTION",
        "new_adaptation_episode_authority_added": False,
        "new_trigger_classification_authority_added": False,
        "new_replan_eligibility_authority_added": False,
        "new_snapshot_binding_authority_added": False,
        "new_candidate_generation_authority_added": False,
        "new_validation_authority_added": False,
        "new_commit_authority_added": False,
        "new_plan_supersession_authority_added": False,
        "new_handoff_authority_added": False,
        "new_recovery_authority_added": False,
        "new_governance_query_added": False,
        "new_runtime_query_added": False,
        "new_runtime_control_io_added": False,
        "new_external_context_refresh_added": False,
        "new_external_network_io_added": False,
        "new_cancellation_io_added": False,
        "new_routing_added": False,
        "new_delegation_added": False,
        "new_dispatch_added": False,
        "new_execution_attempt_added": False,
        "new_mission_state_transition_added": False,
        "new_historical_plan_mutation_added": False,
        "new_active_plan_head_cas_added": False,
        "new_target_action_dispatch_added": False,
        "new_target_actuation_added": False,
        "new_llm_reinterpretation_added": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "stage377_is_successor_plan_commit_authority": True,
        "stage378_is_handoff_authority": True,
        "stage379_replay_is_replan_processing": False,
        "stage379_recovery_is_replan_execution": False,
        "stage379_recovery_is_dispatch": False,
        "stage379_recovery_is_runtime_resumption": False,
        "stage379_recovery_is_lifecycle_transition": False,
        "closure_gate_is_adaptation_detection": False,
        "closure_gate_is_trigger_classification": False,
        "closure_gate_is_replan_eligibility_authority": False,
        "closure_gate_is_snapshot_binding": False,
        "closure_gate_is_candidate_generation": False,
        "closure_gate_is_candidate_validation": False,
        "closure_gate_is_plan_commit": False,
        "closure_gate_is_plan_supersession": False,
        "closure_gate_is_handoff": False,
        "closure_gate_is_recovery": False,
    }
