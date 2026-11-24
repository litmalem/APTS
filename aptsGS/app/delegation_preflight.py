"""Read-only TASK_DELEGATION Scope/RoE preflight.

This is a diagnostic, NOT a PolicyDecision or execution authorization.
Actual delegation still requires the authoritative authorization evaluation,
version-bound binding, and normal downstream gates.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from .models import ActionClass, Decision, RiskLevel

DELEGATION_ACTION = 'delegate_planned_task'
DEFAULT_RECON_CAPABILITY = 'PENTEST:pentest.recon'
_CAPABILITY = re.compile(r'[A-Z][A-Z0-9_]*:[a-z][a-z0-9_.-]*\Z')


def allow_rule_problems(rule: dict | None, capability: str = DEFAULT_RECON_CAPABILITY) -> list[str]:
    """Detect dangerously broad or incomplete ALLOW delegation rules.

    A valid rule does not itself authorize a request. It merely permits the
    deterministic governance gate to evaluate a precisely scoped handoff.
    """
    if not rule:
        return ['NO_ACTION_CONSTRAINT']
    problems = []
    action = rule.get('action_class')
    if hasattr(action, 'value'):
        action = action.value
    if action != ActionClass.TASK_DELEGATION.value:
        problems.append('WRONG_ACTION_CLASS')
    if rule.get('action_name') != DELEGATION_ACTION:
        problems.append('DELEGATION_ACTION_NAME_NOT_EXACT')
    effect = rule.get('effect')
    effect = effect.value if hasattr(effect, 'value') else effect
    if effect != Decision.ALLOW.value:
        problems.append('DELEGATION_ACTION_NOT_ALLOWED')
    risk = rule.get('max_risk_level')
    risk = risk.value if hasattr(risk, 'value') else risk
    if risk != RiskLevel.LOW.value:
        problems.append('DELEGATION_RISK_NOT_LOW')
    if rule.get('requires_approval') not in (False, 0):
        problems.append('DELEGATION_REQUIRES_REVIEW')
    constraints = rule.get('constraints')
    if not isinstance(constraints, dict):
        return problems + ['DELEGATION_CONSTRAINTS_INVALID']
    allowed = constraints.get('allowed_capabilities')
    if (not isinstance(allowed, list) or not allowed
            or any(not isinstance(x, str) or not _CAPABILITY.fullmatch(x) for x in allowed)
            or len(set(allowed)) != len(allowed)):
        problems.append('DELEGATION_ALLOWLIST_INVALID')
    elif capability not in allowed:
        problems.append('SUBSYSTEM_CAPABILITY_NOT_ALLOWLISTED')
    if constraints.get('execution_authorized') is not False:
        problems.append('DELEGATION_EXECUTION_AUTHORITY_MUST_BE_FALSE')
    if constraints.get('target_actuation') is not False:
        problems.append('DELEGATION_TARGET_ACTUATION_MUST_BE_FALSE')
    return problems


def inspect_delegation_scope(service, scope_id: str, capability: str = DEFAULT_RECON_CAPABILITY) -> dict:
    """Read existing GSS scope, policy and emergency state without writing decisions.

    Scope validity is based on the server clock. The result never claims a
    decision is ALLOW, and does not verify Mission's separate binding version.
    """
    scope = service.repo.get_scope_contract(scope_id)
    if scope is None:
        raise LookupError('Scope contract not found')
    errors = []
    if not service._scope_active(scope):
        errors.append('NO_ACTIVE_SCOPE_CONTRACT')
    policy_id = scope.get('policy_set_id')
    policy = service.repo.get_policy_set(policy_id) if policy_id else None
    if not service._policy_active(policy):
        errors.append('NO_ACTIVE_POLICY_SET')
    emergency = service.repo.get_emergency_state()
    if bool(emergency.get('active')):
        errors.append('EMERGENCY_STOP_ACTIVE')
    constraint = service.repo.find_action_constraint(scope_id, ActionClass.TASK_DELEGATION.value, DELEGATION_ACTION)
    errors.extend(allow_rule_problems(constraint, capability))
    # Ensure a matching row in this scope; the repository also supports '*',
    # which must not grant delegation on an unconstrained action name.
    reasons = list(dict.fromkeys(errors))
    return {
        'status': 'READY_SCOPE_CONFIGURATION' if not reasons else 'BLOCKED',
        'ready': not reasons,
        'mission_id': scope.get('mission_id'),
        'scope_contract_id': scope_id,
        'scope_version': scope.get('version'),
        'policy_set_id': policy_id,
        'policy_version': policy.get('version') if policy else None,
        'action_class': ActionClass.TASK_DELEGATION.value,
        'action_name': DELEGATION_ACTION,
        'subject_component': 'APTS-MO01',
        'resource_type': 'SUBSYSTEM_CAPABILITY',
        'resource_value': capability,
        'allowlisted_capabilities': (constraint or {}).get('constraints', {}).get('allowed_capabilities', []),
        'reason_codes': reasons or ['SCOPE_CONFIGURATION_VALID'],
        'decision_issued': False,
        'delegation_authorized': False,
        'execution_authorized': False,
        'target_actuation': False,
        'mission_binding_verified': False,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'limitations': [
            'READ_ONLY_DIAGNOSTIC_NOT_AN_AUTHORIZATION',
            'MISSION_GOVERNANCE_BINDING_MUST_BE_REVALIDATED',
            'EXISTING_DENIED_ROUTE_AUTHORIZATION_REQUIRES_VERSIONED_RETRY_FIX',
        ],
    }
