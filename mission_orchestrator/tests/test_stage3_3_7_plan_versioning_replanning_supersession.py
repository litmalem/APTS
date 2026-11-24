from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionLifecycleGuardRejected,
    MissionPlanVersioningConflict,
    MissionPlanVersioningGuardRejected,
    MissionPlanVersioningNotFound,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.plan_versioning import (
    PLAN_VERSIONING_ACTIVE_STATUS,
    PLAN_VERSIONING_INITIAL_ACTIVATION_TYPE,
    PLAN_VERSIONING_MODE,
    PLAN_VERSIONING_REPLAN_ACTIVATION_TYPE,
    PLAN_VERSIONING_SCHEMA_VERSION,
    PLAN_VERSIONING_SUPERSEDED_STATUS,
    canonical_plan_versioning_definition,
    verify_plan_version_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from tests.test_stage3_3_6_plan_validation_feasibility_gate import (
    make_service,
    provision_generated,
    validation_request,
)
from tests.test_stage3_2_6_pause_resume_replanning_control import execute


def provision_validated(service, key: str):
    mission_id, plan, snapshot, decomp, graph, generated = provision_generated(service, key)
    validation = service.validate_generated_plan_feasibility(
        mission_id, validation_request(service, mission_id, key)
    )
    return mission_id, plan, snapshot, decomp, graph, generated, validation


def activation_request(service, mission_id: str, validation: dict, key: str, **overrides) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key": f"stage337-activate-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_plan_validation_id": validation["plan_validation_id"],
        "expected_plan_validation_sha256": validation["canonical_sha256"],
        "created_by": "stage3.3.7-pytest",
        "reason": "Activate validated feasible Plan as canonical Plan version v1",
        "metadata": {"stage": "3.3.7", "key": key},
    }
    body.update(overrides)
    return body


def activate_v1(service, mission_id: str, validation: dict, key: str) -> dict:
    return service.activate_initial_plan_version(
        mission_id, activation_request(service, mission_id, validation, key)
    )


def enter_replanning(service, mission_id: str, key: str) -> dict:
    execute(service, mission_id, "START", f"run-{key}")
    return execute(service, mission_id, "REPLAN", f"replan-{key}")


def replan_request(service, mission_id: str, replan: dict, key: str, **overrides) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    active = service.get_active_plan_version(mission_id)
    body = {
        "idempotency_key": f"stage337-replan-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_replan_id": replan["replan_control"]["replan_id"],
        "created_by": "stage3.3.7-pytest",
        "reason": "Create immutable successor Plan for active Stage-3.2.6 replanning episode",
        "metadata": {"stage": "3.3.7", "key": key},
    }
    body.update(overrides)
    return body


def test_health_activates_stage337_versioning_without_governance_or_execution_expansion(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][20:30] == [
        "stage3.3.1-canonical-plan-contract-identity",
        "stage3.3.2-planner-input-snapshot-context-binding",
        "stage3.3.3-canonical-task-decomposition-contract",
        "stage3.3.4-task-dependency-graph-structural-validation",
        "stage3.3.5-planner-invocation-plan-generation",
        "stage3.3.6-plan-validation-feasibility-gate",
        "stage3.3.7-plan-versioning-replanning-supersession",
        "stage3.3.8-task-readiness-scheduling-projection",
        "stage3.3.9-planning-event-lineage-replay-recovery",
        "stage3.3.10-planning-acceptance-regression-gate",
    ]
    assert health["plan_versioning_schema_version"] == PLAN_VERSIONING_SCHEMA_VERSION
    assert health["plan_versioning_mode"] == PLAN_VERSIONING_MODE
    assert health["plan_versioning_append_only_versions"] is True
    assert health["plan_versioning_single_active_head"] is True
    assert health["plan_versioning_successor_version_rule"] == "PREDECESSOR_PLUS_ONE"
    assert health["plan_versioning_prior_versions_mutated"] is False
    assert health["plan_versioning_planner_reinvocation_on_replan"] is True
    assert health["plan_versioning_governance_query_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["plan_versioning_scheduling_performed"] is False
    assert health["plan_versioning_target_action_dispatch_enabled"] is False
    assert health["plan_versioning_target_actuation"] is False
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "plan_versioning_version" in health["observed_version_domains"]


def test_plan_versioning_definition_is_discoverable_before_activation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_validated(service, "definition")
    result = service.get_plan_versioning_definition(mission_id)
    assert result["plan_versioning_active"] is False
    assert result["registered_version_count"] == 0
    assert result["active_head"] is None
    assert result["plan_versioning_definition"] == canonical_plan_versioning_definition()


def test_initial_activation_requires_stage336_validated_feasible_artifact(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_generated(service, "missing-validation")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    payload = {
        "idempotency_key": "stage337-no-validation",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_plan_validation_id": "pval-missing",
        "expected_plan_validation_sha256": "0" * 64,
        "created_by": "stage3.3.7-pytest",
    }
    with pytest.raises(MissionPlanVersioningGuardRejected, match="Stage-3.3.6 validation"):
        service.activate_initial_plan_version(mission_id, payload)


def test_initial_activation_materializes_immutable_active_v1(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "v1")
    result = activate_v1(service, mission_id, validation, "v1")
    assert result["idempotent_replay"] is False
    assert result["plan_version"] == 1
    assert result["activation_type"] == PLAN_VERSIONING_INITIAL_ACTIVATION_TYPE
    assert result["effective_status"] == PLAN_VERSIONING_ACTIVE_STATUS
    assert result["predecessor_plan_version_record_id"] is None
    assert result["replan_id"] is None
    assert verify_plan_version_contract(result["plan_version_contract"])
    assert result["plan_version_contract"]["lineage"]["validation"]["validation_status"] == "VALIDATED_FEASIBLE"
    assert result["governance_authorization_query_performed"] is False
    assert result["target_action_dispatch_enabled"] is False


def test_initial_activation_exact_replay_is_idempotent_and_second_activation_rejected(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "replay")
    request = activation_request(service, mission_id, validation, "replay")
    first = service.activate_initial_plan_version(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.activate_initial_plan_version(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["plan_version_record_id"] == first["plan_version_record_id"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count
    different = activation_request(service, mission_id, validation, "replay-2")
    with pytest.raises(MissionPlanVersioningConflict, match="initial active Plan version already exists"):
        service.activate_initial_plan_version(mission_id, different)


def test_initial_activation_stale_vector_and_state_fail_closed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "stale")
    payload = activation_request(service, mission_id, validation, "stale", expected_version_sha256="0" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="expected_version_sha256"):
        service.activate_initial_plan_version(mission_id, payload)

    service2 = make_service(tmp_path / "state.db")
    mission2, *_, validation2 = provision_validated(service2, "state")
    payload2 = activation_request(service2, mission2, validation2, "state")
    execute(service2, mission2, "START", "state-running")
    payload2["expected_version_sha256"] = service2.get_mission_version_vector(mission2)["version_sha256"]
    payload2["expected_state_version"] = service2.get_mission_state(mission2)["mission_state"]["state_version"]
    with pytest.raises(MissionPlanVersioningGuardRejected, match="PLANNING"):
        service2.activate_initial_plan_version(mission2, payload2)


@pytest.mark.parametrize("field", ["authorization", "readiness", "schedule", "dispatch", "execution_command", "planner_output", "tasks"])
def test_stage337_requests_reject_caller_authority_readiness_execution_or_planner_surfaces(tmp_path, field):
    service = make_service(tmp_path / f"surface-{field}.db")
    mission_id, *_, validation = provision_validated(service, f"surface-{field}")
    payload = activation_request(service, mission_id, validation, f"surface-{field}")
    payload[field] = True
    with pytest.raises(MissionValidationError, match="does not accept caller-supplied"):
        service.activate_initial_plan_version(mission_id, payload)


def test_version_vector_advances_only_plan_versioning_domain_on_v1_activation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    bv = before["version_vector"]["versions"]
    assert bv["plan_validation_version"] == 1
    assert bv["plan_versioning_version"] == 0
    result = activate_v1(service, mission_id, validation, "vector")
    after = service.get_mission_version_vector(mission_id)
    av = after["version_vector"]["versions"]
    for key in (
        "mission_plan_version", "planner_input_snapshot_version", "task_decomposition_version",
        "task_dependency_graph_version", "planner_generation_version", "plan_validation_version",
    ):
        assert av[key] == bv[key]
    assert av["plan_versioning_version"] == 1
    assert result["source_version_sha256"] == before["version_sha256"]
    assert after["version_sha256"] != before["version_sha256"]


def test_replan_successor_requires_active_version_and_canonical_replan_lineage(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_validated(service, "no-active")
    execute(service, mission_id, "START", "no-active-run")
    replan = execute(service, mission_id, "REPLAN", "no-active-rp")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    payload = {
        "idempotency_key": "stage337-replan-no-active",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version": 1,
        "expected_active_plan_sha256": "0" * 64,
        "expected_replan_id": replan["replan_control"]["replan_id"],
        "created_by": "stage3.3.7-pytest",
    }
    with pytest.raises(MissionPlanVersioningGuardRejected, match="active Stage-3.3.7"):
        service.create_replan_successor_plan_version(mission_id, payload)


def test_replan_successor_creates_v2_and_effectively_supersedes_v1_without_mutation(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "v2")
    v1 = activate_v1(service, mission_id, validation, "v2")
    v1_contract = deepcopy(v1["plan_version_contract"])
    replan = enter_replanning(service, mission_id, "v2")
    v2 = service.create_replan_successor_plan_version(mission_id, replan_request(service, mission_id, replan, "v2"))
    assert v2["plan_version"] == 2
    assert v2["activation_type"] == PLAN_VERSIONING_REPLAN_ACTIVATION_TYPE
    assert v2["effective_status"] == PLAN_VERSIONING_ACTIVE_STATUS
    assert v2["predecessor_plan_version_record_id"] == v1["plan_version_record_id"]
    assert v2["predecessor_plan_version"] == 1
    assert v2["replan_id"] == replan["replan_control"]["replan_id"]
    assert v2["planner_reinvocation_performed"] is True
    assert verify_plan_version_contract(v2["plan_version_contract"])
    history = service.get_plan_version_history(mission_id)["plan_versions"]
    assert [x["plan_version"] for x in history] == [1, 2]
    assert history[0]["effective_status"] == PLAN_VERSIONING_SUPERSEDED_STATUS
    assert history[1]["effective_status"] == PLAN_VERSIONING_ACTIVE_STATUS
    persisted_v1 = service.repository.list_plan_versions(mission_id)[0]
    assert persisted_v1["plan_version_contract"] == v1_contract


def test_single_successor_per_replan_episode_and_exact_replay_are_enforced(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "single")
    activate_v1(service, mission_id, validation, "single")
    replan = enter_replanning(service, mission_id, "single")
    request = replan_request(service, mission_id, replan, "single")
    first = service.create_replan_successor_plan_version(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.create_replan_successor_plan_version(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["plan_version_record_id"] == first["plan_version_record_id"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count
    different = replan_request(service, mission_id, replan, "single-2")
    with pytest.raises(MissionPlanVersioningConflict, match="already has a successor"):
        service.create_replan_successor_plan_version(mission_id, different)


def test_replan_successor_rejects_stale_head_version_hash_and_wrong_replan_id(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "cas")
    activate_v1(service, mission_id, validation, "cas")
    replan = enter_replanning(service, mission_id, "cas")
    payload = replan_request(service, mission_id, replan, "cas", expected_active_plan_version=99)
    with pytest.raises(MissionConcurrencyConflict, match="expected_active_plan_version"):
        service.create_replan_successor_plan_version(mission_id, payload)
    payload = replan_request(service, mission_id, replan, "cas-hash", expected_active_plan_sha256="0" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="expected_active_plan_sha256"):
        service.create_replan_successor_plan_version(mission_id, payload)
    payload = replan_request(service, mission_id, replan, "cas-replan", expected_replan_id="replan:wrong")
    with pytest.raises(MissionPlanVersioningGuardRejected, match="expected_replan_id"):
        service.create_replan_successor_plan_version(mission_id, payload)


def test_replan_successor_fails_closed_when_planner_snapshot_context_drifted(tmp_path):
    from tests.test_stage3_3_4_task_dependency_graph_structural_validation import scope_payload
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "drift")
    activate_v1(service, mission_id, validation, "drift")
    replan = enter_replanning(service, mission_id, "drift")
    service.put_mission_scope_contract(mission_id, scope_payload("stage337-drift-v1", expected=0))
    payload = replan_request(service, mission_id, replan, "drift")
    with pytest.raises(MissionPlanVersioningGuardRejected, match="planner-input context is stale"):
        service.create_replan_successor_plan_version(mission_id, payload)


def test_replanning_to_running_is_blocked_until_successor_is_committed_then_allowed(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "return")
    activate_v1(service, mission_id, validation, "return")
    replan = enter_replanning(service, mission_id, "return")
    with pytest.raises(MissionLifecycleGuardRejected, match="committed successor Plan version"):
        execute(service, mission_id, "START", "return-too-early", evidence_refs=["plan-readiness:v2"])
    service.create_replan_successor_plan_version(mission_id, replan_request(service, mission_id, replan, "return"))
    result = execute(service, mission_id, "START", "return-ready", evidence_refs=["plan-readiness:v2"])
    assert result["mission_state"]["state"] == "RUNNING"
    assert result["replan_resolution"]["replan_id"] == replan["replan_control"]["replan_id"]


def test_multiple_replanning_episodes_build_contiguous_append_only_chain(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "chain")
    activate_v1(service, mission_id, validation, "chain")
    replan1 = enter_replanning(service, mission_id, "chain-1")
    service.create_replan_successor_plan_version(mission_id, replan_request(service, mission_id, replan1, "chain-1"))
    execute(service, mission_id, "START", "chain-ready-1", evidence_refs=["plan-readiness:v2"])
    replan2 = execute(service, mission_id, "REPLAN", "chain-replan-2")
    v3 = service.create_replan_successor_plan_version(mission_id, replan_request(service, mission_id, replan2, "chain-2"))
    assert v3["plan_version"] == 3
    history = service.get_plan_version_history(mission_id)["plan_versions"]
    assert [x["plan_version"] for x in history] == [1, 2, 3]
    assert [x["effective_status"] for x in history] == ["SUPERSEDED", "SUPERSEDED", "ACTIVE"]
    records = service.repository.list_plan_versions(mission_id)
    assert records[1]["predecessor_plan_version_record_id"] == records[0]["plan_version_record_id"]
    assert records[2]["predecessor_plan_version_record_id"] == records[1]["plan_version_record_id"]


def test_stage337_emits_exactly_one_activation_and_one_replan_supersession_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "events")
    v1 = activate_v1(service, mission_id, validation, "events")
    replan = enter_replanning(service, mission_id, "events")
    v2 = service.create_replan_successor_plan_version(mission_id, replan_request(service, mission_id, replan, "events"))
    events = service.get_mission_events(mission_id)["events"]
    activated = [e for e in events if e["event_type"] == "MISSION_PLAN_VERSION_ACTIVATED"]
    superseded = [e for e in events if e["event_type"] == "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED"]
    assert len(activated) == 1 and activated[0]["causation_id"] == v1["plan_version_record_id"]
    assert len(superseded) == 1 and superseded[0]["causation_id"] == v2["plan_version_record_id"]
    assert superseded[0]["payload"]["superseded_plan_version_record_id"] == v1["plan_version_record_id"]
    assert superseded[0]["payload"]["successor_plan_version_record_id"] == v2["plan_version_record_id"]


def test_repository_integrity_restart_reconstructs_active_head_and_history(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_, validation = provision_validated(service, "repo")
    activate_v1(service, mission_id, validation, "repo")
    replan = enter_replanning(service, mission_id, "repo")
    v2 = service.create_replan_successor_plan_version(mission_id, replan_request(service, mission_id, replan, "repo"))
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_plan_version_heads"] == 1
    assert repo["record_counts"]["mission_plan_versions"] == 2
    store = repo["persistence_manifest"]["plan_versioning_store"]
    assert store["head"]["active_plan_version_record_id"] == v2["plan_version_record_id"]
    assert len(store["versions"]) == 2

    restarted = make_service(db)
    active = restarted.get_active_plan_version(mission_id)
    history = restarted.get_plan_version_history(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)
    assert active["plan_version_record_id"] == v2["plan_version_record_id"]
    assert history["version_count"] == 2
    assert repo_after["repository_sha256"] == repo["repository_sha256"]


def test_repository_integrity_detects_plan_version_contract_tampering(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_, validation = provision_validated(service, "tamper-contract")
    v1 = activate_v1(service, mission_id, validation, "tamper-contract")
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT canonical_json FROM mission_plan_versions WHERE plan_version_record_id=?",
        (v1["plan_version_record_id"],),
    ).fetchone()
    contract = json.loads(row[0])
    contract["semantics"]["target_action_dispatch_enabled"] = True
    conn.execute(
        "UPDATE mission_plan_versions SET canonical_json=? WHERE plan_version_record_id=?",
        (json.dumps(contract, sort_keys=True, separators=(",", ":")), v1["plan_version_record_id"]),
    )
    conn.commit(); conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="plan_versioning_supersession_store"):
        service.get_mission_repository(mission_id)


def test_repository_integrity_detects_plan_version_head_tampering(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, *_, validation = provision_validated(service, "tamper-head")
    activate_v1(service, mission_id, validation, "tamper-head")
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE mission_plan_version_heads SET active_plan_sha256=? WHERE mission_id=?",
        ("f" * 64, mission_id),
    )
    conn.commit(); conn.close()
    with pytest.raises(MissionRepositoryIntegrityError, match="plan_versioning_supersession_store"):
        service.get_mission_repository(mission_id)


def test_missing_plan_version_read_models_raise_typed_not_found(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_ = provision_validated(service, "not-found")
    with pytest.raises(MissionPlanVersioningNotFound):
        service.get_active_plan_version(mission_id)
    with pytest.raises(MissionPlanVersioningNotFound):
        service.get_plan_version_history(mission_id)


def test_migration_015_declares_append_only_version_head_boundaries_and_level_15():
    sql = Path("migrations/015_stage3_3_7_plan_versioning_replanning_supersession.sql").read_text().lower()
    assert "create table if not exists mission_plan_versions" in sql
    assert "create table if not exists mission_plan_version_heads" in sql
    assert "unique key uq_mission_plan_version_number (mission_id, plan_version)" in sql
    assert "unique key uq_mission_plan_version_replan (mission_id, replan_id)" in sql
    assert "no governance authorization" in sql
    assert "scheduling" in sql
    assert "target-action dispatch" in sql and "target actuation" in sql
    assert "15," in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[16].name == "017_stage3_3_9_planning_event_lineage_replay_recovery.sql"
