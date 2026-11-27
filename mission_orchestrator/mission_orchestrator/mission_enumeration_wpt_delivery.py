"""Autonomous CTI-derived enumeration outbox. Stage 6 retains execution authority."""
import logging

from execution_subsystem.enumeration_delivery_repository import EnumerationDeliveryRepository
from execution_subsystem.enumeration_followup_contract import build_intake
from execution_subsystem.wpt_intake_service import WPTIntakeService
from mission_orchestrator.canonical import sha256_hex

LOGGER = logging.getLogger(__name__)


def _result_receipt(request, wpt, pentest, repository, state):
    """Persist agent acceptance before publishing; a lost callback is replayable."""
    if state.get('enum_receipt_status') == 'DELIVERED':
        return
    state['enum_receipt_status'] = 'PENDING'
    try:
        from execution_subsystem.wpt_job_callback import publish_enumeration_receipt
        final = wpt.repository.get_result(request['intake_id'])
        acknowledgement = pentest.accept_wpt_result(request['intake_id'], source_repository=wpt.repository)
        state['enum_acknowledgement'] = acknowledgement
        repository.save(request, state)
        receipt = publish_enumeration_receipt(request, final['record'], acknowledgement)
        if receipt.get('status') != 'DELIVERED' or receipt.get('delivery_id') != acknowledgement['delivery_id']:
            raise ValueError('WPT_ENUMERATION_RECEIPT_ACK_REQUIRED')
        state['enum_receipt_status'] = 'DELIVERED'
    except Exception as exc:
        LOGGER.warning('Enumeration result receipt deferred intake=%s reason=%s',
                       request['intake_id'], type(exc).__name__)


def deliver(service, mission_id, *, pentest=None, wpt=None, repository=None, sender=None):
    from pentest_subsystem.enumeration import EnumerationAgentService
    from pentest_subsystem.web_ui import cti_enumeration_context_for_recon_run
    from .gss_scope_sync import fetch
    from .mission_wpt_inbox_delivery import deliver as inbox
    from .mission_wpt_preparation import _start_stage6_runtime, _reconcile_stage6_result
    from execution_subsystem.wpt_job_callback import publish_job_status
    pentest = pentest or EnumerationAgentService()
    wpt = wpt or WPTIntakeService()
    repository = repository or EnumerationDeliveryRepository()
    sender = sender or inbox
    outcomes = []
    for run in pentest.list_enumeration_runs(mission_id=mission_id, limit=500):
        if not run['request'].get('metadata', {}).get('cti_intake_id'):
            continue
        try:
            request = build_intake(run)
        except ValueError:
            continue  # Empty/non-URL evidence does not justify target enumeration.
        state = {'delivery_status': 'NOT_SENT', 'execution_status': 'NOT_STARTED',
                 'reason_code': 'AWAITING_DELIVERY', 'execution_id': None, 'wpt_job_id': None}
        # Preserve a durable acknowledgement/result even if authority later expires.
        previous = next((row for row in repository.list() if row['request']['intake_id'] == request['intake_id']), None)
        if previous is None:
            # Preserve already accepted legacy identities; never mutate an immutable intake.
            for old in repository.list():
                if old['request']['enumeration_context']['enumeration_run_id'] != run['enumeration_run_id']:
                    continue
                accepted = old['state']['delivery_status'] == 'DELIVERED'
                if not accepted and hasattr(wpt, 'repository'):
                    accepted = wpt.repository.get(old['request']['intake_id']) is not None
                if accepted:
                    request, previous = old['request'], old
                    break
        if previous:
            state.update(previous['state'])
            if (state['execution_status'] == 'RESULT_RECEIVED'
                    and state.get('enum_receipt_status') == 'DELIVERED'):
                outcomes.append({'intake_id': request['intake_id'], **state})
                continue
        try:
            if hasattr(wpt, 'repository'):
                final = wpt.repository.get_result(request['intake_id'])
                if final:
                    from execution_subsystem.wpt_job_callback import publish_stage6_result, publish_job_status
                    from .mission_wpt_preparation import _runtime_authorization_provenance
                    try:
                        callback = publish_stage6_result(request, final['record'])
                    except Exception:
                        callback = {'status': 'PENDING'}
                    if callback.get('status') != 'DELIVERED':
                        # The result callback is refused until the job carries its
                        # authorization provenance. A fast attempt can reach SUCCEEDED
                        # before any authorized job-status callback, stranding the
                        # sealed result. Replay the authorized provenance from the
                        # terminal attempt, then re-seal.
                        provenance = _runtime_authorization_provenance(final['record'].get('execution_id'))
                        if provenance:
                            try:
                                publish_job_status(request, provenance, 'RUNNING')
                                callback = publish_stage6_result(request, final['record'])
                            except Exception:
                                callback = {'status': 'PENDING'}
                    if callback.get('status') == 'DELIVERED' and state['delivery_status'] == 'DELIVERED':
                        state.update(execution_status='RESULT_RECEIVED',reason_code=None)
                        _result_receipt(request, wpt, pentest, repository, state)
                        repository.save(request,state)
                        outcomes.append({'intake_id':request['intake_id'],**state})
                        continue
            if state['execution_status'] == 'RESULT_RECEIVED':
                # Receipt recovery must never re-admit completed work, even if
                # the evidence store or result callback is temporarily unavailable.
                state['enum_receipt_status'] = 'PENDING'
                repository.save(request, state)
                outcomes.append({'intake_id': request['intake_id'], **state})
                continue
            if service.get_mission_state(mission_id)['mission_state']['state'] != 'RUNNING':
                raise ValueError('MISSION_NOT_RUNNING')
            contract = service.get_mission_scope_contract(mission_id)['contract']
            meta = contract.get('metadata', {}).get('gss_scope_sync') or {}
            if not meta.get('source_snapshot_sha256'):
                raise ValueError('GSS_SCOPE_SOURCE_REQUIRED')
            if sha256_hex(fetch(service, mission_id)) != meta['source_snapshot_sha256']:
                raise ValueError('GSS_SCOPE_CHANGED')
            ctx = cti_enumeration_context_for_recon_run(pentest, run['recon_run_id'])
            if (ctx['cti_context']['lineage']['intake_id'] != request['enumeration_context']['source_cti_intake_id']
                    or ctx['cti_context']['enrichment']['source_result_sha256'] != request['enumeration_context']['source_result_sha256']):
                raise ValueError('CTI_SOURCE_CHANGED')
            # Resolves exact task, current scope/RoE/budgets and CTI source binding.
            submitted = wpt.submit(request)
            admission = submitted.get('stage6_admission') or {}
            acknowledgement = sender(request)
            if (acknowledgement.get('status') != 'DELIVERED'
                    or acknowledgement.get('intake_id') != request['intake_id']):
                raise ValueError('WPT_INBOX_ACKNOWLEDGEMENT_REQUIRED')
            acknowledged_before = state['delivery_status'] == 'DELIVERED'
            state.update(delivery_status='DELIVERED', execution_status='AWAITING_AUTHORIZATION',
                         reason_code=admission.get('reason_code'), execution_id=admission.get('execution_id'))
            if not acknowledged_before:
                repository.save(request, state)  # Crash after ACK cannot erase delivered status.
            capability = submitted['record']['authority_snapshot']['execution_status']
            if capability != 'EXECUTABLE':
                state.update(execution_status='BLOCKED', reason_code='WPT_ENUMERATION_ADAPTER_UNAVAILABLE')
            elif admission.get('status') != 'REQUEST_CREATED':
                state.update(execution_status='BLOCKED' if admission.get('status') == 'BLOCKED' else 'AWAITING_AUTHORIZATION',
                             reason_code=admission.get('reason_code') or 'STAGE6_REQUEST_PENDING')
            else:
                job = wpt._publish_stage6_job(request, admission)
                if job.get('status') != 'DELIVERED':
                    state.update(reason_code='WPT_JOB_DELIVERY_PENDING')
                else:
                    state['wpt_job_id'] = job.get('job_id')
                    runtime = _start_stage6_runtime(request, admission)
                    status = runtime.get('status')
                    state.update(execution_status={'SUCCEEDED': 'AWAITING_RESULT', 'RUNNING': 'RUNNING',
                        'FAILED': 'FAILED', 'TIMEOUT': 'FAILED', 'ABORTED': 'BLOCKED', 'BLOCKED': 'BLOCKED',
                        'DENIED': 'BLOCKED', 'CANCELLED': 'CANCELLED'}.get(status, 'AWAITING_AUTHORIZATION'),
                        reason_code=runtime.get('reason_code'), attempt_id=runtime.get('attempt_id'))
                    # Authorization provenance must reach the WPT job before Stage 6
                    # can seal a SUCCEEDED result; without it the result callback is
                    # refused (job has no authorization_id) and the job is stranded at
                    # AWAITING_STAGE6. A fast attempt can race AUTHORIZED->SUCCEEDED
                    # between sweeps, so publish the authorized lifecycle for SUCCEEDED
                    # too, as RUNNING (the last pre-terminal state it genuinely passed
                    # through). The terminal result itself is delivered by reconcile.
                    job_status = {'SUCCEEDED': 'RUNNING', 'AUTHORIZED': 'AUTHORIZED',
                        'DISPATCHED': 'DISPATCHED', 'RUNNING': 'RUNNING', 'FAILED': 'FAILED',
                        'TIMEOUT': 'FAILED', 'ABORTED': 'FAILED', 'BLOCKED': 'BLOCKED',
                        'CANCELLED': 'CANCELLED'}.get(status)
                    if (job_status and runtime.get('execution_id') and not (
                            job_status in {'AUTHORIZED', 'DISPATCHED', 'RUNNING'}
                            and not runtime.get('authorization_id'))):
                        try:
                            publish_job_status(request, runtime, job_status)
                        except Exception as exc:
                            LOGGER.info('Enumeration WPT job status deferred intake=%s status=%s reason=%s',
                                        request['intake_id'], job_status, type(exc).__name__)
                    result = _reconcile_stage6_result(wpt, request, runtime)
                    if result.get('status') == 'DELIVERED':
                        state.update(execution_status='RESULT_RECEIVED', reason_code=None)
                        _result_receipt(request, wpt, pentest, repository, state)
        except Exception as exc:
            # Failed delivery is retryable. Never infer delivery from run_status or enum_status.
            reason = (str(exc)[:180] if type(exc).__name__ in {'ValueError', 'ExecutionSourceRejected'}
                      else type(exc).__name__)
            if type(exc).__name__ == 'ExecutionRequestConflict':
                reason = ('WPT_REQUEST_BUDGET_RESERVED' if 'budget is already reserved' in str(exc)
                          else 'WPT_INTAKE_IDENTITY_CONFLICT')
            state.update(execution_status='BLOCKED' if isinstance(exc, (ValueError, RuntimeError)) else 'PENDING',
                         reason_code=reason)
            LOGGER.warning('Enumeration WPT delivery deferred intake=%s reason=%s', request['intake_id'], state['reason_code'])
        repository.save(request, state)
        outcomes.append({'intake_id': request['intake_id'], **state})
    return outcomes


def sweep(service):
    from .mission_cti_enumeration_delivery import enabled
    if not enabled():
        return
    offset = 0
    while True:
        page = service.list_missions(state='RUNNING', limit=100, offset=offset)
        for mission in page['missions']:
            try:
                deliver(service, mission['mission_id'])
            except Exception:
                LOGGER.exception('Enumeration WPT sweep deferred mission=%s', mission['mission_id'])
        offset += len(page['missions'])
        if not page['missions'] or offset >= page['mission_count']:
            break
