from __future__ import annotations

from pathlib import Path

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.planning_acceptance_gate import (
    PLANNING_ACCEPTANCE_GATE_BASELINE,
    PLANNING_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
    PLANNING_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    PLANNING_ACCEPTANCE_GATE_MODE,
    PLANNING_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
    PLANNING_ACCEPTANCE_GATE_SCHEMA_VERSION,
    REQUIRED_PLANNING_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_3_CONTROLS,
    planning_acceptance_gate_contract,
)
from mission_orchestrator.planning_event_lineage import PLANNING_ARTIFACT_EVENT_TYPES
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from tests.test_stage3_3_7_plan_versioning_replanning_supersession import (
    enter_replanning,
    replan_request,
)
from tests.test_stage3_3_8_task_readiness_scheduling_projection import (
    create_projection,
    make_service,
)
from tests.test_stage3_3_9_planning_event_lineage_replay_recovery import (
    create_checkpoint,
    provision_projected,
)


STAGE3310_CONTROL = "stage3.3.10-planning-acceptance-regression-gate"


def provision_closed_planning(service, key: str):
    mission_id, active, projection = provision_projected(service, key)
    checkpoint = create_checkpoint(service, mission_id, projection, key)
    return mission_id, active, projection, checkpoint


def test_stage3310_health_declares_planning_closure_without_new_authority_or_migration(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["control_version"] == "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["supported_controls"][20:30] == [*REQUIRED_STAGE3_3_CONTROLS, STAGE3310_CONTROL]
    assert health["stage3_3_planning_acceptance_gate_schema_version"] == PLANNING_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert health["stage3_3_planning_acceptance_gate_mode"] == PLANNING_ACCEPTANCE_GATE_MODE
    assert health["stage3_3_planning_acceptance_gate_baseline"] == PLANNING_ACCEPTANCE_GATE_BASELINE
    assert health["stage3_3_planning_acceptance_gate_runtime_change_mode"] == PLANNING_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE
    assert health["stage3_3_planning_acceptance_gate_database_change_mode"] == PLANNING_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE
    assert health["stage3_3_planning_acceptance_gate_expected_migration_level"] == 17
    assert health["stage3_3_planning_acceptance_gate_declared_only"] is True
    assert health["stage3_3_planning_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_3_planning_acceptance_gate_external_execution_required"] is True
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False


def test_stage3310_static_contract_requires_all_stage33_controls_and_external_acceptance():
    contract = planning_acceptance_gate_contract()
    assert contract["schema_version"] == PLANNING_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert contract["mode"] == PLANNING_ACCEPTANCE_GATE_MODE
    assert contract["baseline"] == "STAGE_3_3_1_THROUGH_3_3_9"
    assert contract["required_prior_controls"] == list(REQUIRED_STAGE3_3_CONTROLS)
    assert contract["required_gates"] == list(REQUIRED_PLANNING_ACCEPTANCE_GATES)
    assert contract["expected_repository_migration_level"] == PLANNING_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 17
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert contract["existing_local_planner_invocation_preserved"] is True
    assert contract["new_planner_capability_added"] is False
    assert contract["new_durable_store_added"] is False
    assert contract["new_database_migration_added"] is False
    assert contract["plan_is_authorization"] is False
    assert contract["task_is_dispatch"] is False
    assert contract["readiness_is_permission"] is False
    assert contract["planner_is_governance"] is False
    assert contract["replay_is_execution"] is False
    assert contract["recovery_is_authorization"] is False


def test_stage3310_end_to_end_stage331_through_339_materializes_complete_planning_stack(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, checkpoint = provision_closed_planning(service, "stack")

    plan = service.get_mission_plan_contract(mission_id)
    snapshot = service.get_planner_input_snapshot(mission_id)
    decomp = service.get_task_decomposition(mission_id)
    graph = service.get_task_dependency_graph(mission_id)
    invocation = service.get_planner_invocation(mission_id)
    generated = service.get_generated_plan(mission_id)
    validation = service.get_plan_validation(mission_id)
    active_read = service.get_active_plan_version(mission_id)
    readiness = service.get_active_task_readiness_projection(mission_id)
    recovery = service.get_active_planning_recovery_checkpoint(mission_id)

    assert plan["status"] == "contracted"
    assert snapshot["status"] == "snapshotted"
    assert decomp["status"] == "decomposed" and decomp["task_count"] == 3
    assert graph["status"] == "completed" and graph["validation_status"] == "PASS"
    assert invocation["status"] == "completed" and invocation["task_count"] == 3
    assert generated["status"] == "completed"
    assert validation["validation_status"] == "VALIDATED_FEASIBLE" and validation["feasible"] is True
    assert active_read["effective_status"] == "ACTIVE" and active_read["plan_version"] == 1
    assert readiness["effective_status"] == "ACTIVE" and readiness["task_count"] == 3
    assert recovery["effective_status"] == "ACTIVE" and recovery["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert active_read["plan_version_record_id"] == active["plan_version_record_id"]
    assert readiness["projection_id"] == projection["projection_id"]


def test_stage3310_planning_artifacts_preserve_exact_canonical_bindings_and_hash_chain(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active, projection, checkpoint = provision_closed_planning(service, "bindings")
    plan = service.get_mission_plan_contract(mission_id)
    snapshot = service.get_planner_input_snapshot(mission_id)
    decomp = service.get_task_decomposition(mission_id)
    graph = service.get_task_dependency_graph(mission_id)
    invocation = service.get_planner_invocation(mission_id)
    generated = service.get_generated_plan(mission_id)
    validation = service.get_plan_validation(mission_id)

    assert snapshot["plan_id"] == plan["plan_id"]
    assert snapshot["source_plan_sha256"] == plan["canonical_sha256"]
    assert decomp["plan_id"] == plan["plan_id"] and decomp["snapshot_id"] == snapshot["snapshot_id"]
    assert decomp["source_plan_sha256"] == plan["canonical_sha256"]
    assert decomp["source_snapshot_sha256"] == snapshot["canonical_sha256"]
    assert graph["decomposition_id"] == decomp["decomposition_id"]
    assert invocation["planner_invocation"]["input_bindings"]["graph_sha256"] == graph["canonical_sha256"]
    assert generated["planner_invocation_id"] == invocation["planner_invocation_id"]
    assert validation["generated_plan_id"] == generated["generated_plan_id"]
    assert active["plan_version_contract"]["lineage"]["validation"]["canonical_sha256"] == validation["canonical_sha256"]
    assert projection["plan_version_record_id"] == active["plan_version_record_id"]
    assert checkpoint["plan_version_record_id"] == active["plan_version_record_id"]
    assert checkpoint["readiness_projection_id"] == projection["projection_id"]
    assert checkpoint["readiness_projection_sha256"] == projection["canonical_sha256"]


def test_stage3310_planning_lineage_and_replay_cover_committed_artifacts_in_canonical_order(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_closed_planning(service, "lineage")
    lineage = service.get_planning_event_lineage(mission_id)
    replay = service.get_planning_event_replay(mission_id)
    event_types = [event["event_type"] for event in lineage["planning_events"]]

    for event_type in PLANNING_ARTIFACT_EVENT_TYPES:
        if event_type == "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED":
            continue
        assert event_type in event_types
    assert event_types[-1] == "MISSION_PLANNING_RECOVERY_CHECKPOINTED"
    assert lineage["integrity_status"] == "PASS"
    assert lineage["full_mission_event_chain_verified"] is True
    assert lineage["planning_event_tip_sha256"] == lineage["planning_events"][-1]["event_sha256"]
    assert replay["read_only"] is True
    assert replay["side_effects_performed"] is False
    assert [event["event_id"] for event in replay["replay"]["events"]] == [event["event_id"] for event in lineage["planning_events"]]


def test_stage3310_read_only_replay_and_recovery_reads_do_not_mutate_committed_state(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, checkpoint = provision_closed_planning(service, "observational")
    events_before = service.get_mission_events(mission_id)["event_count"]
    repo_before = service.get_mission_repository(mission_id)
    replay1 = service.get_planning_event_replay(mission_id)
    replay2 = service.get_planning_event_replay(mission_id)
    recovered1 = service.recover_planning_state(mission_id)
    recovered2 = service.recover_planning_state(mission_id)
    repo_after = service.get_mission_repository(mission_id)

    assert replay1["replay"]["replay_sha256"] == replay2["replay"]["replay_sha256"]
    assert recovered1["checkpoint_id"] == recovered2["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered1["recovery_consistency"] == recovered2["recovery_consistency"] == "PASS"
    assert service.get_mission_events(mission_id)["event_count"] == events_before
    assert repo_after["repository_sha256"] == repo_before["repository_sha256"]


def test_stage3310_restart_reconstructs_committed_plan_readiness_checkpoint_without_external_work(tmp_path):
    db = tmp_path / "missions.db"
    service = make_service(db)
    mission_id, active, projection, checkpoint = provision_closed_planning(service, "restart")
    repo_before = service.get_mission_repository(mission_id)

    restarted = make_service(db)
    assert restarted.get_active_plan_version(mission_id)["plan_version_record_id"] == active["plan_version_record_id"]
    assert restarted.get_active_task_readiness_projection(mission_id)["projection_id"] == projection["projection_id"]
    assert restarted.get_active_planning_recovery_checkpoint(mission_id)["checkpoint_id"] == checkpoint["checkpoint_id"]
    recovered = restarted.recover_planning_state(mission_id)
    repo_after = restarted.get_mission_repository(mission_id)

    assert recovered["recovery_consistency"] == "PASS"
    assert recovered["recovered_from_durable_repository"] is True
    assert recovered["planner_rerun_performed"] is False
    assert recovered["external_model_invocation_performed"] is False
    assert recovered["external_network_io_performed"] is False
    assert recovered["governance_authorization_query_performed"] is False
    assert recovered["target_action_dispatch_enabled"] is False
    assert recovered["target_actuation"] is False
    assert repo_after["repository_sha256"] == repo_before["repository_sha256"]


def test_stage3310_replanning_creates_successor_projection_checkpoint_and_supersedes_prior_artifacts(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, active_v1, projection_v1, checkpoint_v1 = provision_closed_planning(service, "replan")
    replan = enter_replanning(service, mission_id, "replan")
    v2 = service.create_replan_successor_plan_version(
        mission_id, replan_request(service, mission_id, replan, "replan-v2")
    )
    projection_v2 = create_projection(service, mission_id, "replan-v2")
    checkpoint_v2 = create_checkpoint(service, mission_id, projection_v2, "replan-v2")

    plan_history = service.get_plan_version_history(mission_id)
    readiness_history = service.get_task_readiness_projection_history(mission_id)
    recovery_history = service.get_planning_recovery_history(mission_id)

    assert v2["plan_version"] == 2 and v2["predecessor_plan_version_record_id"] == active_v1["plan_version_record_id"]
    assert [item["effective_status"] for item in plan_history["plan_versions"]] == ["SUPERSEDED", "ACTIVE"]
    assert [item["effective_status"] for item in readiness_history["projections"]] == ["SUPERSEDED", "ACTIVE"]
    assert [item["effective_status"] for item in recovery_history["checkpoints"]] == ["SUPERSEDED", "ACTIVE"]
    assert recovery_history["checkpoints"][0]["canonical_sha256"] == checkpoint_v1["canonical_sha256"]
    assert checkpoint_v2["plan_version"] == projection_v2["plan_version"] == 2
    assert checkpoint_v2["readiness_projection_id"] == projection_v2["projection_id"]


def test_stage3310_version_vector_tracks_active_successor_readiness_and_recovery_heads(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_closed_planning(service, "vector")
    replan = enter_replanning(service, mission_id, "vector")
    service.create_replan_successor_plan_version(
        mission_id, replan_request(service, mission_id, replan, "vector-v2")
    )
    projection_v2 = create_projection(service, mission_id, "vector-v2")
    create_checkpoint(service, mission_id, projection_v2, "vector-v2")
    versions = service.get_mission_version_vector(mission_id)["version_vector"]["versions"]

    assert versions["mission_plan_version"] == 1
    assert versions["planner_input_snapshot_version"] == 1
    assert versions["task_decomposition_version"] == 1
    assert versions["task_dependency_graph_version"] == 1
    assert versions["planner_generation_version"] == 1
    assert versions["plan_validation_version"] == 1
    assert versions["plan_versioning_version"] == 2
    assert versions["task_readiness_projection_version"] == 2
    assert versions["planning_recovery_version"] == 2


def test_stage3310_repository_manifest_closes_all_stage33_durable_stores_with_integrity_pass(tmp_path):
    service = make_service(tmp_path / "missions.db")
    mission_id, _, _, _ = provision_closed_planning(service, "repository")
    repo = service.get_mission_repository(mission_id)
    counts = repo["record_counts"]
    manifest = repo["persistence_manifest"]

    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    assert counts["mission_plans"] == 1
    assert counts["mission_planner_input_snapshots"] == 1
    assert counts["mission_task_decompositions"] == 1
    assert counts["mission_planned_tasks"] == 3
    assert counts["mission_task_dependency_graphs"] == 1
    assert counts["mission_task_dependency_edges"] == 2
    assert counts["mission_planner_invocations"] == 1
    assert counts["mission_generated_plans"] == 1
    assert counts["mission_plan_validations"] == 1
    assert counts["mission_plan_version_heads"] == 1
    assert counts["mission_plan_versions"] == 1
    assert counts["mission_task_readiness_projections"] == 1
    assert counts["mission_planning_recovery_checkpoints"] == 1
    assert manifest["plan_versioning_store"]["head"]["active_plan_version"] == 1
    assert len(manifest["task_readiness_projection_store"]["projections"]) == 1
    assert len(manifest["planning_recovery_checkpoint_store"]["checkpoints"]) == 1


def test_stage3310_closure_adds_no_migration_or_durable_store():
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert len(migrations) == REPOSITORY_MIGRATION_LEVEL
    assert migrations[16].name == "017_stage3_3_9_planning_event_lineage_replay_recovery.sql"
    assert list(Path("migrations").glob("018_stage3_4_1_*.sql"))
    assert list(Path("migrations").glob("019_stage3_4_2_*.sql"))
    assert "mission_planning_recovery_checkpoints" in REPOSITORY_STORES
    assert REPOSITORY_STORES[-1] == "mission_events"
    contract = planning_acceptance_gate_contract()
    assert contract["new_durable_store_added"] is False
    assert contract["new_database_migration_added"] is False


def test_stage3310_final_authority_matrix_preserves_plan_task_readiness_planner_replay_recovery_boundaries(tmp_path):
    health = make_service(tmp_path / "missions.db").health()
    assert health["planner_generation_planner_invocation_performed"] is True
    assert health["planner_generation_external_model_invocation_performed"] is False
    assert health["planner_generation_external_network_io_performed"] is False
    assert health["planner_generation_governance_query_performed"] is False
    assert health["plan_validation_feasibility_is_authorization"] is False
    assert health["plan_validation_governance_query_performed"] is False
    assert health["plan_versioning_plan_is_authorization"] is False
    assert health["plan_versioning_task_is_dispatch"] is False
    assert health["plan_versioning_readiness_is_permission"] is False
    assert health["plan_versioning_planner_is_governance"] is False
    assert health["task_readiness_projection_readiness_is_permission"] is False
    assert health["task_readiness_projection_ready_is_authorized"] is False
    assert health["task_readiness_projection_wall_clock_schedule_created"] is False
    assert health["task_readiness_projection_resource_assignment_performed"] is False
    assert health["planning_recovery_replay_is_execution"] is False
    assert health["planning_recovery_recovery_is_authorization"] is False
    assert health["planning_recovery_planner_rerun_performed"] is False
    assert health["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert health["target_action_dispatch_enabled"] is False
    assert health["target_actuation"] is False
