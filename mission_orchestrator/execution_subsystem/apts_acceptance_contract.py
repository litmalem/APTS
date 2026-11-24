"""The final APTS gate declares requirements; only the external harness runs them."""
from __future__ import annotations

from mission_orchestrator.global_mission_acceptance_gate import canonical_global_mission_acceptance_gate_contract
from pentest_subsystem.acceptance_gate import canonical_pentest_foundation_acceptance_gate_contract
from pentest_subsystem.agentic_pentest_acceptance_gate import canonical_agentic_pentest_acceptance_gate_contract

from .cti_feedback_contract import canonical_feedback_contract
from .execution_contract import canonical_json, with_integrity

CONTROL_VERSION = "stage6.10-full-apts-end-to-end-acceptance-regression-gate"
CONTRACT_SCHEMA = "apts-stage6.10-full-end-to-end-acceptance-regression-gate-v1"
CONTRACT_DOMAIN = "APTS_STAGE6_10_FULL_ACCEPTANCE_CONTRACT_V1"
REQUIRED_GATES = (
    "AUTHORIZATION_INTEGRITY", "MISSION_INTEGRITY", "SCOPE_ROE_PRESERVATION",
    "AGENT_IDENTITY", "TASK_LINEAGE", "EXECUTION_ISOLATION", "EVIDENCE_INTEGRITY",
    "VEP_INTEGRITY", "RESTART_RECOVERY", "REPLAY_DETERMINISM", "CLOSED_LOOP_FEEDBACK",
    "KILL_ABORT_BEHAVIOR", "FORENSIC_RECONSTRUCTION", "FULL_STAGE1_6_REGRESSION",
)
TRAJECTORY = (
    "HUMAN_OBJECTIVE", "GLOBAL_MISSION_ORCHESTRATOR", "GOVERNANCE", "CTI", "PIP",
    "PENTEST_SUBSYSTEM", "SPECIALIST_AGENTS", "ACTION_PROPOSAL", "GOVERNANCE_REVALIDATION",
    "CONTROLLED_EXECUTION", "OBSERVATION_EVIDENCE", "VEP", "MISSION_OUTCOME",
    "CTI_KNOWLEDGE_UPDATE", "REPLANNING_OR_COMPLETION", "AUDIT_RECONSTRUCTION",
)


def canonical_apts_acceptance_contract():
    feedback = canonical_feedback_contract()
    return with_integrity({
        "schema_version": CONTRACT_SCHEMA, "control_version": CONTROL_VERSION,
        "predecessor": {"control": feedback["control_version"],
                        "contract_sha256": feedback["integrity"]["canonical_sha256"]},
        "domain_closures": {
            "mission": canonical_global_mission_acceptance_gate_contract()["integrity"]["canonical_sha256"],
            "pentest_foundation": canonical_pentest_foundation_acceptance_gate_contract()["integrity"]["canonical_sha256"],
            "agentic_pentest": canonical_agentic_pentest_acceptance_gate_contract()["integrity"]["canonical_sha256"],
        },
        "trajectory": list(TRAJECTORY), "required_gates": list(REQUIRED_GATES),
        "repositories": {"mission": 53, "pentest": 16, "execution": 9, "cti_feedback": 1},
        "regression": {
            "required_components": ["mission", "gss", "vulndesk"],
            "canonical_node_inventory_locked": True, "exact_junit_node_coverage": True,
            "zero_failures_errors_skips": True, "source_snapshot_unchanged": True,
            "fresh_evidence_directory": True, "external_test_processes": True,
            "compilation_required": True, "native_sandbox_probe_required": True,
            "connected_mission_pentest_execution_cti_scenario_required": True,
            "native_vulndesk_pip_publication_and_exact_pentest_projection_required": True,
            "runtime_preflight_required_for_deployment_acceptance": True,
        },
        "assurance": {
            "runtime_status": "DECLARED_ONLY", "runtime_self_certification": False,
            "pass_fail_owner": "EXTERNAL_ACCEPTANCE_HARNESS",
            "build_scope": "ISOLATED_LOOPBACK_AND_AUTHORITY_FIXTURES",
            "deployment_scope": "LIVE_READ_ONLY_PREFLIGHT_PLUS_ISOLATED_REGRESSION",
            "live_user_mission_execution_proven": False,
            "internal_hashes_are_independent_signatures": False,
            "current_adapter_vulnerability_outcome": "INCONCLUSIVE",
            "mission_completion_requires_existing_outcome_and_completion_gates": True,
            "cti_feedback_is_core_vulndesk_mutation": False,
            "target_rollback_or_issuer_revocation_proven": False,
        },
        "authority_boundary": {
            "execution_authorized": False, "governance_authority_added": False,
            "gate_dispatches_target_actions": False, "caller_pass_or_evidence_upload": False,
            "new_database_migration": False, "new_durable_runtime_store": False,
            "automatic_plan_activation": False, "terminal_mission_reopening": False,
        },
        "stage_output": "CONTROLLED_EVIDENCE_DRIVEN_CLOSED_LOOP_APTS",
        "next_stage": None,
    }, CONTRACT_DOMAIN)


def verify_apts_acceptance_contract(value):
    try:
        return canonical_json(value) == canonical_json(canonical_apts_acceptance_contract())
    except (ValueError, TypeError, RecursionError):
        return False
