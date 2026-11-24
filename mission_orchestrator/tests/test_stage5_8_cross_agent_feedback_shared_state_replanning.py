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
from pentest_subsystem.api_service import PentestSubsystemStage58Handler
from pentest_subsystem.cross_agent_feedback import (
    AGENT_HANDOFF_SCHEMA_VERSION,
    CROSS_AGENT_FEEDBACK_ACTOR_ID,
    CROSS_AGENT_FEEDBACK_CONTROL_VERSION,
    CROSS_AGENT_FEEDBACK_NEXT_STAGE,
    CROSS_AGENT_FEEDBACK_RECORD_SCHEMA_VERSION,
    CROSS_AGENT_FEEDBACK_REPOSITORY_MIGRATION_LEVEL,
    CROSS_AGENT_FEEDBACK_REQUEST_SCHEMA_VERSION,
    LOCAL_REPLAN_DECISION_SCHEMA_VERSION,
    LOCAL_REPLAN_REQUEST_SCHEMA_VERSION,
    SHARED_STATE_SCHEMA_VERSION,
    CrossAgentFeedbackConflict,
    CrossAgentFeedbackRepository,
    CrossAgentFeedbackService,
    CrossAgentFeedbackValidationError,
    canonical_cross_agent_feedback_contract,
    normalize_cross_agent_feedback_request,
    normalize_local_replan_request,
    normalize_shared_state_refresh_request,
    verify_agent_handoff,
    verify_cross_agent_feedback_contract,
    verify_feedback_record,
    verify_local_replan_decision,
    verify_shared_state,
)
from pentest_subsystem.post_exploitation_impact import POST_EXPLOITATION_IMPACT_AGENT_ID
from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import materialize
from tests.test_stage5_1_full_agentic_pentest_workflow_orchestrator import start_payload
from tests.test_stage5_2_reconnaissance_agent import recon_request
from tests.test_stage5_3_enumeration_agent import enumeration_request
from tests.test_stage5_4_vulnerability_hypothesis_agent import hypothesis_request
from tests.test_stage5_5_attack_path_planning_agent import attack_path_request
from tests.test_stage5_6_exploitation_agent import exploitation_request
from tests.test_stage5_7_post_exploitation_impact_agent import impact_request

CONTROL = "stage5.8-cross-agent-feedback-shared-state-replanning"
SERVER_VERSION = "APTSPentestSubsystem/5.8"


def _refresh_payload(suffix: str) -> dict:
    return {
        "request_id": f"pstatereq-{suffix}",
        "idempotency_key": f"idem-state58-{suffix}",
        "actor": CROSS_AGENT_FEEDBACK_ACTOR_ID,
        "metadata": {"test": suffix},
    }


def _feedback_payload(
    state: dict,
    suffix: str,
    *,
    feedback_type: str = "PARTIAL_RESULT",
    subject: str = "impact_analysis",
    source_agent: str = CROSS_AGENT_FEEDBACK_ACTOR_ID,
    refs: list[str] | None = None,
) -> dict:
    return {
        "schema_version": CROSS_AGENT_FEEDBACK_REQUEST_SCHEMA_VERSION,
        "feedback_id": f"pfeedback-{suffix}",
        "idempotency_key": f"idem-feedback58-{suffix}",
        "source_agent_id": source_agent,
        "subject_capability_id": subject,
        "feedback_type": feedback_type,
        "expected_shared_state_id": state["shared_state_id"],
        "expected_shared_state_sha256": state["integrity"]["canonical_sha256"],
        "summary": f"Stage 5.8 feedback {feedback_type} for {subject}.",
        "evidence_refs": list(refs if refs is not None else state["evidence_index"][:1]),
        "metadata": {"test": suffix},
    }


def _replan_payload(state: dict, suffix: str, feedback_ids: list[str]) -> dict:
    return {
        "schema_version": LOCAL_REPLAN_REQUEST_SCHEMA_VERSION,
        "local_replan_id": f"preplan58-{suffix}",
        "idempotency_key": f"idem-replan58-{suffix}",
        "actor": CROSS_AGENT_FEEDBACK_ACTOR_ID,
        "expected_shared_state_id": state["shared_state_id"],
        "expected_shared_state_sha256": state["integrity"]["canonical_sha256"],
        "feedback_ids": feedback_ids,
        "strategy": "EARLIEST_AFFECTED_CAPABILITY",
        "metadata": {"test": suffix},
    }


def _pipeline(tmp_path: Path, suffix: str = "stage58", *, complete: bool = True):
    repo = CrossAgentFeedbackRepository(tmp_path / "pentest.db")
    boundary, _, task, _, _ = materialize(repo)
    orch, _, _, created = repo.start_orchestration(task["pentest_task_id"], start_payload(suffix))
    assert created is True
    oid = orch["orchestration_id"]
    if not complete:
        return repo, boundary, task, oid, {}
    recon, _ = repo.run_reconnaissance(oid, recon_request(boundary, task, suffix))
    enum, _ = repo.run_enumeration(oid, enumeration_request(boundary, task, recon, suffix, proposals=False))
    hyp, _ = repo.run_vulnerability_hypothesis(oid, hypothesis_request(boundary, enum, suffix, match=True))
    path, _ = repo.run_attack_path_planning(oid, attack_path_request(boundary, hyp, suffix))
    exploitation, _ = repo.run_exploitation(oid, exploitation_request(boundary, path, suffix))
    impact, _ = repo.run_post_exploitation_impact(oid, impact_request(boundary, exploitation, suffix))
    return repo, boundary, task, oid, {
        "recon": recon,
        "enum": enum,
        "hyp": hyp,
        "path": path,
        "exploitation": exploitation,
        "impact": impact,
    }


def _full_shared_state(tmp_path: Path, suffix: str = "stage58"):
    repo, boundary, task, oid, runs = _pipeline(tmp_path, suffix)
    row, created = repo.refresh_shared_state(oid, _refresh_payload(suffix))
    assert created is True
    return repo, boundary, task, oid, runs, row, row["shared_state"]


def _start_server(repo: CrossAgentFeedbackRepository):
    service = CrossAgentFeedbackService(repo)
    handler = type("IsolatedStage58Handler", (PentestSubsystemStage58Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, service, f"http://127.0.0.1:{server.server_address[1]}"


def _get(url: str):
    try:
        with urlopen_local_with_retry(url, timeout=5) as response:
            return response.status, dict(response.headers), json.loads(response.read().decode())
    except HTTPError as exc:
        return exc.code, dict(exc.headers), json.loads(exc.read().decode())


def _post(url: str, payload: dict):
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen_local_with_retry(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_01_contract_binds_stage57_migration15_and_roadmap_deliverables():
    contract = canonical_cross_agent_feedback_contract()
    assert contract["control_version"] == CONTROL == CROSS_AGENT_FEEDBACK_CONTROL_VERSION
    assert contract["predecessor"]["control"] == "stage5.7-post-exploitation-impact-agent"
    assert contract["repository"]["migration_level"] == CROSS_AGENT_FEEDBACK_REPOSITORY_MIGRATION_LEVEL == 15
    assert contract["deliverables"] == {
        "shared_state_contract": True,
        "agent_handoff_contract": True,
        "cross_agent_feedback": True,
        "local_replanning": True,
    }
    assert contract["next_stage"] == CROSS_AGENT_FEEDBACK_NEXT_STAGE == "5.9"


def test_02_contract_is_sha_bound_and_tamper_fails_closed():
    contract = canonical_cross_agent_feedback_contract()
    assert verify_cross_agent_feedback_contract(contract)
    forged = deepcopy(contract)
    forged["runtime"]["target_actuation_enabled"] = True
    assert not verify_cross_agent_feedback_contract(forged)


def test_03_stage58_is_coordination_plane_not_execution_plane():
    c = canonical_cross_agent_feedback_contract()
    runtime = c["runtime"]
    assert runtime["shared_state_enabled"] is True
    assert runtime["cross_agent_feedback_enabled"] is True
    assert runtime["local_replanning_enabled"] is True
    assert runtime["local_replan_projection_only"] is True
    assert runtime["active_stage5_1_plan_mutation_enabled"] is False
    assert runtime["specialist_auto_replay_enabled"] is False
    assert runtime["execution_request_creation_enabled"] is False
    assert runtime["tool_invocation_enabled"] is False
    assert runtime["external_network_io_enabled"] is False
    assert runtime["target_actuation_enabled"] is False
    assert runtime["controlled_execution_stage"] == "6"


def test_04_refresh_request_is_strict_and_cannot_inject_shared_facts():
    p = _refresh_payload("strict")
    assert normalize_shared_state_refresh_request(p)["actor"] == CROSS_AGENT_FEEDBACK_ACTOR_ID
    for field in ("validated_facts", "findings", "evidence", "task_ownership", "command", "target"):
        bad = deepcopy(p)
        bad[field] = [] if field != "command" else "opaque"
        with pytest.raises(CrossAgentFeedbackValidationError):
            normalize_shared_state_refresh_request(bad)


def test_05_feedback_and_replan_requests_are_strict(tmp_path: Path):
    _, _, _, _, _, _, state = _full_shared_state(tmp_path, "strict58")
    f = _feedback_payload(state, "strict58")
    assert normalize_cross_agent_feedback_request(f)["feedback_type"] == "PARTIAL_RESULT"
    bad = deepcopy(f); bad["command"] = "opaque"
    with pytest.raises(CrossAgentFeedbackValidationError):
        normalize_cross_agent_feedback_request(bad)
    r = _replan_payload(state, "strict58", [f["feedback_id"]])
    assert normalize_local_replan_request(r)["strategy"] == "EARLIEST_AFFECTED_CAPABILITY"
    bad = deepcopy(r); bad["strategy"] = "MODEL_CHOOSES"
    with pytest.raises(CrossAgentFeedbackValidationError):
        normalize_local_replan_request(bad)


def test_06_repository_migrates_to_15_and_creates_stage58_stores(tmp_path: Path):
    repo = CrossAgentFeedbackRepository(tmp_path / "pentest.db")
    assert repo.migration_level() == 15
    with sqlite3.connect(repo.sqlite_path) as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {
        "pentest_cross_agent_shared_states",
        "pentest_agent_handoffs",
        "pentest_cross_agent_feedback_records",
        "pentest_local_replan_decisions",
    } <= tables


def test_07_partial_pipeline_shared_state_is_valid_and_versioned(tmp_path: Path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "partial58", complete=False)
    row, created = repo.refresh_shared_state(oid, _refresh_payload("partial58"))
    state = row["shared_state"]
    assert created is True
    assert state["schema_version"] == SHARED_STATE_SCHEMA_VERSION
    assert state["state_version"] == 1
    assert state["pentest_state"]["available_specialist_stages"] == []
    assert state["validated_facts"] == []
    assert verify_shared_state(state)


def test_08_shared_state_contains_exact_roadmap_domains_and_is_repository_derived(tmp_path: Path):
    _, _, _, _, _, _, state = _full_shared_state(tmp_path, "domains58")
    for key in ("validated_facts", "mission_context", "pentest_state", "findings", "evidence", "task_ownership"):
        assert key in state
    assert state["pentest_state"]["pipeline_complete"] is True
    assert state["semantics"]["shared_state_is_authoritative_repository_projection"] is True
    assert verify_shared_state(state)


def test_09_validated_facts_are_separated_from_hypotheses_paths_and_provisional_findings(tmp_path: Path):
    _, _, _, _, _, _, state = _full_shared_state(tmp_path, "facts58")
    assert state["validated_facts"]
    fact_types = {x["fact_type"] for x in state["validated_facts"]}
    assert fact_types <= {"RECON_HOST", "RECON_DOMAIN", "RECON_SERVICE", "ENUMERATED_ASSET"}
    assert len(state["findings"]["vulnerability_hypotheses"]) == 1
    assert len(state["findings"]["candidate_attack_paths"]) == 1
    assert len(state["findings"]["exploit_action_proposals"]) == 1
    assert len(state["findings"]["provisional_post_validation_findings"]) == 1
    assert state["semantics"]["hypotheses_are_not_validated_facts"] is True
    assert state["semantics"]["provisional_findings_are_not_confirmed_findings"] is True


def test_10_evidence_and_task_ownership_are_explicit_and_non_executing(tmp_path: Path):
    _, _, _, _, _, _, state = _full_shared_state(tmp_path, "ownership58")
    assert len(state["evidence"]) == 6
    assert len(state["evidence_index"]) >= len(state["evidence"])
    assert len(state["task_ownership"]) == 7
    assert all(x["execution_authority"] is False for x in state["task_ownership"])
    assert all(x["direct_tool_access"] is False for x in state["task_ownership"])


def test_11_shared_state_replays_same_fingerprint_and_new_source_creates_next_version(tmp_path: Path):
    repo, boundary, task, oid, _ = _pipeline(tmp_path, "version58", complete=False)
    row1, created = repo.refresh_shared_state(oid, _refresh_payload("version58-a"))
    row1b, replay_created = repo.refresh_shared_state(oid, _refresh_payload("version58-b"))
    assert created is True and replay_created is False
    assert row1b["shared_state_id"] == row1["shared_state_id"]
    recon, _ = repo.run_reconnaissance(oid, recon_request(boundary, task, "version58"))
    row2, created2 = repo.refresh_shared_state(oid, _refresh_payload("version58-c"))
    assert created2 is True
    assert row2["state_version"] == 2
    assert row2["shared_state_id"] != row1["shared_state_id"]
    assert row2["shared_state"]["pentest_state"]["available_specialist_stages"] == ["5.2"]


def test_12_handoffs_bind_shared_state_source_artifacts_and_ownership(tmp_path: Path):
    repo, _, _, oid, _, row, state = _full_shared_state(tmp_path, "handoff58")
    handoffs = repo.list_handoffs(oid, shared_state_id=state["shared_state_id"])
    assert len(handoffs) == 6
    assert [h["sequence"] for h in handoffs] == list(range(1, 7))
    assert all(h["schema_version"] == AGENT_HANDOFF_SCHEMA_VERSION for h in handoffs)
    assert all(h["shared_state_sha256"] == state["integrity"]["canonical_sha256"] for h in handoffs)
    assert all(verify_agent_handoff(h) for h in handoffs)
    assert handoffs[-1]["to_agent_id"] == CROSS_AGENT_FEEDBACK_ACTOR_ID


def test_13_valid_feedback_is_sha_bound_to_latest_state_and_known_evidence(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "feedback58")
    payload = _feedback_payload(state, "feedback58")
    item, created = repo.record_feedback(oid, payload)
    assert created is True
    record = item["feedback"]
    assert record["schema_version"] == CROSS_AGENT_FEEDBACK_RECORD_SCHEMA_VERSION
    assert record["shared_state_id"] == state["shared_state_id"]
    assert record["evidence_refs"] == payload["evidence_refs"]
    assert verify_feedback_record(record)
    replay, created2 = repo.record_feedback(oid, payload)
    assert created2 is False
    assert replay["feedback"]["integrity"] == record["integrity"]


def test_14_feedback_rejects_unknown_evidence_wrong_owner_and_stale_state(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "reject58")
    bad = _feedback_payload(state, "unknown58", refs=["evidence-not-in-state"])
    with pytest.raises(CrossAgentFeedbackConflict):
        repo.record_feedback(oid, bad)
    bad = _feedback_payload(state, "owner58", subject="impact_analysis", source_agent="PENTEST_ENUMERATION_AGENT")
    with pytest.raises(CrossAgentFeedbackConflict):
        repo.record_feedback(oid, bad)
    stale = _feedback_payload(state, "stale58")
    stale["expected_shared_state_sha256"] = "0" * 64
    with pytest.raises(CrossAgentFeedbackConflict):
        repo.record_feedback(oid, stale)


def test_15_specialist_owner_can_submit_feedback_for_owned_capability(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "ownerok58")
    p = _feedback_payload(
        state,
        "ownerok58",
        feedback_type="INSUFFICIENT_EVIDENCE",
        subject="impact_analysis",
        source_agent=POST_EXPLOITATION_IMPACT_AGENT_ID,
    )
    item, created = repo.record_feedback(oid, p)
    assert created is True
    assert item["feedback"]["subject_owner_agent_id"] == POST_EXPLOITATION_IMPACT_AGENT_ID


def _feedback_and_replan(repo, oid, state, suffix, *, feedback_type, subject="impact_analysis"):
    f = _feedback_payload(state, suffix, feedback_type=feedback_type, subject=subject)
    item, _ = repo.record_feedback(oid, f)
    r = _replan_payload(state, suffix, [item["feedback"]["feedback_id"]])
    decision_row, _ = repo.create_local_replan(oid, r)
    return decision_row["decision"]


def test_16_stale_intelligence_replans_from_reconnaissance_without_mutating_active_plan(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "staleplan58")
    before = deepcopy(repo.get_orchestration(oid))
    d = _feedback_and_replan(repo, oid, state, "staleplan58", feedback_type="STALE_INTELLIGENCE")
    assert d["decision_class"] == "REPLAN_LOCAL"
    assert d["restart_capability_id"] == "reconnaissance"
    assert d["proposed_plan_version"] == before["plan_version"] + 1
    assert d["reopened_capabilities"] == [x["capability_id"] for x in before["task_graph"]["nodes"]]
    assert d["obligations"]["active_stage5_1_plan_mutated"] is False
    after = repo.get_orchestration(oid)
    assert after["plan_version"] == before["plan_version"]
    assert after["task_graph_sha256"] == before["task_graph_sha256"]
    assert verify_local_replan_decision(d)


def test_17_conflicting_evidence_reopens_earliest_subject_and_downstream(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "conflict58")
    d = _feedback_and_replan(repo, oid, state, "conflict58", feedback_type="CONFLICTING_EVIDENCE", subject="vulnerability_analysis")
    assert d["decision_class"] == "REPLAN_LOCAL"
    assert d["restart_capability_id"] == "vulnerability_analysis"
    assert d["preserved_succeeded_capabilities"] == ["reconnaissance", "enumeration"]
    assert d["reopened_capabilities"][0] == "vulnerability_analysis"
    statuses = {n["capability_id"]: n["status"] for n in d["projected_task_graph"]["nodes"]}
    assert statuses["reconnaissance"] == statuses["enumeration"] == "SUCCEEDED"
    assert statuses["vulnerability_analysis"] == "READY"
    assert statuses["impact_analysis"] == "PENDING"


def test_18_insufficient_execution_evidence_is_deferred_to_stage6(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "defer58")
    d = _feedback_and_replan(repo, oid, state, "defer58", feedback_type="INSUFFICIENT_EVIDENCE", subject="impact_analysis")
    assert d["decision_class"] == "DEFER_TO_STAGE6"
    assert d["projected_task_graph"] is None
    assert d["obligations"]["stage6_controlled_execution_required"] is True
    assert d["semantics"]["execution_request_created"] is False


def test_19_scope_or_roe_change_escalates_to_governance(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "scope58")
    d = _feedback_and_replan(repo, oid, state, "scope58", feedback_type="SCOPE_OR_ROE_CHANGE", subject="ORCHESTRATION")
    assert d["decision_class"] == "ESCALATE_GOVERNANCE"
    assert d["obligations"]["governance_revalidation_required"] is True
    assert d["projected_task_graph"] is None


def test_20_no_replan_required_yields_no_change(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "nochange58")
    d = _feedback_and_replan(repo, oid, state, "nochange58", feedback_type="NO_REPLAN_REQUIRED", subject="ORCHESTRATION")
    assert d["decision_class"] == "NO_CHANGE"
    assert d["proposed_plan_version"] is None
    assert d["projected_task_graph"] is None


def test_21_governance_escalation_has_precedence_in_mixed_feedback(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "mixed58")
    f1, _ = repo.record_feedback(oid, _feedback_payload(state, "mixed58-a", feedback_type="PARTIAL_RESULT", subject="impact_analysis"))
    f2, _ = repo.record_feedback(oid, _feedback_payload(state, "mixed58-b", feedback_type="SCOPE_OR_ROE_CHANGE", subject="ORCHESTRATION"))
    p = _replan_payload(state, "mixed58", [f1["feedback"]["feedback_id"], f2["feedback"]["feedback_id"]])
    row, created = repo.create_local_replan(oid, p)
    assert created is True
    assert row["decision"]["decision_class"] == "ESCALATE_GOVERNANCE"
    assert row["decision"]["obligations"]["governance_revalidation_required"] is True


def test_22_local_replan_is_idempotent_sha_bound_and_restart_safe(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "restart58")
    f, _ = repo.record_feedback(oid, _feedback_payload(state, "restart58", feedback_type="PARTIAL_RESULT"))
    p = _replan_payload(state, "restart58", [f["feedback"]["feedback_id"]])
    row, created = repo.create_local_replan(oid, p)
    replay, created2 = repo.create_local_replan(oid, p)
    assert created is True and created2 is False
    assert replay["decision"]["integrity"] == row["decision"]["integrity"]
    reopened = CrossAgentFeedbackRepository(repo.sqlite_path)
    persisted = reopened.get_local_replan(p["local_replan_id"])
    assert persisted is not None
    assert verify_local_replan_decision(persisted["decision"])


def test_23_health_and_http_contract_routes_are_active_and_execution_remains_rejected(tmp_path: Path):
    repo, _, _, oid, _, _, state = _full_shared_state(tmp_path, "http58")
    server, thread, service, base = _start_server(repo)
    try:
        status, headers, health = _get(base + "/health")
        assert status == 200
        assert SERVER_VERSION in headers.get("Server", "")
        assert health["control_version"] == CONTROL
        assert health["pentest_repository_migration_level"] == 15
        assert health["stage5_8_shared_state_enabled"] is True
        assert health["stage5_8_local_replanning_enabled"] is True
        status, _, contract = _get(base + "/api/pentest/cross-agent-feedback-contract")
        assert status == 200 and contract["control_version"] == CONTROL
        status, _, current = _get(base + f"/api/pentest/agentic-orchestrations/{oid}/shared-state")
        assert status == 200 and current["snapshot"]["shared_state_id"] == state["shared_state_id"]
        status, body = _post(base + "/api/execution/dispatches", {"action": "not-accepted"})
        assert status == 409
        assert body["error_code"] == "STAGE5_8_CONTROLLED_EXECUTION_NOT_ENABLED"
        assert body["target_actuation"] is False
        assert body["next_stage"] == "5.9"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_24_http_refresh_feedback_replan_round_trip(tmp_path: Path):
    repo, _, _, oid, _ = _pipeline(tmp_path, "httpflow58")
    server, thread, _, base = _start_server(repo)
    try:
        status, refresh = _post(base + f"/api/pentest/agentic-orchestrations/{oid}/shared-state/refresh", _refresh_payload("httpflow58"))
        assert status == 201
        state = refresh["snapshot"]["shared_state"]
        f = _feedback_payload(state, "httpflow58", feedback_type="PARTIAL_RESULT", subject="impact_analysis")
        status, fb = _post(base + f"/api/pentest/agentic-orchestrations/{oid}/feedback", f)
        assert status == 201 and fb["feedback"]["feedback_type"] == "PARTIAL_RESULT"
        p = _replan_payload(state, "httpflow58", [f["feedback_id"]])
        status, rp = _post(base + f"/api/pentest/agentic-orchestrations/{oid}/local-replan", p)
        assert status == 201
        assert rp["decision"]["decision_class"] == "REPLAN_LOCAL"
        assert rp["active_stage5_1_plan_mutated"] is False
        status, _, handoffs = _get(base + f"/api/pentest/agentic-orchestrations/{oid}/handoffs")
        assert status == 200 and handoffs["count"] == 6
        status, _, feedback = _get(base + f"/api/pentest/agentic-orchestrations/{oid}/feedback")
        assert status == 200 and feedback["count"] == 1
        status, _, replans = _get(base + f"/api/pentest/agentic-orchestrations/{oid}/local-replans")
        assert status == 200 and replans["count"] == 1
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
