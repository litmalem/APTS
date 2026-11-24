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
from mission_orchestrator.e2e_completion_outcome_qualification import (
    COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES,
    COMPLETION_OUTCOME_EXPECTED_NONZERO_COUNTS,
    COMPLETION_OUTCOME_PREDECESSOR_CONTROL,
    COMPLETION_OUTCOME_SCHEMA_VERSION,
    canonical_completion_outcome_contract,
    verify_completion_outcome_contract,
)
from mission_orchestrator.errors import MissionConcurrencyConflict
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_8_timeout_cancellation_abort_failure_propagation import propagation_request
from tests.test_stage3_5_9_execution_event_lineage_replay_recovery import recovery_request
from tests.test_stage3_6_1_canonical_task_outcome_contract_identity import outcome_request
from tests.test_stage3_6_2_task_terminality_completion_eligibility import eligibility_request
from tests.test_stage3_6_3_evidence_binding_verification import binding_request
from tests.test_stage3_6_4_dependency_aware_task_completion import completion_request
from tests.test_stage3_6_5_mission_outcome_aggregation import aggregation_request
from tests.test_stage3_6_6_mission_success_criteria_evaluation import evaluation_request
from tests.test_stage3_6_7_completion_readiness_blockers import readiness_request
from tests.test_stage3_9_5_dispatch_execution_evidence_continuity import provision as provision_stage395

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision(tmp_path: Path, run_id: str, *, stop: str | None = None):
    service, governance, runtime, mission_id, upstream, execution, _ = provision_stage395(tmp_path, run_id)
    active = upstream["activation"]
    requests: dict[str, dict] = {}
    rows: dict[str, dict] = dict(execution)

    requests["propagation"] = propagation_request(
        service, mission_id, active, rows["attempt"], rows["result"], run_id
    )
    rows["propagation"] = service.propagate_execution_outcome(mission_id, requests["propagation"])
    if stop == "propagation":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["checkpoint"] = recovery_request(
        service, mission_id, active, rows["attempt"], rows["delivery"], rows["running"],
        rows["result"], rows["propagation"], run_id,
    )
    rows["checkpoint"] = service.create_execution_recovery_checkpoint(mission_id, requests["checkpoint"])
    if stop == "checkpoint":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["outcome"] = outcome_request(
        service, mission_id, active, rows["attempt"], rows["result"], rows["propagation"], rows["checkpoint"], run_id
    )
    rows["outcome"] = service.create_task_outcome(mission_id, requests["outcome"])
    requests["terminality"] = eligibility_request(service, mission_id, active, rows["outcome"], run_id)
    rows["terminality"] = service.evaluate_task_terminality_completion_eligibility(mission_id, requests["terminality"])
    requests["binding"] = binding_request(
        service, mission_id, active, rows["outcome"], rows["terminality"], rows["result"], run_id
    )
    rows["binding"] = service.verify_task_evidence_binding(mission_id, requests["binding"])
    requests["completion"] = completion_request(service, mission_id, active, rows["binding"], run_id)
    rows["completion"] = service.commit_dependency_aware_task_completion(mission_id, requests["completion"])
    if stop == "completion":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["aggregation"] = aggregation_request(service, mission_id, active, run_id)
    rows["aggregation"] = service.aggregate_mission_outcome(mission_id, requests["aggregation"])
    requests["evaluation"] = evaluation_request(service, mission_id, active, rows["aggregation"], run_id)
    rows["evaluation"] = service.evaluate_mission_success_criteria(mission_id, requests["evaluation"])
    requests["readiness"] = readiness_request(service, mission_id, active, rows["evaluation"], run_id)
    rows["readiness"] = service.evaluate_completion_readiness(mission_id, requests["readiness"])
    return service, governance, runtime, mission_id, upstream, rows, requests


def test_01_contract_binds_stage395_and_hands_off_to_397():
    contract = canonical_completion_outcome_contract()
    assert verify_completion_outcome_contract(contract)
    assert contract["predecessor_control"] == COMPLETION_OUTCOME_PREDECESSOR_CONTROL
    assert contract["qualified_segment_head"]["completion_readiness_result"] == "BLOCKED"
    assert contract["qualified_segment_head"]["verified_completion_performed"] is False
    assert contract["qualified_segment_head"]["adaptation_replan_handoff_required"] is True
    assert contract["next_stage"] == "3.9.7"
    forged = deepcopy(contract)
    forged["qualified_segment_head"]["verified_completion_performed"] = True
    assert verify_completion_outcome_contract(forged) is False


def test_02_health_activates_396_without_migration_or_new_authority(tmp_path):
    service, *_ = provision_stage395(tmp_path, "health396", stop="start")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert health["supported_controls"][-6:] == [COMPLETION_OUTCOME_PREDECESSOR_CONTROL, "stage3.9.6-task-completion-mission-outcome-closure", "stage3.9.7-adaptation-replanning-e2e-scenario", "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CONTROL]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["stage3_9_6_completion_outcome_schema_version"] == COMPLETION_OUTCOME_SCHEMA_VERSION
    assert health["stage3_9_6_runtime_verifier_read_only"] is True
    assert health["stage3_9_6_completion_readiness_expected_blocked"] is True
    assert health["stage3_9_6_verified_completion_performed"] is False
    assert health["stage3_9_6_new_database_migration_added"] is False
    assert health["stage3_9_6_new_durable_store_added"] is False
    assert health["stage3_9_6_new_completion_authority_added"] is False


def test_03_canonical_395_head_flows_to_qualified_completion_outcome_head(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "success396")
    proof = service.get_e2e_completion_outcome_qualification(mission_id)
    assert proof["qualification"]["status"] == "QUALIFIED", proof["qualification"]["failed_check_ids"]
    head = proof["qualification"]["segment_head"]
    assert head["state"] == "RUNNING" and head["state_version"] == 4
    assert head["task_key"] == "collect-cti"
    assert head["task_completion_id"] == rows["completion"]["task_completion_id"]
    assert head["aggregation_id"] == rows["aggregation"]["aggregation_id"]
    assert head["readiness_result"] == "BLOCKED" and head["blocker_count"] == 2
    assert proof["target_actuation"] is False


def test_04_exact_40_event_and_repository_footprint(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "footprint396")
    events = service.get_mission_events(mission_id)
    assert events["integrity_status"] == "PASS"
    assert [x["event_type"] for x in events["events"]] == list(COMPLETION_OUTCOME_EXPECTED_EVENT_TYPES)
    assert events["event_count"] == 40
    counts = service.repository.get_repository_record_counts(mission_id)
    assert {k: v for k, v in counts.items() if v} == COMPLETION_OUTCOME_EXPECTED_NONZERO_COUNTS


def test_05_verified_terminal_execution_is_bound_through_task_completion(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "chain396")
    assert rows["propagation"]["task_outcome_status"] == "VERIFIED_COMPLETED"
    assert rows["outcome"]["execution_recovery_checkpoint_id"] == rows["checkpoint"]["checkpoint_id"]
    assert rows["terminality"]["completion_eligible"] is True
    assert rows["binding"]["verification_status"] == "VERIFIED"
    assert rows["completion"]["completion_status"] == "COMPLETED_DEPENDENCY_CONSISTENT"
    assert rows["completion"]["task_completion_committed"] is True
    assert service.get_e2e_completion_outcome_qualification(mission_id)["qualification"]["qualified"] is True


def test_06_outcome_closure_is_fail_closed_and_does_not_prematurely_complete_mission(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "blocked396")
    agg, ev, ready = rows["aggregation"], rows["evaluation"], rows["readiness"]
    assert agg["task_count"] == 3 and agg["verified_complete_count"] == 1 and agg["pending_count"] == 1 and agg["blocked_count"] == 1
    assert agg["all_tasks_terminal"] is False and agg["all_tasks_verified_complete"] is False
    assert ev["overall_result"] == "SUCCESS_CRITERIA_NOT_SATISFIED"
    assert ready["readiness_result"] == "BLOCKED" and ready["completion_ready"] is False
    assert [x["code"] for x in ready["blockers"]] == ["SUCCESS_CRITERIA_NOT_SATISFIED", "TASKS_NOT_ALL_VERIFIED_COMPLETE"]
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"
    assert service.repository.list_verified_completion_declarations(mission_id) == []


def test_07_read_only_qualification_adds_no_calls_events_or_records(tmp_path):
    service, governance, runtime, mission_id, *_ = provision(tmp_path, "readonly396")
    events_before = service.get_mission_events(mission_id)["event_count"]
    counts_before = service.repository.get_repository_record_counts(mission_id)
    calls_before = (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls)
    first = service.get_e2e_completion_outcome_qualification(mission_id)
    second = service.get_e2e_completion_outcome_qualification(mission_id)
    assert first == second and first["qualification"]["qualified"] is True
    assert service.get_mission_events(mission_id)["event_count"] == events_before
    assert service.repository.get_repository_record_counts(mission_id) == counts_before
    assert calls_before == (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls)


def test_08_exact_mutation_replay_is_idempotent_and_event_stable(tmp_path):
    service, _, _, mission_id, _, rows, requests = provision(tmp_path, "replay396")
    before = service.repository.get_repository_record_counts(mission_id)
    assert service.propagate_execution_outcome(mission_id, deepcopy(requests["propagation"]))["idempotent_replay"] is True
    assert service.create_execution_recovery_checkpoint(mission_id, deepcopy(requests["checkpoint"]))["idempotent_replay"] is True
    assert service.create_task_outcome(mission_id, deepcopy(requests["outcome"]))["idempotent_replay"] is True
    assert service.evaluate_task_terminality_completion_eligibility(mission_id, deepcopy(requests["terminality"]))["idempotent_replay"] is True
    assert service.verify_task_evidence_binding(mission_id, deepcopy(requests["binding"]))["idempotent_replay"] is True
    assert service.commit_dependency_aware_task_completion(mission_id, deepcopy(requests["completion"]))["idempotent_replay"] is True
    assert service.aggregate_mission_outcome(mission_id, deepcopy(requests["aggregation"]))["idempotent_replay"] is True
    assert service.evaluate_mission_success_criteria(mission_id, deepcopy(requests["evaluation"]))["idempotent_replay"] is True
    assert service.evaluate_completion_readiness(mission_id, deepcopy(requests["readiness"]))["idempotent_replay"] is True
    assert service.repository.get_repository_record_counts(mission_id) == before
    assert service.get_mission_events(mission_id)["event_count"] == 40
    assert rows["readiness"]["readiness_id"] == service.get_completion_readiness_history(mission_id)["decisions"][0]["readiness_id"]


def test_09_partial_completion_chain_is_rejected(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "partial396", stop="completion")
    result = service.get_e2e_completion_outcome_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert "EXACT_EVENT_TRAJECTORY" in result["failed_check_ids"]
    assert "EXACT_SINGLE_ARTIFACT_CARDINALITY" in result["failed_check_ids"]


def test_10_stale_success_evaluation_input_fails_closed(tmp_path):
    service, _, _, mission_id, upstream, rows, _ = provision(tmp_path, "stale396", stop="completion")
    body = aggregation_request(service, mission_id, upstream["activation"], "stale396")
    aggregation = service.aggregate_mission_outcome(mission_id, body)
    stale = evaluation_request(service, mission_id, upstream["activation"], aggregation, "stale396")
    stale["expected_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict, match="version_sha256"):
        service.evaluate_mission_success_criteria(mission_id, stale)


def test_11_repository_tamper_breaks_qualification(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "tamper396")
    db = service.repository.sqlite_path
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_outcome_aggregations SET canonical_sha256=? WHERE mission_id=? AND aggregation_id=?",
            ("0" * 64, mission_id, rows["aggregation"]["aggregation_id"]),
        )
        conn.commit()
    restarted = CanonicalMissionService(MissionRepository(sqlite_path=db))
    result = restarted.get_e2e_completion_outcome_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert "MISSION_AND_REPOSITORY_INTEGRITY" in result["failed_check_ids"] or "CANONICAL_OUTCOME_ARTIFACT_INTEGRITY" in result["failed_check_ids"]


def test_12_restart_reconstructs_same_read_only_qualification(tmp_path):
    db = tmp_path / "restart396.db"
    service, _, _, mission_id, *_ = provision(tmp_path, "restart396")
    # provision() creates its own run-id DB below tmp_path; use that concrete path.
    db = Path(service.repository.sqlite_path)
    first = service.get_e2e_completion_outcome_qualification(mission_id)
    restarted = CanonicalMissionService(MissionRepository(sqlite_path=str(db)))
    second = restarted.get_e2e_completion_outcome_qualification(mission_id)
    assert first["qualification"] == second["qualification"]
    assert second["qualification"]["status"] == "QUALIFIED"


def test_13_http_contract_and_mission_qualification_routes(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "http396")
    before = service.repository.get_repository_record_counts(mission_id)
    handler = type("Stage396Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/api/e2e/completion-outcome-qualification-contract") as response:
            contract = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-completion-outcome-qualification") as response:
            proof = json.loads(response.read().decode("utf-8"))
        assert contract == service.get_e2e_completion_outcome_contract_definition()
        assert proof["qualification"]["status"] == "QUALIFIED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert service.repository.get_repository_record_counts(mission_id) == before


def test_14_no_stage368_or_369_closure_artifacts_are_fabricated(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "boundary396")
    counts = service.repository.get_repository_record_counts(mission_id)
    assert counts["mission_verified_completion_declarations"] == 0
    assert counts["mission_outcome_recovery_checkpoints"] == 0
    proof = service.get_e2e_completion_outcome_qualification(mission_id)
    assert proof["qualification"]["authority_boundary"]["verified_completion_performed"] is False
    assert proof["qualification"]["authority_boundary"]["mission_state_transition_performed"] is False


def test_15_definition_closes_396_at_nonterminal_adaptation_handoff(tmp_path):
    service, *_ = provision_stage395(tmp_path, "definition396", stop="start")
    out = service.get_e2e_completion_outcome_contract_definition()
    assert out["control_version"] == CONTROL
    assert out["definition"]["predecessor_control"] == COMPLETION_OUTCOME_PREDECESSOR_CONTROL
    assert out["definition"]["blocked_readiness_expected"] is True
    assert out["definition"]["verified_completion_expected"] is False
    assert out["definition"]["adaptation_replan_handoff_required"] is True
    assert out["definition"]["next_stage"] == "3.9.7"
    assert verify_completion_outcome_contract(out["contract"])
