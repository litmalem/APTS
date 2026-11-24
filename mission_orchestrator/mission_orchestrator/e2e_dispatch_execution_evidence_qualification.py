from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .canonical import verify_envelope
from .delegation_authorization import verify_delegation_authorization_contract
from .delegation_delivery import verify_delivery_receipt_contract
from .delegation_handoff import verify_delegation_contract
from .dispatch_eligibility import verify_dispatch_eligibility_contract
from .e2e_mission_acceptance import E2E_MISSION_SCENARIO_ID, materialize_canonical_e2e_mission_request
from .e2e_routing_delegation_governance_qualification import (
    ROUTING_DELEGATION_GOVERNANCE_ALLOWED_NONZERO_REPOSITORY_COUNTS,
    ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES,
    canonical_routing_delegation_governance_qualification_contract,
)
from .execution_attempt import verify_execution_attempt_contract
from .execution_delivery import verify_execution_delivery_contract
from .execution_dispatch import verify_execution_dispatch_contract
from .execution_lineage import EXECUTION_EVENT_TYPES
from .execution_result import verify_execution_result_capture_contract
from .execution_running import verify_running_execution_projection_contract
from .governance_binding import verify_binding_contract
from .pre_dispatch_governance import verify_pre_dispatch_revalidation_contract
from .scope_contract import verify_contract as verify_scope_contract
from .task_route_selection import verify_task_route_selection_contract
from .task_readiness_projection import verify_task_readiness_projection_contract

DISPATCH_EXECUTION_EVIDENCE_SCHEMA_VERSION = "apts-stage3.9-dispatch-execution-evidence-continuity-v1"
DISPATCH_EXECUTION_EVIDENCE_HASH_DOMAIN = "MISSION_STAGE3_9_5_DISPATCH_EXECUTION_EVIDENCE_CONTINUITY_V1"
DISPATCH_EXECUTION_EVIDENCE_MODE = "EXISTING_STAGE3_5_AUTHORITIES_READ_ONLY_DURABLE_CONTINUITY_VERIFICATION"
DISPATCH_EXECUTION_EVIDENCE_PREDECESSOR_CONTROL = "stage3.9.4-routing-delegation-governance-continuity"
DISPATCH_EXECUTION_EVIDENCE_EXPECTED_MIGRATION_LEVEL = 53
DISPATCH_EXECUTION_EVIDENCE_NEXT_STAGE = "3.9.6"
DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES = (
    *ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES,
    "MISSION_STATE_TRANSITIONED",
    "MISSION_COMMAND_COMPLETED",
    *EXECUTION_EVENT_TYPES[:7],
)
DISPATCH_EXECUTION_EVIDENCE_EXPECTED_NONZERO_COUNTS = {
    **ROUTING_DELEGATION_GOVERNANCE_ALLOWED_NONZERO_REPOSITORY_COUNTS,
    "mission_state_transitions": 3,
    "mission_command_journal": 3,
    "mission_events": len(DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES),
    "mission_execution_dispatch_contracts": 1,
    "mission_execution_dispatch_eligibility_gates": 1,
    "mission_pre_dispatch_governance_revalidations": 1,
    "mission_execution_attempts": 1,
    "mission_execution_deliveries": 1,
    "mission_execution_running_projections": 1,
    "mission_execution_result_captures": 1,
}


def build_running_start_request(*, run_id: str, expected_version_sha256: str,
                                expected_state_version: int) -> dict[str, Any]:
    materialize_canonical_e2e_mission_request(run_id)
    if not isinstance(expected_version_sha256, str) or len(expected_version_sha256) != 64:
        raise ValueError("expected_version_sha256 must be a 64-character digest")
    if not isinstance(expected_state_version, int) or isinstance(expected_state_version, bool) or expected_state_version < 1:
        raise ValueError("expected_state_version must be a positive integer")
    return {
        "command_id": f"stage395-{run_id}-start",
        "idempotency_key": f"stage395-{run_id}-start",
        "command": "START",
        "expected_version_sha256": expected_version_sha256,
        "expected_state_version": expected_state_version,
        "actor": "stage3.9.5-acceptance-runner",
        "reason_code": "STAGE395_START_RUNNING",
        "reason": "Enter RUNNING before Stage 3.5 dispatch eligibility and fresh governance revalidation",
        "evidence_refs": [f"evidence:stage3.9.5:{run_id}:start"],
        "metadata": {"stage": "3.9.5", "scenario_id": E2E_MISSION_SCENARIO_ID,
                     "run_id": run_id, "segment": "DISPATCH_TO_EXECUTION_TO_EVIDENCE"},
    }


def _sha(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def canonical_dispatch_execution_evidence_contract() -> dict[str, Any]:
    predecessor = canonical_routing_delegation_governance_qualification_contract()
    core = {
        "schema_version": DISPATCH_EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "mode": DISPATCH_EXECUTION_EVIDENCE_MODE,
        "predecessor_control": DISPATCH_EXECUTION_EVIDENCE_PREDECESSOR_CONTROL,
        "predecessor_contract_sha256": predecessor["integrity"]["canonical_sha256"],
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "expected_repository_migration_level": DISPATCH_EXECUTION_EVIDENCE_EXPECTED_MIGRATION_LEVEL,
        "database_change_mode": "NO_NEW_DATABASE_MIGRATION",
        "persistence_mode": "EXISTING_STAGE3_1_THROUGH_STAGE3_5_STORES_ONLY",
        "existing_authority_sequence": [
            "STAGE3_2_START_RUNNING", "STAGE3_5_1_DISPATCH_IDENTITY",
            "STAGE3_5_2_STATIC_ELIGIBILITY", "STAGE3_5_3_FRESH_AUTHORITATIVE_GOVERNANCE_REVALIDATION",
            "STAGE3_5_4_IDEMPOTENT_ATTEMPT_AND_ENVELOPE", "STAGE3_5_5_RUNTIME_DELIVERY_ACKNOWLEDGEMENT",
            "STAGE3_5_6_RUNNING_HEARTBEAT", "STAGE3_5_7_TERMINAL_RESULT_EVIDENCE_ARTIFACTS",
        ],
        "qualified_segment_head": {
            "state": "RUNNING", "state_version": 4,
            "active_plan_version": 1, "executed_task_key": "collect-cti",
            "blocked_task_keys": ["analyze-cti", "report-findings"],
            "execution_state": "SUCCEEDED", "evidence_required": True,
            "task_completion_performed": False, "mission_completion_performed": False,
        },
        "expected_event_types": list(DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES),
        "expected_repository_nonzero_counts": dict(DISPATCH_EXECUTION_EVIDENCE_EXPECTED_NONZERO_COUNTS),
        "continuity_requirements": {
            "one_mission_plan_task_and_route": True,
            "handoff_ack_precedes_dispatch_identity": True,
            "eligibility_is_not_execution_authority": True,
            "fresh_governance_allow_precedes_dispatch_commit_and_delivery": True,
            "one_initial_attempt_and_envelope_per_dispatch": True,
            "delivery_ack_precedes_running_heartbeat_and_result": True,
            "runtime_result_contains_hash_bound_evidence_and_artifact_references": True,
            "execution_result_is_not_task_or_mission_completion": True,
            "failure_termination_and_recovery_use_existing_stage3_5_controls": True,
        },
        "verification_boundary": {
            "runtime_verifier_read_only": True, "governance_query_performed": False,
            "runtime_io_performed": False, "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False, "task_completion_performed": False,
            "mission_completion_performed": False, "target_actuation": False,
            "new_database_migration_added": False, "new_durable_store_added": False,
            "new_governance_authority_added": False, "new_dispatch_authority_added": False,
            "new_execution_authority_added": False,
        },
        "next_stage": DISPATCH_EXECUTION_EVIDENCE_NEXT_STAGE,
    }
    return {**core, "integrity": {"hash_domain": DISPATCH_EXECUTION_EVIDENCE_HASH_DOMAIN,
                                   "canonical_sha256": _sha({"hash_domain": DISPATCH_EXECUTION_EVIDENCE_HASH_DOMAIN, "core": core})}}


def verify_dispatch_execution_evidence_contract(contract: Mapping[str, Any]) -> bool:
    try:
        return dict(contract) == canonical_dispatch_execution_evidence_contract()
    except (TypeError, ValueError, KeyError):
        return False


def canonical_dispatch_execution_evidence_definition() -> dict[str, Any]:
    contract = canonical_dispatch_execution_evidence_contract()
    return {
        "schema_version": DISPATCH_EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "mode": DISPATCH_EXECUTION_EVIDENCE_MODE,
        "predecessor_control": DISPATCH_EXECUTION_EVIDENCE_PREDECESSOR_CONTROL,
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "expected_repository_migration_level": DISPATCH_EXECUTION_EVIDENCE_EXPECTED_MIGRATION_LEVEL,
        "runtime_verifier_read_only": True,
        "authoritative_pre_dispatch_governance_allow_required": True,
        "evidence_required": True,
        "new_database_migration_added": False,
        "new_durable_store_added": False,
        "new_dispatch_authority_added": False,
        "new_execution_authority_added": False,
        "next_stage": DISPATCH_EXECUTION_EVIDENCE_NEXT_STAGE,
    }


def _one(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return rows[0] if len(rows) == 1 else {}


def _valid(row: Mapping[str, Any], field: str, verifier: Any) -> bool:
    contract = row.get(field)
    return bool(isinstance(contract, Mapping) and verifier(contract)
                and row.get("canonical_sha256") == (
                    contract.get("canonical_sha256") or contract.get("integrity", {}).get("canonical_sha256")))


def evaluate_dispatch_execution_evidence_qualification(
    *, mission_id: str, envelope: Mapping[str, Any], state: Mapping[str, Any],
    active_plan: Mapping[str, Any] | None, readiness: Mapping[str, Any] | None,
    scope: Mapping[str, Any] | None, binding: Mapping[str, Any] | None,
    routing_intents: Sequence[Mapping[str, Any]], routes: Sequence[Mapping[str, Any]],
    authorizations: Sequence[Mapping[str, Any]], delegations: Sequence[Mapping[str, Any]],
    handoffs: Sequence[Mapping[str, Any]], dispatches: Sequence[Mapping[str, Any]],
    gates: Sequence[Mapping[str, Any]], revalidations: Sequence[Mapping[str, Any]],
    attempts: Sequence[Mapping[str, Any]], deliveries: Sequence[Mapping[str, Any]],
    running_projections: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]], repository_counts: Mapping[str, int],
    event_integrity_status: str, repository_integrity_status: str,
    execution_lineage: Mapping[str, Any],
    execution_replay: Mapping[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, observed: Any = None) -> None:
        checks.append({"check_id": name, "status": "PASS" if passed else "FAIL", "observed": observed})

    meta = envelope.get("metadata") if isinstance(envelope.get("metadata"), Mapping) else {}
    run_id = meta.get("run_id")
    try:
        run_valid = isinstance(run_id, str) and bool(materialize_canonical_e2e_mission_request(run_id))
    except ValueError:
        run_valid = False
    check("CANONICAL_MISSION_ROOT", run_valid and meta.get("scenario_id") == E2E_MISSION_SCENARIO_ID
          and verify_envelope(envelope) and state.get("mission_id") == mission_id, run_id)
    check("MISSION_RUNNING_NO_COMPLETION", state.get("state") == "RUNNING"
          and state.get("state_version") == 4 and state.get("terminal") is False,
          {"state": state.get("state"), "state_version": state.get("state_version")})
    check("PREDECESSOR_EXACT_EVENT_PREFIX", [e.get("event_type") for e in events[:22]]
          == list(ROUTING_DELEGATION_GOVERNANCE_EXPECTED_EVENT_TYPES))
    check("EXACT_START_AND_EXECUTION_EVENT_ORDER", [e.get("event_type") for e in events]
          == list(DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES))
    check("EVENT_LEDGER_INTEGRITY", event_integrity_status == "PASS", event_integrity_status)
    check("DURABLE_REPOSITORY_INTEGRITY", repository_integrity_status == "PASS", repository_integrity_status)
    counts = {k: int(v) for k, v in repository_counts.items() if int(v) != 0}
    check("EXACT_DURABLE_SEGMENT_FOOTPRINT", counts == DISPATCH_EXECUTION_EVIDENCE_EXPECTED_NONZERO_COUNTS, counts)

    rows = (routing_intents, routes, authorizations, delegations, handoffs, dispatches,
            gates, revalidations, attempts, deliveries, running_projections, results)
    check("SINGLE_CAUSAL_TRAJECTORY_NO_RETRY_DUPLICATES", all(len(group) == 1 for group in rows),
          [len(group) for group in rows])
    intent, route, auth, delegation, handoff, dispatch, gate, reval, attempt, delivery, running, result = map(_one, rows)
    predecessor_integrity = bool(
        active_plan and readiness and scope and binding
        and verify_task_readiness_projection_contract(readiness.get("projection_contract", {}))
        and verify_scope_contract(scope.get("contract", {}))
        and verify_binding_contract(binding.get("binding", {}))
        and _valid(route, "route_selection_contract", verify_task_route_selection_contract)
        and _valid(auth, "delegation_authorization_contract", verify_delegation_authorization_contract)
        and _valid(delegation, "delegation_contract", verify_delegation_contract)
        and _valid(handoff, "delivery_receipt_contract", verify_delivery_receipt_contract)
    )
    check("PREDECESSOR_DURABLE_AUTHORITY_INTEGRITY", predecessor_integrity)
    active_id = (active_plan or {}).get("plan_version_record_id")
    task_id = intent.get("planned_task_id")
    predecessor_binding = bool(
        active_plan and int(active_plan.get("plan_version", 0)) == 1
        and readiness and readiness.get("projection_id")
        and readiness.get("projection_contract", {}).get("projection", {}).get("ready_task_keys") == ["collect-cti"]
        and readiness.get("projection_contract", {}).get("projection", {}).get("blocked_task_keys") == ["analyze-cti", "report-findings"]
        and all(row.get("mission_id") == mission_id and row.get("plan_version_record_id") == active_id
                and row.get("planned_task_id") == task_id for row in (intent, route, auth, delegation, handoff))
        and task_id and route.get("route_decision_id") == auth.get("route_decision_id")
        and auth.get("authorization_status") == "AUTHORIZED" and auth.get("authorization_granted") is True
        and auth.get("policy_decision_id") and delegation.get("delegation_authorization_id") == auth.get("delegation_authorization_id")
        and handoff.get("delegation_id") == delegation.get("delegation_id")
        and handoff.get("ownership_status") == "ACCEPTED"
        and route.get("selected_subsystem") == "CTI" and route.get("selected_capability") == "cti.read.context"
        and binding.get("binding", {}).get("canonical_scope_binding", {}).get("mission_scope_sha256") == scope.get("canonical_sha256")
    )
    check("HANDOFF_OWNERSHIP_GOVERNANCE_TASK_CONTINUITY", predecessor_binding)

    execution_rows = (
        (dispatch, "execution_dispatch_contract", verify_execution_dispatch_contract),
        (gate, "dispatch_eligibility_contract", verify_dispatch_eligibility_contract),
        (reval, "pre_dispatch_revalidation_contract", verify_pre_dispatch_revalidation_contract),
        (attempt, "execution_attempt_contract", verify_execution_attempt_contract),
        (delivery, "execution_delivery_contract", verify_execution_delivery_contract),
        (running, "running_execution_projection_contract", verify_running_execution_projection_contract),
        (result, "execution_result_capture_contract", verify_execution_result_capture_contract),
    )
    check("STAGE3_5_CANONICAL_ARTIFACT_INTEGRITY", all(_valid(*item) for item in execution_rows))
    check("PLAN_TASK_MISSION_AND_ROUTE_BOUND_THROUGH_EXECUTION", bool(task_id and active_id and all(
        row.get("mission_id") == mission_id and row.get("plan_version_record_id") == active_id
        and row.get("planned_task_id") == task_id and row.get("task_key") == "collect-cti"
        for row in (dispatch, gate, reval, attempt, delivery, running, result))
        and dispatch.get("delivery_receipt_id") == handoff.get("delivery_receipt_id")
        and dispatch.get("delegation_id") == delegation.get("delegation_id")
        and dispatch.get("route_decision_id") == route.get("route_decision_id")
        and dispatch.get("delegation_authorization_id") == auth.get("delegation_authorization_id")
        and dispatch.get("target_subsystem") == "CTI" and dispatch.get("target_capability") == "cti.read.context"))
    check("ELIGIBILITY_BEFORE_FRESH_GOVERNANCE_ALLOW", bool(
        gate.get("execution_dispatch_id") == dispatch.get("execution_dispatch_id")
        and gate.get("task_readiness_projection_id") == (readiness or {}).get("projection_id")
        and gate.get("gate_result") == "PASSED" and gate.get("failed_precondition_count") == 0
        and reval.get("execution_dispatch_id") == dispatch.get("execution_dispatch_id")
        and reval.get("dispatch_eligibility_id") == gate.get("dispatch_eligibility_id")
        and reval.get("revalidation_sequence") == 1 and reval.get("governance_decision") == "ALLOW"
        and reval.get("execution_authorized") is True
        and reval.get("policy_decision_id") and reval.get("policy_decision_hash")))
    attempt_id = attempt.get("execution_attempt_id")
    envelope_id = attempt.get("dispatch_envelope_id")
    check("ONE_AUTHORIZED_DURABLE_ATTEMPT_AND_ENVELOPE", bool(
        isinstance(attempt_id, str) and attempt_id.startswith("xattempt-")
        and isinstance(envelope_id, str) and envelope_id.startswith("xenv-")
        and attempt.get("attempt_ordinal") == 1
        and attempt.get("execution_attempt_contract", {}).get("execution_attempt", {}).get("execution_authorized") is True
        and attempt.get("execution_dispatch_id") == dispatch.get("execution_dispatch_id")
        and attempt.get("dispatch_eligibility_id") == gate.get("dispatch_eligibility_id")
        and attempt.get("pre_dispatch_revalidation_id") == reval.get("pre_dispatch_revalidation_id")))
    check("DELIVERY_ACK_BOUND_TO_AUTHORIZED_ENVELOPE", bool(
        delivery.get("execution_attempt_id") == attempt_id
        and delivery.get("dispatch_envelope_id") == envelope_id
        and delivery.get("execution_dispatch_id") == dispatch.get("execution_dispatch_id")
        and delivery.get("delivery_status") == "DELIVERED_TO_RUNTIME"
        and delivery.get("acknowledgement_status") == "ACKNOWLEDGED_ACCEPTED_FOR_EXECUTION"
        and delivery.get("recipient_subsystem_id") == "CTI"))
    check("RUNNING_HEARTBEAT_BOUND_TO_SAME_ATTEMPT", bool(
        running.get("execution_delivery_id") == delivery.get("execution_delivery_id")
        and running.get("execution_attempt_id") == attempt_id
        and running.get("dispatch_envelope_id") == envelope_id
        and running.get("execution_dispatch_id") == dispatch.get("execution_dispatch_id")
        and running.get("execution_state") == "RUNNING" and running.get("heartbeat_sequence") == 1
        and running.get("policy_decision_id") == reval.get("policy_decision_id")
        and running.get("policy_decision_hash") == reval.get("policy_decision_hash")))
    result_contract = result.get("execution_result_capture_contract", {})
    evidence = result_contract.get("evidence_manifest", {}) if isinstance(result_contract, Mapping) else {}
    artifacts = result_contract.get("artifact_manifest", {}) if isinstance(result_contract, Mapping) else {}
    check("TERMINAL_RESULT_EVIDENCE_PROVENANCE_INTEGRITY", bool(
        result.get("running_projection_id") == running.get("running_projection_id")
        and result.get("execution_delivery_id") == delivery.get("execution_delivery_id")
        and result.get("execution_attempt_id") == attempt_id
        and result.get("dispatch_envelope_id") == envelope_id
        and result.get("execution_dispatch_id") == dispatch.get("execution_dispatch_id")
        and result.get("execution_state") == "SUCCEEDED"
        and result.get("recipient_subsystem_id") == "CTI"
        and result.get("runtime_endpoint") == delivery.get("runtime_endpoint")
        and result.get("policy_decision_id") == reval.get("policy_decision_id")
        and result.get("policy_decision_hash") == reval.get("policy_decision_hash")
        and result.get("evidence_count", 0) >= 1
        and result.get("evidence_count") == evidence.get("evidence_count")
        and result.get("evidence_manifest_sha256") == evidence.get("manifest_sha256")
        and result.get("artifact_count") == artifacts.get("artifact_count")
        and result.get("artifact_manifest_sha256") == artifacts.get("manifest_sha256")
        and all(isinstance(item.get("sha256"), str) and len(item["sha256"]) == 64
                for item in (*evidence.get("items", []), *artifacts.get("items", [])))))
    replay_core = execution_replay.get("replay", {})
    expected_refs = (
        (dispatch, "execution_dispatch_id"), (gate, "dispatch_eligibility_id"),
        (reval, "pre_dispatch_revalidation_id"), (attempt, "execution_attempt_id"),
        (delivery, "execution_delivery_id"), (running, "running_projection_id"),
        (result, "result_capture_id"),
    )
    replay_events = replay_core.get("events", [])
    check("EXECUTION_EVENTS_BIND_DURABLE_ARTIFACT_IDENTITIES_AND_HASHES", len(replay_events) == 7
          and all(event.get("event_type") == event_type and event.get("artifact_id") == row.get(key)
                  and event.get("artifact_sha256") == row.get("canonical_sha256")
                  for event, event_type, (row, key) in zip(replay_events, EXECUTION_EVENT_TYPES[:7], expected_refs)))
    check("EXECUTION_EVENT_LINEAGE_AND_READ_ONLY_REPLAY", bool(
        execution_lineage.get("integrity_status") == "PASS"
        and execution_lineage.get("full_mission_event_chain_verified") is True
        and execution_lineage.get("execution_event_count") == 7
        and execution_lineage.get("checkpoint_count") == 0
        and execution_replay.get("read_only") is True
        and execution_replay.get("side_effects_performed") is False
        and replay_core.get("execution_event_count") == 7
        and replay_core.get("execution_event_tip_sha256") == execution_lineage.get("execution_event_tip_sha256")))
    check("EXECUTION_IS_NOT_TASK_OR_MISSION_COMPLETION", state.get("state") == "RUNNING"
          and all(int(repository_counts.get(key, 0)) == 0 for key in (
              "mission_execution_termination_controls", "mission_execution_outcome_propagations",
              "mission_execution_recovery_checkpoints", "mission_task_outcomes",
              "mission_task_terminality_eligibility_gates", "mission_task_evidence_binding_verifications",
              "mission_task_completion_commits", "mission_outcome_aggregations",
              "mission_success_criteria_evaluations", "mission_verified_completion_declarations")))

    contract = canonical_dispatch_execution_evidence_contract()
    failures = [item["check_id"] for item in checks if item["status"] != "PASS"]
    return {
        "schema_version": DISPATCH_EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "segment": "DISPATCH_TO_EXECUTION_TO_EVIDENCE_CONTINUITY",
        "source_scenario_id": E2E_MISSION_SCENARIO_ID,
        "predecessor_contract_sha256": contract["predecessor_contract_sha256"],
        "qualification_contract_sha256": contract["integrity"]["canonical_sha256"],
        "mission_id": mission_id, "run_id": run_id,
        "status": "QUALIFIED" if not failures else "REJECTED", "qualified": not failures,
        "failed_check_ids": failures, "checks": checks,
        "segment_head": {
            "state": state.get("state"), "state_version": state.get("state_version"),
            "active_plan_version": (active_plan or {}).get("plan_version"),
            "planned_task_id": task_id, "route_decision_id": route.get("route_decision_id"),
            "delegation_id": delegation.get("delegation_id"),
            "execution_dispatch_id": dispatch.get("execution_dispatch_id"),
            "dispatch_eligibility_id": gate.get("dispatch_eligibility_id"),
            "pre_dispatch_revalidation_id": reval.get("pre_dispatch_revalidation_id"),
            "policy_decision_id": reval.get("policy_decision_id"),
            "execution_attempt_id": attempt_id, "dispatch_envelope_id": envelope_id,
            "execution_delivery_id": delivery.get("execution_delivery_id"),
            "running_projection_id": running.get("running_projection_id"),
            "result_capture_id": result.get("result_capture_id"),
            "execution_state": result.get("execution_state"),
            "evidence_count": result.get("evidence_count"),
            "artifact_count": result.get("artifact_count"),
            "event_count": len(events),
        },
        "authority_boundary": {
            "verification_read_only": True, "governance_query_performed": False,
            "runtime_io_performed": False, "dispatch_redelivery_performed": False,
            "new_execution_attempt_created": False, "task_completion_performed": False,
            "mission_completion_performed": False, "target_actuation": False,
        },
    }
