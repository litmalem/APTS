from __future__ import annotations

from typing import Any, Dict

PLANNING_ACCEPTANCE_GATE_SCHEMA_VERSION = "apts-mission-stage3.3-planning-acceptance-gate-v1"
PLANNING_ACCEPTANCE_GATE_MODE = "FULL_REGRESSION_PLUS_LIVE_CANONICAL_PLANNING_PROBES"
PLANNING_ACCEPTANCE_GATE_BASELINE = "STAGE_3_3_1_THROUGH_3_3_9"
PLANNING_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = "NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY"
PLANNING_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
PLANNING_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 17

REQUIRED_STAGE3_3_CONTROLS = (
    "stage3.3.1-canonical-plan-contract-identity",
    "stage3.3.2-planner-input-snapshot-context-binding",
    "stage3.3.3-canonical-task-decomposition-contract",
    "stage3.3.4-task-dependency-graph-structural-validation",
    "stage3.3.5-planner-invocation-plan-generation",
    "stage3.3.6-plan-validation-feasibility-gate",
    "stage3.3.7-plan-versioning-replanning-supersession",
    "stage3.3.8-task-readiness-scheduling-projection",
    "stage3.3.9-planning-event-lineage-replay-recovery",
)

REQUIRED_PLANNING_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_PLAN_IDENTITY_AND_HASH_BINDING",
    "PLANNER_INPUT_SNAPSHOT_CONTEXT_BINDING",
    "CANONICAL_TASK_DECOMPOSITION_CONTRACT",
    "TASK_DAG_STRUCTURAL_VALIDATION",
    "PLANNER_INVOCATION_AND_PLAN_GENERATION",
    "PLAN_VALIDATION_AND_FEASIBILITY",
    "PLAN_VERSIONING_REPLANNING_AND_SUPERSESSION",
    "TASK_READINESS_AND_SCHEDULING_PROJECTION",
    "PLANNING_EVENT_LINEAGE_REPLAY_AND_RECOVERY",
    "RESTART_RECONSTRUCTION_WITHOUT_EXTERNAL_READS",
    "REPOSITORY_AND_EVENT_INTEGRITY",
    "FINAL_NO_GOVERNANCE_SCHEDULING_OR_TARGET_EXECUTION_EXPANSION",
)


def planning_acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.3 closure contract.

    The contract declares what an external release/acceptance activity must prove.
    It deliberately does not self-certify PASS inside the runtime.  Stage 3.3.10 is
    a closure gate only: all planning capabilities being tested already exist in
    Stage 3.3.1 through Stage 3.3.9.
    """

    return {
        "schema_version": PLANNING_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": PLANNING_ACCEPTANCE_GATE_MODE,
        "baseline": PLANNING_ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": PLANNING_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": PLANNING_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": PLANNING_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_3_CONTROLS),
        "required_gates": list(REQUIRED_PLANNING_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "existing_local_planner_invocation_preserved": True,
        "new_planner_capability_added": False,
        "external_model_invocation_added": False,
        "external_network_io_added": False,
        "governance_authorization_query_added": False,
        "wall_clock_scheduling_added": False,
        "resource_assignment_added": False,
        "task_dispatch_added": False,
        "target_action_dispatch_added": False,
        "target_actuation_added": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "plan_is_authorization": False,
        "task_is_dispatch": False,
        "readiness_is_permission": False,
        "planner_is_governance": False,
        "replay_is_execution": False,
        "recovery_is_authorization": False,
    }
