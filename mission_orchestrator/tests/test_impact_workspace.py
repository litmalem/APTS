from copy import deepcopy
import pytest
from pentest_subsystem.impact_workspace import assess
from pentest_subsystem.exploitation_execution import EXECUTION_RUN_HASH_DOMAIN, EXECUTION_RUN_SCHEMA_VERSION, EXECUTION_PATH_RESULT_HASH_DOMAIN, EXECUTION_FINDING_HASH_DOMAIN
from pentest_subsystem.vulnerability_hypothesis import _with_integrity


def source(outcome='CONFIRMED', verdict='OBSERVED', blocked=False):
    finding = _with_integrity({'status': outcome}, domain=EXECUTION_FINDING_HASH_DOMAIN)
    path = _with_integrity({'attack_path_id': 'path-1', 'outcome': outcome,
        'expected_evidence_evaluation': [{'token': 'service_version', 'verdict': verdict}],
        'finding': finding}, domain=EXECUTION_PATH_RESULT_HASH_DOMAIN)
    return _with_integrity({'schema_version': EXECUTION_RUN_SCHEMA_VERSION,
        'execution_run_id': 'xplexec-1', 'mission_id': 'm1', 'pentest_task_id': 't1',
        'orchestration_id': 'paorch-1', 'target': {'value': 'http://localhost/'},
        'completed_at': '2026-11-16T00:00:00Z', 'attack_path_snapshot_sha256': 'a'*64,
        'scope_decision': {'status': 'BLOCKED_OUT_OF_LOCALHOST_SCOPE' if blocked else 'EXECUTED_LOCALHOST'},
        'semantics': {'read_only': True, 'non_destructive': True, 'localhost_scope_enforced': True,
                      'active_payload_sent': False, 'write_performed': False,
                      'destructive_action_performed': False, 'external_target_execution': False},
        'path_results': [path]}, domain=EXECUTION_RUN_HASH_DOMAIN)


def test_sufficient_signal_stops_without_claiming_compromise_or_mission_success():
    r = source()
    a = assess(r)
    assert a == assess(deepcopy(r))
    assert a['decision'] == 'STOP'
    p = a['analyses'][0]
    assert p['evidence_sufficient_for_technical_signals']
    assert not p['reached_privilege']['confirmed']
    assert not p['mission_objective_satisfied']
    assert not a['target_io_performed']
    assert a['source_execution_sha256'] == r['integrity']['canonical_sha256']


@pytest.mark.parametrize('outcome,verdict', [('INCONCLUSIVE','INCONCLUSIVE'), ('PARTIALLY_CONFIRMED','OBSERVED'), ('CONFIRMED','NOT_OBSERVED')])
def test_insufficient_evidence_replans(outcome, verdict):
    assert assess(source(outcome,verdict))['decision'] == 'REPLAN'


def test_refuted_candidate_stops_without_claiming_mission_success():
    result = assess(source('REFUTED', 'NOT_OBSERVED'))
    assert result['decision'] == 'STOP'
    assert result['analyses'][0]['reason'] == 'HYPOTHESIS_REFUTED'
    assert result['objective_assessment']['status'] == 'UNKNOWN'


def objective(signal='endpoint_exists', expected='OBSERVED'):
    return {'success_criteria': [{'criterion_id': 'c1', 'attack_path_id': 'path-1',
                                'signal': signal, 'expected_verdict': expected}]}


def execution_with_signal(verdict='OBSERVED', outcome='CONFIRMED', run_id='xplexec-1', error=None):
    r = source(outcome, verdict)
    p = r['path_results'][0]
    p['expected_evidence_evaluation'][0]['token'] = 'endpoint_exists'
    p['probes'] = [{'error': error}]
    p.pop('integrity')
    r['path_results'] = [_with_integrity(p, domain=EXECUTION_PATH_RESULT_HASH_DOMAIN)]
    r['execution_run_id'] = run_id
    r.pop('integrity')
    return _with_integrity(r, domain=EXECUTION_RUN_HASH_DOMAIN)


@pytest.mark.parametrize('verdict,outcome,status', [
    ('OBSERVED', 'CONFIRMED', 'MET'),
    ('NOT_OBSERVED', 'REFUTED', 'NOT_MET'),
    ('INCONCLUSIVE', 'INCONCLUSIVE', 'UNKNOWN')])
def test_authoritative_objective_matches_only_supported_observations(verdict, outcome, status):
    a = assess(execution_with_signal(verdict, outcome), objective=objective())
    assert a['objective_assessment']['status'] == status
    assert a['mission_objective_satisfied'] == (status == 'MET')
    assert not a['assessment_contract']['mission_completion_authorized']


def test_negative_objective_is_met_by_negative_observation():
    a = assess(execution_with_signal('NOT_OBSERVED', 'REFUTED'),
               objective=objective(expected='NOT_OBSERVED'))
    assert a['objective_assessment']['status'] == 'MET'


def test_unsupported_criterion_never_claims_privilege():
    r = source()
    assert assess(r, objective=objective('admin_access'))['objective_assessment']['status'] == 'UNKNOWN'


@pytest.mark.parametrize('value', [None, {}, {'goal_predicates': ['admin']},
    {'success_criteria': []}, {'success_criteria': ['bad']},
    {'success_criteria': [{'criterion_id': 'bad'}]}])
def test_legacy_or_invalid_criteria_are_unknown(value):
    assert assess(source(), objective=value)['objective_assessment']['status'] == 'UNKNOWN'


def test_stale_results_cannot_satisfy_objective_even_when_signals_match():
    a = assess(execution_with_signal(), objective=objective(), stale=True)
    assert a['decision'] == 'ESCALATE'
    assert a['objective_assessment']['status'] == 'UNKNOWN'
    assert not a['analyses'][0]['evidence_sufficient_for_technical_signals']


def test_projection_uses_same_contract_without_promoting_plans_to_evidence():
    from pentest_subsystem.impact_policy import evaluate_objective, assessment_contract, CONTRACT, POLICY
    evaluated = evaluate_objective(objective())
    assert evaluated['status'] == 'UNKNOWN'
    projected = assessment_contract(evaluated, evidence_basis='STAGE5_PROJECTION',
                                   decision='DEFER', reason_code='NO_EXECUTION')
    observed = assess(source())['assessment_contract']
    assert projected['schema_version'] == observed['schema_version'] == CONTRACT
    assert projected['policy_version'] == observed['policy_version'] == POLICY


def test_repeat_observations_escalate_but_polling_same_record_does_not():
    r = execution_with_signal('INCONCLUSIVE', 'INCONCLUSIVE')
    older = execution_with_signal('INCONCLUSIVE', 'INCONCLUSIVE', run_id='xplexec-0')
    assert assess(r, prior_records=[r])['decision'] == 'REPLAN'
    a = assess(r, prior_records=[older])
    assert a['decision'] == 'ESCALATE'
    assert a['analyses'][0]['reason'] == 'NO_NEW_INFORMATION'
    assert a == assess(r, prior_records=[older])


def test_iteration_budget_and_probe_failure_have_distinct_reasons():
    r = execution_with_signal('INCONCLUSIVE', 'INCONCLUSIVE', error='timeout')
    assert assess(r)['analyses'][0]['reason'] == 'PROBE_FAILED'
    older = [execution_with_signal('INCONCLUSIVE', 'INCONCLUSIVE', run_id=f'xplexec-old-{i}', error=str(i)) for i in range(2)]
    assert assess(r, prior_records=older)['analyses'][0]['reason'] == 'ITERATION_LIMIT_REACHED'
    assert assess(r, prior_records=older[:1] * 4)['analyses'][0]['replanning']['iterations'] == 2


def test_assessment_identity_binds_objective_and_plan_freshness():
    r = execution_with_signal()
    assert assess(r)['assessment_id'] != assess(r, objective=objective())['assessment_id']
    assert assess(r)['assessment_id'] != assess(r, stale=True)['assessment_id']


def test_target_criteria_can_be_declared_before_path_generation():
    from pentest_subsystem.impact_policy import evaluate_objective
    criteria = {'success_criteria': [{'criterion_id': 'c1', 'target': 'http://localhost/',
                                    'signal': 'endpoint_exists', 'expected_verdict': 'OBSERVED'}]}
    paths = [{'attack_path_id': 'generated-later', 'expected_evidence_evaluation': [
        {'token': 'endpoint_exists', 'target': 'http://localhost/', 'verdict': 'OBSERVED'}]}]
    assert evaluate_objective(criteria, paths, evidence_basis='STAGE6_OBSERVATION', usable=True)['status'] == 'MET'
    paths[0]['expected_evidence_evaluation'][0]['target'] = 'http://other/'
    assert evaluate_objective(criteria, paths, evidence_basis='STAGE6_OBSERVATION', usable=True)['status'] == 'UNKNOWN'


def test_conflicting_observations_and_duplicate_criteria_fail_closed():
    from pentest_subsystem.impact_policy import evaluate_objective
    paths = [{'attack_path_id': 'path-1', 'expected_evidence_evaluation': [
        {'token': 'endpoint_exists', 'verdict': 'OBSERVED'},
        {'token': 'endpoint_exists', 'verdict': 'NOT_OBSERVED'}]}]
    assert evaluate_objective(objective(), paths, evidence_basis='STAGE6_OBSERVATION', usable=True)['status'] == 'UNKNOWN'
    criteria = objective()
    criteria['success_criteria'] *= 2
    assert evaluate_objective(criteria, paths, evidence_basis='STAGE6_OBSERVATION', usable=True)['status'] == 'UNKNOWN'


def test_tampered_history_is_rejected_instead_of_resetting_budget():
    r = source()
    old = source()
    old['mission_id'] = 'tampered'
    with pytest.raises(ValueError, match='Prior Exploitation'):
        assess(r, prior_records=[old])


def test_workspace_budget_is_persisted_independent_of_page_limit(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from pentest_subsystem import impact_workspace, attack_path_workspace
    from pentest_subsystem.workflow_repository import PentestWorkflowRepository
    from tests.test_stage4_6_pentest_workflow_orchestrator_skeleton import materialize
    repo = PentestWorkflowRepository(tmp_path / 'history.db')
    _, _, task, _, _ = materialize(repo)
    with repo._connect() as conn:
        conn.execute('CREATE TABLE pentest_exploitation_execution_runs '
                     '(record_json TEXT, created_at TEXT, execution_run_id TEXT)')
        for index in range(3):
            r = execution_with_signal('INCONCLUSIVE', 'INCONCLUSIVE',
                                      run_id=f'xplexec-{index}', error=f'error-{index}')
            r.update(mission_id=task['mission_id'], pentest_task_id=task['pentest_task_id'])
            r.pop('integrity')
            r = _with_integrity(r, domain=EXECUTION_RUN_HASH_DOMAIN)
            conn.execute('INSERT INTO pentest_exploitation_execution_runs VALUES (?,?,?)',
                         (json.dumps(r), f'2026-11-16T00:00:0{index}Z', r['execution_run_id']))
    monkeypatch.setattr(attack_path_workspace, 'history', lambda *args: [{'snapshot_sha256': 'a'*64}])
    service = SimpleNamespace(repository=repo, get_task=repo.get_task)
    latest = impact_workspace.workspace(service, limit=1)['contexts'][0]['assessment']
    assert latest['analyses'][0]['reason'] == 'ITERATION_LIMIT_REACHED'
    assert latest['analyses'][0]['replanning']['iterations'] == 3
    assert impact_workspace.workspace(service, limit=1)['contexts'][0]['assessment'] == latest
    all_results = impact_workspace.workspace(service, limit=500)['contexts']
    assert all_results[0]['assessment'] == latest
    assert all_results[-1]['assessment']['analyses'][0]['replanning']['iterations'] == 1


def test_scope_denial_escalates_even_with_confirmed_outcome():
    a = assess(source(blocked=True))
    assert a['decision'] == 'ESCALATE'
    assert not a['analyses'][0]['evidence_sufficient_for_technical_signals']


def test_tampered_source_rejected():
    r = source()
    r['path_results'][0]['outcome'] = 'REFUTED'
    with pytest.raises(ValueError, match='integrity'):
        assess(r)


def test_workspace_never_calls_upstream_execution(tmp_path, monkeypatch):
    import sqlite3
    import json
    from types import SimpleNamespace
    from pentest_subsystem import impact_workspace, attack_path_workspace
    db = tmp_path / 'impact.db'
    class Repo:
        def _connect(self):
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            return conn
    repo = Repo()
    service = SimpleNamespace(repository=repo)
    assert impact_workspace.workspace(service)['contexts'] == []
    with repo._connect() as conn:
        conn.execute('CREATE TABLE pentest_exploitation_execution_runs (record_json TEXT, created_at TEXT, execution_run_id TEXT)')
        conn.execute('INSERT INTO pentest_exploitation_execution_runs VALUES (?,?,?)', (json.dumps(source()), 'now', 'xplexec-1'))
    monkeypatch.setattr(attack_path_workspace, 'history', lambda *args: [{'snapshot_sha256': 'b'*64}])
    result = impact_workspace.workspace(service)
    assert result['contexts'][0]['status'] == 'STALE_EXECUTION'
    assert not result['target_io_performed']
    monkeypatch.setattr(attack_path_workspace, 'history', lambda *args: [{'snapshot_sha256': 'a'*64}])
    assert impact_workspace.workspace(service)['contexts'][0]['status'] == 'ASSESSED'


def test_new_ui_routes_and_navigation():
    from pentest_subsystem.web_ui import ASSETS, WEB_ROOT
    assert ASSETS['/pentest/post-exploitation-impact/'][0] == 'impact.html'
    assert ASSETS['/pentest/impact.js'][0] == 'impact.js'
    for name in ('index.html', 'enumeration.html', 'hypothesis.html', 'planning.html', 'exploitation.html'):
        assert 'href="/pentest/post-exploitation-impact/"' in (WEB_ROOT / name).read_text(encoding='utf-8')
