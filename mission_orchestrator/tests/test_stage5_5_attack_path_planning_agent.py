from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from tests._localhost_http import urlopen_local_with_retry

from pentest_subsystem.api_service import PentestSubsystemStage54Handler, PentestSubsystemStage55Handler
from pentest_subsystem.attack_path_planning import (
    ATTACK_PATH_EVIDENCE_CONTRACT_SCHEMA_VERSION,
    ATTACK_PATH_GRAPH_SCHEMA_VERSION,
    ATTACK_PATH_MODEL_SCHEMA_VERSION,
    ATTACK_PATH_PLANNING_AGENT_CONTROL_VERSION,
    ATTACK_PATH_PLANNING_AGENT_ID,
    ATTACK_PATH_PLANNING_AGENT_NEXT_STAGE,
    ATTACK_PATH_PLANNING_AGENT_REPOSITORY_MIGRATION_LEVEL,
    ATTACK_PATH_PLANNING_AGENT_SCHEMA_VERSION,
    ATTACK_PATH_PLANNING_CAPABILITY_ID,
    ATTACK_PATH_PLANNING_OUTPUT_SCHEMA_VERSION,
    ATTACK_PATH_PLANNING_RUN_REQUEST_SCHEMA_VERSION,
    ATTACK_PATH_PROVENANCE_SCHEMA_VERSION,
    ATTACK_PATH_RANKING_POLICY,
    ATTACK_PATH_RANKING_SCHEMA_VERSION,
    ATTACK_PATH_STAGE_SEQUENCE,
    AttackPathPlanningAgentConflict,
    AttackPathPlanningAgentIntegrityError,
    AttackPathPlanningAgentRepository,
    AttackPathPlanningAgentService,
    AttackPathPlanningAgentValidationError,
    canonical_attack_path_planning_agent_contract,
    deterministic_attack_path_planning_run_id,
    normalize_attack_path_planning_run_request,
    verify_attack_path_graph,
    verify_attack_path_planning_agent_contract,
    verify_attack_path_planning_evidence_bundle,
    verify_attack_path_planning_output,
    verify_candidate_attack_path,
    verify_candidate_path_ranking,
)
from pentest_subsystem.vulnerability_hypothesis import canonical_vulnerability_hypothesis_agent_contract
from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import materialize
from tests.test_stage5_1_full_agentic_pentest_workflow_orchestrator import start_payload
from tests.test_stage5_2_reconnaissance_agent import recon_request
from tests.test_stage5_3_enumeration_agent import enumeration_request
from tests.test_stage5_4_vulnerability_hypothesis_agent import hypothesis_request, knowledge_item

CONTROL = "stage5.5-attack-path-planning-agent"
SERVER_VERSION = "APTSPentestSubsystem/5.5"


def attack_path_request(boundary: dict, hypothesis_run: dict, suffix: str = "stage55", *, max_paths: int = 25) -> dict:
    return {
        "schema_version": ATTACK_PATH_PLANNING_RUN_REQUEST_SCHEMA_VERSION,
        "request_id": f"apathreq-{suffix}",
        "idempotency_key": f"idem-apathreq-{suffix}",
        "actor": "stage5.5-pytest",
        "boundary": deepcopy(boundary),
        "hypothesis_context": {
            "vulnerability_hypothesis_run_id": hypothesis_run["vulnerability_hypothesis_run_id"],
            "output_sha256": hypothesis_run["output"]["integrity"]["canonical_sha256"],
            "evidence_bundle_sha256": hypothesis_run["evidence_bundle"]["integrity"]["canonical_sha256"],
        },
        "planning_preferences": {
            "max_candidate_paths": max_paths,
            "ranking_policy": ATTACK_PATH_RANKING_POLICY,
        },
        "metadata": {"test": suffix},
    }


def _start_repo(tmp_path: Path, suffix: str = "stage55", *, match: bool = True, knowledge_items: list[dict] | None = None):
    repo = AttackPathPlanningAgentRepository(tmp_path / "pentest.db")
    boundary, _, task, _, _ = materialize(repo)
    orch, lifecycle, transitions, created = repo.start_orchestration(task["pentest_task_id"], start_payload(suffix))
    assert created is True
    recon, recon_created = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, suffix))
    assert recon_created is True
    enum, enum_created = repo.run_enumeration(
        orch["orchestration_id"], enumeration_request(boundary, task, recon, suffix, proposals=False)
    )
    assert enum_created is True
    hpayload = hypothesis_request(boundary, enum, suffix, match=match)
    if knowledge_items is not None:
        hpayload["knowledge_items"] = deepcopy(knowledge_items)
    hyp, hyp_created = repo.run_vulnerability_hypothesis(orch["orchestration_id"], hpayload)
    assert hyp_created is True
    return repo, boundary, task, repo.get_orchestration(orch["orchestration_id"]), recon, enum, hyp, lifecycle, transitions


def _start_server(tmp_path: Path):
    service = AttackPathPlanningAgentService(AttackPathPlanningAgentRepository(tmp_path / "pentest.db"))
    handler = type("IsolatedStage55Handler", (PentestSubsystemStage55Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, service, f"http://127.0.0.1:{server.server_address[1]}"


def _get(url: str):
    with urlopen_local_with_retry(url, timeout=5) as response:
        return response.status, dict(response.headers), json.loads(response.read().decode())


def _post(url: str, payload: dict):
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen_local_with_retry(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_01_contract_binds_stage54_migration12_and_roadmap_deliverables():
    contract = canonical_attack_path_planning_agent_contract()
    predecessor = canonical_vulnerability_hypothesis_agent_contract()
    assert contract["control_version"] == CONTROL == ATTACK_PATH_PLANNING_AGENT_CONTROL_VERSION
    assert contract["schema_version"] == ATTACK_PATH_PLANNING_AGENT_SCHEMA_VERSION
    assert contract["predecessor"]["control"] == "stage5.4-vulnerability-hypothesis-agent"
    assert contract["predecessor"]["contract_sha256"] == predecessor["integrity"]["canonical_sha256"]
    assert contract["repository"]["migration_level"] == ATTACK_PATH_PLANNING_AGENT_REPOSITORY_MIGRATION_LEVEL == 12
    assert contract["deliverables"] == {"attack_path_graph": True, "candidate_path_ranking": True, "path_provenance": True}
    assert contract["next_stage"] == ATTACK_PATH_PLANNING_AGENT_NEXT_STAGE == "5.6"


def test_02_contract_is_sha_bound_and_tamper_fails_closed():
    contract = canonical_attack_path_planning_agent_contract()
    assert verify_attack_path_planning_agent_contract(contract)
    forged = deepcopy(contract)
    forged["runtime"]["validation_execution_enabled"] = True
    assert not verify_attack_path_planning_agent_contract(forged)


def test_03_specialist_is_planning_only_and_has_no_execution_authority():
    contract = canonical_attack_path_planning_agent_contract()
    assert contract["specialist"]["agent_id"] == ATTACK_PATH_PLANNING_AGENT_ID
    assert contract["specialist"]["capability_id"] == ATTACK_PATH_PLANNING_CAPABILITY_ID
    assert contract["specialist"]["execution_authority"] is False
    assert contract["runtime"]["caller_supplied_executable_steps_enabled"] is False
    assert contract["runtime"]["validation_execution_enabled"] is False
    assert contract["runtime"]["execution_request_creation_enabled"] is False
    assert contract["runtime"]["tool_invocation_enabled"] is False
    assert contract["runtime"]["external_network_io_enabled"] is False
    assert contract["runtime"]["controlled_execution_stage"] == "6"


def test_04_run_request_is_strict_and_rejects_raw_attack_steps(tmp_path: Path):
    _, boundary, _, _, _, _, hyp, _, _ = _start_repo(tmp_path, "normalize55")
    payload = attack_path_request(boundary, hyp, "normalize55")
    normalized = normalize_attack_path_planning_run_request(payload)
    assert normalized["request_id"] == "apathreq-normalize55"
    for field, value in (
        ("command", "exploit target"),
        ("attack_steps", ["do something"]),
        ("payload", "opaque-bytes"),
        ("tool_parameters", {"target": "lab-a.internal"}),
    ):
        bad = deepcopy(payload)
        bad[field] = value
        with pytest.raises(AttackPathPlanningAgentValidationError):
            normalize_attack_path_planning_run_request(bad)


def test_05_run_identity_is_deterministic_per_orchestration():
    orch = "paorch-stage55-deterministic"
    one = deterministic_attack_path_planning_run_id(orch)
    two = deterministic_attack_path_planning_run_id(orch)
    assert one == two and one.startswith("apathrun-")
    assert one != deterministic_attack_path_planning_run_id(orch + "-other")


def test_06_repository_migrates_to_level12_and_creates_attack_path_store(tmp_path: Path):
    repo = AttackPathPlanningAgentRepository(tmp_path / "pentest.db")
    assert repo.migration_level() == 12
    with sqlite3.connect(repo.sqlite_path) as conn:
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
    assert "pentest_attack_path_planning_runs" in tables
    assert "pentest_vulnerability_hypothesis_runs" in tables


def test_07_attack_path_requires_exact_authoritative_stage54_context(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "predecessor55")
    payload = attack_path_request(boundary, hyp, "predecessor55")
    payload["hypothesis_context"]["output_sha256"] = "0" * 64
    with pytest.raises(AttackPathPlanningAgentConflict):
        repo.run_attack_path_planning(orch["orchestration_id"], payload)


def test_08_candidate_path_contains_four_canonical_conditional_stages(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "stages55")
    run, created = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "stages55"))
    assert created is True
    path = run["output"]["candidate_paths"][0]
    assert path["stage_sequence"] == list(ATTACK_PATH_STAGE_SEQUENCE)
    assert [n["stage"] for n in path["nodes"]] == list(ATTACK_PATH_STAGE_SEQUENCE)
    assert len(path["edges"]) == 3
    assert all(edge["relation"] == "CONDITIONALLY_PRECEDES" for edge in path["edges"])
    assert verify_candidate_attack_path(path)


def test_09_initial_access_stage_is_bound_to_unvalidated_stage54_hypothesis(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "initial55")
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "initial55"))
    path = run["output"]["candidate_paths"][0]
    first = path["nodes"][0]
    source = hyp["output"]["vulnerability_hypotheses"][0]
    assert first["stage"] == "INITIAL_ACCESS"
    assert first["state"] == "HYPOTHESIS_REQUIRES_VALIDATION"
    assert first["basis"]["hypothesis_id"] == source["hypothesis_id"]
    assert path["source_hypothesis"]["validation_status"] == "UNVALIDATED"
    assert path["semantics"]["reachability_confirmed"] is False


def test_10_path_provenance_binds_hypothesis_knowledge_and_supporting_evidence(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "provenance55")
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "provenance55"))
    path = run["output"]["candidate_paths"][0]
    source = hyp["output"]["vulnerability_hypotheses"][0]
    provenance = path["provenance"]
    assert provenance["schema_version"] == ATTACK_PATH_PROVENANCE_SCHEMA_VERSION
    assert provenance["hypothesis_id"] == source["hypothesis_id"]
    assert provenance["hypothesis_ref"] == source["lineage"]["hypothesis_ref"]
    assert provenance["knowledge"]["knowledge_id"] == source["knowledge"]["knowledge_id"]
    assert provenance["supporting_evidence_refs"] == source["correlation"]["supporting_evidence_refs"]
    assert len(provenance["integrity"]["canonical_sha256"]) == 64


def test_11_attack_path_graph_is_sha_bound_and_contains_only_selected_paths(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "graph55")
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "graph55"))
    graph = run["output"]["attack_path_graph"]
    assert graph["schema_version"] == ATTACK_PATH_GRAPH_SCHEMA_VERSION
    assert len(graph["candidate_paths"]) == 1
    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) == 3
    assert graph["semantics"]["confirmed_attack_route"] is False
    assert graph["semantics"]["execution_performed"] is False
    assert verify_attack_path_graph(graph)


def test_12_candidate_ranking_is_validation_priority_not_exploit_probability(tmp_path: Path):
    k1 = knowledge_item("rank-high55"); k1["confidence"] = 0.9; k1["required_validation"]["estimated_impact"] = "LOW"
    k2 = knowledge_item("rank-low55"); k2["confidence"] = 0.4; k2["required_validation"]["estimated_impact"] = "HIGH"
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "rank55", knowledge_items=[k2, k1])
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "rank55"))
    ranking = run["output"]["candidate_path_ranking"]
    assert ranking["schema_version"] == ATTACK_PATH_RANKING_SCHEMA_VERSION
    assert ranking["ranking_policy"] == ATTACK_PATH_RANKING_POLICY
    assert ranking["ranked_paths"][0]["hypothesis_confidence"] >= ranking["ranked_paths"][1]["hypothesis_confidence"]
    assert ranking["semantics"]["ranking_is_exploit_success_probability"] is False
    assert ranking["semantics"]["ranking_is_validation_priority_heuristic"] is True
    assert verify_candidate_path_ranking(ranking)


def test_13_max_candidate_paths_deterministically_limits_graph_and_output(tmp_path: Path):
    k1 = knowledge_item("limit-a55")
    k2 = knowledge_item("limit-b55"); k2["confidence"] = 0.71
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "limit55", knowledge_items=[k1, k2])
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "limit55", max_paths=1))
    assert len(run["output"]["candidate_paths"]) == 1
    assert len(run["output"]["attack_path_graph"]["candidate_paths"]) == 1
    assert len(run["output"]["candidate_path_ranking"]["ranked_paths"]) == 1


def test_14_zero_hypotheses_produce_empty_graph_and_ranking_without_fabrication(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "empty55", match=False)
    assert hyp["output"]["vulnerability_hypotheses"] == []
    run, created = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "empty55"))
    assert created is True
    assert run["output"]["candidate_paths"] == []
    assert run["output"]["attack_path_graph"]["nodes"] == []
    assert run["output"]["candidate_path_ranking"]["ranked_paths"] == []
    assert run["output"]["path_provenance"] == []


def test_15_output_and_evidence_bundle_are_integrity_bound(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "integrity55")
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "integrity55"))
    assert run["output"]["schema_version"] == ATTACK_PATH_PLANNING_OUTPUT_SCHEMA_VERSION
    assert run["evidence_bundle"]["schema_version"] == ATTACK_PATH_EVIDENCE_CONTRACT_SCHEMA_VERSION
    assert verify_attack_path_planning_output(run["output"])
    assert verify_attack_path_planning_evidence_bundle(run["evidence_bundle"])


def test_16_planner_never_materializes_finding_action_result_or_execution_request(tmp_path: Path):
    repo, boundary, task, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "noexec55")
    with sqlite3.connect(repo.sqlite_path) as conn:
        before = dict(conn.execute(
            "select record_type, count(*) from pentest_lineage_objects where pentest_task_id=? group by record_type",
            (task["pentest_task_id"],),
        ).fetchall())

    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "noexec55"))
    assert run["output"]["semantics"]["validation_executed"] is False
    assert run["output"]["semantics"]["finding_created"] is False
    assert run["output"]["semantics"]["execution_request_created"] is False

    with sqlite3.connect(repo.sqlite_path) as conn:
        after = dict(conn.execute(
            "select record_type, count(*) from pentest_lineage_objects where pentest_task_id=? group by record_type",
            (task["pentest_task_id"],),
        ).fetchall())

    # Stage 5.5 is planning-only. Earlier stages may already have lineage objects
    # such as ACTION_PROPOSAL, so assert this planner introduces no executable
    # or finding-side lineage records rather than assuming the predecessor count is zero.
    for record_type in ("HYPOTHESIS", "FINDING", "ACTION_PROPOSAL", "ACTION_RESULT"):
        assert after.get(record_type, 0) == before.get(record_type, 0)


def test_17_exact_replay_is_idempotent_and_does_not_duplicate_progress(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "replay55")
    payload = attack_path_request(boundary, hyp, "replay55")
    first, c1 = repo.run_attack_path_planning(orch["orchestration_id"], payload)
    second, c2 = repo.run_attack_path_planning(orch["orchestration_id"], payload)
    assert c1 is True and c2 is False
    assert first["attack_path_planning_run_id"] == second["attack_path_planning_run_id"]
    with sqlite3.connect(repo.sqlite_path) as conn:
        assert conn.execute("select count(*) from pentest_attack_path_planning_runs").fetchone()[0] == 1
        assert conn.execute("select count(*) from pentest_agentic_progress_records").fetchone()[0] == 4


def test_18_changed_request_after_completed_run_conflicts(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "conflict55")
    payload = attack_path_request(boundary, hyp, "conflict55")
    repo.run_attack_path_planning(orch["orchestration_id"], payload)
    changed = deepcopy(payload)
    changed["planning_preferences"]["max_candidate_paths"] = 1
    with pytest.raises(AttackPathPlanningAgentConflict):
        repo.run_attack_path_planning(orch["orchestration_id"], changed)


def test_19_successful_handoff_releases_stage56_validation_subtask(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "handoff55")
    repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "handoff55"))
    updated = repo.get_orchestration(orch["orchestration_id"])
    assert updated is not None
    assert updated["task_graph"]["nodes"][3]["capability_id"] == "attack_path_analysis"
    assert updated["task_graph"]["nodes"][3]["status"] == "SUCCEEDED"
    assert updated["task_graph"]["nodes"][4]["capability_id"] == "validation"
    assert updated["task_graph"]["nodes"][4]["status"] == "READY"


def test_20_restart_preserves_attack_path_run_and_integrity(tmp_path: Path):
    path = tmp_path / "pentest.db"
    repo = AttackPathPlanningAgentRepository(path)
    boundary, _, task, _, _ = materialize(repo)
    orch, _, _, _ = repo.start_orchestration(task["pentest_task_id"], start_payload("restart55"))
    recon, _ = repo.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "restart55"))
    enum, _ = repo.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "restart55", proposals=False))
    hyp, _ = repo.run_vulnerability_hypothesis(orch["orchestration_id"], hypothesis_request(boundary, enum, "restart55"))
    first, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "restart55"))
    repo2 = AttackPathPlanningAgentRepository(path)
    second = repo2.get_attack_path_planning_run(first["attack_path_planning_run_id"])
    assert second is not None
    assert second["output"]["integrity"] == first["output"]["integrity"]
    assert repo2.migration_level() == 12


def test_21_persisted_attack_path_output_tamper_fails_integrity_check(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "tamper55")
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "tamper55"))
    with sqlite3.connect(repo.sqlite_path) as conn:
        row = conn.execute(
            "select output_json from pentest_attack_path_planning_runs where attack_path_planning_run_id=?",
            (run["attack_path_planning_run_id"],),
        ).fetchone()
        output = json.loads(row[0])
        output["semantics"]["planner_executes_actions"] = True
        conn.execute(
            "update pentest_attack_path_planning_runs set output_json=? where attack_path_planning_run_id=?",
            (json.dumps(output, sort_keys=True), run["attack_path_planning_run_id"]),
        )
    with pytest.raises(AttackPathPlanningAgentIntegrityError):
        repo.get_attack_path_planning_run(run["attack_path_planning_run_id"])


def test_22_health_activates_stage55_and_preserves_non_execution_boundary(tmp_path: Path):
    service = AttackPathPlanningAgentService(AttackPathPlanningAgentRepository(tmp_path / "pentest.db"))
    health = service.health()
    assert health["control_version"] == CONTROL
    assert health["pentest_repository_migration_level"] == 12
    assert health["stage5_5_attack_path_planning_agent_enabled"] is True
    assert health["stage5_5_attack_path_graph_enabled"] is True
    assert health["stage5_5_candidate_path_ranking_enabled"] is True
    assert health["stage5_5_path_provenance_enabled"] is True
    assert health["stage5_5_caller_supplied_executable_steps_enabled"] is False
    assert health["stage5_5_validation_execution_enabled"] is False
    assert health["stage5_5_execution_request_creation_enabled"] is False
    assert health["stage5_5_tool_invocation_enabled"] is False
    assert health["stage5_5_target_actuation"] is False
    assert health["stage5_5_next_stage"] == "5.6"


def test_23_http_contract_run_get_list_and_handoff(tmp_path: Path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        boundary, _, task, _, _ = materialize(service.repository)
        orch, _, _, _ = service.repository.start_orchestration(task["pentest_task_id"], start_payload("http55"))
        recon, _ = service.repository.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "http55"))
        enum, _ = service.repository.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "http55", proposals=False))
        hyp, _ = service.repository.run_vulnerability_hypothesis(orch["orchestration_id"], hypothesis_request(boundary, enum, "http55"))
        status, headers, health = _get(base + "/health")
        assert status == 200 and SERVER_VERSION in headers["Server"] and health["control_version"] == CONTROL
        status, _, contract = _get(base + "/api/pentest/attack-path-planning-agent-contract")
        assert status == 200 and contract["control_version"] == CONTROL
        status, result = _post(
            base + f"/api/pentest/agentic-orchestrations/{orch['orchestration_id']}/attack-path-planning/run",
            attack_path_request(boundary, hyp, "http55"),
        )
        assert status == 201 and result["created"] is True and result["validation_executed"] is False
        run_id = result["run"]["attack_path_planning_run_id"]
        status, _, fetched = _get(base + f"/api/pentest/attack-path-planning-runs/{run_id}")
        assert status == 200 and fetched["run"]["attack_path_planning_run_id"] == run_id
        status, _, listed = _get(base + "/api/pentest/attack-path-planning-runs?limit=10")
        assert status == 200 and listed["count"] == 1
        assert result["orchestration"]["task_graph"]["nodes"][4]["status"] == "READY"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_24_http_execution_dispatch_remains_rejected_for_stage55(tmp_path: Path):
    server, thread, _, base = _start_server(tmp_path)
    try:
        status, rejected = _post(base + "/api/execution/dispatches", {})
        assert status == 409
        assert rejected["error_code"] == "STAGE5_5_CONTROLLED_EXECUTION_NOT_ENABLED"
        assert rejected["attack_path_planning_agent_enabled"] is True
        assert rejected["validation_executed"] is False
        assert rejected["execution_request_created"] is False
        assert rejected["execution_started"] is False
        assert rejected["tool_invocation_performed"] is False
        assert rejected["target_actuation"] is False
        assert rejected["next_stage"] == "5.6"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_25_http_attack_path_analysis_alias_is_supported(tmp_path: Path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        boundary, _, task, _, _ = materialize(service.repository)
        orch, _, _, _ = service.repository.start_orchestration(task["pentest_task_id"], start_payload("alias55"))
        recon, _ = service.repository.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "alias55"))
        enum, _ = service.repository.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "alias55", proposals=False))
        hyp, _ = service.repository.run_vulnerability_hypothesis(orch["orchestration_id"], hypothesis_request(boundary, enum, "alias55"))
        status, result = _post(
            base + f"/api/pentest/agentic-orchestrations/{orch['orchestration_id']}/attack-path-analysis/run",
            attack_path_request(boundary, hyp, "alias55"),
        )
        assert status == 201 and len(result["run"]["output"]["candidate_paths"]) == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_26_http_run_rejects_raw_command_field(tmp_path: Path):
    server, thread, service, base = _start_server(tmp_path)
    try:
        boundary, _, task, _, _ = materialize(service.repository)
        orch, _, _, _ = service.repository.start_orchestration(task["pentest_task_id"], start_payload("http-invalid55"))
        recon, _ = service.repository.run_reconnaissance(orch["orchestration_id"], recon_request(boundary, task, "http-invalid55"))
        enum, _ = service.repository.run_enumeration(orch["orchestration_id"], enumeration_request(boundary, task, recon, "http-invalid55", proposals=False))
        hyp, _ = service.repository.run_vulnerability_hypothesis(orch["orchestration_id"], hypothesis_request(boundary, enum, "http-invalid55"))
        payload = attack_path_request(boundary, hyp, "http-invalid55")
        payload["command"] = "exploit target"
        status, result = _post(
            base + f"/api/pentest/agentic-orchestrations/{orch['orchestration_id']}/attack-path-planning/run",
            payload,
        )
        assert status == 400 and result["status"] == "invalid"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_27_stage54_handler_is_preserved_and_stage55_is_active_successor():
    assert PentestSubsystemStage54Handler.server_version == "APTSPentestSubsystem/5.4"
    assert PentestSubsystemStage55Handler.server_version == SERVER_VERSION
    assert issubclass(PentestSubsystemStage55Handler, PentestSubsystemStage54Handler)


def test_28_contract_and_output_preserve_predecessor_graph_ranking_provenance_and_stage6_boundary(tmp_path: Path):
    repo, boundary, _, orch, _, _, hyp, _, _ = _start_repo(tmp_path, "semantics55")
    run, _ = repo.run_attack_path_planning(orch["orchestration_id"], attack_path_request(boundary, hyp, "semantics55"))
    contract = canonical_attack_path_planning_agent_contract()
    assert contract["graph"]["schema_version"] == ATTACK_PATH_GRAPH_SCHEMA_VERSION
    assert contract["ranking"]["schema_version"] == ATTACK_PATH_RANKING_SCHEMA_VERSION
    assert contract["provenance"]["schema_version"] == ATTACK_PATH_PROVENANCE_SCHEMA_VERSION
    assert run["output"]["predecessor_vulnerability_hypothesis"]["vulnerability_hypothesis_run_id"] == hyp["vulnerability_hypothesis_run_id"]
    assert run["output"]["semantics"]["transform"] == "HYPOTHESIS_TO_CANDIDATE_ATTACK_PATH_GRAPH_RANKING_PROVENANCE"
    assert run["output"]["semantics"]["planner_executes_actions"] is False
    assert run["output"]["semantics"]["paths_are_confirmed"] is False
    assert run["output"]["semantics"]["controlled_execution_deferred_to_stage6"] is True
    assert run["output"]["semantics"]["authorization_minted"] is False
    assert verify_attack_path_planning_output(run["output"])
