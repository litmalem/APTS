from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .e2e_mission_acceptance import (
    E2E_MISSION_SCENARIO_ID,
    REQUIRED_STAGE_CLOSURE_CONTROLS,
    canonical_e2e_mission_acceptance_contract,
)
from .e2e_observation_reconstruction_forensic_equivalence import (
    OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_MIGRATION_LEVEL,
    OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION,
    canonical_observation_reconstruction_forensic_contract,
)

GLOBAL_MISSION_ACCEPTANCE_GATE_SCHEMA_VERSION = (
    "apts-stage3.9-global-mission-orchestrator-acceptance-regression-gate-v1"
)
GLOBAL_MISSION_ACCEPTANCE_GATE_HASH_DOMAIN = (
    "MISSION_STAGE3_9_10_GLOBAL_MISSION_ORCHESTRATOR_ACCEPTANCE_REGRESSION_GATE_V1"
)
GLOBAL_MISSION_ACCEPTANCE_GATE_MODE = (
    "GLOBAL_STAGE3_CLOSURE_FULL_HISTORICAL_REGRESSION_PLUS_CANONICAL_E2E_QUALIFICATION"
)
GLOBAL_MISSION_ACCEPTANCE_GATE_BASELINE = "STAGE_3_1_THROUGH_3_9_9_QUALIFIED"
GLOBAL_MISSION_ACCEPTANCE_GATE_PREDECESSOR_CONTROL = (
    "stage3.9.9-global-observation-reconstruction-forensic-equivalence"
)
GLOBAL_MISSION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = (
    OBSERVATION_RECONSTRUCTION_FORENSIC_EXPECTED_MIGRATION_LEVEL
)
GLOBAL_MISSION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
GLOBAL_MISSION_ACCEPTANCE_GATE_PERSISTENCE_MODE = "NO_NEW_DURABLE_STORE"
GLOBAL_MISSION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE = (
    "NO_NEW_AUTHORITY_EXECUTION_RUNTIME_IO_TELEMETRY_EXPORT_OR_TARGET_ACTUATION"
)
GLOBAL_MISSION_ACCEPTANCE_GATE_STAGE_OUTPUT = "GLOBAL_MISSION_ORCHESTRATOR"
GLOBAL_MISSION_ACCEPTANCE_GATE_NEXT_STAGE = "4.1"

REQUIRED_STAGE3_9_CONTROLS = (
    "stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract",
    "stage3.9.2-intake-lifecycle-e2e-segment-qualification",
    "stage3.9.3-planning-task-graph-dependency-verification",
    "stage3.9.4-routing-delegation-governance-continuity",
    "stage3.9.5-dispatch-execution-evidence-continuity",
    "stage3.9.6-task-completion-mission-outcome-closure",
    "stage3.9.7-adaptation-replanning-e2e-scenario",
    "stage3.9.8-restart-replay-recovery-e2e-verification",
    GLOBAL_MISSION_ACCEPTANCE_GATE_PREDECESSOR_CONTROL,
)

REQUIRED_GLOBAL_MISSION_ACCEPTANCE_GATES = (
    "PYTHON_COMPILE",
    "CANONICAL_PYTEST_INVENTORY",
    "FULL_HISTORICAL_PYTEST_REGRESSION",
    "ACTIVE_CONTROL_SERVER_VERSION_AND_MIGRATION_LEVEL",
    "STAGE3_1_THROUGH_3_8_DOMAIN_CLOSURE_CONTROLS_PRESENT",
    "STAGE3_9_1_CANONICAL_E2E_ACCEPTANCE_CONTRACT_INTEGRITY",
    "STAGE3_9_2_INTAKE_LIFECYCLE_QUALIFICATION",
    "STAGE3_9_3_PLANNING_TASK_GRAPH_QUALIFICATION",
    "STAGE3_9_4_ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION",
    "STAGE3_9_5_DISPATCH_EXECUTION_EVIDENCE_QUALIFICATION",
    "STAGE3_9_6_COMPLETION_OUTCOME_QUALIFICATION",
    "STAGE3_9_7_ADAPTATION_REPLANNING_QUALIFICATION",
    "STAGE3_9_8_RESTART_REPLAY_RECOVERY_QUALIFICATION",
    "STAGE3_9_9_OBSERVATION_RECONSTRUCTION_FORENSIC_EQUIVALENCE",
    "GLOBAL_IDENTITY_LINEAGE_AND_CANONICAL_HEAD_CONSISTENCY",
    "GOVERNANCE_AUTHORIZATION_AND_PRE_DISPATCH_REVALIDATION_BOUNDARY",
    "IDEMPOTENT_DISPATCH_EXECUTION_AND_REPLAY_NO_DUPLICATE_SIDE_EFFECTS",
    "EVIDENCE_TASK_COMPLETION_MISSION_OUTCOME_AND_SUCCESS_CRITERIA_CONTINUITY",
    "ADAPTATION_REPLAN_COMMIT_SUPERSESSION_AND_RECOVERY_CONTINUITY",
    "READ_ONLY_OBSERVATION_RECONSTRUCTION_FORENSIC_EQUIVALENCE",
    "TAMPER_GAP_SOURCE_DRIFT_AND_INTEGRITY_FAILURE_FAIL_CLOSED",
    "NO_NEW_PERSISTENCE_AUTHORITY_EXTERNAL_IO_OR_TARGET_ACTUATION",
    "FINAL_STAGE3_GLOBAL_MISSION_ORCHESTRATOR_CLOSURE",
)


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_global_mission_acceptance_gate_contract() -> dict[str, Any]:
    stage391 = canonical_e2e_mission_acceptance_contract()
    stage399 = canonical_observation_reconstruction_forensic_contract()
    core = {
        "schema_version": GLOBAL_MISSION_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": GLOBAL_MISSION_ACCEPTANCE_GATE_MODE,
        "baseline": GLOBAL_MISSION_ACCEPTANCE_GATE_BASELINE,
        "predecessor_control": GLOBAL_MISSION_ACCEPTANCE_GATE_PREDECESSOR_CONTROL,
        "predecessor_schema_version": OBSERVATION_RECONSTRUCTION_FORENSIC_SCHEMA_VERSION,
        "predecessor_contract_sha256": stage399["integrity"]["canonical_sha256"],
        "canonical_e2e_scenario_id": E2E_MISSION_SCENARIO_ID,
        "canonical_e2e_contract_sha256": stage391["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": GLOBAL_MISSION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": GLOBAL_MISSION_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
        "persistence_mode": GLOBAL_MISSION_ACCEPTANCE_GATE_PERSISTENCE_MODE,
        "runtime_change_mode": GLOBAL_MISSION_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
        "required_stage_domain_closure_controls": list(REQUIRED_STAGE_CLOSURE_CONTROLS),
        "required_stage3_9_controls": list(REQUIRED_STAGE3_9_CONTROLS),
        "required_gates": list(REQUIRED_GLOBAL_MISSION_ACCEPTANCE_GATES),
        "closure_semantics": {
            "declared_only": True,
            "runtime_self_certification": False,
            "external_acceptance_execution_required": True,
            "acceptance_harness_is_pass_fail_authority": True,
            "full_historical_regression_required": True,
            "all_stage3_9_segment_qualifications_required": True,
            "stage3_9_9_global_equivalence_required": True,
            "historical_stage3_domain_closure_required": True,
            "stage_output": GLOBAL_MISSION_ACCEPTANCE_GATE_STAGE_OUTPUT,
        },
        "authority_boundary": {
            "closure_gate_is_execution_authority": False,
            "closure_gate_is_governance_authority": False,
            "closure_gate_is_routing_authority": False,
            "closure_gate_is_delegation_authority": False,
            "closure_gate_is_dispatch_authority": False,
            "closure_gate_is_recovery_authority": False,
            "closure_gate_is_observability_source": False,
            "closure_gate_is_forensic_attestation": False,
            "runtime_mission_materialization_performed": False,
            "runtime_mission_state_transition_performed": False,
            "runtime_planner_rerun_performed": False,
            "runtime_governance_query_performed": False,
            "runtime_runtime_query_performed": False,
            "runtime_routing_performed": False,
            "runtime_delegation_performed": False,
            "runtime_dispatch_performed": False,
            "runtime_execution_attempt_created": False,
            "runtime_recovery_mutation_performed": False,
            "runtime_integrity_repair_performed": False,
            "runtime_telemetry_export_performed": False,
            "runtime_external_network_io_performed": False,
            "runtime_target_actuation": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "new_execution_authority_added": False,
            "new_governance_authority_added": False,
            "new_routing_authority_added": False,
            "new_delegation_authority_added": False,
            "new_dispatch_authority_added": False,
            "new_recovery_authority_added": False,
            "new_observation_authority_added": False,
            "new_forensic_authority_added": False,
        },
        "stage_output": GLOBAL_MISSION_ACCEPTANCE_GATE_STAGE_OUTPUT,
        "next_stage": GLOBAL_MISSION_ACCEPTANCE_GATE_NEXT_STAGE,
    }
    return {
        **core,
        "integrity": {
            "hash_domain": GLOBAL_MISSION_ACCEPTANCE_GATE_HASH_DOMAIN,
            "canonical_sha256": _sha({
                "hash_domain": GLOBAL_MISSION_ACCEPTANCE_GATE_HASH_DOMAIN,
                "core": core,
            }),
        },
    }


def verify_global_mission_acceptance_gate_contract(contract: Mapping[str, Any]) -> bool:
    try:
        return dict(contract) == canonical_global_mission_acceptance_gate_contract()
    except Exception:
        return False


def canonical_global_mission_acceptance_gate_definition() -> dict[str, Any]:
    contract = canonical_global_mission_acceptance_gate_contract()
    return {
        "schema_version": GLOBAL_MISSION_ACCEPTANCE_GATE_SCHEMA_VERSION,
        "mode": GLOBAL_MISSION_ACCEPTANCE_GATE_MODE,
        "baseline": GLOBAL_MISSION_ACCEPTANCE_GATE_BASELINE,
        "predecessor_control": GLOBAL_MISSION_ACCEPTANCE_GATE_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "canonical_e2e_contract_sha256": contract["canonical_e2e_contract_sha256"],
        "canonical_e2e_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": GLOBAL_MISSION_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
        "required_stage_domain_closure_control_count": len(REQUIRED_STAGE_CLOSURE_CONTROLS),
        "required_stage3_9_control_count": len(REQUIRED_STAGE3_9_CONTROLS),
        "required_gate_count": len(REQUIRED_GLOBAL_MISSION_ACCEPTANCE_GATES),
        "declared_only": True,
        "runtime_self_certification": False,
        "external_acceptance_execution_required": True,
        "full_historical_regression_required": True,
        "new_database_migration_added": False,
        "new_durable_store_added": False,
        "new_runtime_authority_added": False,
        "target_actuation": False,
        "stage_output": GLOBAL_MISSION_ACCEPTANCE_GATE_STAGE_OUTPUT,
        "next_stage": GLOBAL_MISSION_ACCEPTANCE_GATE_NEXT_STAGE,
        "contract_sha256": contract["integrity"]["canonical_sha256"],
    }
