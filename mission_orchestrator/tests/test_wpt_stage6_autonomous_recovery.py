"""Real SQLite parsing and autonomous verified-result recovery regressions."""
from copy import deepcopy
import sqlite3
from unittest.mock import Mock
import pytest
from execution_subsystem.execution_contract import (WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
    ExecutionRequestIntegrityError, ExecutionSourceRejected, ExecutionSourceNotFound)
from execution_subsystem.proposal_source import PentestProposalSource
from execution_subsystem.wpt_intake_repository import WPTIntakeRepository, _seal
from execution_subsystem.wpt_intake_source import WPTIntakeAuthoritySource
from mission_orchestrator.mission_wpt_preparation import _reconcile_stage6_result

@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / 'intakes.db'
    monkeypatch.setenv('APTS_WPT_INTAKE_DB', str(path))
    intake = dict(schema_version='apts-wpt-governed-intake-v1', intake_id='wptreq-regression',
        idempotency_key='idem-regression', mission_id='mission-gmo-regression',
        task_id='ptask-regression', profile='fingerprinting',
        target={'target_type':'URL','target_value':'http://localhost:3000/'})
    record = _seal({'intake':intake, 'authority_snapshot':{'mission_id':intake['mission_id'],'task_id':intake['task_id'],'mission_network_request_budget':20,'limits':{'max_requests':1}}})
    WPTIntakeRepository(path).append(record)
    authority = dict(execution_status='EXECUTABLE', task_lifecycle_state='RUNNING',
        orchestration_status='ACTIVE', pentest_id='pentest-regression',
        pentest_task_id='pentest-task-regression', orchestration_id='paorch-regression',
        authorization_policy_reference={'policy_decision_id':'gdec-regression',
            'policy_decision_hash':'a'*64,'policy_version':1},
        action={'action_class':'TARGET_RECON','capability_id':'web_technology_fingerprinting',
            'technique':'WEB_TECHNOLOGY_FINGERPRINT'},
        current_task={'scope':{},'constraints':{}}, current_boundary={'roe':{}},
        task_artifact_sha256='b'*64,task_binding_sha256='c'*64,
        orchestration_graph_sha256='d'*64,mission_scope_sha256='e'*64)
    monkeypatch.setattr(WPTIntakeAuthoritySource,'resolve',lambda self,value:deepcopy(authority))
    payload = dict(schema_version=WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
        source_type='WPT_GOVERNED_INTAKE',request_id='ereq-regression',
        idempotency_key=intake['idempotency_key'],wpt_intake_id=intake['intake_id'],
        wpt_intake_sha256=record['integrity']['canonical_sha256'])
    return PentestProposalSource(tmp_path/'pentest.db'),payload,path,authority

def test_real_sqlite_build_and_replay(source):
    builder,payload,_,_=source
    first=builder._build_wpt(payload)
    assert first==builder._build_wpt(payload)
    assert first['execution_request']['parameters']['source_wpt_intake_id']==payload['wpt_intake_id']

def test_tampered_intake_rejected(source):
    builder,payload,path,_=source
    with sqlite3.connect(path) as db:
        db.execute('UPDATE wpt_governed_intakes SET record_sha256=?',('f'*64,))
    with pytest.raises(ExecutionRequestIntegrityError): builder._build_wpt(payload)

def test_stopped_task_rejected(source):
    builder,payload,_,authority=source
    authority['task_lifecycle_state']='STOPPED'
    with pytest.raises(ExecutionSourceRejected): builder._build_wpt(payload)

def test_missing_intake_rejected(source):
    builder,payload,_,_=source
    payload['wpt_intake_id']='wptreq-missing'
    with pytest.raises(ExecutionSourceNotFound): builder._build_wpt(payload)

@pytest.mark.parametrize('state',['RUNNING','FAILED','DENIED','PENDING'])
def test_non_success_never_publishes(state):
    wpt=Mock()
    assert _reconcile_stage6_result(wpt,{'intake_id':'wptreq-one'},{'status':state})['status']=='PENDING'
    wpt.submit_stage6_result.assert_not_called()

def test_success_retries_verified_reference():
    wpt=Mock()
    wpt.submit_stage6_result.side_effect=[{'wpt_job_delivery':{'status':'PENDING'}},
        {'wpt_job_delivery':{'status':'DELIVERED'}}]
    intake={'intake_id':'wptreq-one'}
    runtime={'status':'SUCCEEDED','execution_id':'exec-one','attempt_id':'xattempt-one'}
    assert _reconcile_stage6_result(wpt,intake,runtime)['status']=='PENDING'
    assert _reconcile_stage6_result(wpt,intake,runtime)['status']=='DELIVERED'
    assert wpt.submit_stage6_result.call_args_list[0]==wpt.submit_stage6_result.call_args_list[1]

def test_bad_evidence_stays_pending():
    wpt=Mock()
    wpt.submit_stage6_result.side_effect=ExecutionRequestIntegrityError('bad seal')
    assert _reconcile_stage6_result(wpt,{'intake_id':'wptreq-one'},
        {'status':'SUCCEEDED','execution_id':'exec-one','attempt_id':'xattempt-one'})=={
        'status':'PENDING','reason_code':'ExecutionRequestIntegrityError'}

def test_launcher_uses_evidence_runtime():
    from run import execution_runtime
    from execution_subsystem.evidence_api import serve
    assert execution_runtime.serve is serve
    assert execution_runtime.ExecutionEvidenceService.__name__=='ExecutionEvidenceService'
