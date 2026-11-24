"""P1.1 narrow PARTIAL -> RECON_BOOTSTRAP, without target network actions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from mission_orchestrator.cti_stage43_bridge import (
    _hash_source_artifact, _verify_cti_pip, derive_stage43_inputs,
)
from mission_orchestrator.errors import MissionTaskDelegationGuardRejected as Guard
from mission_orchestrator.pentest_handoff import handoff_to_pentest
from tests.test_p1_cti_stage43_materialization import cti_source, setup
from tests.test_mission_pentest_handoff import ready
from pentest_subsystem.governance_bound_e2e import GovernanceBoundE2ERepository
from pentest_subsystem.agentic_pentest_acceptance_service import AgenticPentestAcceptanceService

@pytest.fixture
def url_ready(monkeypatch, request):
    from tests import test_stage3_3_4_task_dependency_graph_structural_validation as planning
    from tests import test_stage3_4_5_governance_bound_delegation_authorization as delegation
    original_scope_planning = planning.scope_payload
    original_scope_governance = delegation.scope_payload
    original_mission = planning.mission_payload

    def scope_with_url(original):
        def wrapped(*args, **kwargs):
            body = original(*args, **kwargs)
            body['scope']['targets'] = [dict(TARGET)]
            body['scope']['network_ranges'] = []
            body['scope']['services'] = [{'name': 'Juice Shop', 'protocol': 'HTTP',
                                          'port': 3000, 'target_ref': TARGET['target_value']}]
            return body
        return wrapped

    def mission_with_url(*args, **kwargs):
        body = original_mission(*args, **kwargs)
        body['objective']['target_ref'] = TARGET['target_value']
        return body

    monkeypatch.setattr(planning, 'scope_payload', scope_with_url(original_scope_planning))
    monkeypatch.setattr(delegation, 'scope_payload', scope_with_url(original_scope_governance))
    monkeypatch.setattr(planning, 'mission_payload', mission_with_url)
    return request.getfixturevalue('ready')


MISSION = 'mission-gmo-bootstrap-test'
TARGET = {'target_type': 'URL', 'target_value': 'http://localhost:3000/', 'environment': 'LAB'}


def _source(now=None):
    now = now or datetime.now(timezone.utc)
    source = cti_source(MISSION, TARGET)
    source['readiness'] = source['artifact']['quality']['readiness'] = 'PARTIAL'
    source['published_readiness'] = 'PARTIAL'
    asset = source['artifact']['intelligence']['asset_profiles'][0]
    asset.update({
        'mission_id': MISSION, 'asset_profile_id': 'assetprof-bootstrap-1',
        'asset_id': 'juice-shop', 'verification_status': 'OBSERVED',
        'evidence_refs': ['asset-observation-genuine-1'],
        'observed_at': (now - timedelta(seconds=15)).isoformat().replace('+00:00','Z'),
        'observed_attributes': {'target_url': TARGET['target_value']},
    })
    source['artifact']['intelligence']['vulnerability_correlations'] = []
    source['artifact']['intelligence']['risk_priorities'] = []
    source['artifact']['intelligence']['attack_paths'] = []
    source['artifact']['created_at'] = now.isoformat().replace('+00:00','Z')
    return _seal(source)


def _seal(source):
    digest = _hash_source_artifact(source['artifact'])
    source['artifact']['integrity']['sha256'] = digest
    source['canonical_sha256'] = digest
    return source


def _verify(source, now=None):
    return _verify_cti_pip(source, pip_id=source['pip_id'], mission_id=MISSION,
                           target=TARGET, now=now or datetime.now(timezone.utc))


def test_partial_with_observed_target_and_ten_gates_allowed_for_bootstrap():
    source = _source()
    _, _, _, confidence, bootstrap = _verify(source)
    assert confidence == 0.91
    assert bootstrap['mode'] == 'RECON_BOOTSTRAP'
    assert bootstrap['execution_authorized'] is False
    assert len(bootstrap['quality_gate_ids']) == 10


@pytest.mark.parametrize('change', [
    lambda s: s['artifact']['intelligence']['asset_profiles'].clear(),
    lambda s: s['artifact']['intelligence']['asset_profiles'][0]['observed_attributes'].update(target_url='http://localhost:3001/'),
    lambda s: s['artifact']['intelligence']['asset_profiles'][0].update(verification_status='INFERRED'),
    lambda s: s['artifact']['intelligence']['asset_profiles'][0].update(evidence_refs=[]),
    lambda s: s['artifact']['intelligence']['asset_profiles'][0].update(confidence=None),
    lambda s: s['artifact']['intelligence']['asset_profiles'][0].update(mission_id='wrong-mission'),
    lambda s: s['artifact']['intelligence']['asset_profiles'][0].update(observed_at='2022-01-01T00:00:00Z'),
    lambda s: s['artifact']['intelligence'].update(vulnerability_correlations=[{'correlation_id':'unverified-claim'}]),
    lambda s: s['artifact']['intelligence'].update(attack_paths=[{'path_id':'unsupported'}]),
    lambda s: s['artifact']['intelligence'].update(risk_priorities=[{'intention_id':'unsound'}]),
    lambda s: s.update(published_readiness='ACTIONABLE'),
    lambda s: s.pop('published_readiness'),
    lambda s: s['validation_results'].pop(),
    lambda s: s['validation_results'][0].update(gate_id='QG-H2'),
    lambda s: s['validation_results'][0].update(passed=False),
    lambda s: s['artifact']['quality'].update(hard_gate_passed=False),
    lambda s: s['artifact']['semantics'].update(execution_authorized=True),
    lambda s: s.update(immutable=False),
])
def test_partial_fail_closed_when_bootstrap_evidence_or_guard_missing(change):
    source = _source()
    change(source)
    source['artifact']['quality']['validation_results'] = deepcopy(source['validation_results'])
    _seal(source)
    with pytest.raises(Guard):
        _verify(source)


def test_partial_fails_if_sha_tampered_even_with_valid_gates():
    source = _source()
    source['artifact']['intelligence']['asset_profiles'][0]['confidence'] = .81
    with pytest.raises(Guard, match='SHA-256'):
        _verify(source)


def test_partial_fails_if_stale_pip_or_nonlab_target():
    now = datetime.now(timezone.utc)
    source = _source(now - timedelta(hours=2))
    with pytest.raises(Guard, match='stale'):
        _verify(source, now)
    source = _source()
    now = datetime.now(timezone.utc)
    with pytest.raises(Guard, match='LAB'):
        _verify_cti_pip(source, pip_id=source['pip_id'], mission_id=MISSION,
                        target={**TARGET, 'environment': 'PRODUCTION'}, now=now)


def test_existing_actionable_path_retains_original_behavior():
    source = cti_source(MISSION, TARGET)
    artifact, _, _, confidence, eligibility = _verify(source)
    assert eligibility is None and confidence == .91
    assert artifact['quality']['readiness'] == 'ACTIONABLE'


def test_end_to_end_partial_materializes_only_recon_task(url_ready, monkeypatch):
    service, gov, mission, inbox, payload, source, ref = setup(url_ready, monkeypatch)
    received = inbox.get(inbox.list()[0]['handoff_id'])
    target = received['envelope']['work_context']['scope']['targets'][0]
    source = cti_source(mission, target)
    source['readiness'] = source['artifact']['quality']['readiness'] = 'PARTIAL'
    source['published_readiness'] = 'PARTIAL'
    asset = source['artifact']['intelligence']['asset_profiles'][0]
    asset.update({'asset_profile_id':'assetprof-e2e-1', 'mission_id':mission,
                  'verification_status':'OBSERVED', 'evidence_refs':['ref-asset-1'],
                  'observed_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                  'observed_attributes':{'target_url':target['target_value']}})
    _seal(source)
    monkeypatch.setattr('mission_orchestrator.cti_stage43_bridge.CtiSubsystemClient.get_pip',
                        lambda self, _id: deepcopy(source))
    output = handoff_to_pentest(service, mission, {**payload, 'stage43_cti':ref}, inbox)
    assert output['stage43_materialized'] is True
    assert output['execution_authorized'] is False and output['target_actuation'] is False
    assert output['pentest_task']['created'] is True
    pentest = AgenticPentestAcceptanceService(GovernanceBoundE2ERepository(inbox.path))
    assert len(pentest.list_tasks()) == 1
    again = handoff_to_pentest(service, mission, {**payload, 'stage43_cti':ref}, inbox)
    assert again['pentest_task']['created'] is False
    assert len(pentest.list_tasks()) == 1


def test_partial_wrong_recipient_capability_never_materializes(url_ready, monkeypatch):
    service, gov, mission, inbox, payload, source, ref = setup(url_ready, monkeypatch)
    received = inbox.get(inbox.list()[0]['handoff_id'])
    target = received['envelope']['work_context']['scope']['targets'][0]
    source = cti_source(mission, target)
    source['readiness'] = source['artifact']['quality']['readiness'] = 'PARTIAL'
    source['published_readiness'] = 'PARTIAL'
    asset = source['artifact']['intelligence']['asset_profiles'][0]
    asset.update({'asset_profile_id':'assetprof-e2e-1', 'mission_id':mission,
                  'verification_status':'OBSERVED', 'evidence_refs':['ref-asset-1'],
                  'observed_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                  'observed_attributes':{'target_url':target['target_value']}})
    _seal(source)
    received['envelope']['recipient']['capability_id'] = 'pentest.exploit'
    monkeypatch.setattr('mission_orchestrator.cti_stage43_bridge.CtiSubsystemClient.get_pip',
                        lambda self, _id: deepcopy(source))
    with pytest.raises(Guard, match='pentest.recon'):
        derive_stage43_inputs(service, received, ref)
