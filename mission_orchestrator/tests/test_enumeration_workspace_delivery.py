from copy import deepcopy
from types import SimpleNamespace
import sqlite3
from unittest.mock import patch

import pytest

from execution_subsystem.enumeration_followup_contract import build_intake
from execution_subsystem.enumeration_delivery_repository import EnumerationDeliveryRepository
from execution_subsystem.wpt_intake_contract import normalize_wpt_intake
from mission_orchestrator.mission_enumeration_wpt_delivery import deliver
from pentest_subsystem.enumeration_workspace import workspace
from tests.test_mission_cti_enumeration_delivery import FakeMission, SCOPE_SRC


@pytest.fixture
def run():
    target = {'target_type': 'URL', 'target_value': 'http://127.0.0.1/app/'}
    return {'enumeration_run_id': 'enumrun-one', 'recon_run_id': 'reconrun-one',
            'request_sha256': 'a' * 64, 'mission_id': 'mission-gmo-one',
            'orchestration_id': 'paorch-one', 'run_status': 'COMPLETED', 'completed_at': '2026-11-10T01:00:00Z',
            'request': {'boundary': {'task_id': 'ptask-one'},
                'metadata': {'cti_intake_id': 'wptreq-source', 'source_result_sha256': 'b' * 64},
                'observations': [{'target': target, 'kind': 'VERSION',
                    'source': {'source_kind': 'CTI_ENRICHMENT', 'source_id': 'wptreq-source'},
                    'attributes': {'product': 'PHP', 'version': '8.0.30', 'cpe_candidates': []}}]}}


class Pentest:
    def __init__(self, run): self.run = run
    def list_enumeration_runs(self, **_): return [self.run]


class WPT:
    def __init__(self, error=None): self.calls = []; self.error = error
    def submit(self, request):
        self.calls.append(request)
        if self.error: raise self.error
        return {'record': {'authority_snapshot': {'execution_status': 'REGISTERED_NOT_EXECUTABLE'}},
                'stage6_admission': {'status': 'BLOCKED', 'reason_code': 'WPT_CAPABILITY_OR_TASK_NOT_EXECUTABLE'}}


def context():
    return {'cti_context': {'lineage': {'intake_id': 'wptreq-source'},
            'enrichment': {'source_result_sha256': 'b' * 64}}}


def test_followup_is_stable_and_bound_to_cti_analysis(run):
    request = build_intake(run)
    assert normalize_wpt_intake(request) == request
    assert request == build_intake(deepcopy(run))
    assert request['intake_id'] != request['enumeration_context']['source_cti_intake_id']
    assert request['enumeration_context']['technologies'] == [{'name': 'PHP', 'version': '8.0.30'}]
    changed = deepcopy(run); changed['request_sha256'] = 'c' * 64
    assert build_intake(changed)['intake_id'] != request['intake_id']


@pytest.mark.parametrize('change', ['source', 'target', 'schema', 'profile'])
def test_followup_rejects_malformed_or_cross_evidence_context(run, change):
    if change == 'source':
        run['request']['observations'][0]['source']['source_id'] = 'wptreq-other'
        with pytest.raises(ValueError): build_intake(run)
    elif change == 'target':
        run['request']['observations'][0]['target']['target_type'] = 'HOST'
        with pytest.raises(ValueError): build_intake(run)
    else:
        request = build_intake(run)
        request['profile' if change == 'profile' else 'unknown'] = 'fingerprinting'
        with pytest.raises(ValueError): normalize_wpt_intake(request)


def test_worker_ack_and_execution_are_distinct_and_replay_is_durable(tmp_path, run):
    repo = EnumerationDeliveryRepository(tmp_path / 'delivery.db'); wpt = WPT(); sends = []
    def send(request):
        sends.append(request)
        return {'status': 'DELIVERED', 'intake_id': request['intake_id']}
    with patch('mission_orchestrator.gss_scope_sync.fetch', return_value=SCOPE_SRC), patch(
        'pentest_subsystem.web_ui.cti_enumeration_context_for_recon_run', return_value=context()):
        first = deliver(FakeMission(), run['mission_id'], pentest=Pentest(run), wpt=wpt, repository=repo, sender=send)
        second = deliver(FakeMission(), run['mission_id'], pentest=Pentest(run), wpt=wpt, repository=repo, sender=send)
    assert first[0]['delivery_status'] == 'DELIVERED'
    assert first[0]['execution_status'] == 'BLOCKED'
    assert first[0]['reason_code'] == 'WPT_ENUMERATION_ADAPTER_UNAVAILABLE'
    assert first[0]['wpt_job_id'] is None
    assert len(repo.list()) == 1 and first == second and sends[0] == sends[1]
    assert EnumerationDeliveryRepository(repo.path).list()[0]['state']['delivery_status'] == 'DELIVERED'


@pytest.mark.parametrize('ack', [{'status': 'DELIVERED', 'intake_id': 'wptreq-wrong'}, {'status': 'PENDING'}])
def test_worker_never_claims_delivery_without_bound_ack(tmp_path, run, ack):
    with patch('mission_orchestrator.gss_scope_sync.fetch', return_value=SCOPE_SRC), patch(
        'pentest_subsystem.web_ui.cti_enumeration_context_for_recon_run', return_value=context()):
        out = deliver(FakeMission(), run['mission_id'], pentest=Pentest(run), wpt=WPT(),
                      repository=EnumerationDeliveryRepository(tmp_path / 'out.db'), sender=lambda _: ack)
    assert out[0]['delivery_status'] == 'NOT_SENT'


def test_worker_preserves_ack_when_authority_later_expires(tmp_path, run):
    repo = EnumerationDeliveryRepository(tmp_path / 'delivery.db')
    repo.save(build_intake(run), {'delivery_status':'DELIVERED','execution_status':'BLOCKED',
                                 'reason_code':'WPT_ENUMERATION_ADAPTER_UNAVAILABLE'})
    with patch('mission_orchestrator.gss_scope_sync.fetch', return_value=SCOPE_SRC), patch(
        'pentest_subsystem.web_ui.cti_enumeration_context_for_recon_run', return_value=context()):
        out = deliver(FakeMission(),run['mission_id'],pentest=Pentest(run),wpt=WPT(ValueError('AUTHORITY_EXPIRED')),
                      repository=repo,sender=lambda _: pytest.fail('expired authority must not resend'))
    assert out[0]['delivery_status'] == 'DELIVERED'
    assert out[0]['execution_status'] == 'BLOCKED'
    assert out[0]['reason_code'] == 'AUTHORITY_EXPIRED'


def test_budget_conflict_has_an_operational_reason_and_does_not_send(tmp_path,run):
    from execution_subsystem.execution_contract import ExecutionRequestConflict
    with patch('mission_orchestrator.gss_scope_sync.fetch',return_value=SCOPE_SRC),patch(
        'pentest_subsystem.web_ui.cti_enumeration_context_for_recon_run',return_value=context()):
        out=deliver(FakeMission(),run['mission_id'],pentest=Pentest(run),
            wpt=WPT(ExecutionRequestConflict('Mission/task WPT request budget is already reserved by prior intakes')),
            repository=EnumerationDeliveryRepository(tmp_path/'budget.db'),
            sender=lambda _:pytest.fail('must not deliver a budget-rejected request'))
    assert out[0]['reason_code']=='WPT_REQUEST_BUDGET_RESERVED'
    assert out[0]['delivery_status']=='NOT_SENT'


def test_projection_accepts_only_matching_sealed_followup_results(run,tmp_path):
    repo=EnumerationDeliveryRepository(tmp_path/'delivery.db')
    request=build_intake(run)
    repo.save(request,{'delivery_status':'DELIVERED','execution_status':'AWAITING_RESULT'})
    record={'intake_id':request['intake_id'],'mission_id':request['mission_id'],'task_id':request['task_id'],
            'target':request['target'],'profile_id':'wpt.bounded-enumeration.v1',
            'status':'VALIDATED_AND_STORED','evidence':{'capture_status':'SEALED'},'result':{}}
    result=lambda _: {'record':record}
    assert workspace(Pentest(run),deliveries=repo,results=result)['items'][0]['progress']['execution_status']=='RESULT_RECEIVED'
    record['mission_id']='mission-gmo-other'
    assert workspace(Pentest(run),deliveries=repo,results=result)['items'][0]['result'] is None


def test_changed_scope_never_sends_to_wpt(tmp_path, run):
    wpt = WPT(); sends = []
    with patch('mission_orchestrator.gss_scope_sync.fetch', return_value={'changed': True}):
        out = deliver(FakeMission(), run['mission_id'], pentest=Pentest(run), wpt=wpt,
            repository=EnumerationDeliveryRepository(tmp_path / 'out.db'), sender=lambda r: sends.append(r))
    assert out[0]['reason_code'] == 'GSS_SCOPE_CHANGED'
    assert not wpt.calls and not sends


def test_projection_is_read_only_and_does_not_infer_wpt_delivery(run, tmp_path):
    repo = EnumerationDeliveryRepository(tmp_path / 'absent.db')
    result = workspace(Pentest(run), deliveries=repo, results=lambda _: None)
    assert not repo.path.exists()
    row = result['items'][0]
    assert row['cti_intake_id'] == 'wptreq-source'
    assert row['analysis_status'] == 'COMPLETED'
    assert row['progress']['delivery_status'] == 'NOT_SENT'
    assert row['progress']['execution_status'] == 'NOT_CREATED'
    assert row['followup_intake_id'] is None
    request = build_intake(run)
    repo.save(request, {'delivery_status': 'DELIVERED', 'execution_status': 'BLOCKED',
                       'reason_code': 'WPT_ENUMERATION_ADAPTER_UNAVAILABLE'})
    row = workspace(Pentest(run), deliveries=repo, results=lambda _: None)['items'][0]
    assert row['followup_intake_id'] == request['intake_id']
    assert row['progress']['execution_status'] == 'BLOCKED'


def test_outbox_rejects_conflicting_identity(tmp_path, run):
    repo = EnumerationDeliveryRepository(tmp_path / 'delivery.db')
    request = build_intake(run); state = {'delivery_status': 'NOT_SENT'}
    repo.save(request, state); repo.save(request, state)
    with sqlite3.connect(repo.path) as conn:
        assert conn.execute('SELECT count(*) FROM enumeration_delivery_events').fetchone()[0] == 1
    bad = deepcopy(request); bad['mission_id'] = 'mission-gmo-other'
    with pytest.raises(ValueError, match='conflicting'): repo.save(bad, state)


def test_authority_rejects_cross_mission_analysis_before_resolving_mission(run, tmp_path):
    from execution_subsystem.wpt_intake_source import WPTIntakeAuthoritySource
    from execution_subsystem.execution_contract import ExecutionRequestIntegrityError
    request = build_intake(run); request['mission_id'] = 'mission-gmo-other'
    authority = WPTIntakeAuthoritySource(pentest_source=SimpleNamespace(sqlite_path=tmp_path / 'pentest.db'),
                                         mission_source=SimpleNamespace())
    with patch('pentest_subsystem.enumeration.EnumerationAgentRepository.get_enumeration_run', return_value=run):
        with pytest.raises(ExecutionRequestIntegrityError, match='authoritative analysis'):
            authority.resolve(request)


def test_successful_runtime_publishes_authorization_before_sealing(tmp_path, run):
    # A fast attempt that races AUTHORIZED->SUCCEEDED between sweeps must still
    # deliver authorization provenance to the WPT job, or the sealed result is
    # refused and the job is stranded at AWAITING_STAGE6.
    repo = EnumerationDeliveryRepository(tmp_path / 'delivery.db'); published = []

    class ExecWPT:
        def submit(self, request):
            return {'record': {'authority_snapshot': {'execution_status': 'EXECUTABLE'}},
                    'stage6_admission': {'status': 'REQUEST_CREATED', 'execution_id': 'exec-abc',
                                         'envelope_sha256': 'e' * 64, 'reason_code': None}}
        def _publish_stage6_job(self, request, admission):
            return {'status': 'DELIVERED', 'job_id': 'wpt-xyz'}

    runtime = {'status': 'SUCCEEDED', 'authorization_id': 'eauth-1', 'execution_id': 'exec-abc',
               'attempt_id': 'xattempt-1', 'runtime_attempt_number': 1, 'runtime_attempt_id': 'xattempt-1',
               'reason_code': 'ADAPTER_PRIMITIVE_COMPLETED'}

    def job_status(req, adm, status):
        published.append((status, adm.get('authorization_id'))); return {'status': 'DELIVERED'}

    with patch('mission_orchestrator.gss_scope_sync.fetch', return_value=SCOPE_SRC), \
         patch('pentest_subsystem.web_ui.cti_enumeration_context_for_recon_run', return_value=context()), \
         patch('mission_orchestrator.mission_wpt_preparation._start_stage6_runtime', return_value=runtime), \
         patch('execution_subsystem.wpt_job_callback.publish_job_status', side_effect=job_status), \
         patch('mission_orchestrator.mission_wpt_preparation._reconcile_stage6_result',
               return_value={'status': 'DELIVERED'}):
        out = deliver(FakeMission(), run['mission_id'], pentest=Pentest(run), wpt=ExecWPT(),
                      repository=repo, sender=lambda r: {'status': 'DELIVERED', 'intake_id': r['intake_id']})
    assert ('RUNNING', 'eauth-1') in published
    assert out[0]['execution_status'] == 'RESULT_RECEIVED'
    assert out[0]['wpt_job_id'] == 'wpt-xyz'


def test_recovers_stored_result_by_delivering_authorization_first(tmp_path, run):
    # A job stranded with a stored-but-undeliverable result (its sealed result
    # was stored, but the job never received authorization provenance) recovers
    # by replaying the authorized callback, then re-sealing. It never re-scans.
    repo = EnumerationDeliveryRepository(tmp_path / 'delivery.db')
    request = build_intake(run)
    repo.save(request, {'delivery_status': 'DELIVERED', 'execution_status': 'BLOCKED',
                        'reason_code': 'RuntimeError', 'wpt_job_id': 'wpt-xyz',
                        'execution_id': 'exec-abc', 'attempt_id': 'xattempt-1'})
    published = []; flag = {'authorized': False}

    class StoredWPT:
        repository = SimpleNamespace(get_result=lambda intake_id: {'record': {'execution_id': 'exec-abc'}})

    def job_status(req, adm, status):
        flag['authorized'] = True; published.append((status, adm.get('authorization_id')))
        return {'status': 'DELIVERED'}

    def seal(req, record):
        if not flag['authorized']:
            raise RuntimeError('WPT 409: job has no authorization_id')
        return {'status': 'DELIVERED', 'job_id': 'wpt-xyz'}

    provenance = {'execution_id': 'exec-abc', 'authorization_id': 'eauth-1',
                  'runtime_attempt_number': 1, 'runtime_attempt_id': 'xattempt-1',
                  'reason_code': 'STAGE6_AUTHORIZATION_PROVENANCE'}

    with patch('execution_subsystem.wpt_job_callback.publish_stage6_result', side_effect=seal), \
         patch('execution_subsystem.wpt_job_callback.publish_job_status', side_effect=job_status), \
         patch('mission_orchestrator.mission_wpt_preparation._runtime_authorization_provenance',
               return_value=provenance):
        out = deliver(FakeMission(), run['mission_id'], pentest=Pentest(run), wpt=StoredWPT(),
                      repository=repo, sender=lambda r: pytest.fail('recovery must not resend intake'))
    assert published == [('RUNNING', 'eauth-1')]
    assert out[0]['execution_status'] == 'RESULT_RECEIVED'


def test_empty_cti_does_not_generate_target_work(run, tmp_path):
    run['request']['observations'] = []
    row = workspace(Pentest(run), deliveries=EnumerationDeliveryRepository(tmp_path / 'none.db'), results=lambda _: None)['items'][0]
    assert row['progress']['execution_status'] == 'NOT_REQUIRED'


def test_http_workspace_has_no_required_ids_and_no_form(tmp_path, run):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import urlopen
    import json
    from pentest_subsystem.api_service import PentestSubsystemStage510Handler
    handler = type('WorkspaceHandler', (PentestSubsystemStage510Handler,), {'service': Pentest(run)})
    with patch('pentest_subsystem.enumeration_workspace.EnumerationDeliveryRepository',
               return_value=EnumerationDeliveryRepository(tmp_path / 'missing.db')), patch(
                   'pentest_subsystem.enumeration_workspace.read_result', return_value=None):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urlopen(base + '/api/pentest/ui/enumeration/workspace') as response:
                assert json.load(response)['items'][0]['cti_intake_id'] == 'wptreq-source'
            with urlopen(base + '/pentest/enumeration/') as response:
                html = response.read().decode()
                assert '<input' not in html and '<textarea' not in html and 'id="submit"' not in html
            with urlopen(base + '/pentest/enumeration.css') as response:
                assert response.status == 200
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)
