from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from http.server import ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import shutil
import socket
import sqlite3
from threading import Event, Thread
import time

import pytest

from execution_subsystem.adapter_policy import DEFAULT_LIMITS
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.cleanup_api import ExecutionSubsystemStage68Handler, serve
from execution_subsystem.cleanup_contract import (CONTROL_VERSION, EXPORT_SCHEMA, INTAKE_SCHEMA, REPORT_DOMAIN,
    RECEIPT_DOMAIN, PHASES, build_report, canonical_cleanup_contract, verify_cleanup_contract,
    verify_post_action_export, verify_receipt, verify_report)
from execution_subsystem.cleanup_repository import ExecutionCleanupRepository
from execution_subsystem.cleanup_resources import rollback_local_resources, resource_snapshot, RevocableCredentialLeaseStore
from execution_subsystem.cleanup_service import ExecutionCleanupService
from execution_subsystem.credential_leases import CredentialLeaseStore
from execution_subsystem.evidence_repository import ExecutionEvidenceRepository
from execution_subsystem.execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json, with_integrity)
from execution_subsystem.governance_client import ExecutionGovernanceClient
from execution_subsystem.request_repository import ExecutionRepositoryError, ExecutionRequestRepository
from execution_subsystem.runtime_contract import START_SCHEMA
from execution_subsystem.runtime_control import RuntimeResources
from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
from execution_subsystem.sandbox_runtime import ResourceSandbox
from execution_subsystem.tool_registry import select_adapter
from execution_subsystem.vep_contract import canonical_vep_contract, verify_vep_export
from execution_subsystem.vep_repository import ExecutionVEPRepository
from execution_subsystem.vep_service import ExecutionVEPService
from run.stage6_8_audit import audit_file
from tests.test_stage6_1_canonical_execution_request_contract import intake_for, http
from tests.test_stage6_2_authoritative_execution_authorization import NOW, seed_mission
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority, authority_server
from tests.test_stage6_4_authorized_tool_adapters_sandboxing import adapter_seed, target_server
from tests.test_stage6_5_execution_runtime_control import wait_for, cancellation, BeforeIOFailure, retry_payload
from tests.test_stage6_7_vep_construction_integrity import construction_payload
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline
from tests import test_stage4_6_pentest_workflow_orchestrator_skeleton as materialize_module

CREDENTIAL_POLICY = {"credential_usage_allowed":True,"credentials_lease":{"lease_id":"credlease-stage68","required":True}}


@pytest.fixture
def ctx(tmp_path, adapter_seed, target_server):
    pdb,mdb,run = adapter_seed
    pentest,mission = tmp_path/"pentest.db",tmp_path/"mission.db"
    shutil.copy2(pdb,pentest)
    shutil.copy2(mdb,mission)
    authority,now = UniqueAuthority(),[NOW]
    service = ExecutionCleanupService(ExecutionCleanupRepository(tmp_path/"execution.db"),
        ExecutionAuthorizationProposalSource(pentest),MissionAuthorizationSource(mission),authority,clock=lambda:now[0])
    request = service.create_request(intake_for(run,"stage68"))
    intake = {"schema_version":START_SCHEMA,"invocation_request_id":"toolreq-stage68","idempotency_key":"idem-stage68",
        "execution_id":request["execution_id"],"envelope_sha256":request["envelope"]["integrity"]["canonical_sha256"],"requested_by":"stage68-test"}
    target_server[2].update({"sleep":0,"redirect":False})
    target_server[1].clear()
    try:
        yield service,intake,authority,request,target_server,now
    finally:
        service.close()
        target_server[2].update({"sleep":0,"redirect":False})


@pytest.fixture(scope="module")
def credential_seed(tmp_path_factory,target_server):
    original = materialize_module.sample_boundary
    def boundary():
        out = original()
        out["scope"]["targets"][0] = {"target_type":"URL","target_value":target_server[0]}
        out["roe"]["credential_usage_allowed"] = True
        return out
    materialize_module.sample_boundary = boundary
    root = tmp_path_factory.mktemp("stage68-credential-seed")
    try:
        repo,bound,_,_,runs = _pipeline(root,"stage68-credential",through_stage="5.6")
    finally:
        materialize_module.sample_boundary = original
    mission = root/"mission.db"
    seed_mission(mission,bound)
    return repo.sqlite_path,mission,runs["5.6"]


@pytest.fixture
def credential_ctx(tmp_path,credential_seed,target_server,monkeypatch):
    pdb,mdb,run = credential_seed
    pentest,mission = tmp_path/"pentest.db",tmp_path/"mission.db"
    shutil.copy2(pdb,pentest)
    shutil.copy2(mdb,mission)
    authority = UniqueAuthority()
    authority.mutate = lambda r:r.update({"constraints":deepcopy(CREDENTIAL_POLICY)})
    path = tmp_path/"leases.json"
    service = ExecutionCleanupService(ExecutionCleanupRepository(tmp_path/"execution.db"),
        ExecutionAuthorizationProposalSource(pentest),MissionAuthorizationSource(mission),authority,clock=lambda:NOW,
        credential_store=CredentialLeaseStore(path))
    request = service.create_request(intake_for(run,"stage68-credential"))
    req = request["envelope"]["execution_request"]
    lease = {"lease_id":"credlease-stage68","mission_id":req["mission_id"],"execution_id":req["execution_id"],
        "target":req["target"],"adapter_id":select_adapter(req).adapter_id,
        "issued_at":"2026-10-02T09:15:00Z","expires_at":"2026-10-02T09:30:00Z",
        "secret_environment":"APTS_CRED_STAGE68_TEST","revoked":False}
    path.write_text(json.dumps([lease]))
    monkeypatch.setenv("APTS_CRED_STAGE68_TEST","SYNTHETIC-STAGE68-CREDENTIAL")
    intake = {"schema_version":START_SCHEMA,"invocation_request_id":"toolreq-stage68-credential","idempotency_key":"idem-stage68-credential",
        "execution_id":req["execution_id"],"envelope_sha256":request["envelope"]["integrity"]["canonical_sha256"],"requested_by":"stage68-test"}
    target_server[1].clear()
    target_server[2].update({"sleep":0,"redirect":False})
    try:
        yield service,intake,authority,request,target_server,[NOW]
    finally:
        service.close()


def post_payload(item, vep):
    value = vep["vep"]
    return {"schema_version":INTAKE_SCHEMA,"attempt_id":item["attempt_id"],
        "envelope_sha256":item["record"]["runtime_intake"]["envelope_sha256"],
        "evidence_sha256":value["evidence"]["integrity"]["canonical_sha256"],"expected_head_sha256":item["head_sha256"],
        "vep_id":value["vep_id"],"vep_sha256":value["integrity"]["canonical_sha256"]}


def ready(ctx):
    service = ctx[0]
    item = wait_for(service,service.start_execution(ctx[1])["attempt_id"])
    vep = service.construct_vep(construction_payload(service,item))
    return item,vep,post_payload(item,vep)


def completed(ctx):
    item,vep,payload = ready(ctx)
    result = ctx[0].complete_post_action(payload)
    return item,vep,payload,result


def exported(ctx):
    item,_,_,result = completed(ctx)
    return ctx[0].export_post_action(result["post_action_id"],item["attempt_id"])


@contextmanager
def server_for(service):
    handler = type("TestStage68Handler",(ExecutionSubsystemStage68Handler,),{"service":service})
    server = ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def resign(value,domain=REPORT_DOMAIN):
    return with_integrity({k:v for k,v in value.items() if k!="integrity"},domain)


def test_exact_stage67_predecessor_and_health(ctx):
    contract = canonical_cleanup_contract()
    assert verify_cleanup_contract(contract)
    assert contract["predecessor"]["contract_sha256"] == canonical_vep_contract()["integrity"]["canonical_sha256"]
    assert ctx[0].health()["control_version"] == CONTROL_VERSION
    assert ctx[0].health()["execution_repository_migration_level"] == 8
    assert ctx[0].health()["next_stage"] == "6.9"
    contract["rollback"]["caller_paths_commands_pids"] = True
    assert not verify_cleanup_contract(contract)


def test_real_native_local_cleanup_and_six_phase_closure(ctx):
    item,vep,_,result = completed(ctx)
    value = ctx[0].export_post_action(result["post_action_id"],item["attempt_id"])
    proof = value["receipt"]
    assert item["state"] == "SUCCEEDED" and result["created"] and result["execution_closed"]
    assert result["status"] == "CLOSED_LOCAL_RESOURCES" and result["cleanup_verified"]
    assert [p["phase"] for p in result["report"]["phases"]] == PHASES
    assert verify_receipt(proof) and verify_post_action_export(value)
    worker = proof["resources"]["after_rollback"]["workers"][0]
    assert worker["process_started"] and worker["worker_exit_confirmed"] and worker["return_code"] == 0
    assert worker["temporary_directory_removed"] and worker["pipes_closed"] and worker["readers_stopped"] and worker["job_handle_released"]
    assert proof["resources"]["after_rollback"]["socket_count"] == 1
    assert proof["resources"]["after_rollback"]["sockets_closed"] and proof["resources"]["after_rollback"]["runtime_closers_detached"]
    assert not result["report"]["rollback"]["target_state_restored"]
    assert not result["target_state_verified"] and not result["execution_authorized"]
    assert value["vep_export"]["vep"] == vep["vep"] and not vep["vep"]["semantics"]["cleanup_verified"]


def test_concurrent_completion_replay_preserves_first_record_without_target_or_authority(ctx):
    item,_,payload = ready(ctx)
    counts = len(ctx[2].calls),len(ctx[4][1])
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda _:ctx[0].complete_post_action(payload),range(4)))
    assert sum(v["created"] for v in values) == 1
    ctx[5][0] += timedelta(days=90)
    assert ctx[0].complete_post_action(payload)["report"] == values[0]["report"]
    assert len(ctx[0].list_post_actions(ctx[1]["execution_id"])["reports"]) == 1
    assert counts == (len(ctx[2].calls),len(ctx[4][1]))


@pytest.mark.parametrize("field",["decision","path","command","pid","cleanup_verified","target_state_restored","credential_secret","receipt","evidence"])
def test_caller_cleanup_authority_and_resource_overrides_rejected(ctx,field):
    payload = {"schema_version":INTAKE_SCHEMA,"attempt_id":"xattempt-forged","vep_id":"xvep-forged",
        **{k:"a"*64 for k in ("envelope_sha256","evidence_sha256","expected_head_sha256","vep_sha256")},field:"FAKE"}
    with pytest.raises(ExecutionRequestValidationError):
        ctx[0].complete_post_action(payload)
    assert not ctx[2].calls and not ctx[4][1]


@pytest.mark.parametrize("field",["envelope_sha256","evidence_sha256","expected_head_sha256","vep_sha256"])
def test_mismatched_exact_reference_rejected_before_and_after_report(ctx,field):
    _,_,payload = ready(ctx)
    bad = {**payload,field:"0"*64}
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].complete_post_action(bad)
    ctx[0].complete_post_action(payload)
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].complete_post_action(bad)


def test_wrong_attempt_vep_binding_rejected(ctx):
    item,_,_,result = completed(ctx)
    with pytest.raises(ExecutionSourceNotFound):
        ctx[0].get_post_action(result["post_action_id"],"xattempt-other")
    with pytest.raises(ExecutionSourceNotFound):
        ctx[0].complete_post_action({"schema_version":INTAKE_SCHEMA,"attempt_id":item["attempt_id"],"vep_id":"xvep-other",
            **{k:"a"*64 for k in ("envelope_sha256","evidence_sha256","expected_head_sha256","vep_sha256")}})


def test_post_action_requires_preexisting_vep_and_does_not_construct_it(ctx):
    item = wait_for(ctx[0],ctx[0].start_execution(ctx[1])["attempt_id"])
    with pytest.raises(ExecutionSourceNotFound):
        ctx[0].complete_post_action({"schema_version":INTAKE_SCHEMA,"attempt_id":item["attempt_id"],"vep_id":"xvep-missing",
            **{k:"a"*64 for k in ("envelope_sha256","evidence_sha256","expected_head_sha256","vep_sha256")}})
    assert ctx[0].list_veps(ctx[1]["execution_id"])["count"] == 0


def test_cancelled_partial_attempt_can_close_only_verified_local_resources(ctx):
    ctx[4][2]["sleep"] = 1.0
    started = ctx[0].start_execution(ctx[1])
    active = wait_for(ctx[0],started["attempt_id"],lambda x:x["state"]=="RUNNING")
    deadline = time.monotonic()+3
    while not ctx[4][1] and time.monotonic()<deadline:
        Event().wait(.01)
    assert ctx[4][1]
    ctx[0].control(cancellation(active))
    item = wait_for(ctx[0],active["attempt_id"])
    vep = ctx[0].construct_vep(construction_payload(ctx[0],item))
    result = ctx[0].complete_post_action(post_payload(item,vep))
    assert item["state"] == "CANCELLED" and result["execution_closed"]
    assert result["report"]["effect_verification"]["capture_status"] == "PARTIAL"
    assert not result["target_state_verified"]


def test_failure_before_target_io_closes_verified_local_baseline(ctx):
    ctx[0].broker = BeforeIOFailure()
    _,_,_,result = completed(ctx)
    assert result["execution_closed"] and result["report"]["effect_verification"]["adapter_status"] == "FAILED"
    assert len(ctx[4][1]) == 0


def test_real_external_authority_http_then_post_action_has_no_authority_call(ctx):
    with authority_server(ctx[2]) as url:
        ctx[0].governance_client = ExecutionGovernanceClient(url)
        item = wait_for(ctx[0],ctx[0].start_execution(ctx[1])["attempt_id"])
    counts = len(ctx[2].calls),len(ctx[4][1])
    vep = ctx[0].construct_vep(construction_payload(ctx[0],item))
    result = ctx[0].complete_post_action(post_payload(item,vep))
    assert result["execution_closed"] and counts == (len(ctx[2].calls),len(ctx[4][1]))


@pytest.mark.parametrize("field,value",[("state","BLOCKED_REQUIRES_REVIEW"),("execution_closed",False),("cleanup_verified",False),
    ("blocking_reasons",["FAKE"]),("closure_scope","TARGET_STATE"),("receipt_sha256","0"*64)])
def test_resealed_report_cannot_forge_derived_state(ctx,field,value):
    export = exported(ctx)
    export["report"][field] = value
    export["report"] = resign(export["report"])
    assert not verify_post_action_export(export)


@pytest.mark.parametrize("field",["worker_exit_confirmed","pipes_closed","readers_stopped","temporary_directory_removed","job_handle_released"])
def test_failed_native_cleanup_check_cannot_keep_success_even_when_resealed(ctx,field):
    export = exported(ctx)
    export["receipt"]["resources"]["after_rollback"]["workers"][0][field] = False
    export["receipt"] = resign(export["receipt"],RECEIPT_DOMAIN)
    assert not verify_receipt(export["receipt"]) and not verify_post_action_export(export)


def test_valid_negative_resource_receipt_generates_blocked_report(ctx):
    export = exported(ctx)
    receipt = deepcopy(export["receipt"])
    receipt["resources"]["after_rollback"]["workers"][0]["temporary_directory_removed"] = False
    receipt["local_resources_verified"] = False
    receipt = resign(receipt,RECEIPT_DOMAIN)
    assert verify_receipt(receipt)
    value = build_report(export["vep_export"]["vep"],receipt,None,export["report"]["evaluated_at"])
    assert value["state"] == "BLOCKED_REQUIRES_REVIEW" and not value["execution_closed"]
    assert "LOCAL_RESOURCE_CLEANUP_UNPROVEN" in value["blocking_reasons"]


def test_retained_artifact_byte_corruption_invalidates_post_action_export(ctx):
    import base64
    export = exported(ctx)
    export["vep_export"]["artifacts"][0]["content_base64"] = base64.b64encode(b"{}").decode()
    assert not verify_post_action_export(export)


def test_read_replay_and_export_remain_available_without_upstream_databases(ctx):
    item,_,payload,result = completed(ctx)
    ctx[0].proposal_source.sqlite_path.unlink()
    ctx[0].mission_source.sqlite_path.unlink()
    ctx[0].governance_client = None
    assert not ctx[0].complete_post_action(payload)["created"]
    assert verify_post_action_export(ctx[0].export_post_action(result["post_action_id"],item["attempt_id"]))


def test_acquired_credential_is_locally_revoked_and_cannot_claim_issuer_revocation(credential_ctx):
    item,_,payload,result = completed(credential_ctx)
    service = credential_ctx[0]
    assert item["invocation"]["result"]["credential_lease"] is not None
    assert item["invocation"]["result"]["reason_codes"] == ["CREDENTIALS_REQUIRE_TLS"]
    assert result["status"] == "BLOCKED_REQUIRES_REVIEW" and not result["execution_closed"]
    assert result["cleanup_verified"] and result["report"]["credentials"]["local_access"] == "REVOKED"
    assert result["blocking_reasons"] == ["ISSUER_CREDENTIAL_REVOCATION_NOT_PROVEN"]
    export = service.export_post_action(result["post_action_id"],item["attempt_id"])
    assert verify_post_action_export(export) and export["revocation"]["issuer_revocation_proven"] is False
    assert "SYNTHETIC-STAGE68-CREDENTIAL" not in canonical_json(export)
    req = credential_ctx[3]["envelope"]["execution_request"]
    with pytest.raises(ExecutionSourceRejected,match="LOCALLY_REVOKED"):
        service.credential_store.acquire("credlease-stage68",req,select_adapter(req),NOW)
    assert not credential_ctx[4][1]


def test_local_lease_revocation_survives_restart_and_config_reset(credential_ctx):
    item,_,payload,result = completed(credential_ctx)
    service = credential_ctx[0]
    config = service.credential_store.delegate
    service.close()
    resumed = ExecutionCleanupService(ExecutionCleanupRepository(service.repository.sqlite_path),service.proposal_source,service.mission_source,
        UniqueAuthority(),clock=lambda:NOW,credential_store=CredentialLeaseStore(config.config_path))
    try:
        req = credential_ctx[3]["envelope"]["execution_request"]
        with pytest.raises(ExecutionSourceRejected,match="LOCALLY_REVOKED"):
            resumed.credential_store.acquire("credlease-stage68",req,select_adapter(req),NOW)
        assert not resumed.complete_post_action(payload)["created"]
        assert resumed.get_post_action(result["post_action_id"],item["attempt_id"])["blocking_reasons"] == result["blocking_reasons"]
        assert not resumed.governance_client.calls
    finally:
        resumed.close()


def test_configured_but_unacquired_lease_can_close_after_local_revocation(credential_ctx):
    credential_ctx[0].credential_store.delegate.config_path.unlink()
    item,_,_,result = completed(credential_ctx)
    assert item["invocation"]["result"]["credential_lease"] is None
    assert result["execution_closed"] and result["report"]["credentials"]["local_access"] == "REVOKED"
    assert result["report"]["credentials"]["issuer_revocation"] == "NOT_REQUIRED_NO_LEASE_ACQUIRED"


@pytest.mark.parametrize("operation",["UPDATE","DELETE"])
def test_local_credential_revocations_are_sql_append_only(credential_ctx,operation):
    completed(credential_ctx)
    with sqlite3.connect(credential_ctx[0].repository.sqlite_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE execution_credential_revocations SET record_json=record_json" if operation=="UPDATE" else "DELETE FROM execution_credential_revocations")


def test_revocation_and_receipt_failure_roll_back_in_same_transaction(credential_ctx):
    service = credential_ctx[0]
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON execution_cleanup_receipts BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
    service.start_execution(credential_ctx[1])
    deadline = time.monotonic()+8
    while not service._failures and time.monotonic()<deadline:
        Event().wait(.02)
    assert service._failures
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        assert conn.execute("SELECT count(*) FROM execution_cleanup_receipts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM execution_credential_revocations").fetchone()[0] == 0


def test_resealed_issuer_revocation_and_scope_forgery_rejected(credential_ctx):
    export = exported(credential_ctx)
    export["revocation"]["issuer_revocation_proven"] = True
    from execution_subsystem.cleanup_contract import REVOCATION_DOMAIN
    export["revocation"] = resign(export["revocation"],REVOCATION_DOMAIN)
    assert not verify_post_action_export(export)


def test_manual_retry_gets_its_own_cleanup_receipt_and_report(ctx):
    ctx[0].broker = BeforeIOFailure()
    first,_,_,result = completed(ctx)
    ctx[5][0] += timedelta(seconds=2)
    second = wait_for(ctx[0],ctx[0].start_execution(retry_payload(ctx[1],first),retry=True)["attempt_id"])
    vep = ctx[0].construct_vep(construction_payload(ctx[0],second))
    next_result = ctx[0].complete_post_action(post_payload(second,vep))
    assert first["attempt_id"] != second["attempt_id"] and result["post_action_id"] != next_result["post_action_id"]
    assert next_result["execution_closed"] and ctx[0].list_post_actions(ctx[1]["execution_id"])["count"] == 2


def test_clock_before_vep_is_rejected_without_report_and_replay_does_not_move_time(ctx):
    _,_,payload = ready(ctx)
    ctx[5][0] -= timedelta(seconds=1)
    with pytest.raises(ExecutionRequestIntegrityError,match="predates"):
        ctx[0].complete_post_action(payload)
    assert ctx[0].list_post_actions(ctx[1]["execution_id"])["count"] == 0
    ctx[5][0] += timedelta(seconds=1)
    result = ctx[0].complete_post_action(payload)
    ctx[5][0] -= timedelta(seconds=1)
    assert ctx[0].complete_post_action(payload)["report"] == result["report"]


@pytest.mark.parametrize("table",["execution_cleanup_receipts","execution_post_action_reports"])
def test_tampered_database_index_is_detected_on_report_read(ctx,table):
    item,_,_,result = completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute(f"DROP TRIGGER {table}_no_update")
        conn.execute(f"UPDATE {table} SET record_sha256=?",("0"*64,))
    with pytest.raises(ExecutionRequestIntegrityError):
        ctx[0].get_post_action(result["post_action_id"],item["attempt_id"])


def test_receipt_cannot_be_reinserted_after_terminal_as_fabricated_backfill(ctx):
    completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_cleanup_receipts_no_delete")
        row = conn.execute("SELECT * FROM execution_cleanup_receipts").fetchone()
        conn.execute("DELETE FROM execution_cleanup_receipts")
        with pytest.raises(sqlite3.IntegrityError,match="enrolled"):
            conn.execute("INSERT INTO execution_cleanup_receipts VALUES (?,?,?,?,?,?,?)",row)


def test_unknown_future_database_and_missing_guards_rejected_without_mutation(tmp_path):
    path = tmp_path/"future.db"
    ExecutionCleanupRepository(path).initialize()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE execution_repository_meta SET migration_level=9")
    before = path.read_bytes()
    with pytest.raises(ExecutionRepositoryError):
        ExecutionCleanupRepository(path).initialize()
    assert path.read_bytes() == before
    missing = tmp_path/"missing_guard.db"
    ExecutionCleanupRepository(missing).initialize()
    with sqlite3.connect(missing) as conn:
        conn.execute("DROP TRIGGER execution_post_action_reports_terminal")
    before = missing.read_bytes()
    with pytest.raises(ExecutionRepositoryError):
        ExecutionCleanupRepository(missing).initialize()
    assert missing.read_bytes() == before


def test_upstream_sources_and_retained_evidence_unchanged_by_post_action(ctx):
    item,vep,payload = ready(ctx)
    import hashlib
    sources = [ctx[0].proposal_source.sqlite_path,ctx[0].mission_source.sqlite_path]
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
    before = ctx[0].export_vep(vep["vep_id"],item["attempt_id"])
    result = ctx[0].complete_post_action(payload)
    assert hashes == [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources]
    assert ctx[0].export_vep(vep["vep_id"],item["attempt_id"]) == before
    assert not result["evidence_deleted"] and not result["vep_modified"]


def test_atomic_report_failure_does_not_touch_runtime_vep_or_evidence(ctx):
    item,vep,payload = ready(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("CREATE TRIGGER reject_post_action BEFORE INSERT ON execution_post_action_reports BEGIN SELECT RAISE(ABORT,'storage failure'); END")
    with pytest.raises(ExecutionRepositoryError):
        ctx[0].complete_post_action(payload)
    assert ctx[0].repository.get_attempt(item["attempt_id"])["head_sha256"] == item["head_sha256"]
    assert ctx[0].export_vep(vep["vep_id"],item["attempt_id"])["vep"] == vep["vep"]
    assert ctx[0].list_post_actions(ctx[1]["execution_id"])["count"] == 0
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER reject_post_action")
    assert ctx[0].complete_post_action(payload)["execution_closed"]


@pytest.mark.parametrize("table",["execution_cleanup_receipts","execution_post_action_reports"])
@pytest.mark.parametrize("operation",["UPDATE","DELETE"])
def test_new_records_are_sql_append_only(ctx,table,operation):
    completed(ctx)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE {table} SET record_json=record_json" if operation=="UPDATE" else f"DELETE FROM {table}")


def test_receipt_storage_failure_keeps_runtime_nonterminal_and_recovery_blocks_closure(ctx):
    service = ctx[0]
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("CREATE TRIGGER reject_cleanup BEFORE INSERT ON execution_cleanup_receipts BEGIN SELECT RAISE(ABORT,'storage failure'); END")
    started = service.start_execution(ctx[1])
    deadline = time.monotonic()+8
    while not service._failures and time.monotonic()<deadline:
        Event().wait(.02)
    assert service._failures and service.health()["status"] == "degraded"
    assert service.repository.get_attempt(started["attempt_id"])["state"] not in {"SUCCEEDED","ABORTED"}
    service.close()
    resumed = ExecutionCleanupService(ExecutionCleanupRepository(service.repository.sqlite_path),service.proposal_source,service.mission_source,
        UniqueAuthority(),clock=lambda:NOW)
    try:
        item = resumed.repository.get_attempt(started["attempt_id"])
        vep = resumed.construct_vep(construction_payload(resumed,item))
        result = resumed.complete_post_action(post_payload(item,vep))
        assert not result["execution_closed"] and "LOCAL_RESOURCE_RECEIPT_MISSING_NO_BACKFILL" in result["blocking_reasons"]
        assert "RECOVERY_TARGET_IO_UNCERTAIN" in result["blocking_reasons"]
    finally:
        resumed.close()


def test_native_resource_compensation_retries_only_exact_owned_temp_directory(tmp_path,monkeypatch):
    guard = RuntimeResources(time.monotonic()+10)
    guard.cleanup_workers,guard.cleanup_sockets = [],[]
    worker = ResourceSandbox(DEFAULT_LIMITS,runtime=guard)
    worker.__enter__()
    folder = Path(worker.folder.name)
    unrelated = tmp_path/"unrelated"
    unrelated.mkdir()
    (unrelated/"keep.txt").write_text("preserve")
    original = worker.folder.cleanup
    def fail_once():
        monkeypatch.setattr(worker.folder,"cleanup",original)
        raise PermissionError("synthetic transient cleanup failure")
    monkeypatch.setattr(worker.folder,"cleanup",fail_once)
    with pytest.raises(PermissionError):
        worker.close()
    assert folder.exists()
    receipt = rollback_local_resources(guard)
    assert receipt["rollback_attempted"] and not receipt["rollback_errors"] and not folder.exists()
    assert (unrelated/"keep.txt").read_text() == "preserve"
    assert resource_snapshot(guard)["workers"][0]["worker_exit_confirmed"]


@pytest.mark.parametrize("repository_class",[ExecutionRequestRepository,ExecutionRuntimeRepository,ExecutionEvidenceRepository,ExecutionVEPRepository])
def test_upgrade_predecessor_database_atomically_to_migration8_and_refuse_downgrade(tmp_path,repository_class):
    path = tmp_path/"upgrade.db"
    repository_class(path).initialize()
    assert ExecutionCleanupRepository(path).migration_level() == 8
    before = path.read_bytes()
    with pytest.raises(ExecutionRepositoryError):
        repository_class(path).initialize()
    assert path.read_bytes() == before


def test_stage67_terminal_vep_upgrade_blocks_no_receipt_backfill(ctx):
    service = ctx[0]
    paths = service.repository.sqlite_path,service.proposal_source,service.mission_source
    service.close()
    legacy_path = paths[0].with_name("legacy.db")
    legacy = ExecutionVEPService(ExecutionVEPRepository(legacy_path),paths[1],paths[2],UniqueAuthority(),clock=lambda:NOW)
    try:
        legacy.create_request(ctx[3]["envelope"]["intake"])
        item = wait_for(legacy,legacy.start_execution(ctx[1])["attempt_id"])
        vep = legacy.construct_vep(construction_payload(legacy,item))
    finally:
        legacy.close()
    resumed = ExecutionCleanupService(ExecutionCleanupRepository(legacy_path),paths[1],paths[2],UniqueAuthority(),clock=lambda:NOW)
    try:
        result = resumed.complete_post_action(post_payload(item,vep))
        assert result["status"] == "BLOCKED_REQUIRES_REVIEW"
        assert result["blocking_reasons"] == ["LOCAL_RESOURCE_RECEIPT_MISSING_NO_BACKFILL"]
        assert not result["execution_closed"] and not resumed.governance_client.calls
    finally:
        resumed.close()


def test_http_post_read_verify_export_and_cache_headers(ctx):
    item,_,payload = ready(ctx)
    counts = len(ctx[2].calls),len(ctx[4][1])
    with server_for(ctx[0]) as url:
        code,result,_ = http(url+"/api/execution/post-actions",payload)
        assert code == 201 and result["execution_closed"]
        assert http(url+"/api/execution/post-actions",payload)[0] == 200
        route = url+f'/api/execution/post-actions/{result["post_action_id"]}'
        assert http(route+f'?attempt_id={item["attempt_id"]}')[0] == 200
        assert http(route+f'/verify?attempt_id={item["attempt_id"]}')[1]["execution_closed"]
        import urllib.request
        with urllib.request.urlopen(route+f'/export?attempt_id={item["attempt_id"]}') as response:
            assert response.headers["Cache-Control"] == "no-store" and response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Post-Action-SHA256"] == result["report_sha256"]
            assert verify_post_action_export(json.loads(response.read()))
        assert http(url+"/api/execution/cleanup/attempts/"+item["attempt_id"])[1]["cleanup_receipt_available"]
        assert http(url+"/api/execution/post-actions?execution_id="+ctx[1]["execution_id"])[1]["count"] == 1
        proof = ctx[0].export_post_action(result["post_action_id"],item["attempt_id"])
        proof_path = ctx[0].repository.sqlite_path.parent/"post_action_offline_export.json"
        proof_path.write_text(canonical_json(proof),encoding="utf-8")
        assert audit_file(proof_path)["status"] == "VERIFIED_INTERNAL_LINEAGE"
        (proof_path.parent/"post_action_http_proof_summary.json").write_text(json.dumps({"status":"PASS",
            "http_created_status":201,"http_replay_status":200,"closure_state":result["status"],
            "artifact_count":len(proof["vep_export"]["artifacts"]),"report_sha256":result["report_sha256"],
            "backend":proof["receipt"]["resources"]["after_rollback"]["workers"][0]["backend"],
            "target_scope":"ISOLATED_LOOPBACK_ONLY","live_user_mission_exercised":False},indent=2)+"\n")
    assert counts == (len(ctx[2].calls),len(ctx[4][1]))


@pytest.mark.parametrize("route",["post-actions?execution_id=exec-x&execution_id=exec-y","post-actions?execution_id=exec-x&limit=0",
    "post-actions?execution_id=exec-x&limit=101","post-actions/xcleanup-x?attempt_id=xattempt-x&attempt_id=xattempt-y",
    "cleanup-rollback-post-action-verification-contract?decision=ALLOW","cleanup/attempts/xattempt-x?path=data"])
def test_http_duplicate_query_or_overrides_rejected(ctx,route):
    with server_for(ctx[0]) as url:
        assert http(url+"/api/execution/"+route)[0] == 400


@pytest.mark.parametrize("route",["post-actions/upload","post-actions/xcleanup-x/verify","cleanup/rollback","cleanup/credentials/revoke"])
def test_http_caller_cleanup_and_verify_upload_forbidden(ctx,route):
    with server_for(ctx[0]) as url:
        assert http(url+"/api/execution/"+route,{"command":"FAKE"})[0] == 409
    assert not ctx[2].calls and not ctx[4][1]


@pytest.mark.parametrize("host",["0.0.0.0","::","192.0.2.1","example.com"])
def test_non_loopback_post_action_bind_rejected(host):
    with pytest.raises(ExecutionRequestValidationError):
        serve(host)


def test_offline_audit_preserves_blocked_vs_closed_semantics_and_rejects_duplicate_keys(ctx,tmp_path):
    export = exported(ctx)
    path = tmp_path/"post_action.json"
    path.write_text(canonical_json(export))
    assert audit_file(path)["execution_closed"]
    path.write_text('{"schema_version":"one","schema_version":"two"}')
    assert audit_file(path)["status"] == "INVALID"


def child_crash(paths,intake,channel,phase,credential_policy=None):
    try:
        authority = UniqueAuthority()
        if credential_policy:
            authority.mutate = lambda r:r.update({"constraints":deepcopy(credential_policy)})
        service = ExecutionCleanupService(ExecutionCleanupRepository(paths[0]),ExecutionAuthorizationProposalSource(paths[1]),
            MissionAuthorizationSource(paths[2]),authority,clock=lambda:NOW)
        if phase == "DURABLE_LOCAL_RECEIPT":
            def hold(identity,*args,**kwargs):
                channel.send(("READY",identity))
                Event().wait(60)
            service.repository.finalize = hold
        else:
            def hold(claim,envelope,**kwargs):
                from execution_subsystem.runtime_contract import attempt_id
                channel.send(("READY",attempt_id(claim["invocation_id"])))
                Event().wait(60)
            service._run_reserved = hold
        service.start_execution(intake)
        Event().wait(60)
    except BaseException as exc:
        channel.send(("ERROR",type(exc).__name__,str(exc)))


@pytest.mark.parametrize("phase",["BEFORE_NATIVE_WORKER","DURABLE_LOCAL_RECEIPT"])
def test_real_owner_crash_recovery_blocks_unproven_cleanup_without_redispatch(ctx,phase):
    service = ctx[0]
    paths = [str(service.repository.sqlite_path),str(service.proposal_source.sqlite_path),str(service.mission_source.sqlite_path)]
    service.close()
    mp = multiprocessing.get_context("spawn")
    parent,child = mp.Pipe()
    process = mp.Process(target=child_crash,args=(paths,ctx[1],child,phase))
    process.start()
    try:
        assert parent.poll(25),"child runtime did not reach durable cleanup barrier"
        message = parent.recv()
        assert message[0] == "READY",message
        with pytest.raises(ExecutionRepositoryError):
            ExecutionCleanupService(ExecutionCleanupRepository(paths[0]))
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        counts = len(ctx[4][1])
        resumed = ExecutionCleanupService(ExecutionCleanupRepository(paths[0]),ExecutionAuthorizationProposalSource(paths[1]),
            MissionAuthorizationSource(paths[2]),UniqueAuthority(),clock=lambda:NOW)
        try:
            item = resumed.repository.get_attempt(message[1])
            vep = resumed.construct_vep(construction_payload(resumed,item))
            if phase == "DURABLE_LOCAL_RECEIPT":
                result = resumed.complete_post_action(post_payload(item,vep))
                assert result["status"] == "BLOCKED_REQUIRES_REVIEW" and not result["execution_closed"]
                assert "CLEANUP_RECEIPT_PRETERMINAL_RESULT_NOT_DURABLE" in result["blocking_reasons"]
                assert result["report"]["effect_verification"]["adapter_status"] is None
                assert verify_post_action_export(resumed.export_post_action(result["post_action_id"],item["attempt_id"]))
            else:
                result = resumed.complete_post_action(post_payload(item,vep))
                assert result["status"] == "BLOCKED_REQUIRES_REVIEW" and not result["execution_closed"]
                assert "RECOVERY_TARGET_IO_UNCERTAIN" in result["blocking_reasons"]
                assert verify_post_action_export(resumed.export_post_action(result["post_action_id"],item["attempt_id"]))
            assert not resumed.governance_client.calls and len(ctx[4][1]) == counts
        finally:
            resumed.close()
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()
        child.close()


def test_real_crash_with_credential_lease_revokes_local_access_and_keeps_acquisition_unknown(credential_ctx):
    service = credential_ctx[0]
    paths = [str(service.repository.sqlite_path),str(service.proposal_source.sqlite_path),str(service.mission_source.sqlite_path)]
    config = service.credential_store.delegate
    service.close()
    mp = multiprocessing.get_context("spawn")
    parent,child = mp.Pipe()
    process = mp.Process(target=child_crash,args=(paths,credential_ctx[1],child,"BEFORE_NATIVE_WORKER",CREDENTIAL_POLICY))
    process.start()
    try:
        assert parent.poll(25)
        ready_message = parent.recv()
        assert ready_message[0] == "READY",ready_message
        process.terminate()
        process.join(timeout=10)
        resumed = ExecutionCleanupService(ExecutionCleanupRepository(paths[0]),ExecutionAuthorizationProposalSource(paths[1]),
            MissionAuthorizationSource(paths[2]),UniqueAuthority(),clock=lambda:NOW,credential_store=config)
        try:
            item = resumed.repository.get_attempt(ready_message[1])
            vep = resumed.construct_vep(construction_payload(resumed,item))
            result = resumed.complete_post_action(post_payload(item,vep))
            assert not result["execution_closed"] and result["report"]["credentials"]["lease_acquired"] is None
            assert "CREDENTIAL_ACQUISITION_UNCERTAIN" in result["blocking_reasons"]
            assert result["report"]["credentials"]["local_access"] == "REVOKED"
            req = credential_ctx[3]["envelope"]["execution_request"]
            with pytest.raises(ExecutionSourceRejected,match="LOCALLY_REVOKED"):
                resumed.credential_store.acquire("credlease-stage68",req,select_adapter(req),NOW)
            assert verify_post_action_export(resumed.export_post_action(result["post_action_id"],item["attempt_id"]))
            assert not resumed.governance_client.calls and not credential_ctx[4][1]
        finally:
            resumed.close()
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        parent.close()
        child.close()
