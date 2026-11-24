from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionRepositoryIntegrityError,
    MissionTaskReadinessProjectionConflict,
    MissionTaskReadinessProjectionGuardRejected,
    MissionTaskReadinessProjectionNotFound,
    MissionValidationError,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.task_readiness_projection import (
    SCHEDULING_PROJECTION_MODE,
    TASK_BLOCKED_DEPENDENCY,
    TASK_READINESS_PROJECTION_ID_PREFIX,
    TASK_READINESS_PROJECTION_MODE,
    TASK_READINESS_PROJECTION_SCHEMA_VERSION,
    TASK_READINESS_PROJECTION_STATES,
    TASK_READY,
    canonical_task_readiness_projection_definition,
    verify_task_readiness_projection_contract,
)
from tests.test_stage3_3_7_plan_versioning_replanning_supersession import (
    activate_v1,
    enter_replanning,
    make_service,
    provision_validated,
    replan_request,
)


def projection_request(service, mission_id: str, key: str, **overrides) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    active = service.get_active_plan_version(mission_id)
    body = {
        "idempotency_key": f"stage338-projection-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "created_by": "stage3.3.8-pytest",
        "reason": "Project structural task readiness and dependency scheduling waves",
        "metadata": {"stage": "3.3.8", "key": key},
    }
    body.update(overrides)
    return body


def provision_active(service, key: str):
    mission_id, *_, validation = provision_validated(service, key)
    active = activate_v1(service, mission_id, validation, key)
    return mission_id, active


def create_projection(service, mission_id: str, key: str, **overrides):
    return service.create_task_readiness_projection(
        mission_id, projection_request(service, mission_id, key, **overrides)
    )


def test_health_activates_stage338_projection_without_authorization_dispatch_or_actuation(tmp_path):
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
    assert health["task_readiness_projection_schema_version"] == TASK_READINESS_PROJECTION_SCHEMA_VERSION
    assert health["task_readiness_projection_mode"] == TASK_READINESS_PROJECTION_MODE
    assert health["task_readiness_projection_identity_prefix"] == TASK_READINESS_PROJECTION_ID_PREFIX
    assert health["task_readiness_projection_allowed_states"] == sorted(TASK_READINESS_PROJECTION_STATES)
    assert health["task_readiness_projection_ready_status"] == TASK_READY
    assert health["task_readiness_projection_blocked_status"] == TASK_BLOCKED_DEPENDENCY
    assert health["task_readiness_projection_scheduling_mode"] == SCHEDULING_PROJECTION_MODE
    assert health["task_readiness_projection_requires_active_plan_version"] is True
    assert health["task_readiness_projection_one_per_plan_version"] is True
    assert health["task_readiness_projection_performed"] is True
    assert health["task_readiness_projection_scheduling_projection_performed"] is True
    assert health["task_readiness_projection_wall_clock_schedule_created"] is False
    assert health["task_readiness_projection_resource_assignment_performed"] is False
    assert health["task_readiness_projection_governance_query_performed"] is False
    assert health["task_readiness_projection_readiness_is_permission"] is False
    assert health["task_readiness_projection_ready_is_authorized"] is False
    assert health["task_readiness_projection_task_is_dispatch"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["task_readiness_projection_target_action_dispatch_enabled"] is False
    assert health["task_readiness_projection_target_actuation"] is False
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "task_readiness_projection_version" in health["observed_version_domains"]


def test_projection_definition_is_discoverable_before_projection(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "definition")
    result = service.get_task_readiness_projection_definition(mission_id)
    assert result["active_projection_registered"] is False
    assert result["registered_projection_count"] == 0
    assert result["active_plan_head"]["active_plan_version"] == 1
    assert result["task_readiness_projection_definition"] == canonical_task_readiness_projection_definition()


def test_projection_requires_active_stage337_plan_version(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, *_, validation = provision_validated(service, "no-active")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    payload = {
        "idempotency_key": "stage338-no-active",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": "pver-missing",
        "expected_active_plan_version": 1,
        "expected_active_plan_sha256": "0" * 64,
        "created_by": "stage3.3.8-pytest",
    }
    with pytest.raises(MissionTaskReadinessProjectionGuardRejected, match="active Stage-3.3.7"):
        service.create_task_readiness_projection(mission_id, payload)


def test_projection_materializes_root_ready_dependents_blocked_and_dependency_waves(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active = provision_active(service, "projection")
    result = create_projection(service, mission_id, "projection")
    assert result["idempotent_replay"] is False
    assert result["projection_id"].startswith(TASK_READINESS_PROJECTION_ID_PREFIX)
    assert result["plan_version_record_id"] == active["plan_version_record_id"]
    assert result["plan_version"] == 1
    assert result["effective_status"] == "ACTIVE"
    assert result["task_count"] == 3
    assert result["ready_task_count"] == 1
    assert result["blocked_task_count"] == 2
    assert result["ready_task_keys"] == ["collect-cti"]
    assert result["blocked_task_keys"] == ["analyze-cti", "report-findings"]
    by_key = {item["task_key"]: item for item in result["task_readiness"]}
    assert by_key["collect-cti"]["readiness_status"] == TASK_READY
    assert by_key["collect-cti"]["unmet_dependency_task_keys"] == []
    assert by_key["collect-cti"]["structurally_ready"] is True
    assert by_key["analyze-cti"]["readiness_status"] == TASK_BLOCKED_DEPENDENCY
    assert by_key["analyze-cti"]["unmet_dependency_task_keys"] == ["collect-cti"]
    assert by_key["report-findings"]["unmet_dependency_task_keys"] == ["analyze-cti"]
    assert all(item["authorization_granted"] is False for item in result["task_readiness"])
    assert all(item["dispatch_performed"] is False for item in result["task_readiness"])
    schedule = result["scheduling_projection"]
    assert schedule["mode"] == SCHEDULING_PROJECTION_MODE
    assert schedule["wave_count"] == 3
    assert [wave["task_keys"] for wave in schedule["waves"]] == [
        ["collect-cti"], ["analyze-cti"], ["report-findings"]
    ]
    assert schedule["structural_order_only"] is True
    assert schedule["wall_clock_schedule_created"] is False
    assert schedule["resource_assignment_performed"] is False
    assert schedule["dispatch_performed"] is False
    assert verify_task_readiness_projection_contract(result["projection_contract"])
    assert result["readiness_is_permission"] is False
    assert result["ready_is_authorized"] is False
    assert result["governance_authorization_query_performed"] is False
    assert result["target_action_dispatch_enabled"] is False
    assert result["target_actuation"] is False


def test_exact_replay_is_idempotent_and_emits_no_duplicate_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "replay")
    request = projection_request(service, mission_id, "replay")
    first = service.create_task_readiness_projection(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.create_task_readiness_projection(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["projection_id"] == first["projection_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_only_one_immutable_projection_is_allowed_per_plan_version(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "single")
    create_projection(service, mission_id, "single")
    with pytest.raises(MissionTaskReadinessProjectionConflict, match="already has an immutable"):
        create_projection(service, mission_id, "single-2")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_version_sha256", "0" * 64, "expected_version_sha256"),
        ("expected_state_version", 999, "expected_state_version"),
        ("expected_active_plan_version_record_id", "pver-wrong", "expected_active_plan_version_record_id"),
        ("expected_active_plan_version", 99, "expected_active_plan_version"),
        ("expected_active_plan_sha256", "0" * 64, "expected_active_plan_sha256"),
    ],
)
def test_projection_rejects_stale_state_vector_or_active_plan_head(tmp_path, field, value, message):
    service = make_service(tmp_path / f"{field}.db")
    mission_id, _ = provision_active(service, field)
    payload = projection_request(service, mission_id, field)
    payload[field] = value
    with pytest.raises(MissionConcurrencyConflict, match=message):
        service.create_task_readiness_projection(mission_id, payload)


@pytest.mark.parametrize(
    "field",
    [
        "task_status", "completion", "authorization", "permission", "schedule",
        "resource_assignment", "dispatch", "execution", "target_action",
    ],
)
def test_projection_request_rejects_caller_supplied_status_authority_scheduling_or_execution_surfaces(tmp_path, field):
    service = make_service(tmp_path / f"surface-{field}.db")
    mission_id, _ = provision_active(service, f"surface-{field}")
    payload = projection_request(service, mission_id, f"surface-{field}")
    payload[field] = True
    with pytest.raises(MissionValidationError, match="does not accept caller-supplied"):
        service.create_task_readiness_projection(mission_id, payload)


def test_projection_is_allowed_in_replanning_and_binds_exact_active_successor(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "replanning-only")
    replan = enter_replanning(service, mission_id, "replanning-only")
    v2 = service.create_replan_successor_plan_version(
        mission_id, replan_request(service, mission_id, replan, "replanning-only")
    )
    result = create_projection(service, mission_id, "replanning-only-v2")
    assert result["projection_contract"]["source_bindings"]["state"] == "REPLANNING"
    assert result["plan_version"] == 2
    assert result["plan_version_record_id"] == v2["plan_version_record_id"]
    assert result["projection_contract"]["source_bindings"]["active_plan_sha256"] == v2["canonical_sha256"]


def test_replanning_successor_gets_separate_projection_and_prior_projection_becomes_superseded(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "supersession")
    p1 = create_projection(service, mission_id, "supersession-v1")
    p1_contract = deepcopy(p1["projection_contract"])
    replan = enter_replanning(service, mission_id, "supersession")
    v2 = service.create_replan_successor_plan_version(
        mission_id, replan_request(service, mission_id, replan, "supersession-v2")
    )
    p2 = create_projection(service, mission_id, "supersession-v2")
    assert p2["plan_version"] == 2
    assert p2["plan_version_record_id"] == v2["plan_version_record_id"]
    history = service.get_task_readiness_projection_history(mission_id)
    assert history["projection_count"] == 2
    assert [item["plan_version"] for item in history["projections"]] == [1, 2]
    assert [item["effective_status"] for item in history["projections"]] == ["SUPERSEDED", "ACTIVE"]
    assert history["projections"][0]["projection_contract"] == p1_contract


def test_version_vector_advances_only_readiness_projection_domain_for_projection(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    bv = before["version_vector"]["versions"]
    assert bv["plan_versioning_version"] == 1
    assert bv["task_readiness_projection_version"] == 0
    result = create_projection(service, mission_id, "vector")
    after = service.get_mission_version_vector(mission_id)
    av = after["version_vector"]["versions"]
    for key in (
        "mission_plan_version", "planner_input_snapshot_version", "task_decomposition_version",
        "task_dependency_graph_version", "planner_generation_version", "plan_validation_version",
        "plan_versioning_version",
    ):
        assert av[key] == bv[key]
    assert av["task_readiness_projection_version"] == 1
    assert result["projection_contract"]["source_bindings"]["source_version_sha256"] == before["version_sha256"]
    assert after["version_sha256"] != before["version_sha256"]


def test_stage338_emits_exactly_one_causal_projection_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "event")
    projection = create_projection(service, mission_id, "event")
    events = service.get_mission_events(mission_id)["events"]
    projected = [e for e in events if e["event_type"] == "MISSION_TASK_READINESS_PROJECTED"]
    assert len(projected) == 1
    event = projected[0]
    assert event["causation_id"] == projection["projection_id"]
    assert int(event["plan_version"]) == 1
    assert event["payload"]["projection_id"] == projection["projection_id"]
    assert event["payload"]["ready_task_count"] == 1
    assert event["payload"]["blocked_task_count"] == 2
    assert event["payload"]["readiness_is_permission"] is False
    assert event["payload"]["dispatch_performed"] is False


def test_active_projection_not_found_before_projection(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "not-found")
    with pytest.raises(MissionTaskReadinessProjectionNotFound):
        service.get_active_task_readiness_projection(mission_id)
    with pytest.raises(MissionTaskReadinessProjectionNotFound):
        service.get_task_readiness_projection_history(mission_id)


def test_repository_integrity_and_restart_reconstruct_projection_without_external_reads(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _ = provision_active(service, "restart")
    created = create_projection(service, mission_id, "restart")
    repo_before = service.get_mission_repository(mission_id)
    assert repo_before["integrity_status"] == "PASS"
    assert repo_before["record_counts"]["mission_task_readiness_projections"] == 1
    assert repo_before["repository"]["migration_level"] == 53

    restarted = make_service(db)
    active = restarted.get_active_task_readiness_projection(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)
    assert active["projection_id"] == created["projection_id"]
    assert active["canonical_sha256"] == created["canonical_sha256"]
    assert active["ready_task_keys"] == ["collect-cti"]
    assert repo_after["integrity_status"] == "PASS"
    assert repo_after["repository_sha256"] == repo_before["repository_sha256"]


def test_repository_integrity_detects_tampered_projection_contract(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _ = provision_active(service, "tamper")
    projection = create_projection(service, mission_id, "tamper")
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT canonical_json FROM mission_task_readiness_projections WHERE projection_id=?",
        (projection["projection_id"],),
    ).fetchone()
    tampered = json.loads(row[0])
    tampered["projection"]["ready_task_count"] = 99
    conn.execute(
        "UPDATE mission_task_readiness_projections SET canonical_json=? WHERE projection_id=?",
        (json.dumps(tampered, sort_keys=True, separators=(",", ":")), projection["projection_id"]),
    )
    conn.commit()
    conn.close()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_migration_016_declares_readiness_store_and_preserves_authority_boundary():
    sql = Path("migrations/016_stage3_3_8_task_readiness_scheduling_projection.sql").read_text().lower()
    assert "mission_task_readiness_projections" in sql
    assert "plan_version_record_id" in sql
    assert "ready_task_count" in sql
    assert "blocked_task_count" in sql
    assert "wave_count" in sql
    assert "migration_level" in sql and "16" in sql
    assert "governance" in sql
    assert "dispatch" in sql
    assert "actuation" in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[16].name == "017_stage3_3_9_planning_event_lineage_replay_recovery.sql"
