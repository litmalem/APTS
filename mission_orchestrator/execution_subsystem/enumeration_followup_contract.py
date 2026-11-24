"""CTI-bound follow-up requests. Contains no execution authority or arbitrary probes."""
from copy import deepcopy
import hashlib
import re

SCHEMA = 'apts-wpt-governed-intake-v4'
LEGACY_SCHEMA = 'apts-wpt-governed-intake-v3'
CONTEXT_FIELDS = {'source_cti_intake_id', 'enumeration_run_id', 'enumeration_request_sha256',
                  'recon_run_id', 'source_result_sha256', 'technologies'}


def normalize_context(value):
    if not isinstance(value, dict) or set(value) not in (CONTEXT_FIELDS, CONTEXT_FIELDS | {'cpe_candidates'}):
        raise ValueError('Invalid enumeration context fields')
    for field, prefix in (('source_cti_intake_id', 'wptreq-'), ('enumeration_run_id', 'enumrun-'),
                          ('recon_run_id', 'reconrun-')):
        text = value[field]
        if not isinstance(text, str) or len(text) > 192 or not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9._:@-]+', text):
            raise ValueError('Invalid enumeration context identity: ' + field)
    for field in ('enumeration_request_sha256', 'source_result_sha256'):
        if not isinstance(value[field], str) or not re.fullmatch(r'[a-f0-9]{64}', value[field]):
            raise ValueError('Invalid enumeration context digest')
    if not isinstance(value['technologies'], list) or not 1 <= len(value['technologies']) <= 32:
        raise ValueError('Enumeration requires bounded CTI technology evidence')
    for technology in value['technologies']:
        if not isinstance(technology, dict) or set(technology) != {'name', 'version'}:
            raise ValueError('Invalid enumeration technology')
        if (not isinstance(technology['name'], str) or not 1 <= len(technology['name']) <= 150
                or not isinstance(technology['version'], str) or len(technology['version']) > 80):
            raise ValueError('Invalid enumeration technology name/version')
    candidates = value.get('cpe_candidates', [])
    if not isinstance(candidates, list) or len(candidates) > 256:
        raise ValueError('Invalid bounded CPE candidates')
    for c in candidates:
        if (not isinstance(c, dict) or set(c) != {'technology_name','cpe23_uri','match_confidence','status'}
                or not isinstance(c['technology_name'], str) or not 1 <= len(c['technology_name']) <= 150
                or c['technology_name'] not in {t['name'] for t in value['technologies']}
                or not isinstance(c['cpe23_uri'], str) or not c['cpe23_uri'].startswith('cpe:2.3:') or len(c['cpe23_uri']) > 512
                or type(c['match_confidence']) not in (int,float) or not 0 <= c['match_confidence'] <= 1
                or c['status'] != 'CPE_CANDIDATE_NEEDS_VERIFICATION'):
            raise ValueError('Invalid CPE candidate')
    return deepcopy(value)


def build_intake(run, *, schema_version=SCHEMA):
    """Derive exactly one follow-up identity from a verified, immutable Stage 5.3 run."""
    request = run['request']
    metadata = request.get('metadata') or {}
    if schema_version not in (SCHEMA, LEGACY_SCHEMA):
        raise ValueError('Unsupported CTI follow-up schema')
    technologies, candidates, target = [], [], None
    for observation in request.get('observations', []):
        if observation.get('source', {}).get('source_kind') != 'CTI_ENRICHMENT':
            continue
        if observation['source']['source_id'] != metadata.get('cti_intake_id'):
            raise ValueError('Enumeration CTI observation lineage mismatch')
        if target is not None and observation['target'] != target:
            raise ValueError('Enumeration follow-up must have one exact target')
        target = observation['target']
        attributes = observation['attributes']
        item = {'name': attributes.get('product') or attributes.get('technology'),
                'version': attributes.get('version', '')}
        if item not in technologies:
            technologies.append(item)
        for c in attributes.get('cpe_candidates', []):
            if (isinstance(c,dict) and isinstance(c.get('cpe23_uri'),str) and c['cpe23_uri'].startswith('cpe:2.3:')
                    and type(c.get('match_confidence')) in (int,float) and 0 <= c['match_confidence'] <= 1):
                candidate = {'technology_name':item['name'],'cpe23_uri':c['cpe23_uri'],
                    'match_confidence':c['match_confidence'],'status':'CPE_CANDIDATE_NEEDS_VERIFICATION'}
                if candidate not in candidates:
                    candidates.append(candidate)
    context = normalize_context({
        'source_cti_intake_id': metadata.get('cti_intake_id'),
        'enumeration_run_id': run['enumeration_run_id'],
        'enumeration_request_sha256': run['request_sha256'],
        'recon_run_id': run['recon_run_id'],
        'source_result_sha256': metadata.get('source_result_sha256'),
        'technologies': technologies,
        **({'cpe_candidates':candidates} if schema_version == SCHEMA else {}),
    })
    if run['run_status'] != 'COMPLETED' or not target or target.get('target_type') != 'URL':
        raise ValueError('Completed CTI URL analysis required for WPT follow-up')
    seed = hashlib.sha256((run['enumeration_run_id'] + ':' + run['request_sha256'] + (':v4' if schema_version == SCHEMA else '')).encode()).hexdigest()[:40]
    return {'schema_version': schema_version, 'intake_id': 'wptreq-enum-' + seed,
            'idempotency_key': 'idem-wpt-enum-' + seed, 'mission_id': run['mission_id'],
            'task_id': request['boundary']['task_id'], 'target': deepcopy(target),
            'profile': 'enumeration', 'enumeration_context': context}
