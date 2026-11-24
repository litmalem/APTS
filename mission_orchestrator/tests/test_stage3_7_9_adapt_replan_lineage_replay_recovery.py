from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionReplanRecoveryConflict,
    MissionReplanRecoveryGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.replan_lineage import (
    REPLAN_EVENT_LINEAGE_MODE,
    REPLAN_EVENT_LINEAGE_SCHEMA_VERSION,
    REPLAN_EVENT_REPLAY_SCHEMA_VERSION,
    REPLAN_EVENT_TYPES,
    REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX,
    REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
    REPLAN_RECOVERY_EVENT_TYPE,
    REPLAN_RECOVERY_MODE,
    REPLAN_REPLAY_MODE,
    canonical_replan_event_lineage_definition,
    verify_replan_recovery_checkpoint_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_7_8_atomic_replan_commit_supersession_handoff import (
    handoff,
    make_governed_service,
    stage378_source,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PRIOR_CONTROL = "stage3.7.8-atomic-replan-commit-supersession-handoff"
PRECHECKPOINT_EVENT_TYPES = list(REPLAN_EVENT_TYPES[:-1])


def provision_stage379_source(tmp_path: Path, key: str) -> dict:
    service, governance = make_governed_service(tmp_path / f"{key}.db")
    mission_id, snapshot, candidate, validation, committed = stage378_source(service, key)
    handed_off, _ = handoff(service, mission_id, committed, key)
    state = service.get_mission_state(mission_id)["mission_state"]
    version = service.get_mission_version_vector(mission_id)
    active = service.repository.get_active_plan_version(mission_id)
    replay = service.get_replan_event_replay(mission_id)
    body = {
        "idempotency_key": f"stage379-recovery-{key}",
        "expected_version_sha256": version["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_adaptation_episode_id": handed_off["adaptation_episode_id"],
        "expected_replan_handoff_id": handed_off["replan_handoff_id"],
        "expected_replan_handoff_sha256": handed_off["canonical_sha256"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_replan_event_count": int(replay["replan_event_count"]),
        "expected_replan_event_tip_sha256": replay["replan_event_tip_sha256"],
        "created_by": "stage3.7.9-pytest",
        "reason": "Checkpoint canonical adapt/replan lineage for deterministic restart recovery",
        "metadata": {"stage": "3.7.9", "key": key},
    }
    return {
        "service": service,
        "governance": governance,
        "mission_id": mission_id,
        "snapshot": snapshot,
        "candidate": candidate,
        "validation": validation,
        "committed": committed,
        "handoff": handed_off,
        "state": state,
        "version": version,
        "active": active,
        "replay": replay,
        "body": body,
    }


@pytest.fixture(scope="module")
def source_context(tmp_path_factory):
    return provision_stage379_source(tmp_path_factory.mktemp("stage379-source"), "shared-stage379")


@pytest.fixture(scope="module")
def checkpoint_context(source_context):
    governance_before = source_context["governance"].evaluate_calls
    created = source_context["service"].create_replan_recovery_checkpoint(
        source_context["mission_id"], deepcopy(source_context["body"])
    )
    return {
        **source_context,
        "created": created,
        "governance_before": governance_before,
        "governance_after": source_context["governance"].evaluate_calls,
    }


def test_01_health_activates_stage379_migration53_and_durable_store(source_context):
    h = source_context["service"].health()
    assert h["control_version"] == CONTROL
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["supported_controls"][67:70] == [
        PRIOR_CONTROL,
        "stage3.7.9-adapt-replan-lineage-replay-recovery",
        "stage3.7.10-adapt-replan-acceptance-regression-gate",
    ]
    assert h["supported_controls"][-1] == CONTROL
    assert h["replan_event_lineage_schema_version"] == REPLAN_EVENT_LINEAGE_SCHEMA_VERSION
    assert h["replan_event_replay_schema_version"] == REPLAN_EVENT_REPLAY_SCHEMA_VERSION
    assert h["replan_recovery_checkpoint_schema_version"] == REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert h["replan_recovery_checkpoint_identity_prefix"] == REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX
    assert h["replan_recovery_database_migration_level"] == 53
    assert h["replan_recovery_persistence_store"] == "mission_replan_recovery_checkpoints"
    assert h["replan_lineage_status"] == "ACTIVE"
    assert "mission_replan_recovery_checkpoints" in REPOSITORY_STORES


def test_02_definition_declares_read_only_replay_recovery_boundary_and_next_stage(source_context):
    d = source_context["service"].get_replan_event_lineage_definition(source_context["mission_id"])[
        "adapt_replan_lineage_replay_recovery_definition"
    ]
    assert d == canonical_replan_event_lineage_definition()
    assert d["lineage_mode"] == REPLAN_EVENT_LINEAGE_MODE
    assert d["replay_mode"] == REPLAN_REPLAY_MODE
    assert d["recovery_mode"] == REPLAN_RECOVERY_MODE
    assert d["source_stages"] == ["3.7.1", "3.7.2", "3.7.3", "3.7.4", "3.7.5", "3.7.6", "3.7.7", "3.7.8"]
    assert d["replay_read_only"] is True
    assert d["planner_rerun_performed"] is False
    assert d["governance_query_performed"] is False
    assert d["dispatch_performed"] is False
    assert d["target_actuation"] is False
    assert d["next_stage"] == "3.7.10"


def test_03_precheckpoint_replay_is_deterministic_complete_and_read_only(source_context):
    first = source_context["service"].get_replan_event_replay(source_context["mission_id"])
    second = source_context["service"].get_replan_event_replay(source_context["mission_id"])
    assert first["events"] == second["events"]
    assert first["replan_event_count"] == 9
    assert [x["event_type"] for x in first["events"]] == PRECHECKPOINT_EVENT_TYPES
    assert first["read_only"] is True
    assert first["side_effects_performed"] is False


def test_04_lineage_exposes_exact_stage371_through_stage378_artifact_classes(source_context):
    lineage = source_context["service"].get_replan_event_lineage(source_context["mission_id"])
    assert len(lineage["adaptation_replans"]) == 1
    assert len(lineage["trigger_classifications"]) == 1
    assert len(lineage["eligibility_governance_gates"]) == 1
    assert len(lineage["replan_snapshots"]) == 1
    assert len(lineage["replan_candidates"]) == 1
    assert len(lineage["replan_validations"]) == 1
    assert len(lineage["replan_commits"]) == 1
    assert len(lineage["replan_handoffs"]) == 1
    assert lineage["recovery_checkpoints"] == []


def test_05_checkpoint_is_self_verifying_and_reconstructs_handoff_ready_state(checkpoint_context):
    created = checkpoint_context["created"]
    contract = created["replan_recovery_checkpoint"]
    assert created["checkpoint_id"].startswith(REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX)
    assert contract["schema_version"] == REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert verify_replan_recovery_checkpoint_contract(contract)
    assert created["canonical_sha256"] == contract["integrity"]["canonical_sha256"]
    assert created["recovery_state"]["effective_episode_state"] == "HANDOFF_READY"
    assert created["recovery_state"]["adapt_replan_trajectory_reconstructed"] is True
    assert created["recovery_state"]["active_head_verified_as_successor"] is True


def test_06_checkpoint_binds_exact_handoff_successor_and_precheckpoint_event_tip(checkpoint_context):
    created = checkpoint_context["created"]
    src = created["replan_recovery_checkpoint"]["source_bindings"]
    assert src["replan_handoff"]["id"] == checkpoint_context["handoff"]["replan_handoff_id"]
    assert src["replan_handoff"]["canonical_sha256"] == checkpoint_context["handoff"]["canonical_sha256"]
    assert src["successor_plan"]["id"] == checkpoint_context["active"]["plan_version_record_id"]
    assert src["replan_event_count"] == 9
    assert src["replan_event_tip_sha256"] == checkpoint_context["replay"]["replan_event_tip_sha256"]


def test_07_checkpoint_event_is_single_causal_terminal_event_and_replay_becomes_ten(checkpoint_context):
    service = checkpoint_context["service"]
    events = service.repository.list_mission_events(checkpoint_context["mission_id"])
    recovery_events = [e for e in events if e["event_type"] == REPLAN_RECOVERY_EVENT_TYPE]
    assert len(recovery_events) == 1
    assert recovery_events[0]["causation_id"] == checkpoint_context["created"]["checkpoint_id"]
    assert recovery_events[0]["payload"]["canonical_sha256"] == checkpoint_context["created"]["canonical_sha256"]
    replay = service.get_replan_event_replay(checkpoint_context["mission_id"])
    assert replay["replan_event_count"] == 10
    assert replay["events"][-1]["event_type"] == REPLAN_RECOVERY_EVENT_TYPE


def test_08_exact_idempotent_replay_reuses_checkpoint_without_duplicate_event(checkpoint_context):
    again = checkpoint_context["service"].create_replan_recovery_checkpoint(
        checkpoint_context["mission_id"], deepcopy(checkpoint_context["body"])
    )
    assert again["idempotent_replay"] is True
    assert again["checkpoint_id"] == checkpoint_context["created"]["checkpoint_id"]
    assert checkpoint_context["service"].get_replan_recovery_history(checkpoint_context["mission_id"])["checkpoint_count"] == 1
    events = checkpoint_context["service"].repository.list_mission_events(checkpoint_context["mission_id"])
    assert len([e for e in events if e["event_type"] == REPLAN_RECOVERY_EVENT_TYPE]) == 1


def test_09_idempotency_key_reuse_with_changed_request_conflicts(checkpoint_context):
    body = deepcopy(checkpoint_context["body"])
    body["reason"] = "different canonical request material"
    with pytest.raises(MissionReplanRecoveryConflict, match="different request material"):
        checkpoint_context["service"].create_replan_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_10_second_checkpoint_for_same_handoff_is_rejected(checkpoint_context):
    body = deepcopy(checkpoint_context["body"])
    body["idempotency_key"] = "stage379-second-checkpoint"
    with pytest.raises(MissionReplanRecoveryConflict, match="already has"):
        checkpoint_context["service"].create_replan_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_11_stale_expected_state_version_fails_closed(checkpoint_context):
    body = deepcopy(checkpoint_context["body"])
    body["idempotency_key"] = "stage379-stale-state"
    body["expected_state_version"] += 1
    with pytest.raises(MissionConcurrencyConflict, match="state_version"):
        checkpoint_context["service"].create_replan_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_12_stale_expected_version_hash_fails_closed(checkpoint_context):
    body = deepcopy(checkpoint_context["body"])
    body["idempotency_key"] = "stage379-stale-vector"
    body["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        checkpoint_context["service"].create_replan_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_13_wrong_handoff_hash_fails_closed(checkpoint_context):
    body = deepcopy(checkpoint_context["body"])
    body["idempotency_key"] = "stage379-wrong-handoff-hash"
    body["expected_replan_handoff_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="ReplanHandoff hash"):
        checkpoint_context["service"].create_replan_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_14_wrong_active_successor_head_fails_closed(checkpoint_context):
    body = deepcopy(checkpoint_context["body"])
    body["idempotency_key"] = "stage379-wrong-active-head"
    body["expected_active_plan_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="active Plan head"):
        checkpoint_context["service"].create_replan_recovery_checkpoint(checkpoint_context["mission_id"], body)


def test_15_changed_replan_event_count_is_rejected_before_checkpoint_creation(tmp_path):
    ctx = provision_stage379_source(tmp_path, "event-count")
    body = deepcopy(ctx["body"])
    body["expected_replan_event_count"] += 1
    with pytest.raises(MissionConcurrencyConflict, match="event count"):
        ctx["service"].create_replan_recovery_checkpoint(ctx["mission_id"], body)
    assert ctx["service"].repository.list_replan_recovery_checkpoints(ctx["mission_id"]) == []


def test_16_changed_replan_event_tip_is_rejected_before_checkpoint_creation(tmp_path):
    ctx = provision_stage379_source(tmp_path, "event-tip")
    body = deepcopy(ctx["body"])
    body["expected_replan_event_tip_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="event tip"):
        ctx["service"].create_replan_recovery_checkpoint(ctx["mission_id"], body)
    assert ctx["service"].repository.list_replan_recovery_checkpoints(ctx["mission_id"]) == []


def test_17_caller_supplied_replacement_or_side_effect_fields_are_forbidden(source_context):
    forbidden = [
        ("replacement_plan", {}),
        ("lifecycle_command", "REPLAN"),
        ("governance_decision", "ALLOW"),
        ("runtime_action", "resume"),
        ("cancellation_command", "cancel"),
        ("routing_command", "route"),
        ("dispatch_command", "dispatch"),
        ("target_action", "actuate"),
    ]
    for i, (field, value) in enumerate(forbidden):
        body = deepcopy(source_context["body"])
        body["idempotency_key"] = f"stage379-forbidden-{i}"
        body[field] = value
        with pytest.raises(MissionValidationError, match="unsupported replan recovery checkpoint field"):
            source_context["service"].create_replan_recovery_checkpoint(source_context["mission_id"], body)


def test_18_recovery_is_readable_after_restart_from_durable_repository_only(checkpoint_context):
    restarted = CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=str(checkpoint_context["service"].repository.sqlite_path))
    )
    recovered = restarted.get_replan_recovery(checkpoint_context["mission_id"])
    assert recovered["checkpoint_id"] == checkpoint_context["created"]["checkpoint_id"]
    assert recovered["canonical_sha256"] == checkpoint_context["created"]["canonical_sha256"]
    assert recovered["recovery_consistency"] == "PASS"
    assert recovered["recovered_from_durable_repository"] is True
    assert recovered["runtime_query_performed"] is False
    assert recovered["governance_query_performed"] is False
    assert recovered["dispatch_performed"] is False


def test_19_repository_projection_and_manifest_include_stage379_checkpoint(checkpoint_context):
    repository = checkpoint_context["service"].get_mission_repository(checkpoint_context["mission_id"])
    assert repository["integrity_status"] == "PASS"
    assert repository["record_counts"]["mission_replan_recovery_checkpoints"] == 1
    manifest = repository["persistence_manifest"]["adapt_replan_lineage_replay_recovery_store"]
    assert manifest["checkpoints"][0]["checkpoint_id"] == checkpoint_context["created"]["checkpoint_id"]


def test_20_persisted_checkpoint_tampering_breaks_repository_integrity(tmp_path):
    ctx = provision_stage379_source(tmp_path, "tamper")
    created = ctx["service"].create_replan_recovery_checkpoint(ctx["mission_id"], deepcopy(ctx["body"]))
    with sqlite3.connect(ctx["service"].repository.sqlite_path) as conn:
        conn.execute(
            "UPDATE mission_replan_recovery_checkpoints SET canonical_sha256=? WHERE checkpoint_id=?",
            ("0" * 64, created["checkpoint_id"]),
        )
        conn.commit()
    with pytest.raises(MissionRepositoryIntegrityError):
        ctx["service"].get_mission_repository(ctx["mission_id"])


def test_21_checkpoint_performs_no_governance_rerun_plan_mutation_lifecycle_or_execution_side_effect(checkpoint_context):
    created = checkpoint_context["created"]
    assert checkpoint_context["governance_after"] == checkpoint_context["governance_before"]
    for key in (
        "planner_rerun_performed",
        "governance_query_performed",
        "runtime_query_performed",
        "runtime_control_io_performed",
        "cancellation_io_performed",
        "routing_performed",
        "delegation_performed",
        "dispatch_performed",
        "execution_attempt_created",
        "mission_state_transition_performed",
        "historical_plan_mutation_performed",
        "active_plan_head_cas_performed",
        "target_actuation",
    ):
        assert created[key] is False


def test_22_api_routes_and_source_boundaries_are_registered():
    text = Path("mission_orchestrator/api_service.py").read_text(encoding="utf-8")
    for route in (
        "replan-lineage",
        "replan-replay",
        "replan-recovery",
        "replan-recovery-checkpoints",
        "replan-lineage-definition",
    ):
        assert route in text
    assert "create_replan_recovery_checkpoint" in text
    source = Path("mission_orchestrator/replan_lineage.py").read_text(encoding="utf-8")
    assert "MISSION_REPLAN_RECOVERY_CHECKPOINTED" in source
    assert "3.7.10" in source
