from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from mission_orchestrator.adapt_replan_acceptance_gate import (
    ADAPT_REPLAN_ACCEPTANCE_GATE_BASELINE,
    ADAPT_REPLAN_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE,
    ADAPT_REPLAN_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL,
    ADAPT_REPLAN_ACCEPTANCE_GATE_MODE,
    ADAPT_REPLAN_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE,
    ADAPT_REPLAN_ACCEPTANCE_GATE_SCHEMA_VERSION,
    REQUIRED_ADAPT_REPLAN_ACCEPTANCE_GATES,
    REQUIRED_STAGE3_7_CONTROLS,
    adapt_replan_acceptance_gate_contract,
)
from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.replan_lineage import REPLAN_RECOVERY_EVENT_TYPE
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_7_9_adapt_replan_lineage_replay_recovery import provision_stage379_source


CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE379 = "stage3.7.9-adapt-replan-lineage-replay-recovery"


@pytest.fixture(scope="module")
def closed_context(tmp_path_factory):
    ctx = provision_stage379_source(tmp_path_factory.mktemp("stage3710-closed"), "shared-closed3710")
    governance_before = ctx["governance"].evaluate_calls
    checkpoint = ctx["service"].create_replan_recovery_checkpoint(
        ctx["mission_id"], deepcopy(ctx["body"])
    )
    return {
        **ctx,
        "replan_checkpoint": checkpoint,
        "governance_before": governance_before,
        "governance_after": ctx["governance"].evaluate_calls,
    }


def test_01_health_activates_stage3710_closure_without_new_migration(closed_context):
    health = closed_context["service"].health()
    assert health["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert health["supported_controls"][60:70] == [*REQUIRED_STAGE3_7_CONTROLS, "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    assert health["stage3_7_adapt_replan_acceptance_gate_schema_version"] == ADAPT_REPLAN_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert health["stage3_7_adapt_replan_acceptance_gate_mode"] == ADAPT_REPLAN_ACCEPTANCE_GATE_MODE
    assert health["stage3_7_adapt_replan_acceptance_gate_baseline"] == ADAPT_REPLAN_ACCEPTANCE_GATE_BASELINE
    assert health["stage3_7_adapt_replan_acceptance_gate_runtime_change_mode"] == ADAPT_REPLAN_ACCEPTANCE_GATE_RUNTIME_CHANGE_MODE
    assert health["stage3_7_adapt_replan_acceptance_gate_database_change_mode"] == ADAPT_REPLAN_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE
    assert health["stage3_7_adapt_replan_acceptance_gate_expected_migration_level"] == 53
    assert health["stage3_7_adapt_replan_acceptance_gate_declared_only"] is True
    assert health["stage3_7_adapt_replan_acceptance_gate_runtime_self_certification"] is False
    assert health["stage3_7_adapt_replan_acceptance_gate_external_execution_required"] is True


def test_02_static_contract_requires_complete_stage37_and_external_acceptance():
    contract = adapt_replan_acceptance_gate_contract()
    assert contract["schema_version"] == ADAPT_REPLAN_ACCEPTANCE_GATE_SCHEMA_VERSION
    assert contract["mode"] == ADAPT_REPLAN_ACCEPTANCE_GATE_MODE
    assert contract["baseline"] == "STAGE_3_7_1_THROUGH_3_7_9"
    assert contract["required_prior_controls"] == list(REQUIRED_STAGE3_7_CONTROLS)
    assert contract["required_gates"] == list(REQUIRED_ADAPT_REPLAN_ACCEPTANCE_GATES)
    assert len(contract["required_gates"]) == len(set(contract["required_gates"])) == 17
    assert contract["expected_repository_migration_level"] == ADAPT_REPLAN_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL == 53
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert contract["governance_authorization_authority"] == "EXTERNAL_APTS_GSS"
    assert contract["stage37_commit_authority_source"] == "STAGE_3_7_7_AUTHORITATIVE_GOVERNANCE_REVALIDATION_AND_SUCCESSOR_PLAN_MATERIALIZATION"
    assert contract["stage37_handoff_authority_source"] == "STAGE_3_7_8_ATOMIC_SUPERSESSION_HANDOFF_READY"
    assert contract["stage37_replay_recovery_boundary"] == "STAGE_3_7_9_READ_ONLY_DURABLE_RECONSTRUCTION"


def test_03_success_trajectory_materializes_complete_stage371_through_379_stack(closed_context):
    service = closed_context["service"]
    mission_id = closed_context["mission_id"]
    assert service.get_adaptation_replan_history(mission_id)["adaptation_episode_count"] == 1
    assert service.get_adaptation_trigger_classification_history(mission_id)["classification_count"] == 1
    assert service.get_replan_eligibility_history(mission_id)["eligibility_gate_count"] == 1
    assert service.get_replan_snapshot_history(mission_id)["replan_snapshot_count"] == 1
    assert service.get_replan_candidate_history(mission_id)["replan_candidate_count"] == 1
    assert service.get_replan_validation_history(mission_id)["replan_validation_count"] == 1
    assert service.get_replan_commit_history(mission_id)["replan_commit_count"] == 1
    assert service.get_replan_handoff_history(mission_id)["replan_handoff_count"] == 1
    assert service.get_replan_recovery_history(mission_id)["checkpoint_count"] == 1
    assert closed_context["handoff"]["effective_episode_state"] == "HANDOFF_READY"
    assert closed_context["replan_checkpoint"]["recovery_state"]["effective_episode_state"] == "HANDOFF_READY"


def test_04_lineage_replay_and_recovery_close_same_handoff_ready_trajectory(closed_context):
    service = closed_context["service"]
    mission_id = closed_context["mission_id"]
    checkpoint = closed_context["replan_checkpoint"]
    lineage = service.get_replan_event_lineage(mission_id)
    replay = service.get_replan_event_replay(mission_id)
    recovered = service.get_replan_recovery(mission_id)
    assert lineage["read_only"] is True
    assert lineage["side_effects_performed"] is False
    assert lineage["replay"]["replan_event_count"] == 10
    assert lineage["replay"]["events"][-1]["event_type"] == REPLAN_RECOVERY_EVENT_TYPE
    assert lineage["replay"]["events"][-1]["artifact_id"] == checkpoint["checkpoint_id"]
    assert replay["replan_event_count"] == 10
    assert replay["events"][-1]["event_type"] == REPLAN_RECOVERY_EVENT_TYPE
    assert replay["read_only"] is True
    assert replay["side_effects_performed"] is False
    assert recovered["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovered["recovery_consistency"] == "PASS"
    assert recovered["recovered_from_durable_repository"] is True


def test_05_replay_and_recovery_reads_do_not_mutate_repository_or_contact_governance(closed_context):
    service = closed_context["service"]
    mission_id = closed_context["mission_id"]
    repo_before = service.get_mission_repository(mission_id)
    events_before = service.get_mission_events(mission_id)["event_count"]
    governance_before = closed_context["governance"].evaluate_calls
    service.get_replan_event_replay(mission_id)
    service.get_replan_recovery(mission_id)
    service.get_replan_event_replay(mission_id)
    service.get_replan_recovery(mission_id)
    repo_after = service.get_mission_repository(mission_id)
    assert repo_after["repository_sha256"] == repo_before["repository_sha256"]
    assert service.get_mission_events(mission_id)["event_count"] == events_before
    assert closed_context["governance"].evaluate_calls == governance_before
    assert closed_context["governance_after"] == closed_context["governance_before"]


def test_06_restart_reconstructs_handoff_ready_without_planner_governance_runtime_redispatch_or_actuation(closed_context):
    restarted = CanonicalMissionService(
        repository=MissionRepository(sqlite_path=closed_context["service"].repository.sqlite_path)
    )
    recovered = restarted.get_replan_recovery(closed_context["mission_id"])
    assert recovered["checkpoint_id"] == closed_context["replan_checkpoint"]["checkpoint_id"]
    assert recovered["recovered_from_durable_repository"] is True
    assert recovered["recovery_consistency"] == "PASS"
    assert recovered["planner_rerun_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert recovered["runtime_query_performed"] is False
    assert recovered["runtime_control_io_performed"] is False
    assert recovered["routing_performed"] is False
    assert recovered["delegation_performed"] is False
    assert recovered["dispatch_performed"] is False
    assert recovered["execution_attempt_created"] is False
    assert recovered["mission_state_transition_performed"] is False
    assert recovered["historical_plan_mutation_performed"] is False
    assert recovered["active_plan_head_cas_performed"] is False
    assert recovered["target_actuation"] is False


def test_07_stage37_authority_matrix_preserves_commit_handoff_and_non_actuating_recovery(closed_context):
    health = closed_context["service"].health()
    assert health["adaptation_replan_classification_performed"] is False
    assert health["adaptation_trigger_eligibility_evaluation_performed"] is False
    assert health["replan_eligibility_static_fail_closed_before_governance_query"] is True
    assert health["replan_snapshot_local_durable_context_only"] is True
    assert health["replan_candidate_deterministic_local_planner"] is True
    assert health["replan_candidate_successor_plan_created"] is False
    assert health["replan_validation_plan_validation_performed"] is True
    assert health["replan_validation_successor_plan_created"] is False
    assert health["replan_commit_authoritative_governance_revalidation_performed"] is True
    assert health["replan_commit_successor_plan_created"] is True
    assert health["replan_commit_plan_supersession_performed"] is True
    assert health["replan_commit_mission_state_transition_performed"] is False
    assert health["replan_handoff_atomic_commit_verified"] is True
    assert health["replan_handoff_plan_supersession_verified"] is True
    assert health["replan_handoff_dispatch_performed"] is False
    assert health["replan_replay_read_only"] is True
    assert health["replan_recovery_planner_rerun_performed"] is False
    assert health["replan_recovery_governance_query_performed"] is False
    assert health["replan_recovery_dispatch_performed"] is False
    assert health["replan_recovery_target_actuation"] is False


def test_08_successor_head_and_predecessor_supersession_remain_exact_after_handoff_and_recovery(closed_context):
    service = closed_context["service"]
    mission_id = closed_context["mission_id"]
    history = service.get_plan_version_history(mission_id)
    committed = closed_context["committed"]
    assert history["version_count"] == 2
    assert history["active_head"]["active_plan_version_record_id"] == committed["successor_plan_version_record_id"]
    assert history["active_head"]["active_plan_version"] == committed["successor_plan_version"]
    predecessor = next(x for x in history["plan_versions"] if x["plan_version_record_id"] == committed["predecessor_plan_version_record_id"])
    successor = next(x for x in history["plan_versions"] if x["plan_version_record_id"] == committed["successor_plan_version_record_id"])
    assert predecessor["effective_status"] == "SUPERSEDED"
    assert successor["effective_status"] == "ACTIVE"
    assert successor["predecessor_plan_version_record_id"] == predecessor["plan_version_record_id"]
    recovered = service.get_replan_recovery(mission_id)
    assert recovered["successor_plan_version_record_id"] == successor["plan_version_record_id"]
    assert recovered["recovery_state"]["active_head_verified_as_successor"] is True


def test_09_repository_manifest_closes_every_stage37_durable_store_with_integrity_pass(closed_context):
    repo = closed_context["service"].get_mission_repository(closed_context["mission_id"])
    counts = repo["record_counts"]
    manifest = repo["persistence_manifest"]
    assert repo["integrity_status"] == "PASS"
    assert repo["repository"]["migration_level"] == 53
    expected_counts = {
        "mission_adaptation_replan_contracts": 1,
        "mission_adaptation_trigger_classifications": 1,
        "mission_replan_eligibility_governance_gates": 1,
        "mission_replan_snapshots": 1,
        "mission_replan_candidates": 1,
        "mission_replan_decisions": 1,
        "mission_replan_commits": 1,
        "mission_replan_handoffs": 1,
        "mission_replan_recovery_checkpoints": 1,
    }
    for store, expected in expected_counts.items():
        assert counts[store] == expected
    for key in (
        "canonical_adaptation_replan_store",
        "adaptation_trigger_classification_store",
        "replan_eligibility_governance_store",
        "replan_snapshot_context_binding_store",
        "replan_candidate_generation_store",
        "replan_candidate_validation_store",
        "authoritative_replan_commit_store",
        "atomic_replan_supersession_handoff_store",
        "adapt_replan_lineage_replay_recovery_store",
    ):
        assert key in manifest


def test_10_stage3710_adds_no_migration_or_durable_store():
    migrations = sorted(Path("migrations").glob("*.sql"))
    assert REPOSITORY_MIGRATION_LEVEL == 53
    assert len(migrations) == 53
    assert migrations[-1].name == "053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql"
    assert not list(Path("migrations").glob("054_stage3_7_10_*.sql"))
    assert "mission_replan_recovery_checkpoints" in REPOSITORY_STORES
    contract = adapt_replan_acceptance_gate_contract()
    assert contract["new_durable_store_added"] is False
    assert contract["new_database_migration_added"] is False


def test_11_closure_gate_adds_no_new_adapt_replan_authority_io_plan_mutation_or_actuation(closed_context):
    health = closed_context["service"].health()
    false_fields = (
        "stage3_7_adapt_replan_acceptance_gate_new_adaptation_episode_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_trigger_classification_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_replan_eligibility_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_snapshot_binding_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_candidate_generation_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_validation_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_commit_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_plan_supersession_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_handoff_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_recovery_authority_added",
        "stage3_7_adapt_replan_acceptance_gate_new_governance_query_added",
        "stage3_7_adapt_replan_acceptance_gate_new_runtime_query_added",
        "stage3_7_adapt_replan_acceptance_gate_new_runtime_control_io_added",
        "stage3_7_adapt_replan_acceptance_gate_new_external_context_refresh_added",
        "stage3_7_adapt_replan_acceptance_gate_new_external_network_io_added",
        "stage3_7_adapt_replan_acceptance_gate_new_cancellation_io_added",
        "stage3_7_adapt_replan_acceptance_gate_new_routing_added",
        "stage3_7_adapt_replan_acceptance_gate_new_delegation_added",
        "stage3_7_adapt_replan_acceptance_gate_new_dispatch_added",
        "stage3_7_adapt_replan_acceptance_gate_new_execution_attempt_added",
        "stage3_7_adapt_replan_acceptance_gate_new_mission_state_transition_added",
        "stage3_7_adapt_replan_acceptance_gate_new_historical_plan_mutation_added",
        "stage3_7_adapt_replan_acceptance_gate_new_active_plan_head_cas_added",
        "stage3_7_adapt_replan_acceptance_gate_new_target_action_dispatch_added",
        "stage3_7_adapt_replan_acceptance_gate_new_target_actuation_added",
        "stage3_7_adapt_replan_acceptance_gate_new_llm_reinterpretation_added",
        "stage3_7_adapt_replan_acceptance_gate_new_durable_store_added",
        "stage3_7_adapt_replan_acceptance_gate_new_database_migration_added",
        "stage3_7_adapt_replan_acceptance_gate_stage379_replay_is_replan_processing",
        "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_replan_execution",
        "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_dispatch",
        "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_runtime_resumption",
        "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_lifecycle_transition",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_adaptation_detection",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_trigger_classification",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_replan_eligibility_authority",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_snapshot_binding",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_candidate_generation",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_candidate_validation",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_plan_commit",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_plan_supersession",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_handoff",
        "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_recovery",
    )
    for field in false_fields:
        assert health[field] is False, field
    assert health["stage3_7_adapt_replan_acceptance_gate_stage377_is_successor_plan_commit_authority"] is True
    assert health["stage3_7_adapt_replan_acceptance_gate_stage378_is_handoff_authority"] is True


def test_12_stage37_supported_control_tail_is_complete_ordered_and_closure_cannot_self_certify(closed_context):
    health = closed_context["service"].health()
    expected_tail = [*REQUIRED_STAGE3_7_CONTROLS, "stage3.7.10-adapt-replan-acceptance-regression-gate"]
    tail = health["supported_controls"][60:70]
    assert tail == expected_tail
    assert tail[-2] == STAGE379
    assert tail[-1] == "stage3.7.10-adapt-replan-acceptance-regression-gate"
    assert len(tail) == len(set(tail)) == 10
    contract = adapt_replan_acceptance_gate_contract()
    assert contract["declared_only"] is True
    assert contract["runtime_self_certification"] is False
    assert contract["external_acceptance_execution_required"] is True
    assert "acceptance_status" not in contract
    assert "passed" not in contract
