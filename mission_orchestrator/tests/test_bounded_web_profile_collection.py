import base64,hashlib,json,time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import pytest
from adapters.profile_contract import validate_profile
from execution_subsystem.adapter_policy import DEFAULT_LIMITS
from execution_subsystem.execution_contract import ExecutionSourceRejected
from execution_subsystem.sandbox_runtime import ResourceSandbox
from execution_subsystem.target_broker import TargetBroker,PinnedTarget
from execution_subsystem.tool_registry import ADAPTERS
from execution_subsystem.web_profile_collection import collect_profile,redirect_destination
from execution_subsystem.wpt_intake_service import WPTIntakeService
ADAPTER=next(a for a in ADAPTERS if a.operation=='WEB_PROFILE_FINGERPRINT')
LIMITS={**DEFAULT_LIMITS,'timeout_seconds':15,'max_network_bytes':393216,'max_output_bytes':60000,'rate_requests':100,'rate_window_seconds':.01}
@pytest.fixture
def site():
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            if self.path=='/app/':
                self.send_response(302);self.send_header('Location','/app/login.php');self.send_header('X-Powered-By','PHP/8.0.30')
                self.send_header('Set-Cookie','PHPSESSID=private-session; HttpOnly');self.end_headers()
            elif self.path=='/app/login.php':
                self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Server','Apache/2.4.58');self.end_headers()
                self.wfile.write(b'<title>Application Login</title><script src="/app/yii.js?token=private-token"></script>')
            elif self.path=='/app/favicon.ico':
                self.send_response(200);self.send_header('Content-Type','image/x-icon');self.end_headers();self.wfile.write(b'icon-image')
            else:self.send_response(404);self.end_headers()
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    yield server,seen
    server.shutdown();server.server_close()
def collect(site,budget=6):
    server,seen=site;target=f'http://127.0.0.1:{server.server_port}/app';pin=PinnedTarget('127.0.0.1','127.0.0.1',server.server_port,'/app',False)
    calls=[]
    def validate(url,child):
        if not child.path.startswith('/app/') or child.ip!=pin.ip:raise ExecutionSourceRejected('outside scope')
    raw=collect_profile(TargetBroker(),ADAPTER,pin,target,LIMITS,budget,deadline=time.monotonic()+8,before_io=lambda:calls.append(True),validate_child=validate)
    with ResourceSandbox(LIMITS) as worker:result=worker.parse(ADAPTER.operation,raw,deadline=time.monotonic()+5)
    assert len(calls)==len(seen)
    return raw,result

def test_full_profile_follows_scoped_redirect_and_captures_stack(site):
    raw,r=collect(site)
    assert site[1]==['/app/','/app/login.php','/app/favicon.ico']
    page=r['observations'][0]
    assert page['page_title']=='Application Login' and page['final_url'].endswith('/app/login.php')
    assert page['cookie_names']==['PHPSESSID'] and page['script_sources']==['/app/yii.js']
    assert r['observations'][1]['favicon_fingerprint']['sha256']==hashlib.sha256(b'icon-image').hexdigest()
    assert any('Apache' in f['technology'] for f in r['technology_findings']) and any('PHP' in f['technology'] for f in r['technology_findings'])
    assert r['scan_metrics']['requests_performed']==3 and r['scan_metrics']['responses_received']==3
    assert r['network_binding']['response_sha256']==hashlib.sha256(base64.b64decode(raw['response_b64'])).hexdigest()
    assert 'private-session' not in repr(r) and 'private-token' not in repr(r)
    assert WPTIntakeService._safe_observation(r)==r
@pytest.mark.parametrize('budget',[1,2])
def test_budget_is_respected_and_partial_result_explained(site,budget):
    _,r=collect(site,budget)
    assert len(site[1])==budget and r['scan_metrics']['scan_status']=='PARTIAL'
    assert r['technology_findings']

ENUM_ADAPTER=next(a for a in ADAPTERS if a.operation=='WEB_PROFILE_ENUMERATION')
CTI_CONTEXT={
    'technologies':[{'name':'nginx','version':'1.24.0'}],
    'cpe_candidates':[{'technology_name':'nginx','cpe23_uri':'cpe:2.3:a:f5:nginx:1.24.0:*:*:*:*:*:*:*',
                       'match_confidence':0.99,'status':'CPE_CANDIDATE_NEEDS_VERIFICATION'}],
}
def _enumerate(site,enumeration_context):
    server,seen=site;target=f'http://127.0.0.1:{server.server_port}/app'
    pin=PinnedTarget('127.0.0.1','127.0.0.1',server.server_port,'/app',False)
    def validate(url,child):
        if not child.path.startswith('/app/') or child.ip!=pin.ip:raise ExecutionSourceRejected('outside scope')
    raw=collect_profile(TargetBroker(),ENUM_ADAPTER,pin,target,LIMITS,9,deadline=time.monotonic()+8,
        before_io=lambda:None,validate_child=validate,enumeration_context=enumeration_context)
    with ResourceSandbox(LIMITS) as worker:result=worker.parse(ENUM_ADAPTER.operation,raw,deadline=time.monotonic()+5)
    return seen,result
def test_cti_enrichment_drives_bounded_followup_enumeration_probe(site):
    # With verified CTI enrichment (nginx), enumeration appends exactly the
    # deterministic follow-up probe and actually requests it against the target.
    seen,result=_enumerate(site,CTI_CONTEXT)
    assert '/app/nginx_status' in seen
    assert len(result['observations'])==6
    assert any(o['url'].endswith('/app/nginx_status') for o in result['observations'])
    assert result['enumeration_context']==CTI_CONTEXT
    assert validate_profile(result)==result
def test_enumeration_without_cti_keeps_fixed_five_probe_footprint(site):
    # No enrichment -> original 5-probe bounded plan, no carried context.
    _,result=_enumerate(site,None)
    assert len(result['observations'])==5
    assert not any(o['url'].endswith('/app/nginx_status') for o in result['observations'])
    assert 'enumeration_context' not in result
    assert validate_profile(result)==result
@pytest.mark.parametrize('location',['https://outside.test/app/','//outside.test/app/','/other/','/application/','/app/../outside','/app/login?token=secret'])
def test_redirect_rejects_outside_origin_prefix_and_query(location):
    assert redirect_destination('http://example.test/app','http://example.test/app/',location) is None
@pytest.mark.parametrize('field,value',[('headers',{'set-cookie':'secret'}),('cookie_names',['PHPSESSID=secret']),('script_sources',['/asset.js?token=secret'])])
def test_sensitive_fields_rejected(site,field,value):
    _,r=collect(site);r['observations'][0][field]=value
    with pytest.raises(ValueError):validate_profile(r)
    with pytest.raises(Exception,match='Invalid sanitized'):WPTIntakeService._safe_observation(r)
def test_exclusions_and_pin_remain_enforced():
    from dataclasses import replace
    broker=TargetBroker();pin=PinnedTarget('127.0.0.1','127.0.0.1',8080,'/app',False)
    req={'target':{'target_type':'URL','target_value':'http://127.0.0.1:8080/app'}}
    scope={'scope':{'targets':[req['target']],'excluded_targets':[{'target_type':'URL','target_value':'http://127.0.0.1:8080/app/private'}]}}
    ctx={'mission_scope':scope,'pentest_context':{'boundary':deepcopy(scope),'task':deepcopy(scope)}}
    broker.validate_profile_pin(req,ctx,ADAPTER,pin,'http://127.0.0.1:8080/app/login',replace(pin,path='/app/login'))
    with pytest.raises(ExecutionSourceRejected,match='EXCLUDED'):broker.validate_profile_pin(req,ctx,ADAPTER,pin,'http://127.0.0.1:8080/app/private/x',replace(pin,path='/app/private/x'))
    with pytest.raises(ExecutionSourceRejected,match='PIN_CHANGED'):broker.validate_profile_pin(req,ctx,ADAPTER,pin,'http://127.0.0.1:8080/app/login',replace(pin,path='/app/login',ip='127.0.0.2'))
def test_runtime_captures_combined_response_digest_once(site):
    from execution_subsystem.runtime_control import RuntimeResources
    server,seen=site;guard=RuntimeResources(time.monotonic()+10);calls=[]
    class Capture:
        def observe_target(self,o,*,complete):calls.append((o,complete))
    guard.evidence_capture=Capture()
    target=f'http://127.0.0.1:{server.server_port}/app';pin=PinnedTarget('127.0.0.1','127.0.0.1',server.server_port,'/app',False)
    try:raw=collect_profile(TargetBroker(),ADAPTER,pin,target,LIMITS,6,deadline=time.monotonic()+8,before_io=lambda:None,validate_child=lambda u,p:None,runtime=guard)
    finally:guard.finish()
    assert len(calls)==1 and calls[0][1] is True and calls[0][0]['response_sha256']==raw['response_sha256']
def test_real_wpt_callback_accepts_safe_metadata_and_rejects_cookie_value(site,tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    _,result=collect(site)
    spec=importlib.util.spec_from_file_location('bounded_wpt',Path(__file__).resolve().parents[2]/'WebTechnologyProfiler/app.py')
    app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
    monkeypatch.setattr(app,'DB_PATH',tmp_path/'wpt.db');monkeypatch.setattr(app,'CLIENT_TOKEN','s'*40)
    server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    def post(path,body):
        with urlopen(Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-APTS-Client-Token':'s'*40},method='POST'),timeout=3) as response:return json.load(response)
    try:
        req={'schema_version':'apts-wpt-governed-intake-v1','intake_id':'wptreq-integration','idempotency_key':'idem-integration','mission_id':'mission-gmo-test','task_id':'ptask-test','target':{'target_type':'URL','target_value':result['target']},'profile':'fingerprinting'}
        post('/api/governed-intakes',req)
        job=post('/api/stage6/intakes/wptreq-integration/job',{'schema_version':'apts-wpt-stage6-job-v1','mission_id':req['mission_id'],'task_id':req['task_id'],'target':result['target'],'profile':'fingerprinting','execution_id':'exec-test','status':'RUNNING','authorization_id':'eauth-test'})['job']
        result.update(mission_id=req['mission_id'],task_id=req['task_id'],profile='fingerprinting',status='SUCCEEDED',evidence={'capture_status':'SEALED','manifest_sha256':'f'*64,'evidence_ref':'stage6-evidence://xevidence-test'})
        body={'status':'COMPLETED','execution_id':'exec-test','result':result,'result_sha256':app.canonical_sha256(result)}
        post('/api/jobs/'+job['job_id']+'/result',body)
        with urlopen(base+'/api/jobs/'+job['job_id']) as response:stored=json.load(response)['job']
        assert stored['status']=='COMPLETED' and stored['result']['technology_findings']
        monkeypatch.setattr(app,'now',lambda:'2099-01-01T00:00:00+00:00')
        post('/api/jobs/'+job['job_id']+'/result',body)
        with urlopen(base+'/api/jobs/'+job['job_id']) as response:repeated=json.load(response)['job']
        assert (repeated['scan_finished_at'],repeated['scan_duration_ms'],repeated['updated_at']) == (
            stored['scan_finished_at'],stored['scan_duration_ms'],stored['updated_at'])
        replay=post('/api/stage6/intakes/wptreq-integration/job',{'schema_version':'apts-wpt-stage6-job-v1',
            'mission_id':req['mission_id'],'task_id':req['task_id'],'target':result['target'],'profile':'fingerprinting',
            'execution_id':'exec-test','status':'AWAITING_STAGE6','authorization_id':None})
        assert replay['historical_status_ignored'] is True
        assert replay['job']['status']=='COMPLETED' and replay['job']['result_sha256']==stored['result_sha256']
        result['observations'][0]['headers']['set-cookie']='private-session';body['result_sha256']=app.canonical_sha256(result)
        with pytest.raises(HTTPError) as error:post('/api/jobs/'+job['job_id']+'/result',body)
        assert error.value.code==400
    finally:server.shutdown();server.server_close()


def test_source_marker_does_not_grant_execution_permission():
    from execution_subsystem.adapter_policy import _data_policy
    _data_policy({'execution_authorized':False})
    with pytest.raises(ExecutionSourceRejected,match='CANNOT_GRANT'):_data_policy({'execution_authorized':True})


def test_wpt_evidence_enrollment_accepts_its_own_source_lineage(tmp_path,monkeypatch):
    from execution_subsystem.evidence_repository import ExecutionEvidenceRepository
    from execution_subsystem.runtime_repository import ExecutionRuntimeRepository
    from execution_subsystem.execution_contract import sha256_hex
    from execution_subsystem.tool_registry import registry_sha256
    monkeypatch.setattr(ExecutionRuntimeRepository,'_before_reservation_insert',lambda *args:None)
    ids={'attempt_id':'xattempt-test','invocation_id':'toolinv-test','execution_id':'exec-test','task_id':'ptask-test',
        'pentest_id':'pentest-test','pentest_task_id':'pentest-task-test','mission_id':'mission-gmo-test'}
    record={**ids,'authorized_at':'2026-11-06T00:00:00Z','integrity':{'canonical_sha256':'a'*64}}
    params={'source_wpt_intake_id':'wptreq-bound','estimated_impact':'LOW','expected_evidence':['bounded metadata']}
    req={'action':{'action_class':'TARGET_RECON','capability_id':'web_technology_fingerprinting','technique':'WEB_TECHNOLOGY_FINGERPRINT'},
        'target':{'target_type':'URL','target_value':'http://127.0.0.1/app'},'parameters':params}
    envelope={'intake':{'source_type':'WPT_GOVERNED_INTAKE'},'execution_request':req}
    claim={**ids,'status':'RESERVED','authorization_id':'eauth-test','integrity':{'canonical_sha256':'b'*64},
        'envelope_sha256':'c'*64,'registry_sha256':registry_sha256(),'controls':{'credential_lease_id':None},
        'authorization_record':{'evaluation':{'current_context':{}}}}
    repo=ExecutionEvidenceRepository(tmp_path/'evidence.db');artifacts={}
    monkeypatch.setattr(repo,'_envelope',lambda conn,identity:envelope)
    monkeypatch.setattr(repo,'_insert_artifact',lambda conn,session,kind,value,at:artifacts.update({kind:value}))
    class Conn:
        def execute(self,*args):return self
        def fetchone(self):return {'record_json':json.dumps(record)}
    repo._before_reservation_insert(Conn(),claim,{})
    action=artifacts['ACTION_PARAMETERS']
    assert action['parameters']['source_wpt_intake_id']=='wptreq-bound'
    assert action['parameters_sha256']==sha256_hex(params)
    assert action['authorization_id']=='eauth-test'


def test_recon_handoff_selects_current_repository_without_schema_downgrade(tmp_path,monkeypatch):
    import sqlite3
    from execution_subsystem.wpt_recon_source import recon_service
    from pentest_subsystem import reconnaissance as module
    from pentest_subsystem.task_repository import PENTEST_REPOSITORY_ID
    from pentest_subsystem.governance_bound_e2e import GovernanceBoundE2ERepository
    path=tmp_path/'pentest.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE pentest_repository_meta(repository_id TEXT,migration_level INTEGER)')
        conn.execute('INSERT INTO pentest_repository_meta VALUES (?,16)',(PENTEST_REPOSITORY_ID,))
    before=path.read_bytes()
    monkeypatch.setattr(module,'ReconnaissanceAgentService',lambda repository:repository)
    repository=recon_service(path)
    assert isinstance(repository,GovernanceBoundE2ERepository)
    assert path.read_bytes()==before
