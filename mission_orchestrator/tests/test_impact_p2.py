from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from pentest_subsystem.impact_workspace import assess, workspace
from pentest_subsystem.impact_evidence import normalize_business_context
from pentest_subsystem.impact_store import (
    save_context, latest_context, persist_assessment, outbox_status, assessment_ref, execution_ref,
)
from pentest_subsystem.impact_followup import publish, dispatch, after_execution
from pentest_subsystem.cross_agent_feedback import CrossAgentFeedbackService
from pentest_subsystem.task_repository import PentestTaskRepositoryError
from pentest_subsystem.exploitation_execution import EXECUTION_RUN_HASH_DOMAIN, EXECUTION_PATH_RESULT_HASH_DOMAIN
from pentest_subsystem.vulnerability_hypothesis import _with_integrity
from tests.test_impact_workspace import execution_with_signal
from tests.test_stage5_8_cross_agent_feedback_shared_state_replanning import _pipeline


def seal(record, domain=EXECUTION_RUN_HASH_DOMAIN):
    return _with_integrity({k: v for k, v in record.items() if k != 'integrity'}, domain=domain)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    from pentest_subsystem import attack_path_workspace
    repo, _, task, oid, _ = _pipeline(tmp_path, 'impact-p2', complete=False)
    service = CrossAgentFeedbackService(repo)
    record = execution_with_signal()
    record.update(mission_id=task['mission_id'], pentest_task_id=task['pentest_task_id'], orchestration_id=oid)
    record['path_results'][0]['expected_evidence_evaluation'][0].update(target='http://localhost/', hypothesis_id='h1', note='endpoint responded')
    record['path_results'][0]['probes'] = [{'url': 'http://localhost/', 'method': 'GET', 'status_code': 200, 'error': None}]
    record['path_results'] = [seal(record['path_results'][0], EXECUTION_PATH_RESULT_HASH_DOMAIN)]
    record = seal(record)
    plans = [{'snapshot_sha256': 'a'*64, 'mission_id': task['mission_id'], 'pentest_task_id': task['pentest_task_id']}]
    monkeypatch.setattr(attack_path_workspace, 'history', lambda *args: plans)
    with repo._connect() as conn:
        conn.execute('CREATE TABLE pentest_exploitation_execution_runs '
                     '(record_json TEXT, created_at TEXT, execution_run_id TEXT)')
        conn.execute('INSERT INTO pentest_exploitation_execution_runs VALUES (?,?,?)',
                     (json.dumps(record), record['completed_at'], record['execution_run_id']))
    return repo, service, task, record, plans


def request_for(service, record):
    context = workspace(service, execution_run_id=record['execution_run_id'])['contexts'][0]
    assert context['status'] == 'ASSESSED', context
    return {'execution_run_id': record['execution_run_id'],
            'expected_assessment_id': context['assessment']['assessment_id']}


def test_claim_has_provenance_timestamp_probe_scope_and_limitations(environment):
    _, service, _, record, _ = environment
    a = workspace(service)['contexts'][0]['assessment']
    claim = a['claims'][0]
    assert claim['status'] == 'OBSERVED'
    assert claim['target'] == 'http://localhost/'
    observation = claim['observations'][0]
    assert observation['execution_sha256'] == record['integrity']['canonical_sha256']
    assert observation['path_sha256'] == record['path_results'][0]['integrity']['canonical_sha256']
    assert observation['observed_at'] == record['completed_at']
    assert observation['record_pointer'] == '/path_results/0/expected_evidence_evaluation/0'
    assert observation['probes'][0]['status_code'] == 200
    assert claim['limitations']


def test_current_conflict_escalates_without_claiming_sufficiency():
    record = execution_with_signal()
    other = deepcopy(record['path_results'][0])
    other['attack_path_id'] = 'path-2'
    other['expected_evidence_evaluation'][0]['verdict'] = 'NOT_OBSERVED'
    record['path_results'].append(seal(other, EXECUTION_PATH_RESULT_HASH_DOMAIN))
    a = assess(seal(record))
    assert a['claims'][0]['current_conflict']
    assert a['claims'][0]['status'] == 'CONFLICTING'
    assert a['decision'] == 'ESCALATE'
    assert all(p['reason'] == 'CONFLICTING_EVIDENCE' and not p['evidence_sufficient_for_technical_signals'] for p in a['analyses'])


def test_historical_verdict_change_is_explicit_and_not_current_conflict():
    old = execution_with_signal('NOT_OBSERVED', 'REFUTED', run_id='xplexec-old')
    a = assess(execution_with_signal(), prior_records=[old])
    claim = a['claims'][0]
    assert claim['historical_verdict_changed'] and not claim['current_conflict']
    assert claim['historical_observations'][0]['verdict'] == 'NOT_OBSERVED'
    assert a['decision'] == 'STOP'


@pytest.mark.parametrize('stale,blocked', [(True, False), (False, True)])
def test_unusable_evidence_cannot_raise_business_review_priority(stale, blocked):
    r = execution_with_signal()
    if blocked:
        r['scope_decision']['status'] = 'BLOCKED_OUT_OF_LOCALHOST_SCOPE'
        r = seal(r)
    a = assess(r, stale=stale, business_context={'data_sensitivity': 'CRITICAL'})
    assert a['claims'][0]['status'] == 'HISTORICAL_OR_BLOCKED'
    assert a['business_impact']['review_priority'] == 'VALIDATION_REQUIRED'
    assert not a['business_impact']['actual_business_impact_confirmed']


def test_context_dependency_is_potential_not_observed_loss():
    context = {'business_criticality': 'MEDIUM', 'service_name': 'Academic portal',
               'dependencies': [{'service_name': 'Enrollment', 'criticality': 'CRITICAL'}]}
    impact = assess(execution_with_signal(), business_context=context)['business_impact']
    assert impact['contextual_exposure_level'] == 'CRITICAL'
    assert impact['review_priority'] == 'CRITICAL'
    assert not impact['dependency_exposure'][0]['observed_impact']
    assert not impact['actual_business_impact_confirmed']
    assert all(x['status'].startswith('CONDITIONAL') for x in impact['potential_consequences'])


@pytest.mark.parametrize('context', [[], {'impact_confirmed': True}, {'data_sensitivity': 'bad'},
    {'dependencies': [{'service_name': '', 'criticality': 'HIGH'}]},
    {'dependencies': [{'service_name': 'x', 'criticality': 'HIGH'}]*2},
    {'service_name': 'x'*201}, {'dependencies': ['x']}])
def test_invalid_context_is_rejected(context):
    with pytest.raises(ValueError):
        normalize_business_context(context)


def test_context_versions_are_idempotent_and_optimistically_locked(environment):
    repo, service, task, record, _ = environment
    payload = {'pentest_task_id': task['pentest_task_id'], 'expected_context_id': None,
               'business_context': {'data_sensitivity': 'HIGH'}}
    first = save_context(service, payload)
    assert first['created'] and first['context']['revision'] == 1
    assert not save_context(service, payload)['created']
    payload['business_context']['data_sensitivity'] = 'CRITICAL'
    with pytest.raises(ValueError, match='changed'):
        save_context(service, payload)
    payload['expected_context_id'] = first['context']['context_id']
    second = save_context(service, payload)['context']
    assert second['revision'] == 2 and second['previous_sha256'] == first['context']['integrity']['canonical_sha256']
    assert latest_context(repo, task['pentest_task_id']) == second
    current = workspace(service, execution_run_id=record['execution_run_id'])['contexts'][0]
    assert current['assessment']['business_impact']['context_source']['revision'] == 2


def test_context_chain_tampering_is_detected(environment):
    repo, service, task, _, _ = environment
    record = save_context(service, {'pentest_task_id': task['pentest_task_id'], 'expected_context_id': None, 'business_context': {}})['context']
    record['business_context']['data_sensitivity'] = 'CRITICAL'
    with repo._connect() as conn:
        conn.execute('UPDATE pentest_impact_contexts SET record_json=?', (json.dumps(record),))
    with pytest.raises(ValueError, match='integrity'):
        latest_context(repo, task['pentest_task_id'])


def test_workspace_get_does_not_write_impact_tables(environment):
    repo, service, _, _, _ = environment
    workspace(service)
    with repo._connect() as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='pentest_impact_outbox'").fetchone()


def test_publish_is_durable_idempotent_and_bound_to_shared_evidence(environment):
    repo, service, _, record, _ = environment
    original_graph = deepcopy(repo.get_orchestration(record['orchestration_id'])['task_graph'])
    payload = request_for(service, record)
    first = publish(service, payload)
    assert first['followup']['status'] == 'PROCESSED', first
    assert first['followup']['result']['decision_class'] == 'NO_CHANGE'
    assert publish(CrossAgentFeedbackService(repo), payload)['followup'] == first['followup']
    with repo._connect() as conn:
        for table in ('pentest_impact_outbox', 'pentest_impact_assessments', 'pentest_cross_agent_feedback_records', 'pentest_local_replan_decisions'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 1
    state = service.get_latest_shared_state(record['orchestration_id'])['shared_state']
    assessment = state['post_execution_impact'][0]
    assert assessment_ref(assessment) in state['evidence_index']
    assert execution_ref(assessment) in state['evidence_index']
    assert not state['validated_facts']  # claims remain separate from Stage 5 facts
    assert repo.get_orchestration(record['orchestration_id'])['task_graph'] == original_graph


def replace_execution(repo, record):
    with repo._connect() as conn:
        conn.execute('UPDATE pentest_exploitation_execution_runs SET record_json=?', (json.dumps(seal(record)),))


@pytest.mark.parametrize('blocked,decision_class', [(False, 'DEFER_TO_STAGE6'), (True, 'ESCALATE_GOVERNANCE')])
def test_replan_and_escalation_use_governed_nonexecuting_coordination(environment, blocked, decision_class):
    repo, service, _, record, _ = environment
    record['path_results'][0]['outcome'] = 'INCONCLUSIVE'
    record['path_results'][0]['expected_evidence_evaluation'][0]['verdict'] = 'INCONCLUSIVE'
    record['path_results'] = [seal(record['path_results'][0], EXECUTION_PATH_RESULT_HASH_DOMAIN)]
    if blocked:
        record['scope_decision']['status'] = 'BLOCKED_OUT_OF_LOCALHOST_SCOPE'
    replace_execution(repo, record)
    result = publish(service, request_for(service, record))['followup']
    assert result['status'] == 'PROCESSED', result
    receipt = result['result']
    assert receipt['decision_class'] == decision_class
    assert receipt['governance_review_required'] == blocked
    assert not receipt['execution_started'] and not receipt['specialist_replay_started']
    assert not receipt['active_plan_mutated'] and not receipt['mission_completion_authorized']


def test_retry_after_interrupted_delivery_does_not_duplicate_feedback(environment, monkeypatch):
    repo, service, _, record, _ = environment
    payload = request_for(service, record)
    original = service.create_local_replan
    def fail(*args, **kwargs):
        raise PentestTaskRepositoryError('simulated interruption after feedback')
    monkeypatch.setattr(service, 'create_local_replan', fail)
    first = publish(service, payload)['followup']
    assert first['status'] == 'PENDING' and first['attempts'] == 1
    monkeypatch.setattr(service, 'create_local_replan', original)
    retried = publish(service, payload)['followup']
    assert retried['status'] == 'PROCESSED' and retried['attempts'] == 2
    assert len(repo.list_feedback(record['orchestration_id'])) == 1


def test_unavailable_coordinator_queues_event_for_restart_safe_delivery(environment):
    repo, service, _, record, _ = environment
    restricted = SimpleNamespace(repository=repo, get_task=repo.get_task)
    payload = request_for(service, record)
    pending = publish(restricted, payload)['followup']
    assert pending['status'] == 'PENDING'
    assert pending['last_error'] == 'STAGE58_COORDINATION_UNAVAILABLE'
    assert publish(CrossAgentFeedbackService(repo), payload)['followup']['status'] == 'PROCESSED'


def test_old_assessment_is_superseded_when_context_changes(environment):
    repo, service, task, record, _ = environment
    a = workspace(service)['contexts'][0]['assessment']
    event = persist_assessment(repo, a)
    save_context(service, {'pentest_task_id': task['pentest_task_id'], 'expected_context_id': None, 'business_context': {'data_sensitivity': 'HIGH'}})
    assert dispatch(service, event)['status'] == 'SUPERSEDED'
    with pytest.raises(ValueError, match='berubah'):
        publish(service, {'execution_run_id': record['execution_run_id'], 'expected_assessment_id': a['assessment_id']})
    # Revisions can be published in the same second; the new assessment must
    # still be the authoritative shared-state source for this execution run.
    published = publish(service, request_for(service, record))
    assert published['followup']['status'] == 'PROCESSED', published
    state = service.get_latest_shared_state(record['orchestration_id'])['shared_state']
    assert state['post_execution_impact'][0]['assessment_id'] == published['assessment_id']


def test_stale_plan_prevents_dispatch(environment):
    repo, service, _, _, plans = environment
    event = persist_assessment(repo, workspace(service)['contexts'][0]['assessment'])
    plans.insert(0, {**plans[0], 'snapshot_sha256': 'b'*64})
    assert dispatch(service, event)['status'] == 'SUPERSEDED'


def test_after_execution_publishes_without_any_new_probe(environment, monkeypatch):
    _, service, _, record, _ = environment
    from pentest_subsystem import exploitation_execution
    monkeypatch.setattr(exploitation_execution, '_probe', lambda *args, **kwargs: pytest.fail('unexpected target I/O'))
    assert after_execution(service, record['execution_run_id'])['followup']['status'] == 'PROCESSED'


def test_receipt_tampering_is_detected(environment):
    repo, service, _, record, _ = environment
    result = publish(service, request_for(service, record))
    receipt = result['followup']['result']
    receipt['decision_class'] = 'APPROVED'
    with repo._connect() as conn:
        conn.execute('UPDATE pentest_impact_outbox SET result_json=?', (json.dumps(receipt),))
    with pytest.raises(ValueError, match='receipt integrity'):
        outbox_status(repo, result['assessment_id'])


def test_publish_rejects_client_supplied_assessment(environment):
    _, service, _, record, _ = environment
    with pytest.raises(ValueError):
        publish(service, {**request_for(service, record), 'assessment': {'decision': 'STOP'}})


@pytest.mark.parametrize('operation', ['context', 'publish'])
def test_ui_post_routes_require_same_origin_and_use_server_assessment(environment, operation):
    from pentest_subsystem.web_ui import PentestWebMixin
    _, service, task, record, _ = environment
    class Handler(PentestWebMixin):
        def _read_json(self):
            return self.payload
        def _send_json(self, status, body):
            self.response = status, body
    handler = Handler()
    handler.service = service
    handler.path = '/api/pentest/ui/post-exploitation-impact/' + operation
    handler.headers = {'Host': 'localhost:8790', 'Origin': 'https://untrusted.example'}
    handler.payload = request_for(service, record) if operation == 'publish' else {
        'pentest_task_id': task['pentest_task_id'], 'business_context': {}, 'expected_context_id': None}
    assert handler.handle_pentest_ui_post()
    assert handler.response[0] == 403
    handler.headers['Origin'] = 'http://localhost:8790'
    assert handler.handle_pentest_ui_post()
    assert handler.response[0] in (200, 201), handler.response
    if operation == 'publish':
        assert handler.response[1]['followup']['status'] == 'PROCESSED'


def test_new_ui_asset_and_controls_are_served():
    from pentest_subsystem.web_ui import ASSETS, WEB_ROOT
    assert ASSETS['/pentest/impact.css'] == ('impact.css', 'text/css')
    html = (WEB_ROOT / 'impact.html').read_text(encoding='utf-8')
    for element_id in ('business-form', 'dependency-rows', 'publish-impact', 'claims', 'business-impact', 'followup'):
        assert f'id="{element_id}"' in html


def test_impact_receipt_cannot_trigger_an_autonomous_planning_execution_loop(tmp_path):
    from pentest_subsystem.attack_path_workspace import create_plan
    repo, _, task, oid, _ = _pipeline(tmp_path, 'impact-loop-guard')
    service = CrossAgentFeedbackService(repo)
    first = create_plan(service, {'orchestration_id': oid})['record']
    r = execution_with_signal()
    r.update(mission_id=task['mission_id'], pentest_task_id=task['pentest_task_id'],
             orchestration_id=oid, attack_path_snapshot_sha256=first['snapshot_sha256'])
    r = seal(r)
    with repo._connect() as conn:
        conn.execute('CREATE TABLE pentest_exploitation_execution_runs '
                     '(record_json TEXT, created_at TEXT, execution_run_id TEXT)')
        conn.execute('INSERT INTO pentest_exploitation_execution_runs VALUES (?,?,?)',
                     (json.dumps(r), r['completed_at'], r['execution_run_id']))
    assert publish(service, request_for(service, r))['followup']['status'] == 'PROCESSED'
    second = create_plan(service, {'orchestration_id': oid})
    assert not second['created']
    assert second['record']['snapshot_sha256'] == first['snapshot_sha256']


def test_execute_and_cached_replay_publish_without_new_target_probes(tmp_path, monkeypatch):
    from pentest_subsystem.attack_path_workspace import create_plan
    from pentest_subsystem import exploitation_execution
    repo, _, _, oid, _ = _pipeline(tmp_path, 'impact-execution-hook')
    service = CrossAgentFeedbackService(repo)
    first = create_plan(service, {'orchestration_id': oid})['record']
    monkeypatch.setattr(exploitation_execution, 'classify_target',
                        lambda value: {'value': value, 'is_loopback': False})
    monkeypatch.setattr(exploitation_execution, '_probe',
                        lambda *args, **kwargs: pytest.fail('unexpected target I/O'))
    result = exploitation_execution.execute(service, oid)
    assert result['created']
    assert result['impact_followup']['followup']['status'] == 'PROCESSED', result['impact_followup']
    assert result['impact_followup']['followup']['result']['decision_class'] == 'ESCALATE_GOVERNANCE'
    cached = exploitation_execution.execute(service, oid)
    assert not cached['created']
    assert cached['impact_followup']['followup']['status'] == 'PROCESSED'
    assert len(repo.list_feedback(oid)) == 1
    assert create_plan(service, {'orchestration_id': oid})['record']['snapshot_sha256'] == first['snapshot_sha256']
