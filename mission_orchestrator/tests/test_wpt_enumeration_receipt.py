"""Enumeration result acceptance, callback binding and recovery without re-scanning."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock, patch

import pytest
from tests.test_enumeration_workspace_delivery import run
from tests.test_mission_cti_enumeration_delivery import FakeMission
from execution_subsystem.enumeration_followup_contract import build_intake
from execution_subsystem.enumeration_delivery_repository import EnumerationDeliveryRepository
from execution_subsystem import wpt_job_callback as callback
from mission_orchestrator.mission_enumeration_wpt_delivery import deliver
from pentest_subsystem.enumeration import EnumerationAgentService, EnumerationAgentIntegrityError


def source_for(run):
    intake = build_intake(run)
    record = {k: deepcopy(intake[k]) for k in ('intake_id', 'mission_id', 'task_id', 'target')}
    record.update(status='VALIDATED_AND_STORED', profile_id='wpt.bounded-enumeration.v1',
        execution_id='exec-receipt', result={'status': 'SUCCEEDED', 'observation': {}},
        evidence={'capture_status': 'SEALED', 'manifest_sha256': 'c'*64},
        integrity={'canonical_sha256': 'd'*64})
    source = SimpleNamespace(get=lambda _: {'record': {'intake': intake}},
                             get_result=lambda _: {'record': record})
    return intake, record, source


def receiver(run):
    return EnumerationAgentService(SimpleNamespace(get_enumeration_run=lambda _: deepcopy(run)))


@pytest.mark.parametrize('change', ['mission_id', 'target', 'profile_id', 'status', 'evidence', 'context'])
def test_agent_rejects_unbound_or_unsealed_result(run, change):
    intake, record, source = source_for(run)
    if change == 'evidence': record['evidence']['capture_status'] = 'PARTIAL'
    elif change == 'context': intake['enumeration_context']['enumeration_request_sha256'] = 'f'*64
    else: record[change] = 'wrong'
    with pytest.raises((EnumerationAgentIntegrityError, ValueError)):
        receiver(run).accept_wpt_result(intake['intake_id'], source_repository=source)


def test_agent_acceptance_is_stable_and_preserves_analysis(run):
    intake, record, source = source_for(run)
    before = deepcopy(run)
    service = receiver(run)
    ack = service.accept_wpt_result(intake['intake_id'], source_repository=source)
    assert ack == service.accept_wpt_result(intake['intake_id'], source_repository=source)
    assert ack['accepted'] is True and ack['source_result_sha256'] == 'd'*64
    assert run == before


def test_old_completed_job_retries_lost_receipt_without_new_scan(tmp_path, run):
    request, record, source = source_for(run)
    repo = EnumerationDeliveryRepository(tmp_path/'outbox.db')
    repo.save(request, {'delivery_status':'DELIVERED', 'execution_status':'RESULT_RECEIVED'})
    service = receiver(run)
    service.list_enumeration_runs = lambda **_: [run]
    wpt = SimpleNamespace(repository=source, submit=Mock(side_effect=AssertionError('must not rescan')))
    ack = service.accept_wpt_result(request['intake_id'], source_repository=source)
    calls = []
    def receipt(*args):
        assert repo.list()[0]['state']['enum_acknowledgement']['accepted'] is True
        calls.append(args)
        if len(calls) == 1: raise RuntimeError('lost response after commit')
        return {'status':'DELIVERED','delivery_id':ack['delivery_id']}
    with patch.object(callback, 'publish_stage6_result', return_value={'status':'DELIVERED'}), \
         patch.object(callback, 'publish_enumeration_receipt', side_effect=receipt) as publish:
        first = deliver(FakeMission(), run['mission_id'], pentest=service, wpt=wpt, repository=repo)
        assert first[0]['enum_receipt_status'] == 'PENDING'
        assert repo.list()[0]['state']['enum_acknowledgement'] == ack
        second = deliver(FakeMission(), run['mission_id'], pentest=service, wpt=wpt, repository=repo)
        assert second[0]['enum_receipt_status'] == 'DELIVERED'
        deliver(FakeMission(), run['mission_id'], pentest=service, wpt=wpt, repository=repo)
        assert publish.call_count == 2
    wpt.submit.assert_not_called()


@pytest.mark.parametrize('result_available', [True, False])
def test_completed_receipt_recovery_never_readmits_when_callback_or_store_unavailable(tmp_path, run, result_available):
    request, record, source = source_for(run)
    if not result_available: source.get_result = lambda _: None
    repo = EnumerationDeliveryRepository(tmp_path/'outbox.db')
    repo.save(request, {'delivery_status':'DELIVERED','execution_status':'RESULT_RECEIVED'})
    service = receiver(run); service.list_enumeration_runs = lambda **_: [run]
    wpt = SimpleNamespace(repository=source,submit=Mock(side_effect=AssertionError('must not readmit')))
    with patch.object(callback,'publish_stage6_result',side_effect=RuntimeError('offline')), \
         patch('mission_orchestrator.mission_wpt_preparation._runtime_authorization_provenance',return_value=None):
        out = deliver(FakeMission(),run['mission_id'],pentest=service,wpt=wpt,repository=repo)
    assert out[0]['execution_status']=='RESULT_RECEIVED'
    assert out[0]['enum_receipt_status']=='PENDING'
    wpt.submit.assert_not_called()


def test_receipt_updates_real_wpt_job_and_replays_safely(tmp_path, monkeypatch, run):
    path = Path(__file__).resolve().parents[2]/'WebTechnologyProfiler'/'app.py'
    spec = importlib.util.spec_from_file_location('enum_receipt_app', path)
    app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)
    app.DB_PATH = tmp_path/'wpt.db'; app.CLIENT_TOKEN = 'x'*40
    intake, record, source = source_for(run)
    job = callback.job_id_for_intake(intake['intake_id'])
    with app.connection() as c:
        c.execute('INSERT INTO governed_intakes(intake_id,idempotency_key,mission_id,task_id,target_type,target_url,profile,received_at,enumeration_context_json) VALUES(?,?,?,?,?,?,?,?,?)',
            (intake['intake_id'],intake['idempotency_key'],intake['mission_id'],intake['task_id'],'URL',intake['target']['target_value'],'enumeration','now',json.dumps(intake['enumeration_context'])))
        c.execute('INSERT INTO jobs(job_id,created_at,updated_at,mission_id,task_id,target,requested_by,mode,status,intake_id,execution_id,result_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (job,'now','now',intake['mission_id'],intake['task_id'],intake['target']['target_value'],'test','enumeration','COMPLETED',intake['intake_id'],record['execution_id'],json.dumps({'evidence':record['evidence']})))
    server = ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
    thread = Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setenv('APTS_WPT_INBOX_URL',f'http://127.0.0.1:{server.server_port}')
    monkeypatch.setenv('APTS_WPT_INBOX_TOKEN',app.CLIENT_TOKEN)
    ack = receiver(run).accept_wpt_result(intake['intake_id'],source_repository=source)
    try:
        for _ in range(2): assert callback.publish_enumeration_receipt(intake,record,ack)['status']=='DELIVERED'
        with app.connection() as c:
            row=c.execute('SELECT * FROM jobs').fetchone()
            assert row['enum_status']=='DELIVERED' and row['enum_delivery_id']==ack['delivery_id']
            assert row['recon_status']=='NOT_SENT'
        bad=deepcopy(ack);bad['source_result_sha256']='f'*64
        with pytest.raises(ValueError): callback.publish_enumeration_receipt(intake,record,bad)
        bad=deepcopy(record);bad['execution_id']='exec-wrong'
        bad_ack={**ack,'execution_id':'exec-wrong'}
        with pytest.raises(RuntimeError): callback.publish_enumeration_receipt(intake,bad,bad_ack)
        wrong_intake=deepcopy(intake)
        wrong_intake['enumeration_context']['enumeration_run_id']='enumrun-wrong'
        bad_ack={**ack,'enumeration_run_id':'enumrun-wrong'}
        with pytest.raises(RuntimeError): callback.publish_enumeration_receipt(wrong_intake,record,bad_ack)
    finally:
        server.shutdown();server.server_close();thread.join(3)
