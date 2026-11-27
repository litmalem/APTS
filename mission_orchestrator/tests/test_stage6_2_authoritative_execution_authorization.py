from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sqlite3
from threading import Thread
from urllib.request import Request

import pytest

from execution_subsystem.authorization_api import ExecutionSubsystemStage62Handler
from execution_subsystem.authorization_contract import (
    AUTHORIZATION_ATTESTATION_SCHEMA, AUTHORIZATION_INTAKE_SCHEMA,
    AUTHORIZATION_RECORD_DOMAIN, AUTHORIZATION_BOUNDARIES,
    EXECUTION_AUTHORIZATION_CONTROL_VERSION, ExecutionGovernanceProtocolError,
    ExecutionGovernanceUnavailable, canonical_execution_authorization_contract,
    normalize_authorization_intake, utc_timestamp, verify_authorization_record,
    verify_execution_authorization_contract, authorization_intake_json_schema, gss_revalidation_json_schema,
)
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.authorization_service import ExecutionAuthorizationService
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.authorization_source import local_execution_checks
from execution_subsystem.execution_contract import (
    REQUIRED_AUTHORIZATION_CHECKS, ExecutionRequestConflict, ExecutionRequestIntegrityError,
    ExecutionRequestValidationError, ExecutionSourceRejected, ExecutionSourceUnavailable,
    canonical_execution_request_contract, canonical_json, sha256_hex, with_integrity,
)
from execution_subsystem.governance_client import ExecutionGovernanceClient, strict_json
from execution_subsystem.request_repository import ExecutionRequestRepository, ExecutionRepositoryError
from mission_orchestrator.governance_binding import build_binding_contract
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.scope_contract import build_contract
from tests.test_stage6_1_canonical_execution_request_contract import intake_for, http
from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline

NOW = datetime(2026, 10, 2, 9, 16, tzinfo=timezone.utc)


def seed_mission(path, boundary):
    """Real Mission schema and sealed contract builders; independent test fixture."""
    MissionRepository(driver="sqlite", sqlite_path=str(path))
    mid = boundary["mission_id"]
    created = utc_timestamp(NOW)
    contract = build_contract({"scope": deepcopy(boundary["scope"]), "roe": deepcopy(boundary["roe"]),
                              "constraints": deepcopy(boundary["constraints"]),
                              "actor": "stage62-test", "idempotency_key": "scope-seed", "metadata": {}},
                             mission_id=mid, contract_id="mscope-stage62", contract_version=1,
                             snapshot_id="mscope-snap-stage62", created_at=created)
    scope_hash = contract["integrity"]["canonical_sha256"]
    external = {"scope_contract_id": "gscope-stage62", "version": 1, "contract_hash": "b"*64,
                "policy_set_id": "default-policy", "mission_id": mid, "status": "ACTIVE"}
    binding = build_binding_contract(mission_id=mid, mission_governance_binding_id="mgbind-stage62",
        binding_snapshot_id="mgbind-snap-stage62", binding_version=1, scope_record={"contract":contract},
        normalized_request={"capabilities": [], "metadata": {}, "actor": "stage62-test"},
        governance_scope=external, created_at=created)
    def insert(conn, table, fields):
        conn.execute("INSERT INTO " + table + " (" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")", tuple(fields.values()))
    with sqlite3.connect(path) as conn:
        insert(conn,"global_missions",dict(mission_id=mid,source_system="STAGE62_TEST", idempotency_key="mission-seed",
               request_sha256="c"*64, correlation_id="corr-stage62",created_by="stage62-test",created_at=created))
        insert(conn,"mission_states",dict(mission_id=mid,schema_version="apts-mission-state-v1",state="RUNNING",
               state_version=3,terminal=0,updated_by="stage62-test",created_at=created,updated_at=created))
        insert(conn,"mission_scope_contract_versions",dict(snapshot_id="mscope-snap-stage62",mission_id=mid,
               mission_scope_contract_id="mscope-stage62",contract_version=1,schema_version=contract["schema_version"],
               request_sha256="d"*64,idempotency_key="scope-seed",canonical_sha256=scope_hash,
               canonical_json=canonical_json(contract),created_by="stage62-test",created_at=created))
        insert(conn,"mission_scope_contract_heads",dict(mission_id=mid,mission_scope_contract_id="mscope-stage62",
               current_version=1,current_snapshot_id="mscope-snap-stage62",current_sha256=scope_hash,
               updated_by="stage62-test",created_at=created,updated_at=created))
        insert(conn,"mission_governance_binding_versions",dict(binding_snapshot_id="mgbind-snap-stage62",mission_id=mid,
               mission_governance_binding_id="mgbind-stage62",binding_version=1,schema_version=binding["schema_version"],
               request_sha256="e"*64,idempotency_key="binding-seed",canonical_sha256=binding["integrity"]["canonical_sha256"],
               canonical_json=canonical_json(binding),mission_scope_snapshot_id="mscope-snap-stage62",mission_scope_sha256=scope_hash,
               governance_scope_contract_id="gscope-stage62",governance_scope_version=1,governance_scope_contract_hash="b"*64,
               policy_set_id="default-policy",external_response_json=canonical_json(external),created_by="stage62-test",created_at=created))
        insert(conn,"mission_governance_binding_heads",dict(mission_id=mid,mission_governance_binding_id="mgbind-stage62",
               current_version=1,current_binding_snapshot_id="mgbind-snap-stage62",current_scope_snapshot_id="mscope-snap-stage62",
               current_governance_scope_contract_id="gscope-stage62",updated_by="stage62-test",created_at=created,updated_at=created))


class FakeAuthority:
    """Only tests instantiate this authority; production has no in-process ALLOW."""
    def __init__(self):
        self.calls = []
        self.decision = "ALLOW"
        self.mutate = None

    def evaluate_authorization(self, payload):
        self.calls.append(deepcopy(payload))
        evaluation = payload["context"]["execution_authorization_evaluation"]
        req = evaluation["execution_request"]
        gov = evaluation["current_context"]["governance_authority"]
        result = {
            "decision_id": f"gdec-stage62-{len(self.calls)}", "request_id": f"greq-stage62-{len(self.calls)}",
            "mission_id": req["mission_id"], "decision": self.decision, "decision_hash": "f"*64,
            "scope_contract_id": gov["governance_scope_contract_id"], "scope_version": gov["governance_scope_version"],
            "policy_set_id": gov["policy_set_id"], "policy_version": req["authorization_requirement"]["policy_reference"]["policy_version"],
            "valid_from": utc_timestamp(NOW-timedelta(seconds=10)), "valid_until": utc_timestamp(NOW+timedelta(minutes=5)),
            "requires_human_approval": self.decision == "REVIEW", "constraints": {}, "reason_codes": ["TEST_AUTHORITY"],
            "execution_revalidation": {
                "schema_version": AUTHORIZATION_ATTESTATION_SCHEMA,
                "evaluation_sha256": evaluation["integrity"]["canonical_sha256"], "nonce": evaluation["nonce"],
                "execution_id": req["execution_id"], "request_sha256": req["integrity"]["canonical_sha256"],
                "envelope_sha256": evaluation["envelope_sha256"], "context_sha256": sha256_hex(evaluation["current_context"]),
                "checked_at": utc_timestamp(NOW), "checks": {key:"PASS" for key in REQUIRED_AUTHORIZATION_CHECKS},
                "revoked": False, "emergency_stop": False, "human_approval_verified": False,
            },
        }
        if self.mutate:
            self.mutate(result)
        return result


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("stage62-seed")
    repo, boundary, task, oid, runs = _pipeline(root,"stage62",through_stage="5.6")
    mission = root / "missions.db"
    seed_mission(mission, boundary)
    return repo.sqlite_path, mission, runs["5.6"]


@pytest.fixture
def ctx(tmp_path, seed):
    pentest, mission, run = seed
    pdb, mdb = tmp_path / "pentest.db", tmp_path / "mission.db"
    # Include committed WAL pages when cloning the predecessor fixtures.
    for original, clone in ((pentest, pdb), (mission, mdb)):
        with sqlite3.connect(original) as source, sqlite3.connect(clone) as destination:
            source.backup(destination)
    authority = FakeAuthority()
    service = ExecutionAuthorizationService(ExecutionAuthorizationRepository(tmp_path/"execution.db"),
        ExecutionAuthorizationProposalSource(pdb), MissionAuthorizationSource(mdb), authority, clock=lambda:NOW)
    request = service.create_request(intake_for(run,"stage62"))
    intake = {"schema_version":AUTHORIZATION_INTAKE_SCHEMA,"revalidation_id":"eauthreq-stage62",
              "idempotency_key":"idem-auth-stage62","execution_id":request["execution_id"],
              "envelope_sha256":request["envelope"]["integrity"]["canonical_sha256"],"requested_by":"stage62-test"}
    return service, intake, authority, request


@contextmanager
def server_for(service):
    handler=type("IsolatedStage62Handler",(ExecutionSubsystemStage62Handler,),{"service":service})
    server=ThreadingHTTPServer(("127.0.0.1",0),handler)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_contract_freezes_stage61_and_all_eight_checks():
    contract=canonical_execution_authorization_contract()
    assert contract["predecessor"]["contract_sha256"] == canonical_execution_request_contract()["integrity"]["canonical_sha256"]
    assert contract["required_checks"] == list(REQUIRED_AUTHORIZATION_CHECKS)
    assert contract["repository"]["migration_level"] == 2
    assert contract["next_stage"] == "6.3" and verify_execution_authorization_contract(contract)
    contract["runtime"]["target_actuation"]=True
    assert not verify_execution_authorization_contract(contract)


def test_published_schemas_match_contract_and_authority_proof(ctx):
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/"execution_subsystem"/"schemas"
    assert json.loads((root/"execution_authorization_intake_v1.schema.json").read_text())==authorization_intake_json_schema()
    assert json.loads((root/"gss_execution_revalidation_v1.schema.json").read_text())==gss_revalidation_json_schema()
    record=ctx[0].authorize_execution(ctx[1])["record"]
    assert set(record["policy_decision"]["execution_revalidation"])==set(gss_revalidation_json_schema()["required"])


def test_complete_stage59_workflow_hands_off_to_fresh_authorization(tmp_path):
    repo,boundary,task,oid,runs=_pipeline(tmp_path,"stage62-complete",through_stage="5.9")
    mdb=tmp_path/"mission.db"
    seed_mission(mdb,boundary)
    service=ExecutionAuthorizationService(ExecutionAuthorizationRepository(tmp_path/"execution.db"),
        ExecutionAuthorizationProposalSource(repo.sqlite_path),MissionAuthorizationSource(mdb),FakeAuthority(),clock=lambda:NOW)
    request=service.create_request(intake_for(runs["5.6"],"stage62-complete"))
    result=service.authorize_execution({"schema_version":AUTHORIZATION_INTAKE_SCHEMA,"revalidation_id":"eauthreq-complete",
        "idempotency_key":"idem-complete","execution_id":request["execution_id"],
        "envelope_sha256":request["envelope"]["integrity"]["canonical_sha256"],"requested_by":"stage62-test"})
    assert result["execution_authorized"] is True and result["record"]["task_id"]==task["upstream_task_id"]
    assert result["record"]["mission_id"]==boundary["mission_id"]


@pytest.mark.parametrize("decision",["ALLOW","DENY","REVIEW"])
def test_fresh_authority_decision_is_bound_and_request_remains_immutable(ctx,decision):
    service,intake,authority,request=ctx
    authority.decision=decision
    before=[p.read_bytes() for p in (service.mission_source.sqlite_path,service.proposal_source.sqlite_path)]
    result=service.authorize_execution(intake)
    assert result["created"] is True and result["record"]["decision"] == decision
    assert result["execution_authorized"] is (decision == "ALLOW")
    assert result["usable_for_dispatch"] is False and result["governance_query_performed"] is True
    record=result["record"]
    assert verify_authorization_record(record)
    assert record["checks"] == {key:"PASS" for key in REQUIRED_AUTHORIZATION_CHECKS}
    assert record["semantics"] == AUTHORIZATION_BOUNDARIES
    assert record["valid_until"] == utc_timestamp(NOW+timedelta(seconds=120))
    assert service.repository.get(intake["execution_id"])["envelope"] == request["envelope"]
    assert before == [p.read_bytes() for p in (service.mission_source.sqlite_path,service.proposal_source.sqlite_path)]


@pytest.mark.parametrize("check",list(REQUIRED_AUTHORIZATION_CHECKS))
def test_failed_authoritative_check_cannot_be_overridden_by_allow(ctx,check):
    service,intake,authority,_=ctx
    authority.mutate=lambda result: result["execution_revalidation"]["checks"].update({check:"FAIL"})
    result=service.authorize_execution(intake)
    assert result["record"]["policy_decision"]["decision"] == "ALLOW"
    assert result["record"]["decision"] == "DENY" and result["execution_authorized"] is False


@pytest.mark.parametrize("check",list(REQUIRED_AUTHORIZATION_CHECKS))
def test_missing_authoritative_check_fails_closed(ctx,check):
    service,intake,authority,_=ctx
    authority.mutate=lambda result: result["execution_revalidation"]["checks"].pop(check)
    with pytest.raises(ExecutionGovernanceProtocolError): service.authorize_execution(intake)
    assert service.repository.list_authorizations(intake["execution_id"]) == []


@pytest.mark.parametrize("flag",["revoked","emergency_stop"])
def test_revocation_and_emergency_stop_take_precedence(ctx,flag):
    service,intake,authority,_=ctx
    authority.mutate=lambda result: result["execution_revalidation"].update({flag:True})
    assert service.authorize_execution(intake)["record"]["decision"] == "DENY"


@pytest.mark.parametrize("field",["decision","policy_decision","target","parameters","execution_authorized","governance_url","nonce","checked_at","constraints"])
def test_caller_cannot_supply_authority_or_action(ctx,field):
    service,intake,authority,_=ctx
    with pytest.raises(ExecutionRequestValidationError): service.authorize_execution({**intake,field:True})
    assert authority.calls == []


@pytest.mark.parametrize("field",["evaluation_sha256","nonce","execution_id","request_sha256","envelope_sha256","context_sha256"])
def test_wrong_execution_or_stale_correlation_is_rejected(ctx,field):
    service,intake,authority,_=ctx
    authority.mutate=lambda result: result["execution_revalidation"].update({field:"forged"})
    with pytest.raises(ExecutionGovernanceProtocolError): service.authorize_execution(intake)


@pytest.mark.parametrize("case",["expired","future","naive","old-checked","future-checked","boolean-policy","policy-downgrade","missing-proof","boolean-check","missing-revocation","unknown-decision","old-decision","nan"])
def test_invalid_or_expired_decision_never_persists_allow(ctx,case):
    service,intake,authority,_=ctx
    def mutate(d):
        if case=="expired": d["valid_until"]=utc_timestamp(NOW)
        if case=="future": d["valid_from"]=utc_timestamp(NOW+timedelta(seconds=1))
        if case=="naive": d["valid_until"]="2026-10-02T09:20:00"
        if case=="old-checked": d["execution_revalidation"]["checked_at"]=utc_timestamp(NOW-timedelta(seconds=6))
        if case=="future-checked": d["execution_revalidation"]["checked_at"]=utc_timestamp(NOW+timedelta(seconds=6))
        if case=="boolean-policy": d["policy_version"]=True
        if case=="policy-downgrade": d["policy_version"]=1
        if case=="missing-proof": d.pop("execution_revalidation")
        if case=="boolean-check": d["execution_revalidation"]["checks"]["RISK"]=True
        if case=="missing-revocation": d["execution_revalidation"].pop("revoked")
        if case=="unknown-decision": d["decision"]="PERMIT"
        if case=="old-decision": d["decision_id"]=ctx[3]["envelope"]["execution_request"]["authorization_requirement"]["policy_reference"]["policy_decision_id"]
        if case=="nan": d["constraints"]["rate"]=float("nan")
    authority.mutate=mutate
    with pytest.raises(ExecutionGovernanceProtocolError): service.authorize_execution(intake)
    assert service.repository.list_authorizations(intake["execution_id"]) == []


def test_current_human_review_requirement_needs_verified_approval(ctx,monkeypatch):
    service,intake,authority,_=ctx
    source=service.mission_source.current_context
    def current(mid):
        context=source(mid)
        context["mission_scope"]["roe"]["human_approval_required_for"]=[ctx[3]["envelope"]["execution_request"]["action"]["action_class"]]
        return context
    monkeypatch.setattr(service.mission_source,"current_context",current)
    assert service.authorize_execution(intake)["record"]["decision"] == "REVIEW"
    authority.mutate=lambda d:d["execution_revalidation"].update(human_approval_verified=True)
    second={**intake,"revalidation_id":"eauthreq-approved","idempotency_key":"idem-approved"}
    assert service.authorize_execution(second)["record"]["decision"] == "ALLOW"


@pytest.mark.parametrize("case",["excluded-target","out-of-scope","risk-limit","prohibited-action","prohibited-technique","allowed-technique","expired-window","network-range"])
def test_current_local_restrictions_block_governance_query(ctx,monkeypatch,case):
    service,intake,authority,request=ctx
    source=service.mission_source.current_context
    target=request["envelope"]["execution_request"]["target"]
    action=request["envelope"]["execution_request"]["action"]
    def current(mid):
        context=source(mid)
        contract=context["mission_scope"]
        if case=="excluded-target":contract["scope"]["excluded_targets"]=[target]
        if case=="out-of-scope":contract["scope"]["targets"]=[]
        if case=="risk-limit":contract["constraints"]["risk_threshold"]="NONE"
        if case=="prohibited-action":contract["roe"]["prohibited_action_classes"]=[action["action_class"]]
        if case=="prohibited-technique":contract["roe"]["prohibited_techniques"]=[action["technique"]]
        if case=="allowed-technique":contract["roe"]["allowed_techniques"]=["another-technique"]
        if case=="expired-window":contract["roe"]["allowed_time_window"]={"start_at":utc_timestamp(NOW-timedelta(hours=1)),"end_at":utc_timestamp(NOW)}
        if case=="network-range":contract["scope"]["network_ranges"]=["192.0.2.0/24"]
        return context
    monkeypatch.setattr(service.mission_source,"current_context",current)
    with pytest.raises(ExecutionSourceRejected):service.authorize_execution(intake)
    assert authority.calls==[]


@pytest.mark.parametrize("case",["scope-head","binding-head","scope-hash","governance-hash","stale-scope"])
def test_mission_source_detects_invalid_current_heads_and_binding(ctx,case):
    service,intake,authority,_=ctx
    statements={
        "scope-head":"UPDATE mission_scope_contract_heads SET current_snapshot_id='mscope-snap-forged'",
        "binding-head":"UPDATE mission_governance_binding_heads SET current_binding_snapshot_id='mgbind-snap-forged'",
        "scope-hash":"UPDATE mission_scope_contract_versions SET canonical_sha256='"+"0"*64+"'",
        "governance-hash":"UPDATE mission_governance_binding_versions SET canonical_sha256='"+"0"*64+"'",
        "stale-scope":"UPDATE mission_governance_binding_versions SET mission_scope_sha256='"+"0"*64+"'",
    }
    with sqlite3.connect(service.mission_source.sqlite_path) as conn:conn.execute(statements[case])
    with pytest.raises(ExecutionRequestIntegrityError):service.authorize_execution(intake)
    assert authority.calls==[]


@pytest.mark.parametrize("check",list(REQUIRED_AUTHORIZATION_CHECKS))
def test_authoritative_review_check_blocks_allow(ctx,check):
    service,intake,authority,_=ctx
    authority.mutate=lambda result:result["execution_revalidation"]["checks"].update({check:"REVIEW"})
    assert service.authorize_execution(intake)["record"]["decision"]=="REVIEW"


def test_reused_authoritative_decision_id_cannot_bind_another_attempt(ctx):
    service,intake,authority,_=ctx
    service.authorize_execution(intake)
    authority.mutate=lambda d:d.update(decision_id="gdec-stage62-1")
    second={**intake,"revalidation_id":"eauthreq-new","idempotency_key":"idem-new"}
    with pytest.raises(ExecutionRequestConflict):service.authorize_execution(second)


def test_missing_sources_fail_closed_without_initializing_source_databases(ctx,tmp_path):
    service,intake,authority,_=ctx
    missing=tmp_path/"missing.db"
    service.mission_source=MissionAuthorizationSource(missing)
    assert service.health()["status"]=="degraded"
    with pytest.raises(ExecutionSourceUnavailable):service.authorize_execution(intake)
    assert not missing.exists() and authority.calls==[]


def test_stale_expiry_after_source_recheck_cannot_be_reported_as_current(ctx,monkeypatch):
    service,intake,authority,_=ctx
    clocks=iter([NOW,NOW,NOW+timedelta(minutes=6)])
    service.clock=lambda:next(clocks)
    with pytest.raises(ExecutionGovernanceProtocolError):service.authorize_execution(intake)
    assert service.repository.list_authorizations(intake["execution_id"])==[]


def test_malformed_source_read_is_reported_as_integrity_failure(ctx):
    service,intake,authority,_=ctx
    with sqlite3.connect(service.proposal_source.sqlite_path) as conn:
        conn.execute("UPDATE pentest_tasks SET task_json='{}'")
    with pytest.raises(ExecutionRequestIntegrityError):service.authorize_execution(intake)
    assert authority.calls==[]


def test_replay_after_restart_is_historical_and_does_not_reauthorize(ctx):
    service,intake,authority,_=ctx
    first=service.authorize_execution(intake)
    restarted=ExecutionAuthorizationService(ExecutionAuthorizationRepository(service.repository.sqlite_path),
        service.proposal_source,service.mission_source,authority,clock=lambda:NOW+timedelta(days=1))
    replay=restarted.authorize_execution(intake)
    assert replay["record"] == first["record"] and replay["stored_at"] == first["stored_at"]
    assert replay["historical_record"] is True and replay["execution_authorized"] is False
    assert replay["authorization_current"] is False and replay["created"] is False and len(authority.calls)==1


def test_fresh_revalidation_observes_new_revocation_and_never_uses_old_allow(ctx):
    service,intake,authority,_=ctx
    assert service.authorize_execution(intake)["execution_authorized"] is True
    authority.mutate=lambda d:d["execution_revalidation"].update(revoked=True)
    second={**intake,"revalidation_id":"eauthreq-revoked","idempotency_key":"idem-revoked"}
    assert service.authorize_execution(second)["execution_authorized"] is False
    assert len(service.repository.list_authorizations(intake["execution_id"]))==2


@pytest.mark.parametrize("exc",[ExecutionGovernanceUnavailable("offline"),ExecutionGovernanceProtocolError("malformed")])
def test_authority_failure_does_not_fallback_to_previous_allow(ctx,monkeypatch,exc):
    service,intake,authority,_=ctx
    service.authorize_execution(intake)
    def fail(_): raise exc
    monkeypatch.setattr(authority,"evaluate_authorization",fail)
    second={**intake,"revalidation_id":"eauthreq-outage","idempotency_key":"idem-outage"}
    with pytest.raises(type(exc)): service.authorize_execution(second)
    assert len(service.repository.list_authorizations(intake["execution_id"]))==1


def test_idempotency_conflict_and_concurrent_replay(ctx):
    service,intake,authority,_=ctx
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(service.authorize_execution,[intake]*5))
    assert sum(x["created"] for x in results)==1 and len(authority.calls)==1
    assert sum(x["execution_authorized"] for x in results)==1
    with pytest.raises(ExecutionRequestConflict): service.authorize_execution({**intake,"requested_by":"different-actor"})


@pytest.mark.parametrize("state",["PAUSED","ABORTED","COMPLETED","WAITING_APPROVAL","REPLANNING"])
def test_non_running_mission_cannot_obtain_execution_authorization(ctx,state):
    service,intake,authority,_=ctx
    with sqlite3.connect(service.mission_source.sqlite_path) as conn:
        conn.execute("UPDATE mission_states SET state=?",(state,))
    with pytest.raises(ExecutionSourceRejected): service.authorize_execution(intake)
    assert authority.calls==[]


def test_changed_context_during_governance_is_rejected(ctx):
    service,intake,authority,_=ctx
    def changed(_):
        with sqlite3.connect(service.mission_source.sqlite_path) as conn:
            conn.execute("UPDATE mission_states SET state_version=state_version+1")
    authority.mutate=changed
    with pytest.raises(ExecutionSourceRejected): service.authorize_execution(intake)
    assert service.repository.list_authorizations(intake["execution_id"])==[]


def test_pentest_termination_after_request_prevents_fresh_authorization(ctx):
    service,intake,authority,_=ctx
    with sqlite3.connect(service.proposal_source.sqlite_path) as conn:
        conn.execute("UPDATE pentest_agentic_orchestrations SET orchestration_status='TERMINATED'")
    with pytest.raises(ExecutionSourceRejected): service.authorize_execution(intake)
    assert authority.calls==[]


def test_append_only_and_tampering_are_detected(ctx):
    service,intake,authority,_=ctx
    result=service.authorize_execution(intake)
    for sql in ("UPDATE execution_authorizations SET decision='ALLOW'","DELETE FROM execution_authorizations"):
        with sqlite3.connect(service.repository.sqlite_path) as conn:
            with pytest.raises(sqlite3.IntegrityError):conn.execute(sql)
    with sqlite3.connect(service.repository.sqlite_path) as conn:
        conn.execute("DROP TRIGGER execution_authorizations_no_update")
        conn.execute("UPDATE execution_authorizations SET mission_id='mission-gmo-forged'")
    with pytest.raises(ExecutionRequestIntegrityError): service.repository.get_authorization(result["authorization_id"])


def test_resigned_record_cannot_change_decision_without_matching_authority(ctx):
    service,intake,authority,_=ctx
    authority.decision="DENY"
    record=service.authorize_execution(intake)["record"]
    record.pop("integrity"); record["decision"]="ALLOW"; record["execution_authorized_at_evaluation"]=True
    assert not verify_authorization_record(with_integrity(record,AUTHORIZATION_RECORD_DOMAIN))


def test_migration_preserves_stage61_envelopes_and_rejects_future_metadata(ctx,tmp_path):
    service,intake,_,request=ctx
    path=tmp_path/"v1.db"
    v1=ExecutionRequestRepository(path)
    v1.append(request["envelope"])
    upgraded=ExecutionAuthorizationRepository(path)
    assert upgraded.migration_level()==2
    assert upgraded.get(intake["execution_id"])["envelope"]==request["envelope"]
    with sqlite3.connect(path) as conn: conn.execute("UPDATE execution_repository_meta SET migration_level=3")
    before=path.read_bytes()
    with pytest.raises(ExecutionRepositoryError):ExecutionAuthorizationRepository(path).initialize()
    assert path.read_bytes()==before


def test_source_aliases_and_foreign_databases_are_rejected_before_writing(ctx,tmp_path):
    service=ctx[0]
    alias=tmp_path/"mission-alias.db"
    os.link(service.mission_source.sqlite_path,alias)
    before=alias.read_bytes()
    with pytest.raises(ExecutionRequestValidationError):
        ExecutionAuthorizationService(ExecutionAuthorizationRepository(alias),service.proposal_source,service.mission_source,ctx[2])
    assert alias.read_bytes()==before
    with pytest.raises(ExecutionRepositoryError):ExecutionAuthorizationRepository(service.mission_source.sqlite_path).initialize()


def test_api_reports_gate_and_historical_reads_without_actuation(ctx):
    service,intake,authority,_=ctx
    with server_for(service) as base:
        code,health,headers=http(base+"/health")
        assert code==200 and "APTSExecutionSubsystem/6.2" in headers["Server"]
        assert health["execution_repository_migration_level"]==2
        assert health["mission_repository_migration_level"]==53 and health["pentest_repository_migration_level"]==16
        assert health["control_version"]==EXECUTION_AUTHORIZATION_CONTROL_VERSION and health["next_stage"]=="6.3"
        assert verify_execution_authorization_contract(http(base+"/api/execution/execution-authorization-contract")[1]["contract"])
        code,result,_=http(base+"/api/execution/authorizations",intake)
        assert code==201 and result["execution_authorized"] is True
        assert http(base+"/api/execution/authorizations",intake)[1]["execution_authorized"] is False
        code,read,_=http(base+"/api/execution/authorizations/"+result["authorization_id"])
        assert code==200 and read["historical_record"] is True and read["authorization_current"] is False
        listed=http(base+"/api/execution/authorizations?execution_id="+intake["execution_id"])[1]
        assert listed["count"]==1 and listed["execution_authorized"] is False
        assert http(base+"/api/execution/authorizations")[0]==400
        assert http(base+"/api/execution/authorizations/eauth-missing")[0]==404
        assert http(base+"/api/execution/authorizations",{**intake,"decision":"ALLOW"})[0]==400
        for path in ["dispatches","results","tool-invocations"]:
            assert http(base+"/api/execution/"+path,{})[0]==409


@pytest.mark.parametrize("url",["http://example.com","file:///tmp/gss","http://user:pass@localhost:8770","http://localhost:8770?url=x","http://localhost:8770/other"])
def test_authority_transport_rejects_untrusted_configuration(url):
    with pytest.raises(ExecutionRequestValidationError):ExecutionGovernanceClient(url)


@pytest.mark.parametrize("raw",[b'{"x":1,"x":2}',b'{"x":NaN}',b'[]',b'\xff',b'{'])
def test_authority_transport_rejects_ambiguous_json(raw):
    with pytest.raises(ExecutionGovernanceProtocolError):strict_json(raw)


@pytest.mark.parametrize("mode",["valid","missing-proof","redirect","non-completed","duplicate","unavailable"])
def test_real_http_authority_transport_and_fail_closed_envelopes(ctx,mode):
    service,intake,authority,_=ctx
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path=="/api/governance/authorization/evaluate"
            decision=authority.evaluate_authorization(payload)
            if mode=="missing-proof":decision.pop("execution_revalidation")
            response={"status":"completed" if mode!="non-completed" else "pending","policy_decision":decision}
            raw=json.dumps(response).encode()
            if mode=="duplicate":raw=b'{"status":"completed","status":"pending"}'
            self.send_response(302 if mode=="redirect" else 503 if mode=="unavailable" else 200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(raw)))
            if mode=="redirect":self.send_header("Location","http://127.0.0.1:1/forbidden")
            self.end_headers(); self.wfile.write(raw)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True); thread.start()
    service.governance_client=ExecutionGovernanceClient(f"http://127.0.0.1:{server.server_address[1]}")
    try:
        with server_for(service) as base:
            code,result,_=http(base+"/api/execution/authorizations",intake)
            if mode=="valid":assert code==201 and result["execution_authorized"] is True
            else:assert code==503 and result["execution_authorized"] is False
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
