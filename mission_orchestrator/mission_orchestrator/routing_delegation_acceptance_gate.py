from __future__ import annotations

from typing import Any, Dict

ROUTING_DELEGATION_ACCEPTANCE_GATE_SCHEMA_VERSION = "apts-mission-stage3.4-routing-delegation-acceptance-gate-v1"
ROUTING_DELEGATION_ACCEPTANCE_GATE_MODE = "FULL_REGRESSION_PLUS_CANONICAL_INTEGRATION_AND_LIVE_RUNTIME_BOUNDARY_PROBES"
ROUTING_DELEGATION_ACCEPTANCE_GATE_BASELINE = "STAGE_3_4_1_THROUGH_3_4_9"
ROUTING_DELEGATION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = "NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY"
ROUTING_DELEGATION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
ROUTING_DELEGATION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 26

REQUIRED_STAGE3_4_CONTROLS = (
    "stage3.4.1-canonical-subsystem-registry-capability-contract",
    "stage3.4.2-task-routing-intent-candidate-resolution",
    "stage3.4.3-routing-eligibility-compatibility-gate",
    "stage3.4.4-deterministic-route-selection-decision-record",
    "stage3.4.5-governance-bound-delegation-authorization",
    "stage3.4.6-canonical-delegation-contract-handoff-envelope",
    "stage3.4.7-delegation-delivery-acknowledgement-ownership",
    "stage3.4.8-retry-fallback-reassignment-conflict-control",
    "stage3.4.9-routing-delegation-event-lineage-replay-recovery",
)

REQUIRED_ROUTING_DELEGATION_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_SUBSYSTEM_REGISTRY_AND_CAPABILITY_CONTRACT",
    "ROUTING_INTENT_AND_DETERMINISTIC_CANDIDATE_RESOLUTION",
    "ROUTING_ELIGIBILITY_AND_COMPATIBILITY_GATE",
    "DETERMINISTIC_ROUTE_SELECTION_AND_DECISION_RECORD",
    "GOVERNANCE_BOUND_DELEGATION_AUTHORIZATION",
    "CANONICAL_DELEGATION_CONTRACT_AND_HANDOFF_ENVELOPE",
    "DELIVERY_ACKNOWLEDGEMENT_AND_OWNERSHIP",
    "RETRY_FALLBACK_REASSIGNMENT_AND_CONFLICT_CONTROL",
    "ROUTING_DELEGATION_EVENT_LINEAGE_REPLAY_AND_RECOVERY",
    "RESTART_RECONSTRUCTION_WITHOUT_REROUTE_REAUTHORIZATION_OR_REDELIVERY",
    "REPOSITORY_AND_EVENT_INTEGRITY",
    "FINAL_NO_EXECUTION_AUTHORITY_OR_TARGET_ACTUATION_EXPANSION",
)


def routing_delegation_acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.4 closure contract.

    Stage 3.4.10 is a release/acceptance declaration only.  It does not execute
    the external acceptance campaign and does not add routing, authorization,
    delivery, ownership-transfer, dispatch, or target-execution authority.  The
    operator-visible acceptance harness plus the full regression suite provide
    the actual PASS/FAIL evidence for Stage 3.4.1 through Stage 3.4.9.
    """

    return {
        "schema_version": ROUTING_DELEGATION_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": ROUTING_DELEGATION_ACCEPTANCE_GATE_MODE,
        "baseline": ROUTING_DELEGATION_ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": ROUTING_DELEGATION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": ROUTING_DELEGATION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": ROUTING_DELEGATION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_4_CONTROLS),
        "required_gates": list(REQUIRED_ROUTING_DELEGATION_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "governance_authorization_authority": "EXTERNAL_APTS_GSS",
        "new_subsystem_registry_capability_added": False,
        "new_candidate_resolution_capability_added": False,
        "new_route_selection_authority_added": False,
        "new_governance_authorization_authority_added": False,
        "new_delegation_authority_added": False,
        "new_ownership_transfer_authority_added": False,
        "new_retry_fallback_reassignment_authority_added": False,
        "new_runtime_endpoint_resolution_added": False,
        "new_runtime_health_probe_added": False,
        "new_resource_assignment_added": False,
        "new_task_dispatch_added": False,
        "new_target_action_dispatch_added": False,
        "new_target_actuation_added": False,
        "new_external_network_io_added": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "candidate_is_eligibility_decision": False,
        "eligibility_is_authorization": False,
        "route_decision_is_delegation": False,
        "delegation_authorization_is_execution_authorization": False,
        "handoff_is_dispatch": False,
        "ownership_is_execution_authority": False,
        "recovery_control_is_dispatch": False,
        "replay_is_execution": False,
        "recovery_is_authorization": False,
    }
