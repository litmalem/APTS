from app.delegation_profile import scope_action_constraints_with_profiles


def target_recon_allow():
    return [{
        'action_class': 'TARGET_RECON', 'action_name': '*', 'effect': 'ALLOW',
        'max_risk_level': 'LOW', 'requires_approval': False,
        'constraints': {'read_only': True},
    }]


def test_profile_is_disabled_by_default():
    rules, applied = scope_action_constraints_with_profiles(
        target_recon_allow(), auto_recon_task_delegation=False)
    assert not applied
    assert len(rules) == 1


def test_profile_derives_only_exact_non_actuating_recon_delegation():
    rules, applied = scope_action_constraints_with_profiles(
        target_recon_allow(), auto_recon_task_delegation=True)
    assert applied
    delegation = [r for r in rules if r['action_class'] == 'TASK_DELEGATION']
    assert delegation == [{
        'action_class': 'TASK_DELEGATION',
        'action_name': 'delegate_planned_task',
        'effect': 'ALLOW',
        'max_risk_level': 'LOW',
        'requires_approval': False,
        'constraints': {
            'allowed_capabilities': ['PENTEST:pentest.recon'],
            'execution_authorized': False,
            'target_actuation': False,
            'policy_profile': 'GSS_AUTO_RECON_TASK_DELEGATION_V1',
        },
    }]


def test_profile_does_not_infer_delegation_without_explicit_target_recon_allow():
    for effect in ('DENY', 'REVIEW'):
        rules = [{**target_recon_allow()[0], 'effect': effect}]
        result, applied = scope_action_constraints_with_profiles(
            rules, auto_recon_task_delegation=True)
        assert not applied
        assert result == rules


def test_profile_preserves_existing_task_delegation_deny_and_wildcard():
    for existing in (
        {'action_class': 'TASK_DELEGATION', 'action_name': 'delegate_planned_task',
         'effect': 'DENY', 'max_risk_level': 'LOW', 'requires_approval': False, 'constraints': {}},
        {'action_class': 'TASK_DELEGATION', 'action_name': '*',
         'effect': 'DENY', 'max_risk_level': 'LOW', 'requires_approval': False, 'constraints': {}},
    ):
        rules = target_recon_allow() + [existing]
        result, applied = scope_action_constraints_with_profiles(
            rules, auto_recon_task_delegation=True)
        assert not applied
        assert result == rules
