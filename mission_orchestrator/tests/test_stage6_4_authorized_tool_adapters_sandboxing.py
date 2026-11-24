from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import shutil
import socket
import sqlite3
from threading import Thread
import time
from uuid import uuid4

import pytest

from execution_subsystem.adapter_api import ExecutionSubsystemStage64Handler, ROUTE, serve
from execution_subsystem.adapter_contract import (
    ADAPTER_CONTROL_VERSION, ADAPTER_INTAKE_SCHEMA, CLAIM_DOMAIN, RESULT_DOMAIN, adapter_intake_json_schema,
    canonical_adapter_contract, normalize_adapter_intake, verify_adapter_contract, verify_adapter_claim, verify_adapter_result,
)
from execution_subsystem.adapter_policy import DEFAULT_LIMITS, compile_runtime_policy
from execution_subsystem.adapter_repository import ExecutionAdapterRepository
from execution_subsystem.adapter_service import ExecutionAdapterService
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.credential_leases import CredentialLeaseStore
from execution_subsystem.execution_contract import (
    ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionRequestValidationError, ExecutionSourceRejected,
    canonical_json, with_integrity,
)
from execution_subsystem.gateway_contract import canonical_execution_gateway_contract
from execution_subsystem.gateway_repository import ExecutionGatewayRepository
from execution_subsystem.gateway_service import ExecutionGatewayService
from execution_subsystem.gateway_contract import GATEWAY_INTAKE_SCHEMA
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.request_repository import ExecutionRequestRepository
from execution_subsystem.governance_client import ExecutionGovernanceClient
from execution_subsystem.request_repository import ExecutionRepositoryError
from execution_subsystem.sandbox_runtime import ResourceSandbox
from execution_subsystem.target_broker import TargetBroker, PinnedTarget, parse_endpoint
from execution_subsystem.tool_registry import ADAPTERS, select_adapter
from tests.test_stage6_1_canonical_execution_request_contract import intake_for, http as baseline_http
from tests.test_stage6_2_authoritative_execution_authorization import NOW, seed_mission
from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority, authority_server
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline
from tests import test_stage4_6_pentest_workflow_orchestrator_skeleton as materialize_module


def http(url, method="GET", payload=None):
    if method == "GET":
        return baseline_http(url)
    return baseline_http(url, payload)


@pytest.fixture(scope="module")
def target_server():
    calls = []
    behavior = {"sleep": 0, "redirect": False}
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            calls.append({"path": self.path, "headers": dict(self.headers)})
            if behavior["sleep"]:
                time.sleep(behavior["sleep"])
            self.send_response(302 if behavior["redirect"] else 200)
            self.send_header("Location", "http://192.0.2.1/outside")
            self.send_header("Set-Cookie", "secret=SENSITIVE_TARGET_COOKIE")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/status", calls, behavior
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.fixture(scope="module")
def adapter_seed(tmp_path_factory, target_server):
    original = materialize_module.sample_boundary
    def boundary():
        out = original()
        out["scope"]["targets"][0] = {"target_type": "URL", "target_value": target_server[0]}
        return out
    materialize_module.sample_boundary = boundary
    root = tmp_path_factory.mktemp("stage64-seed")
    try:
        repo, bound, task, oid, runs = _pipeline(root, "stage64", through_stage="5.6")
    finally:
        materialize_module.sample_boundary = original
    mdb = root / "missions.db"
    seed_mission(mdb, bound)
    return repo.sqlite_path, mdb, runs["5.6"]


@pytest.fixture
def ctx(tmp_path, adapter_seed, target_server):
    pdb, mdb, run = adapter_seed
    pentest, mission = tmp_path / "pentest.db", tmp_path / "mission.db"
    shutil.copy2(pdb, pentest); shutil.copy2(mdb, mission)
    authority = UniqueAuthority()
    service = ExecutionAdapterService(ExecutionAdapterRepository(tmp_path / "execution.db"),
        ExecutionAuthorizationProposalSource(pentest), MissionAuthorizationSource(mission), authority, clock=lambda: NOW)
    request = service.create_request(intake_for(run, "stage64"))
    intake = {"schema_version": ADAPTER_INTAKE_SCHEMA, "invocation_request_id": "toolreq-stage64", "idempotency_key": "idem-tool-stage64",
              "execution_id": request["execution_id"], "envelope_sha256": request["envelope"]["integrity"]["canonical_sha256"], "requested_by": "stage64-test"}
    target_server[2].update({"sleep": 0, "redirect": False})
    return service, intake, authority, request, target_server


def new_intake(intake):
    nonce = uuid4().hex
    return {**intake, "invocation_request_id": "toolreq-" + nonce, "idempotency_key": "idem-tool-" + nonce}


def new_execution(ctx):
    service, intake, _, stored, _ = ctx
    source={**stored["envelope"]["intake"],"request_id":"ereq-"+uuid4().hex,"idempotency_key":"idem-"+uuid4().hex}
    req=service.create_request(source)
    return {**new_intake(intake),"execution_id":req["execution_id"],"envelope_sha256":req["envelope"]["integrity"]["canonical_sha256"]}


def invoke_process(paths, intake):
    service=ExecutionAdapterService(ExecutionAdapterRepository(paths[0]),ExecutionAuthorizationProposalSource(paths[1]),
        MissionAuthorizationSource(paths[2]),UniqueAuthority(),clock=lambda:NOW)
    result=service.invoke_tool(intake)
    return result["record"]["status"], None if result["result"] is None else result["result"]["status"]


@contextmanager
def server_for(service):
    handler = type("IsolatedStage64Handler", (ExecutionSubsystemStage64Handler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def policy_authorization(ctx, constraints):
    service, intake, authority, _, _ = ctx
    authority.mutate = lambda result: result.update({"constraints": constraints})
    return service._fresh_authorization(intake)


def test_contract_exact_predecessor_and_five_families():
    contract = canonical_adapter_contract()
    assert contract["predecessor"]["contract_sha256"] == canonical_execution_gateway_contract()["integrity"]["canonical_sha256"]
    assert len({a.family for a in ADAPTERS}) == 5
    assert contract["repository"]["migration_level"] == 4 and contract["next_stage"] == "6.5"
    assert verify_adapter_contract(contract)
    contract["sandbox"]["shell_supported"] = True
    assert not verify_adapter_contract(contract)


def test_published_schema_is_exact():
    path = Path(__file__).resolve().parents[1] / "execution_subsystem/schemas/execution_adapter_intake_v1.schema.json"
    assert json.loads(path.read_text()) == adapter_intake_json_schema()


def test_real_target_only_after_two_fresh_authorizations_and_native_worker(ctx):
    service, intake, authority, request, target = ctx
    before = len(target[1])
    source_bytes = [p.read_bytes() for p in (service.mission_source.sqlite_path, service.proposal_source.sqlite_path)]
    result = service.invoke_tool(intake)
    assert result["record"]["status"] == "RESERVED" and result["result"]["status"] == "SUCCEEDED"
    assert len(authority.calls) == 2 and len(target[1]) == before+1
    assert result["result"]["sandbox_backend"] in {"SECCOMP_RLIMIT", "JOB_OBJECT_FIXED_WORKER"}
    assert result["result"]["observation"]["http_status"] == 200
    assert result["result"]["observation"]["expected_evidence_confirmed"] is False
    assert result["result"]["semantics"]["vulnerability_confirmed"] is False
    assert verify_adapter_claim(result["record"]) and verify_adapter_result(result["result"])
    assert "SENSITIVE_TARGET_COOKIE" not in canonical_json(result)
    assert "response_b64" not in canonical_json(result)
    assert service.repository.get(intake["execution_id"])["envelope"] == request["envelope"]
    assert source_bytes == [p.read_bytes() for p in (service.mission_source.sqlite_path, service.proposal_source.sqlite_path)]
    assert result["usable_for_dispatch"] is False


@pytest.mark.parametrize("decision", ["DENY", "REVIEW"])
def test_no_target_or_worker_on_authoritative_deny_review(ctx, decision):
    service, intake, authority, _, target = ctx
    authority.decision = decision
    before = len(target[1])
    result = service.invoke_tool(intake)
    assert result["record"]["status"] == "BLOCKED" and result["result"] is None
    assert len(authority.calls) == 1 and len(target[1]) == before


@pytest.mark.parametrize("check", ["SCOPE", "ROE", "POLICY", "RISK", "EXPIRY", "REVOCATION", "TARGET", "TECHNIQUE"])
def test_failed_check_blocks_at_boundary(ctx, check):
    service, intake, authority, _, target = ctx
    def mutate(result):
        if len(authority.calls) == 2:
            result["execution_revalidation"]["checks"][check] = "FAIL"
    authority.mutate = mutate
    before = len(target[1])
    result = service.invoke_tool(intake)
    assert result["result"]["status"] == "BLOCKED" and len(target[1]) == before
    assert result["result"]["semantics"]["target_network_io_performed"] is False


@pytest.mark.parametrize("flag", ["revoked", "emergency_stop"])
def test_boundary_revocation_and_emergency_stop(ctx, flag):
    service, intake, authority, _, target = ctx
    authority.mutate = lambda r: r["execution_revalidation"].update({flag: len(authority.calls)==2})
    before = len(target[1]); result = service.invoke_tool(intake)
    assert result["result"]["status"] == "BLOCKED" and len(target[1]) == before


@pytest.mark.parametrize("extra", ["decision", "authorization_id", "adapter_id", "command", "parameters", "target", "governance_url", "sandbox", "credentials", "payload", "timeout", "proposing_agent"])
def test_caller_cannot_override_control_or_executable_inputs(ctx, extra):
    with pytest.raises(ExecutionRequestValidationError):
        ctx[0].invoke_tool({**ctx[1], extra: "ALLOW"})
    assert not ctx[2].calls


def test_replay_and_restart_are_historical_and_do_not_query_gss(ctx):
    service, intake, authority, _, target = ctx
    original = service.invoke_tool(intake)
    before = (len(authority.calls), len(target[1]))
    service.mission_source.current_context = lambda _: (_ for _ in ()).throw(RuntimeError("offline"))
    replay = service.invoke_tool(intake)
    assert replay["result"] == original["result"] and replay["created"] is False
    restarted = ExecutionAdapterService(ExecutionAdapterRepository(service.repository.sqlite_path), service.proposal_source,
        service.mission_source, authority, clock=lambda: NOW)
    assert restarted.invoke_tool(intake)["record"] == original["record"]
    assert before == (len(authority.calls), len(target[1]))


def test_new_key_same_execution_is_blocked_without_reexecution(ctx):
    service, intake, authority, _, target = ctx
    service.invoke_tool(intake)
    before = len(target[1])
    duplicate = service.invoke_tool(new_intake(intake))
    assert duplicate["record"]["status"] == "BLOCKED" and "EXECUTION_ALREADY_RESERVED" in duplicate["record"]["reason_codes"]
    assert len(target[1]) == before


def test_idempotency_content_conflict(ctx):
    ctx[0].invoke_tool(ctx[1])
    with pytest.raises(ExecutionRequestConflict):
        ctx[0].invoke_tool({**ctx[1], "requested_by": "changed"})


def test_concurrent_same_intake_has_one_target_invocation(ctx):
    service, intake, authority, _, target = ctx
    before = len(target[1])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.invoke_tool(intake), range(4)))
    assert sum(r["created"] for r in results) == 1 and len(target[1]) == before+1 and len(authority.calls) == 2


def test_competing_services_share_one_durable_claim(ctx):
    service, intake, authority, _, target = ctx
    other = ExecutionAdapterService(ExecutionAdapterRepository(service.repository.sqlite_path), service.proposal_source,
        service.mission_source, authority, clock=lambda: NOW)
    before = len(target[1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda s: s.invoke_tool(intake), [service, other]))
    assert int(a["created"])+int(b["created"]) == 1 and len(target[1]) == before+1


def test_crash_after_reservation_cannot_redispatch_on_replay(ctx, monkeypatch):
    service, intake, _, _, target = ctx
    before = len(target[1])
    monkeypatch.setattr(service, "_run_reserved", lambda *args: (_ for _ in ()).throw(RuntimeError("simulated crash")))
    with pytest.raises(RuntimeError):
        service.invoke_tool(intake)
    replay = service.invoke_tool(intake)
    assert replay["invocation_incomplete"] is True and replay["created"] is False and len(target[1]) == before
    assert service.invoke_tool(new_intake(intake))["record"]["status"] == "BLOCKED"


def test_timeout_closes_worker_and_result_remains_consumed(ctx):
    service, intake, authority, _, target = ctx
    authority.mutate = lambda r: r.update({"constraints": {"timeout":0.25}})
    target[2]["sleep"] = 0.6
    result = service.invoke_tool(intake)
    assert result["result"]["status"] == "TIMEOUT"
    assert service.invoke_tool(intake)["created"] is False


def test_redirect_is_observed_without_following(ctx):
    ctx[4][2]["redirect"] = True
    before = len(ctx[4][1]); result = ctx[0].invoke_tool(ctx[1])
    assert result["result"]["observation"]["http_status"] == 302 and len(ctx[4][1]) == before+1


def test_fresh_policy_changes_before_io_block_without_target(ctx):
    service, intake, authority, _, target = ctx
    authority.mutate = lambda r: r.update({"constraints": {"timeout":1} if len(authority.calls)==2 else {}})
    before = len(target[1]); result = service.invoke_tool(intake)
    assert result["result"]["status"] == "BLOCKED" and len(target[1]) == before


@pytest.mark.parametrize("policy", [
    {"timeout":True}, {"timeout":0}, {"timeout":float("nan")}, {"max_duration":-1}, {"maximum_concurrency":"1"},
    {"rate_limit":{"requests":1}}, {"rate_limit":{"requests":False,"window_seconds":1}},
    {"rate_limit":{"requests":0,"window_seconds":1}}, {"resource_budget":{"memory_mb":16}},
    {"resource_budget":{"cpu_seconds":0}}, {"resource_budget":{"max_network_requests":0}},
    {"resource_budget":{"disk_gb":1}}, {"data_handling_policy":{"retention_days":30}},
    {"data_handling_policy":{"retain_sensitive_output":"no"}}, {"command_allowlist":[]},
    {"command_allowlist":["HTTP_HEAD","HTTP_HEAD"]}, {"command_allowlist":"HTTP_HEAD"},
    {"technique_allowlist":["UNRELATED"]}, {"sandbox":"UNRESTRICTED"}, {"credentials_lease":{"lease_id":"x"}},
    {"unknown_control":1}, {"allowed_targets":[]}, {"allowed_techniques":[]}, {"max_actions":0},
])
def test_runtime_policy_malformed_unsupported_and_deny_all_fail_closed(ctx, policy):
    service, intake, authority, _, target = ctx
    authority.mutate = lambda r: r.update({"constraints": policy})
    before = len(target[1])
    try:
        result = service.invoke_tool(intake)
    except RuntimeError:
        assert len(target[1]) == before
    else:
        assert result["record"]["status"] == "BLOCKED" and len(target[1]) == before


def test_supported_runtime_controls_intersect_and_enforce(ctx):
    auth = policy_authorization(ctx, {"timeout":2, "max_duration":3,"maximum_concurrency":2,
        "resource_budget":{"memory_mb":64,"max_output_bytes":2048,"max_network_bytes":4096,"cpu_seconds":1},
        "sandbox":"FIXED_WORKER_BROKER_V1", "rate_limit":{"requests":2,"window_seconds":2},
        "command_allowlist":["HTTP_HEAD"],"technique_allowlist":["SAFE_VERSION_CONFIGURATION_CONFIRMATION"]})
    policy = compile_runtime_policy(auth, select_adapter(auth["evaluation"]["execution_request"]), NOW)
    assert policy["limits"]["timeout_seconds"] == 2 and policy["limits"]["maximum_concurrency"] == 1
    assert policy["limits"]["memory_mb"] == 64 and policy["limits"]["rate_requests"] == 1


@pytest.mark.parametrize("resource", ["unsupported_key", "disk_quota", "unknown_network"])
def test_unknown_source_resource_budget_blocks(ctx, resource):
    auth = policy_authorization(ctx, {})
    auth["evaluation"]["current_context"]["pentest_context"]["task"]["constraints"]["resource_budget"] = {resource:1}
    with pytest.raises(ExecutionSourceRejected):
        compile_runtime_policy(auth, select_adapter(auth["evaluation"]["execution_request"]), NOW)


@pytest.mark.parametrize("value", ["http://u:p@127.0.0.1/", "http://127.0.0.1/?x=1", "file:///etc/passwd", "http://127.0.0.1/#x", "http://127.0.0.1/../x", "http://127.0.0.1/%0d", "http://127.0.0.1/\r\nX: a", "http://127.0.0.1:70000/"])
def test_target_url_rejects_override_traversal_and_header_injection(value):
    with pytest.raises(ExecutionSourceRejected):
        parse_endpoint({"target_type":"URL","target_value":value},80)


@pytest.mark.parametrize("ip", ["192.0.2.1", "169.254.169.254", "0.0.0.0", "224.0.0.1", "::"])
def test_out_of_scope_or_special_dns_answer_blocks(ctx, ip):
    auth = policy_authorization(ctx,{})
    req = deepcopy(auth["evaluation"]["execution_request"])
    req["target"] = {"target_type":"HOST","target_value":"lab.example"}
    context = auth["evaluation"]["current_context"]
    for source in [context["mission_scope"],context["pentest_context"]["boundary"],context["pentest_context"]["task"]]:
        source["scope"]["targets"] = [req["target"],{"target_type":"IP","target_value":"127.0.0.1"}]
    broker = TargetBroker(resolver=lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,"",(ip,80))])
    with pytest.raises(ExecutionSourceRejected):
        broker.pin(req,context,select_adapter(req))


def test_dns_rebinding_not_used_at_connect_and_all_answers_checked(ctx):
    auth = policy_authorization(ctx,{})
    req = deepcopy(auth["evaluation"]["execution_request"])
    req["target"] = {"target_type":"HOST","target_value":"lab.example"}
    context = auth["evaluation"]["current_context"]
    for source in [context["mission_scope"],context["pentest_context"]["boundary"],context["pentest_context"]["task"]]:
        source["scope"]["targets"] = [req["target"],{"target_type":"IP","target_value":"127.0.0.1"}]
    answers=["127.0.0.1"]
    broker=TargetBroker(resolver=lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,"",(ip,80)) for ip in answers])
    pinned=broker.pin(req,context,select_adapter(req))
    answers[:]=["192.0.2.1"]
    assert pinned.ip=="127.0.0.1"
    with pytest.raises(ExecutionSourceRejected): broker.pin(req,context,select_adapter(req))
    answers[:]=["127.0.0.1","192.0.2.1"]
    with pytest.raises(ExecutionSourceRejected): broker.pin(req,context,select_adapter(req))


def test_dns_resolution_is_bounded(ctx):
    auth=policy_authorization(ctx,{})
    req=deepcopy(auth["evaluation"]["execution_request"]);req["target"]={"target_type":"HOST","target_value":"lab.example"}
    context=auth["evaluation"]["current_context"]
    for source in [context["mission_scope"],context["pentest_context"]["boundary"],context["pentest_context"]["task"]]: source["scope"]["targets"]=[req["target"]]
    broker=TargetBroker(resolver=lambda *a,**k:(time.sleep(0.2) or []))
    with pytest.raises(TimeoutError):broker.pin(req,context,select_adapter(req),deadline=time.monotonic()+0.05)


def test_no_shell_plugin_or_unregistered_technique(ctx):
    req=deepcopy(ctx[3]["envelope"]["execution_request"]);req["action"]["technique"]="RUN_ANY_COMMAND"
    with pytest.raises(ExecutionSourceRejected):select_adapter(req)


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a:a.adapter_id)
def test_every_adapter_has_exact_capability_action_technique_selection(ctx, adapter):
    req=deepcopy(ctx[3]["envelope"]["execution_request"])
    req["action"]={"capability_id":adapter.capability_id,"action_class":adapter.action_class,"technique":adapter.technique}
    #req["target"]={"target_type":"IP","target_value":"127.0.0.1"}
    target_type = adapter.target_types[0]
    target_value = (
            "http://127.0.0.1/status"
            if target_type == "URL"
            else "127.0.0.1"
        )
    req["target"] = {
            "target_type": target_type,
            "target_value": target_value,
        }
    assert select_adapter(req)==adapter


def test_native_sandbox_discards_raw_sensitive_output_and_terminates():
    raw=b"HTTP/1.1 200 OK\r\nServer: test\r\nSet-Cookie: secret=TOPSECRET\r\n\r\n"
    obs={"connected":True,"peer_ip":"127.0.0.1","response_bytes":len(raw),"response_sha256":hashlib.sha256(raw).hexdigest(),"response_b64":base64.b64encode(raw).decode(),"byte_limit_reached":False}
    with ResourceSandbox(DEFAULT_LIMITS) as sandbox:
        result=sandbox.parse("HTTP_HEAD",obs,deadline=time.monotonic()+2)
        process=sandbox.process;folder=Path(sandbox.folder.name)
    assert process.poll()==0 and not folder.exists() and "TOPSECRET" not in canonical_json(result)


def test_native_sandbox_output_quota_fails_before_target():
    limits={**DEFAULT_LIMITS,"max_output_bytes":1}
    with pytest.raises(ExecutionSourceRejected):
        with ResourceSandbox(limits): pass


def test_native_sandbox_bad_parser_input_is_rejected():
    with ResourceSandbox(DEFAULT_LIMITS) as sandbox:
        with pytest.raises(ExecutionSourceRejected):sandbox.parse("RUN_SHELL",{},deadline=time.monotonic()+2)


@pytest.mark.parametrize("field,value",[("revoked",True),("execution_id","exec-other"),("mission_id","mission-gmo-other"),("adapter_id","web.http-head.v1"),("expires_at","2020-01-01T00:00:00Z")])
def test_credential_lease_is_server_scoped_and_expiry_checked(ctx,tmp_path,monkeypatch,field,value):
    req=ctx[3]["envelope"]["execution_request"];adapter=select_adapter(req)
    lease={"lease_id":"credlease-test","mission_id":req["mission_id"],"execution_id":req["execution_id"],"target":req["target"],"adapter_id":adapter.adapter_id,
           "issued_at":(NOW-timedelta(minutes=1)).isoformat(),"expires_at":(NOW+timedelta(minutes=1)).isoformat(),"secret_environment":"APTS_CRED_TEST","revoked":False}
    lease[field]=value;path=tmp_path/"leases.json";path.write_text(json.dumps([lease]));monkeypatch.setenv("APTS_CRED_TEST","SERVERSECRET")
    with pytest.raises(ExecutionSourceRejected):CredentialLeaseStore(path).acquire("credlease-test",req,adapter,NOW)


def test_credential_lease_metadata_does_not_contain_secret(ctx,tmp_path,monkeypatch):
    req=ctx[3]["envelope"]["execution_request"];adapter=select_adapter(req)
    lease={"lease_id":"credlease-test","mission_id":req["mission_id"],"execution_id":req["execution_id"],"target":req["target"],"adapter_id":adapter.adapter_id,
           "issued_at":(NOW-timedelta(minutes=1)).isoformat(),"expires_at":(NOW+timedelta(minutes=1)).isoformat(),"secret_environment":"APTS_CRED_TEST","revoked":False}
    path=tmp_path/"leases.json";path.write_text(json.dumps([lease]));monkeypatch.setenv("APTS_CRED_TEST","SERVERSECRET")
    header,metadata=CredentialLeaseStore(path).acquire("credlease-test",req,adapter,NOW)
    assert header=="Bearer SERVERSECRET" and "SERVERSECRET" not in canonical_json(metadata)


def test_migration_preserves_old_request_and_authorizations(ctx):
    repo=ctx[0].repository
    assert repo.migration_level()==4
    assert repo.get(ctx[1]["execution_id"])["envelope"]==ctx[3]["envelope"]
    with pytest.raises(ExecutionRepositoryError):ExecutionGatewayRepository(repo.sqlite_path).initialize()


@pytest.mark.parametrize("statement",["UPDATE execution_adapter_invocations SET status='BLOCKED'","DELETE FROM execution_adapter_invocations","UPDATE execution_adapter_results SET status='FAILED'","DELETE FROM execution_adapter_results"])
def test_append_only_tables_reject_mutation(ctx,statement):
    ctx[0].invoke_tool(ctx[1])
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):conn.execute(statement)


def test_resealed_result_cannot_cross_execution_claim_binding(ctx):
    service=ctx[0];result=service.invoke_tool(ctx[1]);record=result["result"]
    core={k:v for k,v in record.items() if k!="integrity"};core["execution_id"]="exec-other"
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_adapter_results_no_update")
        tampered=with_integrity(core,RESULT_DOMAIN)
        conn.execute("UPDATE execution_adapter_results SET record_json=?,record_sha256=?",(canonical_json(tampered),tampered["integrity"]["canonical_sha256"]))
    with pytest.raises(ExecutionRequestIntegrityError):service.repository.get_adapter_invocation(result["invocation_id"])


def test_raw_execution_routes_closed_and_new_intake_http_strict(ctx):
    with server_for(ctx[0]) as url:
        for route in ["dispatches","results","tool-invocations"]:
            assert http(url+"/api/execution/"+route,"POST",{})[0]==409
        assert http(url+ROUTE,"POST",{"decision":"ALLOW"})[0]==400
        assert http(url+ROUTE+"?command=run","POST",ctx[1])[0]==400
        code,payload,headers=http(url+"/health")
        assert code==200 and "6.4" in headers["Server"] and payload["registered_adapter_count"]==6
        assert payload["execution_repository_migration_level"]==4 and payload["next_stage"]=="6.5"
        assert verify_adapter_contract(http(url+"/api/execution/tool-adapters-contract")[1]["contract"])
        created=http(url+ROUTE,"POST",ctx[1]);assert created[0]==201
        assert http(url+ROUTE,"POST",ctx[1])[0]==200
        read=http(url+ROUTE+"/"+created[1]["invocation_id"])[1]
        assert read["target_network_io_performed"] is False and read["execution_authorized"] is False


def test_real_http_authority_protocol_and_target_proof(ctx):
    service,intake,authority,_,target=ctx
    with authority_server(authority) as authority_url:
        service.governance_client=ExecutionGovernanceClient(authority_url,2)
        before=len(target[1]);result=service.invoke_tool(intake)
        assert result["result"]["status"]=="SUCCEEDED" and len(target[1])==before+1


@pytest.mark.parametrize("host",["0.0.0.0","::","192.0.2.1","remote.example"])
def test_api_cannot_bind_remote(host,ctx):
    with pytest.raises(ExecutionRequestValidationError):serve(host,0,service=ctx[0])


def test_real_competing_processes_cannot_double_execute(ctx):
    service,intake,_,_,target=ctx
    service.repository.initialize()
    paths=[str(p) for p in (service.repository.sqlite_path,service.proposal_source.sqlite_path,service.mission_source.sqlite_path)]
    before=len(target[1])
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context("spawn")) as pool:
        futures=[pool.submit(invoke_process,paths,new_intake(intake)) for _ in range(2)]
        outcomes=[f.result(timeout=30) for f in futures]
    assert sorted(x[0] for x in outcomes)==["BLOCKED","RESERVED"] and len(target[1])==before+1


@pytest.mark.parametrize("kind",["action","rate","network","concurrency"])
def test_budget_rate_network_and_concurrency_block_extra_execution(ctx,monkeypatch,kind):
    service,intake,authority,_,target=ctx
    policy={"max_actions":1} if kind=="action" else {"resource_budget":{"max_network_requests":1}} if kind=="network" else {}
    authority.mutate=lambda r:r.update({"constraints":policy})
    extra=new_execution(ctx)
    before=len(target[1])
    if kind=="concurrency":
        monkeypatch.setattr(service,"_run_reserved",lambda *a:(_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError):service.invoke_tool(intake)
    else:
        assert service.invoke_tool(intake)["result"]["status"]=="SUCCEEDED"
    if kind in {"action","network","concurrency"}:service.clock=lambda:NOW+timedelta(seconds=2)
    blocked=service.invoke_tool(extra)
    expected={"action":"ACTION_BUDGET_EXHAUSTED","rate":"RATE_LIMIT_EXHAUSTED","network":"NETWORK_REQUEST_QUOTA_EXHAUSTED","concurrency":"CONCURRENCY_QUOTA_EXHAUSTED"}[kind]
    assert blocked["record"]["reason_codes"]==[expected]
    assert len(target[1])==before+(0 if kind=="concurrency" else 1)


def test_source_changed_during_second_gss_query_never_contacts_target(ctx):
    service,intake,authority,_,target=ctx
    def mutate(result):
        if len(authority.calls)==2:
            with sqlite3.connect(service.mission_source.sqlite_path) as conn:
                conn.execute("UPDATE mission_states SET state='ABORTED',terminal=1")
    authority.mutate=mutate
    before=len(target[1]);result=service.invoke_tool(intake)
    assert result["result"]["status"]=="BLOCKED" and len(target[1])==before


def test_result_write_failure_keeps_claim_consumed(ctx,monkeypatch):
    service,intake,_,_,target=ctx
    monkeypatch.setattr(service.repository,"append_adapter_result",lambda *a:(_ for _ in ()).throw(ExecutionRepositoryError("storage failure")))
    before=len(target[1])
    with pytest.raises(ExecutionRepositoryError):service.invoke_tool(intake)
    assert service.invoke_tool(intake)["invocation_incomplete"] is True and len(target[1])==before+1
    assert service.invoke_tool(new_intake(intake))["record"]["status"]=="BLOCKED"


@pytest.mark.parametrize("version",[1,2,3])
def test_upgrade_from_predecessor_preserves_rows_and_consumes_existing_gateway_budget(ctx,tmp_path,version):
    oldpath=tmp_path/("old"+str(version)+".db")
    oldrepo={1:ExecutionRequestRepository,2:ExecutionAuthorizationRepository,3:ExecutionGatewayRepository}[version](oldpath)
    oldrepo.append(ctx[3]["envelope"])
    if version>=2:
        auth=ctx[0]._fresh_authorization(ctx[1]);oldrepo.append_authorization(auth)
    gate=None
    if version==3:
        oldservice=ExecutionGatewayService(oldrepo,ctx[0].proposal_source,ctx[0].mission_source,UniqueAuthority(),clock=lambda:NOW)
        gate=oldservice.submit_execution({"schema_version":GATEWAY_INTAKE_SCHEMA,"submission_id":"gwreq-stage64-old","idempotency_key":"idem-old-gateway",
            "execution_id":ctx[1]["execution_id"],"envelope_sha256":ctx[1]["envelope_sha256"],"requested_by":ctx[1]["requested_by"]})
    with sqlite3.connect(oldpath) as conn:
        originals={table:conn.execute("SELECT * FROM "+table).fetchall() for table in ["execution_requests"]+(["execution_authorizations"] if version>=2 else [])+(["execution_gateway_submissions"] if version==3 else [])}
    service=ExecutionAdapterService(ExecutionAdapterRepository(oldpath),ctx[0].proposal_source,ctx[0].mission_source,UniqueAuthority(),clock=lambda:NOW)
    service.repository.initialize()
    with sqlite3.connect(oldpath) as conn:
        for table,rows in originals.items():assert conn.execute("SELECT * FROM "+table).fetchall()==rows
    result=service.invoke_tool(ctx[1])
    assert result["result"]["status"]=="SUCCEEDED"
    assert result["record"]["gateway_id"]==(None if gate is None else gate["gateway_id"])
    if gate:
        assert result["record"]["budget_before"]["mission"]==1


@pytest.mark.parametrize("variant",["foreign","future","missing_table","missing_meta"])
def test_incompatible_repository_rejected_without_mutation(tmp_path,variant):
    path=tmp_path/"foreign.db"
    if variant=="foreign":
        with sqlite3.connect(path) as conn:conn.execute("CREATE TABLE unrelated (id INTEGER)")
    else:
        ExecutionAdapterRepository(path).initialize()
        with sqlite3.connect(path) as conn:
            if variant=="future":conn.execute("UPDATE execution_repository_meta SET migration_level=100")
            elif variant=="missing_table":conn.execute("DROP TABLE execution_adapter_results")
            else:conn.execute("DELETE FROM execution_repository_meta")
    before=path.read_bytes()
    with pytest.raises(ExecutionRepositoryError):ExecutionAdapterRepository(path).initialize()
    assert path.read_bytes()==before


def test_resealed_budget_history_is_detected(ctx):
    result=ctx[0].invoke_tool(ctx[1]);record=result["record"]
    core={k:v for k,v in record.items() if k!="integrity"};core["budget_before"]["mission"]=99
    tampered=with_integrity(core,CLAIM_DOMAIN)
    with sqlite3.connect(ctx[0].repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_adapter_invocations_no_update")
        conn.execute("UPDATE execution_adapter_invocations SET record_json=?,record_sha256=?",(canonical_json(tampered),tampered["integrity"]["canonical_sha256"]))
    with pytest.raises(ExecutionRequestIntegrityError):ctx[0].repository.get_adapter_invocation(result["invocation_id"])


def test_credentials_cannot_be_forced_by_policy_when_source_roe_forbids(ctx):
    policy={"credential_usage_allowed":True,"credentials_lease":{"lease_id":"credlease-test","required":True}}
    ctx[2].mutate=lambda r:r.update({"constraints":policy})
    before=len(ctx[4][1]);result=ctx[0].invoke_tool(ctx[1])
    assert result["record"]["status"]=="BLOCKED" and result["record"]["reason_codes"]==["CREDENTIAL_USE_NOT_AUTHORIZED"] and len(ctx[4][1])==before


@pytest.mark.parametrize("adapter",[a for a in ADAPTERS if a.operation=="HTTP_HEAD"],ids=lambda a:a.adapter_id)
def test_web_validation_and_evidence_adapters_run_fixed_head_operation(target_server,adapter):
    host,port,path,tls=parse_endpoint({"target_type":"URL","target_value":target_server[0]},80)
    target_server[2].update({"sleep":0,"redirect":False})
    guard=[];before=len(target_server[1])
    deadline=time.monotonic()+2
    with ResourceSandbox(DEFAULT_LIMITS) as worker:
        observation=TargetBroker().observe(adapter,PinnedTarget(host,host,port,path,tls),DEFAULT_LIMITS,deadline=deadline,before_io=lambda:guard.append("CHECKED"))
        parsed=worker.parse(adapter.operation,observation,deadline=deadline)
    assert guard==["CHECKED"] and parsed["http_status"]==200 and len(target_server[1])==before+1
    assert "SENSITIVE_TARGET_COOKIE" not in canonical_json(parsed)


@pytest.mark.parametrize("operation",["TCP_CONNECT","TCP_BANNER"])
def test_scanner_and_network_adapter_use_single_bounded_socket(operation):
    import socketserver
    calls=[]
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            calls.append(self.client_address)
            if operation=="TCP_BANNER":self.request.sendall(b"AuthorizedLabBanner")
    server=socketserver.ThreadingTCPServer(("127.0.0.1",0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        adapter=next(a for a in ADAPTERS if a.operation==operation)
        deadline=time.monotonic()+2
        with ResourceSandbox(DEFAULT_LIMITS) as worker:
            observation=TargetBroker().observe(adapter,PinnedTarget("127.0.0.1","127.0.0.1",server.server_address[1],"/",False),DEFAULT_LIMITS,
                deadline=deadline,before_io=lambda:None)
            parsed=worker.parse(operation,observation,deadline=deadline)
        assert parsed["connected"] is True and parsed["response_bytes"]==(0 if operation=="TCP_CONNECT" else len(b"AuthorizedLabBanner"))
        assert "AuthorizedLabBanner" not in canonical_json(parsed)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
    assert len(calls)==1


def test_source_max_duration_is_also_a_lifetime_budget(ctx):
    service,intake,_,_,target=ctx
    original=service.mission_source.current_context
    def current(identity):
        context=original(identity)
        context["mission_scope"]["constraints"]["max_duration"]=1
        return context
    service.mission_source.current_context=current
    extra=new_execution(ctx)
    assert service.invoke_tool(intake)["result"]["status"]=="SUCCEEDED"
    before=len(target[1]);service.clock=lambda:NOW+timedelta(seconds=2)
    blocked=service.invoke_tool(extra)
    assert blocked["record"]["reason_codes"]==["SOURCE_DURATION_BUDGET_EXHAUSTED"] and len(target[1])==before


def test_pinned_address_is_rechecked_against_current_exclusions(ctx):
    auth=policy_authorization(ctx,{})
    req=auth["evaluation"]["execution_request"];context=auth["evaluation"]["current_context"];adapter=select_adapter(req)
    broker=TargetBroker();pinned=broker.pin(req,context,adapter)
    context["mission_scope"]["scope"]["excluded_targets"].append({"target_type":"IP","target_value":pinned.ip})
    with pytest.raises(ExecutionSourceRejected):broker.validate_pin(req,context,adapter,pinned)
