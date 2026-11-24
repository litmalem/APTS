from __future__ import annotations

import inspect
import sqlite3
from copy import deepcopy

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionReplanCandidateConflict,
    MissionReplanCandidateNotFound,
    MissionValidationError,
)
from mission_orchestrator.replan_candidate import (
    REPLAN_CANDIDATE_AUTHORITY,
    REPLAN_CANDIDATE_CONTRACT_SCHEMA_VERSION,
    REPLAN_CANDIDATE_EVENT_TYPE,
    REPLAN_CANDIDATE_ID_PREFIX,
    REPLAN_CANDIDATE_MODE,
    REPLAN_CANDIDATE_STAGE_SCHEMA_VERSION,
    REPLAN_CANDIDATE_STATUS,
    REPLAN_PLANNER_INVOCATION_ID_PREFIX,
    REPLAN_PLANNER_PROFILE,
    canonical_replan_candidate_definition,
    deterministic_replan_candidate_payload,
    verify_replan_candidate_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_7_4_canonical_replan_snapshot_context_binding import (
    bind,
    eligible_episode,
    make_governed_service,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def stage375_source(service, key: str):
    args = eligible_episode(service, key)
    snapshot, _ = bind(service, *args, key)
    return args, snapshot


def candidate_request(snapshot, key: str, **overrides):
    src = snapshot["replan_snapshot_contract"]["source_bindings"]
    body = {
        "idempotency_key": f"stage375-candidate-{key}",
        "expected_replan_snapshot_id": snapshot["replan_snapshot_id"],
        "expected_replan_snapshot_sha256": snapshot["canonical_sha256"],
        "expected_task_context_sha256": src["task_context_sha256"],
        "expected_source_plan_version_record_id": src["source_plan_version_record_id"],
        "expected_source_plan_version": src["source_plan_version"],
        "expected_source_plan_sha256": src["source_plan_sha256"],
        "expected_source_state_version": src["source_state_version"],
        "expected_source_version_sha256": src["source_version_sha256"],
        "planner_profile": REPLAN_PLANNER_PROFILE,
        "generated_by": "stage3.7.5-pytest",
        "reason": "Generate deterministic candidate from immutable ReplanSnapshot",
        "metadata": {"stage": "3.7.5", "key": key},
    }
    body.update(overrides)
    return body


def generate(service, mission_id, snapshot, key: str, **overrides):
    body = candidate_request(snapshot, key, **overrides)
    return service.generate_replan_candidate(mission_id, snapshot["replan_snapshot_id"], body), body


def test_health_activates_stage375_and_migration_49(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    h = service.health()
    assert h["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["replan_candidate_database_migration_level"] == 49
    assert h["replan_candidate_stage_schema_version"] == REPLAN_CANDIDATE_STAGE_SCHEMA_VERSION
    assert h["replan_candidate_contract_schema_version"] == REPLAN_CANDIDATE_CONTRACT_SCHEMA_VERSION
    assert h["replan_candidate_identity_prefix"] == REPLAN_CANDIDATE_ID_PREFIX
    assert h["replan_candidate_planner_invocation_identity_prefix"] == REPLAN_PLANNER_INVOCATION_ID_PREFIX
    assert h["replan_candidate_persistence_store"] == "mission_replan_candidates"
    assert "mission_replan_candidates" in REPOSITORY_STORES


def test_definition_exposes_candidate_only_boundary_and_next_stage(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _ = stage375_source(service, "definition")
    definition = service.get_replan_candidate_definition(args[0])["deterministic_replan_candidate_generation_definition"]
    assert definition == canonical_replan_candidate_definition()
    assert definition["requires_stage374_replan_snapshot"] is True
    assert definition["snapshot_is_sole_authoritative_planning_input"] is True
    assert definition["candidate_only"] is True
    assert definition["successor_plan_created"] is False
    assert definition["next_stage"] == "3.7.6"


def test_generation_materializes_candidate_and_invocation(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "materialize")
    result, _ = generate(service, args[0], snapshot, "materialize")
    assert result["replan_candidate_id"].startswith(REPLAN_CANDIDATE_ID_PREFIX)
    assert result["planner_invocation_id"].startswith(REPLAN_PLANNER_INVOCATION_ID_PREFIX)
    assert result["candidate_status"] == REPLAN_CANDIDATE_STATUS
    assert result["candidate_event"]["event_type"] == REPLAN_CANDIDATE_EVENT_TYPE
    assert verify_replan_candidate_contract(result["replan_candidate_contract"])


def test_deterministic_payload_is_stable_for_same_snapshot(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    _, snapshot = stage375_source(service, "deterministic")
    contract = snapshot["replan_snapshot_contract"]
    assert deterministic_replan_candidate_payload(contract) == deterministic_replan_candidate_payload(contract)


def test_candidate_preserves_source_plan_and_targets_next_version(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "version")
    result, _ = generate(service, args[0], snapshot, "version")
    c = result["replan_candidate_contract"]
    src = c["source_bindings"]
    candidate = c["candidate_successor_plan"]
    assert candidate["candidate_plan_version"] == src["source_plan_version"] + 1
    assert result["source_plan_version_record_id"] == src["source_plan_version_record_id"]
    assert candidate["candidate_only"] is True


def test_candidate_tasks_and_edges_are_canonically_ordered(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "ordering")
    result, _ = generate(service, args[0], snapshot, "ordering")
    cand = result["replan_candidate_contract"]["candidate_successor_plan"]
    indices = [x["candidate_task_index"] for x in cand["candidate_tasks"]]
    assert indices == list(range(1, len(indices) + 1))
    edge_ids = [x["source_dependency_edge_id"] for x in cand["candidate_dependency_edges"]]
    assert edge_ids == sorted(edge_ids)


def test_generation_performs_no_additional_governance_query(tmp_path):
    service, fake = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "no-governance")
    before = fake.evaluate_calls
    result, _ = generate(service, args[0], snapshot, "no-governance")
    assert fake.evaluate_calls == before
    assert result["governance_query_performed"] is False
    assert result["external_context_refresh_performed"] is False


def test_generation_has_no_commit_supersession_dispatch_or_actuation(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "boundary")
    before_state = deepcopy(service.get_mission_state(args[0])["mission_state"])
    before_history = deepcopy(service.get_plan_version_history(args[0]))
    result, _ = generate(service, args[0], snapshot, "boundary")
    assert result["planner_invocation_performed"] is True
    assert result["replan_candidate_created"] is True
    assert result["plan_delta_computed"] is True
    assert result["successor_plan_created"] is False
    assert result["plan_validation_performed"] is False
    assert result["replan_decision_committed"] is False
    assert result["plan_supersession_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["target_actuation"] is False
    assert service.get_mission_state(args[0])["mission_state"] == before_state
    assert service.get_plan_version_history(args[0]) == before_history


def test_stale_snapshot_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "stale-snapshot")
    body = candidate_request(snapshot, "stale-snapshot", expected_replan_snapshot_sha256="0" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="ReplanSnapshot hash"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)


def test_stale_task_context_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "stale-context")
    body = candidate_request(snapshot, "stale-context", expected_task_context_sha256="1" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="task context hash"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)


def test_stale_source_plan_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "stale-plan")
    body = candidate_request(snapshot, "stale-plan", expected_source_plan_sha256="2" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="source Plan hash"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)


def test_stale_source_version_hash_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "stale-version")
    body = candidate_request(snapshot, "stale-version", expected_source_version_sha256="3" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="source Mission version hash"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)


def test_caller_supplied_candidate_content_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "forbidden")
    body = candidate_request(snapshot, "forbidden", candidate_tasks=[])
    with pytest.raises(MissionValidationError, match="Caller-supplied tasks"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)


def test_wrong_planner_profile_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "profile")
    body = candidate_request(snapshot, "profile", planner_profile="LLM_FREEFORM")
    with pytest.raises(MissionValidationError, match="planner_profile"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)


def test_exact_retry_is_idempotent_and_one_event(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "retry")
    first, body = generate(service, args[0], snapshot, "retry")
    second = service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)
    assert second["idempotent_replay"] is True
    assert second["replan_candidate_id"] == first["replan_candidate_id"]
    events = [e for e in service.repository.list_mission_events(args[0]) if e["event_type"] == REPLAN_CANDIDATE_EVENT_TYPE]
    assert len(events) == 1


def test_idempotency_conflict_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "idem-conflict")
    _, body = generate(service, args[0], snapshot, "idem-conflict")
    changed = dict(body); changed["reason"] = "different request material"
    with pytest.raises(MissionReplanCandidateConflict, match="different request material"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], changed)


def test_one_candidate_per_snapshot_is_enforced(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, snapshot = stage375_source(service, "cardinality")
    generate(service, args[0], snapshot, "cardinality")
    body = candidate_request(snapshot, "cardinality-second")
    with pytest.raises(MissionReplanCandidateConflict, match="already has"):
        service.generate_replan_candidate(args[0], snapshot["replan_snapshot_id"], body)


def test_restart_retrieval_and_repository_integrity(tmp_path):
    db = tmp_path / "missions.db"
    service, _ = make_governed_service(db)
    args, snapshot = stage375_source(service, "restart")
    result, _ = generate(service, args[0], snapshot, "restart")
    restarted, _ = make_governed_service(db)
    fetched = restarted.get_replan_candidate(args[0], result["replan_candidate_id"])
    assert fetched["canonical_sha256"] == result["canonical_sha256"]
    repo = restarted.get_mission_repository(args[0])
    assert repo["integrity_status"] == "PASS"
    assert repo["record_counts"]["mission_replan_candidates"] == 1


def test_database_uniqueness_constraints_exist(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    conn = sqlite3.connect(service.repository.sqlite_path)
    try:
        indexes = conn.execute("PRAGMA index_list('mission_replan_candidates')").fetchall()
        assert any(bool(row[2]) for row in indexes)
    finally:
        conn.close()


def test_missing_candidate_returns_not_found(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    args, _ = stage375_source(service, "missing")
    with pytest.raises(MissionReplanCandidateNotFound):
        service.get_replan_candidate(args[0], "rpcand-missing")


def test_http_surface_preserves_candidate_routes_with_stage377_commit_surface(tmp_path):
    source = inspect.getsource(MissionOrchestratorHandler)
    assert 'parts[3] == "replan-candidates"' in source
    assert 'parts[3] == "deterministic-replan-candidate-generation-definition"' in source
    assert 'parts[5] == "candidate"' in source
    assert "generate_replan_candidate" in source
    assert 'parts[3] == "replan-commits"' in source
    assert 'parts[3] == "replan-validations"' in source
    assert 'parts[5] == "commit"' in source
    assert "commit_authorized_replan" in source
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
