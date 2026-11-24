from __future__ import annotations

from copy import deepcopy
import inspect
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionReplanSnapshotConflict,
    MissionReplanSnapshotGuardRejected,
    MissionReplanSnapshotNotFound,
    MissionValidationError,
)
from mission_orchestrator.replan_snapshot import (
    REPLAN_SNAPSHOT_AUTHORITY,
    REPLAN_SNAPSHOT_CONTEXT_MODE,
    REPLAN_SNAPSHOT_CONTRACT_SCHEMA_VERSION,
    REPLAN_SNAPSHOT_EVENT_TYPE,
    REPLAN_SNAPSHOT_ID_PREFIX,
    REPLAN_SNAPSHOT_MODE,
    REPLAN_SNAPSHOT_STAGE_SCHEMA_VERSION,
    REPLAN_SNAPSHOT_STATUS,
    canonical_replan_snapshot_definition,
    verify_replan_snapshot_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_2_6_pause_resume_replanning_control import execute
from tests.test_stage3_7_3_replan_eligibility_governance_gate import (
    PolicyGovernanceClient,
    classified_governed_episode,
    evaluate,
    make_governed_service,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PRIOR_371 = "stage3.7.1-canonical-adaptation-replan-contract-identity"
PRIOR_372 = "stage3.7.2-adaptation-trigger-detection-classification"
PRIOR_373 = "stage3.7.3-replan-eligibility-governance-gate"


def eligible_episode(service, key: str):
    mission_id, active, scope, binding, detected, classification = classified_governed_episode(service, key)
    eligibility, _ = evaluate(service, mission_id, active, scope, binding, detected, classification, key)
    assert eligibility["eligibility_status"] == "ELIGIBLE"
    return mission_id, active, scope, binding, detected, classification, eligibility


def snapshot_request(service, mission_id, active, scope, binding, detected, classification, eligibility, key: str, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage374-snapshot-{key}",
        "expected_adaptation_episode_id": detected["adaptation_episode_id"],
        "expected_classification_id": classification["classification_id"],
        "expected_eligibility_gate_id": eligibility["eligibility_gate_id"],
        "expected_adaptation_replan_sha256": detected["canonical_sha256"],
        "expected_classification_sha256": classification["canonical_sha256"],
        "expected_eligibility_sha256": eligibility["canonical_sha256"],
        "expected_policy_decision_hash": eligibility["policy_decision_hash"],
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_scope_snapshot_id": scope["snapshot_id"],
        "expected_scope_sha256": scope["canonical_sha256"],
        "expected_governance_binding_snapshot_id": binding["binding_snapshot_id"],
        "expected_governance_binding_version": binding["binding_version"],
        "expected_governance_binding_sha256": binding["canonical_sha256"],
        "bound_by": "stage3.7.4-pytest",
        "reason": "Bind immutable canonical context for the eligible adaptation episode",
        "metadata": {"stage": "3.7.4", "key": key},
    }
    body.update(overrides)
    return body


def bind(service, mission_id, active, scope, binding, detected, classification, eligibility, key: str, **overrides):
    body = snapshot_request(service, mission_id, active, scope, binding, detected, classification, eligibility, key, **overrides)
    return service.bind_replan_snapshot(mission_id, detected["adaptation_episode_id"], body), body


def test_health_activates_stage374_and_migration_48(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][60:70] == [PRIOR_371, PRIOR_372, PRIOR_373, "stage3.7.4-canonical-replan-snapshot-context-binding", "stage3.7.5-deterministic-replan-candidate-generation", "stage3.7.6-replan-candidate-validation-delta-feasibility-gate", "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization", "stage3.7.8-atomic-replan-commit-supersession-handoff", "stage3.7.9-adapt-replan-lineage-replay-recovery", "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["replan_snapshot_database_migration_level"] == 48
    assert health["replan_snapshot_stage_schema_version"] == REPLAN_SNAPSHOT_STAGE_SCHEMA_VERSION
    assert health["replan_snapshot_contract_schema_version"] == REPLAN_SNAPSHOT_CONTRACT_SCHEMA_VERSION
    assert health["replan_snapshot_identity_prefix"] == REPLAN_SNAPSHOT_ID_PREFIX
    assert health["replan_snapshot_status"] == REPLAN_SNAPSHOT_STATUS
    assert health["replan_snapshot_mode"] == REPLAN_SNAPSHOT_MODE
    assert health["replan_snapshot_authority"] == REPLAN_SNAPSHOT_AUTHORITY
    assert health["replan_snapshot_event_type"] == REPLAN_SNAPSHOT_EVENT_TYPE
    assert health["replan_snapshot_context_mode"] == REPLAN_SNAPSHOT_CONTEXT_MODE
    assert health["replan_snapshot_persistence_store"] == "mission_replan_snapshots"
    assert "mission_replan_snapshots" in REPOSITORY_STORES


def test_definition_exposes_stage374_boundary_and_next_stage(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, *_ = eligible_episode(service, "definition")
    definition = service.get_replan_snapshot_definition(mission_id)["replan_snapshot_context_binding_definition"]
    assert definition == canonical_replan_snapshot_definition()
    assert definition["requires_stage373_eligible_gate"] is True
    assert definition["context_sources_are_local_durable_only"] is True
    assert definition["planner_invocation_performed"] is False
    assert definition["plan_supersession_performed"] is False
    assert definition["next_stage"] == "3.7.5"


def test_eligible_episode_materializes_immutable_snapshot_without_replan_side_effects(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "materialize")
    mission_id, active, scope, governance_binding, detected, classification, eligibility = args
    before_state = deepcopy(service.get_mission_state(mission_id)["mission_state"])
    before_plans = deepcopy(service.get_plan_version_history(mission_id))
    result, _ = bind(service, mission_id, active, scope, governance_binding, detected, classification, eligibility, "materialize")
    assert result["replan_snapshot_id"].startswith(REPLAN_SNAPSHOT_ID_PREFIX)
    assert result["snapshot_status"] == REPLAN_SNAPSHOT_STATUS
    assert result["effective_episode_state"] == REPLAN_SNAPSHOT_STATUS
    assert result["context_bound"] is True and result["immutable_snapshot"] is True
    assert verify_replan_snapshot_contract(result["replan_snapshot_contract"])
    assert result["snapshot_event"]["event_type"] == REPLAN_SNAPSHOT_EVENT_TYPE
    assert service.get_mission_state(mission_id)["mission_state"] == before_state
    assert service.get_plan_version_history(mission_id) == before_plans
    assert result["lifecycle_replan_requested"] is False
    assert result["planner_invocation_performed"] is False
    assert result["successor_plan_created"] is False
    assert result["plan_supersession_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False


def test_snapshot_binds_canonical_task_dependency_outcome_context(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "task-context")
    result, _ = bind(service, *args, "task-context")
    context = result["replan_snapshot_contract"]["task_dependency_outcome_context"]
    source = result["replan_snapshot_contract"]["source_bindings"]
    assert context["task_count"] == len(context["tasks"]) > 0
    assert context["dependency_graph"] is not None
    assert context["dependency_edge_count"] == len(context["dependency_edges"])
    assert context["task_outcome_count"] == len(context["task_outcomes"])
    assert context["task_completion_count"] == len(context["task_completions"])
    assert source["task_context_sha256"] == result["replan_snapshot_contract"]["context_binding"]["source_context"]["task_context_sha256"]


def test_snapshot_performs_no_additional_governance_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "no-governance-query")
    assert fake.evaluate_calls == 1
    result, _ = bind(service, *args, "no-governance-query")
    assert fake.evaluate_calls == 1
    assert result["governance_query_performed"] is False
    assert result["external_context_refresh_performed"] is False


def test_not_eligible_gate_is_rejected(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    fake.emergency_stop = True
    mission_id, active, scope, governance_binding, detected, classification = classified_governed_episode(service, "deny")
    eligibility, _ = evaluate(service, mission_id, active, scope, governance_binding, detected, classification, "deny")
    assert eligibility["eligibility_status"] == "NOT_ELIGIBLE"
    body = snapshot_request(service, mission_id, active, scope, governance_binding, detected, classification, eligibility, "deny")
    with pytest.raises(MissionReplanSnapshotGuardRejected, match="requires an ELIGIBLE"):
        service.bind_replan_snapshot(mission_id, detected["adaptation_episode_id"], body)


def test_review_required_gate_is_rejected(tmp_path):
    fake = PolicyGovernanceClient(decision="REVIEW")
    service, _ = make_governed_service(tmp_path / "missions.db", fake)
    mission_id, active, scope, governance_binding, detected, classification = classified_governed_episode(service, "review")
    eligibility, _ = evaluate(service, mission_id, active, scope, governance_binding, detected, classification, "review")
    assert eligibility["eligibility_status"] == "REVIEW_REQUIRED"
    body = snapshot_request(service, mission_id, active, scope, governance_binding, detected, classification, eligibility, "review")
    with pytest.raises(MissionReplanSnapshotGuardRejected, match="requires an ELIGIBLE"):
        service.bind_replan_snapshot(mission_id, detected["adaptation_episode_id"], body)


def test_stale_stage371_adaptation_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "stale371")
    body = snapshot_request(service, *args, "stale371", expected_adaptation_replan_sha256="0" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="Stage-3.7.1 adaptation/replan hash"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_stale_stage372_classification_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "stale372")
    body = snapshot_request(service, *args, "stale372", expected_classification_sha256="1" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="Stage-3.7.2 classification hash"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_stale_stage373_eligibility_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "stale373")
    body = snapshot_request(service, *args, "stale373", expected_eligibility_sha256="2" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="Stage-3.7.3 eligibility hash"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_stale_policy_decision_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "stale-policy")
    body = snapshot_request(service, *args, "stale-policy", expected_policy_decision_hash="3" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="PolicyDecision hash"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_stale_state_version_expectation_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "stale-state")
    body = snapshot_request(service, *args, "stale-state", expected_state_version=999999)
    with pytest.raises(MissionConcurrencyConflict, match="expected_state_version"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_mission_state_drift_after_eligibility_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "state-drift")
    mission_id, active, scope, governance_binding, detected, classification, eligibility = args
    execute(service, mission_id, "WAIT_FOR_EVIDENCE", "stage374-state-drift")
    body = snapshot_request(service, mission_id, active, scope, governance_binding, detected, classification, eligibility, "state-drift")
    with pytest.raises(MissionReplanSnapshotGuardRejected, match="source bindings drifted"):
        service.bind_replan_snapshot(mission_id, detected["adaptation_episode_id"], body)


def test_stale_active_plan_expectation_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "stale-plan")
    body = snapshot_request(service, *args, "stale-plan", expected_active_plan_sha256="4" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head changed"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_stale_scope_or_governance_binding_expectations_are_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "stale-scope-binding")
    body = snapshot_request(service, *args, "stale-scope", expected_scope_sha256="5" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="Mission scope changed"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)
    body = snapshot_request(service, *args, "stale-binding", expected_governance_binding_sha256="6" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="Governance binding changed"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_caller_cannot_supply_replan_planner_delta_commit_or_actuation_fields(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "forbidden")
    for field, value in (
        ("lifecycle_replan_requested", True),
        ("planner_input", {"prompt": "replan"}),
        ("planner_output", {"tasks": []}),
        ("plan_delta", {"replace": []}),
        ("successor_plan", {"version": 2}),
        ("replan_commit", True),
        ("plan_supersession", True),
        ("dispatch", True),
        ("actuation", True),
    ):
        body = snapshot_request(service, *args, f"forbidden-{field}")
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported replan snapshot/context-binding field"):
            service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)


def test_exact_retry_is_idempotent_and_event_cardinality_is_one(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "retry")
    first, body = bind(service, *args, "retry")
    second = service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], body)
    assert second["idempotent_replay"] is True
    assert second["replan_snapshot_id"] == first["replan_snapshot_id"]
    assert second["canonical_sha256"] == first["canonical_sha256"]
    assert fake.evaluate_calls == 1
    events = [e for e in service.repository.list_mission_events(args[0]) if e["event_type"] == REPLAN_SNAPSHOT_EVENT_TYPE]
    assert len(events) == 1


def test_idempotency_conflict_and_one_snapshot_per_episode_are_enforced(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args = eligible_episode(service, "conflict")
    first, body = bind(service, *args, "conflict")
    conflicting = deepcopy(body)
    conflicting["reason"] = "different material"
    with pytest.raises(MissionReplanSnapshotConflict, match="idempotency_key"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], conflicting)
    another = deepcopy(body)
    another["idempotency_key"] = "stage374-another-key-same-episode"
    with pytest.raises(MissionReplanSnapshotConflict, match="already has"):
        service.bind_replan_snapshot(args[0], args[4]["adaptation_episode_id"], another)
    assert first["replan_snapshot_id"].startswith(REPLAN_SNAPSHOT_ID_PREFIX)


def test_restart_retrieval_repository_integrity_not_found_and_schema_constraints(tmp_path):
    db = tmp_path / "missions.db"
    service, fake = make_governed_service(db)
    args = eligible_episode(service, "restart")
    result, _ = bind(service, *args, "restart")
    restarted, _ = make_governed_service(db, fake)
    got = restarted.get_replan_snapshot(args[0], result["replan_snapshot_id"])
    by_episode = restarted.get_replan_snapshot_for_episode(args[0], args[4]["adaptation_episode_id"])
    assert got["canonical_sha256"] == result["canonical_sha256"]
    assert by_episode["replan_snapshot_id"] == result["replan_snapshot_id"]
    repo = restarted.get_mission_repository(args[0])
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_replan_snapshots"] == 1
    refs = repo["persistence_manifest"]["replan_snapshot_context_binding_store"]["snapshots"]
    assert refs[0]["replan_snapshot_id"] == result["replan_snapshot_id"]
    with pytest.raises(MissionReplanSnapshotNotFound):
        restarted.get_replan_snapshot(args[0], "rpsnap-missing")
    con = sqlite3.connect(db)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='mission_replan_snapshots'").fetchone()[0]
    con.close()
    assert "adaptation_episode_id TEXT NOT NULL UNIQUE" in sql
    assert "eligibility_gate_id TEXT NOT NULL UNIQUE" in sql
    assert "UNIQUE(mission_id, idempotency_key)" in sql


def test_http_surface_preserves_stage374_snapshot_routes_with_stage377_commit_surface(tmp_path):
    source = inspect.getsource(MissionOrchestratorHandler)
    assert 'parts[3] == "replan-snapshots"' in source
    assert 'parts[3] == "replan-snapshot-context-binding-definition"' in source
    assert 'parts[5] == "snapshot"' in source
    assert "bind_replan_snapshot" in source
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert 'parts[3] == "replan-commits"' in source
    assert 'parts[3] == "replan-validations"' in source
    assert 'parts[5] == "commit"' in source
    assert "commit_authorized_replan" in source
    assert "replan-supersession" not in source
