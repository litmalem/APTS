from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import pytest
from mission_orchestrator.canonical import sha256_hex
from mission_orchestrator.pip_initialization import GATES, history
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.errors import MissionValidationError, MissionStateConflict, MissionIdempotencyConflict
from test_stage3_2_3_mission_pip_activation import mission_payload, lifecycle_request
from test_stage3_1_3_scope_roe_constraint_contract import contract_payload


class Cti:
    def __init__(self):
        self.pip = None
        self.calls = 0
    def get_pip(self, pip_id):
        self.calls += 1
        return deepcopy(self.pip)
    def build_pip(self, payload):
        self.built = deepcopy(payload)
        return {'status': 'completed', 'pip': deepcopy(self.pip)}


@pytest.fixture
def ready(tmp_path):
    repo = MissionRepository(driver='sqlite', sqlite_path=str(tmp_path/'missions.db'))
    cti = Cti()
    service = CanonicalMissionService(repo, cti_client=cti)
    create = mission_payload('two-phase', with_pip=False)
    mid = service.create_mission(create)['canonical_identity']['mission_id']
    scope = service.put_mission_scope_contract(mid, contract_payload())
    artifact = {'pip_id':'pip-test', 'revision':1, 'schema_version':'1.0-harmonized-2026-08',
                'mission_binding': {'mission_id':mid,'scope':scope['contract']['scope'],
                                    'mission_scope_sha256':scope['canonical_sha256'],
                                    'mission_scope_snapshot_id':scope['snapshot_id']},
                'semantics':{'execution_authorized':False,'execution_command':False},
                'intelligence':{}, 'quality':{'validator_version':'pip-validator-1.0'}}
    digest = sha256_hex(artifact)
    artifact['integrity'] = {'sha256':digest}
    cti.pip = {'pip_id':'pip-test','revision':1,'mission_id':mid,'immutable':True,
               'artifact':artifact,'canonical_sha256':digest,'readiness':'PARTIAL',
               'validation_results':[{'gate_id':g,'passed':True} for g in sorted(GATES)]}
    request = {'pip_id':'pip-test','pip_version':'1','expected_envelope_version':1,
               'idempotency_key':'init-1','actor':'tester','reason':'Initialize PIP'}
    return service, mid, cti, request, create


def test_append_activation_replay_restart_and_current_projection(ready):
    s, mid, cti, p, create = ready
    old = s.get_envelope(mid)['envelope']
    scope = s.get_mission_scope_contract(mid)
    vector = s.get_mission_version_vector(mid)['version_sha256']
    result = s.put_mission_pip_binding(mid, p)
    assert result['envelope_version'] == 2 and not result['execution_authorized']
    assert history(s.repository, mid)[0] == old
    assert s.get_mission_scope_contract(mid) == scope
    assert s.get_mission_state(mid)['mission_state']['state'] == 'CREATED'
    assert s.get_mission_activation_contract(mid)['mission_activation']['activation_ready']
    assert s.get_mission_version_vector(mid)['version_sha256'] != vector
    assert s.create_mission(create)['envelope'] == old
    assert s.list_missions()['mission_count'] == 1
    assert s.put_mission_pip_binding(mid, p)['idempotent_replay']
    restarted = CanonicalMissionService(MissionRepository(driver='sqlite',sqlite_path=s.repository.sqlite_path), cti_client=Cti())
    assert restarted.put_mission_pip_binding(mid,p)['idempotent_replay']
    events = s.repository.list_mission_events(mid)
    assert sum(e['event_type']=='MISSION_PIP_BOUND' for e in events)==1
    from mission_orchestrator.mission_events import verify_event
    assert all(verify_event(e) for e in events)
    s.execute_mission_lifecycle_command(mid, lifecycle_request(s,mid))
    assert s.get_mission_state(mid)['mission_state']['state']=='PIP_BOUND'
    assert s.put_mission_pip_binding(mid,p)['idempotent_replay']


@pytest.mark.parametrize('field,value', [('mission_id','wrong'),('revision',2),('immutable',False),
                                         ('readiness','REJECTED'),('canonical_sha256','0'*64),('validation_results',[])])
def test_rejects_bad_authority_records(ready,field,value):
    s,mid,cti,p,_=ready
    cti.pip[field]=value
    with pytest.raises(MissionValidationError): s.put_mission_pip_binding(mid,p)
    assert len(history(s.repository,mid))==1


@pytest.mark.parametrize('mutation', ['scope','snapshot','inner_mission','inner_version','bytes','gate','authority'])
def test_rejects_bad_artifact_and_gates(ready,mutation):
    s,mid,cti,p,_=ready
    a=cti.pip['artifact']
    if mutation=='scope': a['mission_binding']['scope']={}
    if mutation=='snapshot': a['mission_binding']['mission_scope_snapshot_id']='wrong'
    if mutation=='inner_mission': a['mission_binding']['mission_id']='wrong'
    if mutation=='inner_version': a['revision']=2
    if mutation=='bytes': a['intelligence']={'unexpected':'tampered'}
    if mutation=='gate': cti.pip['validation_results'][0]['passed']=False
    if mutation=='authority': a['semantics']['execution_authorized']=True
    with pytest.raises(MissionValidationError): s.put_mission_pip_binding(mid,p)
    assert len(history(s.repository,mid))==1


def test_stale_version_idempotency_and_rebinding(ready):
    s,mid,cti,p,_=ready
    with pytest.raises(MissionStateConflict): s.put_mission_pip_binding(mid,{**p,'expected_envelope_version':2})
    s.put_mission_pip_binding(mid,p)
    with pytest.raises(MissionIdempotencyConflict): s.put_mission_pip_binding(mid,{**p,'reason':'changed'})
    with pytest.raises(MissionStateConflict): s.put_mission_pip_binding(mid,{**p,'expected_envelope_version':2,'idempotency_key':'second'})


def test_cti_unavailable_is_non_mutating(ready):
    s,mid,cti,p,_=ready
    def fail(_): raise ConnectionError('offline')
    cti.get_pip=fail
    with pytest.raises(ConnectionError): s.put_mission_pip_binding(mid,p)
    assert len(history(s.repository,mid))==1


def test_scope_race_is_rejected_at_commit(ready):
    s,mid,cti,p,_=ready
    def race(_):
        s.put_mission_scope_contract(mid, contract_payload('new',1))
        return cti.pip
    cti.get_pip=race
    with pytest.raises(MissionStateConflict): s.put_mission_pip_binding(mid,p)
    assert len(history(s.repository,mid))==1


def test_audit_failure_rolls_back_envelope(ready):
    s,mid,cti,p,_=ready
    with s.repository._connect() as c:
        c.execute("CREATE TRIGGER reject_pip_event BEFORE INSERT ON mission_events WHEN NEW.event_type='MISSION_PIP_BOUND' BEGIN SELECT RAISE(ABORT,'test'); END")
    with pytest.raises(Exception,match='test'): s.put_mission_pip_binding(mid,p)
    assert len(history(s.repository,mid))==1


def test_concurrent_replay_has_one_successor(ready):
    s,mid,cti,p,_=ready
    other=CanonicalMissionService(MissionRepository(driver='sqlite',sqlite_path=s.repository.sqlite_path),cti_client=cti)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda svc:svc.put_mission_pip_binding(mid,p),[s,other]))
    assert sorted(r['idempotent_replay'] for r in results)==[False,True]
    assert len(history(s.repository,mid))==2


def test_build_uses_authoritative_scope_without_target_actions(ready):
    s,mid,cti,p,_=ready
    s.build_initialization_pip(mid,{'asset_profiles':[]})
    assert cti.built['mission_id']==mid
    assert cti.built['mission_binding']['scope']==s.get_mission_scope_contract(mid)['contract']['scope']
    with pytest.raises(MissionValidationError): s.build_initialization_pip(mid,{'mission_id':'forged'})


@pytest.mark.parametrize('field,value',[('expected_envelope_version',True),('pip_version','0'),('pip_id','../other'),('actor','')])
def test_input_validation(ready,field,value):
    s,mid,cti,p,_=ready
    with pytest.raises(MissionValidationError): s.put_mission_pip_binding(mid,{**p,field:value})
    assert cti.calls==0


def test_existing_governance_binding_preserved_and_planning_activates(ready):
    from test_stage3_1_4_governance_authorization_binding import FakeGovernanceClient, binding_payload
    from test_stage3_2_4_planning_run_activation import lifecycle_request as request_for
    s,mid,cti,p,_=ready
    s.governance_client=FakeGovernanceClient()
    # Reuse a capability compatible with the scope fixture.
    b=binding_payload();b['capabilities']=[{'capability_id':'pentest.recon','subject_component':'PENTEST-A01',
        'action_class':'TARGET_RECON','action_name':'recon','authorization_mode':'REQUIRED',
        'resource_types':['IP'],'max_risk_level':'LOW','requires_human_approval':False}]
    s.put_mission_governance_binding(mid,b)
    before=s.get_mission_governance_binding(mid)
    s.put_mission_pip_binding(mid,p)
    assert s.get_mission_governance_binding(mid)==before
    s.execute_mission_lifecycle_command(mid,request_for(s,mid,'BIND_PIP','pip-init'))
    s.execute_mission_lifecycle_command(mid,request_for(s,mid,'START_PLANNING','pip-plan'))
    assert s.get_mission_state(mid)['mission_state']['state']=='PLANNING'
    assert s.governance_client.evaluate_calls==0
