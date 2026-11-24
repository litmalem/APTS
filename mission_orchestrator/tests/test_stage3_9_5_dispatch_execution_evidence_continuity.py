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
from mission_orchestrator.e2e_dispatch_execution_evidence_qualification import (
    DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES,
    DISPATCH_EXECUTION_EVIDENCE_EXPECTED_NONZERO_COUNTS,
    DISPATCH_EXECUTION_EVIDENCE_PREDECESSOR_CONTROL,
    DISPATCH_EXECUTION_EVIDENCE_SCHEMA_VERSION,
    build_running_start_request,
    canonical_dispatch_execution_evidence_contract,
    verify_dispatch_execution_evidence_contract,
)
from mission_orchestrator.errors import (
    MissionConcurrencyConflict, MissionExecutionAttemptGuardRejected,
    MissionSubsystemProtocolError,
)
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.repository_model import REPOSITORY_MIGRATION_LEVEL
from mission_orchestrator.service import CanonicalMissionService
from tests.test_stage3_5_1_canonical_execution_dispatch_contract_identity import dispatch_request
from tests.test_stage3_5_2_dispatch_eligibility_execution_preconditions import eligibility_request
from tests.test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation import revalidation_request
from tests.test_stage3_5_4_idempotent_dispatch_execution_attempt_identity import attempt_request
from tests.test_stage3_5_5_dispatch_delivery_execution_acknowledgement import delivery_request
from tests.test_stage3_5_6_running_execution_state_heartbeat_projection import running_request
from tests.test_stage3_5_7_execution_result_evidence_artifact_capture import (
    FakeExecutionResultClient, result_request,
)
from tests.test_stage3_9_4_routing_delegation_governance_continuity import make_service, provision_stage394

CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"


def provision(tmp_path: Path, run_id: str, *, stop: str | None = None):
    service, governance = make_service(tmp_path / f"{run_id}.db")
    mission_id, _, upstream = provision_stage394(service, run_id)
    runtime = FakeExecutionResultClient()
    service.execution_delivery_client = runtime
    active = upstream["activation"]
    state = service.get_mission_state(mission_id)["mission_state"]
    version = service.get_mission_version_vector(mission_id)
    start = build_running_start_request(run_id=run_id, expected_version_sha256=version["version_sha256"],
                                        expected_state_version=state["state_version"])
    service.execute_mission_lifecycle_command(mission_id, start)
    if stop == "start":
        return service, governance, runtime, mission_id, upstream, {}, {}

    requests = {}
    rows = {}
    requests["dispatch"] = dispatch_request(service, mission_id, active, upstream["delivery"], run_id)
    rows["dispatch"] = service.create_execution_dispatch_contract(mission_id, requests["dispatch"])
    requests["gate"] = eligibility_request(service, mission_id, active, rows["dispatch"], run_id)
    rows["gate"] = service.create_dispatch_eligibility_gate(mission_id, requests["gate"])
    if stop == "gate":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["reval"] = revalidation_request(service, mission_id, active, rows["dispatch"], rows["gate"], run_id)
    rows["reval"] = service.authorize_pre_dispatch_execution(mission_id, requests["reval"])
    if stop == "reval":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["attempt"] = attempt_request(service, mission_id, active, rows["dispatch"], rows["gate"], rows["reval"], run_id)
    rows["attempt"] = service.commit_execution_attempt(mission_id, requests["attempt"])
    requests["delivery"] = delivery_request(service, mission_id, active, rows["attempt"], run_id)
    rows["delivery"] = service.deliver_execution_attempt(mission_id, requests["delivery"])
    requests["running"] = running_request(service, mission_id, active, rows["attempt"], rows["delivery"], run_id)
    rows["running"] = service.project_running_execution_state(mission_id, requests["running"])
    if stop == "running":
        return service, governance, runtime, mission_id, upstream, rows, requests

    requests["result"] = result_request(service, mission_id, active, rows["attempt"], rows["delivery"], rows["running"], run_id)
    rows["result"] = service.capture_execution_result(mission_id, requests["result"])
    return service, governance, runtime, mission_id, upstream, rows, requests


def test_01_contract_binds_394_without_new_authority_or_migration():
    contract = canonical_dispatch_execution_evidence_contract()
    assert verify_dispatch_execution_evidence_contract(contract)
    assert contract["predecessor_control"] == DISPATCH_EXECUTION_EVIDENCE_PREDECESSOR_CONTROL
    assert contract["qualified_segment_head"]["state"] == "RUNNING"
    assert contract["qualified_segment_head"]["task_completion_performed"] is False
    assert contract["continuity_requirements"]["fresh_governance_allow_precedes_dispatch_commit_and_delivery"] is True
    assert contract["next_stage"] == "3.9.6"
    forged = deepcopy(contract)
    forged["continuity_requirements"]["fresh_governance_allow_precedes_dispatch_commit_and_delivery"] = False
    assert verify_dispatch_execution_evidence_contract(forged) is False


def test_02_health_activates_395_and_preserves_existing_authorities(tmp_path):
    service, _ = make_service(tmp_path / "health.db")
    health = service.health()
    assert health["control_version"] == CONTROL
    assert health["supported_controls"][-7:] == [DISPATCH_EXECUTION_EVIDENCE_PREDECESSOR_CONTROL, "stage3.9.5-dispatch-execution-evidence-continuity", "stage3.9.6-task-completion-mission-outcome-closure", "stage3.9.7-adaptation-replanning-e2e-scenario", "stage3.9.8-restart-replay-recovery-e2e-verification", "stage3.9.9-global-observation-reconstruction-forensic-equivalence", CONTROL]
    assert health["mission_repository_migration_level"] == REPOSITORY_MIGRATION_LEVEL == 53
    assert MissionOrchestratorHandler.server_version == "APTSMissionOrchestrator/3.9.10"
    assert health["stage3_9_5_dispatch_execution_evidence_schema_version"] == DISPATCH_EXECUTION_EVIDENCE_SCHEMA_VERSION
    assert health["stage3_9_5_runtime_verifier_read_only"] is True
    assert health["stage3_9_5_authoritative_pre_dispatch_governance_allow_required"] is True
    assert health["stage3_9_5_execution_result_is_task_completion"] is False
    assert health["stage3_9_5_new_database_migration_added"] is False
    assert health["stage3_9_5_new_dispatch_authority_added"] is False
    assert health["stage3_9_5_new_execution_authority_added"] is False
    assert health["stage3_9_5_next_stage"] == "3.9.6"


def test_03_canonical_394_head_flows_to_succeeded_result_with_evidence(tmp_path):
    service, gov, runtime, mission_id, upstream, rows, _ = provision(tmp_path, "success395")
    proof = service.get_e2e_dispatch_execution_evidence_qualification(mission_id)
    assert proof["qualification"]["status"] == "QUALIFIED", proof["qualification"]["failed_check_ids"]
    head = proof["qualification"]["segment_head"]
    assert head["state"] == "RUNNING" and head["state_version"] == 4
    assert head["planned_task_id"] == upstream["delivery"]["planned_task_id"]
    assert head["execution_attempt_id"] == rows["result"]["execution_attempt_id"]
    assert head["dispatch_envelope_id"] == rows["result"]["dispatch_envelope_id"]
    assert head["evidence_count"] == 1 and head["artifact_count"] == 1
    assert gov.evaluate_calls == 2  # separate authoritative delegation and execution decisions
    assert runtime.deliver_calls == runtime.status_calls == runtime.result_calls == 1
    assert proof["target_actuation"] is False


def test_04_exact_event_and_store_footprint_no_outcome_commits(tmp_path):
    service, _, _, mission_id, _, _, _ = provision(tmp_path, "footprint395")
    events = service.get_mission_events(mission_id)
    assert events["integrity_status"] == "PASS"
    assert [item["event_type"] for item in events["events"]] == list(DISPATCH_EXECUTION_EVIDENCE_EXPECTED_EVENT_TYPES)
    assert events["event_count"] == 31
    counts = service.repository.get_repository_record_counts(mission_id)
    assert {k: v for k, v in counts.items() if v} == DISPATCH_EXECUTION_EVIDENCE_EXPECTED_NONZERO_COUNTS


def test_05_result_is_separate_from_task_completion_and_mission_success(tmp_path):
    service, _, _, mission_id, _, rows, _ = provision(tmp_path, "boundary395")
    assert rows["result"]["execution_state"] == "SUCCEEDED"
    assert rows["result"]["result_capture_is_not_task_completion_authority"] is True
    assert service.get_mission_state(mission_id)["mission_state"]["state"] == "RUNNING"
    counts = service.repository.get_repository_record_counts(mission_id)
    assert counts.get("mission_task_completion_commits", 0) == 0
    assert counts.get("mission_outcome_aggregations", 0) == 0
    assert service.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]["qualified"] is True


def test_06_read_only_verification_and_replay_make_no_external_calls(tmp_path):
    service, gov, runtime, mission_id, _, _, _ = provision(tmp_path, "readonly395")
    before_events = service.get_mission_events(mission_id)["event_count"]
    before_counts = service.repository.get_repository_record_counts(mission_id)
    before_calls = (gov.evaluate_calls, runtime.resolve_calls, runtime.health_calls,
                    runtime.deliver_calls, runtime.status_calls, runtime.result_calls)
    first = service.get_e2e_dispatch_execution_evidence_qualification(mission_id)
    second = service.get_e2e_dispatch_execution_evidence_qualification(mission_id)
    assert first == second and first["qualification"]["qualified"] is True
    assert service.get_mission_events(mission_id)["event_count"] == before_events
    assert service.repository.get_repository_record_counts(mission_id) == before_counts
    assert before_calls == (gov.evaluate_calls, runtime.resolve_calls, runtime.health_calls,
                            runtime.deliver_calls, runtime.status_calls, runtime.result_calls)


def test_07_restart_reconstructs_same_head_without_clients(tmp_path):
    service, _, _, mission_id, _, _, _ = provision(tmp_path, "restart395")
    expected = service.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]
    restarted = CanonicalMissionService(MissionRepository(driver="sqlite", sqlite_path=str(tmp_path / "restart395.db")))
    observed = restarted.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]
    assert observed == expected
    assert observed["qualified"] is True


def test_08_before_terminal_result_qualifier_fails_closed(tmp_path):
    service, _, _, mission_id, _, _, _ = provision(tmp_path, "incomplete395", stop="running")
    proof = service.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]
    assert proof["status"] == "REJECTED"
    assert "SINGLE_CAUSAL_TRAJECTORY_NO_RETRY_DUPLICATES" in proof["failed_check_ids"]
    assert "TERMINAL_RESULT_EVIDENCE_PROVENANCE_INTEGRITY" in proof["failed_check_ids"]


def test_09_governance_deny_stops_dispatch_commit_and_runtime_delivery(tmp_path):
    service, gov, runtime, mission_id, upstream, rows, _ = provision(tmp_path, "deny395", stop="gate")
    gov.emergency_stop = True
    active = upstream["activation"]
    deny = service.authorize_pre_dispatch_execution(mission_id, revalidation_request(
        service, mission_id, active, rows["dispatch"], rows["gate"], "deny395"))
    assert deny["governance_decision"] == "DENY"
    with pytest.raises(MissionExecutionAttemptGuardRejected):
        service.commit_execution_attempt(mission_id, attempt_request(
            service, mission_id, active, rows["dispatch"], rows["gate"], deny, "deny395"))
    assert service.repository.list_execution_attempts(mission_id) == []
    assert runtime.deliver_calls == runtime.health_calls == 0
    proof = service.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]
    assert proof["status"] == "REJECTED" and "ELIGIBILITY_BEFORE_FRESH_GOVERNANCE_ALLOW" in proof["failed_check_ids"]


def test_10_stale_pre_dispatch_request_rejects_before_governance_query(tmp_path):
    service, gov, runtime, mission_id, upstream, rows, _ = provision(tmp_path, "stale395", stop="gate")
    body = revalidation_request(service, mission_id, upstream["activation"], rows["dispatch"], rows["gate"], "stale395")
    body["expected_version_sha256"] = "0" * 64
    before = gov.evaluate_calls
    with pytest.raises(MissionConcurrencyConflict):
        service.authorize_pre_dispatch_execution(mission_id, body)
    assert gov.evaluate_calls == before and runtime.deliver_calls == 0


def test_11_exact_attempt_replay_does_not_duplicate_dispatch_or_event(tmp_path):
    service, _, runtime, mission_id, _, rows, requests = provision(tmp_path, "replay395")
    before = service.get_mission_events(mission_id)["event_count"]
    replay = service.commit_execution_attempt(mission_id, deepcopy(requests["attempt"]))
    assert replay["idempotent_replay"] is True
    assert replay["execution_attempt_id"] == rows["attempt"]["execution_attempt_id"]
    assert replay["dispatch_envelope_id"] == rows["attempt"]["dispatch_envelope_id"]
    assert service.get_mission_events(mission_id)["event_count"] == before
    assert runtime.deliver_calls == 1
    assert service.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]["qualified"] is True


def test_12_runtime_missing_evidence_is_fail_closed_without_result_persistence(tmp_path):
    service, _, runtime, mission_id, upstream, rows, _ = provision(tmp_path, "missing395", stop="running")
    runtime.result_response = runtime.execution_result(
        "CTI", rows["delivery"]["runtime_endpoint"], mission_id=mission_id,
        execution_attempt_id=rows["attempt"]["execution_attempt_id"],
        dispatch_envelope_id=rows["attempt"]["dispatch_envelope_id"])
    runtime.result_response["evidence"] = []
    with pytest.raises(MissionSubsystemProtocolError):
        service.capture_execution_result(mission_id, result_request(
            service, mission_id, upstream["activation"], rows["attempt"], rows["delivery"], rows["running"], "missing395"))
    assert service.repository.list_execution_result_captures(mission_id) == []
    assert service.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]["qualified"] is False


def test_13_durable_source_drift_rejects_qualification(tmp_path):
    service, _, _, mission_id, _, _, _ = provision(tmp_path, "tamper395")
    with sqlite3.connect(str(tmp_path / "tamper395.db")) as conn:
        conn.execute("UPDATE mission_execution_result_captures SET evidence_manifest_sha256=? WHERE mission_id=?",
                     ("0" * 64, mission_id))
    proof = service.get_e2e_dispatch_execution_evidence_qualification(mission_id)["qualification"]
    assert proof["status"] == "REJECTED"
    assert "TERMINAL_RESULT_EVIDENCE_PROVENANCE_INTEGRITY" in proof["failed_check_ids"]

    service2, _, _, mission2, _, _, _ = provision(tmp_path, "tamperplan395")
    with sqlite3.connect(str(tmp_path / "tamperplan395.db")) as conn:
        conn.execute("UPDATE mission_plan_versions SET canonical_sha256=? WHERE mission_id=?",
                     ("0" * 64, mission2))
    plan_proof = service2.get_e2e_dispatch_execution_evidence_qualification(mission2)["qualification"]
    assert plan_proof["status"] == "REJECTED"
    assert "DURABLE_REPOSITORY_INTEGRITY" in plan_proof["failed_check_ids"]


def test_14_http_contract_and_qualification_routes_are_read_only(tmp_path):
    service, _, _, mission_id, _, _, _ = provision(tmp_path, "http395")
    before = service.repository.get_repository_record_counts(mission_id)
    handler = type("Stage395Handler", (MissionOrchestratorHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urlopen(base + "/api/e2e/dispatch-execution-evidence-qualification-contract") as response:
            contract = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-dispatch-execution-evidence-qualification") as response:
            proof1 = json.loads(response.read().decode("utf-8"))
        with urlopen(base + f"/api/missions/{mission_id}/e2e-dispatch-execution-evidence-qualification") as response:
            proof2 = json.loads(response.read().decode("utf-8"))
        assert contract == service.get_e2e_dispatch_execution_evidence_contract_definition()
        assert proof1 == proof2
        assert proof1["qualification"]["qualified"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert service.repository.get_repository_record_counts(mission_id) == before


def test_15_invalid_start_builder_input_is_rejected():
    with pytest.raises(ValueError):
        build_running_start_request(run_id="bad run", expected_version_sha256="0" * 64, expected_state_version=3)
