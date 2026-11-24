from copy import deepcopy
import pytest
from test_two_phase_pip_initialization import ready
from mission_orchestrator.automatic_pip import initialization_inputs
from mission_orchestrator.errors import MissionValidationError


def test_automatic_binding_activation_and_replay(ready):
    s, mid, cti, _, _ = ready
    result = s.initialize_mission_pip_automatically(mid)
    assert result['state'] == 'PIP_BOUND'
    assert result['execution_authorized'] is False
    assert cti.built['mission_id'] == mid
    assert 'mission_characteristics' in cti.built['assumptions_and_gaps'][0]
    calls = cti.calls
    assert s.initialize_mission_pip_automatically(mid)['status'] == 'unchanged'
    assert cti.calls == calls


def test_auto_rejects_failed_cti_gates(ready):
    s, mid, cti, _, _ = ready
    cti.pip['validation_results'][0]['passed'] = False
    with pytest.raises(MissionValidationError):
        s.initialize_mission_pip_automatically(mid)
    assert s.repository.get_state(mid)['state'] == 'CREATED'
    assert not s.get_envelope(mid)['envelope']['bindings']['pip']['pip_id']


def test_resume_after_binding_without_rebuild(ready):
    s, mid, cti, request, _ = ready
    s.put_mission_pip_binding(mid, request)
    cti.build_pip = lambda p: pytest.fail('must reuse durable binding')
    assert s.initialize_mission_pip_automatically(mid)['state'] == 'PIP_BOUND'


def test_scope_replay_triggers_automatic_initialization(ready):
    from test_stage3_1_3_scope_roe_constraint_contract import contract_payload
    s, mid, cti, _, _ = ready
    result = s.put_mission_scope_contract(mid, contract_payload())
    assert result['idempotent_replay']
    assert result['automatic_pip']['state'] == 'PIP_BOUND'


def test_recovery_sweep(ready):
    from mission_orchestrator.automatic_pip import sweep
    s, mid, cti, _, _ = ready
    sweep(s)
    assert s.repository.get_state(mid)['state'] == 'PLANNING'
    assert s.get_generated_plan(mid)['target_actuation'] is False


def test_characteristics_do_not_invent_findings(ready):
    s, mid, _, _, _ = ready
    env = s.get_envelope(mid)['envelope']
    data = initialization_inputs(env, s.get_mission_scope_contract(mid))
    context = data['assumptions_and_gaps'][0]['mission_characteristics']
    assert context['objective'] == env['mission']['objective']
    assert set(data) == {'assumptions_and_gaps'}
