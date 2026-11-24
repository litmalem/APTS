from __future__ import annotations

import inspect
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionReplanHandoffConflict,
    MissionValidationError,
)
from mission_orchestrator.replan_handoff import (
    REPLAN_HANDOFF_AUTHORITY,
    REPLAN_HANDOFF_CONTRACT_SCHEMA_VERSION,
    REPLAN_HANDOFF_EVENT_TYPE,
    REPLAN_HANDOFF_ID_PREFIX,
    REPLAN_HANDOFF_MODE,
    REPLAN_HANDOFF_NEXT_CONTROL,
    REPLAN_HANDOFF_STAGE_SCHEMA_VERSION,
    REPLAN_HANDOFF_STATUS,
    REPLAN_TASK_DISPOSITIONS,
    canonical_replan_handoff_definition,
    derive_task_dispositions,
    normalize_replan_handoff_request,
    verify_replan_handoff_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization import (
    commit,
    make_governed_service,
    stage377_source,
)

PRIOR_CONTROL = "stage3.7.8-atomic-replan-commit-supersession-handoff"
CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def stage378_source(service, key: str):
    mission_id, snapshot, candidate, validation = stage377_source(service, key)
    committed, _ = commit(service, mission_id, snapshot, candidate, validation, key)
    return mission_id, snapshot, candidate, validation, committed


def handoff_request(committed, key: str, **overrides):
    mat = committed["replan_commit_contract"]["successor_plan_materialization"]
    src = committed["replan_commit_contract"]["source_bindings"]
    body = {
        "idempotency_key": f"stage378-handoff-{key}",
        "expected_replan_commit_id": committed["replan_commit_id"],
        "expected_replan_commit_sha256": committed["canonical_sha256"],
        "expected_predecessor_plan_version_record_id": committed["predecessor_plan_version_record_id"],
        "expected_predecessor_plan_version": committed["predecessor_plan_version"],
        "expected_predecessor_plan_sha256": mat["predecessor_plan_sha256"],
        "expected_successor_plan_version_record_id": committed["successor_plan_version_record_id"],
        "expected_successor_plan_version": committed["successor_plan_version"],
        "expected_successor_plan_sha256": committed["successor_plan_sha256"],
        "expected_source_state_version": src["source_state_version"],
        "handed_off_by": "stage3.7.8-pytest",
        "reason": "Finalize atomic replan supersession and publish successor handoff",
        "metadata": {"stage": "3.7.8", "key": key},
    }
    body.update(overrides)
    return body


def handoff(service, mission_id, committed, key: str, **overrides):
    body = handoff_request(committed, key, **overrides)
    return service.declare_replan_handoff(mission_id, committed["replan_commit_id"], body), body


def test_health_activates_stage378_and_migration_52(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    h = service.health()
    assert h["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["replan_handoff_database_migration_level"] == 52
    assert h["replan_handoff_stage_schema_version"] == REPLAN_HANDOFF_STAGE_SCHEMA_VERSION
    assert h["replan_handoff_contract_schema_version"] == REPLAN_HANDOFF_CONTRACT_SCHEMA_VERSION
    assert h["replan_handoff_identity_prefix"] == REPLAN_HANDOFF_ID_PREFIX
    assert h["replan_handoff_persistence_store"] == "mission_replan_handoffs"
    assert h["supported_controls"][67:70] == [
        PRIOR_CONTROL,
        "stage3.7.9-adapt-replan-lineage-replay-recovery",
        "stage3.7.10-adapt-replan-acceptance-regression-gate",
    ]
    assert h["supported_controls"][-1] == CONTROL
    assert "mission_replan_handoffs" in REPOSITORY_STORES


def test_definition_declares_atomic_handoff_boundary_and_next_stage(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, *_ = stage378_source(service, "definition")
    d = service.get_replan_handoff_definition(mission_id)["atomic_replan_commit_supersession_handoff_definition"]
    assert d == canonical_replan_handoff_definition()
    assert d["supported_task_dispositions"] == list(REPLAN_TASK_DISPOSITIONS)
    assert d["effective_episode_state"] == "HANDOFF_READY"
    assert d["cancellation_io_performed"] is False
    assert d["routing_performed"] is False
    assert d["dispatch_performed"] is False
    assert d["next_stage"] == "3.7.9"


def test_handoff_verifies_atomic_commit_supersession_and_active_successor(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "normal")
    result, _ = handoff(service, mission_id, committed, "normal")
    assert result["replan_handoff_id"].startswith(REPLAN_HANDOFF_ID_PREFIX)
    assert result["handoff_status"] == REPLAN_HANDOFF_STATUS
    assert result["effective_episode_state"] == "HANDOFF_READY"
    assert result["predecessor_effective_status"] == "SUPERSEDED"
    assert result["successor_effective_status"] == "ACTIVE"
    assert result["active_plan_head_verified"] is True
    assert result["plan_supersession_verified"] is True
    assert result["next_control"] == REPLAN_HANDOFF_NEXT_CONTROL


def test_handoff_contract_self_verifies_and_is_bound_to_stage377_commit(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "contract")
    result, _ = handoff(service, mission_id, committed, "contract")
    c = result["replan_handoff_contract"]
    assert verify_replan_handoff_contract(c)
    assert c["authority_boundary"]["authority"] == REPLAN_HANDOFF_AUTHORITY
    assert c["authority_boundary"]["mode"] == REPLAN_HANDOFF_MODE
    assert c["atomic_commit_binding"]["replan_commit_sha256"] == committed["canonical_sha256"]
    assert c["atomic_commit_binding"]["successor_plan_sha256"] == committed["successor_plan_sha256"]


def test_stage378_performs_no_lifecycle_cancellation_routing_dispatch_or_actuation(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "boundary")
    before_state = service.get_mission_state(mission_id)["mission_state"].copy()
    result, _ = handoff(service, mission_id, committed, "boundary")
    after_state = service.get_mission_state(mission_id)["mission_state"]
    assert after_state == before_state
    assert result["cancellation_io_performed"] is False
    assert result["mission_state_transition_performed"] is False
    assert result["routing_performed"] is False
    assert result["delegation_performed"] is False
    assert result["dispatch_performed"] is False
    assert result["execution_attempt_created"] is False
    assert result["target_actuation"] is False


def test_handoff_records_single_replay_safe_lineage_event(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "event")
    first, body = handoff(service, mission_id, committed, "event")
    second = service.declare_replan_handoff(mission_id, committed["replan_commit_id"], body)
    assert first["handoff_event"]["event_type"] == REPLAN_HANDOFF_EVENT_TYPE
    assert first["handoff_event"]["causation_id"] == first["replan_handoff_id"]
    assert second["handoff_event"]["event_id"] == first["handoff_event"]["event_id"]
    events = [x for x in service.repository.list_mission_events(mission_id) if x["event_type"] == REPLAN_HANDOFF_EVENT_TYPE]
    assert len(events) == 1


def test_exact_idempotent_replay_reuses_handoff_without_duplicate_artifact(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "idem")
    first, body = handoff(service, mission_id, committed, "idem")
    second = service.declare_replan_handoff(mission_id, committed["replan_commit_id"], body)
    assert second["idempotent_replay"] is True
    assert second["replan_handoff_id"] == first["replan_handoff_id"]
    assert len(service.repository.list_replan_handoffs(mission_id)) == 1


def test_idempotency_key_reuse_with_different_material_is_rejected(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "idem-conflict")
    _, body = handoff(service, mission_id, committed, "idem-conflict")
    body["reason"] = "different material"
    with pytest.raises(MissionReplanHandoffConflict, match="different request material"):
        service.declare_replan_handoff(mission_id, committed["replan_commit_id"], body)


def test_only_one_handoff_per_authoritative_replan_commit(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "single")
    handoff(service, mission_id, committed, "single")
    body = handoff_request(committed, "single-second")
    with pytest.raises(MissionReplanHandoffConflict, match="already has"):
        service.declare_replan_handoff(mission_id, committed["replan_commit_id"], body)


def test_stale_replan_commit_hash_fails_closed(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "stale-commit")
    body = handoff_request(committed, "stale-commit", expected_replan_commit_sha256="0" * 64)
    with pytest.raises(MissionConcurrencyConflict, match="ReplanCommit hash"):
        service.declare_replan_handoff(mission_id, committed["replan_commit_id"], body)


def test_stale_active_head_fails_closed_without_handoff_row(tmp_path):
    db = tmp_path / "missions.db"
    service, _ = make_governed_service(db)
    mission_id, _, _, _, committed = stage378_source(service, "stale-head")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_plan_version_heads SET active_plan_version_record_id=?, active_plan_version=?, active_plan_sha256=? WHERE mission_id=?",
            (committed["predecessor_plan_version_record_id"], committed["predecessor_plan_version"],
             committed["replan_commit_contract"]["successor_plan_materialization"]["predecessor_plan_sha256"], mission_id),
        )
        conn.commit()
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        service.declare_replan_handoff(mission_id, committed["replan_commit_id"], handoff_request(committed, "stale-head"))
    assert service.repository.list_replan_handoffs(mission_id) == []


def test_mission_state_drift_after_commit_fails_closed(tmp_path):
    db = tmp_path / "missions.db"
    service, _ = make_governed_service(db)
    mission_id, _, _, _, committed = stage378_source(service, "state-drift")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE mission_states SET state_version=state_version+1 WHERE mission_id=?", (mission_id,))
        conn.commit()
    with pytest.raises(MissionConcurrencyConflict, match="Mission state changed"):
        service.declare_replan_handoff(mission_id, committed["replan_commit_id"], handoff_request(committed, "state-drift"))


def test_disposition_derivation_covers_keep_drain_cancel_and_supersede():
    snapshot = {
        "task_dependency_outcome_context": {
            "tasks": [
                {"planned_task_id":"t1","task_key":"done","task_index":1},
                {"planned_task_id":"t2","task_key":"running-retained","task_index":2},
                {"planned_task_id":"t3","task_key":"running-invalidated","task_index":3},
                {"planned_task_id":"t4","task_key":"pending-invalidated","task_index":4},
            ],
            "task_completions": [{"planned_task_id":"t1"}],
        }
    }
    candidate = {"candidate_successor_plan":{"candidate_tasks":[{"source_planned_task_id":"t1"},{"source_planned_task_id":"t2"}]}}
    attempts = [
        {"execution_attempt_id":"a2","planned_task_id":"t2","plan_version_record_id":"p-old"},
        {"execution_attempt_id":"a3","planned_task_id":"t3","plan_version_record_id":"p-old"},
    ]
    rows = derive_task_dispositions(
        snapshot_contract=snapshot, candidate_contract=candidate, execution_attempts=attempts,
        execution_deliveries=[{"execution_attempt_id":"a2"},{"execution_attempt_id":"a3"}],
        execution_running_projections=[{"execution_attempt_id":"a2","heartbeat_sequence":1},{"execution_attempt_id":"a3","heartbeat_sequence":1}],
        execution_result_captures=[], execution_termination_controls=[], predecessor_plan_version_record_id="p-old",
    )
    by_id = {x["source_planned_task_id"]:x for x in rows}
    assert by_id["t1"]["disposition"] == "KEEP"
    assert by_id["t2"]["disposition"] == "DRAIN"
    assert by_id["t3"]["disposition"] == "CANCEL"
    assert by_id["t3"]["stage35_termination_control_required"] is True
    assert by_id["t3"]["cancellation_io_performed"] is False
    assert by_id["t4"]["disposition"] == "SUPERSEDE"


def test_normal_stage377_candidate_handoff_keeps_unfinished_tasks_for_stage34(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "keep")
    result, _ = handoff(service, mission_id, committed, "keep")
    assert result["task_disposition_count"] == 3
    assert result["keep_count"] == 3
    assert result["drain_count"] == result["cancel_count"] == result["supersede_count"] == result["replace_count"] == 0
    assert all(x["new_dispatch_required"] is True for x in result["task_dispositions"])
    assert result["routing_performed"] is False


def test_request_forbids_caller_supplied_disposition_or_execution_actions():
    body = {
        "idempotency_key":"x", "expected_replan_commit_id":"rpcom-x", "expected_replan_commit_sha256":"0"*64,
        "expected_predecessor_plan_version_record_id":"pver-x", "expected_predecessor_plan_version":1,
        "expected_predecessor_plan_sha256":"1"*64, "expected_successor_plan_version_record_id":"pver-y",
        "expected_successor_plan_version":2, "expected_successor_plan_sha256":"2"*64,
        "expected_source_state_version":1, "handed_off_by":"tester", "metadata":{},
        "task_dispositions":[{"disposition":"CANCEL"}],
    }
    with pytest.raises(MissionValidationError, match="unsupported atomic replan handoff field"):
        normalize_replan_handoff_request(body)


def test_read_surfaces_expose_by_id_by_commit_and_history(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "reads")
    result, _ = handoff(service, mission_id, committed, "reads")
    by_id = service.get_replan_handoff(mission_id, result["replan_handoff_id"])
    by_commit = service.get_replan_handoff_for_commit(mission_id, committed["replan_commit_id"])
    history = service.get_replan_handoff_history(mission_id)
    assert by_id["canonical_sha256"] == result["canonical_sha256"]
    assert by_commit["replan_handoff_id"] == result["replan_handoff_id"]
    assert history["replan_handoff_count"] == 1


def test_repository_reconstruction_includes_and_verifies_stage378_handoff(tmp_path):
    service, _ = make_governed_service(tmp_path / "missions.db")
    mission_id, _, _, _, committed = stage378_source(service, "repository")
    result, _ = handoff(service, mission_id, committed, "repository")
    recovered = service.get_mission_repository(mission_id)
    manifest = recovered["persistence_manifest"]
    handoffs = manifest["atomic_replan_supersession_handoff_store"]["handoffs"]
    assert manifest["repository_migration_level"] == 53
    assert recovered["integrity_status"] == "PASS"
    assert recovered["record_counts"]["mission_replan_handoffs"] == 1
    assert handoffs[0]["replan_handoff_id"] == result["replan_handoff_id"]


def test_api_surface_exposes_stage378_get_post_history_and_definition_routes():
    source_text = inspect.getsource(MissionOrchestratorHandler)
    assert '"replan-handoffs"' in source_text
    assert '"atomic-replan-commit-supersession-handoff-definition"' in source_text
    assert "declare_replan_handoff" in source_text
    assert "get_replan_handoff_for_commit" in source_text
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
