from copy import deepcopy
from datetime import datetime, timezone, timedelta
import pytest
from test_two_phase_pip_initialization import ready
from test_stage3_2_3_mission_pip_activation import mission_payload
from mission_orchestrator.gss_scope_sync import fetch, synchronize, KEY
from mission_orchestrator.canonical import sha256_hex
from mission_orchestrator.errors import MissionValidationError


class Gss:
    def __init__(self, mid):
        now = datetime.now(timezone.utc)
        self.scope = {'scope_contract_id': 'scope-gss-test', 'mission_id': mid, 'version': 1,
            'contract_hash': 'a'*64, 'status': 'ACTIVE', 'policy_set_id': 'default-policy',
            'valid_from': (now-timedelta(hours=1)).isoformat(),
            'valid_until': (now+timedelta(days=2)).isoformat(),
            'targets': [{'target_type':'URL','target_value':'http://localhost:3000/',
                         'environment':'LAB','allowed':1}], 'sources':[], 'action_constraints':[]}
        self.event_hash = 'a'*64
    def get_scope_contract(self, sid):
        assert sid == self.scope['scope_contract_id']
        return deepcopy(self.scope)
    def mission_correlation_snapshot(self, mid):
        return {'mission_id': mid, 'authority': 'aptsGSS', 'scope_contracts': [deepcopy(self.scope)],
                'events': [{'event_type':'SCOPE_CHANGED','payload':{
                    'scope_contract_id': self.scope['scope_contract_id'], 'scope_version': self.scope['version'],
                    'contract_hash': self.event_hash}}]}


@pytest.fixture
def gss_ready(ready, tmp_path, monkeypatch):
    # Planning can publish a durable Recon scope projection. Keep that write
    # inside pytest's temporary workspace instead of the operator's Pentest DB.
    monkeypatch.setenv('APTS_PENTEST_DB', str(tmp_path / 'pentest.db'))
    s, _, cti, _, _ = ready
    mid = s.create_mission(mission_payload('gss-new', with_pip=False))['canonical_identity']['mission_id']
    s.governance_client = gss = Gss(mid)
    def build(body):
        artifact = {'pip_id':'pip-sync', 'revision':1, 'mission_binding':deepcopy(body['mission_binding']),
                    'semantics':{'execution_authorized':False,'execution_command':False},
                    'intelligence':{}, 'quality':{'validator_version':'pip-validator-1.0'}}
        artifact['mission_binding']['mission_id'] = mid
        digest = sha256_hex(artifact)
        artifact['integrity'] = {'sha256': digest}
        cti.pip.update(pip_id='pip-sync',mission_id=mid,artifact=artifact,canonical_sha256=digest)
        cti.built = deepcopy(body)
        return {'status':'completed','pip':deepcopy(cti.pip)}
    cti.build_pip = build
    return s, mid, gss, cti


def test_gss_to_scope_to_pip_bound(gss_ready):
    s, mid, gss, cti = gss_ready
    assert s.initialize_mission_pip_automatically(mid)['state'] == 'PIP_BOUND'
    scope = s.get_mission_scope_contract(mid)
    metadata = scope['contract']['metadata'][KEY]
    assert metadata['source_scope_contract_id'] == gss.scope['scope_contract_id']
    assert metadata['source_version'] == 1
    assert metadata['source_contract_hash'] == gss.scope['contract_hash']
    assert metadata['source_snapshot'] == gss.scope
    assert metadata['source_snapshot_sha256'] == sha256_hex(gss.scope)
    assert metadata['action_constraints'] == []
    assert metadata['projection_mode'] == 'BOOTSTRAP_NO_ACTION_PERMISSIONS'
    assert scope['contract']['roe']['allowed_action_classes'] == []
    assert not scope['contract']['roe']['credential_usage_allowed']
    assert cti.built['mission_binding']['scope'] == scope['contract']['scope']
    count = scope['contract_version']
    assert s.initialize_mission_pip_automatically(mid)['status'] == 'unchanged'
    assert s.get_mission_scope_contract(mid)['contract_version'] == count


def test_gss_scope_without_expiry_keeps_mission_duration_bound(gss_ready):
    service, mid, gss, _ = gss_ready
    gss.scope['valid_until'] = None
    scope = synchronize(service, mid)['contract']
    assert scope['roe']['allowed_time_window'] is None
    assert scope['constraints']['max_duration'] > 0
    assert scope['metadata'][KEY]['source_snapshot']['valid_until'] is None


@pytest.mark.parametrize('mutation', ['mission','revoked','expired','future','hash','version','empty_targets'])
def test_invalid_source_never_bound(gss_ready, mutation):
    s, mid, gss, cti = gss_ready
    if mutation == 'mission': gss.scope['mission_id'] = 'wrong'
    if mutation == 'revoked': gss.scope['status'] = 'REVOKED'
    if mutation == 'expired': gss.scope['valid_until'] = '2020-01-01T00:00:00Z'
    if mutation == 'future': gss.scope['valid_from'] = '2099-01-01T00:00:00Z'
    if mutation == 'hash': gss.event_hash = 'b'*64
    if mutation == 'version': gss.scope['version'] = 0
    if mutation == 'empty_targets': gss.scope['targets'] = []
    with pytest.raises(MissionValidationError): s.initialize_mission_pip_automatically(mid)
    assert s.repository.get_state(mid)['state'] == 'CREATED'
    assert not s.get_envelope(mid)['envelope']['bindings']['pip']['pip_id']


def test_ambiguous_contracts_rejected(gss_ready):
    s, mid, gss, _ = gss_ready
    original = gss.mission_correlation_snapshot
    def duplicate(mid):
        data = original(mid)
        data['scope_contracts'] *= 2
        return data
    gss.mission_correlation_snapshot = duplicate
    with pytest.raises(MissionValidationError): fetch(s, mid)


def test_mission_binding_scope_is_not_counted_as_operator_source_scope(gss_ready):
    s, mid, gss, _ = gss_ready
    original = gss.mission_correlation_snapshot
    def with_binding_scope(mission_id):
        data = original(mission_id)
        generated = deepcopy(gss.scope)
        generated['scope_contract_id'] = 'scope-mission-binding'
        generated['metadata'] = {'mission_orchestrator_binding_operation_id':'mgbind-op-test'}
        data['scope_contracts'].append(generated)
        return data
    gss.mission_correlation_snapshot = with_binding_scope
    assert fetch(s, mid)['scope_contract_id'] == gss.scope['scope_contract_id']


def test_source_action_constraints_project_without_execution_authority(gss_ready):
    s, mid, gss, _ = gss_ready
    gss.scope['action_constraints'] = [{'action_class':'TARGET_RECON','effect':'ALLOW','constraints':{'x':1}}]
    # Isolate synchronization from automatic initialization triggered by scope commit.
    s._automatic_pip_active = {mid}
    scope = synchronize(s, mid)
    assert scope['contract']['metadata'][KEY]['action_constraints'] == gss.scope['action_constraints']
    assert scope['contract']['roe']['allowed_action_classes'] == ['TARGET_RECON']
    assert scope['contract']['roe']['prohibited_action_classes'] == []
    metadata = scope['contract']['metadata'][KEY]
    assert metadata['projected_allowed_action_classes'] == ['TARGET_RECON']
    assert metadata['projection_mode'] == 'GSS_EXPLICIT_ACTION_CONSTRAINTS'
    assert scope['contract']['constraints']['data_handling_policy']['execution_authorized'] is False


def test_review_rule_requires_approval_and_control_plane_rule_is_not_target_roe(gss_ready):
    s, mid, gss, _ = gss_ready
    gss.scope['action_constraints'] = [
        {'action_class':'TARGET_RECON','effect':'REVIEW','requires_approval':True},
        {'action_class':'TASK_DELEGATION','effect':'ALLOW','requires_approval':False},
    ]
    s._automatic_pip_active = {mid}
    scope = synchronize(s, mid)
    roe = scope['contract']['roe']
    assert roe['allowed_action_classes'] == ['TARGET_RECON']
    assert roe['human_approval_required_for'] == ['TARGET_RECON']
    assert 'TASK_DELEGATION' not in roe['allowed_action_classes']
    assert scope['contract']['metadata'][KEY]['action_constraints'] == gss.scope['action_constraints']


@pytest.mark.parametrize(('wire_value', 'expected'), [
    (True, True), (False, False), (1, True), (0, False),
    ('true', True), ('false', False),
])
def test_requires_approval_normalizes_supported_json_encodings(wire_value, expected):
    from mission_orchestrator.gss_scope_sync import _project_action_constraints
    allowed, prohibited, approval_required = _project_action_constraints({
        'action_constraints': [{'action_class': 'TARGET_RECON', 'effect': 'ALLOW',
                               'requires_approval': wire_value}]
    })
    assert allowed == ['TARGET_RECON']
    assert prohibited == []
    assert ('TARGET_RECON' in approval_required) is expected


def test_requires_approval_rejects_ambiguous_encodings():
    from mission_orchestrator.gss_scope_sync import _project_action_constraints
    with pytest.raises(MissionValidationError, match='requires_approval must be boolean'):
        _project_action_constraints({'action_constraints': [
            {'action_class': 'TARGET_RECON', 'effect': 'ALLOW', 'requires_approval': 'yes'}
        ]})


def test_deny_takes_precedence_for_action_class(gss_ready):
    s, mid, gss, _ = gss_ready
    gss.scope['action_constraints'] = [
        {'action_class':'TARGET_RECON','action_name':'recon','effect':'ALLOW'},
        {'action_class':'TARGET_RECON','action_name':'*','effect':'DENY'},
    ]
    s._automatic_pip_active = {mid}
    scope = synchronize(s, mid)
    roe = scope['contract']['roe']
    assert roe['allowed_action_classes'] == []
    assert roe['prohibited_action_classes'] == ['TARGET_RECON']


def test_unknown_action_class_allow_fails_closed(gss_ready):
    s, mid, gss, _ = gss_ready
    gss.scope['action_constraints'] = [
        {'action_class':'UNKNOWN_TARGET_ACTION','effect':'ALLOW'},
    ]
    with pytest.raises(MissionValidationError, match='unsupported Mission action class'):
        from mission_orchestrator.gss_scope_sync import project
        project(gss.scope, s.get_envelope(mid)['envelope'], 0)


def test_revocation_during_cti_build_blocks_activation(gss_ready):
    s, mid, gss, cti = gss_ready
    original = cti.build_pip
    def revoke(body):
        result = original(body)
        gss.scope['status'] = 'REVOKED'
        return result
    cti.build_pip = revoke
    with pytest.raises(MissionValidationError): s.initialize_mission_pip_automatically(mid)
    assert s.repository.get_state(mid)['state'] == 'CREATED'


def test_changed_source_snapshot_rejected_before_commit(gss_ready):
    s, mid, gss, _ = gss_ready
    original = gss.get_scope_contract
    calls = []
    def changed(sid):
        result = original(sid)
        calls.append(sid)
        if len(calls) > 1:
            result['targets'][0]['target_value'] = 'http://other.example/'
        return result
    gss.get_scope_contract = changed
    with pytest.raises(MissionValidationError): s.initialize_mission_pip_automatically(mid)
    assert s.repository.get_current_scope_contract(mid) is None


def test_cti_outage_reuses_snapshot_on_retry(gss_ready):
    from mission_orchestrator.errors import MissionSubsystemUnavailable
    s, mid, gss, cti = gss_ready
    original = cti.build_pip
    def outage(body): raise MissionSubsystemUnavailable('test outage')
    cti.build_pip = outage
    with pytest.raises(MissionSubsystemUnavailable): s.initialize_mission_pip_automatically(mid)
    old = s.get_mission_scope_contract(mid)
    cti.build_pip = original
    assert s.initialize_mission_pip_automatically(mid)['state'] == 'PIP_BOUND'
    assert s.get_mission_scope_contract(mid)['snapshot_id'] == old['snapshot_id']
