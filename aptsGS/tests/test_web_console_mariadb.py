"""Real MariaDB console acceptance in an isolated schema; opt-in only."""
import os
import hashlib
import json
from dataclasses import replace
from fastapi.testclient import TestClient
import pytest
from app import main, approval_auth
from app.governance_service import GovernanceService
from app.approval_auth import REGISTRY_SCHEMA
from test_human_approval_mariadb import database

pytestmark=pytest.mark.skipif(not os.getenv('GSS_TEST_DB_CONFIG'),reason='Requires isolated MariaDB test configuration')
TOKEN='w'*48

@pytest.fixture
def console_db(database,tmp_path,monkeypatch):
    registry=tmp_path/'console-principals.json'
    registry.write_text(json.dumps({'schema_version':REGISTRY_SCHEMA,'principals':[{'principal_id':'console-test-admin','principal_type':'HUMAN','roles':['GOVERNANCE_ADMIN','SECURITY_APPROVER'],'token_sha256':hashlib.sha256(TOKEN.encode()).hexdigest(),'enabled':True}]}))
    service=GovernanceService(database)
    monkeypatch.setattr(main,'service',service)
    monkeypatch.setattr(approval_auth,'settings',replace(approval_auth.settings,approval_principals_file=str(registry)))
    client=TestClient(main.app)
    client.headers['Authorization']='Bearer '+TOKEN
    return client,service


def test_real_scope_revision_lists_policy_audit_and_overview(console_db):
    c,s=console_db
    body={'contract':{'mission_id':'console-db-test','name':'Test scope','created_by':'forged','targets':[], 'sources':[{'source_id':'nvd-cve'}],'action_constraints':[{'action_class':'CTI_SOURCE_READ','effect':'ALLOW','max_risk_level':'LOW','constraints':{'read_only':True}}]},'reason':'Synthetic database acceptance'}
    created=c.post('/api/governance/console/scopes',json=body);assert created.status_code==200,created.text
    first=created.json()['scope_contract'];assert first['created_by']=='console-test-admin'
    body.update(previous_id=first['scope_contract_id'],expected_version=1)
    revised=c.post('/api/governance/console/scopes',json=body);assert revised.status_code==200,revised.text
    second=revised.json()['scope_contract'];assert second['version']==2
    assert s.repo.get_scope_contract(first['scope_contract_id'])['status']=='REVOKED'
    for kind in ['scopes','approvals','decisions','policies','audit','emergency-history']:
        response=c.get('/api/governance/console/records/'+kind);assert response.status_code==200,response.text
    assert c.get('/api/governance/console/overview').status_code==200
    policy=c.get('/api/governance/console/policy/default-policy');assert policy.status_code==200
    version=policy.json()['policy']['version']
    change={'reason':'Synthetic policy lifecycle','expected_version':version,'name':'Updated test policy','description':'Synthetic','status':'RETIRED'}
    result=c.post('/api/governance/console/policies/default-policy',json=change);assert result.status_code==200,result.text
    assert result.json()['policy']['version']==version+1
    assert c.post('/api/governance/console/policies/default-policy',json=change).status_code==409
    assert c.post('/api/governance/console/scopes/'+second['scope_contract_id']+'/revoke',json={'reason':'Finish test','expected_version':2}).status_code==200


def test_real_emergency_version_guard(console_db):
    c,s=console_db
    state=s.repo.get_emergency_state()
    body={'actor_id':'forged','reason':'Synthetic emergency test','metadata':{'expected_version':state['version']}}
    r=c.post('/api/governance/emergency-stop/activate',json=body);assert r.status_code==200,r.text
    assert r.json()['emergency_state']['activated_by']=='console-test-admin'
    assert c.post('/api/governance/emergency-stop/release',json=body).status_code==409
    body['metadata']['expected_version']=r.json()['emergency_state']['version']
    assert c.post('/api/governance/emergency-stop/release',json=body).status_code==200
