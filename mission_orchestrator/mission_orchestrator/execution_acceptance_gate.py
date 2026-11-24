from __future__ import annotations

from typing import Any, Dict

EXECUTION_ACCEPTANCE_GATE_SCHEMA_VERSION = "apts-mission-stage3.5-execution-dispatch-acceptance-gate-v1"
EXECUTION_ACCEPTANCE_GATE_MODE = "FULL_REGRESSION_PLUS_CANONICAL_EXECUTION_INTEGRATION_AND_LIVE_RUNTIME_BOUNDARY_PROBES"
EXECUTION_ACCEPTANCE_GATE_BASELINE = "STAGE_3_5_1_THROUGH_3_5_9"
EXECUTION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = "NO_NEW_EXECUTION_AUTHORITY_RUNTIME_IO_OR_TARGET_ACTUATION"
EXECUTION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
EXECUTION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 35

REQUIRED_STAGE3_5_CONTROLS = (
    "stage3.5.1-canonical-execution-dispatch-contract-identity",
    "stage3.5.2-dispatch-eligibility-execution-preconditions",
    "stage3.5.3-authoritative-pre-dispatch-governance-revalidation",
    "stage3.5.4-idempotent-dispatch-execution-attempt-identity",
    "stage3.5.5-dispatch-delivery-execution-acknowledgement",
    "stage3.5.6-running-execution-state-heartbeat-projection",
    "stage3.5.7-execution-result-evidence-artifact-capture",
    "stage3.5.8-timeout-cancellation-abort-failure-propagation",
    "stage3.5.9-execution-event-lineage-replay-recovery",
)

REQUIRED_EXECUTION_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "CANONICAL_PYTEST_INVENTORY",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_EXECUTION_DISPATCH_CONTRACT_AND_IDENTITY",
    "DISPATCH_ELIGIBILITY_AND_EXECUTION_PRECONDITIONS",
    "AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE_REVALIDATION",
    "IDEMPOTENT_DISPATCH_AND_EXECUTION_ATTEMPT_IDENTITY",
    "DISPATCH_DELIVERY_AND_EXECUTION_ACKNOWLEDGEMENT",
    "RUNNING_EXECUTION_STATE_AND_HEARTBEAT_PROJECTION",
    "EXECUTION_RESULT_EVIDENCE_AND_ARTIFACT_CAPTURE",
    "TIMEOUT_CANCELLATION_ABORT_AND_FAILURE_PROPAGATION",
    "EXECUTION_EVENT_LINEAGE_REPLAY_AND_RECOVERY",
    "SUCCESS_AND_NON_SUCCESS_TERMINAL_TRAJECTORY_INTEGRATION",
    "RESTART_RECONSTRUCTION_WITHOUT_RUNTIME_QUERY_REDISPATCH_OR_RESUMPTION",
    "REPOSITORY_AND_EVENT_INTEGRITY",
    "FINAL_EXECUTION_AUTHORITY_RUNTIME_IO_AND_ACTUATION_BOUNDARY",
)


def execution_acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.5 closure contract.

    Stage 3.5.10 is a release/acceptance declaration only. It does not itself
    authorize execution, perform a Governance decision, create a dispatch or
    execution attempt, resolve/contact a target runtime, issue termination
    control, replay/resume work, transition Mission state, or actuate a target.

    The operator-visible acceptance harness plus the full regression suite are
    the authoritative PASS/FAIL evidence for Stage 3.5.1 through Stage 3.5.9.
    """

    return {
        "schema_version": EXECUTION_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": EXECUTION_ACCEPTANCE_GATE_MODE,
        "baseline": EXECUTION_ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": EXECUTION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": EXECUTION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": EXECUTION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_5_CONTROLS),
        "required_gates": list(REQUIRED_EXECUTION_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "stage35_execution_authority_source": "STAGE_3_5_3_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE_ALLOW",
        "stage35_target_dispatch_boundary": "STAGE_3_5_5_RUNTIME_DELIVERY",
        "stage35_runtime_observation_boundary": "STAGE_3_5_6_THROUGH_3_5_8",
        "stage35_replay_recovery_boundary": "STAGE_3_5_9_READ_ONLY_DURABLE_RECONSTRUCTION",
        "new_execution_authorization_authority_added": False,
        "new_governance_query_added": False,
        "new_execution_dispatch_contract_added": False,
        "new_dispatch_eligibility_gate_added": False,
        "new_execution_attempt_added": False,
        "new_runtime_endpoint_resolution_added": False,
        "new_runtime_health_probe_added": False,
        "new_runtime_delivery_added": False,
        "new_runtime_execution_state_query_added": False,
        "new_runtime_result_query_added": False,
        "new_runtime_control_io_added": False,
        "new_external_network_io_added": False,
        "new_dispatch_redelivery_added": False,
        "new_runtime_resumption_added": False,
        "new_target_action_dispatch_added": False,
        "new_target_actuation_added": False,
        "new_mission_state_transition_added": False,
        "new_failure_propagation_added": False,
        "new_mission_success_completion_authority_added": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "dispatch_contract_is_dispatch": False,
        "eligibility_is_execution_authorization": False,
        "governance_authorization_is_dispatch": False,
        "dispatch_commit_is_target_delivery": False,
        "delivery_ack_is_running_state": False,
        "running_projection_is_execution_authority": False,
        "result_capture_is_task_completion_authority": False,
        "successful_execution_is_mission_completion": False,
        "replay_is_execution": False,
        "recovery_is_authorization": False,
        "recovery_is_dispatch": False,
        "recovery_is_runtime_resumption": False,
        "closure_gate_is_execution": False,
    }
