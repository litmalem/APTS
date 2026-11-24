"""APTS Recon -> Stage 6 authorized collector -> sealed evidence -> Recon iteration.

This is an operator-side coordinator, NOT a new scanner and NOT an authorization
provider. All target network I/O is performed by the existing Stage 6 runtime.
Run only against the operator's explicitly authorized lab mission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import ipaddress


class BridgeError(RuntimeError):
    pass


def require_loopback(base: str) -> str:
    u = urlsplit(base)
    try:
        local = u.hostname == 'localhost' or ipaddress.ip_address(u.hostname).is_loopback
    except (ValueError, TypeError):
        local = False
    if u.scheme != 'http' or not local or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
        raise BridgeError('APTS control-plane URL must be plain HTTP on a loopback address')
    return base.rstrip('/')


class HTTPClient:
    def __init__(self, base: str, timeout: int = 12):
        self.base = require_loopback(base)
        self.timeout = timeout

    def call(self, method: str, path: str, payload=None, *, allow_not_found=False):
        content = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        request = Request(self.base + path, data=content, method=method, headers={
            'Accept': 'application/json', **({'Content-Type': 'application/json'} if content is not None else {})})
        try:
            with urlopen(request, timeout=self.timeout) as stream:
                answer = json.loads(stream.read().decode('utf-8'))
            if not isinstance(answer, dict):
                raise BridgeError('APTS API returned a non-object response')
            return answer
        except HTTPError as exc:
            if exc.code == 404 and allow_not_found:
                return None
            try:
                detail = json.loads(exc.read().decode('utf-8'))
                message = detail.get('error') or detail.get('message') or detail.get('status')
            except (ValueError, UnicodeError, AttributeError):
                message = 'no structured reason'
            raise BridgeError(f'{method} {path} rejected HTTP {exc.code}: {message}') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BridgeError(f'{method} {path} unavailable: {exc}') from exc
        except (ValueError, UnicodeError) as exc:
            raise BridgeError(f'{method} {path} returned invalid JSON') from exc

    def get(self, path: str, *, allow_not_found=False):
        return self.call('GET', path, allow_not_found=allow_not_found)

    def post(self, path: str, payload: dict):
        return self.call('POST', path, payload)


def stable_id(prefix: str, action_id: str, suffix: str) -> str:
    digest = hashlib.sha256((action_id + '\0' + suffix).encode('utf-8')).hexdigest()[:32]
    return prefix + digest


def assert_equal(actual, expected, label):
    if actual != expected:
        raise BridgeError(f'{label} binding mismatch: expected {expected!r}, got {actual!r}')


def verify_result(result: dict, action: dict) -> None:
    # Installed under <MissionRoot>/run; make the canonical project modules available.
    root = Path(__file__).resolve().parents[1]
    if str(root) in sys.path:
        sys.path.remove(str(root))
    sys.path.insert(0, str(root))
    from execution_subsystem.execution_result_contract import verify_recon_execution_result
    if not verify_recon_execution_result(result):
        raise BridgeError('Stage 6 result integrity verification failed')
    for field in ('action_id', 'proposal_ref', 'mission_id', 'orchestration_id'):
        assert_equal(result.get(field), action.get(field), f'result.{field}')
    if result.get('terminal') is not True:
        raise BridgeError('Stage 6 attempt is not terminal')
    if result.get('runtime_state') != 'SUCCEEDED' or (result.get('execution_result') or {}).get('status') != 'SUCCEEDED':
        raise BridgeError('Stage 6 attempt failed; no Recon iteration will be performed')
    evidence = result.get('evidence') or {}
    if evidence.get('capture_status') != 'SEALED' or not evidence.get('manifest_sha256'):
        raise BridgeError('Stage 6 evidence is not SEALED; Recon iteration blocked')


def run_bridge(pentest: HTTPClient, execution: HTTPClient, *, mission_id: str, run_id: str,
               action_id: str, expected_target: str, operator: str,
               execute: bool, poll_timeout: int = 90, poll_interval: float = 1.0,
               sleep=time.sleep, monotonic=time.monotonic, log=print) -> dict:
    """Coordinates existing APIs; never calls the target URL directly."""
    if not mission_id.startswith('mission-gmo-') or not run_id.startswith('reconrun-') or not action_id.startswith('rareq-'):
        raise BridgeError('Specify exact canonical mission, Recon run and Action Request IDs')
    if not operator or len(operator) > 150:
        raise BridgeError('Operator identity is required')
    for name, client in [('Pentest', pentest), ('Stage 6', execution)]:
        health = client.get('/health')
        if health.get('status') != 'ok':
            raise BridgeError(f'{name} API health is not ok')
    if execution.get('/api/contracts/recon-execution-result', allow_not_found=True) is None:
        # The route is available at Stage 6.6+; preflight before any write.
        raise BridgeError('Stage 6.6 Recon result contract endpoint is unavailable')

    run_reply = pentest.get('/api/pentest/reconnaissance-runs/' + quote(run_id, safe=''))
    run = run_reply.get('run')
    if not isinstance(run, dict):
        raise BridgeError('Recon run cannot be retrieved from authoritative Pentest API')
    assert_equal(run.get('mission_id'), mission_id, 'run.mission_id')
    if run.get('run_status') != 'COMPLETED':
        raise BridgeError('Source Recon run is not COMPLETED')
    matches = [a for a in run.get('output', {}).get('action_requests', []) if a.get('action_id') == action_id]
    if len(matches) != 1:
        raise BridgeError('Action Request is absent or ambiguous in the immutable Recon run')
    action = matches[0]
    for key in ('recon_run_id', 'mission_id', 'orchestration_id'):
        assert_equal(action.get(key), {'recon_run_id':run_id, 'mission_id':mission_id,
                                       'orchestration_id':run.get('orchestration_id')}[key], f'action.{key}')
    if action.get('technique') != 'TCP_CONNECT_SCAN' or action.get('capability_id') != 'reconnaissance':
        raise BridgeError('Only registered, bounded TCP_CONNECT_SCAN Recon is supported')
    target = action.get('target_ref', {}).get('target_value')
    assert_equal(target, expected_target, 'authorized target')
    request_sha = action.get('integrity', {}).get('canonical_sha256')
    if not isinstance(request_sha, str) or len(request_sha) != 64:
        raise BridgeError('Recon Action Request is missing canonical integrity hash')
    validation = pentest.get('/api/pentest/recon-action-requests/' + quote(action_id, safe='') + '/validate-stage6-intake')
    checked = validation.get('validation') or {}
    if checked.get('status') != 'VALIDATED_AWAITING_GSS' or checked.get('target_scope_verified') is not True:
        raise BridgeError('Pentest current-scope/RoE Action Request validation denied dispatch')
    assert_equal(checked.get('action_id'), action_id, 'validation.action_id')
    assert_equal(checked.get('recon_run_id'), run_id, 'validation.recon_run_id')
    log('PREFLIGHT_OK: verified immutable Recon Action Request and current Pentest RoE; not an authorization')
    if not execute:
        return {'status':'PREFLIGHT_ONLY', 'mission_id':mission_id, 'recon_run_id':run_id,
                'action_id':action_id, 'target':target, 'execution_started':False}

    result_path = '/api/execution/recon-action-requests/' + quote(action_id, safe='') + '/results'
    prior = execution.get(result_path, allow_not_found=True)
    if prior and prior.get('results'):
        latest = prior.get('latest_result')
        if not isinstance(latest, dict):
            raise BridgeError('Stage 6 result history is malformed')
        if not latest.get('terminal'):
            log('RESUME: an existing Stage 6 attempt is still running; waiting without new dispatch')
        elif latest.get('runtime_state') != 'SUCCEEDED':
            raise BridgeError('Existing terminal Stage 6 attempt failed; manual review required, no automatic retry')
        else:
            verify_result(latest, action)
            log('RESUME: existing SEALED Stage 6 result detected; no target I/O will be repeated')
            return iterate(pentest, action, latest, log)
    else:
        log('REQUEST: creating canonical Stage 6.1 execution request')
        request = execution.post('/api/execution/requests', {
            'schema_version':'apts-execution-request-intake-v2',
            'source_type':'STAGE5_2_RECON_ACTION_REQUEST',
            'request_id':stable_id('ereq-',action_id,'request'),
            'idempotency_key':stable_id('idem-',action_id,'execution'),
            'recon_action_id':action_id,'recon_request_sha256':request_sha})
        envelope = request.get('envelope') or {}
        payload = envelope.get('execution_request') or {}
        assert_equal(payload.get('mission_id'), mission_id, 'execution_request.mission_id')
        assert_equal(payload.get('parameters', {}).get('source_action_id'), action_id, 'execution_request.action_id')
        assert_equal(payload.get('target', {}).get('target_value'), target, 'execution_request.target')
        if payload.get('action') != {'action_class':'TARGET_RECON', 'capability_id':'reconnaissance', 'technique':'TCP_CONNECT_SCAN'}:
            raise BridgeError('Stage 6 source proposal does not match registered Recon technique')
        execution_id = request.get('execution_id')
        sha = envelope.get('integrity',{}).get('canonical_sha256')
        if not execution_id or not sha:
            raise BridgeError('Stage 6 did not return a canonical execution envelope')
        log('GATEWAY: submitting for fresh external GSS authorization and controlled admission')
        admitted = execution.post('/api/execution/gateway/submissions', {
            'schema_version':'apts-execution-gateway-intake-v1',
            'submission_id':stable_id('gwreq-',action_id,'gateway'),
            'idempotency_key':stable_id('idem-',action_id,'gateway'),
            'execution_id':execution_id, 'envelope_sha256':sha, 'requested_by':operator})
        if admitted.get('gateway_admitted') is not True or admitted.get('created') is not True or admitted.get('governance_query_performed') is not True:
            raise BridgeError('Gateway did not produce a NEW governed admission; replay, denial or review blocks dispatch')
        log('RUNTIME: requesting server-owned Stage 6.5/6.6 collector, not direct network I/O')
        started = execution.post('/api/execution/runtime/attempts', {
            'schema_version':'apts-execution-runtime-start-v1',
            'invocation_request_id':stable_id('toolreq-',action_id,'collector'),
            'idempotency_key':stable_id('idem-',action_id,'collector'),
            'execution_id':execution_id, 'envelope_sha256':sha, 'requested_by':operator})
        if not started.get('attempt_id'):
            raise BridgeError('Stage 6 runtime returned no attempt_id')
        log('ATTEMPT: ' + started['attempt_id'])
    deadline = monotonic() + poll_timeout
    while monotonic() < deadline:
        response = execution.get(result_path, allow_not_found=True)
        latest = response.get('latest_result') if response else None
        if latest and latest.get('terminal'):
            verify_result(latest, action)
            log('EVIDENCE_SEALED: ' + latest['evidence']['manifest_sha256'])
            return iterate(pentest, action, latest, log)
        sleep(poll_interval)
    raise BridgeError('Timed out while monitoring Stage 6; collector may still be running. DO NOT automatically redispatch.')


def iterate(pentest: HTTPClient, action: dict, latest: dict, log=print) -> dict:
    verify_result(latest, action)
    log('ITERATION: asking Recon Agent to ingest the sealed Stage 6 observation')
    iteration = pentest.post('/api/pentest/agentic-orchestrations/' + quote(action['orchestration_id'],safe='') + '/reconnaissance/iterations', {
        'schema_version':'apts-stage5.2-recon-iteration-request-v1',
        'parent_recon_run_id':action['recon_run_id'], 'action_id':action['action_id']})
    new_run = iteration.get('run') or {}
    if iteration.get('status') not in ('completed','replayed') or not new_run.get('recon_run_id'):
        raise BridgeError('Recon iteration returned no durable run')
    assert_equal(new_run.get('mission_id'), action['mission_id'], 'iteration.mission_id')
    assert_equal(new_run.get('source_action_id'), action['action_id'], 'iteration.source_action_id')
    assert_equal(new_run.get('source_result_sha256'), latest['integrity']['canonical_sha256'], 'iteration.result_sha256')
    if new_run.get('parent_recon_run_id') != action['recon_run_id']:
        raise BridgeError('Iteration did not preserve the immutable Recon parent')
    log('COMPLETE: child Recon run ' + new_run['recon_run_id'])
    return {'status':'COMPLETED', 'mission_id':action['mission_id'], 'action_id':action['action_id'],
            'attempt_id':latest['attempt_id'], 'execution_id':latest['execution_id'],
            'evidence_manifest_sha256':latest['evidence']['manifest_sha256'],
            'result_sha256':latest['integrity']['canonical_sha256'], 'parent_recon_run_id':action['recon_run_id'],
            'child_recon_run_id':new_run['recon_run_id'], 'iteration_replayed':not iteration.get('created',False)}


def main(argv=None):
    p = argparse.ArgumentParser(description='APTS governed Recon collector end-to-end bridge')
    p.add_argument('--mission-id', required=True)
    p.add_argument('--recon-run-id', required=True)
    p.add_argument('--action-id', required=True)
    p.add_argument('--expect-target', required=True, help='Exact URL from the authorized Recon Action Request')
    p.add_argument('--operator', required=True)
    p.add_argument('--pentest-api', default='http://127.0.0.1:8790')
    p.add_argument('--execution-api', default='http://127.0.0.1:8791')
    p.add_argument('--execute', action='store_true', help='Allow Stage 6 gateway submission and controlled runtime')
    p.add_argument('--ack-authorized-lab', action='store_true', help='Acknowledge RoE and explicit target authorization')
    p.add_argument('--timeout', type=int, default=90)
    p.add_argument('--output', help='Optional local JSON evidence summary')
    a = p.parse_args(argv)
    if a.execute and not a.ack_authorized_lab:
        p.error('--execute also requires --ack-authorized-lab')
    if not 5 <= a.timeout <= 600:
        p.error('--timeout must be between 5 and 600 seconds')
    try:
        report = run_bridge(HTTPClient(a.pentest_api), HTTPClient(a.execution_api), mission_id=a.mission_id,
                            run_id=a.recon_run_id, action_id=a.action_id, expected_target=a.expect_target,
                            operator=a.operator, execute=a.execute, poll_timeout=a.timeout)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if a.output:
            Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return 0
    except BridgeError as exc:
        print('BLOCKED: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
