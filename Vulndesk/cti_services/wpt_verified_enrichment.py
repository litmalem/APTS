"""HMAC authenticated, evidence-only WPT -> Vulndesk CTI enrichment.

Does not scan targets, consult external APIs, or claim exploitability.
Trusted sender is the Mission worker *after* Stage 6 evidence validation and
Recon durable acknowledgement. It is not a public, generic scanning API.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
from urllib.parse import urlsplit

from .db_adapter import DbAdapter, to_json

ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:@-]{0,191}$')
HASH = re.compile(r'^[a-f0-9]{64}$')
SCHEMA = 'apts-verified-wpt-recon-to-cti-v1'
TABLE = 'cti_wpt_verified_evidence'
MATCHING_REVISION = 3


def canonical_bytes(data: dict) -> bytes:
    return json.dumps(data,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def signature(body: dict, secret: str) -> str:
    return hmac.new(secret.encode('utf-8'), canonical_bytes(body), hashlib.sha256).hexdigest()


def valid_signature(body: dict, supplied: str, secret: str) -> bool:
    if not isinstance(secret, str) or len(secret) < 32 or not isinstance(supplied, str) or not HASH.fullmatch(supplied):
        return False
    return hmac.compare_digest(signature(body, secret), supplied)


def normalize(body: dict) -> dict:
    fields = {'schema_version','mission_id','task_id','recon_run_id','wpt_intake_id',
              'evidence_manifest_sha256','source_result_sha256','target','technologies','evidence_status'}
    if not isinstance(body, dict) or set(body) != fields or body['schema_version'] != SCHEMA:
        raise ValueError('Invalid WPT to CTI envelope schema')
    for k in ('mission_id','task_id','recon_run_id','wpt_intake_id'):
        if not isinstance(body[k],str) or not ID.fullmatch(body[k]):
            raise ValueError('Invalid identity: '+k)
    for k in ('evidence_manifest_sha256','source_result_sha256'):
        if not isinstance(body[k],str) or not HASH.fullmatch(body[k]):
            raise ValueError('Invalid digest: '+k)
    if body['evidence_status'] != 'SEALED':
        raise ValueError('Unsealed WPT evidence cannot enrich CTI')
    target = body['target']
    if not isinstance(target,dict) or set(target) != {'target_type','target_value'} or target['target_type'] != 'URL' or not isinstance(target['target_value'],str) or len(target['target_value']) > 2048:
        raise ValueError('WPT enrichment target must be a declared URL')
    try:
        url = urlsplit(target['target_value'])
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or any(c.isspace() for c in target['target_value']):
            raise ValueError('Invalid target URL')
        url.port
    except ValueError as exc:
        raise ValueError('Invalid target URL') from exc
    technologies = body['technologies']
    if not isinstance(technologies,list) or len(technologies)>32:
        raise ValueError('Invalid technology evidence count')
    normalized = []
    for tech in technologies:
        if not isinstance(tech,dict) or set(tech) != {'name','version'}:
            raise ValueError('Only name and version are admitted from WPT')
        name, version = tech['name'], tech['version']
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 150 or not isinstance(version,str) or len(version)>80:
            raise ValueError('Invalid technology evidence')
        normalized.append({'name':name.strip(), 'version':version.strip()})
    return {**body,'target':dict(target),'technologies':normalized}


class VerifiedWPTEnrichment:
    def __init__(self, db=None, matcher=None):
        self.db = db or DbAdapter()
        self.matcher = matcher

    def enrich(self, body: dict, *, reprocess: bool = False) -> dict:
        payload = normalize(body)
        digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        # Never silently succeed if CTI persistence has not been migrated.
        if not self.db.table_exists(TABLE):
            raise RuntimeError('CTI WPT evidence migration not installed')
        existing = self.db.fetch_one('SELECT input_sha256,result_json FROM '+TABLE+' WHERE intake_id=%(id)s',
                                     {'id':payload['wpt_intake_id']})
        if existing is not None:
            if existing['input_sha256'] != digest:
                raise ValueError('WPT intake replay has conflicting evidence')
            previous = json.loads(existing['result_json'])
            if not reprocess and previous.get('enrichment_version') == 2 and previous.get('matching_revision') == MATCHING_REVISION:
                return {'status':'enriched','created':False, **previous}
        from cpe_dictionary_services import normalize_technology
        technologies = [{'name': t['name'], 'version': t['version']}
                        for t in map(normalize_technology, payload['technologies'])]
        if self.matcher is None:
            from cpe_dictionary_services import CpeDictionaryService
            self.matcher = CpeDictionaryService()
        resolutions = [self.matcher.resolve_technology(tech, limit=3) for tech in technologies]
        matched = [candidate for resolution in resolutions for candidate in resolution['candidates']]
        # CPE matches, even with versions, are candidate asset interpretations.
        # CVE applicability/exploitability must be assessed by the existing CTI
        # correlation service using separately verified configuration evidence.
        candidates = []
        for item in matched[:48]:
            candidates.append({'cpe23_uri':item.get('cpe23_uri'),
                               'reference_cpe23_uri':item.get('reference_cpe23_uri'),
                               'vendor':item.get('vendor'), 'product':item.get('product'),
                               'match_level':item.get('match_level'),
                               'version_verified':item.get('version_verified', False),
                               'technology_name':item.get('technology_name'),
                               'technology_version':item.get('technology_version'),
                               'match_confidence':item.get('match_confidence'),
                               'match_method':item.get('match_method'),
                               'reason':item.get('reason'),
                               'status':item.get('resolution_status', 'CPE_CANDIDATE_NEEDS_VERIFICATION'),
                               'exploitability_confirmed':False})
        result = {'mission_id':payload['mission_id'],'task_id':payload['task_id'],
                  'recon_run_id':payload['recon_run_id'],'intake_id':payload['wpt_intake_id'],
                  'evidence_manifest_sha256':payload['evidence_manifest_sha256'],
                  'source_result_sha256':payload['source_result_sha256'],
                  'enrichment_version':2,
                  'matching_revision':MATCHING_REVISION,
                  'enriched_at':datetime.now(timezone.utc).isoformat(),
                  'technology_resolution':[{k:v for k,v in resolution.items() if k != 'candidates'}
                                           for resolution in resolutions],
                  'target':payload['target'],
                  'observed_technologies':payload['technologies'],
                  'technologies':technologies,
                  'evidence_status':payload['evidence_status'],
                  'pipeline_status':{
                      'evidence':'SEALED',
                      'cpe_resolution':'COMPLETED_WITH_CANDIDATES' if candidates else 'COMPLETED_NO_MATCH',
                      'vulnerability_correlation':'NOT_RUN', 'attack_mapping':'NOT_RUN',
                      'risk_prioritization':'NOT_RUN', 'pip_assembly':'NOT_RUN'},
                  'technology_count':len(payload['technologies']),
                  'cpe_candidates':candidates,'verified_vulnerability_count':0,
                  'target_io_performed_by_cti':False,
                  'classification':'CTI_CONTEXT_ENRICHMENT_NOT_CONFIRMED_VULNERABILITIES'}
        if existing is not None:
            # Reprocess only an identical, authenticated envelope; retain the old
            # derived result for audit. The original evidence digest never changes.
            result['previous_enrichment'] = previous
            self.db.execute('UPDATE '+TABLE+' SET result_json=%(result_json)s WHERE intake_id=%(intake_id)s AND input_sha256=%(input_sha256)s',
                            {'result_json':to_json(result), 'intake_id':payload['wpt_intake_id'], 'input_sha256':digest})
            return {'status':'enriched','created':False,**result}
        self.db.execute('''INSERT INTO '''+TABLE+''' (intake_id,mission_id,task_id,recon_run_id,input_sha256,evidence_manifest_sha256,result_json,created_at)
                VALUES (%(intake_id)s,%(mission_id)s,%(task_id)s,%(recon_run_id)s,%(input_sha256)s,%(evidence_sha256)s,%(result_json)s,CURRENT_TIMESTAMP)''',
            {'intake_id':payload['wpt_intake_id'],'mission_id':payload['mission_id'],
             'task_id':payload['task_id'],'recon_run_id':payload['recon_run_id'],
             'input_sha256':digest,'evidence_sha256':payload['evidence_manifest_sha256'],
             'result_json':to_json(result)})
        return {'status':'enriched','created':True,**result}
