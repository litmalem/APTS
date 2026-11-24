import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import pytest
from mission_orchestrator.mission_wpt_preparation import _start_stage6_runtime
ADMISSION={'status':'REQUEST_CREATED','execution_id':'exec-test','envelope_sha256':'a'*64}
INTAKE={'intake_id':'wptreq-test'}
@pytest.fixture
def server(monkeypatch):
    servers=[]
    def start(gate='ADMITTED_AWAITING_ADAPTER',consumed=False,initial_state='SUCCEEDED',history=None):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,body))
                code=200
                if self.path.endswith('/submissions'):result={'record':{'status':gate,'reason_codes':['TEST_DENY'] if gate!='ADMITTED_AWAITING_ADAPTER' else []}}
                elif consumed and len(calls)==1:code=409;result={'error':'HISTORICAL_ADAPTER_INTAKE_NOT_RUNTIME_ADMISSION'}
                else:result={'state':initial_state,'attempt_id':'xattempt-test','events':[{'event_type':'AUTHORIZED','data':{'authorization_id':'eauth-test'}}]}
                raw=json.dumps(result).encode();self.send_response(code);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                raw=json.dumps({'attempts':history or []}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*args):pass
        s=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=s.serve_forever,daemon=True).start();servers.append(s)
        monkeypatch.setenv('APTS_STAGE6_RUNTIME_URL',f'http://127.0.0.1:{s.server_port}')
        return calls
    yield start
    for s in servers:s.shutdown();s.server_close()
def test_runtime_performs_current_admission_and_binds_request(server):
    calls=server();r=_start_stage6_runtime(INTAKE,ADMISSION)
    assert r['status']=='SUCCEEDED' and r['authorization_id']=='eauth-test'
    assert [c[0] for c in calls]==['/api/execution/runtime/attempts']
    assert all(c[1]['execution_id']=='exec-test' and c[1]['envelope_sha256']=='a'*64 for c in calls)
def test_only_pre_attempt_consumed_identity_advances(server):
    calls=server(consumed=True);r=_start_stage6_runtime(INTAKE,ADMISSION)
    assert r['status']=='SUCCEEDED' and len(calls)==2
    assert calls[0][1]['invocation_request_id']!=calls[1][1]['invocation_request_id']

def test_corrected_scope_gets_new_stable_runtime_identity(server):
    calls=server()
    _start_stage6_runtime(INTAKE,ADMISSION)
    repaired={**ADMISSION,'runtime_scope_sha256':'b'*64}
    _start_stage6_runtime(INTAKE,repaired)
    _start_stage6_runtime(INTAKE,repaired)
    assert calls[0][1]['invocation_request_id']!=calls[1][1]['invocation_request_id']
    assert calls[1][1]==calls[2][1]

@pytest.mark.parametrize('envelope_sha,expected',[('a'*64,'SUCCEEDED'),('b'*64,'FAILED')])
def test_reconciles_explicit_retry_only_for_the_same_execution_binding(server,envelope_sha,expected):
    latest={'state':'SUCCEEDED','attempt_id':'xattempt-retry',
        'record':{'runtime_intake':{'execution_id':'exec-test','envelope_sha256':envelope_sha}},
        'events':[{'event_type':'AUTHORIZED','data':{'authorization_id':'eauth-retry'}}]}
    calls=server(initial_state='FAILED',history=[latest])
    result=_start_stage6_runtime(INTAKE,ADMISSION)
    assert result['status']==expected
    assert len(calls)==1  # No automatic re-scan or retry request.
    if expected=='SUCCEEDED':
        assert result['attempt_id']=='xattempt-retry'
        assert result['authorization_id']=='eauth-retry'

@pytest.mark.parametrize('status,reason', [('BLOCKED','AUTHORITATIVE_DENY'),
    ('RESERVED','HISTORICAL_ADAPTER_INTAKE_NOT_RUNTIME_ADMISSION')])
def test_replay_preserves_denial_instead_of_consuming_new_identities(monkeypatch,status,reason):
    from unittest.mock import Mock
    from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
    from execution_subsystem.execution_contract import ExecutionSourceRejected
    repo=ExecutionRuntimeRepository(':memory:')
    monkeypatch.setattr(repo,'initialize',lambda:None)
    conn=Mock()
    conn.execute.return_value.fetchone.return_value=None
    monkeypatch.setattr(repo,'_connect',lambda:conn)
    monkeypatch.setattr(repo,'_find_adapter',lambda *args:{'invocation_id':'toolinv-test',
        'record':{'status':status,'reason_codes':['AUTHORITATIVE_DENY'] if status=='BLOCKED' else []}})
    intake={**ADMISSION,'schema_version':'apts-execution-runtime-start-v1',
        'invocation_request_id':'toolreq-test','idempotency_key':'idem-test','requested_by':'test'}
    with pytest.raises(ExecutionSourceRejected,match=reason):repo.find_runtime_intake(intake)

def test_wpt_runtime_admission_does_not_bypass_general_recon_receipts(tmp_path):
    from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
    from execution_subsystem.execution_contract import ExecutionSourceRejected
    repo=ExecutionRuntimeRepository(tmp_path/'runtime.db')
    req={'action':{'action_class':'TARGET_RECON','capability_id':'web_technology_fingerprinting','technique':'WEB_TECHNOLOGY_FINGERPRINT'},
        'parameters':{'source_wpt_intake_id':'wptreq-bound'},'target':{'target_type':'URL'},'proposing_agent':{'role':'RECONNAISSANCE'}}
    assert repo._reservation_gateway(None,[],req) is None
    req['action']['technique']='TCP_CONNECT_SCAN'
    with pytest.raises(ExecutionSourceRejected,match='REQUIRES_STAGE6_3'):repo._reservation_gateway(None,[],req)


@pytest.mark.parametrize('reason,eligible,expected', [
    ('RESOLVED_ADDRESS_OUTSIDE_SCOPE',True,1), ('AUTHORITATIVE_DENY',True,1),
    ('ADAPTER_WALL_TIMEOUT',False,1), ('ADAPTER_WALL_TIMEOUT',True,2)])
def test_recovery_reuses_execution_and_requires_transient_no_io(server,reason,eligible,expected):
    latest = {'state':'FAILED','attempt_id':'xattempt-test','head_sha256':'c'*64,
        'retry_eligible_by_result':eligible,
        'record':{'attempt_number':1,'runtime_intake':{
            'execution_id':'exec-test','envelope_sha256':'a'*64}},
        'events':[{'event_type':'FAILED','data':{'reason_code':reason}}]}
    calls=server(initial_state='FAILED',history=[latest])
    _start_stage6_runtime(INTAKE,ADMISSION)
    assert len(calls)==expected
    if expected==2:
        path,body=calls[1]
        assert path=='/api/execution/runtime/retries'
        assert body['execution_id']=='exec-test'
        assert body['retry_of_attempt_id']=='xattempt-test'
        assert body['expected_head_sha256']=='c'*64
