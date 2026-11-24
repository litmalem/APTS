from copy import deepcopy
import io
import json
from types import SimpleNamespace

import pytest

from pentest_subsystem.impact_workspace import assess, workspace
from pentest_subsystem.impact_report import (
    build_report, verify_report, create_report, list_reports, get_report, export_markdown,
)
from pentest_subsystem.exploitation_execution import EXECUTION_RUN_HASH_DOMAIN, EXECUTION_PATH_RESULT_HASH_DOMAIN
from pentest_subsystem.web_ui import PentestWebMixin, ASSETS, WEB_ROOT
from tests.test_impact_workspace import execution_with_signal
from tests.test_impact_p2 import environment, seal, replace_execution


def report_source(signal='exact_product_version', verdict='OBSERVED', *, time='2026-11-16T01:00:00Z',
                  target='http://localhost/', run_id='xplexec-baseline', method='GET'):
    r = execution_with_signal(verdict, 'CONFIRMED' if verdict == 'OBSERVED' else 'REFUTED' if verdict == 'NOT_OBSERVED' else 'INCONCLUSIVE', run_id=run_id)
    r['completed_at'] = time
    r['target'] = {'value': target}
    r.update(method='CONTROLLED_READ_ONLY_VALIDATION_PROBE', control_version='stage6-controlled-validation-execution')
    p = r['path_results'][0]
    p['expected_evidence_evaluation'][0].update(token=signal, target=target, hypothesis_id='h1', technique='HTTP_OBSERVATION')
    p['probes'] = [{'url': target, 'method': method, 'status_code': 200, 'error': None}]
    r['path_results'] = [seal(p, EXECUTION_PATH_RESULT_HASH_DOMAIN)]
    return seal(r)


def report_for(r, *, baseline=None, objective=None, current=True, note=''):
    return build_report(assess(r, objective=objective), r, current_plan_matches=current,
                        baseline=baseline, remediation_note=note)


def retest(old=None, **kwargs):
    old = old or report_source()
    new = report_source(time='2026-11-16T02:00:00Z', run_id='xplexec-retest', **kwargs)
    return report_for(new, baseline=report_for(old))


def test_report_summary_preserves_unknown_objective_and_business_limits():
    r = report_for(report_source())
    assert verify_report(r)
    assert r['summary']['objective']['status'] == 'UNKNOWN'
    assert r['summary']['contextual_exposure_level'] == 'UNDETERMINED'
    assert not r['summary']['actual_business_impact_confirmed']
    assert not r['summary']['mission_completion_authorized']
    assert any('Objective' in line or 'objective' in line for line in r['limitations'])
    assert r['findings'][0]['evidence_refs'][0]['record_pointer'].endswith('/0')


@pytest.mark.parametrize('signal,category,desired', [
    ('exact_product_version', 'EXPOSURE_REVIEW', 'NOT_OBSERVED'),
    ('configuration_state', 'CONFIGURATION_REVIEW', None),
    ('endpoint_exists', 'SURFACE_REVIEW', None),
    ('authentication_required', 'ACCESS_CONTROL_REVIEW', None),
])
def test_recommendations_do_not_promote_normal_http_signals_into_vulnerabilities(signal, category, desired):
    f = report_for(report_source(signal))['findings'][0]
    assert f['recommendation']['category'] == category
    assert f['recommendation']['desired_verdict'] == desired
    assert not f['confirmed_vulnerability']
    assert f['classification'] == 'TECHNICAL_OBSERVATION_NOT_CONFIRMED_VULNERABILITY'


@pytest.mark.parametrize('verdict', ['INCONCLUSIVE', 'UNSUPPORTED'])
def test_nonconclusive_observations_require_evidence_review(verdict):
    f = report_for(report_source(verdict=verdict))['findings'][0]
    assert f['recommendation']['category'] == 'EVIDENCE_REVIEW'
    assert f['recommendation']['desired_verdict'] is None


@pytest.mark.parametrize('before,after,status', [
    ('OBSERVED', 'NOT_OBSERVED', 'SIGNAL_NO_LONGER_OBSERVED'),
    ('NOT_OBSERVED', 'OBSERVED', 'SIGNAL_NEWLY_OBSERVED'),
    ('OBSERVED', 'OBSERVED', 'UNCHANGED'),
    ('NOT_OBSERVED', 'NOT_OBSERVED', 'UNCHANGED'),
])
def test_retest_classifies_signal_changes_without_asserting_patch_success(before, after, status):
    result = retest(report_source(verdict=before), verdict=after)
    row = result['comparison']['rows'][0]
    assert row['status'] == status
    assert row['technical_expectation_met'] == (after == 'NOT_OBSERVED')
    assert not row['vulnerability_remediation_confirmed']
    assert not result['comparison']['vulnerability_remediation_confirmed']
    assert not result['target_io_performed']


def test_report_keeps_frozen_baseline_refs_and_current_refs():
    old = report_for(report_source())
    new = report_for(report_source(verdict='NOT_OBSERVED', time='2026-11-16T02:00:00Z'), baseline=old)
    comparison = new['comparison']
    assert comparison['baseline_report_id'] == old['report_id']
    assert comparison['baseline_report_sha256'] == old['integrity']['canonical_sha256']
    assert comparison['rows'][0]['baseline_claim_refs'] == old['findings'][0]['claim_refs']
    assert comparison['rows'][0]['retest_claim_refs'] == new['findings'][0]['claim_refs']


def test_same_execution_with_changed_context_is_not_a_retest():
    source = report_source()
    old = report_for(source)
    current = report_for(source, baseline=old, objective={'different': 'declaration'})
    assert current['comparison']['status'] == 'NOT_COMPARABLE'
    assert current['comparison']['reason_code'] == 'NO_NEW_EXECUTION_EVIDENCE'


@pytest.mark.parametrize('time', ['2026-11-16T01:00:00Z', '2026-11-16T00:59:59Z', 'invalid'])
def test_retest_needs_unambiguous_chronology(time):
    old = report_for(report_source())
    new = report_for(report_source(verdict='NOT_OBSERVED', time=time), baseline=old)
    assert new['comparison']['reason_code'] == 'RETEST_CHRONOLOGY_NOT_ESTABLISHED'
    assert new['comparison']['status'] == 'NOT_COMPARABLE'


def test_measurement_changes_and_missing_probe_details_prevent_comparison():
    assert retest(method='HEAD')['comparison']['rows'][0]['status'] == 'NOT_COMPARABLE'
    source = report_source(time='2026-11-16T02:00:00Z')
    p = source['path_results'][0]
    p['probes'] = []
    source['path_results'] = [seal(p, EXECUTION_PATH_RESULT_HASH_DOMAIN)]
    result = report_for(seal(source), baseline=report_for(report_source()))
    assert result['comparison']['rows'][0]['status'] == 'NOT_COMPARABLE'


def test_missing_and_new_coverage_are_not_reported_as_fixed():
    comparison = retest(signal='endpoint_exists')['comparison']
    assert {r['status'] for r in comparison['rows']} == {'NEW_COVERAGE', 'NOT_RETESTED'}
    assert comparison['status'] == 'INCOMPLETE_RETEST'


def test_inconclusive_retest_is_not_a_negative_observation():
    comparison = retest(verdict='INCONCLUSIVE')['comparison']
    assert comparison['rows'][0]['status'] == 'INCONCLUSIVE'
    assert not comparison['rows'][0]['technical_expectation_met']


def test_retest_matches_technical_scope_across_changed_path_and_hypothesis_ids():
    old = report_for(report_source())
    r = report_source(time='2026-11-16T02:00:00Z', verdict='NOT_OBSERVED')
    p = r['path_results'][0]
    p['attack_path_id'] = 'new-path'
    p['expected_evidence_evaluation'][0]['hypothesis_id'] = 'new-hypothesis'
    r['path_results'] = [seal(p, EXECUTION_PATH_RESULT_HASH_DOMAIN)]
    new = report_for(seal(r), baseline=old)
    assert new['comparison']['rows'][0]['status'] == 'SIGNAL_NO_LONGER_OBSERVED'


def test_objective_changes_are_explicit_even_when_technical_scope_matches():
    old = report_for(report_source(), objective={'name': 'old'})
    new = report_for(report_source(time='2026-11-16T02:00:00Z'), objective={'name': 'new'}, baseline=old)
    assert new['comparison']['objective_comparison'] == 'NOT_COMPARABLE_DIFFERENT_OBJECTIVE'
    assert new['comparison']['rows'][0]['status'] == 'UNCHANGED'


def test_historical_baseline_cannot_prove_retest_success():
    old = report_for(report_source(), current=False)
    assert any('historis' in x for x in old['limitations'])
    new = report_for(report_source(time='2026-11-16T02:00:00Z'), baseline=old)
    assert new['comparison']['reason_code'] == 'HISTORICAL_PLAN_AT_CAPTURE'


@pytest.mark.parametrize('field,value', [('mission_id', 'other-mission'), ('target', {'value': 'http://other/'})])
def test_baseline_must_have_same_mission_and_target(field, value):
    old = report_for(report_source())
    source = report_source(time='2026-11-16T02:00:00Z')
    source[field] = value
    with pytest.raises(ValueError, match='mission dan target'):
        report_for(seal(source), baseline=old)


def test_report_detects_mismatched_or_tampered_source_and_report():
    execution = report_source()
    a = assess(execution)
    other = report_source(verdict='NOT_OBSERVED')
    with pytest.raises(ValueError, match='lineage mismatch'):
        build_report(a, other, current_plan_matches=True)
    report = report_for(execution)
    report['summary']['objective']['status'] = 'MET'
    assert not verify_report(report)
    with pytest.raises(ValueError):
        export_markdown(report)


def test_markdown_export_escapes_untrusted_notes_and_keeps_evidence_hashes():
    r = report_for(report_source(), note='<script>alert(1)</script>\n# fake | [click](javascript:x)')
    md = export_markdown(r)
    assert '<script>' not in md
    assert '\n# fake' not in md
    assert '[click](javascript:x)' not in md
    assert r['integrity']['canonical_sha256'] in md
    assert r['source_snapshot']['execution']['integrity']['canonical_sha256'] in md


def test_workspace_preview_remains_read_only(environment):
    repo, service, _, _, _ = environment
    context = workspace(service)['contexts'][0]
    assert context['report_preview']['summary']['technical_observation_count'] == 1
    with repo._connect() as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='pentest_impact_reports'").fetchone()


def request_for_report(service, execution):
    context = workspace(service, execution_run_id=execution['execution_run_id'])['contexts'][0]
    assert context['status'] == 'ASSESSED', context
    return {'execution_run_id': execution['execution_run_id'], 'expected_assessment_id': context['assessment']['assessment_id']}


def test_report_persistence_idempotency_and_frozen_source_after_execution_overwrite(environment):
    repo, service, _, execution, _ = environment
    payload = request_for_report(service, execution)
    first = create_report(service, payload)
    assert first['created']
    assert not create_report(service, payload)['created']
    frozen = deepcopy(first['report'])
    execution['completed_at'] = '2026-11-16T02:00:00Z'
    execution['path_results'][0]['expected_evidence_evaluation'][0]['verdict'] = 'NOT_OBSERVED'
    execution['path_results'] = [seal(execution['path_results'][0], EXECUTION_PATH_RESULT_HASH_DOMAIN)]
    replace_execution(repo, execution)
    assert get_report(repo, frozen['report_id'])['report'] == frozen
    new = create_report(service, {**request_for_report(service, execution), 'baseline_report_id': frozen['report_id']})
    assert new['created']
    assert new['report']['comparison']['baseline_report_id'] == frozen['report_id']
    assert len(list_reports(repo, mission_id=execution['mission_id'])['reports']) == 2
    assert list_reports(repo, mission_id=execution['mission_id'], limit=1)['may_have_more']
    assert not list_reports(repo, mission_id='other-mission')['reports']


def test_changed_assessment_and_client_supplied_report_are_rejected(environment):
    _, service, _, execution, _ = environment
    payload = request_for_report(service, execution)
    with pytest.raises(ValueError):
        create_report(service, {**payload, 'expected_assessment_id': 'old'})
    with pytest.raises(ValueError):
        create_report(service, {**payload, 'report': {'objective': 'MET'}})
    with pytest.raises(ValueError):
        create_report(service, {**payload, 'remediation_note': 'x'*2001})


def test_stored_report_tampering_is_rejected(environment):
    repo, service, _, execution, _ = environment
    item = create_report(service, request_for_report(service, execution))
    report = item['report']
    report['findings'][0]['confirmed_vulnerability'] = True
    with repo._connect() as conn:
        conn.execute('UPDATE pentest_impact_reports SET record_json=?', (json.dumps(report),))
    with pytest.raises(ValueError, match='integrity'):
        get_report(repo, report['report_id'])
    with pytest.raises(ValueError, match='integrity'):
        list_reports(repo, mission_id=execution['mission_id'])


class Handler(PentestWebMixin):
    def _read_json(self):
        return self.payload
    def _send_json(self, status, body):
        self.response = status, body
    def send_response(self, status):
        self.http_status = status
    def send_header(self, name, value):
        self.response_headers[name] = value
    def end_headers(self):
        pass


def test_report_ui_routes_origin_and_exports_without_http_sockets(environment):
    _, service, _, execution, _ = environment
    handler = Handler()
    handler.service = service
    handler.path = '/api/pentest/ui/post-exploitation-impact/reports'
    handler.payload = request_for_report(service, execution)
    handler.headers = {'Host': 'localhost:8790', 'Origin': 'http://foreign.invalid'}
    assert handler.handle_pentest_ui_post() and handler.response[0] == 403
    handler.headers['Origin'] = 'http://localhost:8790'
    assert handler.handle_pentest_ui_post() and handler.response[0] == 201
    report = handler.response[1]['report']
    handler.path += '?mission_id=' + execution['mission_id']
    assert handler.handle_pentest_ui_get() and handler.response[0] == 200
    assert len(handler.response[1]['reports']) == 1
    handler.path = '/api/pentest/ui/post-exploitation-impact/report?report_id=' + report['report_id']
    assert handler.handle_pentest_ui_get() and handler.response[1]['report'] == report
    handler.path += '&format=markdown'
    handler.wfile, handler.response_headers = io.BytesIO(), {}
    assert handler.handle_pentest_ui_get() and handler.http_status == 200
    assert handler.response_headers['Content-Type'] == 'text/markdown; charset=utf-8'
    assert report['integrity']['canonical_sha256'].encode() in handler.wfile.getvalue()
    handler.path = '/api/pentest/ui/post-exploitation-impact/report?report_id=' + report['report_id'] + '&format=html'
    assert handler.handle_pentest_ui_get() and handler.response[0] == 400


def test_report_asset_controls_and_script_order():
    assert ASSETS['/pentest/impact-report.js'] == ('impact-report.js', 'text/javascript')
    html = (WEB_ROOT / 'impact.html').read_text(encoding='utf-8')
    assert html.index('/pentest/impact-report.js') < html.index('/pentest/impact.js')
    for element_id in ('report-preview', 'report-findings', 'report-form', 'report-baseline', 'saved-report-detail'):
        assert f'id="{element_id}"' in html


def test_report_creation_does_not_publish_feedback_or_access_target(environment, monkeypatch):
    repo, service, _, execution, _ = environment
    from pentest_subsystem import exploitation_execution
    def unexpected(*args, **kwargs):
        pytest.fail('report generation must not execute or publish coordination')
    monkeypatch.setattr(exploitation_execution, '_probe', unexpected)
    monkeypatch.setattr(service, 'create_local_replan', unexpected)
    result = create_report(service, request_for_report(service, execution))
    assert not result['execution_started'] and not result['target_io_performed']
    with repo._connect() as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='pentest_impact_outbox'").fetchone()


def test_report_groups_technical_scope_without_double_counting_hypotheses():
    source = report_source()
    second = deepcopy(source['path_results'][0])
    second['attack_path_id'] = 'path-2'
    second['expected_evidence_evaluation'][0]['hypothesis_id'] = 'h2'
    source['path_results'].append(seal(second, EXECUTION_PATH_RESULT_HASH_DOMAIN))
    report = report_for(seal(source))
    assert report['summary']['technical_observation_count'] == 1
    assert report['findings'][0]['hypothesis_refs'] == ['h1', 'h2']
    assert len(report['findings'][0]['evidence_refs']) == 2


def test_report_grouped_contradictions_remain_conflicting():
    source = report_source()
    second = deepcopy(source['path_results'][0])
    second['attack_path_id'] = 'path-2'
    second['expected_evidence_evaluation'][0].update(hypothesis_id='h2', verdict='NOT_OBSERVED')
    source['path_results'].append(seal(second, EXECUTION_PATH_RESULT_HASH_DOMAIN))
    report = report_for(seal(source))
    assert report['findings'][0]['status'] == 'CONFLICTING'
    assert report['findings'][0]['recommendation']['category'] == 'EVIDENCE_REVIEW'


def test_report_requires_exact_source_execution_reference():
    execution = report_source()
    assessment = assess(execution)
    assessment['source_execution_run_id'] = 'xplexec-wrong'
    assessment = seal(assessment, 'APTS_POST_EXECUTION_IMPACT_V1')
    with pytest.raises(ValueError, match='lineage mismatch'):
        build_report(assessment, execution, current_plan_matches=True)


def test_markdown_retest_export_contains_baseline_hash_and_frozen_coordination_state():
    report = retest(verdict='NOT_OBSERVED')
    text = export_markdown(report)
    assert report['comparison']['baseline_report_sha256'] in text
    assert 'Status tindak lanjut saat snapshot: UNPUBLISHED' in text
    assert '## Konteks bisnis' in text
