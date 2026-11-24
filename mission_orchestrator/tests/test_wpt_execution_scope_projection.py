from copy import deepcopy
import pytest
from mission_orchestrator.governance_binding import build_governance_scope_payload


def project(rules):
    capability = dict(capability_id='web_technology_fingerprinting',
        subject_component='PENTEST-SUB01', action_class='TARGET_RECON',
        action_name='web_technology_fingerprinting', authorization_mode='REQUIRED',
        resource_types=['URL'], max_risk_level='LOW', requires_human_approval=False,
        constraints={'max_requests':6}, source_allowlist=[])
    scope = dict(scope={'targets':[]}, roe={},
        identity=dict(mission_scope_contract_id='scope-one',contract_version=1,snapshot_id='snap-one'),
        integrity={'canonical_sha256':'a'*64},
        metadata={'gss_scope_sync':{'action_constraints':rules}})
    result=build_governance_scope_payload(mission_id='mission-one',
        scope_record={'contract':scope}, binding_request=dict(capabilities=[capability],
        metadata={},policy_set_id='default-policy',actor='test'),operation_id='op-one',request_sha256='b'*64)
    return [r for r in result['action_constraints'] if r['action_name']=='AUTHORIZE_TARGET_EXECUTION']


RULE=dict(action_class='TARGET_RECON',action_name='AUTHORIZE_TARGET_EXECUTION',
    effect='ALLOW',requires_approval=False,
    constraints={'allowed_techniques':['WEB_TECHNOLOGY_FINGERPRINT','TCP_CONNECT_SCAN'],
                 'max_network_requests':20})


def test_projects_exact_wpt_execution_route_without_other_techniques():
    rules=project([deepcopy(RULE)])
    assert len(rules)==1
    assert rules[0]['constraints']['allowed_techniques']==['WEB_TECHNOLOGY_FINGERPRINT']
    assert rules[0]['constraints']['max_network_requests']==20
    assert rules[0]['constraints']['max_requests']==6


@pytest.mark.parametrize('change',[{'effect':'DENY'}, {'effect':'REVIEW'},
    {'requires_approval':True}, {'constraints':{'allowed_techniques':['TCP_CONNECT_SCAN']}},
    {'constraints':{'allowed_techniques':['WEB_TECHNOLOGY_FINGERPRINT'],
                    'prohibited_techniques':['WEB_TECHNOLOGY_FINGERPRINT']}}])
def test_does_not_expand_source_permissions(change):
    assert project([{**deepcopy(RULE),**change}])==[]


def test_missing_source_permission_and_explicit_deny_fail_closed():
    assert project([])==[]
    assert project([deepcopy(RULE),{**deepcopy(RULE),'effect':'DENY'}])==[]
