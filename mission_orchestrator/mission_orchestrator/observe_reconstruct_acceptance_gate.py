from __future__ import annotations

from typing import Any, Dict

OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_SCHEMA_VERSION = (
    "apts-mission-stage3.8-observe-reconstruct-acceptance-gate-v1"
)
OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_MODE = (
    "FULL_REGRESSION_PLUS_LIVE_OBSERVE_RECONSTRUCT_FORENSIC_AND_FAIL_CLOSED_PROBES"
)
OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_BASELINE = "STAGE_3_8_1_THROUGH_3_8_9"
OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = (
    "NO_NEW_OBSERVATION_RECONSTRUCTION_AUTHORITY_TELEMETRY_EXPORT_RUNTIME_IO_OR_TARGET_ACTUATION"
)
OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 53

REQUIRED_STAGE3_8_CONTROLS = (
    "stage3.8.1-canonical-observability-trace-identity-contract",
    "stage3.8.2-event-normalization-ingestion",
    "stage3.8.3-global-causal-lineage-graph",
    "stage3.8.4-live-mission-state-execution-projection",
    "stage3.8.5-decision-governance-evidence-trace",
    "stage3.8.6-deterministic-mission-timeline-reconstruction",
    "stage3.8.7-integrity-gap-consistency-diagnostics",
    "stage3.8.8-observability-metrics-health-operator-diagnostics",
    "stage3.8.9-forensic-query-evidence-bundle-reconstruction-api",
)

REQUIRED_OBSERVE_RECONSTRUCT_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "CANONICAL_PYTEST_INVENTORY",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_OBSERVABILITY_TRACE_IDENTITY",
    "EVENT_NORMALIZATION_AND_SOURCE_BINDING",
    "GLOBAL_CAUSAL_LINEAGE_GRAPH",
    "LIVE_MISSION_STATE_EXECUTION_PROJECTION",
    "DECISION_GOVERNANCE_EVIDENCE_TRACE",
    "DETERMINISTIC_MISSION_TIMELINE_RECONSTRUCTION",
    "INTEGRITY_GAP_CONSISTENCY_DIAGNOSTICS",
    "OBSERVABILITY_METRICS_HEALTH_OPERATOR_DIAGNOSTICS",
    "FORENSIC_EVIDENCE_BUNDLE_QUERY_AND_RECONSTRUCTION_API",
    "OBSERVE_RECONSTRUCT_CROSS_VIEW_CONSISTENCY",
    "RESTART_STABILITY_FOR_STABLE_DURABLE_SOURCES",
    "TAMPER_GAP_AND_SOURCE_DRIFT_FAIL_CLOSED",
    "READ_ONLY_NO_TELEMETRY_EXPORT_NO_EXTERNAL_IO_BOUNDARY",
    "REPOSITORY_MIGRATION_AND_PERSISTENCE_BOUNDARY",
    "FINAL_OBSERVE_RECONSTRUCT_AUTHORITY_AND_ACTUATION_BOUNDARY",
)


def observe_reconstruct_acceptance_gate_contract() -> Dict[str, Any]:
    """Static Stage-3.8 closure contract.

    Stage 3.8.10 is declaration-only release metadata. It neither observes a new
    external source nor mutates Mission state. PASS remains an operator-visible
    result produced by the acceptance harness and full regression execution.
    """

    return {
        "schema_version": OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_MODE,
        "baseline": OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_BASELINE,
        "runtime_change_mode": OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "database_change_mode": OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "expected_repository_migration_level": OBSERVE_RECONSTRUCT_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_prior_controls": list(REQUIRED_STAGE3_8_CONTROLS),
        "required_gates": list(REQUIRED_OBSERVE_RECONSTRUCT_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "stage381_trace_identity_authority": "CANONICAL_MISSION_IDENTITY_ENVELOPE_DERIVATION",
        "stage382_normalization_boundary": "READ_ONLY_VERIFIED_MISSION_EVENT_LEDGER",
        "stage383_causal_graph_boundary": "DETERMINISTIC_DERIVED_LINEAGE_GRAPH",
        "stage384_live_projection_boundary": "READ_ONLY_DERIVED_LIVE_PROJECTION",
        "stage385_decision_trace_boundary": "SOURCE_BOUND_DECISION_GOVERNANCE_EVIDENCE",
        "stage386_timeline_boundary": "VERIFIED_EVENT_LEDGER_APPEND_ORDER",
        "stage387_diagnostics_boundary": "FAIL_CLOSED_INTEGRITY_GAP_CONSISTENCY_DIAGNOSTICS",
        "stage388_operator_health_boundary": "OBSERVABILITY_DATA_QUALITY_ONLY",
        "stage389_forensics_boundary": "READ_ONLY_SOURCE_BOUND_EVIDENCE_BUNDLE_QUERY_RECONSTRUCTION",
        "new_observability_identity_authority_added": False,
        "new_event_ingestion_authority_added": False,
        "new_lineage_authority_added": False,
        "new_live_state_authority_added": False,
        "new_decision_authority_added": False,
        "new_reconstruction_authority_added": False,
        "new_repair_authority_added": False,
        "new_governance_query_added": False,
        "new_runtime_query_added": False,
        "new_external_network_io_added": False,
        "new_telemetry_export_added": False,
        "new_mission_state_transition_added": False,
        "new_routing_added": False,
        "new_delegation_added": False,
        "new_dispatch_added": False,
        "new_execution_attempt_added": False,
        "new_target_actuation_added": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "closure_gate_is_observability_source": False,
        "closure_gate_is_reconstruction_execution": False,
        "closure_gate_is_forensic_attestation": False,
        "closure_gate_is_integrity_repair": False,
        "closure_gate_is_runtime_control": False,
        "closure_gate_is_governance_authority": False,
        "closure_gate_is_dispatch_authority": False,
        "stage389_verified_bundle_is_external_attestation": False,
        "stage389_reconstruction_is_runtime_resumption": False,
        "stage389_reconstruction_is_mission_reexecution": False,
    }
