from mission_orchestrator.mission_routing_handoff_automation import (
    _key, find_target_recon_decision, process_mission, automatic_recon_binding_policy,
)


def test_recon_waiting_reason_preserves_explicit_policy_gate():
    scope = {'scope': {'targets': [{'target_type': 'URL'}]},
             'roe': {'allowed_action_classes': ['TARGET_RECON']}}
    assert automatic_recon_binding_policy(scope, {'action_constraints': []}) == (
        False, 'GSS_TARGET_RECON_ALLOW_REQUIRED')
    allow = {'action_class': 'TARGET_RECON', 'effect': 'ALLOW', 'requires_approval': False}
    assert automatic_recon_binding_policy(scope, {'action_constraints': [allow]})[0]
    assert automatic_recon_binding_policy(scope, {'action_constraints': [
        allow, {**allow, 'effect': 'DENY'}]}) == (False, 'GSS_TARGET_RECON_DENIED')
    assert automatic_recon_binding_policy(scope, {'action_constraints': [
        {**allow, 'requires_approval': True}]}) == (False, 'GSS_TARGET_RECON_REQUIRES_APPROVAL')


def test_target_recon_decision_requires_exact_authoritative_allow():
    mission = "mission-gmo-test-001"
    target = {"target_type": "URL", "target_value": "http://localhost:3000/"}
    snapshot = {
        "authority": "aptsGSS", "mission_id": mission,
        "authorization_requests": [{
            "request_id": "req-1", "mission_id": mission,
            "subject_component": "PENTEST-SUB01", "action_class": "TARGET_RECON",
            "resource_type": "URL", "resource_value": target["target_value"],
        }],
        "policy_decisions": [{"request_id": "req-1", "decision_id": "dec-1",
                              "decision": "ALLOW", "decision_hash": "a" * 64,
                              "policy_version": 1}],
    }
    assert find_target_recon_decision(snapshot, mission, target)["decision_id"] == "dec-1"
    assert find_target_recon_decision(snapshot, mission, {**target, "target_value": "http://localhost/"}) is None
    assert find_target_recon_decision({**snapshot, "authority": "local"}, mission, target) is None


def test_idempotency_key_is_stable_and_task_specific():
    a = _key("mission-a", "ptask-1", "intent")
    assert a == _key("mission-a", "ptask-1", "intent")
    assert a != _key("mission-a", "ptask-2", "intent")
    assert a != _key("mission-a", "ptask-1", "route")


def test_worker_does_not_process_nonplanning_mission():
    class Repository:
        def get_state(self, mission_id):
            return {"state": "RUNNING", "state_version": 4}

    class Service:
        repository = Repository()

    result = process_mission(Service(), "mission-gmo-test-001")
    assert result["status"] == "unchanged"
    assert result["state"] == "RUNNING"
