from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any, Mapping

E2E_MISSION_ACCEPTANCE_SCHEMA_VERSION = "apts-stage3.9-e2e-mission-acceptance-contract-v1"
E2E_MISSION_SCENARIO_SCHEMA_VERSION = "apts-stage3.9-canonical-e2e-mission-scenario-v1"
E2E_MISSION_ACCEPTANCE_HASH_DOMAIN = "MISSION_STAGE3_9_CANONICAL_E2E_ACCEPTANCE_CONTRACT_V1"
E2E_MISSION_SCENARIO_ID = "stage3.9-canonical-e2e-control-plane-mission-v1"
E2E_MISSION_ACCEPTANCE_MODE = (
    "IMMUTABLE_VERSIONED_CANONICAL_CROSS_STAGE_E2E_SCENARIO_"
    "DECLARATION_ONLY_NO_NEW_EXECUTION_AUTHORITY"
)
E2E_MISSION_ACCEPTANCE_BASELINE = "STAGE_3_1_THROUGH_3_8_CLOSED"
E2E_MISSION_ACCEPTANCE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"
E2E_MISSION_ACCEPTANCE_PERSISTENCE_MODE = "STATIC_CONTRACT_DERIVED_NO_NEW_DURABLE_STORE"
E2E_MISSION_ACCEPTANCE_EXPECTED_MIGRATION_LEVEL = 53
E2E_MISSION_ACCEPTANCE_ENVIRONMENT_MODE = (
    "CONTROL_PLANE_SANDBOX_WITH_INJECTED_GOVERNANCE_AND_RUNTIME_DOUBLES_"
    "NO_EXTERNAL_TARGET_ACTUATION"
)
E2E_RUN_ID_TOKEN = "${RUN_ID}"

# Stage 3.9 starts only after the eight preceding Stage-3 domains have been
# closed by their acceptance/regression gates. These controls are prerequisites,
# not authorities newly introduced by Stage 3.9.1.
REQUIRED_STAGE_CLOSURE_CONTROLS = (
    "stage3.1.10-acceptance-regression-gate",
    "stage3.2.10-lifecycle-acceptance-regression-gate",
    "stage3.3.10-planning-acceptance-regression-gate",
    "stage3.4.10-routing-delegation-acceptance-regression-gate",
    "stage3.5.10-execution-dispatch-acceptance-regression-gate",
    "stage3.6.10-outcome-acceptance-regression-gate",
    "stage3.7.10-adapt-replan-acceptance-regression-gate",
    "stage3.8.10-observe-reconstruct-acceptance-regression-gate",
)

# Frozen Stage-3.9 qualification sequence. Stage 3.9.1 only declares this map;
# later substages execute and prove the individual segments.
E2E_ACCEPTANCE_PHASES = (
    ("3.9.1", "CANONICAL_E2E_MISSION_SCENARIO_AND_ACCEPTANCE_CONTRACT"),
    ("3.9.2", "INTAKE_TO_LIFECYCLE"),
    ("3.9.3", "PLANNING_TO_TASK_GRAPH"),
    ("3.9.4", "ROUTING_TO_DELEGATION_TO_GOVERNANCE"),
    ("3.9.5", "DISPATCH_TO_EXECUTION_TO_EVIDENCE"),
    ("3.9.6", "COMPLETION_TO_OUTCOME"),
    ("3.9.7", "ADAPTATION_AND_REPLANNING"),
    ("3.9.8", "RESTART_REPLAY_AND_RECOVERY"),
    ("3.9.9", "OBSERVATION_RECONSTRUCTION_AND_FORENSIC_EQUIVALENCE"),
    ("3.9.10", "GLOBAL_ACCEPTANCE_AND_REGRESSION_GATE"),
)

# Identity namespaces that the canonical scenario must connect without aliasing
# or cross-mission leakage. This list intentionally uses already-owned prefixes;
# Stage 3.9.1 creates none of them.
E2E_REQUIRED_IDENTITY_FAMILIES = (
    ("mission_id", "mission-gmo-"),
    ("envelope_id", "menv-"),
    ("mission_event_id", "mevent-"),
    ("mission_transition_id", "mtrans-"),
    ("plan_id", "mplan-"),
    ("planned_task_id", "ptask-"),
    ("routing_intent_id", "rint-"),
    ("route_decision_id", "rdec-"),
    ("delegation_authorization_id", "dauth-"),
    ("delegation_id", "deleg-"),
    ("handoff_envelope_id", "handoff-"),
    ("execution_dispatch_id", "xdispatch-"),
    ("execution_attempt_id", "xattempt-"),
    ("dispatch_envelope_id", "xenv-"),
    ("execution_result_id", "xresult-"),
    ("task_outcome_id", "toutcome-"),
    ("mission_outcome_aggregation_id", "moutcome-"),
    ("adaptation_episode_id", "adpt-"),
    ("replan_trigger_id", "rpln-"),
    ("replan_snapshot_id", "rpsnap-"),
    ("replan_candidate_id", "rpcand-"),
    ("replan_decision_id", "rpdec-"),
    ("replan_commit_id", "rpcom-"),
)

E2E_ACCEPTANCE_INVARIANTS = (
    "ONE_CANONICAL_MISSION_ID_ROOTS_THE_COMPLETE_E2E_TRAJECTORY",
    "ALL_CHILD_IDENTITIES_REMAIN_BOUND_TO_THE_SAME_MISSION_AND_ACTIVE_PLAN_LINEAGE",
    "MISSION_STATE_TRANSITIONS_FOLLOW_THE_CANONICAL_GUARD_MATRIX",
    "PLAN_TASK_ROUTE_DELEGATION_DISPATCH_EXECUTION_AND_OUTCOME_LINEAGE_IS_SOURCE_BOUND",
    "GOVERNANCE_AUTHORIZATION_PRECEDES_DELEGATION_AND_AUTHORITATIVE_PRE_DISPATCH_REVALIDATION",
    "DISPATCH_AND_EXECUTION_ATTEMPT_IDENTITY_IS_IDEMPOTENT_UNDER_EXACT_REPLAY",
    "EXECUTION_RESULT_EVIDENCE_AND_ARTIFACTS_ARE_HASH_BOUND_BEFORE_TASK_COMPLETION",
    "DEPENDENCY_AWARE_TASK_COMPLETION_PRECEDES_MISSION_OUTCOME_AGGREGATION",
    "MISSION_SUCCESS_CRITERIA_MUST_BE_SATISFIED_BEFORE_VERIFIED_COMPLETION",
    "ADAPTATION_REPLAN_MAY_ONLY_MATERIALIZE_FROM_AN_ELIGIBLE_NONTERMINAL_SOURCE_STATE",
    "REPLAY_RECOVERY_MUST_RECONSTRUCT_DURABLE_STATE_WITHOUT_DUPLICATE_SIDE_EFFECTS",
    "OBSERVE_RECONSTRUCT_FORENSIC_VIEWS_MUST_BE_READ_ONLY_AND_CROSS_VIEW_CONSISTENT",
    "TAMPER_GAP_OR_SOURCE_DRIFT_MUST_FAIL_CLOSED",
    "NO_STAGE3_9_ACCEPTANCE_STEP_CREATES_UNDECLARED_EXTERNAL_TARGET_AUTHORITY",
)

E2E_SUCCESS_CRITERIA = (
    "CANONICAL_MISSION_REACHES_COMPLETED_ONLY_THROUGH_VERIFIED_COMPLETION_HANDOFF",
    "ALL_CANONICAL_TASKS_ARE_VERIFIED_COMPLETE_AND_TERMINAL_NON_SUCCESS_IS_ABSENT",
    "REQUIRED_GOVERNANCE_REVALIDATIONS_ARE_PRESENT_AND_SOURCE_BOUND",
    "EXECUTION_EVIDENCE_AND_OUTCOME_LINEAGE_VERIFY_SUCCESSFULLY",
    "RESTART_REPLAY_RECOVERY_PRODUCES_THE_SAME_DURABLE_CANONICAL_HEAD",
    "FORENSIC_RECONSTRUCTION_MATCHES_THE_VERIFIED_EVENT_LEDGER_AND_DURABLE_RECORD_COUNTS",
    "NO_DUPLICATE_DISPATCH_EXECUTION_OR_TARGET_SIDE_EFFECT_OCCURS_DURING_IDEMPOTENT_REPLAY",
    "FULL_HISTORICAL_REGRESSION_REMAINS_GREEN",
)

E2E_FAILURE_CRITERIA = (
    "IDENTITY_OR_MISSION_BINDING_DIVERGENCE",
    "ILLEGAL_STATE_OR_PLAN_LINEAGE_TRANSITION",
    "ROUTING_DELEGATION_OR_DISPATCH_WITHOUT_REQUIRED_AUTHORIZATION",
    "PRE_DISPATCH_GOVERNANCE_REVALIDATION_MISSING_OR_REJECTED",
    "EVIDENCE_ARTIFACT_OR_EVENT_HASH_MISMATCH",
    "DEPENDENCY_COMPLETION_OR_SUCCESS_CRITERIA_VIOLATION",
    "REPLAY_OR_RESTART_CREATES_DUPLICATE_SIDE_EFFECTS",
    "RECONSTRUCTION_DIFFERS_FROM_VERIFIED_DURABLE_SOURCE",
    "TAMPER_GAP_OR_SOURCE_DRIFT_IS_NOT_REJECTED",
    "UNDECLARED_DATABASE_MIGRATION_DURABLE_STORE_EXTERNAL_IO_OR_TARGET_AUTHORITY",
    "ANY_HISTORICAL_REGRESSION_FAILURE",
)

E2E_STAGE391_FORBIDDEN_SIDE_EFFECTS = (
    "mission_materialization",
    "mission_state_transition",
    "plan_materialization",
    "task_materialization",
    "routing",
    "delegation",
    "governance_query",
    "dispatch",
    "execution_attempt",
    "execution_delivery",
    "target_action_dispatch",
    "target_actuation",
    "outcome_commit",
    "replan_materialization",
    "recovery_mutation",
    "telemetry_export",
    "external_network_io",
    "database_migration",
    "durable_store_creation",
)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_hex(value: Any) -> str:
    if not isinstance(value, str):
        value = _canonical_json(value)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scenario_template() -> dict[str, Any]:
    return {
        "schema_version": E2E_MISSION_SCENARIO_SCHEMA_VERSION,
        "scenario_id": E2E_MISSION_SCENARIO_ID,
        "environment_mode": E2E_MISSION_ACCEPTANCE_ENVIRONMENT_MODE,
        "run_binding": {
            "token": E2E_RUN_ID_TOKEN,
            "allowed_template_fields": ["mission_request.idempotency_key", "mission_request.metadata.run_id"],
            "semantic_fields_are_run_invariant": True,
        },
        "mission_request": {
            "idempotency_key": f"stage391-e2e-{E2E_RUN_ID_TOKEN}",
            "source_system": "STAGE3_9_ACCEPTANCE_HARNESS",
            "created_by": "stage3.9-acceptance-runner",
            "mission_kind": "E2E_ORCHESTRATOR_ACCEPTANCE",
            "objective": {
                "type": "CONTROL_PLANE_E2E_ACCEPTANCE",
                "target_ref": "sandbox-e2e-target-01",
            },
            "success_criteria": [
                {"metric": "all_tasks_verified_complete", "expected": True},
                {"metric": "terminal_non_success_present", "expected": False},
            ],
            "budgets": {
                "time_seconds": 900,
                "max_actions": 16,
                "risk_ceiling": "LOW",
            },
            "required_subsystems": ["CTI"],
            "scope_contract_id": "scope-stage391-e2e-v1",
            "scope_version": 1,
            "roe_version": "1",
            "pip_id": "pip-stage391-e2e-v1",
            "pip_version": "1",
            "policy_version": "1",
            "metadata": {
                "environment": "CONTROL_PLANE_SANDBOX",
                "scenario_id": E2E_MISSION_SCENARIO_ID,
                "run_id": E2E_RUN_ID_TOKEN,
                "external_target_actuation_allowed": False,
            },
        },
        "trace_expectation": {
            "mission_root_trace_id_format": "32_LOWERCASE_HEX",
            "root_span_id_format": "16_LOWERCASE_HEX",
            "event_lineage": "APPEND_ONLY_HASH_CHAIN",
            "forensic_equivalence_required": True,
        },
    }


def canonical_e2e_mission_acceptance_contract() -> dict[str, Any]:
    core = {
        "schema_version": E2E_MISSION_ACCEPTANCE_SCHEMA_VERSION,
        "mode": E2E_MISSION_ACCEPTANCE_MODE,
        "baseline": E2E_MISSION_ACCEPTANCE_BASELINE,
        "database_change_mode": E2E_MISSION_ACCEPTANCE_DATABASE_CHANGE_MODE,
        "persistence_mode": E2E_MISSION_ACCEPTANCE_PERSISTENCE_MODE,
        "expected_repository_migration_level": E2E_MISSION_ACCEPTANCE_EXPECTED_MIGRATION_LEVEL,
        "scenario": _scenario_template(),
        "required_stage_closure_controls": list(REQUIRED_STAGE_CLOSURE_CONTROLS),
        "acceptance_phases": [
            {"stage": stage, "phase": phase} for stage, phase in E2E_ACCEPTANCE_PHASES
        ],
        "required_identity_families": [
            {"name": name, "prefix": prefix} for name, prefix in E2E_REQUIRED_IDENTITY_FAMILIES
        ],
        "invariants": list(E2E_ACCEPTANCE_INVARIANTS),
        "success_criteria": list(E2E_SUCCESS_CRITERIA),
        "failure_criteria": list(E2E_FAILURE_CRITERIA),
        "stage391_boundary": {
            "declared_only": True,
            "runtime_self_certification": False,
            "external_acceptance_execution_required": True,
            "runtime_side_effects": False,
            "new_execution_authority_added": False,
            "new_governance_authority_added": False,
            "new_routing_authority_added": False,
            "new_delegation_authority_added": False,
            "new_dispatch_authority_added": False,
            "new_target_actuation_authority_added": False,
            "new_external_network_io_added": False,
            "new_telemetry_export_added": False,
            "new_database_migration_added": False,
            "new_durable_store_added": False,
            "forbidden_side_effects": list(E2E_STAGE391_FORBIDDEN_SIDE_EFFECTS),
        },
    }
    return {
        **core,
        "integrity": {
            "hash_domain": E2E_MISSION_ACCEPTANCE_HASH_DOMAIN,
            "canonical_sha256": _sha256_hex({
                "hash_domain": E2E_MISSION_ACCEPTANCE_HASH_DOMAIN,
                "core": core,
            }),
        },
    }


def verify_canonical_e2e_mission_acceptance_contract(contract: Mapping[str, Any]) -> bool:
    try:
        if contract.get("schema_version") != E2E_MISSION_ACCEPTANCE_SCHEMA_VERSION:
            return False
        if contract.get("expected_repository_migration_level") != E2E_MISSION_ACCEPTANCE_EXPECTED_MIGRATION_LEVEL:
            return False
        if tuple(contract.get("required_stage_closure_controls", ())) != REQUIRED_STAGE_CLOSURE_CONTROLS:
            return False
        boundary = contract["stage391_boundary"]
        if boundary.get("declared_only") is not True or boundary.get("runtime_side_effects") is not False:
            return False
        for key, value in boundary.items():
            if key.startswith("new_") and value is not False:
                return False
        scenario = contract["scenario"]
        if scenario.get("schema_version") != E2E_MISSION_SCENARIO_SCHEMA_VERSION:
            return False
        if scenario.get("scenario_id") != E2E_MISSION_SCENARIO_ID:
            return False
        core = dict(contract)
        integrity = core.pop("integrity")
        expected = _sha256_hex({
            "hash_domain": E2E_MISSION_ACCEPTANCE_HASH_DOMAIN,
            "core": core,
        })
        if not (
            integrity.get("hash_domain") == E2E_MISSION_ACCEPTANCE_HASH_DOMAIN
            and integrity.get("canonical_sha256") == expected
        ):
            return False

        # The Stage 3.9.1 contract is frozen, not merely self-consistent.  A caller
        # cannot alter an invariant/criterion and make it canonical by recomputing
        # the digest; canonical verification requires exact semantic equivalence to
        # the versioned contract owned by this runtime.
        return dict(contract) == canonical_e2e_mission_acceptance_contract()
    except (KeyError, TypeError, ValueError):
        return False


def materialize_canonical_e2e_mission_request(run_id: str) -> dict[str, Any]:
    """Materialize the frozen Stage-3.9 scenario request without creating a Mission.

    The run identifier is allowed to vary only in explicitly declared non-semantic
    fields. Calling this helper performs no repository write, network call, state
    transition, Governance query, dispatch, execution, or target action.
    """

    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    request = deepcopy(_scenario_template()["mission_request"])
    request["idempotency_key"] = request["idempotency_key"].replace(E2E_RUN_ID_TOKEN, run_id)
    request["metadata"]["run_id"] = run_id
    return request


def canonical_e2e_mission_acceptance_definition() -> dict[str, Any]:
    contract = canonical_e2e_mission_acceptance_contract()
    return {
        "schema_version": E2E_MISSION_ACCEPTANCE_SCHEMA_VERSION,
        "scenario_schema_version": E2E_MISSION_SCENARIO_SCHEMA_VERSION,
        "scenario_id": E2E_MISSION_SCENARIO_ID,
        "mode": E2E_MISSION_ACCEPTANCE_MODE,
        "baseline": E2E_MISSION_ACCEPTANCE_BASELINE,
        "database_change_mode": E2E_MISSION_ACCEPTANCE_DATABASE_CHANGE_MODE,
        "persistence_mode": E2E_MISSION_ACCEPTANCE_PERSISTENCE_MODE,
        "expected_repository_migration_level": E2E_MISSION_ACCEPTANCE_EXPECTED_MIGRATION_LEVEL,
        "environment_mode": E2E_MISSION_ACCEPTANCE_ENVIRONMENT_MODE,
        "contract_sha256": contract["integrity"]["canonical_sha256"],
        "runtime_side_effects": False,
        "new_durable_store_added": False,
        "new_database_migration_added": False,
        "new_execution_authority_added": False,
        "next_stage": "3.9.2",
    }
