from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

REPOSITORY_SCHEMA_VERSION = "apts-mission-repository-v1"
PERSISTENCE_MANIFEST_SCHEMA_VERSION = "apts-mission-persistence-manifest-v1"
REPOSITORY_HASH_DOMAIN = "MISSION_PERSISTENCE_MANIFEST_V1"
REPOSITORY_MIGRATION_LEVEL = 53
REPOSITORY_MODEL = "NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS"
REPOSITORY_SOURCE_OF_TRUTH = "MISSION_ORCHESTRATOR_DATABASE"
REPOSITORY_RECOVERY_MODE = "DURABLE_RECONSTRUCTION_NO_IN_MEMORY_SOURCE_OF_TRUTH"
REPOSITORY_INTEGRITY_MODE = "CANONICAL_HASH_AND_RELATIONAL_HEAD_CHAIN_VERIFICATION"

REPOSITORY_STORES = (
    "mission_repository_metadata",
    "global_missions",
    "mission_envelopes",
    "mission_states",
    "mission_state_transitions",
    "mission_scope_contract_heads",
    "mission_scope_contract_versions",
    "mission_governance_binding_heads",
    "mission_governance_binding_versions",
    "mission_governance_binding_operations",
    "mission_authorization_operations",
    "mission_authorization_bindings",
    "mission_routed_tasks",
    "mission_task_dispatch_attempts",
    "mission_command_journal",
    "mission_plans",
    "mission_planner_input_snapshots",
    "mission_task_decompositions",
    "mission_planned_tasks",
    "mission_task_dependency_graphs",
    "mission_task_dependency_edges",
    "mission_planner_invocations",
    "mission_generated_plans",
    "mission_plan_validations",
    "mission_plan_version_heads",
    "mission_plan_versions",
    "mission_task_readiness_projections",
    "mission_planning_recovery_checkpoints",
    "mission_task_routing_intents",
    "mission_task_routing_eligibility_gates",
    "mission_task_route_decisions",
    "mission_delegation_authorizations",
    "mission_task_delegations",
    "mission_delegation_deliveries",
    "mission_delegation_recovery_controls",
    "mission_routing_delegation_recovery_checkpoints",
    "mission_execution_dispatch_contracts",
    "mission_execution_dispatch_eligibility_gates",
    "mission_pre_dispatch_governance_revalidations",
    "mission_execution_attempts",
    "mission_execution_deliveries",
    "mission_execution_running_projections",
    "mission_execution_result_captures",
    "mission_execution_termination_controls",
    "mission_execution_outcome_propagations",
    "mission_execution_recovery_checkpoints",
    "mission_task_outcomes",
    "mission_task_terminality_eligibility_gates",
    "mission_task_evidence_binding_verifications",
    "mission_task_completion_commits",
    "mission_outcome_aggregations",
    "mission_success_criteria_evaluations",
    "mission_completion_readiness_decisions",
    "mission_verified_completion_declarations",
    "mission_outcome_recovery_checkpoints",
    "mission_adaptation_replan_contracts",
    "mission_adaptation_trigger_classifications",
    "mission_replan_eligibility_governance_gates",
    "mission_replan_snapshots",
    "mission_replan_candidates",
    "mission_replan_decisions",
    "mission_replan_commits",
    "mission_replan_handoffs",
    "mission_replan_recovery_checkpoints",
    "mission_events",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def persistence_manifest_core(
    *,
    mission_id: str,
    identity: Mapping[str, Any],
    envelope_sha256: str,
    state: Mapping[str, Any],
    transitions: list[Mapping[str, Any]],
    scope_head: Mapping[str, Any] | None,
    scope_versions: list[Mapping[str, Any]],
    governance_head: Mapping[str, Any] | None,
    governance_versions: list[Mapping[str, Any]],
    governance_operations: list[Mapping[str, Any]],
    authorization_operations: list[Mapping[str, Any]],
    authorization_bindings: list[Mapping[str, Any]],
    routed_tasks: list[Mapping[str, Any]],
    dispatch_attempts: list[Mapping[str, Any]],
    commands: list[Mapping[str, Any]],
    plan: Mapping[str, Any] | None,
    planner_input_snapshot: Mapping[str, Any] | None,
    task_decomposition: Mapping[str, Any] | None,
    planned_tasks: list[Mapping[str, Any]],
    task_dependency_graph: Mapping[str, Any] | None,
    task_dependency_edges: list[Mapping[str, Any]],
    planner_invocation: Mapping[str, Any] | None,
    generated_plan: Mapping[str, Any] | None,
    plan_validation: Mapping[str, Any] | None,
    plan_version_head: Mapping[str, Any] | None,
    plan_versions: list[Mapping[str, Any]],
    task_readiness_projections: list[Mapping[str, Any]],
    planning_recovery_checkpoints: list[Mapping[str, Any]],
    task_routing_intents: list[Mapping[str, Any]],
    task_routing_eligibility_gates: list[Mapping[str, Any]],
    task_route_decisions: list[Mapping[str, Any]],
    delegation_authorizations: list[Mapping[str, Any]],
    task_delegations: list[Mapping[str, Any]],
    delegation_deliveries: list[Mapping[str, Any]],
    delegation_recovery_controls: list[Mapping[str, Any]],
    routing_delegation_recovery_checkpoints: list[Mapping[str, Any]],
    execution_dispatch_contracts: list[Mapping[str, Any]],
    dispatch_eligibility_gates: list[Mapping[str, Any]],
    pre_dispatch_revalidations: list[Mapping[str, Any]],
    execution_attempts: list[Mapping[str, Any]],
    execution_deliveries: list[Mapping[str, Any]],
    execution_running_projections: list[Mapping[str, Any]],
    execution_result_captures: list[Mapping[str, Any]],
    execution_termination_controls: list[Mapping[str, Any]],
    execution_outcome_propagations: list[Mapping[str, Any]],
    execution_recovery_checkpoints: list[Mapping[str, Any]],
    task_outcomes: list[Mapping[str, Any]],
    task_terminality_eligibility_gates: list[Mapping[str, Any]],
    task_evidence_binding_verifications: list[Mapping[str, Any]],
    task_completion_commits: list[Mapping[str, Any]],
    mission_outcome_aggregations: list[Mapping[str, Any]],
    mission_success_criteria_evaluations: list[Mapping[str, Any]],
    mission_completion_readiness_decisions: list[Mapping[str, Any]],
    mission_verified_completion_declarations: list[Mapping[str, Any]],
    outcome_recovery_checkpoints: list[Mapping[str, Any]],
    adaptation_replans: list[Mapping[str, Any]],
    adaptation_trigger_classifications: list[Mapping[str, Any]],
    replan_eligibility_governance_gates: list[Mapping[str, Any]],
    replan_snapshots: list[Mapping[str, Any]],
    replan_candidates: list[Mapping[str, Any]],
    replan_validations: list[Mapping[str, Any]],
    replan_commits: list[Mapping[str, Any]],
    replan_handoffs: list[Mapping[str, Any]],
    replan_recovery_checkpoints: list[Mapping[str, Any]],
    events: list[Mapping[str, Any]],
    record_counts: Mapping[str, int],
) -> dict[str, Any]:
    """Build a stable, local-only durable repository projection.

    Volatile observation timestamps and live external CTI/Governance reads are deliberately
    excluded. The hash therefore changes only when durable Mission Orchestrator state changes.
    """

    def transition_ref(t: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "transition_id": t["transition_id"],
            "from_state": t["from_state"],
            "to_state": t["to_state"],
            "from_state_version": int(t["from_state_version"]),
            "to_state_version": int(t["to_state_version"]),
            "reason_code": t["reason_code"],
        }

    def scope_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "snapshot_id": v["snapshot_id"],
            "contract_version": int(v["contract_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
        }

    def governance_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "binding_snapshot_id": v["binding_snapshot_id"],
            "binding_version": int(v["binding_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "mission_scope_snapshot_id": v["mission_scope_snapshot_id"],
            "mission_scope_sha256": v["mission_scope_sha256"],
            "governance_scope_contract_id": v["governance_scope_contract_id"],
            "governance_scope_version": int(v["governance_scope_version"]),
            "governance_scope_contract_hash": v["governance_scope_contract_hash"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
        }

    def operation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "operation_id": v["operation_id"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "status": v["status"],
        }

    def authorization_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "authorization_binding_id": v["authorization_binding_id"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "governance_binding_version": int(v["governance_binding_version"]),
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "scope_version": int(v["scope_version"]),
            "decision": v["decision"],
        }

    def task_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "task_id": v["task_id"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "destination_subsystem": v["destination_subsystem"],
            "destination_component": v["destination_component"],
            "capability_id": v["capability_id"],
            "task_status": v["task_status"],
        }

    def attempt_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "dispatch_attempt_id": v["dispatch_attempt_id"],
            "task_id": v["task_id"],
            "attempt_no": int(v["attempt_no"]),
            "status": v["status"],
            "recovered_after_response_loss": bool(v.get("recovered_after_response_loss")),
            "external_mission_id": v.get("external_mission_id"),
        }

    def command_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "command_id": v["command_id"],
            "idempotency_key": v["idempotency_key"],
            "operation": v["operation"],
            "request_sha256": v["request_sha256"],
            "expected_version_sha256": v["expected_version_sha256"],
            "status": v["status"],
            "before_version_sha256": None if v.get("before_version_vector") is None else v["before_version_vector"].get("integrity", {}).get("canonical_sha256"),
            "after_version_sha256": None if v.get("after_version_vector") is None else v["after_version_vector"].get("integrity", {}).get("canonical_sha256"),
        }

    def plan_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_transition_id": v["source_transition_id"],
        }

    def planner_input_snapshot_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "snapshot_id": v["snapshot_id"],
            "snapshot_version": int(v["snapshot_version"]),
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_plan_sha256": v["source_plan_sha256"],
        }

    def task_decomposition_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "decomposition_id": v["decomposition_id"],
            "decomposition_version": int(v["decomposition_version"]),
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "snapshot_id": v["snapshot_id"],
            "snapshot_version": int(v["snapshot_version"]),
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "task_set_sha256": v["task_set_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_plan_sha256": v["source_plan_sha256"],
            "source_snapshot_sha256": v["source_snapshot_sha256"],
            "source_version_sha256": v["source_version_sha256"],
            "task_count": int(v["task_count"]),
        }

    def planned_task_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "planned_task_id": v["planned_task_id"],
            "decomposition_id": v["decomposition_id"],
            "decomposition_version": int(v["decomposition_version"]),
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "snapshot_id": v["snapshot_id"],
            "snapshot_version": int(v["snapshot_version"]),
            "task_key": v["task_key"],
            "task_index": int(v["task_index"]),
            "schema_version": v["schema_version"],
            "canonical_sha256": v["canonical_sha256"],
            "required_subsystem": v["required_subsystem"],
            "required_capability": v["required_capability"],
            "task_status": v["task_status"],
        }

    def task_dependency_graph_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "graph_id": v["graph_id"],
            "graph_version": int(v["graph_version"]),
            "decomposition_id": v["decomposition_id"],
            "decomposition_version": int(v["decomposition_version"]),
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "snapshot_id": v["snapshot_id"],
            "snapshot_version": int(v["snapshot_version"]),
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "node_set_sha256": v["node_set_sha256"],
            "edge_set_sha256": v["edge_set_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_plan_sha256": v["source_plan_sha256"],
            "source_snapshot_sha256": v["source_snapshot_sha256"],
            "source_decomposition_sha256": v["source_decomposition_sha256"],
            "source_task_set_sha256": v["source_task_set_sha256"],
            "source_version_sha256": v["source_version_sha256"],
            "node_count": int(v["node_count"]),
            "edge_count": int(v["edge_count"]),
            "validation_status": v["validation_status"],
        }

    def task_dependency_edge_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "dependency_edge_id": v["dependency_edge_id"],
            "graph_id": v["graph_id"],
            "graph_version": int(v["graph_version"]),
            "decomposition_id": v["decomposition_id"],
            "from_planned_task_id": v["from_planned_task_id"],
            "from_task_key": v["from_task_key"],
            "to_planned_task_id": v["to_planned_task_id"],
            "to_task_key": v["to_task_key"],
            "schema_version": v["schema_version"],
            "canonical_sha256": v["canonical_sha256"],
        }

    def planner_invocation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "planner_invocation_id": v["planner_invocation_id"],
            "generation_version": int(v["generation_version"]),
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "snapshot_id": v["snapshot_id"],
            "snapshot_version": int(v["snapshot_version"]),
            "decomposition_id": v["decomposition_id"],
            "decomposition_version": int(v["decomposition_version"]),
            "graph_id": v["graph_id"],
            "graph_version": int(v["graph_version"]),
            "schema_version": v["schema_version"],
            "planner_profile": v["planner_profile"],
            "planner_engine": v["planner_engine"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "output_sha256": v["output_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
            "source_plan_sha256": v["source_plan_sha256"],
            "source_snapshot_sha256": v["source_snapshot_sha256"],
            "source_decomposition_sha256": v["source_decomposition_sha256"],
            "source_task_set_sha256": v["source_task_set_sha256"],
            "source_graph_sha256": v["source_graph_sha256"],
            "source_node_set_sha256": v["source_node_set_sha256"],
            "source_edge_set_sha256": v["source_edge_set_sha256"],
        }

    def generated_plan_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "generated_plan_id": v["generated_plan_id"],
            "planner_invocation_id": v["planner_invocation_id"],
            "generation_version": int(v["generation_version"]),
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "schema_version": v["schema_version"],
            "status": v["status"],
            "planner_profile": v["planner_profile"],
            "planner_output_sha256": v["planner_output_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "task_count": int(v["task_count"]),
            "dependency_edge_count": int(v["dependency_edge_count"]),
            "planning_layer_count": int(v["planning_layer_count"]),
        }

    def plan_validation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "plan_validation_id": v["plan_validation_id"],
            "validation_version": int(v["validation_version"]),
            "plan_id": v["plan_id"],
            "plan_version": int(v["plan_version"]),
            "generated_plan_id": v["generated_plan_id"],
            "generation_version": int(v["generation_version"]),
            "schema_version": v["schema_version"],
            "status": v["status"],
            "feasible": bool(v["feasible"]),
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
            "source_generated_plan_sha256": v["source_generated_plan_sha256"],
        }

    def plan_version_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "plan_version_record_id": v["plan_version_record_id"],
            "mission_id": v["mission_id"],
            "canonical_plan_id": v["canonical_plan_id"],
            "plan_version": int(v["plan_version"]),
            "activation_type": v["activation_type"],
            "predecessor_plan_version_record_id": v.get("predecessor_plan_version_record_id"),
            "predecessor_plan_version": None if v.get("predecessor_plan_version") is None else int(v["predecessor_plan_version"]),
            "replan_id": v.get("replan_id"),
            "replan_transition_id": v.get("replan_transition_id"),
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "candidate_plan_sha256": v["candidate_plan_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def task_readiness_projection_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "projection_id": v["projection_id"],
            "mission_id": v["mission_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
            "ready_task_count": int(v["ready_task_count"]),
            "blocked_task_count": int(v["blocked_task_count"]),
            "task_count": int(v["task_count"]),
            "wave_count": int(v["wave_count"]),
        }

    def planning_recovery_checkpoint_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "checkpoint_id": v["checkpoint_id"],
            "mission_id": v["mission_id"],
            "checkpoint_version": int(v["checkpoint_version"]),
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
            "source_event_count": int(v["source_event_count"]),
            "source_event_tip_sha256": v["source_event_tip_sha256"],
            "readiness_projection_id": v["readiness_projection_id"],
            "readiness_projection_sha256": v["readiness_projection_sha256"],
        }

    def task_routing_intent_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "routing_intent_id": v["routing_intent_id"],
            "mission_id": v["mission_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "readiness_projection_id": v["readiness_projection_id"],
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "registry_id": v["registry_id"],
            "registry_version": int(v["registry_version"]),
            "registry_sha256": v["registry_sha256"],
            "resolution_status": v["resolution_status"],
            "candidate_count": int(v["candidate_count"]),
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def task_routing_eligibility_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "eligibility_gate_id": v["eligibility_gate_id"],
            "mission_id": v["mission_id"],
            "routing_intent_id": v["routing_intent_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "readiness_projection_id": v["readiness_projection_id"],
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "registry_id": v["registry_id"],
            "registry_version": int(v["registry_version"]),
            "registry_sha256": v["registry_sha256"],
            "routing_intent_sha256": v["routing_intent_sha256"],
            "gate_result": v["gate_result"],
            "eligibility_status": v["eligibility_status"],
            "candidate_count": int(v["candidate_count"]),
            "eligible_candidate_count": int(v["eligible_candidate_count"]),
            "ineligible_candidate_count": int(v["ineligible_candidate_count"]),
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def task_route_decision_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "route_decision_id": v["route_decision_id"],
            "mission_id": v["mission_id"],
            "eligibility_gate_id": v["eligibility_gate_id"],
            "routing_intent_id": v["routing_intent_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "readiness_projection_id": v["readiness_projection_id"],
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "schema_version": v["schema_version"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "registry_id": v["registry_id"],
            "registry_version": int(v["registry_version"]),
            "registry_sha256": v["registry_sha256"],
            "routing_intent_sha256": v["routing_intent_sha256"],
            "eligibility_gate_sha256": v["eligibility_gate_sha256"],
            "decision_status": v["decision_status"],
            "route_selected": bool(v["route_selected"]),
            "eligible_candidate_count": int(v["eligible_candidate_count"]),
            "selected_subsystem": v.get("selected_subsystem"),
            "selected_capability": v.get("selected_capability"),
            "canonical_sha256": v["canonical_sha256"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def delegation_authorization_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "delegation_authorization_id": v["delegation_authorization_id"],
            "route_decision_id": v["route_decision_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "authorization_status": v["authorization_status"],
            "authorization_granted": bool(v["authorization_granted"]),
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "canonical_sha256": v["canonical_sha256"],
        }

    def task_delegation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "delegation_id": v["delegation_id"],
            "handoff_envelope_id": v["handoff_envelope_id"],
            "delegation_authorization_id": v["delegation_authorization_id"],
            "route_decision_id": v["route_decision_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "delegation_status": v["delegation_status"],
            "selected_subsystem": v["selected_subsystem"],
            "selected_capability": v["selected_capability"],
            "handoff_envelope_sha256": v["handoff_envelope_sha256"],
            "canonical_sha256": v["canonical_sha256"],
        }

    def delegation_delivery_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "delivery_receipt_id": v["delivery_receipt_id"],
            "delegation_id": v["delegation_id"],
            "handoff_envelope_id": v["handoff_envelope_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "delivery_status": v["delivery_status"],
            "acknowledgement_status": v["acknowledgement_status"],
            "ownership_status": v["ownership_status"],
            "recipient_subsystem": v["recipient_subsystem"],
            "recipient_capability": v["recipient_capability"],
            "delegation_sha256": v["delegation_sha256"],
            "handoff_envelope_sha256": v["handoff_envelope_sha256"],
            "canonical_sha256": v["canonical_sha256"],
        }

    def delegation_recovery_control_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "recovery_control_id": v["recovery_control_id"],
            "delivery_receipt_id": v["delivery_receipt_id"],
            "delegation_id": v["delegation_id"],
            "route_decision_id": v["route_decision_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "control_sequence": int(v["control_sequence"]),
            "control_action": v["control_action"],
            "control_outcome": v["control_outcome"],
            "current_owner_subsystem": v["current_owner_subsystem"],
            "current_owner_capability": v["current_owner_capability"],
            "proposed_subsystem": v.get("proposed_subsystem"),
            "proposed_capability": v.get("proposed_capability"),
            "retry_ordinal": v.get("retry_ordinal"),
            "conflict_status": v["conflict_status"],
            "canonical_sha256": v["canonical_sha256"],
        }

    def routing_delegation_recovery_checkpoint_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "checkpoint_id": v["checkpoint_id"],
            "checkpoint_version": int(v["checkpoint_version"]),
            "delivery_receipt_id": v["delivery_receipt_id"],
            "delegation_id": v["delegation_id"],
            "route_decision_id": v["route_decision_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "recovery_control_count": int(v["recovery_control_count"]),
            "source_event_count": int(v["source_event_count"]),
            "source_event_tip_sha256": v["source_event_tip_sha256"],
            "canonical_sha256": v["canonical_sha256"],
        }

    def execution_dispatch_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "execution_dispatch_id": v["execution_dispatch_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "delivery_receipt_id": v["delivery_receipt_id"],
            "delegation_id": v["delegation_id"],
            "handoff_envelope_id": v["handoff_envelope_id"],
            "route_decision_id": v["route_decision_id"],
            "delegation_authorization_id": v["delegation_authorization_id"],
            "dispatch_status": v["dispatch_status"],
            "target_subsystem": v["target_subsystem"],
            "target_capability": v["target_capability"],
            "target_capability_version": int(v["target_capability_version"]),
            "delivery_receipt_sha256": v["delivery_receipt_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def dispatch_eligibility_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "dispatch_eligibility_id": v["dispatch_eligibility_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "task_readiness_projection_id": v["task_readiness_projection_id"],
            "gate_result": v["gate_result"],
            "eligibility_status": v["eligibility_status"],
            "execution_precondition_status": v["execution_precondition_status"],
            "precondition_count": int(v["precondition_count"]),
            "satisfied_precondition_count": int(v["satisfied_precondition_count"]),
            "failed_precondition_count": int(v["failed_precondition_count"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def pre_dispatch_revalidation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "pre_dispatch_revalidation_id": v["pre_dispatch_revalidation_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "dispatch_eligibility_id": v["dispatch_eligibility_id"],
            "revalidation_sequence": int(v["revalidation_sequence"]),
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "static_revalidation_status": v["static_revalidation_status"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "governance_decision": v["governance_decision"],
            "policy_version": int(v["policy_version"]),
            "execution_authorization_status": v["execution_authorization_status"],
            "execution_authorized": bool(v["execution_authorized"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def execution_attempt_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "execution_attempt_id": v["execution_attempt_id"],
            "dispatch_envelope_id": v["dispatch_envelope_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "dispatch_eligibility_id": v["dispatch_eligibility_id"],
            "pre_dispatch_revalidation_id": v["pre_dispatch_revalidation_id"],
            "attempt_ordinal": int(v["attempt_ordinal"]),
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "dispatch_commit_status": v["dispatch_commit_status"],
            "execution_attempt_status": v["execution_attempt_status"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def execution_delivery_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "execution_delivery_id": v["execution_delivery_id"],
            "execution_attempt_id": v["execution_attempt_id"],
            "dispatch_envelope_id": v["dispatch_envelope_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "delivery_status": v["delivery_status"],
            "acknowledgement_status": v["acknowledgement_status"],
            "execution_attempt_status": v["execution_attempt_status"],
            "recipient_subsystem_id": v["recipient_subsystem_id"],
            "recipient_capability_id": v["recipient_capability_id"],
            "runtime_health_sha256": v["runtime_health_sha256"],
            "acknowledgement_id": v["acknowledgement_id"],
            "acknowledgement_sha256": v["acknowledgement_sha256"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def execution_running_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "running_projection_id": v["running_projection_id"],
            "execution_delivery_id": v["execution_delivery_id"],
            "execution_attempt_id": v["execution_attempt_id"],
            "dispatch_envelope_id": v["dispatch_envelope_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "execution_state": v["execution_state"],
            "execution_attempt_status": v["execution_attempt_status"],
            "heartbeat_id": v["heartbeat_id"],
            "heartbeat_sequence": int(v["heartbeat_sequence"]),
            "heartbeat_at": v["heartbeat_at"],
            "heartbeat_status": v["heartbeat_status"],
            "heartbeat_sha256": v["heartbeat_sha256"],
            "recipient_subsystem_id": v["recipient_subsystem_id"],
            "recipient_capability_id": v["recipient_capability_id"],
            "runtime_health_sha256": v["runtime_health_sha256"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def execution_result_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "result_capture_id": v["result_capture_id"],
            "running_projection_id": v["running_projection_id"],
            "execution_delivery_id": v["execution_delivery_id"],
            "execution_attempt_id": v["execution_attempt_id"],
            "dispatch_envelope_id": v["dispatch_envelope_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "execution_state": v["execution_state"],
            "execution_attempt_status": v["execution_attempt_status"],
            "completed_at": v["completed_at"],
            "evidence_count": int(v["evidence_count"]),
            "evidence_manifest_sha256": v["evidence_manifest_sha256"],
            "artifact_count": int(v["artifact_count"]),
            "artifact_manifest_sha256": v["artifact_manifest_sha256"],
            "recipient_subsystem_id": v["recipient_subsystem_id"],
            "recipient_capability_id": v["recipient_capability_id"],
            "runtime_health_sha256": v["runtime_health_sha256"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def execution_termination_control_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "termination_control_id": v["termination_control_id"],
            "running_projection_id": v["running_projection_id"],
            "execution_delivery_id": v["execution_delivery_id"],
            "execution_attempt_id": v["execution_attempt_id"],
            "dispatch_envelope_id": v["dispatch_envelope_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "control_action": v["control_action"],
            "expected_terminal_state": v["expected_terminal_state"],
            "control_status": v["control_status"],
            "acknowledged_at": v["acknowledged_at"],
            "runtime_health_sha256": v["runtime_health_sha256"],
            "acknowledgement_sha256": v["acknowledgement_sha256"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def execution_outcome_propagation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "outcome_propagation_id": v["outcome_propagation_id"],
            "result_capture_id": v["result_capture_id"],
            "termination_control_id": v.get("termination_control_id"),
            "execution_attempt_id": v["execution_attempt_id"],
            "dispatch_envelope_id": v["dispatch_envelope_id"],
            "execution_dispatch_id": v["execution_dispatch_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "execution_state": v["execution_state"],
            "outcome_classification": v["outcome_classification"],
            "task_outcome_status": v["task_outcome_status"],
            "propagation_action": v["propagation_action"],
            "lifecycle_command": v.get("lifecycle_command"),
            "lifecycle_command_id": v.get("lifecycle_command_id"),
            "transition_id": v.get("transition_id"),
            "resulting_mission_state": v["resulting_mission_state"],
            "resulting_state_version": int(v["resulting_state_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def execution_recovery_checkpoint_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "checkpoint_id": v["checkpoint_id"],
            "checkpoint_version": int(v["checkpoint_version"]),
            "outcome_propagation_id": v["outcome_propagation_id"],
            "result_capture_id": v["result_capture_id"],
            "termination_control_id": v.get("termination_control_id"),
            "execution_attempt_id": v["execution_attempt_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
            "source_event_count": int(v["source_event_count"]),
            "source_event_tip_sha256": v["source_event_tip_sha256"],
        }

    def task_outcome_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "task_outcome_id": v["task_outcome_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "execution_attempt_id": v["execution_attempt_id"],
            "result_capture_id": v["result_capture_id"],
            "outcome_propagation_id": v["outcome_propagation_id"],
            "execution_recovery_checkpoint_id": v["execution_recovery_checkpoint_id"],
            "contract_status": v["contract_status"],
            "execution_state": v["execution_state"],
            "source_task_outcome_status": v["source_task_outcome_status"],
            "outcome_classification": v["outcome_classification"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def task_terminality_eligibility_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "eligibility_gate_id": v["eligibility_gate_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "task_outcome_id": v["task_outcome_id"],
            "gate_status": v["gate_status"],
            "terminality_confirmed": bool(v["terminality_confirmed"]),
            "terminality_status": v["terminality_status"],
            "completion_eligibility_status": v["completion_eligibility_status"],
            "completion_eligible": bool(v["completion_eligible"]),
            "eligibility_reason_code": v["eligibility_reason_code"],
            "task_outcome_sha256": v["task_outcome_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def task_evidence_binding_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "verification_id": v["verification_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "task_outcome_id": v["task_outcome_id"],
            "eligibility_gate_id": v["eligibility_gate_id"],
            "result_capture_id": v["result_capture_id"],
            "verification_status": v["verification_status"],
            "evidence_binding_verified": bool(v["evidence_binding_verified"]),
            "artifact_binding_verified": bool(v["artifact_binding_verified"]),
            "evidence_reference_count": int(v["evidence_reference_count"]),
            "artifact_reference_count": int(v["artifact_reference_count"]),
            "evidence_manifest_sha256": v["evidence_manifest_sha256"],
            "artifact_manifest_sha256": v["artifact_manifest_sha256"],
            "task_outcome_sha256": v["task_outcome_sha256"],
            "eligibility_gate_sha256": v["eligibility_gate_sha256"],
            "result_capture_sha256": v["result_capture_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def task_completion_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "task_completion_id": v["task_completion_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "planned_task_id": v["planned_task_id"],
            "task_key": v["task_key"],
            "evidence_binding_verification_id": v["evidence_binding_verification_id"],
            "task_outcome_id": v["task_outcome_id"],
            "eligibility_gate_id": v["eligibility_gate_id"],
            "completion_status": v["completion_status"],
            "task_outcome_accepted": bool(v["task_outcome_accepted"]),
            "task_completion_committed": bool(v["task_completion_committed"]),
            "dependency_status": v["dependency_status"],
            "dependency_count": int(v["dependency_count"]),
            "completed_dependency_count": int(v["completed_dependency_count"]),
            "dependency_binding_sha256": v["dependency_binding_sha256"],
            "evidence_binding_verification_sha256": v["evidence_binding_verification_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def mission_outcome_aggregation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "aggregation_id": v["aggregation_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "aggregation_status": v["aggregation_status"],
            "task_count": int(v["task_count"]),
            "terminal_task_count": int(v["terminal_task_count"]),
            "verified_complete_count": int(v["verified_complete_count"]),
            "failed_count": int(v["failed_count"]),
            "cancelled_count": int(v["cancelled_count"]),
            "timed_out_count": int(v["timed_out_count"]),
            "running_count": int(v["running_count"]),
            "blocked_count": int(v["blocked_count"]),
            "pending_count": int(v["pending_count"]),
            "all_tasks_terminal": bool(v["all_tasks_terminal"]),
            "all_tasks_verified_complete": bool(v["all_tasks_verified_complete"]),
            "source_snapshot_sha256": v["source_snapshot_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def mission_success_evaluation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "evaluation_id": v["evaluation_id"], "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]), "aggregation_id": v["aggregation_id"],
            "evaluation_status": v["evaluation_status"], "overall_result": v["overall_result"],
            "criterion_count": int(v["criterion_count"]), "satisfied_count": int(v["satisfied_count"]),
            "not_satisfied_count": int(v["not_satisfied_count"]), "indeterminate_count": int(v["indeterminate_count"]),
            "success_criteria_sha256": v["success_criteria_sha256"], "aggregation_sha256": v["aggregation_sha256"],
            "canonical_sha256": v["canonical_sha256"], "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"], "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]), "source_version_sha256": v["source_version_sha256"],
        }

    def completion_readiness_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "readiness_id": v["readiness_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "evaluation_id": v["evaluation_id"],
            "readiness_result": v["readiness_result"],
            "completion_ready": bool(v["completion_ready"]),
            "blocker_count": int(v["blocker_count"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
        }

    def verified_completion_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "declaration_id": v["declaration_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "readiness_id": v["readiness_id"],
            "evaluation_id": v["evaluation_id"],
            "declaration_status": v["declaration_status"],
            "readiness_sha256": v["readiness_sha256"],
            "evaluation_sha256": v["evaluation_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def outcome_recovery_checkpoint_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "checkpoint_id": v["checkpoint_id"],
            "checkpoint_version": int(v["checkpoint_version"]),
            "declaration_id": v["declaration_id"],
            "plan_version_record_id": v["plan_version_record_id"],
            "plan_version": int(v["plan_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
            "source_event_count": int(v["source_event_count"]),
            "source_event_tip_sha256": v["source_event_tip_sha256"],
        }

    def adaptation_replan_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "adaptation_episode_id": v["adaptation_episode_id"],
            "replan_trigger_id": v["replan_trigger_id"],
            "source_plan_version_record_id": v["source_plan_version_record_id"],
            "source_plan_version": int(v["source_plan_version"]),
            "source_plan_generation": int(v["source_plan_generation"]),
            "target_plan_generation": int(v["target_plan_generation"]),
            "episode_state": v["episode_state"],
            "trigger_source": v["trigger_source"],
            "trigger_code": v["trigger_code"],
            "source_event_id": v.get("source_event_id"),
            "source_event_sha256": v.get("source_event_sha256"),
            "evidence_ref_count": int(v["evidence_ref_count"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def adaptation_trigger_classification_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "classification_id": v["classification_id"],
            "adaptation_episode_id": v["adaptation_episode_id"],
            "replan_trigger_id": v["replan_trigger_id"],
            "source_plan_version_record_id": v["source_plan_version_record_id"],
            "source_plan_version": int(v["source_plan_version"]),
            "source_plan_generation": int(v["source_plan_generation"]),
            "canonical_plan_id": v["canonical_plan_id"],
            "classification_status": v["classification_status"],
            "reason_code": v["reason_code"],
            "severity": v["severity"],
            "replan_scope_level": v["replan_scope_level"],
            "source_stage": v["source_stage"],
            "source_event_id": v.get("source_event_id"),
            "source_event_sha256": v.get("source_event_sha256"),
            "evidence_ref_count": int(v["evidence_ref_count"]),
            "detection_event_id": v["detection_event_id"],
            "detection_event_sha256": v["detection_event_sha256"],
            "source_adaptation_replan_sha256": v["source_adaptation_replan_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def replan_eligibility_governance_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "eligibility_gate_id": v["eligibility_gate_id"],
            "classification_id": v["classification_id"],
            "adaptation_episode_id": v["adaptation_episode_id"],
            "replan_trigger_id": v["replan_trigger_id"],
            "source_plan_version_record_id": v["source_plan_version_record_id"],
            "source_plan_version": int(v["source_plan_version"]),
            "source_plan_generation": int(v["source_plan_generation"]),
            "canonical_plan_id": v["canonical_plan_id"],
            "static_eligibility_status": v["static_eligibility_status"],
            "eligibility_status": v["eligibility_status"],
            "replan_eligible": bool(v["replan_eligible"]),
            "governance_decision": v["governance_decision"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_request_id": v["policy_request_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "governance_scope_contract_id": v["governance_scope_contract_id"],
            "governance_scope_version": int(v["governance_scope_version"]),
            "mission_scope_snapshot_id": v["mission_scope_snapshot_id"],
            "governance_binding_snapshot_id": v["governance_binding_snapshot_id"],
            "governance_binding_version": int(v["governance_binding_version"]),
            "source_classification_sha256": v["source_classification_sha256"],
            "source_adaptation_replan_sha256": v["source_adaptation_replan_sha256"],
            "classification_event_id": v["classification_event_id"],
            "classification_event_sha256": v["classification_event_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def replan_snapshot_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "replan_snapshot_id": v["replan_snapshot_id"],
            "adaptation_episode_id": v["adaptation_episode_id"],
            "replan_trigger_id": v["replan_trigger_id"],
            "classification_id": v["classification_id"],
            "eligibility_gate_id": v["eligibility_gate_id"],
            "source_plan_version_record_id": v["source_plan_version_record_id"],
            "source_plan_version": int(v["source_plan_version"]),
            "source_plan_generation": int(v["source_plan_generation"]),
            "target_plan_generation": int(v["target_plan_generation"]),
            "canonical_plan_id": v["canonical_plan_id"],
            "snapshot_status": v["snapshot_status"],
            "source_adaptation_replan_sha256": v["source_adaptation_replan_sha256"],
            "source_classification_sha256": v["source_classification_sha256"],
            "source_eligibility_sha256": v["source_eligibility_sha256"],
            "policy_decision_hash": v["policy_decision_hash"],
            "mission_scope_snapshot_id": v["mission_scope_snapshot_id"],
            "governance_binding_snapshot_id": v["governance_binding_snapshot_id"],
            "governance_binding_version": int(v["governance_binding_version"]),
            "task_context_sha256": v["task_context_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def replan_candidate_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "replan_candidate_id": v["replan_candidate_id"],
            "planner_invocation_id": v["planner_invocation_id"],
            "replan_snapshot_id": v["replan_snapshot_id"],
            "adaptation_episode_id": v["adaptation_episode_id"],
            "source_plan_version_record_id": v["source_plan_version_record_id"],
            "source_plan_version": int(v["source_plan_version"]),
            "candidate_plan_version": int(v["candidate_plan_version"]),
            "candidate_plan_generation": int(v["candidate_plan_generation"]),
            "candidate_status": v["candidate_status"],
            "source_replan_snapshot_sha256": v["source_replan_snapshot_sha256"],
            "task_context_sha256": v["task_context_sha256"],
            "source_plan_sha256": v["source_plan_sha256"],
            "candidate_payload_sha256": v["candidate_payload_sha256"],
            "planner_invocation_sha256": v["planner_invocation_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def replan_validation_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "replan_validation_id": v["replan_validation_id"],
            "replan_candidate_id": v["replan_candidate_id"],
            "replan_snapshot_id": v["replan_snapshot_id"],
            "adaptation_episode_id": v["adaptation_episode_id"],
            "source_plan_version_record_id": v["source_plan_version_record_id"],
            "source_plan_version": int(v["source_plan_version"]),
            "candidate_plan_version": int(v["candidate_plan_version"]),
            "candidate_plan_generation": int(v["candidate_plan_generation"]),
            "validation_status": v["validation_status"],
            "feasible": bool(v["feasible"]),
            "failed_check_count": int(v["failed_check_count"]),
            "source_replan_candidate_sha256": v["source_replan_candidate_sha256"],
            "candidate_payload_sha256": v["candidate_payload_sha256"],
            "source_replan_snapshot_sha256": v["source_replan_snapshot_sha256"],
            "source_plan_sha256": v["source_plan_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def replan_commit_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "replan_commit_id": v["replan_commit_id"],
            "replan_validation_id": v["replan_validation_id"],
            "replan_candidate_id": v["replan_candidate_id"],
            "replan_snapshot_id": v["replan_snapshot_id"],
            "adaptation_episode_id": v["adaptation_episode_id"],
            "replan_trigger_id": v["replan_trigger_id"],
            "eligibility_gate_id": v["eligibility_gate_id"],
            "predecessor_plan_version_record_id": v["predecessor_plan_version_record_id"],
            "predecessor_plan_version": int(v["predecessor_plan_version"]),
            "successor_plan_version_record_id": v["successor_plan_version_record_id"],
            "successor_plan_version": int(v["successor_plan_version"]),
            "candidate_plan_generation": int(v["candidate_plan_generation"]),
            "authorization_operation_id": v["authorization_operation_id"],
            "policy_decision_id": v["policy_decision_id"],
            "policy_decision_hash": v["policy_decision_hash"],
            "policy_version": int(v["policy_version"]),
            "governance_decision": v["governance_decision"],
            "commit_status": v["commit_status"],
            "source_replan_validation_sha256": v["source_replan_validation_sha256"],
            "source_replan_candidate_sha256": v["source_replan_candidate_sha256"],
            "candidate_payload_sha256": v["candidate_payload_sha256"],
            "source_replan_snapshot_sha256": v["source_replan_snapshot_sha256"],
            "source_plan_sha256": v["source_plan_sha256"],
            "successor_plan_sha256": v["successor_plan_sha256"],
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
        }

    def replan_handoff_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "replan_handoff_id": v["replan_handoff_id"],
            "replan_commit_id": v["replan_commit_id"],
            "adaptation_episode_id": v["adaptation_episode_id"],
            "replan_trigger_id": v["replan_trigger_id"],
            "predecessor_plan_version_record_id": v["predecessor_plan_version_record_id"],
            "predecessor_plan_version": int(v["predecessor_plan_version"]),
            "successor_plan_version_record_id": v["successor_plan_version_record_id"],
            "successor_plan_version": int(v["successor_plan_version"]),
            "handoff_status": v["handoff_status"],
            "source_replan_commit_sha256": v["source_replan_commit_sha256"],
            "predecessor_plan_sha256": v["predecessor_plan_sha256"],
            "successor_plan_sha256": v["successor_plan_sha256"],
            "task_disposition_count": int(v["task_disposition_count"]),
            "keep_count": int(v["keep_count"]),
            "drain_count": int(v["drain_count"]),
            "cancel_count": int(v["cancel_count"]),
            "supersede_count": int(v["supersede_count"]),
            "replace_count": int(v["replace_count"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
        }

    def replan_recovery_checkpoint_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "checkpoint_id": v["checkpoint_id"],
            "checkpoint_version": int(v["checkpoint_version"]),
            "adaptation_episode_id": v["adaptation_episode_id"],
            "replan_trigger_id": v["replan_trigger_id"],
            "replan_handoff_id": v["replan_handoff_id"],
            "successor_plan_version_record_id": v["successor_plan_version_record_id"],
            "successor_plan_version": int(v["successor_plan_version"]),
            "canonical_sha256": v["canonical_sha256"],
            "request_sha256": v["request_sha256"],
            "idempotency_key": v["idempotency_key"],
            "source_state": v["source_state"],
            "source_state_version": int(v["source_state_version"]),
            "source_version_sha256": v["source_version_sha256"],
            "source_event_count": int(v["source_event_count"]),
            "source_event_tip_sha256": v["source_event_tip_sha256"],
        }

    def event_ref(v: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "event_id": v["event_id"],
            "trace_id": v["trace_id"],
            "correlation_id": v["correlation_id"],
            "causation_id": v.get("causation_id"),
            "parent_event_id": v.get("parent_event_id"),
            "source_component": v["source_component"],
            "event_type": v["event_type"],
            "state_version": v.get("state_version"),
            "plan_version": v.get("plan_version"),
            "policy_version": v.get("policy_version"),
            "canonical_sha256": v["canonical_sha256"],
            "previous_event_sha256": v.get("previous_event_sha256"),
            "occurred_at": v["occurred_at"],
        }

    return {
        "schema_version": PERSISTENCE_MANIFEST_SCHEMA_VERSION,
        "repository_schema_version": REPOSITORY_SCHEMA_VERSION,
        "repository_migration_level": REPOSITORY_MIGRATION_LEVEL,
        "mission_id": mission_id,
        "identity": {
            "envelope_id": identity["envelope_id"],
            "envelope_version": int(identity["envelope_version"]),
            "correlation_id": identity["correlation_id"],
            "parent_mission_id": identity.get("parent_mission_id"),
            "source_system": identity["source_system"],
            "idempotency_key": identity["idempotency_key"],
            "request_sha256": identity["request_sha256"],
            "envelope_sha256": envelope_sha256,
        },
        "current_state": {
            "state": state["state"],
            "state_version": int(state["state_version"]),
            "terminal": bool(state["terminal"]),
            "last_transition_id": state.get("last_transition_id"),
            "last_reason_code": state.get("last_reason_code"),
        },
        "state_transition_ledger": [transition_ref(x) for x in transitions],
        "scope_contract_store": {
            "head": None if scope_head is None else {
                "mission_scope_contract_id": scope_head["mission_scope_contract_id"],
                "current_version": int(scope_head["current_version"]),
                "current_snapshot_id": scope_head["current_snapshot_id"],
                "current_sha256": scope_head["current_sha256"],
            },
            "versions": [scope_ref(x) for x in scope_versions],
        },
        "governance_binding_store": {
            "head": None if governance_head is None else {
                "mission_governance_binding_id": governance_head["mission_governance_binding_id"],
                "current_version": int(governance_head["current_version"]),
                "current_binding_snapshot_id": governance_head["current_binding_snapshot_id"],
                "current_scope_snapshot_id": governance_head["current_scope_snapshot_id"],
                "current_governance_scope_contract_id": governance_head["current_governance_scope_contract_id"],
            },
            "versions": [governance_ref(x) for x in governance_versions],
            "operations": [operation_ref(x) for x in governance_operations],
        },
        "authorization_store": {
            "operations": [operation_ref(x) for x in authorization_operations],
            "bindings": [authorization_ref(x) for x in authorization_bindings],
        },
        "routing_store": {
            "tasks": [task_ref(x) for x in routed_tasks],
            "dispatch_attempts": [attempt_ref(x) for x in dispatch_attempts],
        },
        "command_journal": [command_ref(x) for x in commands],
        "mission_plan_store": None if plan is None else plan_ref(plan),
        "planner_input_snapshot_store": None if planner_input_snapshot is None else planner_input_snapshot_ref(planner_input_snapshot),
        "task_decomposition_store": None if task_decomposition is None else task_decomposition_ref(task_decomposition),
        "planned_task_store": [planned_task_ref(x) for x in planned_tasks],
        "task_dependency_graph_store": None if task_dependency_graph is None else task_dependency_graph_ref(task_dependency_graph),
        "task_dependency_edge_store": [task_dependency_edge_ref(x) for x in task_dependency_edges],
        "planner_invocation_store": None if planner_invocation is None else planner_invocation_ref(planner_invocation),
        "generated_plan_store": None if generated_plan is None else generated_plan_ref(generated_plan),
        "plan_validation_store": None if plan_validation is None else plan_validation_ref(plan_validation),
        "plan_versioning_store": {
            "head": None if plan_version_head is None else {
                "mission_id": plan_version_head["mission_id"],
                "active_plan_version_record_id": plan_version_head["active_plan_version_record_id"],
                "active_plan_version": int(plan_version_head["active_plan_version"]),
                "active_plan_sha256": plan_version_head["active_plan_sha256"],
            },
            "versions": [plan_version_ref(x) for x in plan_versions],
        },
        "task_readiness_projection_store": {
            "projections": [task_readiness_projection_ref(x) for x in task_readiness_projections],
        },
        "planning_recovery_checkpoint_store": {
            "checkpoints": [planning_recovery_checkpoint_ref(x) for x in planning_recovery_checkpoints],
        },
        "task_routing_intent_store": {
            "intents": [task_routing_intent_ref(x) for x in task_routing_intents],
        },
        "task_routing_eligibility_store": {
            "gates": [task_routing_eligibility_ref(x) for x in task_routing_eligibility_gates],
        },
        "task_route_selection_store": {
            "decisions": [task_route_decision_ref(x) for x in task_route_decisions],
        },
        "delegation_authorization_store": {
            "authorizations": [delegation_authorization_ref(x) for x in delegation_authorizations],
        },
        "task_delegation_store": {
            "delegations": [task_delegation_ref(x) for x in task_delegations],
        },
        "delegation_delivery_store": {
            "deliveries": [delegation_delivery_ref(x) for x in delegation_deliveries],
        },
        "delegation_recovery_control_store": {
            "controls": [delegation_recovery_control_ref(x) for x in delegation_recovery_controls],
        },
        "routing_delegation_recovery_checkpoint_store": {
            "checkpoints": [routing_delegation_recovery_checkpoint_ref(x) for x in routing_delegation_recovery_checkpoints],
        },
        "execution_dispatch_contract_store": {
            "contracts": [execution_dispatch_ref(x) for x in execution_dispatch_contracts],
        },
        "dispatch_eligibility_execution_preconditions_store": {
            "gates": [dispatch_eligibility_ref(x) for x in dispatch_eligibility_gates],
        },
        "authoritative_pre_dispatch_governance_revalidation_store": {
            "revalidations": [pre_dispatch_revalidation_ref(x) for x in pre_dispatch_revalidations],
        },
        "idempotent_dispatch_execution_attempt_store": {
            "attempts": [execution_attempt_ref(x) for x in execution_attempts],
        },
        "dispatch_delivery_execution_acknowledgement_store": {
            "deliveries": [execution_delivery_ref(x) for x in execution_deliveries],
        },
        "running_execution_state_heartbeat_projection_store": {
            "projections": [execution_running_ref(x) for x in execution_running_projections],
        },
        "execution_result_evidence_artifact_capture_store": {
            "captures": [execution_result_ref(x) for x in execution_result_captures],
        },
        "execution_timeout_cancellation_abort_control_store": {
            "controls": [execution_termination_control_ref(x) for x in execution_termination_controls],
        },
        "execution_terminal_outcome_failure_propagation_store": {
            "propagations": [execution_outcome_propagation_ref(x) for x in execution_outcome_propagations],
        },
        "execution_event_lineage_replay_recovery_store": {
            "checkpoints": [execution_recovery_checkpoint_ref(x) for x in execution_recovery_checkpoints],
        },
        "canonical_task_outcome_store": {
            "outcomes": [task_outcome_ref(x) for x in task_outcomes],
        },
        "task_terminality_completion_eligibility_store": {
            "gates": [task_terminality_eligibility_ref(x) for x in task_terminality_eligibility_gates],
        },
        "task_evidence_binding_verification_store": {
            "verifications": [task_evidence_binding_ref(x) for x in task_evidence_binding_verifications],
        },
        "dependency_aware_task_completion_store": {
            "completions": [task_completion_ref(x) for x in task_completion_commits],
        },
        "mission_outcome_aggregation_store": {
            "aggregations": [mission_outcome_aggregation_ref(x) for x in mission_outcome_aggregations],
        },
        "mission_success_criteria_evaluation_store": {
            "evaluations": [mission_success_evaluation_ref(x) for x in mission_success_criteria_evaluations],
        },
        "mission_completion_readiness_store": {
            "decisions": [completion_readiness_ref(x) for x in mission_completion_readiness_decisions],
        },
        "mission_verified_completion_declaration_store": {
            "declarations": [verified_completion_ref(x) for x in mission_verified_completion_declarations],
        },
        "outcome_lineage_replay_recovery_store": {
            "checkpoints": [outcome_recovery_checkpoint_ref(x) for x in outcome_recovery_checkpoints],
        },
        "canonical_adaptation_replan_store": {
            "episodes": [adaptation_replan_ref(x) for x in adaptation_replans],
        },
        "adaptation_trigger_classification_store": {
            "classifications": [adaptation_trigger_classification_ref(x) for x in adaptation_trigger_classifications],
        },
        "replan_eligibility_governance_store": {
            "gates": [replan_eligibility_governance_ref(x) for x in replan_eligibility_governance_gates],
        },
        "replan_snapshot_context_binding_store": {
            "snapshots": [replan_snapshot_ref(x) for x in replan_snapshots],
        },
        "replan_candidate_generation_store": {
            "candidates": [replan_candidate_ref(x) for x in replan_candidates],
        },
        "replan_candidate_validation_store": {
            "decisions": [replan_validation_ref(x) for x in replan_validations],
        },
        "authoritative_replan_commit_store": {
            "commits": [replan_commit_ref(x) for x in replan_commits],
        },
        "atomic_replan_supersession_handoff_store": {
            "handoffs": [replan_handoff_ref(x) for x in replan_handoffs],
        },
        "adapt_replan_lineage_replay_recovery_store": {
            "checkpoints": [replan_recovery_checkpoint_ref(x) for x in replan_recovery_checkpoints],
        },
        "mission_event_store": [event_ref(x) for x in events],
        "record_counts": {k: int(record_counts[k]) for k in sorted(record_counts)},
    }


def finalize_persistence_manifest(core: Mapping[str, Any], *, reconstructed_at: str) -> dict[str, Any]:
    digest = sha256_hex({"hash_domain": REPOSITORY_HASH_DOMAIN, "manifest": dict(core)})
    return {
        **dict(core),
        "reconstructed_at": reconstructed_at,
        "integrity": {
            "algorithm": "SHA-256",
            "hash_domain": REPOSITORY_HASH_DOMAIN,
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "canonical_sha256": digest,
        },
    }


def verify_persistence_manifest(manifest: Mapping[str, Any]) -> bool:
    try:
        integrity = manifest["integrity"]
        core = {k: v for k, v in manifest.items() if k not in {"reconstructed_at", "integrity"}}
        return (
            integrity.get("hash_domain") == REPOSITORY_HASH_DOMAIN
            and integrity.get("canonical_sha256")
            == sha256_hex({"hash_domain": REPOSITORY_HASH_DOMAIN, "manifest": core})
        )
    except Exception:
        return False
