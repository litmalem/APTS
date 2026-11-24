"""Durable, verified WPT Stage 6 evidence -> Recon handoff recovery worker.

The Stage 6 result MUST already be in the authoritative evidence repository
and validated by WPTIntakeService.submit_stage6_result. No self-attested
results, raw network output, or caller-supplied Recon IDs are admitted.
"""
from __future__ import annotations

from contextlib import closing
import logging
import os

from execution_subsystem.proposal_source import PentestProposalSource
from execution_subsystem.wpt_intake_service import WPTIntakeService
from mission_orchestrator.canonical import sha256_hex

LOGGER = logging.getLogger(__name__)


def _receipt(intake, result, handoff):
    from execution_subsystem.wpt_job_callback import publish_recon_receipt
    try:
        publish_recon_receipt(intake, result, handoff)
        return 'DELIVERED'
    except Exception:
        LOGGER.warning('Recon receipt deferred intake=%s', intake['intake_id'])
        return 'PENDING'


def enabled() -> bool:
    return os.getenv('APTS_AUTONOMOUS_WPT_RECON_DELIVERY', '').strip() == '1'


def _match_action(run: dict, intake: dict):
    if run.get('mission_id') != intake['mission_id']:
        return []
    if run.get('orchestration_id') != intake['orchestration_id']:
        return []
    # The immutable initial run is a parent. Derived Recon iterations are
    # outputs of the handoff and must never become new candidate parents.
    if run.get('parent_recon_run_id') is not None:
        return []
    if run.get('request', {}).get('boundary', {}).get('task_id') != intake['task_id']:
        return []
    return [action for action in run.get('output', {}).get('action_requests', [])
            if action.get('target_ref') == intake['target']
            and isinstance(action.get('action_id'), str)
            and action['action_id'].startswith('rareq-')]


def deliver(service, mission_id: str, *, wpt=None, recon=None, pentest=None) -> list[dict]:
    if service.get_mission_state(mission_id)['mission_state']['state'] != 'RUNNING':
        return [{'status': 'deferred', 'reason': 'MISSION_NOT_RUNNING'}]
    source_scope = service.get_mission_scope_contract(mission_id)['contract']
    meta = source_scope.get('metadata', {}).get('gss_scope_sync') or {}
    if not meta.get('source_snapshot_sha256'):
        return [{'status': 'deferred', 'reason': 'GSS_SCOPE_SOURCE_REQUIRED'}]
    from .gss_scope_sync import fetch
    if sha256_hex(fetch(service, mission_id)) != meta['source_snapshot_sha256']:
        return [{'status': 'deferred', 'reason': 'GSS_SCOPE_CHANGED'}]
    wpt = wpt or WPTIntakeService()
    pentest = pentest or PentestProposalSource()
    with closing(pentest._connect()) as conn:
        pentest._migration(conn)
        rows = conn.execute('SELECT upstream_task_id FROM pentest_tasks WHERE mission_id=? ORDER BY upstream_task_id LIMIT 101',
                            (mission_id,)).fetchall()
    if len(rows) > 100:
        return [{'status': 'deferred', 'reason': 'PENTEST_TASK_LIMIT_EXCEEDED'}]
    if not rows:
        return [{'status': 'deferred', 'reason': 'AWAITING_PENTEST_TASK_MATERIALIZATION'}]
    items = []
    for task in rows:
        items.extend(wpt.list_for_task(mission_id, task['upstream_task_id']))
    if not any(item.get('stage6_result') is not None for item in items):
        return [{'status': 'waiting', 'reason': 'VERIFIED_STAGE6_EVIDENCE_REQUIRED'}]
    if recon is None:
        from execution_subsystem.wpt_recon_source import recon_service
        recon = recon_service(pentest.sqlite_path)
    runs = recon.list_recon_runs(mission_id=mission_id, limit=500)
    outcome = []
    for item in items:
        if item.get('stage6_result') is None:
            continue
        intake = item['record']['intake']
        intake_id = intake['intake_id']
        existing = wpt.get_handoff(intake_id)
        if existing is not None and existing.get('delivery_status') == 'DELIVERED':
            receipt = _receipt(intake, item['stage6_result']['record'], existing)
            outcome.append({'status': 'delivered', 'intake_id': intake_id, 'replayed': True, 'wpt_receipt_status': receipt})
            if os.getenv('APTS_AUTONOMOUS_WPT_CTI_DELIVERY','') == '1':
                from .mission_wpt_cti_delivery import build_delivery, publish
                try:
                    outcome.append(publish(build_delivery(intake, item['stage6_result']['record'], existing)))
                except Exception as exc:
                    LOGGER.warning('Verified CTI delivery deferred for %s: %s', intake_id, type(exc).__name__)
            continue
        context = {**intake, 'orchestration_id': item['record']['authority_snapshot']['orchestration_id']}
        matches = [(run, action) for run in runs for action in _match_action(run, context)]
        # Never guess a parent from an ambiguous action reference.
        initial = (existing is not None and existing.get('record', {}).get('schema_version') == 'apts-wpt-recon-initial-event-v1') or not any(run.get('orchestration_id') == context['orchestration_id'] for run in runs)
        if len(matches) != 1 and not initial:
            outcome.append({'status': 'deferred', 'intake_id': intake_id,
                            'reason': 'RECON_PARENT_ACTION_NOT_UNIQUE'})
            continue
        request = {'schema_version': 'apts-wpt-recon-initial-request-v1'} if initial else {
            'schema_version': 'apts-wpt-recon-handoff-request-v1',
            'parent_recon_run_id': matches[0][0]['recon_run_id'], 'action_id': matches[0][1]['action_id'],
        }
        response = wpt.handoff_to_recon(intake_id, request)
        receipt = _receipt(intake, item['stage6_result']['record'], response) if response['delivery_status'] == 'DELIVERED' else 'PENDING'
        outcome.append({'status': response['status'], 'intake_id': intake_id,
                        'delivery_status': response['delivery_status'],
                        'wpt_receipt_status': receipt,
                        'execution_authorized_by_handoff': False})
        if response['status'] == 'delivered' and os.getenv('APTS_AUTONOMOUS_WPT_CTI_DELIVERY','') == '1':
            from .mission_wpt_cti_delivery import build_delivery, publish
            try:
                outcome.append(publish(build_delivery(intake, item['stage6_result']['record'], response)))
            except Exception as exc:
                LOGGER.warning('Verified CTI delivery deferred for %s: %s', intake_id, type(exc).__name__)
    return outcome


def sweep(service) -> None:
    if not enabled():
        return
    offset, ids = 0, []
    while True:
        page = service.list_missions(state='RUNNING', limit=100, offset=offset)
        ids.extend(row['mission_id'] for row in page['missions'])
        offset += len(page['missions'])
        if not page['missions'] or offset >= page['mission_count']:
            break
    for mid in ids:
        try:
            deliver(service, mid)
        except Exception:
            LOGGER.exception('Verified WPT -> Recon delivery deferred mission=%s', mid)
