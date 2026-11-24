"""Guard-preserving autonomous Mission RUNNING activation.

RUNNING changes lifecycle state, *never* authorizes a target operation.  No
network actions are performed by this module.  A failed GSS source check,
missing plan validation, or missing transition lineage leaves PLANNING intact.
"""
from __future__ import annotations

import hashlib
import logging
import os
from contextlib import closing

from .canonical import sha256_hex

LOGGER = logging.getLogger(__name__)


def _missing_pentest_orchestration_task_ids(service, mission_id: str) -> list[str]:
    """Return required Pentest orchestration tasks not durably materialized.

    Delegation, Stage 4.3 materialization, and Stage 5.1 orchestration creation
    are valid only while Mission is in PLANNING/REPLANNING. Promoting before
    both the authoritative task and its active local orchestration exist stops
    the routing handoff worker and strands Recon targets before WPT. This is a
    control-plane readiness check; it grants no execution authority.
    """
    if os.getenv('APTS_REQUIRE_PENTEST_ORCHESTRATION_BEFORE_RUNNING', '1').strip() == '0':
        return []

    planned = service.list_planned_tasks(mission_id).get('planned_tasks', [])
    required_ids = [
        row['planned_task_id'] for row in planned
        if row.get('required_subsystem') == 'PENTEST'
        and str(row.get('task_key', '')).endswith('-pentest-orchestration')
        and isinstance(row.get('planned_task_id'), str)
    ]
    if not required_ids:
        return []

    # ProposalSource is read-only and checks the installed Pentest schema.
    # An unavailable repository is handled by activate() as fail-closed.
    from execution_subsystem.proposal_source import PentestProposalSource

    pentest = PentestProposalSource()
    placeholders = ','.join('?' for _ in required_ids)
    with closing(pentest._connect()) as conn:
        pentest._migration(conn)
        tables = {row['name'] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('pentest_tasks','pentest_agentic_orchestrations')").fetchall()}
        if tables != {'pentest_tasks', 'pentest_agentic_orchestrations'}:
            return required_ids
        rows = conn.execute(
            'SELECT t.upstream_task_id FROM pentest_tasks AS t '
            'JOIN pentest_agentic_orchestrations AS o '
            'ON o.pentest_task_id=t.pentest_task_id '
            f'WHERE t.mission_id=? AND t.upstream_task_id IN ({placeholders}) '
            "AND o.mission_id=t.mission_id AND o.upstream_task_id=t.upstream_task_id "
            "AND o.orchestration_status='ACTIVE'",
            (mission_id, *required_ids),
        ).fetchall()
    ready = {row['upstream_task_id'] for row in rows}
    return [task_id for task_id in required_ids if task_id not in ready]


def enabled() -> bool:
    # A validated Mission should not remain stuck in PLANNING solely because
    # an opt-in flag was omitted. Operators can explicitly pause promotion.
    return os.getenv('APTS_AUTONOMOUS_RUNNING', '1').strip() != '0'


def activate(service, mission_id: str) -> dict:
    state = service.get_mission_state(mission_id)['mission_state']
    if state['state'] != 'PLANNING':
        return {'status': 'unchanged', 'state': state['state'], 'execution_authorized': False,
                'target_io_performed': False}
    validation = service.get_plan_validation(mission_id)
    if validation.get('validation_status') != 'VALIDATED_FEASIBLE':
        return {'status': 'deferred', 'reason': 'FEASIBLE_PLAN_NOT_VERIFIED', 'execution_authorized': False}
    plan = service.get_generated_plan(mission_id)
    if not isinstance(plan, dict) or not plan.get('generated_plan_id') or not plan.get('canonical_sha256'):
        return {'status': 'deferred', 'reason': 'GENERATED_PLAN_MISSING', 'execution_authorized': False}
    scope = service.get_mission_scope_contract(mission_id)['contract']
    source_meta = (scope.get('metadata') or {}).get('gss_scope_sync')
    if not isinstance(source_meta, dict) or not source_meta.get('source_snapshot_sha256'):
        return {'status': 'deferred', 'reason': 'AUTHORITATIVE_GSS_SCOPE_REQUIRED', 'execution_authorized': False}
    from .gss_scope_sync import fetch
    # fetch validates ACTIVE, validity dates, GSS creation lineage, and latest
    # scope revision. A source edit or revocation cannot silently activate RUNNING.
    authoritative = fetch(service, mission_id)
    if sha256_hex(authoritative) != source_meta['source_snapshot_sha256']:
        return {'status': 'deferred', 'reason': 'GSS_SCOPE_CHANGED', 'execution_authorized': False}
    try:
        missing = _missing_pentest_orchestration_task_ids(service, mission_id)
    except Exception as exc:
        LOGGER.info('Pentest task readiness unavailable for %s: %s', mission_id, type(exc).__name__)
        return {'status': 'deferred', 'reason': 'PENTEST_REPOSITORY_UNAVAILABLE',
                'execution_authorized': False, 'target_io_performed': False}
    if missing:
        LOGGER.info('Pentest orchestration handoff pending for %s task_ids=%s', mission_id, ','.join(missing))
        return {'status': 'deferred', 'reason': 'PENTEST_ORCHESTRATION_NOT_MATERIALIZED',
                'pending_planned_task_ids': missing,
                'execution_authorized': False, 'target_io_performed': False}
    # Use the actual lifecycle command, which independently enforces START's
    # append-only PIP/PLANNING activation proofs at its guarded commit boundary.
    state = service.get_mission_state(mission_id)['mission_state']
    vector = service.get_mission_version_vector(mission_id)
    command_key = 'auto-run-' + hashlib.sha256(mission_id.encode('utf-8')).hexdigest()[:40]
    result = service.execute_mission_lifecycle_command(mission_id, {
        'command_id': command_key, 'idempotency_key': command_key,
        'command': 'START', 'expected_version_sha256': vector['version_sha256'],
        'expected_state_version': state['state_version'],
        'actor': 'mission-auto-running', 'reason_code': 'AUTONOMOUS_VALIDATED_PLAN_ACTIVATION',
        'reason': 'Start Mission after verified PIP, plan and unchanged authoritative GSS scope',
        'evidence_refs': ['validated-plan:' + plan['generated_plan_id']],
        'metadata': {'automation': 'APTS_AUTONOMOUS_RUNNING_V1',
                     'plan_sha256': plan['canonical_sha256'],
                     'gss_source_sha256': source_meta['source_snapshot_sha256'],
                     'execution_authorized': False, 'target_io_performed': False},
    })
    return {'status': 'activated', 'mission_id': mission_id,
            'state': service.get_mission_state(mission_id)['mission_state']['state'],
            'lifecycle': result, 'execution_authorized': False, 'target_io_performed': False}


def sweep(service) -> None:
    if not enabled():
        return
    offset = 0
    ids = []
    while True:
        page = service.list_missions(state='PLANNING', limit=100, offset=offset)
        ids += [row['mission_id'] for row in page['missions']]
        offset += len(page['missions'])
        if not page['missions'] or offset >= page['mission_count']:
            break
    for mid in ids:
        try:
            activate(service, mid)
        except Exception:
            LOGGER.exception('Guarded autonomous RUNNING activation deferred for %s', mid)
