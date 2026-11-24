from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .canonical import verify_envelope
from .e2e_mission_acceptance import E2E_MISSION_SCENARIO_ID, materialize_canonical_e2e_mission_request
from .e2e_planning_task_graph_qualification import (
    PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES,
    PLANNING_TASK_GRAPH_TASK_KEYS,
    canonical_planning_task_graph_qualification_contract,
)
from .planner_generation import PLANNER_PROFILE_CANONICAL_DAG_V1, verify_generated_plan_contract, verify_planner_invocation_contract
from .plan_validation import verify_plan_validation_contract
from .plan_versioning import verify_plan_version_contract
from .task_readiness_projection import verify_task_readiness_projection_contract
from .scope_contract import verify_contract as verify_scope_contract
from .governance_binding import verify_binding_contract
from .task_routing_intent import verify_task_routing_intent_contract
from .task_routing_eligibility import verify_task_routing_eligibility_contract
from .task_route_selection import verify_task_route_selection_contract
from .delegation_authorization import verify_delegation_authorization_contract
from .delegation_handoff import verify_delegation_contract, verify_handoff_envelope
from .delegation_delivery import verify_delivery_receipt_contract

ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_SCHEMA_VERSION = (
    "apts-stage3.9-routing-delegation-governance-continuity-v1"
)
ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_HASH_DOMAIN = (
    "MISSION_STAGE3_9_4_ROUTING_DELEGATION_GOVERNANCE_CONTINUITY_V1"
)
ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_MODE = (
    "EXISTING_STAGE3_3_5_TO_3_3_8_AND_STAGE3_4_AUTHORITIES_"
    "AUTHORITATIVE_GOVERNANCE_CONTINUITY_READ_ONLY_RUNTIME_VERIFICATION"
)
ROUTING_DELEGATION_GOVERNANCE_PREDECESSOR_CONTROL = (
    "stage3.9.3-planning-task-graph-dependency-verification"
)
ROUTING_DELEGATION_GOVERNANCE_EXPECTED_MIGRATION_LEVEL = 53
ROUTING_DELEGATION_GOVERNANCE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
ROUTING_DELEGATION_GOVERNANCE_PERSISTENCE_MODE = "EXISTING_STAGE3_1_STAGE3_3_STAGE3_4_STORES_ONLY"
ROUTING_DELEGATION_GOVERNANCE_ENTRY_STATE = "PLANNING"
ROUTING_DELEGATION_GOVERNANCE_ENTRY_STATE_VERSION = 3
ROUTING_DELEGATION_GOVERNANCE_READY_TASK_KEY = "collect-cti"
ROUTING_DELEGATION_GOVERNANCE_SELECTED_SUBSYSTEM = "CTI"
ROUTING_DELEGATION_GOVERNANCE_SELECTED_CAPABILITY = "cti.read.context"
ROUTING_DELEGATION_GOVERNANCE_NEXT_STAGE = "3.9.5"

ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES = PLANNING_TASK_GRAPH_EXPECTED_EVENT_TYPES + (
    "MISSION_PLANNER_INVOKED",
    "MISSION_PLAN_GENERATED",
    "MISSION_PLAN_VALIDATED_FEASIBLE",
    "MISSION_PLAN_VERSION_ACTIVATED",
    "MISSION_TASK_READINESS_PROJECTED",
    "MISSION_SCOPE_CONTRACT_COMMITTED",
    "MISSION_GOVERNANCE_BOUND",
    "MISSION_TASK_ROUTING_CANDIDATES_RESOLVED",
    "MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED",
    "MISSION_TASK_ROUTE_DECISION_RECORDED",
    "MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED",
    "MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED",
    "MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED",
)

ROUTING_DELEGATION_GOVERNANCE_ALLOWED_NONZERO_REPOSITORY_COUNTS = {
    "global_missions": 1,
    "mission_envelopes": 1,
    "mission_states": 1,
    "mission_state_transitions": 2,
    "mission_command_journal": 2,
    "mission_scope_contract_heads": 1,
    "mission_scope_contract_versions": 1,
    "mission_governance_binding_heads": 1,
    "mission_governance_binding_versions": 1,
    "mission_governance_binding_operations": 1,
    "mission_plans": 1,
    "mission_planner_input_snapshots": 1,
    "mission_task_decompositions": 1,
    "mission_planned_tasks": 3,
    "mission_task_dependency_graphs": 1,
    "mission_task_dependency_edges": 2,
    "mission_planner_invocations": 1,
    "mission_generated_plans": 1,
    "mission_plan_validations": 1,
    "mission_plan_versions": 1,
    "mission_plan_version_heads": 1,
    "mission_task_readiness_projections": 1,
    "mission_task_routing_intents": 1,
    "mission_task_routing_eligibility_gates": 1,
    "mission_task_route_decisions": 1,
    "mission_delegation_authorizations": 1,
    "mission_task_delegations": 1,
    "mission_delegation_deliveries": 1,
    "mission_events": 22,
}

ROUTING_DELEGATION_GOVERNANCE_FORBIDDEN_NEW_AUTHORITIES = (
    "new_governance_decision_authority",
    "new_routing_authority",
    "new_delegation_authority",
    "dispatch",
    "execution",
    "target_action_dispatch",
    "target_actuation",
    "runtime_endpoint_resolution",
    "runtime_health_probe",
    "external_target_network_io",
    "telemetry_export",
    "database_migration",
    "durable_store_creation",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = _canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_run_id(run_id: str) -> None:
    materialize_canonical_e2e_mission_request(run_id)


def _meta(run_id: str, step: str) -> dict[str, Any]:
    return {
        "stage": "3.9.4",
        "scenario_id": E2E_MISSION_SCENARIO_ID,
        "run_id": run_id,
        "segment": "ROUTING_TO_DELEGATION_TO_GOVERNANCE_CONTINUITY",
        "step": step,
    }


def build_planner_generation_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int,
                                     plan: Mapping[str, Any], snapshot: Mapping[str, Any], decomposition: Mapping[str, Any], graph: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-planner-generation",
        "expected_version_sha256": expected_version_sha256,
        "expected_plan_id": plan["plan_id"], "expected_plan_version": int(plan["plan_version"]), "expected_plan_sha256": plan["canonical_sha256"],
        "expected_snapshot_id": snapshot["snapshot_id"], "expected_snapshot_version": int(snapshot["snapshot_version"]), "expected_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_decomposition_id": decomposition["decomposition_id"], "expected_decomposition_version": int(decomposition["decomposition_version"]),
        "expected_decomposition_sha256": decomposition["canonical_sha256"], "expected_task_set_sha256": decomposition["task_set_sha256"],
        "expected_graph_id": graph["graph_id"], "expected_graph_version": int(graph["graph_version"]), "expected_graph_sha256": graph["canonical_sha256"],
        "expected_node_set_sha256": graph["node_set_sha256"], "expected_edge_set_sha256": graph["edge_set_sha256"],
        "expected_state_version": expected_state_version, "planner_profile": PLANNER_PROFILE_CANONICAL_DAG_V1,
        "created_by": "stage3.9.4-acceptance-runner", "reason": "Bridge the verified Stage 3.9.3 DAG into the existing deterministic planner before routing",
        "metadata": _meta(run_id, "PLANNER_GENERATION"),
    }


def build_plan_validation_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int, generated: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-plan-validation", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_generated_plan_id": generated["generated_plan_id"],
        "expected_generated_plan_sha256": generated["generated_plan_sha256"] if "generated_plan_sha256" in generated else generated["canonical_sha256"],
        "created_by": "stage3.9.4-acceptance-runner", "reason": "Validate the deterministic planner candidate before activation",
        "metadata": _meta(run_id, "PLAN_VALIDATION"),
    }


def build_plan_activation_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int, validation: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-plan-activation", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_plan_validation_id": validation["plan_validation_id"],
        "expected_plan_validation_sha256": validation["canonical_sha256"], "created_by": "stage3.9.4-acceptance-runner",
        "reason": "Activate the validated canonical Plan v1 required by routing", "metadata": _meta(run_id, "PLAN_ACTIVATION"),
    }


def build_readiness_projection_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int, active: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-readiness", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]), "expected_active_plan_sha256": active["canonical_sha256"],
        "created_by": "stage3.9.4-acceptance-runner", "reason": "Project structural readiness so only the root CTI task can enter routing",
        "metadata": _meta(run_id, "TASK_READINESS"),
    }


def build_scope_request(*, run_id: str) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "expected_contract_version": 0, "idempotency_key": f"stage394-{run_id}-scope", "actor": "stage3.9.4-acceptance-runner",
        "scope": {"targets": [{"target_type": "OTHER", "target_value": "sandbox-e2e-target-01", "environment": "CONTROL_PLANE_SANDBOX"}],
                  "excluded_targets": [], "network_ranges": [], "domains": [], "services": []},
        "roe": {"allowed_action_classes": ["TARGET_RECON", "INTERNAL_REASONING"], "prohibited_action_classes": ["DESTRUCTIVE_ACTION", "CREDENTIAL_USE"],
                "allowed_time_window": {"start_at": "2026-01-01T00:00:00Z", "end_at": "2030-12-31T23:59:59Z"},
                "maximum_concurrency": 1, "destructive_actions_allowed": False, "credential_usage_allowed": False,
                "persistence_allowed": False, "human_approval_required_for": []},
        "constraints": {"max_actions": 16, "max_duration": 900, "risk_threshold": "LOW", "resource_budget": {"max_network_requests": 0},
                        "data_handling_policy": {"classification": "INTERNAL", "retention_days": 1, "export_allowed": False}},
        "reason": "Stage 3.9.4 sandbox governance continuity scope", "metadata": _meta(run_id, "MISSION_SCOPE"),
    }


def build_governance_binding_request(*, run_id: str) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "expected_binding_version": 0, "idempotency_key": f"stage394-{run_id}-governance-binding", "actor": "stage3.9.4-acceptance-runner",
        "policy_set_id": "default-policy", "name": "Stage 3.9.4 E2E routing/delegation governance continuity",
        "capabilities": [{"capability_id": "stage394.control-plane-anchor", "subject_component": "MISSION-ORCH",
                          "action_class": "TARGET_RECON", "action_name": "stage394_control_plane_anchor", "authorization_mode": "REQUIRED",
                          "resource_types": ["OTHER"], "max_risk_level": "LOW", "requires_human_approval": False, "constraints": {}}],
        "reason": "Bind canonical Mission scope to authoritative aptsGSS without creating local governance authority",
        "metadata": _meta(run_id, "GOVERNANCE_BINDING"),
    }


def build_routing_intent_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int,
                                 active: Mapping[str, Any], readiness: Mapping[str, Any], planned_task_id: str) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-routing-intent", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]), "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": readiness["projection_id"], "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
        "planned_task_id": planned_task_id, "created_by": "stage3.9.4-acceptance-runner",
        "reason": "Resolve canonical CTI routing candidates for the sole READY task", "metadata": _meta(run_id, "ROUTING_INTENT"),
    }


def build_routing_eligibility_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int,
                                      active: Mapping[str, Any], readiness: Mapping[str, Any], routing: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-routing-eligibility", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]), "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": readiness["projection_id"], "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
        "expected_routing_intent_id": routing["routing_intent_id"], "expected_routing_intent_sha256": routing["canonical_sha256"],
        "planned_task_id": routing["planned_task_id"], "created_by": "stage3.9.4-acceptance-runner",
        "reason": "Evaluate static routing eligibility and compatibility", "metadata": _meta(run_id, "ROUTING_ELIGIBILITY"),
    }


def build_route_selection_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int,
                                  active: Mapping[str, Any], readiness: Mapping[str, Any], routing: Mapping[str, Any], eligibility: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-route-selection", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]), "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": readiness["projection_id"], "expected_task_readiness_projection_sha256": readiness["canonical_sha256"],
        "expected_routing_intent_id": routing["routing_intent_id"], "expected_routing_intent_sha256": routing["canonical_sha256"],
        "expected_eligibility_gate_id": eligibility["eligibility_gate_id"], "expected_eligibility_gate_sha256": eligibility["canonical_sha256"],
        "planned_task_id": routing["planned_task_id"], "created_by": "stage3.9.4-acceptance-runner",
        "reason": "Select the deterministic logical route from eligible candidates", "metadata": _meta(run_id, "ROUTE_SELECTION"),
    }


def build_delegation_authorization_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int,
                                           active: Mapping[str, Any], route: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-delegation-authorization", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]), "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_route_decision_id": route["route_decision_id"], "expected_route_decision_sha256": route["canonical_sha256"],
        "planned_task_id": route["planned_task_id"], "requested_by": "stage3.9.4-acceptance-runner",
        "reason": "Obtain authoritative pre-delegation Governance decision for the selected logical route",
        "metadata": _meta(run_id, "DELEGATION_AUTHORIZATION"),
    }


def build_delegation_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int,
                             active: Mapping[str, Any], route: Mapping[str, Any], authorization: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    return {
        "idempotency_key": f"stage394-{run_id}-delegation", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]), "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_delegation_authorization_id": authorization["delegation_authorization_id"],
        "expected_delegation_authorization_sha256": authorization["canonical_sha256"], "planned_task_id": route["planned_task_id"],
        "delegated_by": "stage3.9.4-acceptance-runner", "reason": "Materialize immutable logical delegation and handoff envelope",
        "metadata": _meta(run_id, "DELEGATION_HANDOFF"),
    }


def build_delegation_delivery_request(*, run_id: str, expected_version_sha256: str, expected_state_version: int,
                                      active: Mapping[str, Any], delegation: Mapping[str, Any]) -> dict[str, Any]:
    _validate_run_id(run_id)
    recipient = delegation["handoff_envelope"]["recipient"]
    return {
        "idempotency_key": f"stage394-{run_id}-delegation-delivery", "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version, "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]), "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_delegation_id": delegation["delegation_id"], "expected_delegation_sha256": delegation["canonical_sha256"],
        "expected_handoff_envelope_id": delegation["handoff_envelope_id"], "expected_handoff_envelope_sha256": delegation["handoff_envelope_sha256"],
        "recipient_subsystem_id": recipient["subsystem_id"], "recipient_capability_id": recipient["capability_id"],
        "acknowledged_by": recipient["subsystem_id"], "ownership_accepted_by": recipient["subsystem_id"],
        "reason": "Record control-plane handoff acknowledgement and deterministic ownership without dispatch",
        "metadata": _meta(run_id, "DELEGATION_DELIVERY_OWNERSHIP"),
    }


def canonical_routing_delegation_governance_qualification_contract() -> dict[str, Any]:
    predecessor = canonical_planning_task_graph_qualification_contract()
    core = {
        "schema_version": ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_SCHEMA_VERSION,
        "mode": ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_MODE,
        "predecessor_control": ROUTING_DELEGATION_GOVERNANCE_PREDECESSOR_CONTROL,
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": predecessor["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": ROUTING_DELEGATION_GOVERNANCE_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": ROUTING_DELEGATION_GOVERNANCE_DATABASE_CHANGE_MODE,
        "persistence_mode": ROUTING_DELEGATION_GOVERNANCE_PERSISTENCE_MODE,
        "existing_authority_sequence": [
            "STAGE3_3_5_PLANNER_GENERATION", "STAGE3_3_6_PLAN_VALIDATION", "STAGE3_3_7_PLAN_ACTIVATION",
            "STAGE3_3_8_TASK_READINESS", "STAGE3_1_3_SCOPE", "STAGE3_1_4_GOVERNANCE_BINDING",
            "STAGE3_4_2_ROUTING_INTENT", "STAGE3_4_3_ELIGIBILITY", "STAGE3_4_4_ROUTE_SELECTION",
            "STAGE3_4_5_AUTHORITATIVE_DELEGATION_AUTHORIZATION", "STAGE3_4_6_DELEGATION_HANDOFF", "STAGE3_4_7_DELIVERY_ACK_OWNERSHIP",
        ],
        "qualified_segment_head": {
            "state": "PLANNING", "state_version": 3, "active_plan_version": 1,
            "ready_task_keys": [ROUTING_DELEGATION_GOVERNANCE_READY_TASK_KEY],
            "blocked_task_keys": ["analyze-cti", "report-findings"],
            "selected_subsystem": ROUTING_DELEGATION_GOVERNANCE_SELECTED_SUBSYSTEM,
            "selected_capability": ROUTING_DELEGATION_GOVERNANCE_SELECTED_CAPABILITY,
            "governance_authorization_status": "AUTHORIZED", "handoff_acknowledged": True, "ownership_accepted": True,
            "dispatch_performed": False, "execution_authorized": False, "target_actuation": False,
        },
        "expected_event_types": list(ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(ROUTING_DELEGATION_GOVERNANCE_ALLOWED_NONZERO_REPOSITORY_COUNTS),
        "continuity_requirements": {
            "same_mission_root": True, "same_active_plan_lineage": True, "same_ready_task_identity": True,
            "route_selection_precedes_authoritative_governance": True, "authorization_precedes_delegation": True,
            "delegation_precedes_acknowledgement_and_ownership": True, "blocked_dependencies_do_not_route": True,
            "pre_dispatch_governance_revalidation_remains_required": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True, "new_governance_decision_authority_added": False,
            "new_routing_authority_added": False, "new_delegation_authority_added": False,
            "new_dispatch_authority_added": False, "new_execution_authority_added": False,
            "new_target_actuation_authority_added": False, "new_external_target_network_io_added": False,
            "new_database_migration_added": False, "new_durable_store_added": False,
            "forbidden_new_authorities": list(ROUTING_DELEGATION_GOVERNANCE_FORBIDDEN_NEW_AUTHORITIES),
        },
        "next_stage": ROUTING_DELEGATION_GOVERNANCE_NEXT_STAGE,
    }
    return {**core, "integrity": {"hash_domain": ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_HASH_DOMAIN,
                                   "canonical_sha256": _sha256_hex({"hash_domain": ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_HASH_DOMAIN, "core": core})}}


def verify_routing_delegation_governance_qualification_contract(contract: Mapping[str, Any]) -> bool:
    try:
        expected = canonical_routing_delegation_governance_qualification_contract()
        return dict(contract) == expected
    except Exception:
        return False


def _check(checks: list[dict[str, Any]], check_id: str, passed: bool, observed: Any, required: Any) -> None:
    checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "observed": observed, "required": required})


def evaluate_routing_delegation_governance_qualification(*, mission_id: str, envelope: Mapping[str, Any], state: Mapping[str, Any],
                                                         planner_invocation: Mapping[str, Any] | None, generated_plan: Mapping[str, Any] | None,
                                                         plan_validation: Mapping[str, Any] | None, active_plan: Mapping[str, Any] | None,
                                                         readiness: Mapping[str, Any] | None, scope_record: Mapping[str, Any] | None,
                                                         governance_binding: Mapping[str, Any] | None, routing_intents: Sequence[Mapping[str, Any]],
                                                         eligibility_gates: Sequence[Mapping[str, Any]], route_decisions: Sequence[Mapping[str, Any]],
                                                         delegation_authorizations: Sequence[Mapping[str, Any]], delegations: Sequence[Mapping[str, Any]],
                                                         deliveries: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]],
                                                         repository_counts: Mapping[str, int], event_integrity_status: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    metadata = envelope.get("metadata") if isinstance(envelope.get("metadata"), Mapping) else {}
    run_id = metadata.get("run_id")
    run_valid = isinstance(run_id, str)
    if run_valid:
        try: _validate_run_id(run_id)
        except ValueError: run_valid = False
    _check(checks, "CANONICAL_RUN_AND_SCENARIO_BINDING", run_valid and metadata.get("scenario_id") == E2E_MISSION_SCENARIO_ID and verify_envelope(envelope),
           {"run_id": run_id, "scenario_id": metadata.get("scenario_id"), "envelope_verified": verify_envelope(envelope)}, "VALID_CANONICAL_STAGE3_9_MISSION")
    _check(checks, "MISSION_HEAD_REMAINS_PLANNING", state.get("state") == "PLANNING" and int(state.get("state_version", 0)) == 3 and state.get("terminal") is False,
           {"state": state.get("state"), "state_version": state.get("state_version"), "terminal": state.get("terminal")}, {"state": "PLANNING", "state_version": 3, "terminal": False})

    planner_ok = bool(planner_invocation and generated_plan and verify_planner_invocation_contract(planner_invocation.get("planner_invocation", {})) and verify_generated_plan_contract(generated_plan.get("generated_plan", {})))
    validation_ok = bool(plan_validation and verify_plan_validation_contract(plan_validation.get("plan_validation", {})) and plan_validation.get("status") == "VALIDATED_FEASIBLE" and bool(plan_validation.get("feasible")))
    active_ok = bool(active_plan and verify_plan_version_contract(active_plan.get("plan_version_contract", {})) and int(active_plan.get("plan_version", 0)) == 1)
    readiness_ok = bool(readiness and verify_task_readiness_projection_contract(readiness.get("projection_contract", {})) and int(readiness.get("ready_task_count", 0)) == 1 and int(readiness.get("blocked_task_count", 0)) == 2)
    ready_keys = [] if not readiness else list(readiness.get("projection_contract", {}).get("projection", {}).get("ready_task_keys", []))
    blocked_keys = [] if not readiness else list(readiness.get("projection_contract", {}).get("projection", {}).get("blocked_task_keys", []))
    _check(checks, "PLANNING_BRIDGE_MATERIALIZED", planner_ok and validation_ok and active_ok and readiness_ok,
           {"planner": planner_ok, "validation": validation_ok, "active_plan": active_ok, "readiness": readiness_ok}, {"planner": True, "validation": True, "active_plan": True, "readiness": True})
    _check(checks, "DEPENDENCY_READINESS_PRESERVED", ready_keys == ["collect-cti"] and blocked_keys == ["analyze-cti", "report-findings"],
           {"ready": ready_keys, "blocked": blocked_keys}, {"ready": ["collect-cti"], "blocked": ["analyze-cti", "report-findings"]})

    scope_ok = bool(scope_record and verify_scope_contract(scope_record.get("contract", {})))
    binding_ok = bool(
        governance_binding
        and verify_binding_contract(governance_binding.get("binding", {}))
        and governance_binding.get("binding", {}).get("canonical_scope_binding", {}).get("mission_scope_sha256")
        == (scope_record or {}).get("canonical_sha256")
    )
    _check(checks, "AUTHORITATIVE_GOVERNANCE_BINDING_CONTINUITY", scope_ok and binding_ok, {"scope": scope_ok, "binding": binding_ok}, {"scope": True, "binding": True})

    cardinality = [len(routing_intents), len(eligibility_gates), len(route_decisions), len(delegation_authorizations), len(delegations), len(deliveries)]
    _check(checks, "EXACT_SINGLE_READY_TASK_ROUTING_TRAJECTORY", cardinality == [1, 1, 1, 1, 1, 1], cardinality, [1, 1, 1, 1, 1, 1])
    routing = routing_intents[0] if len(routing_intents) == 1 else None
    eligibility = eligibility_gates[0] if len(eligibility_gates) == 1 else None
    route = route_decisions[0] if len(route_decisions) == 1 else None
    auth = delegation_authorizations[0] if len(delegation_authorizations) == 1 else None
    delegation = delegations[0] if len(delegations) == 1 else None
    delivery = deliveries[0] if len(deliveries) == 1 else None
    integrity_ok = bool(routing and eligibility and route and auth and delegation and delivery
        and verify_task_routing_intent_contract(routing.get("routing_intent_contract", {}))
        and verify_task_routing_eligibility_contract(eligibility.get("eligibility_contract", {}))
        and verify_task_route_selection_contract(route.get("route_selection_contract", {}))
        and verify_delegation_authorization_contract(auth.get("delegation_authorization_contract", {}))
        and verify_delegation_contract(delegation.get("delegation_contract", {}))
        and verify_handoff_envelope(delegation.get("delegation_contract", {}).get("handoff_envelope", {}))
        and verify_delivery_receipt_contract(delivery.get("delivery_receipt_contract", {})))
    _check(checks, "ROUTING_DELEGATION_ARTIFACT_INTEGRITY", integrity_ok, integrity_ok, True)

    if routing and eligibility and route and auth and delegation and delivery:
        task_ids = {routing.get("planned_task_id"), eligibility.get("planned_task_id"), route.get("planned_task_id"), auth.get("planned_task_id"), delegation.get("planned_task_id"), delivery.get("planned_task_id")}
        plan_ids = {routing.get("plan_version_record_id"), eligibility.get("plan_version_record_id"), route.get("plan_version_record_id"), auth.get("plan_version_record_id"), delegation.get("plan_version_record_id"), delivery.get("plan_version_record_id")}
        same_lineage = len(task_ids) == 1 and len(plan_ids) == 1 and next(iter(plan_ids)) == (active_plan or {}).get("plan_version_record_id")
        route_ok = route.get("decision_status") == "ROUTE_SELECTED" and route.get("selected_subsystem") == "CTI" and route.get("selected_capability") == "cti.read.context"
        auth_ok = auth.get("authorization_status") == "AUTHORIZED" and bool(auth.get("authorization_granted")) and auth.get("route_decision_id") == route.get("route_decision_id")
        handoff_ok = delegation.get("delegation_authorization_id") == auth.get("delegation_authorization_id") and delivery.get("delegation_id") == delegation.get("delegation_id") and delivery.get("ownership_status") == "ACCEPTED"
    else:
        same_lineage = route_ok = auth_ok = handoff_ok = False
    _check(checks, "MISSION_PLAN_TASK_LINEAGE_CONTINUITY", same_lineage, same_lineage, True)
    _check(checks, "DETERMINISTIC_ROUTE_SELECTION", route_ok, None if not route else {"status": route.get("decision_status"), "subsystem": route.get("selected_subsystem"), "capability": route.get("selected_capability")}, {"status": "ROUTE_SELECTED", "subsystem": "CTI", "capability": "cti.read.context"})
    _check(checks, "AUTHORITATIVE_PRE_DELEGATION_ALLOW", auth_ok, None if not auth else {"status": auth.get("authorization_status"), "granted": auth.get("authorization_granted"), "policy_decision_id": auth.get("policy_decision_id")}, {"status": "AUTHORIZED", "granted": True, "policy_decision_id": "NONEMPTY"})
    _check(checks, "HANDOFF_ACK_AND_OWNERSHIP_CONTINUITY", handoff_ok, None if not delivery else {"delegation_id": delivery.get("delegation_id"), "ownership_status": delivery.get("ownership_status")}, {"delegation_bound": True, "ownership_status": "ACCEPTED"})

    downstream_zero = all(int(repository_counts.get(k, 0)) == 0 for k in (
        "mission_execution_dispatches", "mission_dispatch_eligibility_gates", "mission_pre_dispatch_governance_revalidations",
        "mission_execution_attempts", "mission_execution_deliveries", "mission_execution_running_projections", "mission_execution_result_captures"))
    _check(checks, "NO_STAGE3_9_5_DISPATCH_OR_EXECUTION", downstream_zero, downstream_zero, True)
    observed_event_types = [e.get("event_type") for e in events]
    _check(checks, "EXACT_EVENT_SEQUENCE", observed_event_types == list(ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES), observed_event_types, list(ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES))
    _check(checks, "EVENT_LEDGER_INTEGRITY", event_integrity_status == "PASS", event_integrity_status, "PASS")
    nonzero = {k: int(v) for k, v in repository_counts.items() if int(v) != 0}
    expected_counts = dict(ROUTING_DELEGATION_GOVERNANCE_ALLOWED_NONZERO_REPOSITORY_COUNTS)
    _check(checks, "EXACT_SEGMENT_REPOSITORY_FOOTPRINT", nonzero == expected_counts, nonzero, expected_counts)

    failures = [c["check_id"] for c in checks if c["status"] != "PASS"]
    contract = canonical_routing_delegation_governance_qualification_contract()
    return {
        "schema_version": ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_SCHEMA_VERSION,
        "segment": "ROUTING_TO_DELEGATION_TO_GOVERNANCE_CONTINUITY",
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "qualification_contract_sha256": contract["integrity"]["canonical_sha256"],
        "mission_id": mission_id, "run_id": run_id,
        "status": "QUALIFIED" if not failures else "REJECTED", "qualified": not failures,
        "failed_check_ids": failures, "checks": checks,
        "segment_head": {
            "state": state.get("state"), "state_version": state.get("state_version"),
            "active_plan_version": None if not active_plan else active_plan.get("plan_version"),
            "ready_task_keys": ready_keys, "blocked_task_keys": blocked_keys,
            "routing_intent_id": None if not routing else routing.get("routing_intent_id"),
            "route_decision_id": None if not route else route.get("route_decision_id"),
            "delegation_authorization_id": None if not auth else auth.get("delegation_authorization_id"),
            "policy_decision_id": None if not auth else auth.get("policy_decision_id"),
            "delegation_id": None if not delegation else delegation.get("delegation_id"),
            "delivery_receipt_id": None if not delivery else delivery.get("delivery_receipt_id"),
            "ownership_status": None if not delivery else delivery.get("ownership_status"),
            "event_count": len(events),
        },
        "authority_boundary": {
            "verification_read_only": True, "authoritative_governance_required": True,
            "new_governance_decision_authority_added": False, "new_routing_authority_added": False,
            "new_delegation_authority_added": False, "dispatch_performed": False,
            "execution_authorized": False, "target_actuation": False,
            "pre_dispatch_governance_revalidation_required": True,
        },
    }


def canonical_routing_delegation_governance_qualification_definition() -> dict[str, Any]:
    contract = canonical_routing_delegation_governance_qualification_contract()
    return {
        "schema_version": ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_SCHEMA_VERSION,
        "mode": ROUTING_DELEGATION_GOVERNANCE_QUALIFICATION_MODE,
        "predecessor_control": ROUTING_DELEGATION_GOVERNANCE_PREDECESSOR_CONTROL,
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": ROUTING_DELEGATION_GOVERNANCE_EXPECTED_MIGRATION_LEVEL,
        "ready_task_key": ROUTING_DELEGATION_GOVERNANCE_READY_TASK_KEY,
        "selected_subsystem": ROUTING_DELEGATION_GOVERNANCE_SELECTED_SUBSYSTEM,
        "selected_capability": ROUTING_DELEGATION_GOVERNANCE_SELECTED_CAPABILITY,
        "runtime_verifier_read_only": True,
        "authoritative_governance_required": True,
        "pre_dispatch_governance_revalidation_required": True,
        "new_database_migration_added": False, "new_durable_store_added": False,
        "new_dispatch_authority_added": False, "new_execution_authority_added": False,
        "next_stage": ROUTING_DELEGATION_GOVERNANCE_NEXT_STAGE,
    }
