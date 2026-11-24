from __future__ import annotations

from typing import Any, Dict

ACCEPTANCE_GATE_SCHEMA_VERSION = "apts-mission-stage3.1-acceptance-gate-v1"
ACCEPTANCE_GATE_MODE = "FULL_REGRESSION_PLUS_LIVE_CONTRACT_PROBES"
ACCEPTANCE_GATE_BASELINE = "STAGE_3_1_1_THROUGH_3_1_9"
ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = "NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY"
ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 8

REQUIRED_STAGE3_1_CONTROLS = (
    "stage3.1.1-canonical-mission-identity-envelope",
    "stage3.1.2-canonical-mission-state-model",
    "stage3.1.3-mission-scope-roe-constraint-contract",
    "stage3.1.4-governance-authorization-binding-contract",
    "stage3.1.5-governed-task-routing",
    "stage3.1.6-mission-versioning-concurrency",
    "stage3.1.7-mission-persistence-repository-model",
    "stage3.1.8-canonical-mission-api-validation-layer",
    "stage3.1.9-mission-event-lineage-foundation",
)

REQUIRED_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "GOVERNANCE_READINESS_AND_EMERGENCY_STOP",
    "CTI_READINESS",
    "CANONICAL_PREFLIGHT_ZERO_SIDE_EFFECTS",
    "IDENTITY_IDEMPOTENCY_AND_STATE_CONCURRENCY",
    "SCOPE_ROE_CONSTRAINT_IMMUTABILITY",
    "GOVERNANCE_BINDING_AND_AUTHORIZATION_PROVENANCE",
    "GOVERNED_CTI_ROUTING_AND_REPLAY",
    "VERSION_VECTOR_AND_COMMAND_GATE",
    "EVENT_LINEAGE_AND_REPOSITORY_INTEGRITY",
    "FINAL_NO_TARGET_EXECUTION_AUTHORITY",
)


def acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.1 closure contract.

    This is release metadata, not a claim that the external acceptance script has
    already executed.  The actual PASS/FAIL decision remains an offline/live
    acceptance activity.
    """

    return {
        "schema_version": ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": ACCEPTANCE_GATE_MODE,
        "baseline": ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_1_CONTROLS),
        "required_gates": list(REQUIRED_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
    }
