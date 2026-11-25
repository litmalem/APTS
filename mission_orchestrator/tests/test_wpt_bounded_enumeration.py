"""Real loopback collector/worker and immutable intake accounting regressions."""
from copy import deepcopy
from dataclasses import replace
import time
import pytest

from tests.test_bounded_web_profile_collection import site, LIMITS
from tests.test_enumeration_workspace_delivery import run
from tests.test_stage6_wpt_governed_intake import request, Authority
from execution_subsystem.tool_registry import ADAPTERS
from execution_subsystem.target_broker import TargetBroker, PinnedTarget
from execution_subsystem.web_profile_collection import collect_profile
from execution_subsystem.sandbox_runtime import ResourceSandbox
from execution_subsystem.wpt_intake_repository import WPTIntakeRepository, _seal, _seal_result
from execution_subsystem.wpt_intake_service import WPTIntakeService
from execution_subsystem.execution_contract import ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionSourceRejected
from execution_subsystem.enumeration_followup_contract import build_intake
from execution_subsystem.wpt_intake_contract import normalize_wpt_intake
from adapters.profile_contract import validate_profile

ENUM = next(a for a in ADAPTERS if a.operation == 'WEB_PROFILE_ENUMERATION')
FINGERPRINT = next(a for a in ADAPTERS if a.operation == 'WEB_PROFILE_FINGERPRINT')


def collect(site, adapter=ENUM, budget=5):
    server, seen = site
    target = f'http://127.0.0.1:{server.server_port}/app'
    pin = PinnedTarget('127.0.0.1','127.0.0.1',server.server_port,'/app',False)
    checks, authorizations = [], []
    def check(url, child):
        assert child.ip == pin.ip and child.path.startswith('/app/')
        checks.append(url)
    raw = collect_profile(TargetBroker(),adapter,pin,target,LIMITS,budget,
        deadline=time.monotonic()+8,before_io=lambda:authorizations.append(True),validate_child=check)
    with ResourceSandbox(LIMITS) as worker:
        result = worker.parse(adapter.operation,raw,deadline=time.monotonic()+5)
    assert len(authorizations) == len(seen)
    return result


def test_enumeration_executes_only_fixed_scoped_probes_without_following_redirect(site):
    result = collect(site)
    assert site[1] == ['/app/','/app/robots.txt','/app/sitemap.xml','/app/.well-known/security.txt','/app/favicon.ico']
    assert '/app/login.php' not in site[1]
    assert result['mode'] == 'enumeration'
    assert result['scan_metrics']['requests_performed'] == 5
    assert result['scan_metrics']['scan_status'] == 'PARTIAL'
    assert result['observations'][0]['redirect_blocked'] is True
    assert result['surface_candidates'][0]['url'].endswith('/app/')
    assert 'private-session' not in repr(result) and 'private-token' not in repr(result)
    assert validate_profile(result) == result
    assert WPTIntakeService._safe_observation(result) == result


def test_remaining_budget_limits_enumeration_and_unprobed_urls_are_not_results(site):
    result = collect(site,budget=4)
    assert len(site[1]) == 4
    assert result['observations'][-1]['status_code'] is None
    assert result['scan_metrics']['scan_status'] == 'PARTIAL'
    assert all(not c['url'].endswith('favicon.ico') for c in result['surface_candidates'])
    bad = deepcopy(result)
    bad['surface_candidates'].append({'url':'https://outside.test/','status_code':200,'source':'bounded_probe'})
    with pytest.raises(ValueError):validate_profile(bad)


def test_subresource_scope_rejection_stops_before_target_io(site):
    server, seen = site
    target = f'http://127.0.0.1:{server.server_port}/app'
    pin = PinnedTarget('127.0.0.1','127.0.0.1',server.server_port,'/app',False)
    def reject(url, child):
        raise ExecutionSourceRejected('EXCLUDED_TARGET')
    with pytest.raises(ExecutionSourceRejected,match='EXCLUDED_TARGET'):
        collect_profile(TargetBroker(),ENUM,pin,target,LIMITS,5,deadline=time.monotonic()+5,
            before_io=lambda:None,validate_child=reject)
    assert not seen


def store_intake(repo, identity, target, budget=6):
    intake = request(identity,target={'target_type':'URL','target_value':target})
    authority = Authority().resolve(intake)
    authority['mission_network_request_budget'] = budget
    record = _seal({'intake':intake,'authority_snapshot':authority})
    return repo.append(record)[0]['record']


def store_result(repo, original, observation, **changes):
    intake=original['intake']
    value={'schema_version':'apts-wpt-stage6-result-record-v1','status':'VALIDATED_AND_STORED',
        **{k:intake[k] for k in ('intake_id','mission_id','task_id','target')},
        'execution_id':'exec-completed','attempt_id':'xattempt-completed',
        'profile_id':original['authority_snapshot']['profile_id'],
        'action':original['authority_snapshot']['action'],
        'evidence':{'capture_status':'SEALED'},
        'result':{'status':'SUCCEEDED','observation':observation},**changes}
    repo.append_result(_seal_result(value))


def test_budget_reconciles_terminal_verified_consumption_once_and_replay_does_not_rescan(site,tmp_path):
    result = collect(site,FINGERPRINT,6)  # Three actual requests, including redirect.
    repo=WPTIntakeRepository(tmp_path/'intakes.db')
    first=store_intake(repo,'first',result['target'])
    with pytest.raises(ExecutionRequestConflict):store_intake(repo,'second',result['target'])
    store_result(repo,first,result)
    next_record=store_intake(repo,'second',result['target'])
    assert next_record['authority_snapshot']['limits']['max_requests'] == 3
    assert store_intake(repo,'second',result['target']) == next_record
    service=WPTIntakeService(repo,Authority())
    assert service.submit(first['intake'])['stage6_admission']['status']=='RESULT_STORED'
    assert len(site[1]) == 3
    with pytest.raises(ExecutionRequestConflict):store_intake(repo,'third',result['target'])


@pytest.mark.parametrize('change',[{'mission_id':'mission-gmo-other'}, {'evidence':{'capture_status':'PENDING'}}])
def test_budget_does_not_release_mismatched_completion(site,tmp_path,change):
    result=collect(site,FINGERPRINT,6);repo=WPTIntakeRepository(tmp_path/'intakes.db')
    first=store_intake(repo,'first',result['target']);store_result(repo,first,result,**change)
    with pytest.raises(ExecutionRequestIntegrityError):store_intake(repo,'second',result['target'])


def test_legacy_unknown_consumption_keeps_full_reservation(tmp_path):
    repo=WPTIntakeRepository(tmp_path/'intakes.db');first=store_intake(repo,'first','http://127.0.0.1/app')
    store_result(repo,first,{'scan_metrics':{'requests_performed':1}})
    with pytest.raises(ExecutionRequestConflict):store_intake(repo,'second','http://127.0.0.1/app')


def test_cti_v4_carries_valid_candidates_and_preserves_v3_identity(run):
    run['request']['observations'][0]['attributes']['cpe_candidates']=[
        {'cpe23_uri':None,'match_confidence':None},
        {'cpe23_uri':'cpe:2.3:a:php:php:8.0.30:*:*:*:*:*:*:*','match_confidence':.99}]
    new=build_intake(run);old=build_intake(run,schema_version='apts-wpt-governed-intake-v3')
    assert normalize_wpt_intake(new)==new and normalize_wpt_intake(old)==old
    assert new['intake_id'] != old['intake_id']
    assert len(new['enumeration_context']['cpe_candidates'])==1
    assert 'cpe_candidates' not in old['enumeration_context']
    bad=deepcopy(new);bad['enumeration_context']['arbitrary_probes']=['/admin']
    with pytest.raises(ValueError):normalize_wpt_intake(bad)


def test_real_stage6_fingerprint_then_enumeration_share_six_request_budget(site,tmp_path,monkeypatch):
    from tests import test_stage4_6_pentest_workflow_orchestrator_skeleton as materialize
    from tests.test_stage5_9_governance_bound_multi_agent_pentest_e2e import _pipeline
    from tests.test_stage6_2_authoritative_execution_authorization import NOW, seed_mission
    from tests.test_stage6_3_controlled_execution_gateway import UniqueAuthority
    from tests.test_stage6_5_execution_runtime_control import wait_for
    from execution_subsystem.evidence_service import ExecutionEvidenceService
    from execution_subsystem.evidence_repository import ExecutionEvidenceRepository
    from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
    from execution_subsystem.runtime_contract import START_SCHEMA
    from datetime import timedelta
    target=f'http://127.0.0.1:{site[0].server_port}/app'
    original=materialize.sample_boundary
    def boundary():
        value=original();value['scope']['targets'][0]={'target_type':'URL','target_value':target}
        value['roe']['allowed_techniques'] += ['WEB_TECHNOLOGY_FINGERPRINT','BOUNDED_WEB_SURFACE_ENUMERATION']
        value['constraints']['resource_budget']={'max_network_requests':6}
        return value
    monkeypatch.setattr(materialize,'sample_boundary',boundary)
    pentest,bound,task,_,_=_pipeline(tmp_path,'bounded-wpt',through_stage='5.2')
    mission_db=tmp_path/'mission.db';seed_mission(mission_db,bound)
    monkeypatch.setenv('APTS_PENTEST_DB',str(pentest.sqlite_path))
    monkeypatch.setenv('APTS_EXECUTION_MISSION_DB',str(mission_db))
    monkeypatch.setenv('APTS_WPT_INTAKE_DB',str(tmp_path/'intakes.db'))
    monkeypatch.setenv('APTS_STAGE6_RUNTIME_URL','http://127.0.0.1:1')
    monkeypatch.setattr('execution_subsystem.wpt_job_callback.publish_stage6_result',lambda *a:{'status':'DELIVERED'})
    authority=UniqueAuthority()
    now=[NOW]
    runtime=ExecutionEvidenceService(ExecutionEvidenceRepository(tmp_path/'execution.db'),
        ExecutionAuthorizationProposalSource(pentest.sqlite_path),MissionAuthorizationSource(mission_db),
        authority,clock=lambda:now[0])
    wpt=WPTIntakeService(stage6_gateway=runtime,stage6_result_source=runtime.repository)
    try:
        for index,profile in enumerate(('fingerprinting','enumeration')):
            now[0]=NOW+timedelta(seconds=2*index)
            intake=request('full-'+profile,mission_id=bound['mission_id'],task_id=bound['task_id'],
                target={'target_type':'URL','target_value':target},profile=profile)
            submitted=wpt.submit(intake)
            admission=submitted['stage6_admission']
            assert admission['status']=='REQUEST_CREATED',admission
            attempt=runtime.start_execution({'schema_version':START_SCHEMA,
                'invocation_request_id':'toolreq-full-'+profile,'idempotency_key':'idem-full-'+profile,
                'execution_id':admission['execution_id'],'envelope_sha256':admission['envelope_sha256'],
                'requested_by':'bounded-wpt-test'})
            final=wait_for(runtime,attempt['attempt_id'])
            assert final['state']=='SUCCEEDED',(final,runtime._failures)
            evidence=runtime.get_evidence(attempt['attempt_id'])
            assert evidence['sealed'] is True
            result=wpt.submit_stage6_result({'schema_version':'apts-wpt-stage6-result-reference-v1',
                'intake_id':intake['intake_id'],'execution_id':admission['execution_id'],'attempt_id':attempt['attempt_id']})
            observed=result['record']['result']['observation']
            assert observed['mode']==profile
            assert observed['scan_metrics']['requests_performed']==3
            assert len(site[1])==3*(index+1)
        assert site[1][3:]==['/app/','/app/robots.txt','/app/sitemap.xml']
        with pytest.raises(ExecutionRequestConflict):
            wpt.submit(request('exhausted',mission_id=bound['mission_id'],task_id=bound['task_id'],
                target={'target_type':'URL','target_value':target},profile='enumeration'))
    finally:
        runtime.close()


# --- Opsi B: CTI enumeration_context must reach the collector via the sealed,
# authority-bound WPT intake (previously dropped: execution_request carried only
# source_wpt_intake_id, so collect_profile always ran the 5-probe base plan). ---
ENUM_CTX = {
    'source_cti_intake_id': 'wptreq-ctx', 'enumeration_run_id': 'enumrun-ctx',
    'enumeration_request_sha256': 'a' * 64, 'recon_run_id': 'reconrun-ctx',
    'source_result_sha256': 'b' * 64,
    'technologies': [{'name': 'PHP', 'version': '8.0.30'}],
    'cpe_candidates': [{'technology_name': 'PHP',
                        'cpe23_uri': 'cpe:2.3:a:php:php:8.0.30:*:*:*:*:*:*:*',
                        'match_confidence': 0.99, 'status': 'CPE_CANDIDATE_NEEDS_VERIFICATION'}],
}


def _store_enum_intake(repo, suffix, *, context=None, target='http://127.0.0.1/app'):
    changes = {'profile': 'enumeration', 'mission_id': 'mission-gmo-' + suffix,
               'task_id': 'ptask-' + suffix, 'target': {'target_type': 'URL', 'target_value': target}}
    if context is not None:
        changes['schema_version'] = 'apts-wpt-governed-intake-v4'
        changes['enumeration_context'] = context
    intake = request(suffix, **changes)
    authority = Authority().resolve(intake)
    return repo.append(_seal({'intake': intake, 'authority_snapshot': authority}))[0]['record']


def _bound_request(record):
    return {'parameters': {'source_wpt_intake_id': record['intake']['intake_id']},
            'evidence_basis': [{'canonical_sha256': record['integrity']['canonical_sha256']}]}


def test_enumeration_context_binds_to_sealed_intake_and_drives_cti_probe(tmp_path, monkeypatch):
    from execution_subsystem.adapter_policy import _wpt_enumeration_context
    from adapters.profile_engine import cti_surface_paths
    repo = WPTIntakeRepository(tmp_path / 'intakes.db')
    monkeypatch.setenv('APTS_WPT_INTAKE_DB', str(tmp_path / 'intakes.db'))

    # A CTI-bearing follow-up intake yields its context verbatim, which the shared
    # planner turns into the deterministic /phpinfo.php follow-up probe.
    ctx_record = _store_enum_intake(repo, 'ctx', context=ENUM_CTX)
    resolved = _wpt_enumeration_context(_bound_request(ctx_record))
    assert resolved == ENUM_CTX
    assert '/phpinfo.php' in cti_surface_paths(resolved)

    # A plain enumeration intake carries no context -> fixed 5-probe base plan.
    plain_record = _store_enum_intake(repo, 'plain')
    assert _wpt_enumeration_context(_bound_request(plain_record)) is None

    # No source intake reference at all -> None (fingerprinting / legacy path).
    assert _wpt_enumeration_context({'parameters': {}, 'evidence_basis': []}) is None


def test_enumeration_context_rejected_when_not_bound_to_execution_evidence(tmp_path, monkeypatch):
    from execution_subsystem.adapter_policy import _wpt_enumeration_context
    repo = WPTIntakeRepository(tmp_path / 'intakes.db')
    monkeypatch.setenv('APTS_WPT_INTAKE_DB', str(tmp_path / 'intakes.db'))
    record = _store_enum_intake(repo, 'ctx', context=ENUM_CTX)
    # Same intake id, but the sealed digest is absent from evidence_basis: the
    # context is not bound to this authorized execution -> fail closed.
    unbound = {'parameters': {'source_wpt_intake_id': record['intake']['intake_id']},
               'evidence_basis': [{'canonical_sha256': '0' * 64}]}
    with pytest.raises(ExecutionSourceRejected, match='WPT_INTAKE_CONTEXT_BINDING_MISMATCH'):
        _wpt_enumeration_context(unbound)
