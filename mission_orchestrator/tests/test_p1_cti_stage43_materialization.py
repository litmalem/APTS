"""P1 integration: genuine CTI data, existing GSS authorization, no target I/O."""
from copy import deepcopy
from datetime import datetime, timezone
import pytest
from unittest.mock import Mock

from mission_orchestrator.cti_stage43_bridge import derive_stage43_inputs, _hash_source_artifact
from mission_orchestrator.pentest_handoff import handoff_to_pentest
from mission_orchestrator.errors import MissionTaskDelegationGuardRejected as Guard, MissionValidationError
from tests.test_mission_pentest_handoff import ready, stage43_inputs
from pentest_subsystem.mission_handoff import PentestHandoffInbox
from pentest_subsystem.web_ui import list_orchestration_options
from pentest_subsystem.agentic_pentest_acceptance_service import AgenticPentestAcceptanceService
from pentest_subsystem.governance_bound_e2e import GovernanceBoundE2ERepository


def cti_source(mission, target):
    created = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    checks = [{'gate_id': 'QG-H'+str(i), 'passed': True} for i in range(1, 11)]
    artifact = {
        'schema_version': '1.0-harmonized-2026-08',
        'pip_id': 'pip-cti-real-bridge', 'revision': 2, 'created_at': created,
        'mission_binding': {'mission_id': mission, 'target_url': target['target_value']},
        'intelligence': {'asset_profiles': [{'asset_id': 'juice-shop', 'confidence': 0.91, 'target_url': target['target_value']}]},
        'validation_objectives': [], 'assumptions_and_gaps': [], 'policy_context': {},
        'semantics': {'execution_authorized': False, 'execution_command': False},
        'quality': {'readiness': 'ACTIONABLE', 'hard_gate_passed': True, 'validation_results': checks,
                    'redacted_secret_paths': [], 'validator_version': 'pip-validator-1.0'},
    }
    digest = _hash_source_artifact(artifact)
    artifact['integrity'] = {'algorithm': 'SHA-256', 'canonicalization': 'JSON_SORT_KEYS_COMPACT_UTF8',
                             'sha256': digest, 'signature': None}
    return {'pip_id': artifact['pip_id'], 'mission_id': mission, 'revision': 2, 'schema_version': artifact['schema_version'],
            'canonical_sha256': digest, 'readiness': 'ACTIONABLE', 'immutable': True,
            'artifact': artifact, 'validation_results': checks}


def setup(ready, monkeypatch):
    service, gov, mission, inbox, payload = ready
    first = handoff_to_pentest(service, mission, payload, inbox)
    received = inbox.get(first['handoff_id'])
    target = received['envelope']['work_context']['scope']['targets'][0]
    source = cti_source(mission, target)
    existing = stage43_inputs(service, gov, received)
    # Reuse the fake GSS decision only. It is NOT allowed to be supplied by the CTI adapter.
    revalidate = gov.revalidate_policy_decision
    def valid(body):
        value = revalidate(body)
        if body['action_class'] == 'TARGET_RECON':
            value['execution_authorized'] = True
        return value
    monkeypatch.setattr(gov, 'revalidate_policy_decision', valid)
    monkeypatch.setattr('mission_orchestrator.cti_stage43_bridge.CtiSubsystemClient.get_pip',
                        lambda self, _id: deepcopy(source))
    ref = {'pip_id': source['pip_id'], 'policy_decision_id': existing['authorization_reference']['policy_decision_id']}
    return service, gov, mission, inbox, payload, source, ref


def test_cti_to_pentest_stage43_end_to_end(ready, monkeypatch):
    service, gov, mission, inbox, payload, source, ref = setup(ready, monkeypatch)
    result = handoff_to_pentest(service, mission, {**payload, 'stage43_cti': ref}, inbox)
    assert result['stage43_materialized'] is True
    assert result['pentest_task']['created'] is True
    assert result['execution_authorized'] is False and result['target_actuation'] is False
    pentest = AgenticPentestAcceptanceService(GovernanceBoundE2ERepository(inbox.path))
    options = list_orchestration_options(pentest)
    assert len(options['pending_tasks']) == 1 and options['pending_handoffs'] == []
    assert options['tool_invocation_performed'] is False
    again = handoff_to_pentest(service, mission, {**payload, 'stage43_cti': ref}, inbox)
    assert again['pentest_task']['created'] is False
    assert len(pentest.list_tasks()) == 1


@pytest.mark.parametrize('tamper', [
    lambda x: x.update(canonical_sha256='0'*64),
    lambda x: x.update(readiness='PARTIAL'),
    lambda x: x['artifact']['mission_binding'].update(target_url='http://other.test/'),
    lambda x: x['artifact']['semantics'].update(execution_authorized=True),
    lambda x: x['artifact']['quality'].update(hard_gate_passed=False),
    lambda x: x.update(mission_id='mission-gmo-other'),
    lambda x: x['artifact']['intelligence']['asset_profiles'][0].pop('confidence'),
    lambda x: x['artifact'].update(created_at='2022-01-01T00:00:00Z'),
])
def test_cti_tampering_fails_closed(ready, monkeypatch, tamper):
    service, gov, mission, inbox, payload, source, ref = setup(ready, monkeypatch)
    tamper(source)
    monkeypatch.setattr('mission_orchestrator.cti_stage43_bridge.CtiSubsystemClient.get_pip',
                        lambda self, _id: deepcopy(source))
    with pytest.raises(Guard):
        handoff_to_pentest(service, mission, {**payload, 'stage43_cti': ref}, inbox)
    pentest = AgenticPentestAcceptanceService(GovernanceBoundE2ERepository(inbox.path))
    assert pentest.list_tasks() == []


def test_missing_authorization_never_materializes(ready, monkeypatch):
    service, gov, mission, inbox, payload, source, ref = setup(ready, monkeypatch)
    ref['policy_decision_id'] = 'decision-nonexistent'
    with pytest.raises(Guard, match='decision'):
        handoff_to_pentest(service, mission, {**payload, 'stage43_cti': ref}, inbox)
    assert AgenticPentestAcceptanceService(GovernanceBoundE2ERepository(inbox.path)).list_tasks() == []


def test_non_explicit_reference_rejected(ready, monkeypatch):
    service, gov, mission, inbox, payload, source, ref = setup(ready, monkeypatch)
    with pytest.raises(Guard):
        handoff_to_pentest(service, mission, {**payload, 'stage43_cti': {**ref, 'execution_authorized': True}}, inbox)
    with pytest.raises(MissionValidationError):
        handoff_to_pentest(service, mission, {**payload, 'stage43_cti': ref, 'stage43_inputs': {}}, inbox)
