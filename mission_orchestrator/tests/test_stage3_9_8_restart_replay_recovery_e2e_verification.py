from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

import pytest

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.e2e_restart_replay_recovery_qualification import (
    RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES,
    RESTART_REPLAY_RECOVERY_EXPECTED_NONZERO_COUNTS,
    RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES,
    RESTART_REPLAY_RECOVERY_PREDECESSOR_CONTROL,
    RESTART_REPLAY_RECOVERY_SCHEMA_VERSION,
    canonical_restart_replay_recovery_contract,
    verify_restart_replay_recovery_contract,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_9_7_adaptation_replanning_e2e_scenario import provision as provision_stage397

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision(tmp_path: Path, run_id: str):
    service, governance, runtime, mission_id, upstream, rows, requests = provision_stage397(tmp_path, run_id)
    state = service.get_mission_state(mission_id)["mission_state"]
    version = service.get_mission_version_vector(mission_id)
    active = service.repository.get_active_plan_version(mission_id)
    replay = service.get_replan_event_replay(mission_id)
    body = {
        "idempotency_key": f"stage398-recovery-{run_id}",
        "expected_version_sha256": version["version_sha256"],
        "expected_state_version": int(state["state_version"]),
        "expected_adaptation_episode_id": rows["handoff"]["adaptation_episode_id"],
        "expected_replan_handoff_id": rows["handoff"]["replan_handoff_id"],
        "expected_replan_handoff_sha256": rows["handoff"]["canonical_sha256"],
        "expected_active_plan_version_record_id": active["plan_version_record_id"],
        "expected_active_plan_version": int(active["plan_version"]),
        "expected_active_plan_sha256": active["canonical_sha256"],
        "expected_replan_event_count": int(replay["replan_event_count"]),
        "expected_replan_event_tip_sha256": replay["replan_event_tip_sha256"],
        "created_by": "stage3.9.8-e2e-runner",
        "reason": "Freeze canonical Stage 3.9.7 handoff for restart/replay/recovery E2E verification",
        "metadata": {"stage": "3.9.8", "scenario": "canonical-e2e", "run_id": run_id},
    }
    checkpoint = service.create_replan_recovery_checkpoint(mission_id, deepcopy(body))
    before = {
        "state": service.get_mission_state(mission_id)["mission_state"],
        "active": service.repository.get_active_plan_version(mission_id),
        "events": service.get_mission_events(mission_id),
        "counts": service.repository.get_repository_record_counts(mission_id),
        "replay": service.get_replan_event_replay(mission_id),
        "repository": service.get_mission_repository(mission_id),
        "recovery": service.get_replan_recovery(mission_id),
    }
    restarted = CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=str(service.repository.sqlite_path))
    )
    return service, restarted, governance, runtime, mission_id, rows, body, checkpoint, before


def test_01_contract_binds_397_and_advances_to_399():
    contract = canonical_restart_replay_recovery_contract()
    assert verify_restart_replay_recovery_contract(contract)
    assert contract["predecessor_control"] == RESTART_REPLAY_RECOVERY_PREDECESSOR_CONTROL
    assert contract["qualified_restart_head"]["active_plan_version"] == 2
    assert contract["qualified_restart_head"]["recovery_checkpoint_count"] == 1
    assert contract["qualified_restart_head"]["recovery_consistency"] == "PASS"
    assert contract["next_stage"] == "3.9.9"
    forged = deepcopy(contract); forged["qualified_restart_head"]["active_plan_version"] = 3
    assert verify_restart_replay_recovery_contract(forged) is False



@pytest.fixture(scope="module")
def shared_context(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("stage398-shared")
    ctx = provision(tmp_path, "shared398")
    return {
        "service": ctx[0], "restarted": ctx[1], "governance": ctx[2], "runtime": ctx[3],
        "mission_id": ctx[4], "rows": ctx[5], "body": ctx[6], "checkpoint": ctx[7], "before": ctx[8],
    }


def test_02_health_activates_398_without_migration_or_new_recovery_authority(shared_context):
    h = shared_context["service"].health()
    assert h["control_version"] == CONTROL
    assert h["supported_controls"][-4:] == [RESTART_REPLAY_RECOVERY_PREDECESSOR_CONTROL, "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CONTROL]
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["stage3_9_8_restart_replay_recovery_schema_version"] == RESTART_REPLAY_RECOVERY_SCHEMA_VERSION
    assert h["stage3_9_8_runtime_verifier_read_only"] is True
    assert h["stage3_9_8_restart_source"] == "DURABLE_REPOSITORY_ONLY"
    assert h["stage3_9_8_recovery_checkpoint_count_expected"] == 1
    assert h["stage3_9_8_new_database_migration_added"] is False
    assert h["stage3_9_8_new_durable_store_added"] is False
    assert h["stage3_9_8_new_recovery_authority_added"] is False


def test_03_checkpoint_extends_exact_49_event_stage397_head_to_50(shared_context):
    events = shared_context["service"].get_mission_events(shared_context["mission_id"])
    assert events["integrity_status"] == "PASS"
    assert events["event_count"] == 50
    assert [x["event_type"] for x in events["events"]] == list(RESTART_REPLAY_RECOVERY_EXPECTED_EVENT_TYPES)
    assert events["events"][-1]["causation_id"] == shared_context["checkpoint"]["checkpoint_id"]


def test_04_exact_repository_footprint_includes_one_existing_stage379_checkpoint(shared_context):
    counts = shared_context["service"].repository.get_repository_record_counts(shared_context["mission_id"])
    assert {k: v for k, v in counts.items() if v} == RESTART_REPLAY_RECOVERY_EXPECTED_NONZERO_COUNTS
    assert counts["mission_replan_recovery_checkpoints"] == 1


def test_05_restart_recovers_state_plan_and_repository_from_same_durable_db(shared_context):
    restarted = shared_context["restarted"]; mission_id = shared_context["mission_id"]; before = shared_context["before"]
    after_state = restarted.get_mission_state(mission_id)["mission_state"]
    after_active = restarted.repository.get_active_plan_version(mission_id)
    after_repository = restarted.get_mission_repository(mission_id)
    assert after_state == before["state"]
    assert after_active == before["active"]
    assert after_repository["record_counts"] == before["repository"]["record_counts"]
    assert after_repository["integrity_status"] == "PASS"


def test_06_restart_preserves_exact_event_chain_and_tip_hash(shared_context):
    restarted = shared_context["restarted"]; mission_id = shared_context["mission_id"]; before = shared_context["before"]
    after = restarted.get_mission_events(mission_id)
    assert after["events"] == before["events"]["events"]
    assert after["event_count"] == before["events"]["event_count"] == 50
    assert after["events"][-1]["canonical_sha256"] == before["events"]["events"][-1]["canonical_sha256"]


def test_07_replan_replay_after_restart_is_exact_deterministic_and_read_only(shared_context):
    restarted = shared_context["restarted"]; mission_id = shared_context["mission_id"]; before = shared_context["before"]
    first = restarted.get_replan_event_replay(mission_id)
    second = restarted.get_replan_event_replay(mission_id)
    assert first == second == before["replay"]
    assert first["replan_event_count"] == 10
    assert [x["event_type"] for x in first["events"]] == list(RESTART_REPLAY_RECOVERY_EXPECTED_REPLAN_EVENT_TYPES)
    assert first["read_only"] is True and first["side_effects_performed"] is False


def test_08_recovery_projection_after_restart_is_consistent_and_side_effect_free(shared_context):
    restarted = shared_context["restarted"]; mission_id = shared_context["mission_id"]; checkpoint = shared_context["checkpoint"]
    recovery = restarted.get_replan_recovery(mission_id)
    assert recovery["checkpoint_id"] == checkpoint["checkpoint_id"]
    assert recovery["canonical_sha256"] == checkpoint["canonical_sha256"]
    assert recovery["recovery_consistency"] == "PASS"
    assert recovery["recovered_from_durable_repository"] is True
    assert recovery["runtime_query_performed"] is False
    assert recovery["governance_query_performed"] is False
    assert recovery["dispatch_performed"] is False
    assert recovery["target_actuation"] is False


def test_09_stage398_qualification_passes_on_restarted_service(shared_context):
    proof = shared_context["restarted"].get_e2e_restart_replay_recovery_qualification(shared_context["mission_id"])
    assert proof["qualification"]["status"] == "QUALIFIED", proof["qualification"]["failed_check_ids"]
    head = proof["qualification"]["segment_head"]
    assert head["state"] == "RUNNING" and head["state_version"] == 4
    assert head["active_plan_version"] == 2
    assert head["recovery_consistency"] == "PASS"
    assert head["replan_event_count"] == 10 and head["event_count"] == 50
    assert head["restart_source"] == "DURABLE_REPOSITORY_ONLY"


def test_10_qualification_is_read_only_and_does_not_change_durable_state(shared_context):
    restarted = shared_context["restarted"]; mission_id = shared_context["mission_id"]
    before_events = restarted.get_mission_events(mission_id)
    before_counts = restarted.repository.get_repository_record_counts(mission_id)
    first = restarted.get_e2e_restart_replay_recovery_qualification(mission_id)
    second = restarted.get_e2e_restart_replay_recovery_qualification(mission_id)
    assert first == second and first["qualification"]["qualified"] is True
    assert restarted.get_mission_events(mission_id) == before_events
    assert restarted.repository.get_repository_record_counts(mission_id) == before_counts


def test_11_exact_checkpoint_request_replay_after_restart_is_idempotent(shared_context):
    restarted = shared_context["restarted"]; mission_id = shared_context["mission_id"]
    again = restarted.create_replan_recovery_checkpoint(mission_id, deepcopy(shared_context["body"]))
    assert again["idempotent_replay"] is True
    assert again["checkpoint_id"] == shared_context["checkpoint"]["checkpoint_id"]
    assert restarted.get_mission_events(mission_id)["event_count"] == 50
    assert restarted.repository.get_repository_record_counts(mission_id) == shared_context["before"]["counts"]


def test_12_checkpoint_tamper_is_rejected_by_restart_repository_integrity(tmp_path):
    service, _, _, _, mission_id, _, _, checkpoint, _ = provision(tmp_path, "tamper398")
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute(
            "UPDATE mission_replan_recovery_checkpoints SET canonical_sha256=? WHERE checkpoint_id=?",
            ("0" * 64, checkpoint["checkpoint_id"]),
        )
        conn.commit()
    restarted = CanonicalMissionService(
        repository=MissionRepository(driver="sqlite", sqlite_path=str(service.repository.sqlite_path))
    )
    with pytest.raises(Exception):
        restarted.get_mission_repository(mission_id)


def test_13_restart_qualification_does_not_rerun_governance_runtime_routing_or_dispatch(shared_context):
    governance = shared_context["governance"]; runtime = shared_context["runtime"]
    before = (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls)
    proof = shared_context["restarted"].get_e2e_restart_replay_recovery_qualification(shared_context["mission_id"])
    assert proof["planner_rerun_performed"] is False
    assert proof["governance_query_performed"] is False
    assert proof["runtime_query_performed"] is False
    assert proof["routing_performed"] is False
    assert proof["dispatch_performed"] is False
    assert proof["new_execution_attempt_created"] is False
    assert proof["mission_state_transition_performed"] is False
    assert proof["target_actuation"] is False
    assert before == (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls)


def test_14_http_contract_and_qualification_routes(shared_context):
    restarted = shared_context["restarted"]; mission_id = shared_context["mission_id"]
    handler = type("Stage398Handler", (MissionOrchestratorHandler,), {"service": restarted})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/api/e2e/restart-replay-recovery-qualification-contract") as resp:
            contract = json.loads(resp.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-restart-replay-recovery-qualification") as resp:
            proof = json.loads(resp.read().decode("utf-8"))
        assert contract["definition"]["schema_version"] == RESTART_REPLAY_RECOVERY_SCHEMA_VERSION
        assert proof["qualification"]["status"] == "QUALIFIED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
