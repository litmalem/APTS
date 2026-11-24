from __future__ import annotations

from typing import Any, Dict

LIFECYCLE_ACCEPTANCE_GATE_SCHEMA_VERSION = "apts-mission-stage3.2-lifecycle-acceptance-gate-v1"
LIFECYCLE_ACCEPTANCE_GATE_MODE = "FULL_REGRESSION_PLUS_LIVE_LIFECYCLE_CONTRACT_PROBES"
LIFECYCLE_ACCEPTANCE_GATE_BASELINE = "STAGE_3_2_1_THROUGH_3_2_9"
LIFECYCLE_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = "NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY"
LIFECYCLE_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
LIFECYCLE_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 8

REQUIRED_STAGE3_2_CONTROLS = (
    "stage3.2.1-mission-lifecycle-command-contract",
    "stage3.2.2-lifecycle-transition-guard-matrix",
    "stage3.2.3-mission-pip-activation",
    "stage3.2.4-planning-run-activation",
    "stage3.2.5-waiting-dependency-control",
    "stage3.2.6-pause-resume-replanning-control",
    "stage3.2.7-abort-failure-expiration-semantics",
    "stage3.2.8-cleanup-verified-completion-gate",
    "stage3.2.9-event-driven-lifecycle-automation-reliability",
)

REQUIRED_LIFECYCLE_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "LIFECYCLE_COMMAND_AND_GUARD_DISCOVERY",
    "PIP_PLANNING_RUN_ACTIVATION",
    "WAITING_EVIDENCE_AND_APPROVAL_RESOLUTION",
    "PAUSE_RESUME_AND_REPLANNING_CONTROL",
    "ABORT_FAILURE_EXPIRATION_FINALITY",
    "CLEANUP_AND_VERIFIED_COMPLETION",
    "EVENT_AUTOMATION_IDEMPOTENCY_AND_STALE_REJECTION",
    "EVENT_LINEAGE_AND_REPOSITORY_INTEGRITY",
    "RESTART_RECONSTRUCTION_WITHOUT_EXTERNAL_READS",
    "FINAL_NO_GOVERNANCE_OR_TARGET_EXECUTION_EXPANSION",
)


def lifecycle_acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.2 closure contract.

    This is release metadata only.  It deliberately does not self-certify that
    the external acceptance script has executed or passed.  PASS/FAIL remains
    an operator-visible acceptance activity over the running service plus the
    full regression suite.
    """

    return {
        "schema_version": LIFECYCLE_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": LIFECYCLE_ACCEPTANCE_GATE_MODE,
        "baseline": LIFECYCLE_ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": LIFECYCLE_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": LIFECYCLE_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": LIFECYCLE_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_2_CONTROLS),
        "required_gates": list(REQUIRED_LIFECYCLE_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "planner_invocation_added": False,
        "target_action_dispatch_added": False,
        "target_actuation_added": False,
        "external_event_delivery_added": False,
    }
