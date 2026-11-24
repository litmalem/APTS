from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from http.server import ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import shutil
import sqlite3
from threading import Thread
import time
from uuid import uuid4

import pytest

from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.evidence_api import ExecutionSubsystemStage66Handler, serve
from execution_subsystem.evidence_collector import safe_worker_messages
from execution_subsystem.evidence_contract import (EVIDENCE_CONTROL_VERSION, KINDS, MAX_ARTIFACT_BYTES,
    bytes_sha256, canonical_evidence_contract, verify_artifact, verify_evidence, verify_evidence_contract)
from execution_subsystem.evidence_repository import ExecutionEvidenceRepository
from execution_subsystem.evidence_service import ExecutionEvidenceService
from execution_subsystem.execution_result_contract import build_recon_execution_result, verify_recon_execution_result
from execution_subsystem.execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json)
from execution_subsystem.governance_client import ExecutionGovernanceClient
from execution_subsystem.request_repository import ExecutionRepositoryError, ExecutionRequestRepository
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.adapter_repository import ExecutionAdapterRepository
from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
from execution_subsystem.runtime_service import ExecutionRuntimeService
from execution_subsystem.runtime_contract import START_SCHEMA, canonical_runtime_contract
from tests.test_stage6_1_canonical_execution_request_contract import intake_for, http
from tests.test_stage6_2_authoritative_execution_authorization import NOW
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority, authority_server
from tests.test_stage6_4_authorized_tool_adapters_sandboxing import adapter_seed, target_server
from tests.test_stage6_5_execution_runtime_control import wait_for, cancellation, retry_payload


@pytest.fixture
def ctx(tmp_path, adapter_seed, target_server):
    pdb, mdb, run = adapter_seed
    pentest, mission = tmp_path / "pentest.db", tmp_path / "mission.db"
    shutil.copy2(pdb, pentest)
    shutil.copy2(mdb, mission)
    authority = UniqueAuthority()
    now = [NOW]
    service = ExecutionEvidenceService(ExecutionEvidenceRepository(tmp_path / "execution.db"),
        ExecutionAuthorizationProposalSource(pentest), MissionAuthorizationSource(mission), authority,
        clock=lambda:now[0])
    request = service.create_request(intake_for(run, "stage66"))
    intake = {"schema_version": START_SCHEMA, "invocation_request_id": "toolreq-stage66",
        "idempotency_key": "idem-stage66", "execution_id": request["execution_id"],
        "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"], "requested_by": "stage66-test"}
    target_server[2].update({"sleep":0, "redirect":False})
    target_server[1].clear()
    try:
        yield service, intake, authority, request, target_server, now
    finally:
        service.close()
        target_server[2].update({"sleep":0, "redirect":False})


def completed(ctx):
    service, intake = ctx[:2]
    attempt = service.start_execution(intake)
    item = wait_for(service, attempt["attempt_id"])
    capture = service.get_evidence(attempt["attempt_id"])
    return item, capture


@contextmanager
def server_for(service):
    handler = type("TestStage66Handler", (ExecutionSubsystemStage66Handler,), {"service":service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_native_loopback_capture_exact_terminal_manifest_and_blobs(ctx):
    item, capture = completed(ctx)
    assert item["state"] == "SUCCEEDED", ctx[0]._failures
    manifest = capture["manifest"]
    assert capture["sealed"] and capture["status"] == "CAPTURED" and verify_evidence(manifest)
    assert {a["kind"] for a in capture["artifacts"]} == set(KINDS)
    assert manifest["terminal_event_sha256"] == item["head_sha256"]
    assert manifest["adapter_result_sha256"] == item["invocation"]["result"]["integrity"]["canonical_sha256"]
    assert manifest["authorization_id"] == item["events"][0]["data"]["authorization_id"]
    assert manifest["recon_action_id"] is None and manifest["proposal_ref"] is None
    action_parameters = next(a for a in capture["artifacts"] if a["kind"] == "ACTION_PARAMETERS")
    _, action_payload = ctx[0].repository.get_artifact(action_parameters["artifact_id"], item["attempt_id"])
    action_payload = json.loads(action_payload)
    assert action_payload["authorization_id"] == manifest["authorization_id"]
    assert action_payload["recon_action_id"] is None and action_payload["proposal_ref"] is None
    assert manifest["coverage"]["SCREENSHOTS"] == "NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS"
    assert manifest["coverage"]["TARGET_BEFORE_STATE"] == "NOT_MEASURED"
    for descriptor in capture["artifacts"]:
        stored, payload = ctx[0].repository.get_artifact(descriptor["artifact_id"], item["attempt_id"])
        assert stored == descriptor and verify_artifact(stored, payload)
        assert b"SENSITIVE_TARGET_COOKIE" not in payload
        assert all(stored[k] == manifest[k] for k in ("execution_id", "mission_id", "task_id", "pentest_id"))
    response = next(a for a in capture["artifacts"] if a["kind"] == "TARGET_RESPONSE")
    assert response["captured_sha256"] == item["invocation"]["result"]["observation"]["response_sha256"]
    assert response["content_sha256"] != response["captured_sha256"]
    stdout = next(a for a in capture["artifacts"] if a["kind"] == "STDOUT")
    _, payload = ctx[0].repository.get_artifact(stdout["artifact_id"], item["attempt_id"])
    assert len(json.loads(payload)["messages"]) == 2
    assert not manifest["semantics"]["vulnerability_confirmed"] and not manifest["semantics"]["vep_created"]


@pytest.mark.parametrize("field", ["next_stage", "predecessor", "limits", "capture", "privacy", "semantics", "repository"])
def test_contract_tamper_rejected_and_predecessor_exact(field):
    value = canonical_evidence_contract()
    assert verify_evidence_contract(value)
    assert value["predecessor"]["contract_sha256"] == canonical_runtime_contract()["integrity"]["canonical_sha256"]
    forged = deepcopy(value)
    forged[field] = "FORGED"
    assert not verify_evidence_contract(forged)


def test_replay_and_verification_do_not_revalidate_or_touch_target(ctx):
    item, capture = completed(ctx)
    calls = len(ctx[2].calls), len(ctx[4][1])
    assert not ctx[0].start_execution(ctx[1])["created"]
    for _ in range(3):
        assert ctx[0].get_evidence(item["attempt_id"]) == capture
        assert ctx[0].verify_capture(item["attempt_id"])["status"] == "VERIFIED"
    assert calls == (len(ctx[2].calls), len(ctx[4][1]))


def test_recon_execution_result_projection_is_hash_bound_and_non_authorizing():
    action_id, proposal_ref = "rareq-" + "a" * 48, "actp-" + "b" * 48
    item = {
        "attempt_id": "xattempt-" + "c" * 32, "state": "SUCCEEDED", "head_sha256": "d" * 64,
        "record": {"mission_id":"mission-gmo-test", "pentest_id":"pentest-test", "task_id":"ptask-test",
            "pentest_task_id":"pentest-task-test", "execution_id":"exec-test", "attempt_number":1,
            "retry_of_attempt_id":None, "integrity":{"canonical_sha256":"e" * 64}},
        "invocation": {"result":{"status":"SUCCEEDED", "reason_codes":[], "observation":None,
            "semantics":{"target_network_io_performed":False}, "integrity":{"canonical_sha256":"f" * 64}}},
        "events":[{"event_id":"xevent-auth", "data":{"authorization_id":"eauth-test"}}],
    }
    manifest = {"recon_action_id":action_id, "proposal_ref":proposal_ref, "attempt_id":item["attempt_id"],
        "terminal_event_sha256":item["head_sha256"], "evidence_id":"xevidence-test",
        "integrity":{"canonical_sha256":"1" * 64}, "capture_status":"CAPTURED",
        "target_io_uncertain":False, "artifacts":[]}
    result = build_recon_execution_result(action_id=action_id, proposal_ref=proposal_ref,
        orchestration_id="orch-test", item=item, manifest=manifest)
    assert verify_recon_execution_result(result)
    assert result["action_id"] == action_id and result["proposal_ref"] == proposal_ref
    assert result["evidence"]["evidence_id"] == manifest["evidence_id"]
    assert result["evidence"]["capture_status"] == "SEALED"
    assert result["semantics"]["result_is_authorization"] is False
    forged = {**result, "runtime_state":"FAILED"}
    assert not verify_recon_execution_result(forged)


def test_recon_result_endpoint_is_exact_read_only_and_does_not_accept_submissions(ctx):
    action_id = "rareq-" + "a" * 48
    with server_for(ctx[0]) as url:
        code, contract, _ = http(url + "/api/contracts/recon-execution-result")
        assert code == 200 and contract["contract"]["lookup"] == "EXACT_RECON_ACTION_REQUEST_ID"
        assert contract["contract"]["predecessor"]["control"] == "stage6.6-artifact-evidence-capture"
        code, response, _ = http(url + "/api/execution/recon-action-requests/" + action_id + "/results")
        assert code == 404 and response.get("error"), response
        code, response, _ = http(url + "/api/execution/recon-action-requests/" + action_id + "/results",
                                 {"execution_result":{"status":"SUCCEEDED"}})
        assert code == 409 and response["execution_authorized"] is False
    assert not ctx[4][1] and not ctx[2].calls


def test_concurrent_duplicate_intake_one_attempt_one_manifest(ctx):
    with ThreadPoolExecutor(max_workers=4) as pool:
        starts = list(pool.map(lambda _:ctx[0].start_execution(ctx[1]), range(4)))
    assert sum(s["created"] for s in starts) == 1
    item = wait_for(ctx[0], starts[0]["attempt_id"])
    assert ctx[0].get_evidence(item["attempt_id"])["artifact_count"] == 9
    assert len(ctx[4][1]) == 1


@pytest.mark.parametrize("route", ["evidence", "artifacts", "evidence/attempts/xattempt-forged", "artifacts/upload"])
def test_caller_upload_and_fabricated_evidence_rejected(ctx, route):
    with server_for(ctx[0]) as url:
        code, response, _ = http(url + "/api/execution/" + route, {"decision":"ALLOW", "stdout":"FAKE"})
    assert code == 409 and not response["execution_authorized"]
    assert not ctx[4][1] and not ctx[2].calls


@pytest.mark.parametrize("query", ["", "?attempt_id=xattempt-other", "?attempt_id=a&attempt_id=b", "?attempt_id=xattempt-x&path=../../data"])
def test_artifact_read_requires_exact_attempt_and_rejects_overrides(ctx, query):
    item, capture = completed(ctx)
    artifact = capture["artifacts"][0]
    with server_for(ctx[0]) as url:
        code, _, _ = http(url + "/api/execution/artifacts/" + artifact["artifact_id"] + query)
    assert code in {400, 404}


def test_http_contract_verify_artifact_content_and_runtime_version(ctx):
    item, capture = completed(ctx)
    artifact = capture["artifacts"][0]
    with server_for(ctx[0]) as url:
        code, health, headers = http(url + "/health")
        assert code == 200 and "APTSExecutionSubsystem/6.6" in headers["Server"]
        assert health["execution_repository_migration_level"] == 6 and health["next_stage"] == "6.7"
        code, value, _ = http(url + "/api/execution/artifact-evidence-contract")
        assert code == 200 and verify_evidence_contract(value["contract"])
        code, value, _ = http(url + "/api/execution/evidence/attempts/" + item["attempt_id"] + "/verify")
        assert code == 200 and value["status"] == "VERIFIED"
        code, value, _ = http(url + "/api/execution/artifacts/" + artifact["artifact_id"] + "?attempt_id=" + item["attempt_id"])
        assert code == 200 and verify_artifact(value["artifact"], base64.b64decode(value["content_base64"]))
        code, _, headers = http(url + "/api/execution/artifacts/" + artifact["artifact_id"] + "/content?attempt_id=" + item["attempt_id"])
        assert code == 200 and headers["X-Artifact-SHA256"] == artifact["content_sha256"]
        code, value, _ = http(url + "/api/execution/evidence?execution_id=" + ctx[1]["execution_id"])
        assert code == 200 and value["count"] == 1


@pytest.mark.parametrize("table", ["execution_capture_sessions", "execution_artifacts", "execution_evidence_captures"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_append_only_sql_guards(ctx, table, operation):
    completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE {table} SET record_json=record_json" if operation == "UPDATE" else f"DELETE FROM {table}")


@pytest.mark.parametrize("column,value", [("payload", b'{"forged":true}'), ("content_sha256", "0"*64),
    ("record_sha256", "0"*64), ("kind", "SCREENSHOT"), ("record_json", '{}')])
def test_blob_or_index_corruption_is_rejected_on_every_read(ctx, column, value):
    item, capture = completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_artifacts_no_update")
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(f"UPDATE execution_artifacts SET {column}=? WHERE artifact_id=?", (value, capture["artifacts"][0]["artifact_id"]))
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].get_evidence(item["attempt_id"])
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].repository.get_attempt(item["attempt_id"])


@pytest.mark.parametrize("table", ["execution_capture_sessions", "execution_evidence_captures", "execution_artifacts"])
def test_missing_manifest_session_or_artifact_rejected(ctx, table):
    item, _ = completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute(f"DROP TRIGGER {table}_no_delete")
        conn.execute(f"DELETE FROM {table}")
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].get_evidence(item["attempt_id"])


def test_cancel_preserves_partial_output_and_terminal_evidence(ctx):
    ctx[4][2]["sleep"] = 1.3
    attempt = ctx[0].start_execution(ctx[1])
    item = wait_for(ctx[0], attempt["attempt_id"], lambda x:x["state"] == "RUNNING" and bool(ctx[4][1]))
    ctx[0].control(cancellation(item))
    item = wait_for(ctx[0], item["attempt_id"])
    capture = ctx[0].get_evidence(item["attempt_id"])
    assert item["state"] == "CANCELLED" and verify_evidence(capture["manifest"])
    assert capture["status"] == "PARTIAL"
    assert capture["manifest"]["coverage"]["TARGET_RESPONSE"] == "PARTIAL"


def test_pre_io_failure_and_manual_retry_have_separate_evidence(ctx):
    pin = ctx[0].broker.pin
    def fail(*args, **kwargs):
        raise OSError("synthetic pre-connect failure")
    ctx[0].broker.pin = fail
    item, first = completed(ctx)
    assert item["state"] == "FAILED"
    assert first["manifest"]["coverage"]["TARGET_RESPONSE"] == "NO_TARGET_IO"
    ctx[0].broker.pin = pin
    ctx[5][0] += timedelta(seconds=1)
    attempt = ctx[0].start_execution(retry_payload(ctx[1], item), retry=True)
    next_item = wait_for(ctx[0], attempt["attempt_id"])
    second = ctx[0].get_evidence(next_item["attempt_id"])
    assert second["status"] == "CAPTURED" and second["evidence_id"] != first["evidence_id"]
    assert not set(a["artifact_id"] for a in first["artifacts"]) & set(a["artifact_id"] for a in second["artifacts"])


def test_capture_owner_and_terminal_write_fences(ctx):
    item, _ = completed(ctx)
    with pytest.raises(ExecutionSourceRejected):
        ctx[0].repository.store_capture(item["attempt_id"], ctx[0].owner_id, "STDOUT", {}, NOW.isoformat())


def test_active_capture_is_explicitly_unsealed(ctx):
    ctx[4][2]["sleep"] = 1.0
    attempt = ctx[0].start_execution(ctx[1])
    capture = ctx[0].get_evidence(attempt["attempt_id"])
    assert not capture["sealed"] and capture["status"] == "CAPTURING" and capture["manifest"] is None
    assert ctx[0].verify_capture(attempt["attempt_id"])["status"] == "CAPTURING"
    wait_for(ctx[0], attempt["attempt_id"])


@pytest.mark.parametrize("repository_class", [ExecutionRequestRepository, ExecutionAuthorizationRepository,
    ExecutionGatewayRepository, ExecutionAdapterRepository, ExecutionRuntimeRepository])
def test_atomic_upgrade_supported_predecessors(tmp_path, repository_class):
    db = tmp_path / "execution.db"
    repository_class(db).initialize()
    assert ExecutionEvidenceRepository(db).migration_level() == 6
    with pytest.raises(ExecutionRepositoryError):
        repository_class(db).initialize()


@pytest.mark.parametrize("version", [0, 7, 98])
def test_future_or_invalid_version_is_not_modified(tmp_path, version):
    db = tmp_path / "execution.db"
    ExecutionEvidenceRepository(db).initialize()
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE execution_repository_meta SET migration_level=?", (version,))
    before = db.read_bytes()
    with pytest.raises(ExecutionRepositoryError):
        ExecutionEvidenceRepository(db).initialize()
    assert db.read_bytes() == before


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1"])
def test_remote_control_api_bind_rejected(host):
    with pytest.raises(ExecutionRequestValidationError):
        serve(host, 0)


def test_untrusted_worker_output_never_copies_secret_text():
    raw = b'{"token":"VERY_SECRET"}\n' + b'{"ready":true,"backend":"VERY_SECRET","pid":12}\n'
    result = safe_worker_messages(raw)
    assert result["omitted_line_count"] == 2 and "VERY_SECRET" not in canonical_json(result)


def test_actual_external_authority_http_capture(ctx):
    with authority_server(ctx[2]) as url:
        ctx[0].governance_client = ExecutionGovernanceClient(url)
        item, capture = completed(ctx)
    assert item["state"] == "SUCCEEDED" and verify_evidence(capture["manifest"])


def test_upstream_mission_pentest_bytes_unchanged(ctx):
    paths = [ctx[0].proposal_source.sqlite_path, ctx[0].mission_source.sqlite_path]
    before = [p.read_bytes() for p in paths]
    completed(ctx)
    assert before == [p.read_bytes() for p in paths]


def child_capture_crash(paths, intake, channel, phase):
    service = ExecutionEvidenceService(ExecutionEvidenceRepository(paths[0]),
        ExecutionAuthorizationProposalSource(paths[1]), MissionAuthorizationSource(paths[2]),
        UniqueAuthority(), clock=lambda:NOW)
    if phase == "DURABLE_OUTPUT":
        def hold(identity, *args, **kwargs):
            channel.send(("READY", identity))
            from threading import Event
            Event().wait(60)
        service.repository.finalize = hold
    else:
        def hold(claim, envelope, **kwargs):
            from execution_subsystem.runtime_contract import attempt_id
            channel.send(("READY", attempt_id(claim["invocation_id"])))
            from threading import Event
            Event().wait(60)
        service._run_reserved = hold
    try:
        service.start_execution(intake)
        from threading import Event
        Event().wait(60)
    except BaseException as exc:
        channel.send(("ERROR", type(exc).__name__, str(exc)))


@pytest.mark.parametrize("phase", ["BEFORE_NATIVE_WORKER", "DURABLE_OUTPUT"])
def test_real_process_crash_recovery_seals_partial_capture_without_redispatch(ctx, phase):
    service = ctx[0]
    paths = [str(service.repository.sqlite_path), str(service.proposal_source.sqlite_path), str(service.mission_source.sqlite_path)]
    service.close()
    mp = multiprocessing.get_context("spawn")
    parent, child = mp.Pipe()
    process = mp.Process(target=child_capture_crash, args=(paths, ctx[1], child, phase))
    process.start()
    try:
        assert parent.poll(25), "child runtime did not reach capture barrier"
        ready = parent.recv()
        assert ready[0] == "READY", ready
        with pytest.raises(ExecutionRepositoryError):
            ExecutionEvidenceService(ExecutionEvidenceRepository(paths[0]))
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        target_calls = len(ctx[4][1])
        resumed = ExecutionEvidenceService(ExecutionEvidenceRepository(paths[0]),
            ExecutionAuthorizationProposalSource(paths[1]), MissionAuthorizationSource(paths[2]),
            UniqueAuthority(), clock=lambda:NOW)
        try:
            attempt = resumed.get_attempt(ready[1])
            value = resumed.get_evidence(ready[1])
            assert attempt["state"] == "ABORTED" and attempt["target_io_uncertain"]
            assert value["status"] == "RECOVERED_PARTIAL" and verify_evidence(value["manifest"])
            assert value["manifest"]["adapter_result_sha256"] is None
            assert value["manifest"]["coverage"]["RESULT"] == "NOT_DURABLY_CAPTURED_BEFORE_CRASH"
            assert value["artifact_count"] == (8 if phase == "DURABLE_OUTPUT" else 4)
            assert len(ctx[4][1]) == target_calls and not resumed.governance_client.calls
        finally:
            resumed.close()
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()
        child.close()


def test_legacy_stage65_attempt_is_not_fabricated_or_recaptured(ctx, tmp_path):
    original = ctx[0]
    legacy = ExecutionRuntimeService(ExecutionRuntimeRepository(tmp_path / "legacy.db"),
        original.proposal_source, original.mission_source, UniqueAuthority(), clock=lambda:NOW)
    try:
        legacy.create_request(ctx[3]["envelope"]["intake"])
        attempt = legacy.start_execution(ctx[1])
        item = wait_for(legacy, attempt["attempt_id"])
        old_head = item["head_sha256"]
    finally:
        legacy.close()
    calls = len(ctx[4][1])
    upgraded = ExecutionEvidenceService(ExecutionEvidenceRepository(tmp_path / "legacy.db"),
        original.proposal_source, original.mission_source, UniqueAuthority(), clock=lambda:NOW)
    try:
        value = upgraded.get_evidence(item["attempt_id"])
        assert value["status"] == "LEGACY_NOT_CAPTURED" and not value["sealed"] and not value["artifacts"]
        assert upgraded.get_attempt(item["attempt_id"])["head_sha256"] == old_head
        assert len(ctx[4][1]) == calls and not upgraded.governance_client.calls
    finally:
        upgraded.close()


def test_artifact_persistence_failure_cannot_commit_success(ctx):
    repo = ctx[0].repository
    insert = repo._insert_artifact
    def fail(conn, session, kind, *args, **kwargs):
        if kind == "STDOUT":
            raise OSError("synthetic capture persistence failure")
        return insert(conn, session, kind, *args, **kwargs)
    repo._insert_artifact = fail
    attempt = ctx[0].start_execution(ctx[1])
    limit = time.monotonic() + 8
    while not ctx[0]._failures and time.monotonic() < limit:
        time.sleep(0.02)
    assert ctx[0]._failures and ctx[0].health()["status"] == "degraded"
    item = repo.get_attempt(attempt["attempt_id"])
    assert item["state"] == "RUNNING" and item["invocation"]["result"] is None
    assert not ctx[0].get_evidence(item["attempt_id"])["sealed"]


@pytest.mark.parametrize("decision", ["DENY", "REVIEW"])
def test_denied_authority_produces_no_capture_or_target_io(ctx, decision):
    ctx[2].decision = decision
    with pytest.raises(ExecutionSourceRejected):
        ctx[0].start_execution(ctx[1])
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        assert conn.execute("SELECT count(*) FROM execution_capture_sessions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM execution_artifacts").fetchone()[0] == 0
    assert not ctx[4][1]


def reserve_only(ctx):
    from execution_subsystem.runtime_contract import adapter_intake, attempt_id
    service = ctx[0]
    intake = adapter_intake(ctx[1])
    auth = service._fresh_authorization(intake)
    item, created = service.repository.reserve_adapter(intake, auth["authorization_id"],
        final_check=lambda authorization:service._final_admission_check(ctx[3]["envelope"], authorization),
        runtime_context={"runtime_intake": ctx[1], "owner_id": service.owner_id})
    assert created and item["record"]["status"] == "RESERVED"
    return attempt_id(item["invocation_id"])


@pytest.mark.parametrize("quota", ["ARTIFACT", "ATTEMPT"])
def test_artifact_and_total_attempt_quotas_reject_without_target_io(ctx, quota):
    identity = reserve_only(ctx)
    store = ctx[0].repository.store_capture
    if quota == "ARTIFACT":
        with pytest.raises(ExecutionSourceRejected, match="ARTIFACT_BYTE_QUOTA"):
            store(identity, ctx[0].owner_id, "STDOUT", "X" * MAX_ARTIFACT_BYTES, NOW.isoformat())
    else:
        payload = "X" * (MAX_ARTIFACT_BYTES - 2)
        for kind in ("STDOUT", "STDERR", "NETWORK_OBSERVATION"):
            store(identity, ctx[0].owner_id, kind, payload, NOW.isoformat())
        with pytest.raises(ExecutionSourceRejected, match="ATTEMPT_ARTIFACT_QUOTA"):
            store(identity, ctx[0].owner_id, "TARGET_RESPONSE", payload, NOW.isoformat())
    assert not ctx[4][1]


def test_active_attempt_capture_requires_exact_owner(ctx):
    identity = reserve_only(ctx)
    with pytest.raises(ExecutionSourceRejected, match="EXACT_RUNTIME_OWNER"):
        ctx[0].repository.store_capture(identity, "runtime-owner-forged", "STDOUT", {}, NOW.isoformat())
    assert not ctx[4][1]


def test_terminal_result_and_event_roll_back_when_manifest_insert_fails(ctx):
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("CREATE TRIGGER reject_test_manifest BEFORE INSERT ON execution_evidence_captures "
            "BEGIN SELECT RAISE(ABORT,'synthetic manifest write failure'); END")
    attempt = ctx[0].start_execution(ctx[1])
    limit = time.monotonic() + 8
    while not ctx[0]._failures and time.monotonic() < limit:
        time.sleep(0.02)
    assert ctx[0]._failures
    item = ctx[0].repository.get_attempt(attempt["attempt_id"])
    assert item["state"] == "RUNNING" and item["invocation"]["result"] is None
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        assert conn.execute("SELECT count(*) FROM execution_evidence_captures").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM execution_artifacts WHERE kind IN ('AFTER_STATE','RESULT')").fetchone()[0] == 0


@pytest.mark.parametrize("route", ["evidence?execution_id=exec-x&execution_id=exec-y",
    "evidence?execution_id=exec-x&path=data", "artifact-evidence-contract?decision=ALLOW"])
def test_evidence_queries_cannot_override_source_or_authority(ctx, route):
    with server_for(ctx[0]) as url:
        code, _, _ = http(url + "/api/execution/" + route)
    assert code == 400 and not ctx[4][1] and not ctx[2].calls
