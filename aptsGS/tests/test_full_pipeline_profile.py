"""The bounded Pentest autonomous profile must authorize the whole safe pipeline:
recon (fingerprint + bounded enumeration) and read-only vulnerability validation,
plus non-actuating delegation to recon/validate/cti. It must never authorize an
exploitation/post-exploitation/credential/destructive action class.
"""
from app.workflow_profile import (PROFILE_ID, SAFE_RECON_TECHNIQUES,
                                   SAFE_VALIDATION_TECHNIQUES, apply_workflow_profile)


def _by_class(rules):
    out = {}
    for r in rules:
        out.setdefault(r['action_class'], {})[r['action_name']] = r
    return out


def test_full_pipeline_profile_authorizes_recon_enumeration_and_validation():
    rules, meta = apply_workflow_profile([], PROFILE_ID)
    by = _by_class(rules)

    recon_exec = by['TARGET_RECON']['AUTHORIZE_TARGET_EXECUTION']['constraints']['allowed_techniques']
    assert 'WEB_TECHNOLOGY_FINGERPRINT' in recon_exec
    assert 'BOUNDED_WEB_SURFACE_ENUMERATION' in recon_exec
    assert set(recon_exec) <= set(SAFE_RECON_TECHNIQUES)
    assert by['TARGET_RECON']['AUTHORIZE_TARGET_EXECUTION']['constraints']['read_only'] is True

    validation_exec = by['VULNERABILITY_VALIDATION']['AUTHORIZE_TARGET_EXECUTION']['constraints']['allowed_techniques']
    assert set(validation_exec) == set(SAFE_VALIDATION_TECHNIQUES)

    delegation = next(r for r in rules if r['action_class'] == 'TASK_DELEGATION')
    assert delegation['constraints']['allowed_capabilities'] == [
        'PENTEST:pentest.recon', 'PENTEST:pentest.validate', 'CTI:cti.analyze.context']
    assert delegation['constraints']['execution_authorized'] is False
    assert meta['execution_authorized'] is False and meta['target_actuation'] is False


def test_full_pipeline_profile_never_authorizes_exploitation_classes():
    rules, _ = apply_workflow_profile([], PROFILE_ID)
    forbidden = {'CONTROLLED_EXPLOITATION', 'POST_EXPLOITATION', 'CREDENTIAL_USE',
                 'PRIVILEGE_ESCALATION', 'LATERAL_MOVEMENT', 'DATA_ACCESS',
                 'DESTRUCTIVE_ACTION', 'TARGET_ENUMERATION'}
    assert not any(r['action_class'] in forbidden for r in rules)


def test_bounded_enumeration_is_read_only_and_safe():
    # Enumeration joined the recon tier only as a bounded, read-only technique.
    assert 'BOUNDED_WEB_SURFACE_ENUMERATION' in SAFE_RECON_TECHNIQUES
