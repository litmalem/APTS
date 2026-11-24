from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import base64
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

import pytest

from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.adapter_repository import ExecutionAdapterRepository
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.evidence_contract import (bytes_sha256, canonical_evidence_contract, seal_artifact,
    seal_evidence, verify_evidence_contract)
from execution_subsystem.evidence_repository import ExecutionEvidenceRepository
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json, sha256_hex, with_integrity)
from execution_subsystem.request_repository import ExecutionRepositoryError, ExecutionRequestRepository
from execution_subsystem.runtime_contract import START_SCHEMA
from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
from execution_subsystem.runtime_service import ExecutionRuntimeService
from execution_subsystem.vep_api import ExecutionSubsystemStage67Handler, serve
from execution_subsystem.vep_contract import (INTAKE_SCHEMA, VEP_CONTROL_VERSION, VEP_DOMAIN, MAX_VEP_BYTES,
    SECTION_FIELDS, build_vep, canonical_vep_contract, normalize_vep_intake, verify_vep, verify_vep_contract, verify_vep_export)
from execution_subsystem.vep_repository import ExecutionVEPRepository
from execution_subsystem.vep_service import ExecutionVEPService
from execution_subsystem.vep_source import SOURCE_DOMAIN, verify_source_snapshot
from tests.test_stage6_1_canonical_execution_request_contract import intake_for, http
from tests.test_stage6_2_authoritative_execution_authorization import NOW
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority
from tests.test_stage6_3_controlled_execution_gateway import authority_server
from execution_subsystem.governance_client import ExecutionGovernanceClient
from tests.test_stage6_4_authorized_tool_adapters_sandboxing import adapter_seed, target_server
from tests.test_stage6_5_execution_runtime_control import wait_for, cancellation, retry_payload, BeforeIOFailure
from run.stage6_7_audit import audit_file


@pytest.fixture
def ctx(tmp_path, adapter_seed, target_server):
    pdb, mdb, run = adapter_seed
    pentest, mission = tmp_path / "pentest.db", tmp_path / "mission.db"
    shutil.copy2(pdb, pentest)
    shutil.copy2(mdb, mission)
    authority, now = UniqueAuthority(), [NOW]
    service = ExecutionVEPService(ExecutionVEPRepository(tmp_path / "execution.db"),
        ExecutionAuthorizationProposalSource(pentest), MissionAuthorizationSource(mission), authority, clock=lambda:now[0])
    request = service.create_request(intake_for(run, "stage67"))
    intake = {"schema_version":START_SCHEMA, "invocation_request_id":"toolreq-stage67", "idempotency_key":"idem-stage67",
        "execution_id":request["execution_id"], "envelope_sha256":request["envelope"]["integrity"]["canonical_sha256"], "requested_by":"stage67-test"}
    target_server[2].update({"sleep":0, "redirect":False})
    target_server[1].clear()
    try:
        yield service, intake, authority, request, target_server, now
    finally:
        service.close()
        target_server[2].update({"sleep":0, "redirect":False})


def construction_payload(service, item):
    capture = service.get_evidence(item["attempt_id"])
    return {"schema_version":INTAKE_SCHEMA, "attempt_id":item["attempt_id"],
        "envelope_sha256":item["record"]["runtime_intake"]["envelope_sha256"],
        "evidence_sha256":capture["manifest_sha256"], "expected_head_sha256":item["head_sha256"]}


def completed(ctx):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    payload = construction_payload(ctx[0], item)
    value = ctx[0].construct_vep(payload)
    return item, payload, value


@contextmanager
def server_for(service):
    handler = type("TestStage67Handler", (ExecutionSubsystemStage67Handler,), {"service":service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def resign(value):
    core = {k:v for k,v in value.items() if k != "integrity"}
    core["integrity_hashes"] = {k:sha256_hex(core[k]) for k in SECTION_FIELDS}
    return with_integrity(core, VEP_DOMAIN)


def test_exact_predecessor_and_construction_contract():
    value = canonical_vep_contract()
    assert value["predecessor"]["contract_sha256"] == canonical_evidence_contract()["integrity"]["canonical_sha256"]
    assert verify_vep_contract(value) and verify_evidence_contract(canonical_evidence_contract())
    assert value["repository"]["migration_level"] == 7 and value["next_stage"] == "6.8"
    value["construction"]["automatic_vulnerability_confirmation"] = True
    assert not verify_vep_contract(value)


def test_native_terminal_vep_contains_all_roadmap_fields_and_exact_blobs(ctx):
    item, _, response = completed(ctx)
    value = response["vep"]
    assert item["state"] == "SUCCEEDED" and response["created"] and verify_vep(value)
    assert set(value) >= {"mission_id", "pentest_id", "finding_id", "hypothesis", "validation_method", "execution_references",
        "observed_result", "evidence", "affected_asset", "impact", "confidence", "provenance", "timestamps", "integrity_hashes"}
    assert value["finding"]["status"] == "UNCONFIRMED_CANDIDATE" and not value["semantics"]["vulnerability_confirmed"]
    assert value["observed_result"]["target_io_observed"] and value["confidence"]["validated_vulnerability_confidence"] is None
    assert value["impact"]["observed_security_impact"] is None and not value["impact"]["confirmed"]
    assert value["evidence"]["terminal_event_sha256"] == item["head_sha256"]
    assert value["integrity_hashes"] == {k:sha256_hex(value[k]) for k in SECTION_FIELDS}
    export = ctx[0].export_vep(value["vep_id"], item["attempt_id"])
    assert verify_vep_export(export) and len(export["artifacts"]) == 9
    assert "SENSITIVE_TARGET_COOKIE" not in canonical_json(export)


def test_replay_reads_and_offline_verify_have_no_governance_or_target_io(ctx):
    item, payload, response = completed(ctx)
    counts = len(ctx[2].calls), len(ctx[4][1])
    export = ctx[0].export_vep(response["vep_id"], item["attempt_id"])
    ctx[5][0] += timedelta(days=90)
    for _ in range(3):
        replay = ctx[0].construct_vep(payload)
        assert not replay["created"] and replay["vep"] == response["vep"]
        assert ctx[0].verify_vep_record(response["vep_id"], item["attempt_id"])["status"] == "VERIFIED"
        assert verify_vep_export(export)
    assert counts == (len(ctx[2].calls), len(ctx[4][1]))


def test_concurrent_duplicate_construction_commits_one_immutable_package(ctx):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    payload = construction_payload(ctx[0], item)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _:ctx[0].construct_vep(payload), range(4)))
    assert sum(v["created"] for v in values) == 1
    assert all(v["vep"] == values[0]["vep"] for v in values)
    assert len(ctx[4][1]) == 1 and ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 1


@pytest.mark.parametrize("field", ["decision", "finding_id", "hypothesis", "impact", "confidence", "evidence", "path", "command", "stdout"])
def test_caller_authority_summary_and_artifacts_forbidden(ctx, field):
    with pytest.raises(ExecutionRequestValidationError):
        ctx[0].construct_vep({"schema_version":INTAKE_SCHEMA, "attempt_id":"xattempt-forged", "envelope_sha256":"a"*64,
            "evidence_sha256":"b"*64, "expected_head_sha256":"c"*64, field:"FAKE"})
    assert not ctx[2].calls and not ctx[4][1]


@pytest.mark.parametrize("field", ["envelope_sha256", "evidence_sha256", "expected_head_sha256"])
def test_exact_reference_mismatch_blocks_new_and_existing_vep(ctx, field):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    payload = construction_payload(ctx[0], item)
    bad = {**payload, field:"0"*64}
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].construct_vep(bad)
    assert ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 0
    ctx[0].construct_vep(payload)
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].construct_vep(bad)


def test_active_attempt_never_produces_vep(ctx):
    ctx[4][2]["sleep"] = 1.1
    start = ctx[0].start_execution(ctx[1])
    with pytest.raises(ExecutionSourceRejected, match="TERMINAL"):
        ctx[0].construct_vep({"schema_version":INTAKE_SCHEMA, "attempt_id":start["attempt_id"],
            "envelope_sha256":ctx[1]["envelope_sha256"], "evidence_sha256":"0"*64, "expected_head_sha256":"0"*64})
    assert ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 0


def test_cancelled_partial_capture_remains_inconclusive(ctx):
    ctx[4][2]["sleep"] = 1.1
    start = ctx[0].start_execution(ctx[1])
    running = wait_for(ctx[0], start["attempt_id"], lambda i:i["state"] == "RUNNING" and bool(ctx[4][1]))
    ctx[0].control(cancellation(running))
    item = wait_for(ctx[0], start["attempt_id"])
    value = ctx[0].construct_vep(construction_payload(ctx[0], item))["vep"]
    assert value["observed_result"]["runtime_state"] == "CANCELLED"
    assert value["observed_result"]["capture_status"] == "PARTIAL" and verify_vep(value)
    assert verify_vep_export(ctx[0].export_vep(value["vep_id"], item["attempt_id"]))


def test_failed_before_io_and_manual_retry_have_distinct_veps(ctx):
    original = ctx[0].broker
    ctx[0].broker = BeforeIOFailure()
    first, _, first_vep = completed(ctx)
    assert first["state"] == "FAILED" and not first_vep["vep"]["observed_result"]["target_io_observed"]
    ctx[0].broker = original
    ctx[5][0] += timedelta(seconds=1)
    second = wait_for(ctx[0], ctx[0].start_execution(retry_payload(ctx[1], first), retry=True)["attempt_id"])
    value = ctx[0].construct_vep(construction_payload(ctx[0], second))
    assert value["vep_id"] != first_vep["vep_id"] and value["finding_id"] == first_vep["finding_id"]
    assert value["vep"]["execution_references"]["retry_of_attempt_id"] == first["attempt_id"]
    assert ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 2


def test_vep_reads_replay_survive_unavailable_upstream_sources(ctx):
    item, payload, response = completed(ctx)
    ctx[0].proposal_source.sqlite_path.unlink()
    ctx[0].mission_source.sqlite_path.unlink()
    assert ctx[0].get_vep(response["vep_id"], item["attempt_id"])["vep"] == response["vep"]
    assert not ctx[0].construct_vep(payload)["created"]
    assert verify_vep_export(ctx[0].export_vep(response["vep_id"], item["attempt_id"]))


def test_first_construction_after_mission_stop_and_orchestration_termination(ctx):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    with sqlite3.connect(ctx[0].proposal_source.sqlite_path) as conn:
        conn.execute("UPDATE pentest_agentic_orchestrations SET orchestration_status='TERMINATED'")
    with sqlite3.connect(ctx[0].mission_source.sqlite_path) as conn:
        conn.execute("UPDATE mission_states SET state='ABORTED',terminal=1")
    ctx[5][0] += timedelta(days=90)
    response = ctx[0].construct_vep(construction_payload(ctx[0], item))
    assert verify_vep(response["vep"]) and not response["authorization_current"]


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_vep_sql_append_only_guards(ctx, operation):
    completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE execution_veps SET record_json=record_json" if operation == "UPDATE" else "DELETE FROM execution_veps")


@pytest.mark.parametrize("column,value", [("record_json", '{}'), ("record_sha256", "0"*64),
    ("evidence_sha256", "0"*64), ("terminal_event_sha256", "0"*64), ("mission_id", "mission-gmo-foreign"),
    ("finding_id", "xvepfind-forged"), ("constructed_at", "2000-01-01T00:00:00Z")])
def test_vep_corruption_rejected_by_read_verify_list_and_export(ctx, column, value):
    item, _, response = completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_veps_no_update")
        conn.execute(f"UPDATE execution_veps SET {column}=?", (value,))
    for action in (ctx[0].get_vep, ctx[0].verify_vep_record, ctx[0].export_vep):
        with pytest.raises(ExecutionRequestIntegrityError):
            action(response["vep_id"], item["attempt_id"])
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].list_veps(ctx[1]["execution_id"])


@pytest.mark.parametrize("field", ["payload", "content_sha256", "record_sha256"])
def test_vep_reads_reverify_original_artifact_bytes(ctx, field):
    item, _, response = completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_artifacts_no_update")
        conn.execute(f"UPDATE execution_artifacts SET {field}=?", (b'{}' if field == "payload" else "0"*64,))
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].export_vep(response["vep_id"], item["attempt_id"])


@pytest.mark.parametrize("field", ["finding", "hypothesis", "validation_method", "observed_result", "impact", "confidence", "provenance", "timestamps", "limitations", "semantics"])
def test_rehashed_fabricated_summary_cannot_pass_semantic_verification(ctx, field):
    _, _, response = completed(ctx)
    forged = deepcopy(response["vep"])
    forged[field]["forged"] = True
    assert not verify_vep(resign(forged))


@pytest.mark.parametrize("tamper", ["blob", "missing", "duplicate", "reordered", "extra", "scope", "coverage", "source", "event", "result"])
def test_offline_export_rejects_tampering_and_cross_binding(ctx, tamper):
    item, _, response = completed(ctx)
    export = ctx[0].export_vep(response["vep_id"], item["attempt_id"])
    if tamper == "blob":
        export["artifacts"][0]["content_base64"] = "e30="
    elif tamper == "missing":
        export["artifacts"].pop()
    elif tamper == "duplicate":
        export["artifacts"][0] = export["artifacts"][1]
    elif tamper == "reordered":
        export["artifacts"].reverse()
    elif tamper == "extra":
        export["artifacts"].append(export["artifacts"][0])
    elif tamper == "scope":
        export["vep"]["mission_id"] = "mission-gmo-foreign"
    elif tamper == "coverage":
        export["vep"]["evidence"]["coverage"]["SCREENSHOTS"] = "PRESENT"
    elif tamper == "source":
        export["vep"]["source_snapshot"]["hypothesis"]["data"]["statement"] = "Different hypothesis"
    elif tamper == "event":
        export["vep"]["execution_snapshot"]["events"][-1]["state_after"] = "FAILED"
    elif tamper == "result":
        export["vep"]["execution_snapshot"]["adapter_result"]["semantics"]["vulnerability_confirmed"] = True
    export["vep"] = resign(export["vep"])
    assert not verify_vep_export(export)


def test_original_source_corruption_blocks_first_construction(ctx):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    with sqlite3.connect(ctx[0].proposal_source.sqlite_path) as conn:
        conn.execute("UPDATE pentest_exploitation_runs SET output_sha256=?", ("0"*64,))
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].construct_vep(construction_payload(ctx[0], item))
    assert ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 0


def test_source_access_is_read_only_and_upstream_bytes_unchanged(ctx):
    paths = ctx[0].proposal_source.sqlite_path, ctx[0].mission_source.sqlite_path
    before = [p.read_bytes() for p in paths]
    with ctx[0].vep_source._connect() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM pentest_lineage_objects")
    completed(ctx)
    assert before == [p.read_bytes() for p in paths]


@pytest.mark.parametrize("old_repository", [ExecutionRequestRepository, ExecutionAuthorizationRepository,
    ExecutionGatewayRepository, ExecutionAdapterRepository, ExecutionRuntimeRepository, ExecutionEvidenceRepository])
def test_atomic_upgrade_from_all_predecessor_migrations(tmp_path, old_repository):
    path = tmp_path / "execution.db"
    old_repository(path).initialize()
    repo = ExecutionVEPRepository(path)
    assert repo.migration_level() == 7
    with pytest.raises(ExecutionRepositoryError):
        old_repository(path).initialize()


def test_failed_migration_rolls_back_exact_stage66_schema(tmp_path, monkeypatch):
    path = tmp_path / "execution.db"
    ExecutionEvidenceRepository(path).initialize()
    original = Path.read_text
    def bad_sql(self, *args, **kwargs):
        if self.name.startswith("007_stage6_7"):
            return "CREATE TABLE partial_vep(x TEXT);\nINVALID SQL;\n"
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", bad_sql)
    with pytest.raises(ExecutionRepositoryError):
        ExecutionVEPRepository(path).initialize()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT migration_level FROM execution_repository_meta").fetchone()[0] == 6
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='partial_vep'").fetchone()


def test_sql_insert_failure_is_atomic_and_does_not_redispatch(ctx):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    counts = len(ctx[2].calls), len(ctx[4][1])
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("CREATE TRIGGER vep_write_failure BEFORE INSERT ON execution_veps BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END;")
    with pytest.raises(ExecutionRepositoryError):
        ctx[0].construct_vep(construction_payload(ctx[0], item))
    assert ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 0
    assert ctx[0].get_evidence(item["attempt_id"])["sealed"] and counts == (len(ctx[2].calls), len(ctx[4][1]))


def test_legacy_terminal_history_not_backfilled(ctx, tmp_path):
    old = ExecutionRuntimeService(ExecutionRuntimeRepository(tmp_path / "legacy.db"), ctx[0].proposal_source,
        ctx[0].mission_source, ctx[2], clock=lambda:NOW)
    try:
        old.create_request(ctx[3]["envelope"]["intake"])
        item = wait_for(old, old.start_execution(ctx[1])["attempt_id"])
    finally:
        old.close()
    service = ExecutionVEPService(ExecutionVEPRepository(tmp_path / "legacy.db"), ctx[0].proposal_source,
        ctx[0].mission_source, ctx[2], clock=lambda:NOW)
    try:
        counts = len(ctx[2].calls), len(ctx[4][1])
        with pytest.raises(ExecutionSourceRejected, match="NO_LEGACY_BACKFILL"):
            service.construct_vep({"schema_version":INTAKE_SCHEMA, "attempt_id":item["attempt_id"],
                "envelope_sha256":ctx[1]["envelope_sha256"], "evidence_sha256":"0"*64, "expected_head_sha256":item["head_sha256"]})
        assert counts == (len(ctx[2].calls), len(ctx[4][1]))
    finally:
        service.close()


def test_http_construct_read_verify_export_and_health(ctx):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    with server_for(ctx[0]) as url:
        code, health, headers = http(url + "/health")
        assert code == 200 and "APTSExecutionSubsystem/6.7" in headers["Server"]
        assert health["control_version"] == VEP_CONTROL_VERSION and health["execution_repository_migration_level"] == 7
        assert health["next_stage"] == "6.8" and not health["vep_automatic_vulnerability_confirmation"]
        code, value, _ = http(url + "/api/execution/vep-construction-integrity-contract")
        assert code == 200 and verify_vep_contract(value["contract"])
        payload = construction_payload(ctx[0], item)
        code, response, _ = http(url + "/api/execution/veps", payload)
        assert code == 201 and verify_vep(response["vep"])
        assert http(url + "/api/execution/veps", payload)[0] == 200
        endpoint = url + "/api/execution/veps/" + response["vep_id"]
        query = "?attempt_id=" + item["attempt_id"]
        assert http(endpoint + query)[1]["vep"] == response["vep"]
        assert http(endpoint + "/verify" + query)[1]["status"] == "VERIFIED"
        code, export, headers = http(endpoint + "/export" + query)
        assert code == 200 and verify_vep_export(export)
        assert headers["X-VEP-SHA256"] == response["vep_sha256"] and headers["X-Content-Type-Options"] == "nosniff"
        assert http(url + "/api/execution/veps?execution_id=" + ctx[1]["execution_id"])[1]["count"] == 1
        proof_path = ctx[0].repository.sqlite_path.parent / "vep_offline_export.json"
        proof_path.write_text(canonical_json(export), encoding="utf-8")
        assert audit_file(proof_path)["status"] == "VERIFIED"
        (proof_path.parent / "vep_http_proof_summary.json").write_text(json.dumps({"status":"PASS",
            "target":"ISOLATED_LOOPBACK_ONLY", "http_created_status":201, "http_replay_status":200,
            "artifact_count":len(export["artifacts"]), "vep_sha256":response["vep_sha256"],
            "native_backend":next(e["data"]["sandbox_backend"] for e in item["events"] if e["event_type"] == "RUNNING"),
            "offline_audit":"VERIFIED", "vulnerability_confirmed":False, "live_user_mission_exercised":False}, indent=2))


@pytest.mark.parametrize("query", ["", "?attempt_id=xattempt-other", "?attempt_id=a&attempt_id=b", "?attempt_id=xattempt-a&path=../../data"])
def test_http_exact_attempt_scoped_reads(ctx, query):
    _, _, response = completed(ctx)
    with server_for(ctx[0]) as url:
        assert http(url + "/api/execution/veps/" + response["vep_id"] + query)[0] in {400,404}


@pytest.mark.parametrize("path", ["veps/upload", "veps/xvep-forged/verify", "veps/xvep-forged/export", "evidence", "artifacts/upload", "runtime/results"])
def test_http_fabricated_upload_and_result_routes_closed(ctx, path):
    with server_for(ctx[0]) as url:
        assert http(url + "/api/execution/" + path, {"decision":"ALLOW","evidence":"FAKE"})[0] == 409
    assert not ctx[2].calls and not ctx[4][1]


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.1", "::"])
def test_non_loopback_vep_server_bind_rejected(host):
    with pytest.raises(ExecutionRequestValidationError):
        serve(host)


def child_vep_crash(paths, intake, channel, phase):
    service = ExecutionVEPService(ExecutionVEPRepository(paths[0]), ExecutionAuthorizationProposalSource(paths[1]),
        MissionAuthorizationSource(paths[2]), UniqueAuthority(), clock=lambda:NOW)
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
def test_real_owner_process_crash_recovery_constructs_partial_vep_without_redispatch(ctx, phase):
    paths = [str(ctx[0].repository.sqlite_path), str(ctx[0].proposal_source.sqlite_path), str(ctx[0].mission_source.sqlite_path)]
    ctx[0].close()
    mp = multiprocessing.get_context("spawn")
    parent, child = mp.Pipe()
    process = mp.Process(target=child_vep_crash, args=(paths, ctx[1], child, phase))
    process.start()
    try:
        assert parent.poll(25), "child VEP runtime did not reach durable barrier"
        ready = parent.recv()
        assert ready[0] == "READY", ready
        with pytest.raises(ExecutionRepositoryError):
            ExecutionVEPService(ExecutionVEPRepository(paths[0]))
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        target_calls = len(ctx[4][1])
        resumed = ExecutionVEPService(ExecutionVEPRepository(paths[0]), ExecutionAuthorizationProposalSource(paths[1]),
            MissionAuthorizationSource(paths[2]), UniqueAuthority(), clock=lambda:NOW)
        try:
            item = resumed.repository.get_attempt(ready[1])
            response = resumed.construct_vep(construction_payload(resumed, item))
            value = response["vep"]
            assert value["observed_result"]["runtime_state"] == "ABORTED" and value["observed_result"]["target_io_uncertain"]
            assert value["observed_result"]["capture_status"] == "RECOVERED_PARTIAL" and value["observed_result"]["adapter_status"] is None
            assert value["evidence"]["coverage"]["RESULT"] == "NOT_DURABLY_CAPTURED_BEFORE_CRASH"
            assert len(value["evidence"]["artifacts"]) == (8 if phase == "DURABLE_OUTPUT" else 4)
            assert verify_vep_export(resumed.export_vep(value["vep_id"], item["attempt_id"]))
            assert len(ctx[4][1]) == target_calls and not resumed.governance_client.calls
        finally:
            resumed.close()
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()
        child.close()


def test_real_authority_http_native_execution_then_no_authority_for_vep(ctx):
    with authority_server(ctx[2]) as url:
        ctx[0].governance_client = ExecutionGovernanceClient(url)
        item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    counts = len(ctx[2].calls), len(ctx[4][1])
    response = ctx[0].construct_vep(construction_payload(ctx[0], item))
    assert verify_vep(response["vep"]) and counts == (len(ctx[2].calls), len(ctx[4][1]))


@pytest.mark.parametrize("route", ["veps?execution_id=exec-x&execution_id=exec-y", "veps?execution_id=exec-x&path=data",
    "veps?execution_id=exec-x&limit=0", "veps?execution_id=exec-x&limit=101", "vep-construction-integrity-contract?decision=ALLOW"])
def test_http_duplicate_query_and_source_override_rejected(ctx, route):
    with server_for(ctx[0]) as url:
        assert http(url + "/api/execution/" + route)[0] == 400
    assert not ctx[2].calls and not ctx[4][1]


def test_backward_construction_clock_rejected_without_persisting_vep(ctx):
    item = wait_for(ctx[0], ctx[0].start_execution(ctx[1])["attempt_id"])
    ctx[5][0] -= timedelta(seconds=1)
    with pytest.raises(ExecutionRequestIntegrityError, match="predates"):
        ctx[0].construct_vep(construction_payload(ctx[0], item))
    assert ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 0


def test_export_audit_rejects_duplicate_keys_and_oversize_bytes(tmp_path):
    from execution_subsystem.vep_contract import MAX_EXPORT_BYTES
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version":"one","schema_version":"two"}')
    with pytest.raises(ExecutionRequestValidationError):
        audit_file(path)
    path.write_bytes(b' ' * (MAX_EXPORT_BYTES+1))
    with pytest.raises(ValueError, match="quota"):
        audit_file(path)


def test_sql_terminal_guard_and_byte_quota_enforced(ctx):
    item, _, response = completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_veps_no_delete")
        row = conn.execute("SELECT * FROM execution_veps").fetchone()
        conn.execute("DELETE FROM execution_veps")
        wrong = list(row)
        wrong[7] = "0"*64
        with pytest.raises(sqlite3.IntegrityError, match="terminal"):
            conn.execute("INSERT INTO execution_veps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", wrong)
        too_big = list(row)
        too_big[10] = "x" * (MAX_VEP_BYTES+1)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO execution_veps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", too_big)
        assert conn.execute("SELECT count(*) FROM execution_veps").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["TOOL_IDENTITY", "ACTION_PARAMETERS", "BEFORE_STATE", "STDOUT", "STDERR",
    "NETWORK_OBSERVATION", "TARGET_RESPONSE", "RESULT", "AFTER_STATE"])
def test_resealed_hash_consistent_export_rejects_non_allowlisted_artifact_payload(ctx, kind):
    item, _, response = completed(ctx)
    export = ctx[0].export_vep(response["vep_id"], item["attempt_id"])
    blob = next(b for b in export["artifacts"] if b["artifact"]["kind"] == kind)
    payload = json.loads(base64.b64decode(blob["content_base64"]))
    payload["raw_secret"] = "NON_ALLOWLISTED_DATA"
    raw = canonical_json(payload).encode("utf-8")
    descriptor = {k:v for k,v in blob["artifact"].items() if k not in {"artifact_id", "integrity"}}
    descriptor.update({"content_sha256":bytes_sha256(raw), "size_bytes":len(raw)})
    blob["artifact"] = seal_artifact(descriptor)
    blob["content_base64"] = base64.b64encode(raw).decode("ascii")
    manifest = {k:v for k,v in export["vep"]["evidence"].items() if k not in {"evidence_id", "integrity"}}
    manifest["artifacts"] = [b["artifact"] for b in export["artifacts"]]
    manifest["stored_bytes"] = sum(a["size_bytes"] for a in manifest["artifacts"])
    vep = export["vep"]
    export["vep"] = build_vep(vep["source_snapshot"], vep["execution_snapshot"], seal_evidence(manifest), vep["timestamps"]["constructed_at"])
    assert verify_vep(export["vep"])
    assert not verify_vep_export(export)
