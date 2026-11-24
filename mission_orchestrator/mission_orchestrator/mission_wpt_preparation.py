"""Mission RUNNING -> authoritative Recon/WPT measurement intake.

Submits governance-checked proposals for RUNNING tasks to the owned Stage 6
runtime and reconciles sealed results. Stage 6 alone authorizes and performs
target I/O; Mission never manufactures an ALLOW decision.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from execution_subsystem.proposal_source import PentestProposalSource
from execution_subsystem.wpt_intake_service import WPTIntakeService
from mission_orchestrator.canonical import sha256_hex

LOGGER = logging.getLogger(__name__)
RECON_SCOPE_TARGET_HASH_DOMAIN = 'APTS_RECON_MISSION_SCOPE_TARGET_V1'
STAGE6_RUNTIME_START_SCHEMA = 'apts-execution-runtime-start-v1'

# A dead or unreachable target makes the fixed fingerprint/enumeration adapter
# end in a terminal failure whose reason is a generic collector/connection code.
# To an operator these all mean the same thing -- the target did not answer --
# so they are surfaced to WPT as one explicit, dedicated job-status notification
# instead of an opaque internal code that leaves the job looking stuck.
TARGET_UNREACHABLE_REASONS = frozenset({
    'WEB_PROFILE_NO_RESPONSE',
    'TARGET_DNS_RESOLUTION_FAILED',
    'ADAPTER_FAILURE:ConnectionRefusedError',
    'ADAPTER_FAILURE:ConnectionResetError',
})
WPT_TARGET_UNREACHABLE_REASON = 'WPT_TARGET_UNREACHABLE'


def target_unreachable_notice(runtime: dict) -> dict | None:
    """Map a terminal, dead-target runtime outcome to an explicit WPT notification.

    Returns the job-status ``{status, reason_code}`` to publish to the WPT inbox
    when the Stage 6 runtime failed because the target was unreachable, or
    ``None`` for any other outcome. Pure: it reads the runtime summary only and
    never performs or implies target I/O.
    """
    if not isinstance(runtime, dict):
        return None
    status = runtime.get('status')
    reason = runtime.get('reason_code')
    if status in {'FAILED', 'TIMEOUT', 'ABORTED', 'BLOCKED', 'DENIED'} and reason in TARGET_UNREACHABLE_REASONS:
        return {'status': 'FAILED',
                'reason_code': (WPT_TARGET_UNREACHABLE_REASON + ':' + str(reason))[:180]}
    return None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Stage 6 runtime redirect rejected')


def _start_stage6_runtime(intake: dict, admission: dict) -> dict:
    """Start the request-created WPT execution through the Stage 6.5 runtime API.

    The runtime owns fresh Governance checks, durable reservation, the adapter,
    and target I/O. Mission only submits the exact immutable execution identity; Stage 6.5 performs fresh authorization.
    """
    if admission.get('status') != 'REQUEST_CREATED':
        return {'status': 'BLOCKED', 'reason_code': 'STAGE6_REQUEST_NOT_CREATED',
                'execution_id': admission.get('execution_id'),
                'execution_authorized': False, 'target_io_performed': False}

    base = os.getenv('APTS_STAGE6_RUNTIME_URL', '').strip().rstrip('/')
    if not base:
        return {'status': 'PENDING', 'reason_code': 'STAGE6_RUNTIME_URL_NOT_CONFIGURED',
                'execution_id': admission.get('execution_id'),
                'execution_authorized': False, 'target_io_performed': False}
    parsed = urlparse(base)
    if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        return {'status': 'BLOCKED', 'reason_code': 'STAGE6_RUNTIME_URL_MUST_USE_HTTPS_OR_LOOPBACK',
                'execution_id': admission.get('execution_id'),
                'execution_authorized': False, 'target_io_performed': False}

    execution_id = admission.get('execution_id')
    envelope_sha256 = admission.get('envelope_sha256')
    if (not isinstance(execution_id, str) or not execution_id.startswith('exec-')
            or not isinstance(envelope_sha256, str) or len(envelope_sha256) != 64
            or any(c not in '0123456789abcdef' for c in envelope_sha256)):
        return {'status': 'BLOCKED', 'reason_code': 'STAGE6_ADMISSION_BINDING_INVALID',
                'execution_authorized': False, 'target_io_performed': False}

    base_seed=intake['intake_id']+'\0'+execution_id+'\0'+envelope_sha256
    if admission.get('runtime_scope_sha256'):
        base_seed += '\0scope-' + admission['runtime_scope_sha256']
    seed=hashlib.sha256(base_seed.encode()).hexdigest()[:32]
    def post(path,payload):
        request=Request(base+path,data=json.dumps(payload,separators=(',',':')).encode(),
            headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'APTS-Mission-WPT-Runtime/2.0'},method='POST')
        with build_opener(ProxyHandler({}),_NoRedirect()).open(request,timeout=8) as response:
            raw=response.read(1048577)
            if len(raw)>1048576:raise RuntimeError('Stage 6 response exceeds limit')
            data=json.loads(raw.decode('utf-8'))
            if not isinstance(data,dict) or response.status not in (200,201,202):raise RuntimeError('Invalid Stage 6 response')
            return data
    def error_text(exc):
        try:
            raw=exc.read(4097);value=json.loads(raw.decode()) if len(raw)<=4096 else {}
            return str(value.get('error') or value.get('error_code') or 'HTTP_'+str(exc.code))[:180]
        except (ValueError,UnicodeError):return 'HTTP_'+str(exc.code)
    try:
        # Stage 6.5 performs fresh GSS authorization and durable admission;
        # the obsolete Stage 6.3 gateway endpoint rejects new receipts.
        data=None
        for epoch in range(5):
            epoch_seed=seed if epoch==0 else hashlib.sha256((base_seed+'\0epoch-'+str(epoch)).encode()).hexdigest()[:32]
            try:
                data=post('/api/execution/runtime/attempts',{
                    'schema_version':STAGE6_RUNTIME_START_SCHEMA,'invocation_request_id':'toolreq-wpt-'+epoch_seed,
                    'idempotency_key':'idem-wpt-runtime-'+epoch_seed,'execution_id':execution_id,
                    'envelope_sha256':envelope_sha256,'requested_by':'MISSION_AUTONOMOUS_WPT_WORKER'})
                break
            except HTTPError as exc:
                reason=error_text(exc)
                # Only advance an identity that never acquired a runtime attempt.
                # Runtime independently blocks a consumed RESERVED legacy claim.
                if exc.code==409 and 'HISTORICAL_ADAPTER_INTAKE_NOT_RUNTIME_ADMISSION' in reason:continue
                return {'status':'BLOCKED' if exc.code==409 else 'PENDING','reason_code':reason,
                    'execution_id':execution_id,'execution_authorized':False,'target_io_performed':False}
        if data is None:raise RuntimeError('STAGE6_RUNTIME_IDENTITY_EPOCHS_EXHAUSTED')
    except HTTPError as exc:
        return {'status':'PENDING','reason_code':error_text(exc),'execution_id':execution_id,
                'execution_authorized':False,'target_io_performed':False}
    except (URLError,TimeoutError,OSError,ValueError,RuntimeError) as exc:
        return {'status':'PENDING','reason_code':str(exc)[:180],'execution_id':execution_id,
                'execution_authorized':False,'target_io_performed':False}

    # The original idempotent start remains terminal after an explicit runtime
    # retry or recovery. Reconcile the latest bound attempt instead of replaying
    # its failure forever. Reading history never creates or retries target I/O.
    if data.get('state') in {'FAILED','TIMEOUT','ABORTED'}:
        try:
            history_request=Request(base+'/api/execution/runtime/attempts?execution_id='+execution_id,
                                    headers={'Accept':'application/json'})
            with build_opener(ProxyHandler({}),_NoRedirect()).open(history_request,timeout=8) as response:
                raw=response.read(1048577)
                if len(raw)>1048576:raise RuntimeError('Stage 6 history exceeds limit')
                history=json.loads(raw.decode('utf-8'))
            attempts=history.get('attempts') or []
            if attempts:
                latest=attempts[-1]
                binding=(latest.get('record') or {}).get('runtime_intake') or {}
                if (binding.get('execution_id')==execution_id
                        and binding.get('envelope_sha256')==envelope_sha256):
                    data=latest
        except (URLError,TimeoutError,OSError,ValueError,RuntimeError):
            pass  # Retain the known original outcome until history is available.
    events = data.get('events') or []
    reason = (events[-1].get('data') or {}).get('reason_code') if events else None
    transient = {'ADAPTER_WALL_TIMEOUT', 'TARGET_DNS_RESOLUTION_FAILED',
                 'ADAPTER_FAILURE:ConnectionRefusedError', 'ADAPTER_FAILURE:ConnectionResetError'}
    record = data.get('record') or {}
    # Two distinct drivers for a fresh, independently-authorized next attempt,
    # both bound to the exact latest terminal head. A transient FAILED/TIMEOUT
    # is an automatic retry; a proven-no-I/O ABORTED (a stalled source read or a
    # lost supervisor heartbeat before any target I/O) is an explicit recovery.
    # Without this the pipeline would otherwise wait on STAGE6_SUCCESS_REQUIRED
    # forever and never make a second attempt. Both go through the same explicit
    # retry endpoint, which obtains fresh GSS authorization for the new attempt.
    transient_retry = (data.get('state') in {'FAILED', 'TIMEOUT'} and reason in transient
                       and data.get('retry_eligible_by_result') is True)
    aborted_recovery = (data.get('state') == 'ABORTED'
                        and data.get('recovery_eligible_by_result') is True)
    if (transient_retry or aborted_recovery) and record.get('attempt_number', 3) < 3:
        marker = '\0recover-' if aborted_recovery else '\0retry-'
        retry_seed = hashlib.sha256((base_seed + marker + data['attempt_id']
                                     + '\0' + data['head_sha256']).encode()).hexdigest()[:32]
        try:
            data = post('/api/execution/runtime/retries', {
                'schema_version': 'apts-execution-runtime-retry-v1',
                'invocation_request_id': 'toolreq-wpt-' + retry_seed,
                'idempotency_key': 'idem-wpt-runtime-' + retry_seed,
                'execution_id': execution_id, 'envelope_sha256': envelope_sha256,
                'requested_by': 'MISSION_AUTONOMOUS_WPT_WORKER',
                'retry_of_attempt_id': data['attempt_id'],
                'expected_head_sha256': data['head_sha256']})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError):
            pass  # Publish the known terminal result; a later sweep can reconcile.
    attempt = data.get('attempt') if isinstance(data.get('attempt'), dict) else {}
    events=data.get('events') or []
    authorization_id=next((e.get('data',{}).get('authorization_id') for e in events if isinstance(e,dict) and e.get('event_type')=='AUTHORIZED'),None)
    reason=(events[-1].get('data') or {}).get('reason_code') if events and isinstance(events[-1],dict) else None
    return {'status': data.get('state') or attempt.get('state') or data.get('status', 'PENDING'),
            'authorization_id':authorization_id,'reason_code':reason,
            'execution_id': execution_id,
            'attempt_id': attempt.get('attempt_id') or data.get('attempt_id'),
            'created': data.get('created'),
            'runtime_attempt_number': (data.get('record') or {}).get('attempt_number'),
            'runtime_attempt_id': data.get('attempt_id') or attempt.get('attempt_id'),
            'execution_authorized': False,
            'target_io_performed': bool(data.get('target_network_io_performed', False))}


def _runtime_authorization_provenance(execution_id) -> dict | None:
    """Read-only authorization provenance of the latest SUCCEEDED runtime attempt.

    Lets the enumeration outbox deliver the authorized job-status callback that a
    sealed result requires, when a fast attempt reached SUCCEEDED before any
    authorized callback was published. Reads attempt history only; it never
    performs target I/O and never creates or retries an attempt.
    """
    if not isinstance(execution_id, str) or not execution_id.startswith('exec-'):
        return None
    base = os.getenv('APTS_STAGE6_RUNTIME_URL', '').strip().rstrip('/')
    if not base:
        return None
    parsed = urlparse(base)
    if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        return None
    try:
        request = Request(base + '/api/execution/runtime/attempts?execution_id=' + quote(execution_id, safe=''),
                          headers={'Accept': 'application/json'})
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=8) as response:
            raw = response.read(1048577)
            if len(raw) > 1048576:
                return None
            history = json.loads(raw.decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError):
        return None
    for attempt in reversed(history.get('attempts') or []):
        if not isinstance(attempt, dict) or attempt.get('state') != 'SUCCEEDED':
            continue
        binding = (attempt.get('record') or {}).get('runtime_intake') or {}
        if binding.get('execution_id') != execution_id:
            continue
        events = attempt.get('events') or []
        authorization_id = next((e.get('data', {}).get('authorization_id') for e in events
                                 if isinstance(e, dict) and e.get('event_type') == 'AUTHORIZED'), None)
        if not authorization_id:
            continue
        record = attempt.get('record') or {}
        return {'execution_id': execution_id, 'authorization_id': authorization_id,
                'runtime_attempt_number': record.get('attempt_number'),
                'runtime_attempt_id': attempt.get('attempt_id'),
                'reason_code': 'STAGE6_AUTHORIZATION_PROVENANCE'}
    return None


# Failures that retrying cannot fix: the sealed Stage 6 evidence itself is
# rejected by the integrity/validation gate. Transient lookup failures are not.
_PERMANENT_RESULT_REJECTIONS = frozenset({
    'ExecutionRequestIntegrityError', 'ExecutionSourceRejected', 'ExecutionRequestValidationError'})
_PERMANENT_RESULT_CACHE: dict = {}


def _reconcile_stage6_result(wpt, intake: dict, runtime: dict) -> dict:
    """Retry delivery of a successful, ledger-verified result without re-scanning."""
    if runtime.get('status') != 'SUCCEEDED':
        return {'status': 'PENDING', 'reason_code': 'STAGE6_SUCCESS_REQUIRED'}
    if not runtime.get('execution_id') or not runtime.get('attempt_id'):
        return {'status': 'PENDING', 'reason_code': 'STAGE6_RESULT_BINDING_REQUIRED'}
    key = (intake['intake_id'], runtime['execution_id'], runtime['attempt_id'])
    if key in _PERMANENT_RESULT_CACHE:
        # Same sealed attempt, same verdict: do not re-run the verification
        # on every sweep. A process restart re-evaluates once (e.g. after a fix).
        return dict(_PERMANENT_RESULT_CACHE[key])
    try:
        result = wpt.submit_stage6_result({
            'schema_version': 'apts-wpt-stage6-result-reference-v1',
            'intake_id': intake['intake_id'],
            'execution_id': runtime['execution_id'],
            'attempt_id': runtime['attempt_id'],
        })
        return result['wpt_job_delivery']
    except Exception as exc:
        # The service independently checks terminal success, sealed evidence,
        # and exact mission/task/target identity. Never publish unverified data.
        name = type(exc).__name__
        if name in _PERMANENT_RESULT_REJECTIONS:
            # Same return contract as any non-delivery (PENDING + reason_code);
            # permanence is expressed by the cache (no re-verification) and one ERROR log.
            outcome = {'status': 'PENDING', 'reason_code': name[:80]}
            _PERMANENT_RESULT_CACHE[key] = outcome
            LOGGER.error('Stage 6 result permanently rejected intake=%s execution=%s attempt=%s: %s',
                         intake['intake_id'], runtime['execution_id'], runtime['attempt_id'], str(exc)[:180])
            return dict(outcome)
        return {'status': 'PENDING', 'reason_code': name[:80]}


def _unobserved_recon_targets(conn, mission_id: str, scope: dict, source_sha: str) -> list[dict]:
    """Read immutable, hash-bound Recon declarations; fail closed on drift."""
    try:
        rows = conn.execute(
            'SELECT target_key,record_json,record_sha256 FROM pentest_recon_scope_targets '
            'WHERE mission_id=? ORDER BY target_key LIMIT 501', (mission_id,)
        ).fetchall()
    except Exception as exc:
        raise ValueError('RECON_SCOPE_TARGET_STORE_UNAVAILABLE') from exc
    if len(rows) > 500:
        raise ValueError('RECON_SCOPE_TARGET_LIMIT_EXCEEDED')
    metadata = (scope.get('metadata') or {}).get('gss_scope_sync') or {}
    declared = {
        (item.get('target_type'), item.get('target_value'), item.get('environment'))
        for item in scope.get('scope', {}).get('targets', [])
        if isinstance(item, dict)
    }
    result = []
    for row in rows:
        try:
            record = json.loads(row['record_json'])
            digest = sha256_hex({'hash_domain': RECON_SCOPE_TARGET_HASH_DOMAIN, 'record': record})
            target = record['target']
            key = (target['target_type'], target['target_value'], target['environment'])
            semantics = record['semantics']
            if (record.get('schema_version') != 'apts-recon-mission-scope-target-v1'
                    or record.get('mission_id') != mission_id
                    or record.get('target_key') != row['target_key']
                    or digest != row['record_sha256']):
                raise ValueError('RECON_SCOPE_TARGET_INTEGRITY_OR_SCOPE_MISMATCH')
            # Older, still-valid declarations are immutable history. Ignore
            # them when their exact GSS source revision is no longer current.
            if (record.get('source_snapshot_sha256') != source_sha
                    or record.get('scope_contract_id') != metadata.get('source_scope_contract_id')
                    or record.get('scope_version') != metadata.get('source_version')
                    or record.get('scope_contract_hash') != metadata.get('source_contract_hash')):
                continue
            if (record.get('status') != 'READY_FOR_COLLECTION'
                    or semantics != {'target_is_observed': False, 'execution_authorized': False,
                                     'recon_run_created': False, 'external_network_io_performed': False}
                    or key not in declared):
                raise ValueError('RECON_SCOPE_TARGET_INTEGRITY_OR_SCOPE_MISMATCH')
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('RECON_SCOPE_TARGET_RECORD_INVALID') from exc
        result.append({'target_key': row['target_key'], 'target_sha256': digest,
                       'target': target, 'status': 'READY_FOR_COLLECTION'})
    return result


def enabled() -> bool:
    # Intake creates a scope-checked proposal only; it never grants execution
    # authority or performs target I/O. Enabled by default so RUNNING missions
    # do not silently stop before the WPT observability boundary.
    return os.getenv('APTS_AUTONOMOUS_WPT_INTAKE', '1').strip() != '0'


def propose(service, mission_id: str, *, wpt=None, pentest=None) -> list[dict]:
    state = service.get_mission_state(mission_id)['mission_state']['state']
    if state != 'RUNNING':
        return [{'status': 'deferred', 'reason': 'MISSION_NOT_RUNNING'}]
    scope = service.get_mission_scope_contract(mission_id)['contract']
    src = (scope.get('metadata') or {}).get('gss_scope_sync')
    if not isinstance(src, dict) or not src.get('source_snapshot_sha256'):
        return [{'status': 'deferred', 'reason': 'GSS_SCOPE_SOURCE_REQUIRED'}]
    from .gss_scope_sync import fetch
    if sha256_hex(fetch(service, mission_id)) != src['source_snapshot_sha256']:
        return [{'status': 'deferred', 'reason': 'GSS_SCOPE_CHANGED'}]
    pentest = pentest or PentestProposalSource()
    with closing(pentest._connect()) as conn:
        pentest._migration(conn)  # read-only repository schema guard
        try:
            recon_targets = _unobserved_recon_targets(conn, mission_id, scope, src['source_snapshot_sha256'])
        except ValueError as exc:
            return [{'status': 'deferred', 'reason': str(exc)}]
        tasks = conn.execute('SELECT upstream_task_id FROM pentest_tasks WHERE mission_id=? ORDER BY upstream_task_id LIMIT 101',
                             (mission_id,)).fetchall()
    # Only URL declarations that Recon has received and has not yet observed.
    recon_targets = [item for item in recon_targets if item['target']['target_type'] == 'URL']
    if not recon_targets:
        return [{'status': 'deferred', 'reason': 'NO_UNOBSERVED_RECON_URL_TARGETS'}]
    if len(tasks) > 100:
        return [{'status': 'deferred', 'reason': 'PENTEST_TASK_LIMIT_EXCEEDED'}]
    if not tasks:
        return [{'status': 'deferred', 'reason': 'AWAITING_PENTEST_TASK_MATERIALIZATION'}]
    wpt = wpt or WPTIntakeService()
    results = []
    for row in tasks:
        task_id = row['upstream_task_id']
        for source in recon_targets:
            kind, url = source['target']['target_type'], source['target']['target_value']
            digest = hashlib.sha256((mission_id + '\0' + task_id + '\0' + source['target_key'] + '\0' + source['target_sha256'] + '\0fingerprinting').encode()).hexdigest()[:40]
            request = {
                'schema_version': 'apts-wpt-governed-intake-v2',
                'intake_id': 'wptreq-auto-' + digest,
                'idempotency_key': 'idem-wpt-auto-' + digest,
                'mission_id': mission_id,
                'task_id': task_id,
                'target': {'target_type': kind, 'target_value': url},
                'recon_target_key': source['target_key'],
                'recon_target_sha256': source['target_sha256'],
                'recon_target_status': source['status'],
                'target_is_observed': False,
                'profile': 'fingerprinting',
            }
            try:
                submitted = wpt.submit(request)
                record = submitted['record']
                delivery = {'status': 'WPT_INBOX_NOT_CONFIGURED'}
                try:
                    from .mission_wpt_inbox_delivery import deliver
                    delivery = deliver(request)
                except Exception as exc:
                    LOGGER.info('WPT inbox delivery pending for %s: %s', request['intake_id'], type(exc).__name__)
                    delivery = {'status': 'DELIVERY_PENDING', 'reason': type(exc).__name__}
                if delivery.get('status') != 'DELIVERED':
                    LOGGER.warning('WPT intake persisted in Mission but not received by WPT intake_id=%s status=%s',
                                   request['intake_id'], delivery.get('status', 'UNKNOWN'))
                admission = submitted.get('stage6_admission', {})
                runtime = {'status': 'PENDING', 'reason_code': 'WPT_INTAKE_DELIVERY_REQUIRED',
                           'execution_id': admission.get('execution_id'),
                           'execution_authorized': False, 'target_io_performed': False}
                job_delivery = {'status': 'PENDING', 'reason_code': 'WPT_INTAKE_DELIVERY_REQUIRED',
                                'target_io_performed': False}
                # The first job callback made by WPTIntakeService.submit() can
                # arrive before WPT has durably received the intake. Replay it
                # only after the inbox acknowledges the exact record. Otherwise
                # WPT keeps showing AWAITING_STAGE6 with zero jobs, and the
                # Stage 6 result has no job identity to update.
                if delivery.get('status') == 'DELIVERED':
                    job_delivery = wpt._publish_stage6_job(request, admission)
                    if job_delivery.get('status') == 'DELIVERED':
                        # Admission is only a gate; Stage 6.5 performs fresh
                        # Governance checks and owns any target I/O.
                        runtime_admission = dict(admission)
                        binding = service.repository.get_current_governance_binding(mission_id)
                        if binding and (binding.get('binding', {}).get('metadata') or {}).get('wpt_execution_projection_version') == 1:
                            runtime_admission['runtime_scope_sha256'] = binding['canonical_sha256']
                        runtime = _start_stage6_runtime(request, runtime_admission)
                    else:
                        runtime = {'status': 'PENDING',
                                   'reason_code': 'WPT_STAGE6_JOB_DELIVERY_REQUIRED',
                                   'execution_id': admission.get('execution_id'),
                                   'execution_authorized': False,
                                   'target_io_performed': False}
                runtime_status = {'BLOCKED':'BLOCKED', 'DENIED':'BLOCKED',
                    'FAILED':'FAILED', 'TIMEOUT':'FAILED', 'ABORTED':'FAILED',
                    'CANCELLED':'CANCELLED', 'RUNNING':'RUNNING',
                    'AUTHORIZED':'AUTHORIZED'}.get(runtime.get('status'))
                # A dead/unreachable target ends as a terminal FAILED whose reason
                # is the generic collector code. Replace it with one explicit,
                # dedicated reason so the WPT job shows "target unreachable" instead
                # of an opaque code, and is not mistaken for a job that hangs.
                notice = target_unreachable_notice(runtime)
                publish_runtime = runtime
                if notice is not None:
                    runtime_status = notice['status']
                    publish_runtime = {**runtime, 'reason_code': notice['reason_code']}
                    LOGGER.warning('WPT target unreachable mission=%s task=%s intake=%s reason=%s',
                                   mission_id, task_id, request['intake_id'], runtime.get('reason_code'))
                if runtime_status and runtime.get('execution_id'):
                    try:
                        from execution_subsystem.wpt_job_callback import publish_job_status
                        job_delivery = publish_job_status(request, publish_runtime, runtime_status)
                    except Exception as exc:
                        job_delivery = {'status':'PENDING', 'error_code':type(exc).__name__}
                result_delivery = _reconcile_stage6_result(wpt, request, runtime)
                results.append({'status': record['status'], 'created': submitted['created'],
                                'intake_id': request['intake_id'], 'mission_id': mission_id,
                                'task_id': task_id, 'target': request['target'],
                                'recon_target_key': source['target_key'],
                                'target_is_observed': False,
                                'wpt_delivery': delivery,
                                'stage6_job_delivery': job_delivery,
                                'capability_status': record['authority_snapshot']['execution_status'],
                                'stage6_admission': submitted.get('stage6_admission', {
                                    'status': 'PENDING', 'reason_code': 'STAGE6_ADMISSION_RESULT_UNAVAILABLE',
                                    'execution_authorized': False, 'gateway_admitted': False,
                                    'target_io_performed': False}),
                                'stage6_runtime': runtime,
                                'stage6_result_delivery': result_delivery,
                                'target_unreachable_notified': notice is not None,
                                'execution_authorized': False,
                                'target_io_performed': runtime.get('target_io_performed', False)})
            except Exception as exc:
                # Do not make a broad unverified proposal when per-task authority
                # resolution fails; this is commonly an unstarted task, a stale
                # orchestration, or a policy/RoE denial.
                LOGGER.warning('WPT intake deferred mission=%s task=%s target_key=%s error=%s',
                            mission_id, task_id, source['target_key'], type(exc).__name__)
                results.append({'status': 'deferred', 'task_id': task_id,
                                'target': {'target_type': kind, 'target_value': url},
                                'recon_target_key': source['target_key'],
                                # ExecutionSourceRejected uses stable policy text
                                # (for example, the exact task lifecycle gate).
                                # Other exceptions remain type-only so paths or
                                # secrets from lower layers are not written here.
                                'reason': (str(exc)[:180] if type(exc).__name__ == 'ExecutionSourceRejected'
                                           else type(exc).__name__),
                                'execution_authorized': False})
    return results


def prequeue_recon_targets(service, mission_id: str, *, pentest=None) -> list[dict]:
    """Queue exact Recon URLs in WPT before Pentest orchestration is active.

    This is a visibility/intake proposal only. It is bound to the immutable
    Recon declaration and planned Pentest orchestration ID, and cannot authorize
    Stage 6 or perform target I/O. WPT keeps it in AWAITING_PENTEST_TASK until
    the normal governed v2 delivery confirms that the task is active.
    """
    state = service.get_mission_state(mission_id)['mission_state']['state']
    if state not in {'PLANNING', 'REPLANNING', 'RUNNING'}:
        return [{'status': 'deferred', 'reason': 'MISSION_NOT_READY_FOR_RECON_INTAKE'}]
    scope = service.get_mission_scope_contract(mission_id)['contract']
    src = (scope.get('metadata') or {}).get('gss_scope_sync')
    if not isinstance(src, dict) or not src.get('source_snapshot_sha256'):
        return [{'status': 'deferred', 'reason': 'GSS_SCOPE_SOURCE_REQUIRED'}]
    from .gss_scope_sync import fetch
    authoritative = fetch(service, mission_id)
    if sha256_hex(authoritative) != src['source_snapshot_sha256']:
        return [{'status': 'deferred', 'reason': 'GSS_SCOPE_CHANGED'}]
    from .mission_routing_handoff_automation import automatic_recon_binding_policy
    policy_allowed, policy_reason = automatic_recon_binding_policy(scope, authoritative)

    planned = service.list_planned_tasks(mission_id).get('planned_tasks', [])
    task_ids = [row.get('planned_task_id') for row in planned
                if row.get('required_subsystem') == 'PENTEST'
                and str(row.get('task_key', '')).endswith('-pentest-orchestration')
                and isinstance(row.get('planned_task_id'), str)
                and row['planned_task_id'].startswith('ptask-')]
    if not task_ids:
        return [{'status': 'deferred', 'reason': 'PLANNED_PENTEST_TASK_REQUIRED'}]

    pentest = pentest or PentestProposalSource()
    with closing(pentest._connect()) as conn:
        pentest._migration(conn)
        try:
            recon_targets = _unobserved_recon_targets(
                conn, mission_id, scope, src['source_snapshot_sha256'])
        except ValueError as exc:
            return [{'status': 'deferred', 'reason': str(exc)}]

    recon_targets = [item for item in recon_targets
                     if item['target']['target_type'] == 'URL']
    if not recon_targets:
        return [{'status': 'deferred', 'reason': 'NO_UNOBSERVED_RECON_URL_TARGETS'}]

    from .mission_wpt_inbox_delivery import deliver
    results = []
    for task_id in task_ids:
        for source in recon_targets:
            target = source['target']
            digest = hashlib.sha256((mission_id + '\0' + task_id + '\0'
                + source['target_key'] + '\0' + source['target_sha256']
                + '\0fingerprinting').encode()).hexdigest()[:40]
            request = {
                'schema_version': 'apts-wpt-recon-prequeue-v1',
                'intake_id': 'wptreq-auto-' + digest,
                'idempotency_key': 'idem-wpt-auto-' + digest,
                'mission_id': mission_id, 'task_id': task_id,
                'target': {'target_type': 'URL', 'target_value': target['target_value']},
                'recon_target_key': source['target_key'],
                'recon_target_sha256': source['target_sha256'],
                'recon_target_status': source['status'],
                'target_is_observed': False, 'task_materialized': False,
                'profile': 'fingerprinting',
                'waiting_reason_code': None if policy_allowed else policy_reason,
            }
            try:
                delivery = deliver(request)
                results.append({'status': delivery.get('status', 'DELIVERY_PENDING'),
                    'intake_id': request['intake_id'], 'mission_id': mission_id,
                    'task_id': task_id, 'target': request['target'],
                    'target_is_observed': False, 'execution_authorized': False,
                    'target_io_performed': False, 'wpt_delivery': delivery})
            except Exception as exc:
                LOGGER.info('WPT Recon prequeue pending for %s: %s',
                            request['intake_id'], type(exc).__name__)
                results.append({'status': 'deferred', 'reason': type(exc).__name__,
                    'intake_id': request['intake_id'], 'mission_id': mission_id,
                    'task_id': task_id, 'target': request['target'],
                    'execution_authorized': False, 'target_io_performed': False})
    return results


def sweep(service) -> None:
    if not enabled():
        return
    for state in ('PLANNING', 'REPLANNING', 'RUNNING'):
        ids, offset = [], 0
        while True:
            page = service.list_missions(state=state, limit=100, offset=offset)
            ids += [row['mission_id'] for row in page['missions']]
            offset += len(page['missions'])
            if not page['missions'] or offset >= page['mission_count']:
                break
        for mid in ids:
            try:
                queued = prequeue_recon_targets(service, mid)
                for item in queued:
                    if item.get('status') == 'deferred':
                        LOGGER.warning('WPT Recon prequeue deferred mission=%s reason=%s',
                                    mid, item.get('reason', 'UNSPECIFIED'))
                if state == 'RUNNING':
                    proposed = propose(service, mid)
                    for item in proposed:
                        for phase in ('stage6_admission', 'stage6_job_delivery',
                                      'stage6_runtime', 'stage6_result_delivery'):
                            progress = item.get(phase) or {}
                            if progress.get('reason_code') or progress.get('error_code'):
                                LOGGER.warning('WPT pipeline pending mission=%s intake=%s phase=%s status=%s reason=%s',
                                    mid, item.get('intake_id', 'n/a'), phase,
                                    progress.get('status', 'UNKNOWN'),
                                    progress.get('reason_code') or progress.get('error_code'))
                        if item.get('status') == 'deferred':
                            LOGGER.warning('Governed WPT preparation deferred mission=%s task=%s reason=%s',
                                        mid, item.get('task_id', 'n/a'),
                                        item.get('reason', 'UNSPECIFIED'))
            except Exception:
                LOGGER.exception('Autonomous governed WPT preparation deferred for %s', mid)
