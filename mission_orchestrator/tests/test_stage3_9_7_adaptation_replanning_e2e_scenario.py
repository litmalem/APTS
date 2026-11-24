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
from mission_orchestrator.e2e_adaptation_replanning_qualification import (
    ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES,
    ADAPTATION_REPLANNING_EXPECTED_NONZERO_COUNTS,
    ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES,
    ADAPTATION_REPLANNING_PREDECESSOR_CONTROL,
    ADAPTATION_REPLANNING_SCHEMA_VERSION,
    canonical_adaptation_replanning_contract,
    verify_adaptation_replanning_contract,
)
from mission_orchestrator.errors import MissionConcurrencyConflict
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_7_1_canonical_adaptation_replan_contract_identity import adaptation_request
from tests.test_stage3_7_2_adaptation_trigger_detection_classification import classification_request
from tests.test_stage3_7_3_replan_eligibility_governance_gate import eligibility_request
from tests.test_stage3_7_4_canonical_replan_snapshot_context_binding import snapshot_request
from tests.test_stage3_7_5_deterministic_replan_candidate_generation import candidate_request
from tests.test_stage3_7_6_replan_candidate_validation_delta_feasibility_gate import validation_request
from tests.test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization import commit_request
from tests.test_stage3_7_8_atomic_replan_commit_supersession_handoff import handoff_request
from tests.test_stage3_9_6_task_completion_mission_outcome_closure import provision as provision_stage396

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision(tmp_path: Path, run_id: str, *, stop: str | None = None):
    service, governance, runtime, mission_id, upstream, completion, _ = provision_stage396(tmp_path, run_id)
    active = upstream["activation"]
    scope = upstream["scope"]
    binding = upstream["binding"]
    rows: dict[str, dict] = dict(completion)
    requests: dict[str, dict] = {}

    predecessor_event = service.get_mission_events(mission_id)["events"][-1]
    requests["adaptation"] = adaptation_request(
        service, mission_id, active, run_id,
        trigger_source="MISSION_EVENT", trigger_code="EVIDENCE_CHANGE",
        evidence_refs=[
            f"mission://{mission_id}/completion-readiness/{completion['readiness']['readiness_id']}",
            f"mission://{mission_id}/task-completions/{completion['completion']['task_completion_id']}",
        ],
        source_event_id=predecessor_event["event_id"],
        expected_source_event_sha256=predecessor_event["canonical_sha256"],
        detected_by="stage3.9.7-e2e-runner",
        reason="Stage 3.9.6 blocked outcome requires evidence-aware replanning",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["adaptation"] = service.create_adaptation_replan(mission_id, requests["adaptation"])
    if stop == "adaptation":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["classification"] = classification_request(
        service, mission_id, active, rows["adaptation"], run_id,
        reason_code="PLAN_STALE", severity="MEDIUM", source_stage="STAGE3_6_OUTCOME_COMPLETION",
        classified_by="stage3.9.7-e2e-runner",
        reason="Classify blocked completion evidence as deterministic Level-3 partial-plan adaptation",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["classification"] = service.classify_adaptation_trigger(
        mission_id, rows["adaptation"]["adaptation_episode_id"], requests["classification"]
    )
    if stop == "classification":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["eligibility"] = eligibility_request(
        service, mission_id, active, scope, binding, rows["adaptation"], rows["classification"], run_id,
        requested_by="stage3.9.7-e2e-runner", reason="Gate canonical E2E replanning eligibility",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["eligibility"] = service.evaluate_replan_eligibility(
        mission_id, rows["adaptation"]["adaptation_episode_id"], requests["eligibility"]
    )
    requests["snapshot"] = snapshot_request(
        service, mission_id, active, scope, binding, rows["adaptation"], rows["classification"], rows["eligibility"], run_id,
        bound_by="stage3.9.7-e2e-runner", reason="Freeze canonical E2E replan context",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["snapshot"] = service.bind_replan_snapshot(
        mission_id, rows["adaptation"]["adaptation_episode_id"], requests["snapshot"]
    )
    requests["candidate"] = candidate_request(
        rows["snapshot"], run_id, generated_by="stage3.9.7-e2e-runner",
        reason="Deterministically retain unfinished canonical remainder DAG",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["candidate"] = service.generate_replan_candidate(
        mission_id, rows["snapshot"]["replan_snapshot_id"], requests["candidate"]
    )
    requests["validation"] = validation_request(
        rows["candidate"], run_id, validated_by="stage3.9.7-e2e-runner",
        reason="Validate canonical E2E replan delta and feasibility",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["validation"] = service.validate_replan_candidate(
        mission_id, rows["candidate"]["replan_candidate_id"], requests["validation"]
    )
    if stop == "validation":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["commit"] = commit_request(
        rows["snapshot"], rows["candidate"], rows["validation"], run_id,
        requested_by="stage3.9.7-e2e-runner", reason="Authoritatively commit canonical E2E successor Plan v2",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["commit"] = service.commit_authorized_replan(
        mission_id, rows["validation"]["replan_validation_id"], requests["commit"]
    )
    requests["handoff"] = handoff_request(
        rows["commit"], run_id, handed_off_by="stage3.9.7-e2e-runner",
        reason="Publish canonical successor handoff to Stage 3.4 routing",
        metadata={"stage": "3.9.7", "scenario": "canonical-e2e", "run_id": run_id},
    )
    rows["handoff"] = service.declare_replan_handoff(
        mission_id, rows["commit"]["replan_commit_id"], requests["handoff"]
    )
    return service, governance, runtime, mission_id, upstream, rows, requests


def test_01_contract_binds_stage396_and_hands_off_to_398():
    contract = canonical_adaptation_replanning_contract()
    assert verify_adaptation_replanning_contract(contract)
    assert contract["predecessor_control"] == ADAPTATION_REPLANNING_PREDECESSOR_CONTROL
    assert contract["qualified_segment_head"]["successor_plan_version"] == 2
    assert contract["qualified_segment_head"]["handoff_status"] == "HANDOFF_READY"
    assert contract["qualified_segment_head"]["recovery_checkpoint_performed"] is False
    assert contract["next_stage"] == "3.9.8"
    forged = deepcopy(contract); forged["qualified_segment_head"]["successor_plan_version"] = 3
    assert verify_adaptation_replanning_contract(forged) is False


def test_02_health_activates_397_without_migration_or_new_replan_authority(tmp_path):
    service, *_ = provision_stage396(tmp_path, "health397")
    h = service.health()
    assert h["control_version"] == CONTROL
    assert h["supported_controls"][-5:] == [ADAPTATION_REPLANNING_PREDECESSOR_CONTROL, "stage3.9.7-adaptation-replanning-e2e-scenario", "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CONTROL]
    assert h["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert h["stage3_9_7_adaptation_replanning_schema_version"] == ADAPTATION_REPLANNING_SCHEMA_VERSION
    assert h["stage3_9_7_runtime_verifier_read_only"] is True
    assert h["stage3_9_7_authoritative_governance_required"] is True
    assert h["stage3_9_7_successor_plan_version_expected"] == 2
    assert h["stage3_9_7_recovery_checkpoint_performed"] is False
    assert h["stage3_9_7_new_database_migration_added"] is False
    assert h["stage3_9_7_new_durable_store_added"] is False
    assert h["stage3_9_7_new_replan_authority_added"] is False


def test_03_canonical_stage396_head_replans_to_active_successor_v2(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "success397")
    proof = service.get_e2e_adaptation_replanning_qualification(mission_id)
    assert proof["qualification"]["status"] == "QUALIFIED", proof["qualification"]["failed_check_ids"]
    head = proof["qualification"]["segment_head"]
    assert head["state"] == "RUNNING" and head["state_version"] == 4
    assert head["predecessor_plan_version"] == 1 and head["successor_plan_version"] == 2
    assert head["active_plan_version"] == 2
    assert head["candidate_task_keys"] == ["analyze-cti", "report-findings"]
    assert head["replan_handoff_id"] == rows["handoff"]["replan_handoff_id"]
    assert proof["target_actuation"] is False


def test_04_exact_49_event_and_repository_footprint(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "footprint397")
    events = service.get_mission_events(mission_id)
    assert events["integrity_status"] == "PASS"
    assert [x["event_type"] for x in events["events"]] == list(ADAPTATION_REPLANNING_EXPECTED_EVENT_TYPES)
    assert events["event_count"] == 49
    counts = service.repository.get_repository_record_counts(mission_id)
    assert {k: v for k, v in counts.items() if v} == ADAPTATION_REPLANNING_EXPECTED_NONZERO_COUNTS


def test_05_stage396_blocked_readiness_event_is_exact_adaptation_source(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "source397")
    predecessor = service.get_mission_events(mission_id)["events"][39]
    assert predecessor["event_type"] == "MISSION_COMPLETION_READINESS_EVALUATED"
    adaptation = service.repository.list_adaptation_replans(mission_id)[0]
    assert adaptation["source_event_id"] == predecessor["event_id"]
    assert adaptation["source_event_sha256"] == predecessor["canonical_sha256"]
    assert adaptation["trigger_source"] == "MISSION_EVENT" and adaptation["trigger_code"] == "EVIDENCE_CHANGE"
    assert rows["classification"]["reason_code"] == "PLAN_STALE"
    assert rows["classification"]["replan_scope_level"] == "LEVEL_3_PARTIAL_PLAN"


def test_06_deterministic_candidate_removes_completed_root_and_preserves_remainder_dag(tmp_path):
    _, _, _, _, _, rows, _ = provision(tmp_path, "candidate397")
    cand = rows["candidate"]["replan_candidate_contract"]["candidate_successor_plan"]
    assert cand["candidate_task_count"] == 2
    assert [x["task_key"] for x in cand["candidate_tasks"]] == ["analyze-cti", "report-findings"]
    assert cand["completed_source_task_count"] == 1
    assert cand["candidate_dependency_edge_count"] == 1
    assert cand["satisfied_predecessor_count"] == 1


def test_07_authoritative_commit_atomically_advances_plan_head_without_state_transition(tmp_path):
    service, governance, _, mission_id, _, rows, _ = provision(tmp_path, "commit397")
    assert rows["eligibility"]["eligibility_status"] == "ELIGIBLE"
    assert rows["validation"]["validation_status"] == "VALIDATED_FOR_COMMIT" and rows["validation"]["feasible"] is True
    assert rows["commit"]["commit_status"] == "COMMITTED_SUCCESSOR_PLAN"
    history = service.get_plan_version_history(mission_id)["plan_versions"]
    assert [(x["plan_version"], x["effective_status"]) for x in history] == [(1, "SUPERSEDED"), (2, "ACTIVE")]
    assert service.get_active_plan_version(mission_id)["plan_version"] == 2
    assert service.get_mission_state(mission_id)["mission_state"]["state_version"] == 4
    assert governance.evaluate_calls == 4


def test_08_handoff_ready_stops_before_new_routing_dispatch_or_recovery(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "handoff397")
    handoff = rows["handoff"]
    assert handoff["handoff_status"] == "HANDOFF_READY"
    assert handoff["task_disposition_count"] == 3 and handoff["keep_count"] == 3
    contract = handoff["replan_handoff_contract"]
    assert contract["successor_handoff"]["next_control"] == "STAGE3_4_ROUTING_THEN_STAGE3_5_DISPATCH"
    assert contract["successor_handoff"]["routing_performed"] is False
    assert contract["successor_handoff"]["dispatch_performed"] is False
    assert contract["task_handoff"]["cancellation_io_performed"] is False
    assert service.repository.list_replan_recovery_checkpoints(mission_id) == []


def test_09_read_only_qualification_adds_no_calls_events_or_records(tmp_path):
    service, governance, runtime, mission_id, *_ = provision(tmp_path, "readonly397")
    before_events = service.get_mission_events(mission_id)["event_count"]
    before_counts = service.repository.get_repository_record_counts(mission_id)
    before_calls = (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls)
    first = service.get_e2e_adaptation_replanning_qualification(mission_id)
    second = service.get_e2e_adaptation_replanning_qualification(mission_id)
    assert first == second and first["qualification"]["qualified"] is True
    assert service.get_mission_events(mission_id)["event_count"] == before_events
    assert service.repository.get_repository_record_counts(mission_id) == before_counts
    assert before_calls == (governance.evaluate_calls, runtime.deliver_calls, runtime.status_calls, runtime.result_calls)


def test_10_exact_replan_mutation_replay_is_idempotent_and_event_stable(tmp_path):
    service, _, _, mission_id, _, rows, requests = provision(tmp_path, "replay397")
    before = service.repository.get_repository_record_counts(mission_id)
    episode = rows["adaptation"]["adaptation_episode_id"]
    assert service.create_adaptation_replan(mission_id, deepcopy(requests["adaptation"]))["idempotent_replay"] is True
    assert service.classify_adaptation_trigger(mission_id, episode, deepcopy(requests["classification"]))["idempotent_replay"] is True
    assert service.evaluate_replan_eligibility(mission_id, episode, deepcopy(requests["eligibility"]))["idempotent_replay"] is True
    assert service.bind_replan_snapshot(mission_id, episode, deepcopy(requests["snapshot"]))["idempotent_replay"] is True
    assert service.generate_replan_candidate(mission_id, rows["snapshot"]["replan_snapshot_id"], deepcopy(requests["candidate"]))["idempotent_replay"] is True
    assert service.validate_replan_candidate(mission_id, rows["candidate"]["replan_candidate_id"], deepcopy(requests["validation"]))["idempotent_replay"] is True
    assert service.commit_authorized_replan(mission_id, rows["validation"]["replan_validation_id"], deepcopy(requests["commit"]))["idempotent_replay"] is True
    assert service.declare_replan_handoff(mission_id, rows["commit"]["replan_commit_id"], deepcopy(requests["handoff"]))["idempotent_replay"] is True
    assert service.repository.get_repository_record_counts(mission_id) == before
    assert service.get_mission_events(mission_id)["event_count"] == 49


def test_11_partial_adaptation_chain_is_rejected(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "partial397", stop="classification")
    result = service.get_e2e_adaptation_replanning_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert "EXACT_EVENT_TRAJECTORY" in result["failed_check_ids"]
    assert "EXACT_SINGLE_ARTIFACT_CARDINALITY" in result["failed_check_ids"]


def test_12_stale_commit_source_fails_closed_before_authoritative_commit(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "stale397", stop="validation")
    stale = commit_request(rows["snapshot"], rows["candidate"], rows["validation"], "stale397-guard")
    stale["expected_source_version_sha256"] = "0" * 64
    with pytest.raises(MissionConcurrencyConflict):
        service.commit_authorized_replan(mission_id, rows["validation"]["replan_validation_id"], stale)


def test_13_repository_tamper_breaks_qualification(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "tamper397")
    db = service.repository.sqlite_path
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE mission_replan_commits SET canonical_sha256=? WHERE mission_id=? AND replan_commit_id=?",
            ("0" * 64, mission_id, rows["commit"]["replan_commit_id"]),
        ); conn.commit()
    restarted = CanonicalMissionService(MissionRepository(sqlite_path=db))
    result = restarted.get_e2e_adaptation_replanning_qualification(mission_id)["qualification"]
    assert result["status"] == "REJECTED"
    assert "MISSION_AND_REPOSITORY_INTEGRITY" in result["failed_check_ids"] or "CANONICAL_REPLAN_ARTIFACT_INTEGRITY" in result["failed_check_ids"]


def test_14_restart_reconstructs_same_read_only_qualification(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "restart397")
    first = service.get_e2e_adaptation_replanning_qualification(mission_id)
    restarted = CanonicalMissionService(MissionRepository(sqlite_path=str(service.repository.sqlite_path)))
    second = restarted.get_e2e_adaptation_replanning_qualification(mission_id)
    assert first["qualification"] == second["qualification"]
    assert second["qualification"]["status"] == "QUALIFIED"


def test_15_http_contract_and_mission_qualification_routes(tmp_path):
    service, _, _, mission_id, *_ = provision(tmp_path, "http397")
    before = service.repository.get_repository_record_counts(mission_id)
    handler = type("Stage397Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/api/e2e/adaptation-replanning-qualification-contract") as response:
            contract = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-adaptation-replanning-qualification") as response:
            proof = json.loads(response.read().decode("utf-8"))
        assert contract == service.get_e2e_adaptation_replanning_contract_definition()
        assert proof["qualification"]["status"] == "QUALIFIED"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert service.repository.get_repository_record_counts(mission_id) == before


def test_16_replay_is_exact_precheckpoint_and_definition_hands_off_to_398(tmp_path):
    service, *_rest, mission_id, _, _, _ = provision(tmp_path, "boundary397")
    replay = service.get_replan_event_replay(mission_id)
    assert replay["replan_event_count"] == 9
    assert [x["event_type"] for x in replay["events"]] == list(ADAPTATION_REPLANNING_EXPECTED_REPLAN_EVENT_TYPES)
    assert service.repository.list_replan_recovery_checkpoints(mission_id) == []
    out = service.get_e2e_adaptation_replanning_contract_definition()
    assert out["control_version"] == CONTROL
    assert out["definition"]["predecessor_control"] == ADAPTATION_REPLANNING_PREDECESSOR_CONTROL
    assert out["definition"]["stage3_7_9_recovery_checkpoint_expected"] is False
    assert out["definition"]["next_stage"] == "3.9.8"
