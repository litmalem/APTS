"""Authenticated Mission -> WPT inbox delivery; proposal only, never dispatches scans."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('WPT inbox redirect rejected')


def deliver(intake: dict) -> dict:
    base = os.getenv('APTS_WPT_INBOX_URL', '').rstrip('/')
    token = os.getenv('APTS_WPT_INBOX_TOKEN', '')
    if not base:
        return {'status': 'WPT_INBOX_NOT_CONFIGURED'}
    parsed = urlparse(base)
    if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('WPT inbox URL must use HTTPS or loopback HTTP')
    if len(token) < 32:
        raise RuntimeError('WPT inbox service token is not configured')
    payload = {key: intake[key] for key in (
        'schema_version', 'intake_id', 'idempotency_key', 'mission_id',
        'task_id', 'target', 'profile')}
    if intake.get('schema_version') in ('apts-wpt-governed-intake-v3','apts-wpt-governed-intake-v4'):
        payload['enumeration_context'] = intake['enumeration_context']
    if intake.get('schema_version') in (
            'apts-wpt-governed-intake-v2', 'apts-wpt-recon-prequeue-v1'):
        payload.update({key: intake[key] for key in (
            'recon_target_key', 'recon_target_sha256', 'recon_target_status', 'target_is_observed')})
    if intake.get('schema_version') == 'apts-wpt-recon-prequeue-v1':
        payload['task_materialized'] = False
        if 'waiting_reason_code' in intake:
            payload['waiting_reason_code'] = intake['waiting_reason_code']
    req = Request(base + '/api/governed-intakes',
                  data=json.dumps(payload, separators=(',', ':')).encode('utf-8'),
                  headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                           'X-APTS-Client-Token': token,
                           'User-Agent': 'APTS-Mission-WPT-Intake/1.0'},
                  method='POST')
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(req, timeout=8) as response:
            data = json.loads(response.read(65537).decode('utf-8'))
            if response.status not in (200, 201):
                raise RuntimeError(f'WPT inbox returned HTTP {response.status}')
            if data.get('intake_id') != intake['intake_id']:
                raise RuntimeError('WPT inbox acknowledgement identity mismatch')
            return {'status': 'DELIVERED', 'created': bool(data.get('created')),
                    'intake_id': data.get('intake_id')}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError('WPT inbox delivery failed') from exc
