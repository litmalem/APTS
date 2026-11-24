from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from execution_subsystem.api_service import ExecutionSubsystemStage61Handler
from execution_subsystem.execution_contract import (
    ACTION_ENVELOPE_HASH_DOMAIN, EXECUTION_REQUEST_CONTRACT_SCHEMA_VERSION,
    EXECUTION_REQUEST_CONTROL_VERSION, EXECUTION_REQUEST_FIELDS,
    EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION, EXECUTION_REQUEST_SCHEMA_VERSION,
    REQUIRED_AUTHORIZATION_CHECKS, REQUEST_SEMANTICS, ExecutionRequestConflict,
    ExecutionRequestIntegrityError, ExecutionRequestValidationError, ExecutionSourceNotFound,
    ExecutionSourceRejected, ExecutionSourceUnavailable, canonical_execution_request_contract,
    canonical_action_envelope_json_schema,
    deterministic_execution_id, execution_request_json_schema, normalize_execution_request,
    normalize_execution_request_intake, seal_execution_request, verify_canonical_action_envelope,
    verify_execution_request, verify_execution_request_contract, with_integrity,
)
from execution_subsystem.proposal_source import PentestProposalSource
from execution_subsystem.request_repository import ExecutionRequestRepository, ExecutionRepositoryError
from execution_subsystem.request_service import ExecutionRequestService
from pentest_subsystem.agentic_pentest_acceptance_gate import canonical_agentic_pentest_acceptance_gate_contract
from pentest_subsystem.governance_bound_e2e import GovernanceBoundE2ERepository
from tests._localhost_http import urlopen_local_with_retry
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline
from tests.test_stage5_6_exploitation_agent import _start_repo, exploitation_request
from tests.test_stage5_4_vulnerability_hypothesis_agent import knowledge_item


def intake_for(run, suffix="stage61"):
    proposal = run["output"]["exploit_action_proposals"][0]
    return {
        "schema_version": EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
        "request_id": "ereq-" + suffix, "idempotency_key": "idem-" + suffix,
        "exploitation_run_id": run["exploitation_run_id"],
        "exploit_action_proposal_id": proposal["exploit_action_proposal_id"],
        "proposal_sha256": proposal["integrity"]["canonical_sha256"],
    }


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("stage61-seed")
    repo, boundary, task, oid, runs = _pipeline(root, "stage61", through_stage="5.6")
    return repo.sqlite_path, boundary, task, oid, runs["5.6"]


@pytest.fixture
def ctx(tmp_path, seed):
    source_path, boundary, task, oid, run = seed
    db = tmp_path / "pentest.db"
    shutil.copy2(source_path, db)
    service = ExecutionRequestService(ExecutionRequestRepository(tmp_path / "execution.db"), PentestProposalSource(db))
    return service, intake_for(run), deepcopy(boundary), deepcopy(task), oid, deepcopy(run)


@contextmanager
def server_for(service):
    handler = type("IsolatedStage61Handler", (ExecutionSubsystemStage61Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def http(url, payload=None, *, raw=None):
    if payload is not None or raw is not None:
        data = raw if raw is not None else json.dumps(payload).encode()
        req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    else:
        req = url
    try:
        with urlopen_local_with_retry(req, timeout=5) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read()), dict(exc.headers)


def request_core(ctx):
    envelope = ctx[0].proposal_source.build_envelope(ctx[1])
    return {k: deepcopy(v) for k, v in envelope["execution_request"].items() if k != "integrity"}


def test_contract_binds_stage5_closure_and_exact_roadmap_deliverables():
    c = canonical_execution_request_contract()
    assert c["control_version"] == EXECUTION_REQUEST_CONTROL_VERSION
    assert c["schema_version"] == EXECUTION_REQUEST_CONTRACT_SCHEMA_VERSION
    assert c["predecessor"]["contract_sha256"] == canonical_agentic_pentest_acceptance_gate_contract()["integrity"]["canonical_sha256"]
    assert c["required_execution_request_fields"] == [
        "execution_id", "mission_id", "task_id", "pentest_id", "proposing_agent",
        "action", "target", "parameters", "evidence_basis", "authorization_requirement",
    ]
    assert c["deliverables"] == {"execution_request_schema": True, "canonical_action_envelope": True}
    assert c["repository"]["migration_level"] == 1
    assert c["predecessor"]["pentest_repository_migration_level"] == 16
    assert c["next_stage"] == "6.2"
    assert verify_execution_request_contract(c)
    c["runtime"]["execution_authorized"] = True
    assert not verify_execution_request_contract(c)
    assert canonical_execution_request_contract()["runtime"]["execution_authorized"] is False


def test_exported_json_schema_matches_published_contract():
    path = Path(__file__).resolve().parents[1] / "execution_subsystem" / "schemas" / "execution_request_v1.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema == execution_request_json_schema()
    assert schema == canonical_execution_request_contract()["execution_request_json_schema"]
    assert set(schema["required"]) == set(EXECUTION_REQUEST_FIELDS) | {"schema_version"}
    assert schema["additionalProperties"] is False
    envelope_path = path.with_name("canonical_action_envelope_v1.schema.json")
    assert json.loads(envelope_path.read_text(encoding="utf-8")) == canonical_action_envelope_json_schema()


def test_request_preserves_upstream_task_agent_target_and_existing_evidence(ctx):
    service, payload, boundary, task, oid, run = ctx
    result = service.create_request(payload)
    env, proposal = result["envelope"], run["output"]["exploit_action_proposals"][0]
    req = env["execution_request"]
    assert result["created"] is True and result["status"] == "AWAITING_AUTHORIZATION"
    assert req["schema_version"] == EXECUTION_REQUEST_SCHEMA_VERSION
    assert req["task_id"] == task["upstream_task_id"] == boundary["task_id"]
    assert env["source_binding"]["pentest_task_id"] == task["pentest_task_id"]
    assert req["mission_id"] == task["mission_id"] and req["pentest_id"] == task["pentest_id"]
    assert req["target"] == proposal["target"]
    assert req["action"]["technique"] == proposal["technique"]
    assert req["proposing_agent"]["agent_id"] == proposal["agent_id"]
    assert req["proposing_agent"]["orchestration_id"] == oid
    assert req["proposing_agent"]["subtask_id"] == run["exploitation_subtask_id"]
    assert sorted(x["evidence_id"] for x in req["evidence_basis"]) == sorted(proposal["evidence_basis"])
    assert req["authorization_requirement"]["required_checks"] == list(REQUIRED_AUTHORIZATION_CHECKS)
    assert req["authorization_requirement"]["revalidation_required"] is True
    assert env["semantics"] == REQUEST_SEMANTICS
    assert verify_execution_request(req) and verify_canonical_action_envelope(env)


def test_deterministic_envelope_and_evidence_order_without_clock_or_randomness(ctx):
    service, payload = ctx[:2]
    one = service.proposal_source.build_envelope(payload)
    two = service.proposal_source.build_envelope(dict(reversed(list(payload.items()))))
    assert one == two
    core = request_core(ctx)
    core["evidence_basis"].reverse()
    assert seal_execution_request(core) == one["execution_request"]
    req = one["execution_request"]
    assert req["execution_id"] == deterministic_execution_id(req["mission_id"], req["task_id"], req["pentest_id"], payload["idempotency_key"])
    assert req["execution_id"] != deterministic_execution_id("mission-gmo-other", req["task_id"], req["pentest_id"], payload["idempotency_key"])


@pytest.mark.parametrize("field", [
    "execution_id", "mission_id", "task_id", "pentest_id", "target", "parameters", "evidence_basis",
    "proposing_agent", "authorization_requirement", "command", "payload", "tool_parameters", "execution_authorized",
])
def test_intake_rejects_caller_owned_actions_identity_or_authorization(ctx, field):
    service, payload = ctx[:2]
    payload[field] = {"command": "opaque"}
    with pytest.raises(ExecutionRequestValidationError):
        service.create_request(payload)
    assert not service.repository.sqlite_path.exists()


@pytest.mark.parametrize("field", list(EXECUTION_REQUEST_FIELDS))
def test_request_rejects_missing_roadmap_fields(ctx, field):
    core = request_core(ctx)
    del core[field]
    with pytest.raises(ExecutionRequestValidationError):
        normalize_execution_request(core)


@pytest.mark.parametrize("case", ["nan", "boolean-version", "blank-target", "duplicate-evidence", "empty-evidence", "nested-command", "missing-check", "disable-revalidation"])
def test_request_rejects_invalid_nested_values_and_relaxed_authorization(ctx, case):
    core = request_core(ctx)
    if case == "nan": core["parameters"]["estimated_impact"] = float("nan")
    if case == "boolean-version": core["authorization_requirement"]["policy_reference"]["policy_version"] = True
    if case == "blank-target": core["target"]["target_value"] = " "
    if case == "duplicate-evidence": core["evidence_basis"].append(deepcopy(core["evidence_basis"][0]))
    if case == "empty-evidence": core["evidence_basis"] = []
    if case == "nested-command": core["parameters"]["command"] = "opaque"
    if case == "missing-check": core["authorization_requirement"]["required_checks"].pop()
    if case == "disable-revalidation": core["authorization_requirement"]["revalidation_required"] = False
    with pytest.raises(ExecutionRequestValidationError):
        seal_execution_request(core)


def test_resigned_envelope_cannot_self_authorize_or_change_execution_identity(ctx):
    env = ctx[0].proposal_source.build_envelope(ctx[1])
    for change in ("status", "semantics", "identity"):
        bad = deepcopy(env)
        if change == "status": bad["status"] = "AUTHORIZED"
        if change == "semantics": bad["semantics"]["execution_authorized"] = True
        if change == "identity":
            core = {k: v for k, v in bad["execution_request"].items() if k != "integrity"}
            core["execution_id"] = "exec-other"
            bad["execution_request"] = seal_execution_request(core)
        bad.pop("integrity")
        assert not verify_canonical_action_envelope(with_integrity(bad, ACTION_ENVELOPE_HASH_DOMAIN))


def test_restart_and_idempotent_replay_preserve_exact_immutable_envelope(ctx):
    service, payload = ctx[:2]
    first = service.create_request(payload)
    restarted = ExecutionRequestService(ExecutionRequestRepository(service.repository.sqlite_path), service.proposal_source)
    replay = restarted.create_request(payload)
    assert replay["created"] is False
    assert replay["stored_at"] == first["stored_at"]
    assert replay["envelope"] == first["envelope"]
    assert restarted.repository.get(first["execution_id"])["envelope"] == first["envelope"]
    assert len(restarted.repository.list_requests()) == 1


@pytest.mark.parametrize("field,value", [("request_id", "ereq-changed"), ("idempotency_key", "idem-changed"), ("proposal_sha256", "a" * 64)])
def test_reusing_request_or_idempotency_identity_with_different_content_conflicts(ctx, field, value):
    service, payload = ctx[:2]
    service.create_request(payload)
    payload[field] = value
    with pytest.raises(ExecutionRequestConflict):
        service.create_request(payload)
    assert len(service.repository.list_requests()) == 1


def test_concurrent_duplicate_intake_creates_one_request(ctx):
    service, payload = ctx[:2]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: service.create_request(payload), range(8)))
    assert sum(x["created"] for x in results) == 1
    assert len({x["execution_id"] for x in results}) == 1
    assert len(service.repository.list_requests()) == 1


def test_pentest_source_reads_leave_database_bytes_and_migration_unchanged(ctx):
    service, payload = ctx[:2]
    path = service.proposal_source.sqlite_path
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert service.health()["pentest_repository_migration_level"] == 16
    service.create_request(payload)
    service.create_request(payload)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert service.proposal_source.migration_level() == 16


def test_missing_or_wrong_migration_source_fails_closed_without_creating_pentest_db(tmp_path, ctx):
    path = tmp_path / "missing" / "pentest.db"
    source = PentestProposalSource(path)
    with pytest.raises(ExecutionSourceUnavailable): source.build_envelope(ctx[1])
    assert not path.exists() and not path.parent.exists()
    service, payload = ctx[:2]
    with sqlite3.connect(service.proposal_source.sqlite_path) as conn:
        conn.execute("UPDATE pentest_repository_meta SET migration_level=17")
    with pytest.raises(ExecutionSourceUnavailable): service.create_request(payload)
    assert service.repository.list_requests() == []


@pytest.mark.parametrize("field,value", [("exploitation_run_id", "xplrun-unknown"), ("exploit_action_proposal_id", "xplprop-unknown")])
def test_unknown_source_identity_is_not_materialized(ctx, field, value):
    service, payload = ctx[:2]
    payload[field] = value
    with pytest.raises(ExecutionSourceNotFound): service.create_request(payload)
    assert service.repository.list_requests() == []


def test_wrong_proposal_hash_is_rejected(ctx):
    service, payload = ctx[:2]
    payload["proposal_sha256"] = "a" * 64
    with pytest.raises(ExecutionRequestIntegrityError): service.create_request(payload)
    assert service.repository.list_requests() == []


@pytest.mark.parametrize("case", ["run-json", "cross-mission", "task-binding", "evidence-json", "evidence-type", "agent-assignment", "governance-json", "predecessor-json"])
def test_persisted_tampering_and_cross_context_references_fail_closed(ctx, case):
    service, payload, _, task, oid, run = ctx
    with sqlite3.connect(service.proposal_source.sqlite_path) as conn:
        if case in {"evidence-json", "evidence-type"}:
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='pentest_lineage_objects'").fetchall():
                conn.execute('DROP TRIGGER "' + row[0] + '"')
        if case == "run-json": conn.execute("UPDATE pentest_exploitation_runs SET output_json='{}'")
        if case == "cross-mission": conn.execute("UPDATE pentest_exploitation_runs SET mission_id='mission-gmo-foreign'")
        if case == "task-binding": conn.execute("UPDATE pentest_tasks SET binding_json='{}'")
        if case == "evidence-json": conn.execute("UPDATE pentest_lineage_objects SET canonical_json='{}' WHERE record_type='EVIDENCE'")
        if case == "evidence-type": conn.execute("UPDATE pentest_lineage_objects SET record_type='ARTIFACT' WHERE record_type='EVIDENCE'")
        if case == "agent-assignment": conn.execute("UPDATE pentest_exploitation_runs SET exploitation_subtask_id=?", (run["validation_subtask_id"],))
        if case == "governance-json": conn.execute("UPDATE pentest_scope_roe_decisions SET decision_json='{}'")
        if case == "predecessor-json": conn.execute("UPDATE pentest_attack_path_planning_runs SET output_json='{}'")
    with pytest.raises(ExecutionRequestIntegrityError): service.create_request(payload)
    assert service.repository.list_requests() == []


def test_real_blocked_stage5_proposal_cannot_create_execution_request(tmp_path):
    item = knowledge_item("blocked-stage61")
    item["required_validation"]["estimated_impact"] = "HIGH"
    repo, boundary, _, orch, _, _, _, apath, _, _ = _start_repo(tmp_path, "blocked-stage61", knowledge_items=[item])
    run, _ = repo.run_exploitation(orch["orchestration_id"], exploitation_request(boundary, apath, "blocked-stage61"))
    assert run["output"]["exploit_action_proposals"][0]["proposal_status"] == "BLOCKED_BY_SCOPE_ROE"
    GovernanceBoundE2ERepository(repo.sqlite_path).initialize()
    service = ExecutionRequestService(ExecutionRequestRepository(tmp_path / "execution.db"), PentestProposalSource(repo.sqlite_path))
    with pytest.raises(ExecutionSourceRejected): service.create_request(intake_for(run, "blocked"))
    assert service.repository.list_requests() == []


def test_real_human_review_proposal_retains_review_requirement(tmp_path, monkeypatch):
    import tests.test_stage4_6_pentest_workflow_orchestrator_skeleton as wf
    boundary = wf.sample_boundary()
    boundary["roe"]["human_approval_required_for"] = ["VULNERABILITY_VALIDATION"]
    monkeypatch.setattr(wf, "sample_boundary", lambda: deepcopy(boundary))
    repo, _, _, _, runs = _pipeline(tmp_path, "review-stage61", through_stage="5.6")
    run = runs["5.6"]
    assert run["output"]["exploit_action_proposals"][0]["proposal_status"] == "AWAITING_HUMAN_REVIEW"
    service = ExecutionRequestService(ExecutionRequestRepository(tmp_path / "execution.db"), PentestProposalSource(repo.sqlite_path))
    req = service.create_request(intake_for(run, "review"))["envelope"]["execution_request"]
    assert req["authorization_requirement"]["human_review_required"] is True
    assert req["authorization_requirement"]["revalidation_required"] is True


def test_terminated_orchestration_cannot_propose_a_new_request(ctx):
    service, payload, _, _, oid = ctx[:5]
    with sqlite3.connect(service.proposal_source.sqlite_path) as conn:
        conn.execute("UPDATE pentest_agentic_orchestrations SET orchestration_status='TERMINATED' WHERE orchestration_id=?", (oid,))
    with pytest.raises(ExecutionSourceRejected): service.create_request(payload)


def test_append_only_triggers_prevent_update_and_delete(ctx):
    service, payload = ctx[:2]
    item = service.create_request(payload)
    for statement in ("UPDATE execution_requests SET status='AUTHORIZED'", "DELETE FROM execution_requests"):
        with sqlite3.connect(service.repository.sqlite_path) as conn:
            with pytest.raises(sqlite3.IntegrityError): conn.execute(statement)
    assert service.repository.get(item["execution_id"]) is not None


def test_read_detects_persisted_envelope_or_index_tampering(ctx):
    service, payload = ctx[:2]
    item = service.create_request(payload)
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_requests_no_update")
        conn.execute("UPDATE execution_requests SET mission_id='mission-gmo-forged'")
    with pytest.raises(ExecutionRequestIntegrityError): service.repository.get(item["execution_id"])
    with pytest.raises(ExecutionRequestIntegrityError): service.repository.list_requests()


def test_future_execution_migration_is_rejected_without_downgrade(ctx):
    service = ctx[0]
    service.repository.initialize()
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("UPDATE execution_repository_meta SET migration_level=2")
    before = service.repository.sqlite_path.read_bytes()
    restarted = ExecutionRequestRepository(service.repository.sqlite_path)
    with pytest.raises(ExecutionRepositoryError): restarted.initialize()
    assert service.repository.sqlite_path.read_bytes() == before


def test_same_database_and_hardlink_alias_are_forbidden(ctx, tmp_path):
    source = ctx[0].proposal_source
    with pytest.raises(ExecutionRequestValidationError): ExecutionRequestService(ExecutionRequestRepository(source.sqlite_path), source)
    alias = tmp_path / "alias.db"
    os.link(source.sqlite_path, alias)
    with pytest.raises(ExecutionRequestValidationError): ExecutionRequestService(ExecutionRequestRepository(alias), source)
    foreign = tmp_path / "global-mission.db"
    with sqlite3.connect(foreign) as conn:
        conn.execute("CREATE TABLE global_missions (mission_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO global_missions VALUES ('mission-gmo-preserve')")
    before = foreign.read_bytes()
    with pytest.raises(ExecutionRepositoryError): ExecutionRequestRepository(foreign).initialize()
    assert foreign.read_bytes() == before


def test_list_filters_and_unknown_request_do_not_widen_context(ctx):
    service, payload, _, task = ctx[:4]
    first = service.create_request(payload)
    second_payload = {**payload, "request_id": "ereq-second", "idempotency_key": "idem-second"}
    service.create_request(second_payload)
    assert len(service.repository.list_requests(mission_id=task["mission_id"], task_id=task["upstream_task_id"], pentest_id=task["pentest_id"])) == 2
    assert len(service.repository.list_requests(limit=1)) == 1
    assert service.repository.list_requests(mission_id="mission-gmo-other") == []
    assert service.repository.get("exec-unknown") is None
    with pytest.raises(ExecutionRequestValidationError): service.repository.list_requests(limit=True)


def test_api_health_contract_create_replay_read_and_list(ctx):
    service, payload = ctx[:2]
    with server_for(service) as base:
        status, health, headers = http(base + "/health")
        assert status == 200 and "APTSExecutionSubsystem/6.1" in headers["Server"]
        assert health["control_version"] == EXECUTION_REQUEST_CONTROL_VERSION
        assert health["execution_repository_migration_level"] == 1
        assert health["pentest_repository_migration_level"] == 16
        assert health["execution_authorized"] is False
        for route in ("/api/execution/execution-request-contract", "/api/contracts/canonical-execution-request"):
            status, contract, _ = http(base + route)
            assert status == 200 and verify_execution_request_contract(contract["contract"])
        status, created, _ = http(base + "/api/execution/requests", payload)
        assert status == 201 and created["created"] is True
        status, replay, _ = http(base + "/api/execution/requests", payload)
        assert status == 200 and replay["created"] is False and replay["envelope"] == created["envelope"]
        status, read, _ = http(base + "/api/execution/requests/" + created["execution_id"])
        assert status == 200 and read["envelope"] == created["envelope"]
        status, listed, _ = http(base + "/api/execution/requests")
        assert status == 200 and listed["count"] == 1
        assert http(base + "/api/execution/requests/exec-unknown")[0] == 404
        assert http(base + "/api/execution/requests?limit=0")[0] == 400
        assert http(base + "/api/execution/requests?limit=1&limit=2")[0] == 400


@pytest.mark.parametrize("route", ["dispatches", "authorizations", "results", "tool-invocations"])
def test_api_execution_authorization_results_and_raw_tool_paths_remain_closed(ctx, route):
    with server_for(ctx[0]) as base:
        status, response, _ = http(base + "/api/execution/" + route, {})
        assert status == 409
        assert response["error_code"] == "STAGE6_1_AUTHORIZATION_AND_EXECUTION_NOT_ENABLED"
        assert all(response[key] is False for key in REQUEST_SEMANTICS)
    assert not ctx[0].repository.sqlite_path.exists()


@pytest.mark.parametrize("raw", [b'{"request_id":"ereq-a","request_id":"ereq-b"}', b'{"x":NaN}', b'[]', b'{', b'\xff'])
def test_api_rejects_ambiguous_or_malformed_json(ctx, raw):
    with server_for(ctx[0]) as base:
        assert http(base + "/api/execution/requests", raw=raw)[0] == 400
    assert not ctx[0].repository.sqlite_path.exists()


def test_api_reports_source_integrity_and_availability_failures(ctx, tmp_path):
    service, payload = ctx[:2]
    with server_for(service) as base:
        assert http(base + "/api/execution/requests", {**payload, "proposal_sha256": "a" * 64})[0] == 409
        assert http(base + "/api/execution/requests", {**payload, "exploitation_run_id": "xplrun-unknown"})[0] == 404
        assert http(base + "/api/execution/requests", {**payload, "execution_authorized": True})[0] == 400
    missing = ExecutionRequestService(ExecutionRequestRepository(tmp_path / "isolated-exec.db"), PentestProposalSource(tmp_path / "absent-pentest.db"))
    with server_for(missing) as base:
        status, health, _ = http(base + "/health")
        assert status == 503 and health["proposal_source_ready"] is False
        assert http(base + "/api/execution/requests", payload)[0] == 503
    assert not missing.proposal_source.sqlite_path.exists()
