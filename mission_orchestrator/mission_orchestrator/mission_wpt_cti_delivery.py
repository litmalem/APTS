"""HMAC-protected delivery of verified Stage 6 WPT evidence to local Vulndesk.

Outbox recovery comes from the durable WPT -> Recon handoff acknowledgement.
No target traffic is performed by the CTI delivery client.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

SCHEMA = 'apts-verified-wpt-recon-to-cti-v1'


def extract_technologies(stage6_record: dict) -> list[dict]:
    observation = stage6_record.get('result', {}).get('observation') or {}
    if not isinstance(observation, dict):
        return []
    findings = observation.get('technology_findings') or []
    if not isinstance(findings, list):
        return []
    out = []
    for finding in findings[:32]:
        if not isinstance(finding, dict):
            continue
        name = finding.get('name') or finding.get('technology_name') or finding.get('technology') or ''
        version = finding.get('observed_version') or finding.get('version') or finding.get('technology_version') or ''
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 150:
            continue
        if not isinstance(version, str) or len(version) > 80:
            continue
        row = {'name':name.strip(), 'version':version.strip()}
        if row not in out:
            out.append(row)
    return out


def build_delivery(intake: dict, result: dict, handoff: dict) -> dict:
    """Build a read-only CTI package from already authenticated repository objects."""
    # Explicit runtime validation (never Python asserts, which -O disables).
    if result.get('status') != 'VALIDATED_AND_STORED' or (result.get('evidence') or {}).get('capture_status') != 'SEALED':
        raise ValueError('Verified sealed Stage 6 evidence is required')
    if handoff.get('delivery_status') != 'DELIVERED':
        raise ValueError('Durable Recon handoff has not been delivered')
    ack = handoff.get('acknowledgement') or {}
    if (ack.get('accepted') is not True or ack.get('intake_id') != intake['intake_id']
            or ack.get('source_result_sha256') != (result.get('integrity') or {}).get('canonical_sha256')
            or not ack.get('recon_run_id')):
        raise ValueError('Recon acknowledgement does not match verified evidence')
    return {
        'schema_version': SCHEMA,
        'mission_id': intake['mission_id'], 'task_id': intake['task_id'],
        'recon_run_id': ack['recon_run_id'], 'wpt_intake_id': intake['intake_id'],
        'evidence_manifest_sha256': result['evidence']['manifest_sha256'],
        'source_result_sha256': result['integrity']['canonical_sha256'],
        'target': dict(intake['target']),
        'technologies': extract_technologies(result),
        'evidence_status': 'SEALED',
    }


def publish(delivery: dict, *, sender=None) -> dict:
    secret = os.getenv('APTS_WPT_CTI_SHARED_TOKEN','')
    if len(secret) < 32:
        return {'status':'deferred', 'reason':'CTI_SHARED_SECRET_NOT_CONFIGURED'}
    url = os.getenv('APTS_WPT_CTI_URL','http://127.0.0.1:8765/api/cti/wpt/verified-enrich')
    parsed = urlsplit(url)
    # There is no generic URL forwarding facility: the integration is strictly
    # local and the endpoint path is fixed. Never send evidence to a remote IP.
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1','::1','localhost'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != '/api/cti/wpt/verified-enrich'):
        return {'status':'deferred', 'reason':'CTI_ENDPOINT_MUST_BE_LOCAL'}
    canonical = json.dumps(delivery,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    sig = hmac.new(secret.encode('utf-8'), canonical, hashlib.sha256).hexdigest()
    req = Request(url, data=canonical, method='POST', headers={
        'Content-Type':'application/json', 'X-APTS-WPT-CTI-Signature':sig})
    # Unconditional proxy bypass so localhost evidence cannot be exfiltrated
    # via a configured HTTP_PROXY environment variable.
    opener = sender or build_opener(ProxyHandler({})).open
    with opener(req, timeout=8) as response:
        data = response.read(262145)
        if len(data)>262144:
            raise ValueError('CTI response exceeds bounded size')
        result = json.loads(data.decode('utf-8'))
    if result.get('mission_id') != delivery['mission_id'] or result.get('intake_id') != delivery['wpt_intake_id']:
        raise ValueError('CTI acknowledgement identity mismatch')
    if result.get('source_result_sha256') != delivery['source_result_sha256']:
        raise ValueError('CTI acknowledgement evidence hash mismatch')
    return {'status':'delivered', 'intake_id':delivery['wpt_intake_id'],
            'cti_status':result['status'], 'candidate_count':len(result.get('cpe_candidates') or []),
            'vulnerability_confirmed':False, 'target_io_performed':False}
