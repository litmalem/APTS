"""Console security, transactional revisions, read models and loopback BFF tests."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
import threading
import time

from fastapi.testclient import TestClient
import pytest
import requests
from app import main, approval_auth
from app.approval_auth import REGISTRY_SCHEMA
from app.console_auth import capabilities
from app.approval_auth import ApprovalPrincipal
from gss_web.server import Server, UpstreamError

TOKEN='t'*48

class FakeDB:
    def __init__(self):
        self.calls=[]; self.old={'scope_contract_id':'scope-old','mission_id':'mission-test','version':1,'status':'ACTIVE'}
        self.policy={'policy_set_id':'default-policy','name':'Default','description':'','status':'ACTIVE','version':1}
        self.emergency={'version':1,'active':0}; self.rolled_back=False
    @contextmanager
    def connect(self):
        before=deepcopy((self.old,self.policy,self.emergency))
        try: yield self
        except Exception:
            self.old,self.policy,self.emergency=before; self.rolled_back=True; raise
    def fetch_one(self,sql,params=None):
        self.calls.append((sql,params))
        if 'COUNT(*) AS n' in sql:return {'n':1}
        if 'FOR UPDATE' in sql:
            return deepcopy(self.emergency if 'gov_emergency_state' in sql else self.policy if 'gov_policy_sets' in sql else self.old)
        if 'pending_approvals' in sql:return {'pending_approvals':2,'active_scopes':1,'expiring_scopes':0,'failed_events':0}
        raise AssertionError(sql)
    def fetch_all(self,sql,params=None):
        self.calls.append((sql,params))
        if 'DISTINCT mission_id' in sql:return [{'mission_id':'mission-test'}]
        return [{'id':1,'scope_contract_id':'scope-old','metadata_json':'{"source":"fixture"}'}]
    def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if 'UPDATE gov_scope_contracts' in sql:self.old['status']='REVOKED'
        if 'UPDATE gov_policy_sets' in sql:self.policy.update(version=self.policy['version']+1,name=params['name'],description=params['description'],status=params['status'])
        return 1

class FakeService:
    def __init__(self):
        self.db=FakeDB(); self.repo=SimpleNamespace(db=self.db,get_policy_set=lambda _:deepcopy(self.db.policy))
        self.audit_rows=[]; self.events_rows=[]; self.created=[]; self.fail_create=False
        self.audit=SimpleNamespace(record=lambda *a,**k:self.audit_rows.append((a,k)))
        self.events=SimpleNamespace(publish=lambda *a,**k:self.events_rows.append((a,k)),deliver_pending=lambda **k:0)
    def create_scope_contract(self,payload,revision_version=1):
        self.created.append(payload)
        if self.fail_create:raise RuntimeError('synthetic failure')
        return {**payload.model_dump(mode='json'),'scope_contract_id':'scope-new','version':revision_version}
    def activate_emergency_stop(self,payload):
        self.created.append(payload);self.db.emergency.update(active=1,version=2);return deepcopy(self.db.emergency)
    def release_emergency_stop(self,payload):
        self.created.append(payload);self.db.emergency.update(active=0,version=2);return deepcopy(self.db.emergency)
    def revoke_decision(self,ident,payload):self.created.append(payload);return {'decision_id':ident}

@pytest.fixture
def console(tmp_path,monkeypatch):
    path=tmp_path/'principals.json'; service=FakeService()
    def role(roles):
        path.write_text(json.dumps({'schema_version':REGISTRY_SCHEMA,'principals':[{'principal_id':'person-01','principal_type':'HUMAN','roles':roles,'token_sha256':hashlib.sha256(TOKEN.encode()).hexdigest(),'enabled':True}]}))
    role(['GOVERNANCE_ADMIN'])
    monkeypatch.setattr(main,'service',service)
    monkeypatch.setattr(approval_auth,'settings',replace(approval_auth.settings,approval_principals_file=str(path)))
    client=TestClient(main.app,raise_server_exceptions=False)
    client.headers['Authorization']='Bearer '+TOKEN
    return client,service,role

def scope_body():return {'contract':{'mission_id':'mission-test','name':'Test','created_by':'forged','approved_by':'forged'},'reason':'Reviewed limits','previous_id':'scope-old','expected_version':1}

@pytest.mark.parametrize('path',['console/me','console/overview','console/records/scopes'])
def test_reads_require_credential(console,path):
    c,_,_=console;c.headers.clear();assert c.get('/api/governance/'+path).status_code==401

@pytest.mark.parametrize('path,body',[
 ('console/scopes',scope_body()),('console/scopes/scope-old/revoke',{'reason':'test','expected_version':1}),
 ('emergency-stop/activate',{'actor_id':'forged','reason':'test'}),('emergency-stop/release',{'actor_id':'forged','reason':'test'}),
 ('decisions/gdec-1/revoke',{'actor_id':'forged','reason':'test'}),('events/retry',{})])
def test_viewer_cannot_mutate(console,path,body):
    c,s,role=console;role(['VIEWER']);assert c.post('/api/governance/'+path,json=body).status_code==403;assert not s.created


def test_admin_cannot_grant_self_human_approval_role():
    p=ApprovalPrincipal('admin',frozenset(['GOVERNANCE_ADMIN']),'HUMAN')
    assert 'approve' not in capabilities(p)


def test_pagination_and_search_are_bound(console):
    c,s,_=console;r=c.get('/api/governance/console/records/scopes',params={'q':"' OR 1=1 --",'mission_id':'mission-test','page':2,'limit':10})
    assert r.status_code==200 and r.json()['items'][0]['metadata']=={'source':'fixture'}
    sql,params=s.db.calls[-1];assert 'OR 1=1' not in sql and params['q']=="%' OR 1=1 --%" and params['offset']==10
    assert c.get('/api/governance/console/records/scopes?limit=5000').status_code==422
    assert c.get('/api/governance/console/records/credentials').status_code==404


def test_expired_queue_uses_database_clock(console):
    c,s,_=console;c.get('/api/governance/console/records/approvals?status=EXPIRED')
    assert 'expires_at<=UTC_TIMESTAMP()' in s.db.calls[-1][0]


def test_scope_revision_identity_and_version(console):
    c,s,_=console;r=c.post('/api/governance/console/scopes',json=scope_body())
    assert r.status_code==200 and r.json()['scope_contract']['version']==2
    assert s.created[0].created_by=='person-01' and s.created[0].approved_by=='person-01'
    assert s.created[0].metadata['supersedes_scope_id']=='scope-old' and s.db.old['status']=='REVOKED'
    assert c.post('/api/governance/console/scopes',json=scope_body()).status_code==409


def test_scope_revision_failure_rolls_back(console):
    c,s,_=console;s.fail_create=True;assert c.post('/api/governance/console/scopes',json=scope_body()).status_code==500
    assert s.db.old['status']=='ACTIVE' and s.db.rolled_back


def test_scope_revision_rejects_cross_mission(console):
    c,_,_=console;body=scope_body();body['contract']['mission_id']='other'
    assert c.post('/api/governance/console/scopes',json=body).status_code==422


def test_scope_invalid_interval(console):
    c,_,_=console;body=scope_body();body['contract']['valid_until']='2020-01-01T00:00:00Z'
    assert c.post('/api/governance/console/scopes',json=body).status_code==422


def test_policy_update_increments_version_and_audits(console):
    c,s,_=console;body={'reason':'Maintenance','expected_version':1,'name':'Changed','description':'Test','status':'RETIRED'}
    r=c.post('/api/governance/console/policies/default-policy',json=body)
    assert r.status_code==200 and r.json()['policy']['version']==2
    assert s.audit_rows[-1][1]['payload']['before']['status']=='ACTIVE'
    assert s.events_rows[-1][0]==('POLICY_CHANGED',)
    assert c.post('/api/governance/console/policies/default-policy',json=body).status_code==409


def test_operator_can_activate_but_not_release(console):
    c,s,role=console;role(['OPERATOR']);body={'actor_id':'forged','reason':'Stop review','metadata':{'expected_version':1}}
    assert c.post('/api/governance/emergency-stop/activate',json=body).status_code==200
    assert s.created[-1].actor_id=='person-01'
    assert c.post('/api/governance/emergency-stop/release',json=body).status_code==403


def test_stale_emergency_state_rejected(console):
    c,s,_=console;body={'actor_id':'forged','reason':'Stop review','metadata':{'expected_version':99}}
    assert c.post('/api/governance/emergency-stop/activate',json=body).status_code==409
    assert s.db.emergency['active']==0

@pytest.mark.parametrize('endpoint',['scope-contracts','authorization/evaluate','authorization/revalidate'])
def test_browser_cannot_call_legacy_machine_writes(console,endpoint):
    c,_,_=console;assert c.post('/api/governance/'+endpoint,json={},headers={'Origin':'http://127.0.0.1:8802'}).status_code==403

@pytest.fixture
def web():
    server=Server(0);calls=[];disabled=[False]
    def upstream(path,token,body=None):
        calls.append((path,token,body))
        if disabled[0] or token!=TOKEN:raise UpstreamError(401,{'detail':'Invalid credential'})
        if path.endswith('/console/me'):return {'principal_id':'person-01','roles':['VIEWER'],'capabilities':['read']}
        return {'status':'ok'}
    server.upstream=upstream
    mission_calls=[]
    def mission_upstream(path,body=None):
        mission_calls.append((path,body))
        if path == '/api/missions' and body is not None:
            return {'status':'registered','idempotent_replay':False,'canonical_identity':{'mission_id':'mission-human-01','envelope_id':'env-human-01'}}
        if path.startswith('/api/operator/attention/advanced'):
            return {'status':'completed','attention_count':0,'items':[]}
        if path.startswith('/api/missions?') or path == '/api/missions':
            return {'status':'completed','mission_count':0,'missions':[]}
        if path.endswith('/state'):
            return {'status':'completed','mission_state':{'state':'REGISTERED','state_version':1}}
        if path.endswith('/envelope'):
            return {'status':'completed','envelope':{'mission':{'objective':{'goal':'test'},'required_subsystems':['CTI','PENTEST']}}}
        if path.endswith('/governance-visibility'):
            return {'status':'completed','mission_id':'mission-human-01'}
        if path.startswith('/api/missions/'):
            return {'status':'completed','mission':{'mission_id':'mission-human-01','created_by':'person-01','source_system':'HUMAN_LAYER'}}
        raise UpstreamError(404,{'detail':'Mission route not stubbed'})
    server.mission_upstream=mission_upstream
    server._mission_calls=mission_calls
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}';session=requests.Session();session.trust_env=False
    yield server,url,session,calls,disabled
    session.close();server.shutdown();server.server_close();thread.join()


def login(web):
    _,url,s,_,_=web;r=s.post(url+'/api/login',json={'token':TOKEN},headers={'Origin':url});assert r.status_code==200
    return {'Origin':url,'X-CSRF-Token':r.json()['csrf']},r


def test_bff_login_session_no_plaintext_token(web):
    _,url,s,_,_=web;h,r=login(web)
    assert TOKEN not in r.text and TOKEN not in r.headers['Set-Cookie']
    assert 'HttpOnly' in r.headers['Set-Cookie'] and 'SameSite=Strict' in r.headers['Set-Cookie']
    assert s.get(url+'/api/session').json()['principal_id']=='person-01'
    assert s.get(url+'/').headers['Content-Security-Policy'].startswith("default-src 'self'")

@pytest.mark.parametrize('path',['/api/login','/api/governance/events/retry'])
def test_bff_cross_origin_denied(web,path):
    _,url,s,_,_=web;r=s.post(url+path,json={'token':TOKEN},headers={'Origin':'http://evil.example'})
    assert r.status_code==403


def test_bff_csrf_and_arbitrary_proxy_blocked(web):
    _,url,s,calls,_=web;headers,_=login(web)
    assert s.post(url+'/api/governance/events/retry',json={},headers={'Origin':url}).status_code==403
    before=len(calls)
    assert s.post(url+'/api/governance/scope-contracts',json={},headers=headers).status_code==404
    assert all(path!='/api/governance/scope-contracts' for path,_,_ in calls[before:])
    assert s.get(url+'/api/governance/%2Fsecret').status_code==404
    assert s.get(url+'/',headers={'Host':'evil.example'}).status_code==403


def test_bff_expiry_revocation_logout(web):
    server,url,s,_,disabled=web;headers,_=login(web);disabled[0]=True
    assert s.get(url+'/api/session').status_code==401;disabled[0]=False
    assert s.post(url+'/api/logout',json={},headers=headers).status_code==200
    assert s.get(url+'/api/session').status_code==401
    login(web)
    for sess in server.sessions.values():sess['expires']=time.monotonic()-1
    assert s.get(url+'/api/session').status_code==401


def test_bff_api_offline_is_not_reported_as_healthy(web):
    server,url,s,_,_=web;login(web)
    def offline(*a,**k):raise UpstreamError(503,{'detail':'GSS tidak terjangkau; status tidak diketahui.'})
    server.upstream=offline
    assert s.get(url+'/api/governance/runtime/status').status_code==503
    assert s.get(url+'/health').json()['governance_status']=='not_checked'


def test_explicit_human_contract_endpoints_require_read(console):
    c,_,_=console
    layer=c.get('/api/governance/human-layer')
    interaction=c.get('/api/governance/human-interaction')
    assert layer.status_code==200 and layer.json()['component_id']=='HUMAN-LAYER'
    assert interaction.status_code==200 and interaction.json()['component_id']=='HUMAN-INTERACTION'
    assert interaction.json()['principal']['principal_id']=='person-01'


def test_bff_human_mission_authoring_is_server_owned_and_bounded(web):
    server,url,s,calls,_=web
    headers,_=login(web)
    original=server.upstream
    def operator_upstream(path,token,body=None):
        if path.endswith('/console/me'):
            return {'principal_id':'person-01','roles':['OPERATOR'],'capabilities':['read','mission_author','emergency_activate','retry']}
        return original(path,token,body)
    server.upstream=operator_upstream
    body={
        'client_request_id':'hui-test-001',
        'mission_kind':'AUTHORIZED_PENTEST',
        'objective_type':'AUTHORIZED_PENTEST',
        'objective':'Validate the explicitly authorized lab scope and collect evidence.',
        'success_criteria':['Evidence is recorded'],
        'budgets':{'max_duration_seconds':600},
        'required_subsystems':['CTI','PENTEST'],
        'metadata':{'test':True},
    }
    r=s.post(url+'/api/human/missions',json=body,headers=headers)
    assert r.status_code==200
    assert r.json()['canonical_identity']['mission_id']=='mission-human-01'
    path,payload=server._mission_calls[-1]
    assert path=='/api/missions'
    assert payload['created_by']=='person-01'
    assert payload['source_system']=='HUMAN_LAYER'
    assert payload['idempotency_key']=='human-ui-hui-test-001'
    assert payload['metadata']['human_interaction']['principal_id']=='person-01'
    assert 'scope_contract_id' not in payload and 'authorized' not in payload


def test_bff_human_mission_authoring_requires_capability(web):
    _,url,s,_,_=web
    headers,_=login(web)
    r=s.post(url+'/api/human/missions',json={'objective':'test'},headers=headers)
    assert r.status_code==403


def test_bff_human_mission_read_uses_only_constructed_mission_paths(web):
    server,url,s,_,_=web
    login(web)
    r=s.get(url+'/api/human/missions/mission-human-01')
    assert r.status_code==200
    paths=[p for p,b in server._mission_calls]
    assert '/api/missions/mission-human-01' in paths
    assert '/api/missions/mission-human-01/state' in paths
    assert '/api/missions/mission-human-01/envelope' in paths
    assert '/api/missions/mission-human-01/governance-visibility' in paths
    assert s.get(url+'/api/human/proxy?url=http://example.com').status_code==404
