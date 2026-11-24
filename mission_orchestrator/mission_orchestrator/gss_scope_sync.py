"""Read authoritative GSS lineage and persist a non-actuating bootstrap projection."""
from copy import deepcopy
from datetime import datetime, timezone
import re
from .canonical import sha256_hex
from .errors import MissionValidationError, MissionScopeContractNotFound
from .scope_contract import ACTION_CLASSES

KEY = 'gss_scope_sync'
# TASK_DELEGATION is a GSS control-plane permission. It is deliberately kept
# out of the Mission target-action ROE projection below.
_CONTROL_PLANE_ACTION_CLASSES = frozenset({'TASK_DELEGATION'})
_ACTION_EFFECTS = frozenset({'ALLOW', 'DENY', 'REVIEW'})


def timestamp(value):
    if not isinstance(value, str):
        raise MissionValidationError('GSS scope validity timestamp missing')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise MissionValidationError('Invalid GSS scope timestamp') from exc
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def active(scope):
    now = datetime.now(timezone.utc)
    return (scope.get('status') == 'ACTIVE' and timestamp(scope.get('valid_from')) <= now
            and (scope.get('valid_until') is None or now < timestamp(scope['valid_until'])))


def fetch(service, mission_id):
    correlation = service.governance_client.mission_correlation_snapshot(mission_id)
    if correlation.get('mission_id') != mission_id or correlation.get('authority') != 'aptsGSS':
        raise MissionValidationError('GSS correlation authority/mission mismatch')
    # Governance-binding operations create their own immutable, operation-bound
    # GSS contract. It is not the operator-authored source scope for this
    # read-only projection, so do not count it as a second source contract.
    candidates = [
        x for x in correlation.get('scope_contracts', [])
        if active(x) and not ((x.get('metadata') or {}).get('mission_orchestrator_binding_operation_id'))
    ]
    if len(candidates) != 1:
        raise MissionValidationError('Expected exactly one active GSS scope for Mission; found ' + str(len(candidates)))
    ref = candidates[0]
    source = service.governance_client.get_scope_contract(ref['scope_contract_id'])
    if source.get('mission_id') != mission_id or not active(source):
        raise MissionValidationError('GSS scope mission/status/validity mismatch')
    for field in ('scope_contract_id', 'version', 'contract_hash'):
        if source.get(field) != ref.get(field):
            raise MissionValidationError('GSS scope changed during correlation: ' + field)
    if type(source.get('version')) is not int or source['version'] < 1:
        raise MissionValidationError('Invalid GSS scope version')
    digest = source.get('contract_hash')
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise MissionValidationError('Invalid GSS source contract hash')
    # GSS retains the original authoring hash, while its API includes database fields.
    # Verify that source reference against the independently persisted creation lineage.
    events = correlation.get('events', [])
    if not any(e.get('event_type') == 'SCOPE_CHANGED' and
               (e.get('payload') or {}).get('scope_contract_id') == source['scope_contract_id'] and
               (e.get('payload') or {}).get('scope_version') == source['version'] and
               (e.get('payload') or {}).get('contract_hash') == digest for e in events):
        raise MissionValidationError('GSS source hash/version not corroborated by SCOPE_CHANGED lineage')
    if not isinstance(source.get('action_constraints'), list):
        raise MissionValidationError('GSS action_constraints must be an explicit array')
    if not isinstance(source.get('targets'), list) or not source['targets']:
        raise MissionValidationError('GSS scope has no targets')
    return deepcopy(source)


def _project_action_constraints(source):
    """Project only explicit, recognized GSS target-action rules into Mission ROE.

    GSS owns the authoritative rules. Empty constraints therefore project to an
    empty ROE allowlist. Control-plane rules such as TASK_DELEGATION remain in
    the source snapshot and are never treated as target-action permission.
    """
    allowed, prohibited, approval_required = set(), set(), set()
    for index, item in enumerate(source.get('action_constraints') or []):
        if not isinstance(item, dict):
            raise MissionValidationError(f'GSS action_constraints[{index}] must be an object')
        action_class = item.get('action_class')
        effect = item.get('effect')
        if not isinstance(action_class, str) or not action_class.strip():
            raise MissionValidationError(f'GSS action_constraints[{index}].action_class is required')
        action_class = action_class.strip().upper()
        if not isinstance(effect, str) or effect.strip().upper() not in _ACTION_EFFECTS:
            raise MissionValidationError(f'GSS action_constraints[{index}].effect is unsupported')
        effect = effect.strip().upper()
        requires_approval = item.get('requires_approval', effect == 'REVIEW')
        # GSS responses can cross JSON/database boundaries as 0/1 or the
        # strings "true"/"false". Normalize only these exact encodings;
        # ambiguous values still fail closed and are never treated as ALLOW.
        if isinstance(requires_approval, bool):
            pass
        elif type(requires_approval) is int and requires_approval in (0, 1):
            requires_approval = bool(requires_approval)
        elif isinstance(requires_approval, str) and requires_approval.strip().lower() in ('true', 'false'):
            requires_approval = requires_approval.strip().lower() == 'true'
        else:
            raise MissionValidationError(f'GSS action_constraints[{index}].requires_approval must be boolean')

        if action_class in _CONTROL_PLANE_ACTION_CLASSES:
            continue
        if action_class not in ACTION_CLASSES:
            # Unknown ALLOW rules must never silently become Mission grants.
            raise MissionValidationError(
                f'GSS action_constraints[{index}] uses unsupported Mission action class {action_class}'
            )
        if effect == 'DENY':
            prohibited.add(action_class)
            allowed.discard(action_class)
            approval_required.discard(action_class)
        else:
            allowed.add(action_class)
            if effect == 'REVIEW' or requires_approval:
                approval_required.add(action_class)

    # Mission ROE is class-granular. If any GSS rule denies a class, fail closed
    # for that complete class even when another action_name has an ALLOW rule.
    allowed.difference_update(prohibited)
    approval_required.intersection_update(allowed)
    return sorted(allowed), sorted(prohibited), sorted(approval_required)


def _project_network_request_budget(source):
    """Project only an explicit positive GSS TARGET_RECON request budget.

    Every TARGET_RECON ALLOW rule must carry the same-class limit; otherwise
    the projection remains empty and WPT intake fails closed.
    """
    allow_rules = [
        item for item in source.get('action_constraints') or []
        if isinstance(item, dict)
        and str(item.get('action_class', '')).strip().upper() == 'TARGET_RECON'
        and str(item.get('effect', '')).strip().upper() == 'ALLOW'
    ]
    if not allow_rules:
        return {}
    limits = []
    for item in allow_rules:
        constraints = item.get('constraints')
        if not isinstance(constraints, dict):
            return {}
        limit = constraints.get('max_network_requests')
        if type(limit) is not int or limit < 1:
            return {}
        limits.append(limit)
    return {'max_network_requests': min(limits)}


def project(source, envelope, expected):
    included, excluded = [], []
    for target in source['targets']:
        item = {k: target[k] for k in ('target_type', 'target_value', 'environment')}
        (included if target.get('allowed') in (True, 1) else excluded).append(item)
    if not included:
        raise MissionValidationError('GSS scope has no allowed targets')
    budgets = envelope['mission'].get('budgets') or {}
    duration = budgets.get('max_duration_seconds', budgets.get('time_seconds', 3600))
    snapshot_hash = sha256_hex(source)
    allowed_actions, prohibited_actions, approval_actions = _project_action_constraints(source)
    resource_budget = _project_network_request_budget(source)
    projection_mode = ('GSS_EXPLICIT_ACTION_CONSTRAINTS' if
                       allowed_actions or prohibited_actions else 'BOOTSTRAP_NO_ACTION_PERMISSIONS')
    return {
        'expected_contract_version': expected,
        'idempotency_key': 'gss-sync-' + sha256_hex({'source': snapshot_hash})[:48],
        'actor': 'mission-gss-scope-sync', 'reason': 'Read-only GSS scope projection for PIP bootstrap',
        'scope': {'targets': included, 'excluded_targets': excluded},
        'roe': {'allowed_action_classes': allowed_actions, 'prohibited_action_classes': prohibited_actions,
                'allowed_time_window': ({'start_at': timestamp(source['valid_from']).isoformat(),
                                         'end_at': timestamp(source['valid_until']).isoformat()}
                                        if source.get('valid_until') else None),
                'maximum_concurrency': 1, 'destructive_actions_allowed': False,
                'credential_usage_allowed': False, 'persistence_allowed': False,
                'human_approval_required_for': approval_actions},
        'constraints': {'max_actions': budgets.get('max_actions', 1), 'max_duration': duration,
                        'risk_threshold': 'LOW', 'resource_budget': resource_budget,
                        'data_handling_policy': {'execution_authorized': False}},
        'metadata': {KEY: {'source_scope_contract_id': source['scope_contract_id'],
                           'source_version': source['version'], 'source_contract_hash': source['contract_hash'],
                           'source_snapshot_sha256': snapshot_hash, 'source_snapshot': deepcopy(source),
                           'action_constraints': deepcopy(source['action_constraints']),
                           'projected_allowed_action_classes': allowed_actions,
                           'projected_prohibited_action_classes': prohibited_actions,
                           'projected_human_approval_required_for': approval_actions,
                           'projected_resource_budget': deepcopy(resource_budget),
                           'hash_verification': 'GSS_CORRELATION_AND_CREATION_LINEAGE',
                           'projection_mode': projection_mode, 'execution_authorized': False}}}


def synchronize(service, mission_id):
    try:
        current = service.get_mission_scope_contract(mission_id)
    except MissionScopeContractNotFound:
        current = None
    previous = ((current or {}).get('contract') or {}).get('metadata', {}).get(KEY)
    if current is not None and not previous:
        return current  # Explicitly authored local contract remains authoritative locally.
    source = fetch(service, mission_id)
    digest = sha256_hex(source)
    if previous and previous['source_snapshot_sha256'] == digest:
        return current
    if previous and source['scope_contract_id'] == previous['source_scope_contract_id'] and source['version'] <= previous['source_version']:
        raise MissionValidationError('GSS source changed without a new immutable scope/version')
    # Detect source changes/revocation during collection before committing a snapshot.
    if sha256_hex(fetch(service, mission_id)) != digest:
        raise MissionValidationError('GSS scope changed during synchronization; retry required')
    envelope = service.get_envelope(mission_id)['envelope']
    request = project(source, envelope, current['contract_version'] if current else 0)
    service.put_mission_scope_contract(mission_id, request)
    return service.get_mission_scope_contract(mission_id)
