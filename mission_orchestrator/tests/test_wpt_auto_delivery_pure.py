import json
import os
import pytest
from mission_orchestrator.mission_wpt_recon_delivery import _match_action
from mission_orchestrator.mission_wpt_cti_delivery import build_delivery, extract_technologies, publish


def test_recon_handoff_selects_one_declared_action_not_derived_iteration():
    context={'mission_id':'mission-gmo-one','task_id':'ptask-one',
             'orchestration_id':'orchestration-1',
             'target':{'target_type':'URL','target_value':'http://localhost:3000/'}}
    run={'mission_id':context['mission_id'],'orchestration_id':context['orchestration_id'],
         'parent_recon_run_id':None,
         'request':{'boundary':{'task_id':context['task_id']}},
         'output':{'action_requests':[
             {'action_id':'rareq-a','target_ref':context['target']},
             {'action_id':'rareq-b','target_ref':{'target_type':'URL','target_value':'https://other.test'}}]}}
    assert [x['action_id'] for x in _match_action(run,context)] == ['rareq-a']
    assert _match_action({**run,'parent_recon_run_id':'reconrun-parent'},context)==[]
    assert _match_action({**run,'mission_id':'mission-gmo-other'},context)==[]


def test_cti_build_requires_sealed_verified_recon_handoff():
    intake={'intake_id':'wptreq-one','mission_id':'mission-gmo-one','task_id':'ptask-one',
            'target':{'target_type':'URL','target_value':'http://localhost:3000/'}}
    result={'status':'VALIDATED_AND_STORED','evidence':{'capture_status':'SEALED','manifest_sha256':'a'*64},
            'integrity':{'canonical_sha256':'b'*64},
            'result':{'observation':{'technology_findings':[{'name':'nginx','version':'1.24'}]}}}
    handoff={'delivery_status':'DELIVERED','acknowledgement':{'accepted':True,
             'intake_id':'wptreq-one','source_result_sha256':'b'*64,'recon_run_id':'reconrun-one'}}
    delivery=build_delivery(intake,result,handoff)
    assert delivery['technologies']==[{'name':'nginx','version':'1.24'}]
    with pytest.raises(ValueError):
        build_delivery(intake,{**result,'status':'FAKE'},handoff)
    with pytest.raises(ValueError):
        build_delivery(intake,result,{**handoff,'delivery_status':'PENDING'})


def test_cti_publisher_never_sends_to_remote_url(monkeypatch):
    monkeypatch.setenv('APTS_WPT_CTI_SHARED_TOKEN','s'*48)
    monkeypatch.setenv('APTS_WPT_CTI_URL','http://example.org/api/cti/wpt/verified-enrich')
    assert publish({})=={'status':'deferred','reason':'CTI_ENDPOINT_MUST_BE_LOCAL'}
