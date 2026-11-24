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

