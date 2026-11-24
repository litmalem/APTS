import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = HERE if (HERE / 'execution_subsystem').exists() else HERE.parent / 'mission'
MISSION = PROJECT_ROOT
for parent in (HERE, HERE / 'run', PROJECT_ROOT):
    if str(parent) in sys.path:
        sys.path.remove(str(parent))
    sys.path.insert(0, str(parent))
from recon_collector_bridge import BridgeError, run_bridge, require_loopback
from execution_subsystem.execution_contract import with_integrity
from execution_subsystem.execution_result_contract import RESULT_DOMAIN

MID = 'mission-gmo-mock-1'
RID = 'reconrun-mock-1'
AID = 'rareq-mock-1'
ORCH = 'paorch-mock-1'
TARGET = 'http://localhost:3000/'
SHA = 'a' * 64


def fixture_result(*, sealed=True, status='SUCCEEDED'):
    core = {'schema_version':'apts-recon-execution-result-v1', 'action_id':AID,'proposal_ref':'actp-mock-1','mission_id':MID,'orchestration_id':ORCH,
            'execution_id':'exec-mock-1','attempt_id':'xattempt-mock-1','terminal':True,
            'runtime_state':status,'execution_result':{'status':status},
            'evidence':{'capture_status':'SEALED' if sealed else 'PARTIAL','manifest_sha256':SHA},
            'semantics':{'result_is_authorization':False,'result_is_vulnerability_finding':False,
                         'result_is_vep':False,'target_state_measurement_performed':False,'raw_target_bytes_returned':False}}
    return with_integrity(core, RESULT_DOMAIN)


class Fake:
    def __init__(self, side, *, previous=None, gateway=True, scope=True, result=None):
        self.side, self.previous,self.gateway,self.scope,self.result=side,previous,gateway,scope,result
        self.writes=[]
        self.polls=0

    def get(self, path, *, allow_not_found=False):
        if path=='/health':return {'status':'ok'}
        if path=='/api/contracts/recon-execution-result':return {'status':'declared'}
        if path.endswith('/validate-stage6-intake'):
            return {'validation':{'status':'VALIDATED_AWAITING_GSS' if self.scope else 'DENIED',
                 'target_scope_verified':self.scope,'action_id':AID,'recon_run_id':RID}}
        if path.endswith(RID):
            return {'run':{'mission_id':MID,'run_status':'COMPLETED','orchestration_id':ORCH,
                 'output':{'action_requests':[{'action_id':AID,'proposal_ref':'actp-mock-1','mission_id':MID,
                 'orchestration_id':ORCH,'recon_run_id':RID,'technique':'TCP_CONNECT_SCAN',
                 'capability_id':'reconnaissance','target_ref':{'target_value':TARGET},
                 'integrity':{'canonical_sha256':SHA}}]}}}
        if path.endswith('/results'):
            self.polls+=1
            current=self.previous if self.polls==1 else self.result
            if current is None:
                return None
            return {'results':[current],'latest_result':current}
        raise AssertionError('unexpected GET ' + path)

    def post(self, path, payload):
        self.writes.append((path,payload))
        if path=='/api/execution/requests':
            return {'created':True,'execution_id':'exec-mock-1',
                'envelope':{'integrity':{'canonical_sha256':SHA},'execution_request':{
                'mission_id':MID,'parameters':{'source_action_id':AID},
                'target':{'target_value':TARGET},'action':{
                'action_class':'TARGET_RECON','capability_id':'reconnaissance','technique':'TCP_CONNECT_SCAN'}}}}
        if path=='/api/execution/gateway/submissions':
            return {'created':True,'gateway_admitted':self.gateway,'governance_query_performed':True}
        if path=='/api/execution/runtime/attempts':
            return {'created':True,'attempt_id':'xattempt-mock-1'}
        if path.endswith('/reconnaissance/iterations'):
            return {'created':True,'status':'completed','run':{
                'recon_run_id':'reconrun-child-1','mission_id':MID,'source_action_id':AID,
                'source_result_sha256':self.result['integrity']['canonical_sha256'],
                'parent_recon_run_id':RID}}
        raise AssertionError('unexpected POST ' + path)


def drive(pentest, stage6, execute=True):
    return run_bridge(pentest,stage6,mission_id=MID,run_id=RID,action_id=AID,
        expected_target=TARGET,operator='operator-admin-01',execute=execute,
        poll_timeout=3,poll_interval=0,sleep=lambda _:None,log=lambda _:None)


def test_full_authorized_dispatch_evidence_iteration():
    result=fixture_result();p=Fake('pentest',result=result);s=Fake('stage6',result=result)
    report=drive(p,s)
    assert report['status']=='COMPLETED'
    assert report['child_recon_run_id']=='reconrun-child-1'
    assert [x[0] for x in s.writes]==['/api/execution/requests',
        '/api/execution/gateway/submissions','/api/execution/runtime/attempts']
    assert len(p.writes)==1
    assert s.writes[-1][1]['schema_version']=='apts-execution-runtime-start-v1'


def test_preflight_never_submits():
    p=Fake('pentest');s=Fake('stage6')
    assert drive(p,s,execute=False)['status']=='PREFLIGHT_ONLY'
    assert not p.writes and not s.writes


def test_denied_gateway_never_runs_tool_or_iteration():
    p=Fake('pentest');s=Fake('stage6',gateway=False)
    with pytest.raises(BridgeError,match='Gateway'):
        drive(p,s)
    assert len(s.writes)==2 and not p.writes


def test_scope_denied_never_calls_execution():
    p=Fake('pentest',scope=False);s=Fake('stage6')
    with pytest.raises(BridgeError,match='scope/RoE'):
        drive(p,s)
    assert not s.writes


def test_unsealed_evidence_never_reaches_iteration():
    result=fixture_result(sealed=False)
    p=Fake('pentest',result=result);s=Fake('stage6',result=result)
    with pytest.raises(BridgeError,match='SEALED'):
        drive(p,s)
    assert not p.writes


def test_terminal_failure_never_reaches_iteration():
    result=fixture_result(status='FAILED')
    p=Fake('pentest',result=result);s=Fake('stage6',result=result)
    with pytest.raises(BridgeError,match='failed'):
        drive(p,s)
    assert not p.writes


def test_existing_sealed_result_is_resumed_without_dispatch():
    result=fixture_result();p=Fake('pentest',result=result);s=Fake('stage6',previous=result,result=result)
    assert drive(p,s)['status']=='COMPLETED'
    assert not s.writes and len(p.writes)==1


def test_mismatched_target_never_touches_execution():
    p=Fake('pentest');s=Fake('stage6')
    with pytest.raises(BridgeError,match='target'):
        run_bridge(p,s,mission_id=MID,run_id=RID,action_id=AID,expected_target='http://localhost:9999/',
                   operator='op',execute=True,log=lambda _:None)
    assert not s.writes


def test_tampered_result_rejected():
    result=fixture_result()
    result['evidence']['manifest_sha256']='b'*64
    p=Fake('pentest',result=result);s=Fake('stage6',previous=result,result=result)
    with pytest.raises(BridgeError,match='integrity'):
        drive(p,s)
    assert not s.writes and not p.writes


@pytest.mark.parametrize('bad',["http://example.com",'https://127.0.0.1:8791','http://127.0.0.1:8791/path',
                              'http://user:pw@127.0.0.1:8791','http://0.0.0.0:8791'])
def test_control_endpoints_loopback_only(bad):
    with pytest.raises(BridgeError):
        require_loopback(bad)
