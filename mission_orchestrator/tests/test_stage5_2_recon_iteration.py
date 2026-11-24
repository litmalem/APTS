from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from execution_subsystem.execution_contract import with_integrity
from execution_subsystem.execution_result_contract import RESULT_DOMAIN, build_recon_execution_result
from pentest_subsystem.orchestration.orchestrator import AgenticPentestOrchestratorRepository
from pentest_subsystem.reconnaissance import ReconnaissanceAgentConflict, ReconnaissanceAgentRepository, ReconnaissanceAgentService
from tests.test_stage5_2_reconnaissance_agent import _start_repo, recon_request


def test_migration_010_upgrades_existing_stage52_repository(tmp_path):
    db = tmp_path / "legacy-stage52.db"
    predecessor = AgenticPentestOrchestratorRepository(db)
    predecessor.initialize()
    migration_009 = Path(__file__).resolve().parents[1] / "pentest_migrations" / "009_stage5_2_reconnaissance_agent.sql"
    with sqlite3.connect(db) as conn:
        conn.executescript(migration_009.read_text(encoding="utf-8"))
        conn.execute("UPDATE pentest_repository_meta SET migration_level=9, schema_version='apts-pentest-reconnaissance-agent-repository-v9'")
    upgraded = ReconnaissanceAgentRepository(db)
    upgraded.initialize()
    assert upgraded.migration_level() == 10
    with sqlite3.connect(db) as conn:
        columns = {item[1] for item in conn.execute("PRAGMA table_info(pentest_recon_runs)")}
    assert {"iteration_index", "parent_recon_run_id", "source_action_id", "source_result_sha256"}.issubset(columns)


def _stage6_result(action, task, orchestration):
    attempt = {
        "attempt_id": "xattempt-stage10",
        "state": "SUCCEEDED",
        "head_sha256": "a" * 64,
        "record": {
            "mission_id": task["mission_id"], "pentest_id": task["pentest_id"],
            "task_id": task["upstream_task_id"], "pentest_task_id": task["pentest_task_id"],
            "execution_id": "exec-stage10", "attempt_number": 1, "retry_of_attempt_id": None,
            "integrity": {"canonical_sha256": "b" * 64},
        },
        "invocation": {"result": {
            "status": "SUCCEEDED", "reason_codes": [], "observation": {"service": "https", "port": 443},
            "semantics": {"target_io_uncertain": False}, "integrity": {"canonical_sha256": "c" * 64},
        }},
        "events": [{"event_id": "auth-event", "data": {"authorization_id": "auth-stage10"}},
                   {"event_id": "terminal-event", "data": {}}],
    }
    manifest = {"recon_action_id": action["action_id"], "proposal_ref": action["proposal_ref"],
                "attempt_id": attempt["attempt_id"], "terminal_event_sha256": attempt["head_sha256"],
                "evidence_id": "xevidence-stage10", "integrity": {"canonical_sha256": "d" * 64},
                "capture_status": "SEALED", "target_io_uncertain": False, "artifacts": []}
    result = build_recon_execution_result(action_id=action["action_id"], proposal_ref=action["proposal_ref"],
        orchestration_id=orchestration["orchestration_id"], item=attempt, manifest=manifest)
    return with_integrity({key: value for key, value in result.items() if key != "integrity"}, RESULT_DOMAIN)


def test_iteration_adds_new_hash_bound_run_and_preserves_parent(tmp_path):
    repo, boundary, task, orchestration, *_ = _start_repo(tmp_path, "stage10-iteration")
    parent, _ = repo.run_reconnaissance(orchestration["orchestration_id"],
        recon_request(boundary, task, "stage10-iteration"))
    action = parent["output"]["action_requests"][0]
    result = _stage6_result(action, task, orchestration)
    service = ReconnaissanceAgentService(repo, execution_result_provider=lambda action_id: {
        "action_id": action_id, "results": [result], "latest_result": result,
    })

    iteration = service.run_reconnaissance_iteration(orchestration["orchestration_id"], {
        "schema_version": "apts-stage5.2-recon-iteration-request-v1",
        "parent_recon_run_id": parent["recon_run_id"], "action_id": action["action_id"],
    })["run"]

    assert iteration["recon_run_id"] != parent["recon_run_id"]
    assert iteration["iteration_index"] == 2
    assert iteration["parent_recon_run_id"] == parent["recon_run_id"]
    assert iteration["source_action_id"] == action["action_id"]
    assert iteration["source_result_sha256"] == result["integrity"]["canonical_sha256"]
    assert iteration["output"]["iteration"]["semantics"]["previous_run_mutated"] is False
    assert iteration["request"]["observations"][-1]["source"]["source_kind"] == "STAGE6_EXECUTION_RESULT"
    assert repo.get_recon_run(parent["recon_run_id"]) == parent
    assert repo.get_orchestration_recon_run(orchestration["orchestration_id"])["recon_run_id"] == iteration["recon_run_id"]


def test_iteration_rejects_unsealed_or_nonterminal_result(tmp_path):
    repo, boundary, task, orchestration, *_ = _start_repo(tmp_path, "stage10-block")
    parent, _ = repo.run_reconnaissance(orchestration["orchestration_id"],
        recon_request(boundary, task, "stage10-block"))
    action = parent["output"]["action_requests"][0]
    result = _stage6_result(action, task, orchestration)
    result["terminal"] = False
    result = with_integrity({key: value for key, value in result.items() if key != "integrity"}, RESULT_DOMAIN)
    service = ReconnaissanceAgentService(repo, execution_result_provider=lambda _: {
        "action_id": action["action_id"], "results": [result], "latest_result": result,
    })
    with pytest.raises(ReconnaissanceAgentConflict, match="terminal"):
        service.run_reconnaissance_iteration(orchestration["orchestration_id"], {
            "schema_version": "apts-stage5.2-recon-iteration-request-v1",
            "parent_recon_run_id": parent["recon_run_id"], "action_id": action["action_id"],
        })


def test_wpt_handoff_creates_durable_hash_bound_recon_iteration_and_replays(tmp_path):
    from execution_subsystem.wpt_intake_repository import _seal_handoff
    repo, boundary, task, orchestration, *_ = _start_repo(tmp_path, "stage10-wpt-handoff")
    parent, _ = repo.run_reconnaissance(orchestration["orchestration_id"],
        recon_request(boundary, task, "stage10-wpt-handoff"))
    action = parent["output"]["action_requests"][0]
    source_hash = "e" * 64
    handoff = _seal_handoff({
        "schema_version": "apts-wpt-recon-handoff-event-v1", "handoff_id": "wpthandoff-test",
        "intake_id": "wptreq-test", "mission_id": task["mission_id"],
        "task_id": task["upstream_task_id"], "orchestration_id": orchestration["orchestration_id"],
        "target": deepcopy(task["target"]),
        "profile_id": "wpt.fingerprinting.v1",
        "action": {"action_class": "TARGET_RECON", "capability_id": "web_technology_fingerprinting",
                   "technique": "WEB_TECHNOLOGY_FINGERPRINT"},
        "parent_recon_run_id": parent["recon_run_id"], "action_id": action["action_id"],
        "execution_id": "exec-wpt-test", "attempt_id": "xattempt-wpt-test",
        "result_stored_at": "2026-10-17T10:24:00Z",
        "source_result_sha256": source_hash,
        "evidence": {"evidence_id": "xevidence-wpt-test", "manifest_sha256": "f" * 64,
                     "capture_status": "SEALED"},
        "result": {"status": "SUCCEEDED", "reason_codes": [],
                   "observation": {"technology_findings": [{"name": "Example"}]}},
        "semantics": {"result_is_authorization": False, "result_is_vulnerability_finding": False,
                      "target_io_performed_by_handoff": False, "previous_recon_run_mutated": False},
    })
    service = ReconnaissanceAgentService(repo)
    first = service.run_wpt_reconnaissance_iteration(handoff)
    replay = service.run_wpt_reconnaissance_iteration(handoff)
    assert first["accepted"] is True and first["created"] is True
    assert replay["replayed"] is True and replay["recon_run_id"] == first["recon_run_id"]
    child = repo.get_recon_run(first["recon_run_id"])
    assert child["parent_recon_run_id"] == parent["recon_run_id"]
    assert child["source_action_id"] == action["action_id"]
    assert child["source_result_sha256"] == source_hash
    assert child["request"]["observations"][-1]["source"]["source_kind"] == "WPT_STAGE6_RESULT"
    assert repo.get_recon_run(parent["recon_run_id"]) == parent


def test_workflow_monitor_reads_only_bound_action_results(tmp_path):
    repo, boundary, task, orchestration, *_ = _start_repo(tmp_path, "stage11-monitor")
    parent, _ = repo.run_reconnaissance(orchestration["orchestration_id"],
        recon_request(boundary, task, "stage11-monitor"))
    action = parent["output"]["action_requests"][0]
    result = _stage6_result(action, task, orchestration)
    response = {"action_id": action["action_id"], "results": [result], "latest_result": result}
    service = ReconnaissanceAgentService(repo, execution_result_provider=lambda action_id: response)

    observed = service.get_stage6_execution_results(action["action_id"])
    assert observed["read_only"] is True
    assert observed["latest_result"] == result
    assert observed["attempt_count"] == 1
    assert repo.get_recon_run(parent["recon_run_id"]) == parent


def test_workflow_monitor_rejects_unbound_action_id(tmp_path):
    from pentest_subsystem.reconnaissance import ReconnaissanceAgentNotFound
    repo, *_ = _start_repo(tmp_path, "stage11-monitor-unbound")
    service = ReconnaissanceAgentService(repo, execution_result_provider=lambda _: {})
    with pytest.raises(ReconnaissanceAgentNotFound, match="Action Request"):
        service.get_stage6_execution_results("rareq-not-in-recon")
