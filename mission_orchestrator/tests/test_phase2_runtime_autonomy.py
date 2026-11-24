from __future__ import annotations

from http.server import ThreadingHTTPServer
import sqlite3
import threading
import time
from threading import Thread

import pytest

from pentest_subsystem.api_service import PentestSubsystemStage510Handler
from pentest_subsystem.cross_agent_feedback import CrossAgentFeedbackRepository, CrossAgentFeedbackService
from pentest_subsystem.orchestration.runtime_autonomy import AutonomyRuntime, allowed_techniques_for, project
from pentest_subsystem.runtime_autonomy_api import (
    PentestSubsystemRuntimeAutonomyHandler,
    start_background_ticker,
)
from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import materialize
from tests.test_stage5_1_full_agentic_pentest_workflow_orchestrator import start_payload
from tests.test_stage5_2_recon_iteration import _stage6_result
from tests.test_stage5_2_reconnaissance_agent import recon_request
from tests.test_stage5_8_cross_agent_feedback_shared_state_replanning import (
    _get,
    _pipeline,
    _post,
)


def _recon_only(tmp_path, suffix="rt2"):
    repo = CrossAgentFeedbackRepository(tmp_path / "pentest.db")
    boundary, _, task, _, _ = materialize(repo)
    orch, _, _, _ = repo.start_orchestration(task["pentest_task_id"], start_payload(suffix))
    oid = orch["orchestration_id"]
    run, _ = repo.run_reconnaissance(oid, recon_request(boundary, task, suffix))
    return repo, task, orch, oid, run


def _service_with_result(repo, run, task, orch, *, present=True):
    action = run["output"]["action_requests"][0]
    result = _stage6_result(action, task, orch)
    service = CrossAgentFeedbackService(repo)
    service.execution_result_provider = lambda action_id: (
        {"action_id": action_id, "results": [result], "latest_result": result} if present
        else {"action_id": action_id, "results": [], "latest_result": None})
    return service, action, result


def _count(db, table):
    try:
        with sqlite3.connect(db) as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:  # table not created yet (sidecar migration runs on first tick)
        return 0


def test_projection_reads_authoritative_stage_runs_not_caller_input(tmp_path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "rtproj")
    proj = project(repo, oid)
    obs = proj["observations"]
    assert obs["in_scope_assets"] >= 1 and obs["candidate_paths"] >= 1
    assert obs["validated_paths"] >= 1 and obs["impact_assessed_paths"] == obs["validated_paths"]
    done = {n["capability_id"] for n in proj["overlay_graph"]["nodes"] if n["status"] == "SUCCEEDED"}
    assert {"reconnaissance", "enumeration", "vulnerability_analysis", "attack_path_analysis",
            "validation", "exploitation", "impact_analysis"} <= done
    before = repo.get_orchestration(oid)["task_graph_sha256"]
    project(repo, oid)
    assert repo.get_orchestration(oid)["task_graph_sha256"] == before  # projection never mutates the plan


def test_deliberate_on_real_state_is_persisted_and_idempotent(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rtdel")
    rt = AutonomyRuntime(CrossAgentFeedbackService(repo))
    first = rt.deliberate(oid, budget_remaining=10)
    assert first["created"] and first["deliberation"]["intention"]["capability_id"] == "enumeration"
    again = rt.deliberate(oid, budget_remaining=10)
    assert again["created"] is False
    assert _count(tmp_path / "pentest.db", "pentest_deliberation_records") == 1
    assert first["execution_started"] is False and first["authorization_minted"] is False


def test_tick_without_stage6_result_records_baseline_and_no_event(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rtnone")
    service, *_ = _service_with_result(repo, run, task, orch, present=False)
    report = AutonomyRuntime(service).tick(oid)
    rec = report["capabilities"]["reconnaissance"]
    assert rec["events_processed"] == [] and rec["skipped"]
    assert report["capabilities"]["enumeration"]["skipped"] == [{"reason": "NO_PRIOR_RUN"}]
    assert _count(tmp_path / "pentest.db", "pentest_perception_decisions") == 1  # baseline sequence 0
    assert report["external_network_io_performed"] is False


def test_sealed_result_event_drives_decision_and_replays_idempotently(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rtevt")
    service, action, result = _service_with_result(repo, run, task, orch)
    rt = AutonomyRuntime(service)
    report = rt.tick(oid)
    ev = report["capabilities"]["reconnaissance"]["events_processed"]
    assert len(ev) == 1 and ev[0]["event_id"] == "sealed-" + result["integrity"]["canonical_sha256"][:40]
    assert ev[0]["arbitration"]["rule"] == "R3_DELIBERATIVE_STANDS"
    assert rt.tick(oid)["capabilities"]["reconnaissance"]["events_processed"] == []
    db = tmp_path / "pentest.db"
    assert _count(db, "pentest_perception_decisions") == 2
    assert _count(db, "pentest_arbitration_records") == 1
    assert len(repo.list_recon_runs(limit=50)) == 1  # no auto_iterate: no new run created


def test_auto_iterate_runs_existing_governed_recon_iteration_only(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rtiter")
    service, action, result = _service_with_result(repo, run, task, orch)
    report = AutonomyRuntime(service).tick(oid, auto_iterate=True)
    iterations = report["capabilities"]["reconnaissance"]["iterations"]
    assert iterations == [{"action_id": action["action_id"], "status": "ok"}]
    latest = repo.get_orchestration_recon_run(oid)
    assert latest["iteration_index"] == 2 and latest["parent_recon_run_id"] == run["recon_run_id"]
    assert repo.get_recon_run(run["recon_run_id"]) == run  # parent immutable
    assert report["execution_started"] is False and report["authorization_minted"] is False


def test_adverse_target_condition_preempts_and_tightens_noise(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rtrea")
    service, action, result = _service_with_result(repo, run, task, orch)
    signal = {"signal_id": "tcond-" + "a" * 48, "integrity": {"canonical_sha256": "d" * 64},
              "observed": {"rate_limited": True, "server_overload": False, "access_forbidden": False,
                           "waf_indicator": False, "retry_after_seconds": None}}
    rt = AutonomyRuntime(service, signal_extractor=lambda _res: signal)
    entry = rt.tick(oid)["capabilities"]["reconnaissance"]["events_processed"][0]
    assert entry["arbitration"]["rule"] == "R2_DEGRADE_PREEMPTS"
    assert entry["arbitration"]["winner"] == "REACTIVE"
    state_row = sqlite3.connect(tmp_path / "pentest.db").execute(
        "SELECT state_json FROM pentest_perception_decisions WHERE sequence=1").fetchone()[0]
    assert '"max_noise":0' in state_row.replace(" ", "")
    status = rt.status(oid)
    assert status["integrity_verified"] is True and status["arbitrations"][0]["rule"] == "R2_DEGRADE_PREEMPTS"


def test_runtime_tables_are_append_only(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rtapp")
    service, *_ = _service_with_result(repo, run, task, orch)
    AutonomyRuntime(service).tick(oid)
    with sqlite3.connect(tmp_path / "pentest.db") as conn:
        for sql in ("UPDATE pentest_perception_decisions SET event_id='x'",
                    "DELETE FROM pentest_perception_decisions",
                    "UPDATE pentest_arbitration_records SET winner='x'",
                    "DELETE FROM pentest_arbitration_records"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)


def _server(repo):
    service = CrossAgentFeedbackService(repo)
    handler = type("IsolatedAutonomyHandler", (PentestSubsystemRuntimeAutonomyHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_http_routes_expose_runtime_without_changing_existing_routes(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rthttp")
    server, base = _server(repo)
    try:
        status, _, body = _get(base + "/api/contracts/runtime-autonomy")
        assert status == 200 and body["execution_authority"] == "STAGE6" and body["background_ticker_default"] == "OFF"
        root = "/api/pentest/agentic-orchestrations/" + oid
        status, body = _post(base + root + "/autonomy/deliberate", {"budget_remaining": 5})
        assert status == 200 and body["deliberation"]["intention"]["capability_id"] == "enumeration"
        status, body = _post(base + root + "/autonomy/tick", {})
        assert status == 200 and body["execution_started"] is False
        status, _, body = _get(base + root + "/autonomy")
        assert status == 200 and body["integrity_verified"] is True and body["read_only"] is True
        assert _post(base + "/api/pentest/agentic-orchestrations/nope/autonomy/tick", {})[0] == 404
        assert _post(base + root + "/autonomy/tick", {"auto_iterate": "yes"})[0] == 400
        assert _post(base + root + "/autonomy/deliberate", {"budget_remaining": -1})[0] == 400
        assert _post(base + "/api/execution/dispatches", {})[0] == 409  # Stage 6 remains the only executor
        assert _get(base + "/api/pentest/health")[0] in {200, 404}
    finally:
        server.shutdown()


def test_runtime_handler_extends_active_stage510_handler():
    assert issubclass(PentestSubsystemRuntimeAutonomyHandler, PentestSubsystemStage510Handler)


def test_background_ticker_is_opt_in_and_stoppable(tmp_path):
    repo, task, orch, oid, run = _recon_only(tmp_path, "rttick")
    service, *_ = _service_with_result(repo, run, task, orch)
    stop = threading.Event()
    thread = start_background_ticker(service, 0.05, stop=stop)
    deadline = time.time() + 5
    while time.time() < deadline and _count(tmp_path / "pentest.db", "pentest_perception_decisions") < 2:
        time.sleep(0.05)
    stop.set()
    thread.join(timeout=2)
    assert _count(tmp_path / "pentest.db", "pentest_perception_decisions") >= 2
    assert not thread.is_alive()


def test_projection_handles_web_mission_with_enumerated_asset_but_no_recon_hosts():
    class FakeRepo:
        def get_orchestration(self, oid):
            return {"task_graph": {"nodes": [{"capability_id": c, "status": "PENDING", "subtask_id": "s-" + c}
                                             for c in ("reconnaissance", "enumeration", "vulnerability_analysis",
                                                       "attack_path_analysis", "validation", "exploitation",
                                                       "impact_analysis")]}}
        def get_orchestration_recon_run(self, oid):
            return {"output": {"hosts": [], "domains": [], "services": []}, "request": {"boundary": {"roe": {}}}}
        def get_orchestration_enumeration_run(self, oid):
            return {"output": {"enumerated_assets": [{}], "technology_identifications": [{}, {}],
                               "service_observations": [], "version_discoveries": []},
                    "request": {"boundary": {"roe": {}}}}
        def get_orchestration_vulnerability_hypothesis_run(self, oid):
            return {"output": {"vulnerability_hypotheses": [{}] * 19}}
        def get_orchestration_attack_path_planning_run(self, oid): return None
        def get_orchestration_exploitation_run(self, oid): return None
        def get_orchestration_post_exploitation_impact_run(self, oid): return None

    proj = project(FakeRepo(), "paorch-x")
    assert proj["observations"]["in_scope_assets"] == 1 and proj["observations"]["enumerated_assets"] == 1
    assert proj["observations"]["open_hypotheses"] == 19
    assert proj["surfaces"]["enumeration"]["unversioned_services"] == {"total": 1, "remaining": 1}
    assert proj["surfaces"]["reconnaissance"]["unprofiled_hosts"]["total"] == 1


def test_roe_allowlist_semantics_are_fail_closed_and_match_existing_rules():
    base = {"allowed_action_classes": ["TARGET_RECON"]}
    assert allowed_techniques_for("reconnaissance", base)[0] == ["PASSIVE_DISCOVERY"]  # active scan needs explicit RoE
    assert "VERSION_DISCOVERY" in allowed_techniques_for("enumeration", base)[0]
    assert allowed_techniques_for("reconnaissance", {**base, "allowed_techniques": ["TCP_CONNECT_SCAN"]})[0] == ["TCP_CONNECT_SCAN"]
    assert allowed_techniques_for("enumeration", {})[0] == []
    assert allowed_techniques_for("enumeration", {**base, "prohibited_action_classes": ["TARGET_RECON"]})[0] == []
    assert allowed_techniques_for("enumeration", {**base, "prohibited_techniques": ["TCP_BANNER_READ"]})[1] == ["TCP_BANNER_READ"]
