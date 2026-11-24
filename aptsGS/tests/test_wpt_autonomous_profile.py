from copy import deepcopy
import pytest
from app.workflow_profile import (WPT_PROFILE_ID, WPT_RECON_BUDGET, WPT_RECON_TECHNIQUES,
                                   apply_workflow_profile, default_console_profile)


TARGETS = [{'target_type': 'URL', 'target_value': 'http://127.0.0.1:80//dvwa/',
            'environment': 'LAB', 'allowed': True}]


def test_new_empty_lab_url_scope_has_complete_bounded_recon_profile():
    profile = default_console_profile(TARGETS, [])
    assert profile == WPT_PROFILE_ID
    rules, metadata = apply_workflow_profile([], profile)
    recon = [r for r in rules if r['action_class'] == 'TARGET_RECON']
    assert {r['action_name'] for r in recon} == {
        'recon', 'web_technology_fingerprinting', 'AUTHORIZE_TARGET_EXECUTION'}
    # The autonomous recon profile authorizes both bounded read-only recon techniques
    # (fingerprinting and bounded surface enumeration), GET-only, within one shared budget.
    assert all(r['constraints']['allowed_techniques'] == list(WPT_RECON_TECHNIQUES)
               and r['constraints']['max_network_requests'] == WPT_RECON_BUDGET
               and r['constraints']['allowed_methods'] == ['GET'] for r in recon)
    assert 'BOUNDED_WEB_SURFACE_ENUMERATION' in WPT_RECON_TECHNIQUES
    delegation = next(r for r in rules if r['action_class'] == 'TASK_DELEGATION')
    assert delegation['constraints']['allowed_capabilities'] == ['PENTEST:pentest.recon']
    assert delegation['constraints']['authorized_subject_component'] == 'APTS-MO01'
    assert delegation['constraints']['execution_authorized'] is False
    assert metadata['profile_id'] == WPT_PROFILE_ID
    assert not any(r['action_class'] in ('VULNERABILITY_VALIDATION', 'CONTROLLED_EXPLOITATION') for r in rules)
    assert apply_workflow_profile(rules, profile)[0] == rules


@pytest.mark.parametrize('change', [{'environment': 'PRODUCTION'}, {'target_type': 'IP'}, {'allowed': False}])
def test_auto_does_not_grant_for_other_target_contexts(change):
    assert default_console_profile([{**TARGETS[0], **change}], []) == 'NONE'


@pytest.mark.parametrize('effect,approval', [('DENY', False), ('REVIEW', False), ('ALLOW', True)])
def test_operator_policy_is_preserved(effect, approval):
    rules = [{'action_class': 'TARGET_RECON', 'action_name': '*', 'effect': effect,
              'requires_approval': approval, 'constraints': {}}]
    before = deepcopy(rules)
    assert default_console_profile(TARGETS, rules) == 'NONE'
    with pytest.raises(ValueError): apply_workflow_profile(rules, WPT_PROFILE_ID)
    assert rules == before


def test_revisions_inherit_persisted_choice_and_none_removes_generated_grants():
    assert default_console_profile(TARGETS, [], {}) == 'NONE'
    metadata = {'gss_workflow_profile': {'profile_id': WPT_PROFILE_ID}}
    assert default_console_profile(TARGETS, [], metadata) == WPT_PROFILE_ID
    rules, _ = apply_workflow_profile([], WPT_PROFILE_ID)
    assert apply_workflow_profile(rules, 'NONE') == ([], None)


def test_smaller_operator_budget_is_never_increased():
    rules = [{'action_class': 'TARGET_RECON', 'action_name': '*', 'effect': 'ALLOW',
              'requires_approval': False, 'constraints': {'max_network_requests': 2}}]
    result, _ = apply_workflow_profile(rules, WPT_PROFILE_ID)
    assert result[0]['constraints']['max_network_requests'] == 2
