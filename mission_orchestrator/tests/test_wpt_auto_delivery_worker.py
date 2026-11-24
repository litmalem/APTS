"""Acceptance: Stage6-sealed evidence -> unique parent Recon -> authenticated CTI delivery.

No network traffic, active scan, synthetic authorization, or real database writes.
"""
from copy import deepcopy
import sqlite3
from mission_orchestrator.automatic_pip import sweep as pip_sweep
from mission_orchestrator.mission_running_automation import activate
from mission_orchestrator.mission_wpt_recon_delivery import deliver
from test_gss_scope_sync import gss_ready  # noqa: F401
from test_two_phase_pip_initialization import ready  # noqa: F401


class Pentest:
    def __init__(self, tmp_path, mission_id):
        self.path = str(tmp_path / 'tasks.db')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE pentest_tasks(mission_id TEXT,upstream_task_id TEXT)')
            db.execute('INSERT INTO pentest_tasks VALUES (?,?)',(mission_id,'ptask-synthetic'))
    def _connect(self):
        result=sqlite3.connect(self.path)
        result.row_factory=sqlite3.Row
        return result
    def _migration(self, conn):
        return 16


class WPT:
    def __init__(self, mid):
        intake={'mission_id':mid,'task_id':'ptask-synthetic','intake_id':'wptreq-test',
                'target':{'target_type':'URL','target_value':'http://localhost:3000/'}}
        self.intake=intake
        self.record={'status':'VALIDATED_AND_STORED', 'evidence':{'capture_status':'SEALED',
                     'manifest_sha256':'a'*64}, 'integrity':{'canonical_sha256':'b'*64},
                     'result':{'observation':{'technology_findings':[{'name':'nginx','version':'1.24'}]}}}
        self.handoff=None
        self.calls=[]
    def list_for_task(self, mid, task):
        return [{'record':{'intake':self.intake,
                 'authority_snapshot':{'orchestration_id':'pentorch-test'}},
                 'stage6_result':{'record':self.record}}]
    def get_handoff(self, intake_id):
        return deepcopy(self.handoff)
    def handoff_to_recon(self, intake_id, request):
        self.calls.append(deepcopy(request))
        self.handoff={'delivery_status':'DELIVERED','acknowledgement':{'accepted':True,
            'intake_id':intake_id,'recon_run_id':'reconrun-child','source_result_sha256':'b'*64}}
        return {'status':'delivered', 'created':True, **deepcopy(self.handoff)}


class Recon:
    def __init__(self, mid, count=1):
        parent={'mission_id':mid,'orchestration_id':'pentorch-test','recon_run_id':'reconrun-parent',
                'parent_recon_run_id':None, 'request':{'boundary':{'task_id':'ptask-synthetic'}},
                'output':{'action_requests':[{'action_id':'rareq-fingerprint',
                    'target_ref':{'target_type':'URL','target_value':'http://localhost:3000/'}}]}}
        self.runs=[deepcopy(parent) for _ in range(count)]
    def list_recon_runs(self,*,mission_id,limit):
        assert limit==500
        return self.runs


def test_sealed_evidence_delivery_and_cti_replay(gss_ready, tmp_path, monkeypatch):
    service, mid, _, _ = gss_ready
    monkeypatch.setenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', '0')
    pip_sweep(service)
    activate(service,mid)
    pentest=Pentest(tmp_path,mid)
    wpt=WPT(mid)
    recon=Recon(mid)
    monkeypatch.setenv('APTS_AUTONOMOUS_WPT_CTI_DELIVERY','1')
    import mission_orchestrator.mission_wpt_cti_delivery as module
    dispatched=[]
    def send(pkg):
        dispatched.append(pkg)
        return {'status':'delivered', 'intake_id':pkg['wpt_intake_id']}
    monkeypatch.setattr(module,'publish',send)
    first=deliver(service,mid,wpt=wpt,recon=recon,pentest=pentest)
    assert first[0]['status']=='delivered'
    assert first[0]['execution_authorized_by_handoff'] is False
    assert wpt.calls[0]['parent_recon_run_id']=='reconrun-parent'
    assert dispatched[0]['source_result_sha256']=='b'*64
    assert dispatched[0]['technologies']==[{'name':'nginx','version':'1.24'}]
    repeated=deliver(service,mid,wpt=wpt,recon=recon,pentest=pentest)
    assert repeated[0]['replayed'] is True
    assert len(wpt.calls)==1  # durable handoff is not recreated


def test_ambiguous_recon_cannot_receive_wpt(gss_ready,tmp_path,monkeypatch):
    service,mid,_,_=gss_ready
    monkeypatch.setenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', '0')
    pip_sweep(service);activate(service,mid)
    wpt=WPT(mid)
    results=deliver(service,mid,wpt=wpt,recon=Recon(mid,count=2),pentest=Pentest(tmp_path,mid))
    assert results[0]['reason']=='RECON_PARENT_ACTION_NOT_UNIQUE'
    assert not wpt.calls


def test_first_observation_and_receipt_retry_without_redelivery(gss_ready,tmp_path,monkeypatch):
    service,mid,_,_=gss_ready
    monkeypatch.setenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', '0')
    pip_sweep(service);activate(service,mid)
    import mission_orchestrator.mission_wpt_recon_delivery as module
    receipts=[]
    def receipt(*args):
        receipts.append(args)
        return 'PENDING' if len(receipts)==1 else 'DELIVERED'
    monkeypatch.setattr(module,'_receipt',receipt)
    wpt=WPT(mid)
    pentest=Pentest(tmp_path,mid)
    first=deliver(service,mid,wpt=wpt,recon=Recon(mid,count=0),pentest=pentest)
    assert wpt.calls==[{'schema_version':'apts-wpt-recon-initial-request-v1'}]
    assert first[0]['wpt_receipt_status']=='PENDING'
    repeated=deliver(service,mid,wpt=wpt,recon=Recon(mid,count=0),pentest=pentest)
    assert repeated[0]['wpt_receipt_status']=='DELIVERED'
    assert len(wpt.calls)==1
