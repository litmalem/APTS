from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from copy import deepcopy
import pytest
import execution_subsystem.adapter_policy as policy


@pytest.mark.parametrize('mission_budget,policy_budget,expected',[(20,20,20),(8,20,8),(20,6,6)])
def test_profile_limit_does_not_replace_lifetime_network_budget(monkeypatch,mission_budget,policy_budget,expected):
    monkeypatch.setattr(policy,'admission_policy',lambda *a:{'reason_codes':[],
        'human_review_required':False,'action_limits':{'mission':100,'pentest':100,'task':100}})
    monkeypatch.setattr(policy,'_wpt_reserved_requests',lambda *a:6)
    now=datetime(2026,11,6,tzinfo=timezone.utc)
    source={'constraints':{'resource_budget':{'max_network_requests':mission_budget}},'roe':{}}
    auth={'decision':'ALLOW','valid_until':(now+timedelta(minutes=5)).isoformat(),
        'policy_decision':{'constraints':{'max_requests':6,'max_network_requests':policy_budget}},
        'evaluation':{'execution_request':{},'current_context':{
            'mission_scope':deepcopy(source),'pentest_context':{'boundary':deepcopy(source),'task':deepcopy(source)}}}}
    adapter=SimpleNamespace(operation='WEB_PROFILE_FINGERPRINT',capability_id='web_technology_fingerprinting',
                            adapter_id='test-wpt')
    controls=policy.compile_runtime_policy(auth,adapter,now)
    assert controls['network_request_cost']==6
    assert controls['limits']['max_network_requests']==6
    assert controls['network_request_budget']==expected
