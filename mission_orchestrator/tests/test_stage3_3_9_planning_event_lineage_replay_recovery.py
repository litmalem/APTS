from __future__ import annotations

from pathlib import Path
import json
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionPlanningRecoveryConflict,
    MissionPlanningRecoveryGuardRejected,
    MissionPlanningRecoveryNotFound,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.planning_event_lineage import (
    PLANNING_ARTIFACT_EVENT_TYPES,
    PLANNING_EVENT_LINEAGE_MODE,
    PLANNING_EVENT_LINEAGE_SCHEMA_VERSION,
    PLANNING_EVENT_REPLAY_SCHEMA_VERSION,
    PLANNING_RECOVERY_CHECKPOINT_ID_PREFIX,
    PLANNING_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
    PLANNING_RECOVERY_MODE,
    PLANNING_REPLAY_MODE,
    canonical_planning_event_lineage_definition,
    verify_planning_recovery_checkpoint_contract,
)
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from tests.test_stage3_3_8_task_readiness_scheduling_projection import (
    create_projection,
    make_service,
    provision_active,
)
from tests.test_stage3_3_7_plan_versioning_replanning_supersession import (
    enter_replanning,
    replan_request,
)


def recovery_request(service, mission_id: str, projection: dict, key: str, **overrides) -> dict:
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    active = service.get_active_plan_version(mission_id)
    lineage = service.get_planning_event_lineage(mission_id)
    body = {
        "idempotency_key": f"stage339-recovery-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": projection["projection_id"],
        "expected_task_readiness_projection_sha256": projection["canonical_sha256"],
        "expected_planning_event_count": lineage["planning_event_count"],
        "expected_planning_event_tip_sha256": lineage["planning_event_tip_sha256"],
        "created_by": "stage3.3.9-pytest",
        "reason": "Freeze deterministic planning replay and durable recovery state",
        "metadata": {"stage": "3.3.9", "key": key},
    }
    body.update(overrides)
    return body


def provision_projected(service, key: str):
    mission_id, active = provision_active(service, key)
    projection = create_projection(service, mission_id, key)
    return mission_id, active, projection


def create_checkpoint(service, mission_id: str, projection: dict, key: str, **overrides):
    return service.create_planning_recovery_checkpoint(
        mission_id, recovery_request(service, mission_id, projection, key, **overrides)
    )


def test_health_activates_stage339_lineage_replay_recovery_without_authority_or_execution_expansion(tmp_path):
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
    assert health["planning_event_lineage_schema_version"] == PLANNING_EVENT_LINEAGE_SCHEMA_VERSION
    assert health["planning_event_replay_schema_version"] == PLANNING_EVENT_REPLAY_SCHEMA_VERSION
    assert health["planning_recovery_checkpoint_schema_version"] == PLANNING_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert health["planning_recovery_checkpoint_identity_prefix"] == PLANNING_RECOVERY_CHECKPOINT_ID_PREFIX
    assert health["planning_event_lineage_mode"] == PLANNING_EVENT_LINEAGE_MODE
    assert health["planning_event_replay_mode"] == PLANNING_REPLAY_MODE
    assert health["planning_recovery_mode"] == PLANNING_RECOVERY_MODE
    assert health["planning_recovery_requires_active_plan_version"] is True
    assert health["planning_recovery_requires_active_readiness_projection"] is True
    assert health["planning_recovery_one_checkpoint_per_plan_version"] is True
    assert health["planning_recovery_replay_read_only"] is True
    assert health["planning_recovery_restart_reconstruction_enabled"] is True
    assert health["planning_recovery_planner_rerun_performed"] is False
    assert health["planning_recovery_external_model_invocation_performed"] is False
    assert health["planning_recovery_external_network_io_performed"] is False
    assert health["planning_recovery_governance_query_performed"] is False
    assert health["planning_recovery_recovery_is_authorization"] is False
    assert health["planning_recovery_replay_is_execution"] is False
    assert health["planning_recovery_readiness_is_permission"] is False
    assert health["planning_recovery_task_is_dispatch"] is False
    assert health["planning_recovery_target_action_dispatch_enabled"] is False
    assert health["planning_recovery_target_actuation"] is False
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert "planning_recovery_version" in health["observed_version_domains"]


def test_definition_is_discoverable_before_checkpoint(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_projected(service, "definition")
    result = service.get_planning_event_lineage_definition(mission_id)
    assert result["active_recovery_checkpoint_registered"] is False
    assert result["registered_checkpoint_count"] == 0
    assert result["active_plan_head"]["active_plan_version"] == 1
    assert result["planning_event_lineage_definition"] == canonical_planning_event_lineage_definition()


def test_planning_lineage_filters_canonical_planning_events_and_preserves_order(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_projected(service, "lineage")
    result = service.get_planning_event_lineage(mission_id)
    types = [item["event_type"] for item in result["planning_events"]]
    for required in (
        "MISSION_PLAN_CONTRACT_REGISTERED",
        "MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED",
        "MISSION_TASK_DECOMPOSITION_REGISTERED",
        "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED",
        "MISSION_PLANNER_INVOKED",
        "MISSION_PLAN_GENERATED",
        "MISSION_PLAN_VALIDATED_FEASIBLE",
        "MISSION_PLAN_VERSION_ACTIVATED",
        "MISSION_TASK_READINESS_PROJECTED",
    ):
        assert required in types
    assert "MISSION_REGISTERED" not in types
    assert result["planning_event_count"] == len(result["planning_events"])
    assert result["planning_event_tip_sha256"] == result["planning_events"][-1]["event_sha256"]
    assert result["integrity_status"] == "PASS"
    assert result["full_mission_event_chain_verified"] is True


def test_planning_replay_is_read_only_and_has_no_event_side_effect(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_projected(service, "replay-read")
    before = service.get_mission_events(mission_id)["event_count"]
    replay1 = service.get_planning_event_replay(mission_id)
    replay2 = service.get_planning_event_replay(mission_id)
    after = service.get_mission_events(mission_id)["event_count"]
    assert before == after
    assert replay1["replay"]["replay_sha256"] == replay2["replay"]["replay_sha256"]
    assert replay1["read_only"] is True
    assert replay1["side_effects_performed"] is False
    assert replay1["planner_rerun_performed"] is False
    assert replay1["target_action_dispatch_enabled"] is False


def test_checkpoint_requires_stage338_projection_for_active_plan(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _ = provision_active(service, "no-readiness")
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    active = service.get_active_plan_version(mission_id)
    lineage = service.get_planning_event_lineage(mission_id)
    payload = {
        "idempotency_key": "stage339-no-readiness",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_task_readiness_projection_id": "rproj-missing",
        "expected_task_readiness_projection_sha256": "0" * 64,
        "expected_planning_event_count": lineage["planning_event_count"],
        "expected_planning_event_tip_sha256": lineage["planning_event_tip_sha256"],
        "created_by": "stage3.3.9-pytest",
    }
    with pytest.raises(MissionPlanningRecoveryGuardRejected, match="Stage-3.3.8 readiness projection"):
        service.create_planning_recovery_checkpoint(mission_id, payload)


def test_checkpoint_materializes_replay_and_recoverable_active_plan_state(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_projected(service, "checkpoint")
    lineage_before = service.get_planning_event_lineage(mission_id)
    result = create_checkpoint(service, mission_id, projection, "checkpoint")
    assert result["idempotent_replay"] is False
    assert result["checkpoint_id"].startswith(PLANNING_RECOVERY_CHECKPOINT_ID_PREFIX)
    assert result["checkpoint_version"] == 1
    assert result["plan_version_record_id"] == active["plan_version_record_id"]
    assert result["plan_version"] == 1
    assert result["effective_status"] == "ACTIVE"
    assert result["source_event_count"] == lineage_before["planning_event_count"]
    assert result["source_event_tip_sha256"] == lineage_before["planning_event_tip_sha256"]
    assert result["readiness_projection_id"] == projection["projection_id"]
    recovery = result["recovery_state"]
    assert recovery["active_plan_version_record_id"] == active["plan_version_record_id"]
    assert recovery["active_plan_sha256"] == active["canonical_sha256"]
    assert recovery["task_readiness_projection_id"] == projection["projection_id"]
    assert recovery["task_count"] == 3
    assert recovery["ready_task_count"] == 1
    assert recovery["blocked_task_count"] == 2
    assert recovery["wave_count"] == 3
    assert recovery["ready_task_keys"] == ["collect-cti"]
    assert verify_planning_recovery_checkpoint_contract(result["recovery_checkpoint"])
    assert result["planner_rerun_performed"] is False
    assert result["recovery_is_authorization"] is False
    assert result["replay_is_execution"] is False
    assert result["target_action_dispatch_enabled"] is False
    assert result["target_actuation"] is False


def test_exact_checkpoint_replay_is_idempotent_and_emits_no_duplicate_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "replay")
    request = recovery_request(service, mission_id, projection, "replay")
    first = service.create_planning_recovery_checkpoint(mission_id, request)
    event_count = service.get_mission_events(mission_id)["event_count"]
    replay = service.create_planning_recovery_checkpoint(mission_id, request)
    assert replay["idempotent_replay"] is True
    assert replay["checkpoint_id"] == first["checkpoint_id"]
    assert replay["canonical_sha256"] == first["canonical_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == event_count


def test_only_one_immutable_recovery_checkpoint_is_allowed_per_plan_version(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "single")
    create_checkpoint(service, mission_id, projection, "single")
    with pytest.raises(MissionPlanningRecoveryConflict, match="already has an immutable"):
        create_checkpoint(service, mission_id, projection, "single-2")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_version_sha256", "0" * 64, "expected_version_sha256"),
        ("expected_state_version", 999, "expected_state_version"),
        ("expected_active_plan_version_record_id", "pver-wrong", "expected_active_plan_version_record_id"),
        ("expected_active_plan_version", 99, "expected_active_plan_version"),
        ("expected_active_plan_sha256", "0" * 64, "expected_active_plan_sha256"),
        ("expected_task_readiness_projection_id", "rproj-wrong", "expected_task_readiness_projection_id"),
        ("expected_task_readiness_projection_sha256", "0" * 64, "expected_task_readiness_projection_sha256"),
        ("expected_planning_event_count", 999, "expected_planning_event_count"),
        ("expected_planning_event_tip_sha256", "0" * 64, "expected_planning_event_tip_sha256"),
    ],
)
def test_checkpoint_rejects_stale_state_vector_plan_readiness_or_lineage(tmp_path, field, value, message):
    service = make_service(tmp_path / f"{field}.db")
    mission_id, _, projection = provision_projected(service, field)
    payload = recovery_request(service, mission_id, projection, field)
    payload[field] = value
    with pytest.raises(MissionConcurrencyConflict, match=message):
        service.create_planning_recovery_checkpoint(mission_id, payload)


@pytest.mark.parametrize(
    "field",
    ["plan", "tasks", "readiness", "authorization", "dispatch", "execution", "recovery_state", "replay"],
)
def test_checkpoint_request_rejects_caller_supplied_planning_authority_execution_or_recovery_surfaces(tmp_path, field):
    service = make_service(tmp_path / f"surface-{field}.db")
    mission_id, _, projection = provision_projected(service, f"surface-{field}")
    payload = recovery_request(service, mission_id, projection, f"surface-{field}")
    payload[field] = True
    with pytest.raises(MissionValidationError, match="does not accept caller-supplied"):
        service.create_planning_recovery_checkpoint(mission_id, payload)


def test_version_vector_advances_only_planning_recovery_domain_for_checkpoint(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "vector")
    before = service.get_mission_version_vector(mission_id)
    bv = before["version_vector"]["versions"]
    assert bv["task_readiness_projection_version"] == 1
    assert bv["planning_recovery_version"] == 0
    create_checkpoint(service, mission_id, projection, "vector")
    after = service.get_mission_version_vector(mission_id)
    av = after["version_vector"]["versions"]
    for key in (
        "mission_plan_version",
        "planner_input_snapshot_version",
        "task_decomposition_version",
        "task_dependency_graph_version",
        "planner_generation_version",
        "plan_validation_version",
        "plan_versioning_version",
        "task_readiness_projection_version",
    ):
        assert av[key] == bv[key]
    assert av["planning_recovery_version"] == 1
    assert after["version_sha256"] != before["version_sha256"]


def test_stage339_emits_exactly_one_causal_recovery_checkpoint_event(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "event")
    checkpoint = create_checkpoint(service, mission_id, projection, "event")
    events = service.get_mission_events(mission_id)["events"]
    selected = [e for e in events if e["event_type"] == "MISSION_PLANNING_RECOVERY_CHECKPOINTED"]
    assert len(selected) == 1
    event = selected[0]
    assert event["causation_id"] == checkpoint["checkpoint_id"]
    assert int(event["plan_version"]) == 1
    assert event["payload"]["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert event["payload"]["canonical_sha256"] == checkpoint["canonical_sha256"]
    assert event["payload"]["planner_rerun_performed"] is False
    assert event["payload"]["recovery_is_authorization"] is False
    assert event["payload"]["dispatch_performed"] is False


def test_checkpoint_event_extends_planning_lineage_but_checkpoint_source_snapshot_remains_immutable(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "event-lineage")
    before = service.get_planning_event_lineage(mission_id)
    checkpoint = create_checkpoint(service, mission_id, projection, "event-lineage")
    after = service.get_planning_event_lineage(mission_id)
    assert after["planning_event_count"] == before["planning_event_count"] + 1
    assert after["planning_events"][-1]["event_type"] == "MISSION_PLANNING_RECOVERY_CHECKPOINTED"
    assert checkpoint["source_event_count"] == before["planning_event_count"]
    assert checkpoint["source_event_tip_sha256"] == before["planning_event_tip_sha256"]
    assert checkpoint["recovery_checkpoint"]["replay"]["event_ids"][-1] == before["planning_event_tip_event_id"]


def test_recover_planning_state_uses_checkpoint_and_durable_artifacts_without_planner_rerun(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection = provision_projected(service, "recover")
    checkpoint = create_checkpoint(service, mission_id, projection, "recover")
    recovered = service.recover_planning_state(mission_id)
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["recovery_consistency"] == "PASS"
    assert recovered["recovered_state"]["active_plan_version_record_id"] == active["plan_version_record_id"]
    assert recovered["recovered_state"]["task_readiness_projection_id"] == projection["projection_id"]
    assert recovered["repository_integrity_status"] == "PASS"
    assert recovered["recovered_from_durable_repository"] is True
    assert recovered["planner_rerun_performed"] is False
    assert recovered["external_model_invocation_performed"] is False
    assert recovered["external_network_io_performed"] is False
    assert recovered["governance_authorization_query_performed"] is False
    assert recovered["target_action_dispatch_enabled"] is False
    assert recovered["target_actuation"] is False


def test_restart_reconstructs_active_checkpoint_and_recovery_without_external_reads(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, projection = provision_projected(service, "restart")
    checkpoint = create_checkpoint(service, mission_id, projection, "restart")
    repo_before = service.get_mission_repository(mission_id)

    restarted = make_service(db)
    active_checkpoint = restarted.get_active_planning_recovery_checkpoint(mission_id)
    recovered = restarted.recover_planning_state(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)
    assert active_checkpoint["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["recovery_consistency"] == "PASS"
    assert recovered["planner_rerun_performed"] is False
    assert repo_after["integrity_status"] == "PASS"
    assert repo_after["repository_sha256"] == repo_before["repository_sha256"]


def test_replanning_successor_gets_separate_checkpoint_and_prior_checkpoint_becomes_superseded(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection_v1 = provision_projected(service, "replan")
    checkpoint_v1 = create_checkpoint(service, mission_id, projection_v1, "replan-v1")
    replan = enter_replanning(service, mission_id, "replan")
    successor = service.create_replan_successor_plan_version(
        mission_id, replan_request(service, mission_id, replan, "replan-v2")
    )
    projection_v2 = create_projection(service, mission_id, "replan-v2")
    checkpoint_v2 = create_checkpoint(service, mission_id, projection_v2, "replan-v2")
    assert successor["plan_version"] == 2
    assert checkpoint_v2["plan_version"] == 2
    assert checkpoint_v2["checkpoint_version"] == 2
    history = service.get_planning_recovery_history(mission_id)
    assert history["checkpoint_count"] == 2
    assert [item["plan_version"] for item in history["checkpoints"]] == [1, 2]
    assert [item["effective_status"] for item in history["checkpoints"]] == ["SUPERSEDED", "ACTIVE"]
    assert history["checkpoints"][0]["canonical_sha256"] == checkpoint_v1["canonical_sha256"]
    recovered = service.recover_planning_state(mission_id)
    assert recovered["checkpoint_id"] == checkpoint_v2["checkpoint_id"]
    assert recovered["recovered_state"]["active_plan_version"] == 2


def test_active_recovery_not_found_before_checkpoint(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _ = provision_projected(service, "not-found")
    with pytest.raises(MissionPlanningRecoveryNotFound):
        service.get_active_planning_recovery_checkpoint(mission_id)
    with pytest.raises(MissionPlanningRecoveryNotFound):
        service.get_planning_recovery_history(mission_id)
    with pytest.raises(MissionPlanningRecoveryNotFound):
        service.recover_planning_state(mission_id)


def test_repository_integrity_and_manifest_include_planning_recovery_store(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "repository")
    checkpoint = create_checkpoint(service, mission_id, projection, "repository")
    repo = service.get_mission_repository(mission_id)
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert "mission_planning_recovery_checkpoints" in repo["repository"]["stores"]
    assert repo["record_counts"]["mission_planning_recovery_checkpoints"] == 1
    stored = repo["persistence_manifest"]["planning_recovery_checkpoint_store"]["checkpoints"]
    assert len(stored) == 1
    assert stored[0]["checkpoint_id"] == checkpoint["checkpoint_id"]


def test_repository_integrity_detects_tampered_recovery_checkpoint_contract(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, projection = provision_projected(service, "tamper-contract")
    checkpoint = create_checkpoint(service, mission_id, projection, "tamper-contract")
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT canonical_json FROM mission_planning_recovery_checkpoints WHERE checkpoint_id=?",
        (checkpoint["checkpoint_id"],),
    ).fetchone()
    tampered = json.loads(row[0])
    tampered["recovery_state"]["ready_task_count"] = 99
    conn.execute(
        "UPDATE mission_planning_recovery_checkpoints SET canonical_json=? WHERE checkpoint_id=?",
        (json.dumps(tampered, sort_keys=True, separators=(",", ":")), checkpoint["checkpoint_id"]),
    )
    conn.commit(); conn.close()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_repository_integrity_detects_tampered_recovery_checkpoint_event(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, _, projection = provision_projected(service, "tamper-event")
    checkpoint = create_checkpoint(service, mission_id, projection, "tamper-event")
    event = checkpoint["checkpoint_event"]
    conn = sqlite3.connect(db)
    payload = json.loads(conn.execute("SELECT payload_json FROM mission_events WHERE event_id=?", (event["event_id"],)).fetchone()[0])
    payload["canonical_sha256"] = "0" * 64
    conn.execute(
        "UPDATE mission_events SET payload_json=? WHERE event_id=?",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")), event["event_id"]),
    )
    conn.commit(); conn.close()
    with pytest.raises(MissionRepositoryIntegrityError):
        service.get_mission_repository(mission_id)


def test_full_mission_lineage_remains_hash_chain_valid_after_recovery_checkpoint(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "full-lineage")
    create_checkpoint(service, mission_id, projection, "full-lineage")
    events = service.get_mission_events(mission_id)
    lineage = service.get_mission_lineage(mission_id)
    assert events["integrity_status"] == "PASS"
    assert lineage["integrity_status"] == "PASS"
    assert lineage["event_count"] == events["event_count"]
    assert lineage["causal_edge_count"] == lineage["event_count"] - 1


def test_planning_replay_contains_declared_artifact_event_family(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, projection = provision_projected(service, "family")
    create_checkpoint(service, mission_id, projection, "family")
    replay = service.get_planning_event_replay(mission_id)["replay"]
    types = {event["event_type"] for event in replay["events"]}
    for event_type in PLANNING_ARTIFACT_EVENT_TYPES:
        # Replan event is absent until a replan episode; all other Stage-3.3 planning artifacts are expected here.
        if event_type == "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED":
            continue
        assert event_type in types


def test_migration_017_declares_recovery_store_and_preserves_authority_boundary():
    sql = Path("migrations/017_stage3_3_9_planning_event_lineage_replay_recovery.sql").read_text().lower()
    assert "mission_planning_recovery_checkpoints" in sql
    assert "plan_version_record_id" in sql
    assert "readiness_projection_id" in sql
    assert "source_event_tip_sha256" in sql
    assert "migration_level" in sql and "17" in sql
    assert "authorization" in sql
    assert "dispatch" in sql
    assert "permission" in sql
    assert "governance" in sql
    assert REPOSITORY_MIGRATION_LEVEL == 53
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[16].name == "017_stage3_3_9_planning_event_lineage_replay_recovery.sql"
