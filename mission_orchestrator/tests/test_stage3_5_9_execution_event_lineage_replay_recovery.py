from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.errors import (
    MissionConcurrencyConflict,
    MissionExecutionRecoveryConflict,
    MissionExecutionRecoveryGuardRejected,
    MissionRepositoryIntegrityError,
    MissionValidationError,
)
from mission_orchestrator.execution_lineage import (
    EXECUTION_EVENT_LINEAGE_SCHEMA_VERSION,
    EXECUTION_EVENT_REPLAY_SCHEMA_VERSION,
    EXECUTION_RECOVERY_CHECKPOINT_ID_PREFIX,
    EXECUTION_RECOVERY_CHECKPOINT_SCHEMA_VERSION,
    EXECUTION_RECOVERY_EVENT_TYPE,
    canonical_execution_event_lineage_definition,
    verify_execution_recovery_checkpoint_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL, REPOSITORY_STORES
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_8_timeout_cancellation_abort_failure_propagation import (
    ACTION_ABORT,
    capture_terminal,
    propagation_request,
    provision_358,
    termination_request,
)

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
STAGE358 = "stage3.5.8-timeout-cancellation-abort-failure-propagation"
STAGE359 = "stage3.5.9-execution-event-lineage-replay-recovery"


def complete_success(tmp_path, key: str):
    service, governance, runtime, mission_id, active, dispatch, gate, reval, attempt, delivery, running = provision_358(tmp_path, key)
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, f"{key}-result", "SUCCEEDED")
    prop = service.propagate_execution_outcome(
        mission_id, propagation_request(service, mission_id, active, attempt, result, f"{key}-prop")
    )
    return service, governance, runtime, mission_id, active, attempt, delivery, running, result, prop


def recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, key, *, term_count=0, **overrides):
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    replay = service.get_execution_event_replay(mission_id)["replay"]
    body = {
        "idempotency_key": f"stage359-recover-{key}",
        "expected_version_sha256": vector["version_sha256"],
        "expected_state_version": state["state_version"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": active["plan_version"],
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_execution_attempt_id": attempt["execution_attempt_id"],
        "expected_execution_attempt_sha256": attempt["canonical_sha256"],
        "expected_execution_delivery_id": delivery["execution_delivery_id"],
        "expected_execution_delivery_sha256": delivery["canonical_sha256"],
        "expected_running_projection_id": running["running_projection_id"],
        "expected_running_projection_sha256": running["canonical_sha256"],
        "expected_result_capture_id": result["result_capture_id"],
        "expected_result_capture_sha256": result["canonical_sha256"],
        "expected_outcome_propagation_id": prop["outcome_propagation_id"],
        "expected_outcome_propagation_sha256": prop["canonical_sha256"],
        "expected_termination_control_count": term_count,
        "expected_execution_event_count": replay["execution_event_count"],
        "expected_execution_event_tip_sha256": replay["execution_event_tip_sha256"],
        "created_by": "stage3.5.9-pytest",
        "reason": "reconstruct terminal execution from durable evidence",
        "metadata": {"stage": "3.5.9", "key": key},
    }
    body.update(overrides)
    return body


def test_01_health_activates_stage359_and_migration35(tmp_path):
    service, *_ = provision_358(tmp_path, "health359")
    h = service.health()
    assert h["control_version"] == CONTROL
    assert h["supported_controls"][48:50] == [STAGE359, "stage3.5.10-execution-dispatch-acceptance-regression-gate"]
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert h["execution_event_lineage_schema_version"] == EXECUTION_EVENT_LINEAGE_SCHEMA_VERSION
    assert h["execution_event_replay_schema_version"] == EXECUTION_EVENT_REPLAY_SCHEMA_VERSION
    assert h["execution_recovery_checkpoint_schema_version"] == EXECUTION_RECOVERY_CHECKPOINT_SCHEMA_VERSION
    assert h["execution_replay_read_only"] is True
    assert h["execution_recovery_runtime_result_query_performed"] is False
    assert "mission_execution_recovery_checkpoints" in REPOSITORY_STORES


def test_02_definition_closes_execution_lineage_boundary(tmp_path):
    service, _, _, mission_id, *_ = provision_358(tmp_path, "definition359")
    out = service.get_execution_event_lineage_definition(mission_id)
    d = out["execution_event_lineage_definition"]
    assert d == canonical_execution_event_lineage_definition()
    assert d["requires_stage358_terminal_outcome_propagation"] is True
    assert d["replay_read_only"] is True
    assert d["runtime_result_query_on_recovery"] is False
    assert d["new_execution_attempt_on_recovery"] is False
    assert d["mission_state_transition_on_recovery"] is False
    assert d["next_stage"] == "3.5.10"


def test_03_complete_stage358_success_has_eight_execution_events_before_checkpoint(tmp_path):
    service, _, _, mission_id, *rest = complete_success(tmp_path, "lineage359")
    lineage = service.get_execution_event_lineage(mission_id)
    assert lineage["execution_event_count"] == 8
    assert lineage["execution_events"][-1]["event_type"] == "MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED"
    assert lineage["integrity_status"] == "PASS"
    assert lineage["full_mission_event_chain_verified"] is True


def test_04_replay_is_read_only_and_does_not_touch_runtime(tmp_path):
    service, _, runtime, mission_id, *_ = complete_success(tmp_path, "replay359")
    before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    out = service.get_execution_event_replay(mission_id)
    after = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    assert after == before
    assert out["read_only"] is True
    assert out["side_effects_performed"] is False
    assert out["replay_is_execution"] is False
    assert out["external_network_io_performed"] is False


def test_05_success_checkpoint_is_immutable_canonical_recovery_evidence(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "checkpoint359")
    out = service.create_execution_recovery_checkpoint(
        mission_id, recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "checkpoint359")
    )
    assert out["checkpoint_id"].startswith(EXECUTION_RECOVERY_CHECKPOINT_ID_PREFIX)
    assert out["recovery_state"]["execution_state"] == "SUCCEEDED"
    assert out["recovery_state"]["outcome_propagation_id"] == prop["outcome_propagation_id"]
    assert out["recovery_state"]["terminal_execution_trajectory_reconstructed"] is True
    assert out["mission_state_transition_performed"] is False
    assert out["runtime_result_query_performed"] is False
    assert verify_execution_recovery_checkpoint_contract(out["recovery_checkpoint"])


def test_06_restart_recovery_uses_only_durable_repository(tmp_path):
    service, _, runtime, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "restart359")
    out = service.create_execution_recovery_checkpoint(
        mission_id, recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "restart359")
    )
    db = service.repository.sqlite_path
    before = (runtime.health_calls, runtime.result_calls, runtime.control_calls)
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=db))
    recovered = restarted.recover_execution_state(mission_id)
    assert recovered["checkpoint_id"] == out["checkpoint_id"]
    assert recovered["reconstructed_from_durable_repository"] is True
    assert recovered["external_network_io_performed"] is False
    assert recovered["runtime_health_probe_performed"] is False
    assert recovered["runtime_result_query_performed"] is False
    assert recovered["runtime_control_io_performed"] is False
    assert (runtime.health_calls, runtime.result_calls, runtime.control_calls) == before


def test_07_exact_idempotent_replay_returns_same_checkpoint_without_duplicate_event(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "idem359")
    body = recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "idem359")
    first = service.create_execution_recovery_checkpoint(mission_id, body)
    events_before = service.get_execution_event_replay(mission_id)["replay"]["execution_event_count"]
    second = service.create_execution_recovery_checkpoint(mission_id, body)
    assert second["idempotent_replay"] is True
    assert second["checkpoint_id"] == first["checkpoint_id"]
    assert service.get_execution_recovery_history(mission_id)["checkpoint_count"] == 1
    assert service.get_execution_event_replay(mission_id)["replay"]["execution_event_count"] == events_before


def test_08_idempotency_key_reuse_with_different_request_conflicts(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "idem-conflict359")
    body = recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "idem-conflict359")
    service.create_execution_recovery_checkpoint(mission_id, body)
    changed = dict(body); changed["reason"] = "different request"
    with pytest.raises(MissionExecutionRecoveryConflict):
        service.create_execution_recovery_checkpoint(mission_id, changed)


def test_09_second_checkpoint_for_same_outcome_is_rejected(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "second359")
    body = recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "first359")
    service.create_execution_recovery_checkpoint(mission_id, body)
    # Bind a fresh request to the pre-checkpoint execution subchain snapshot from the stored contract.
    stored = service.repository.get_latest_execution_recovery_checkpoint(mission_id)
    second = dict(body)
    second["idempotency_key"] = "stage359-recover-second359"
    second["expected_execution_event_count"] = stored["source_event_count"]
    second["expected_execution_event_tip_sha256"] = stored["source_event_tip_sha256"]
    with pytest.raises((MissionConcurrencyConflict, MissionExecutionRecoveryConflict)):
        service.create_execution_recovery_checkpoint(mission_id, second)


def test_10_stale_state_version_fails_before_checkpoint_commit(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "stale359")
    body = recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "stale359")
    body["expected_state_version"] -= 1
    with pytest.raises(MissionConcurrencyConflict):
        service.create_execution_recovery_checkpoint(mission_id, body)
    assert service.get_execution_recovery_history(mission_id)["checkpoint_count"] == 0


def test_11_wrong_source_artifact_hash_fails_closed(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "hash359")
    body = recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "hash359")
    body["expected_result_capture_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.create_execution_recovery_checkpoint(mission_id, body)


def test_12_caller_cannot_inject_recovery_state_or_replay(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "inject359")
    body = recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "inject359")
    body["recovery_state"] = {"execution_state": "SUCCEEDED"}
    with pytest.raises(MissionValidationError, match="unsupported execution recovery checkpoint field"):
        service.create_execution_recovery_checkpoint(mission_id, body)


def test_13_checkpoint_requires_stage358_outcome_propagation(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "no-prop359")
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "no-prop359", "SUCCEEDED")
    replay = service.get_execution_event_replay(mission_id)["replay"]
    state = service.get_mission_state(mission_id)["mission_state"]
    vector = service.get_mission_version_vector(mission_id)
    body = {
        "idempotency_key":"stage359-no-prop", "expected_version_sha256":vector["version_sha256"], "expected_state_version":state["state_version"],
        "expected_active_plan_version_record_id":active["plan_version_record_id"], "expected_active_plan_version":active["plan_version"], "expected_active_plan_sha256":active["canonical_sha256"],
        "expected_execution_attempt_id":attempt["execution_attempt_id"], "expected_execution_attempt_sha256":attempt["canonical_sha256"],
        "expected_execution_delivery_id":delivery["execution_delivery_id"], "expected_execution_delivery_sha256":delivery["canonical_sha256"],
        "expected_running_projection_id":running["running_projection_id"], "expected_running_projection_sha256":running["canonical_sha256"],
        "expected_result_capture_id":result["result_capture_id"], "expected_result_capture_sha256":result["canonical_sha256"],
        "expected_outcome_propagation_id":"xprop-missing", "expected_outcome_propagation_sha256":"0"*64,
        "expected_termination_control_count":0, "expected_execution_event_count":replay["execution_event_count"], "expected_execution_event_tip_sha256":replay["execution_event_tip_sha256"],
        "created_by":"pytest",
    }
    with pytest.raises(MissionExecutionRecoveryGuardRejected):
        service.create_execution_recovery_checkpoint(mission_id, body)


def test_14_failure_terminal_state_is_recoverable_without_repropagation(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "failed359")
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "failed359", "FAILED")
    prop = service.propagate_execution_outcome(mission_id, propagation_request(service, mission_id, active, attempt, result, "failed359"))
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "FAILED"
    out = service.create_execution_recovery_checkpoint(
        mission_id, recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "failed359")
    )
    assert out["recovery_state"]["resulting_mission_state"] == "FAILED"
    assert out["failure_propagation_performed"] is False
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "FAILED"


def test_15_abort_control_is_optional_source_and_is_bound_when_present(tmp_path):
    service, _, runtime, mission_id, active, _, _, _, attempt, delivery, running = provision_358(tmp_path, "abort359")
    term = service.control_running_execution(mission_id, termination_request(service, mission_id, active, attempt, delivery, running, "abort359", ACTION_ABORT))
    result = capture_terminal(service, runtime, mission_id, active, attempt, delivery, running, "abort359", "CANCELLED")
    prop = service.propagate_execution_outcome(mission_id, propagation_request(service, mission_id, active, attempt, result, "abort359"))
    out = service.create_execution_recovery_checkpoint(
        mission_id, recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "abort359", term_count=1)
    )
    assert out["termination_control_id"] == term["termination_control_id"]
    assert out["recovery_state"]["termination_control_id"] == term["termination_control_id"]
    assert out["recovery_state"]["resulting_mission_state"] == "ABORTED"


def test_16_checkpoint_event_extends_execution_lineage_once(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "event359")
    before = service.get_execution_event_replay(mission_id)["replay"]["execution_event_count"]
    out = service.create_execution_recovery_checkpoint(mission_id, recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "event359"))
    after = service.get_execution_event_replay(mission_id)["replay"]
    assert after["execution_event_count"] == before + 1
    assert after["events"][-1]["event_type"] == EXECUTION_RECOVERY_EVENT_TYPE
    assert after["events"][-1]["artifact_id"] == out["checkpoint_id"]


def test_17_repository_manifest_includes_execution_recovery_store(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "repo359")
    service.create_execution_recovery_checkpoint(mission_id, recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "repo359"))
    repo = service.get_mission_repository(mission_id=mission_id)
    assert repo["repository"]["migration_level"] == 53
    assert repo["record_counts"]["mission_execution_recovery_checkpoints"] == 1
    assert len(repo["persistence_manifest"]["execution_event_lineage_replay_recovery_store"]["checkpoints"]) == 1


def test_18_tampered_checkpoint_contract_fails_restart_recovery(tmp_path):
    service, _, _, mission_id, active, attempt, delivery, running, result, prop = complete_success(tmp_path, "tamper359")
    service.create_execution_recovery_checkpoint(mission_id, recovery_request(service, mission_id, active, attempt, delivery, running, result, prop, "tamper359"))
    db = service.repository.sqlite_path
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT checkpoint_id, canonical_json FROM mission_execution_recovery_checkpoints WHERE mission_id=?", (mission_id,)).fetchone()
        contract = json.loads(row[1]); contract["recovery_state"]["execution_state"] = "FAILED"
        conn.execute("UPDATE mission_execution_recovery_checkpoints SET canonical_json=? WHERE checkpoint_id=?", (json.dumps(contract, sort_keys=True, separators=(",", ":")), row[0]))
        conn.commit()
    restarted = CanonicalMissionService(repository=MissionRepository(sqlite_path=db))
    with pytest.raises(MissionRepositoryIntegrityError):
        restarted.recover_execution_state(mission_id)


def test_19_migration_035_declares_recovery_store_and_fk_sources():
    path = Path("migrations/035_stage3_5_9_execution_event_lineage_replay_recovery.sql")
    sql = path.read_text(encoding="utf-8")
    assert "mission_execution_recovery_checkpoints" in sql
    assert "mission_execution_outcome_propagations" in sql
    assert "mission_execution_result_captures" in sql
    assert "mission_execution_termination_controls" in sql
    assert "mission_execution_attempts" in sql


def test_20_definition_and_health_preserve_non_actuating_recovery_semantics(tmp_path):
    service, _, _, mission_id, *_ = provision_358(tmp_path, "semantics359")
    h = service.health(); d = service.get_execution_event_lineage_definition(mission_id)["execution_event_lineage_definition"]
    assert h["execution_recovery_new_target_action_dispatch_performed"] is False
    assert h["execution_recovery_mission_state_transition_performed"] is False
    assert h["execution_recovery_target_actuation"] is False
    assert d["dispatch_redelivery_on_recovery"] is False
    assert d["new_target_action_dispatch_on_recovery"] is False
    assert d["target_actuation"] is False
