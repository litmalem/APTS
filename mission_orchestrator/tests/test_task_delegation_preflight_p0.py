"""P0 checks for read-only scope readiness and safe admin-authored allowlists."""
from datetime import datetime, timedelta, timezone
import re

import pytest
from pydantic import ValidationError

from app.delegation_preflight import inspect_delegation_scope, allow_rule_problems
from app.models import ScopeContractCreate
from tests.test_task_delegation_governance import FakeRepo, request, service
from gss_web.server import GET_PATH

CAP = 'PENTEST:pentest.recon'


def test_readiness_is_read_only_and_never_mints_authorization():
    repo = FakeRepo()
    result = inspect_delegation_scope(service(repo), 'scope-delegation')
    assert result['ready'] is True
    assert result['status'] == 'READY_SCOPE_CONFIGURATION'
    assert result['decision_issued'] is False
    assert result['delegation_authorized'] is False
    assert result['execution_authorized'] is False
    assert result['mission_binding_verified'] is False
    assert repo.authorization_requests == {}
    assert repo.decisions == {}


def test_readiness_fails_closed_for_missing_capability_and_legacy_rule():
    repo = FakeRepo()
    repo.constraint['constraints']['allowed_capabilities'] = ['PENTEST:pentest.other']
    result = inspect_delegation_scope(service(repo), 'scope-delegation')
    assert not result['ready']
    assert 'SUBSYSTEM_CAPABILITY_NOT_ALLOWLISTED' in result['reason_codes']


def test_readiness_blocks_expiry_policy_emergency():
    repo = FakeRepo(emergency=True)
    repo.scope['valid_until'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    repo.policy['status'] = 'RETIRED'
    result = inspect_delegation_scope(service(repo), 'scope-delegation')
    assert {'NO_ACTIVE_SCOPE_CONTRACT','NO_ACTIVE_POLICY_SET','EMERGENCY_STOP_ACTIVE'} <= set(result['reason_codes'])


def test_readiness_requires_exact_action_not_wildcard():
    repo = FakeRepo()
    repo.constraint['action_name'] = '*'
    result = inspect_delegation_scope(service(repo), 'scope-delegation')
    assert 'DELEGATION_ACTION_NAME_NOT_EXACT' in result['reason_codes']


def test_bad_legacy_permissions_are_denied_during_actual_authorization():
    repo = FakeRepo()
    repo.constraint['constraints']['execution_authorized'] = True
    outcome = service(repo).evaluate_authorization(request())
    assert outcome['decision'] == 'DENY'
    assert 'DELEGATION_EXECUTION_AUTHORITY_MUST_BE_FALSE' in outcome['reason_codes']


def test_config_refuses_unscoped_allowlist_and_actuation():
    valid = {'mission_id':'m','name':'test','created_by':'operator','action_constraints':[
        {'action_class':'TASK_DELEGATION','action_name':'delegate_planned_task','effect':'ALLOW','max_risk_level':'LOW',
         'constraints':{'allowed_capabilities':[CAP], 'execution_authorized':False,'target_actuation':False}}]}
    assert ScopeContractCreate.model_validate(valid)
    bad_cases = [
        {'allowed_capabilities':[], 'execution_authorized':False,'target_actuation':False},
        {'allowed_capabilities':['PENTEST:*'], 'execution_authorized':False,'target_actuation':False},
        {'allowed_capabilities':[CAP], 'execution_authorized':True,'target_actuation':False},
        {'allowed_capabilities':[CAP], 'execution_authorized':False,'target_actuation':True},
        {'allowed_capabilities':[CAP], 'execution_authorized':False},
    ]
    for constraints in bad_cases:
        with pytest.raises(ValidationError):
            ScopeContractCreate.model_validate({**valid,'action_constraints':[{**valid['action_constraints'][0], 'constraints':constraints}]})
    for key,value in [('action_name','*'),('max_risk_level','CRITICAL')]:
        with pytest.raises(ValidationError):
            ScopeContractCreate.model_validate({**valid,'action_constraints':[{**valid['action_constraints'][0],key:value}]})


def test_preflight_route_is_bff_allowlisted():
    assert GET_PATH.fullmatch('/api/governance/console/scopes/scope-abc/delegation-readiness')
    assert not GET_PATH.fullmatch('/api/governance/console/scopes/../../secret/delegation-readiness')


def test_revalidation_rejects_later_corrupted_allowlist_flags():
    from app.models import ActionClass, PolicyDecisionRevalidationRequest
    repo = FakeRepo()
    gov = service(repo)
    issued = gov.evaluate_authorization(request())
    assert issued['decision'] == 'ALLOW'
    repo.constraint['constraints']['target_actuation'] = True
    result = gov.revalidate_policy_decision(PolicyDecisionRevalidationRequest(
        decision_id=issued['decision_id'], request_id=issued['request_id'],
        mission_id='mission-delegation', scope_contract_id='scope-delegation',
        scope_version=1, policy_set_id='default-policy', policy_version=1,
        decision_hash=issued['decision_hash'], subject_component='APTS-MO01',
        action_class=ActionClass.TASK_DELEGATION, action_name='delegate_planned_task',
        resource_type='SUBSYSTEM_CAPABILITY', resource_value=CAP,
        requested_by='operator-test'))
    assert result['valid'] is False
    assert result['delegation_authorized'] is False
    assert 'CURRENT_DELEGATION_TARGET_ACTUATION_MUST_BE_FALSE' in result['reason_codes']


def test_authenticated_read_only_console_endpoint(monkeypatch, tmp_path):
    import hashlib
    import json
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app import main, approval_auth
    from app.approval_auth import REGISTRY_SCHEMA
    token = 'v' * 48
    registry = tmp_path / 'principals.json'
    registry.write_text(json.dumps({'schema_version':REGISTRY_SCHEMA,'principals':[
        {'principal_id':'scope-auditor','principal_type':'HUMAN','roles':['VIEWER'],
         'token_sha256':hashlib.sha256(token.encode()).hexdigest(),'enabled':True}]}))
    repo = FakeRepo()
    monkeypatch.setattr(main, 'service', service(repo))
    monkeypatch.setattr(approval_auth, 'settings', replace(approval_auth.settings,approval_principals_file=str(registry)))
    client = TestClient(main.app)
    url = '/api/governance/console/scopes/scope-delegation/delegation-readiness'
    assert client.get(url).status_code == 401
    response = client.get(url,headers={'Authorization':'Bearer '+token})
    assert response.status_code == 200, response.text
    assert response.json()['ready'] is True
    assert client.get(url.replace('scope-delegation','no-such-scope'),headers={'Authorization':'Bearer '+token}).status_code == 404
    assert repo.authorization_requests == {}
    assert repo.decisions == {}
