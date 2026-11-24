"""A dead/unreachable target must surface as an explicit WPT job-status notice.

Covers the pure mapping only: no network traffic, scan, or runtime I/O.
"""
import pytest

from mission_orchestrator.mission_wpt_preparation import (
    TARGET_UNREACHABLE_REASONS,
    WPT_TARGET_UNREACHABLE_REASON,
    target_unreachable_notice,
)


@pytest.mark.parametrize('reason', sorted(TARGET_UNREACHABLE_REASONS))
def test_terminal_unreachable_target_produces_dedicated_notice(reason):
    notice = target_unreachable_notice({'status': 'FAILED', 'reason_code': reason})
    assert notice == {'status': 'FAILED',
                      'reason_code': f'{WPT_TARGET_UNREACHABLE_REASON}:{reason}'}


def test_web_profile_no_response_is_the_fingerprint_dead_target_case():
    # The exact code the fixed fingerprint collector raises when every probe
    # fails at the connection level (the observed WPT incident).
    assert 'WEB_PROFILE_NO_RESPONSE' in TARGET_UNREACHABLE_REASONS
    notice = target_unreachable_notice(
        {'status': 'FAILED', 'reason_code': 'WEB_PROFILE_NO_RESPONSE',
         'execution_id': 'exec-fd03a56ed15234635b2999fd0ac8950e'})
    assert notice['status'] == 'FAILED'
    assert notice['reason_code'].startswith(WPT_TARGET_UNREACHABLE_REASON + ':')


@pytest.mark.parametrize('status', ['TIMEOUT', 'ABORTED', 'BLOCKED', 'DENIED'])
def test_other_terminal_states_with_unreachable_reason_also_notify(status):
    notice = target_unreachable_notice(
        {'status': status, 'reason_code': 'WEB_PROFILE_NO_RESPONSE'})
    assert notice is not None
    assert notice['status'] == 'FAILED'  # normalized to a single terminal signal


def test_success_or_running_is_not_a_notice():
    assert target_unreachable_notice({'status': 'SUCCEEDED', 'reason_code': None}) is None
    assert target_unreachable_notice({'status': 'RUNNING', 'reason_code': None}) is None
    assert target_unreachable_notice({'status': 'AUTHORIZED'}) is None


def test_failure_from_another_cause_is_not_target_unreachable():
    # A genuine adapter/validation failure must keep its own reason, not be
    # mislabeled as a dead target.
    assert target_unreachable_notice(
        {'status': 'FAILED', 'reason_code': 'ADAPTER_CONTRACT_VIOLATION'}) is None


def test_non_dict_runtime_is_ignored():
    assert target_unreachable_notice(None) is None
    assert target_unreachable_notice('FAILED') is None


def test_reason_code_is_length_bounded():
    notice = target_unreachable_notice(
        {'status': 'FAILED', 'reason_code': 'WEB_PROFILE_NO_RESPONSE'})
    assert len(notice['reason_code']) <= 180
