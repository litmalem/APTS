import hashlib
import pytest
from cti_services.wpt_verified_enrichment import (VerifiedWPTEnrichment, normalize,
    signature, valid_signature, canonical_bytes, SCHEMA)


def payload():
    return {'schema_version': SCHEMA,
        'mission_id':'mission-gmo-one','task_id':'ptask-one',
        'recon_run_id':'reconrun-one','wpt_intake_id':'wptreq-one',
        'evidence_manifest_sha256':'a'*64,'source_result_sha256':'b'*64,
        'target':{'target_type':'URL','target_value':'http://localhost:3000/'},
        'technologies':[{'name':'nginx','version':'1.24'}],
        'evidence_status':'SEALED'}


class Database:
    def __init__(self):self.saved=None
    def table_exists(self,name):return name=='cti_wpt_verified_evidence'
    def fetch_one(self,sql, params):return self.saved
    def execute(self,sql,params):
        assert params['input_sha256']==hashlib.sha256(canonical_bytes(payload())).hexdigest()
        self.saved={'input_sha256':params['input_sha256'], 'result_json':params['result_json']}
        return 1


class Matcher:
    def __init__(self):self.calls=[]
    def resolve_technology(self, tech, limit=3):
        matches = self.match_technologies([tech], limit, False)
        return {'name':tech['name'], 'version':tech['version'],
                'status':'EXACT_VERSION_MATCH', 'candidates':matches}
    def match_technologies(self, techs, per_technology_limit, auto_fetch):
        self.calls.append((techs,per_technology_limit,auto_fetch))
        return [{'cpe23_uri':'cpe:2.3:a:nginx:nginx:1.24:*:*:*:*:*:*:*',
                 'technology_name':'nginx','technology_version':'1.24',
                 'match_confidence':0.88}]


def test_hmac_authentication_denies_unconfigured_tampered_or_short_key():
    item=payload(); token='r'*40
    sig=signature(item,token)
    assert valid_signature(item,sig,token)
    assert not valid_signature(item,sig,'')
    assert not valid_signature(item,sig,'tiny')
    assert not valid_signature({**item,'mission_id':'mission-gmo-other'},sig,token)


def test_signed_enrichment_uses_local_dictionary_and_is_idempotent():
    db=Database(); matcher=Matcher(); svc=VerifiedWPTEnrichment(db,matcher)
    first=svc.enrich(payload()); second=svc.enrich(payload())
    assert first['created'] is True and second['created'] is False
    assert len(matcher.calls)==1
    assert matcher.calls[0][2] is False  # never fetch external CPE feed
    assert first['verified_vulnerability_count']==0
    assert first['classification']=='CTI_CONTEXT_ENRICHMENT_NOT_CONFIRMED_VULNERABILITIES'
    assert first['target_io_performed_by_cti'] is False


def test_mismatched_stage6_evidence_and_unbounded_payload_denied():
    data=payload()
    for changes in ({'evidence_status':'UNSEALED'},
                    {'technologies':[{'name':'N'*200,'version':''}]},
                    {'technologies':[{'name':'nginx','version':'','extra':'raw_response'}]},
                    {'target':{'target_type':'IP','target_value':'127.0.0.1'}}):
        with pytest.raises(ValueError):normalize({**data,**changes})
    with pytest.raises(ValueError):
        normalize({**data,'authorization':'TRUE'})


def test_persists_target_technologies_and_explicit_pipeline():
    result = VerifiedWPTEnrichment(Database(), Matcher()).enrich(payload())
    assert result['target'] == payload()['target']
    assert result['technologies'] == payload()['technologies']
    assert result['observed_technologies'] == payload()['technologies']
    assert result['evidence_status'] == 'SEALED'
    assert result['pipeline_status']['vulnerability_correlation'] == 'NOT_RUN'
    assert result['pipeline_status']['cpe_resolution'] == 'COMPLETED_WITH_CANDIDATES'


def test_legacy_replay_reprocesses_only_identical_evidence_and_preserves_previous():
    import json
    db = Database()
    digest = hashlib.sha256(canonical_bytes(payload())).hexdigest()
    db.saved = {'input_sha256': digest, 'result_json': json.dumps({'technology_count': 1})}
    service = VerifiedWPTEnrichment(db, Matcher())
    result = service.enrich(payload())
    assert result['created'] is False
    assert result['enrichment_version'] == 2
    assert result['previous_enrichment'] == {'technology_count': 1}
    assert service.enrich(payload())['enrichment_version'] == 2
    with pytest.raises(ValueError, match='conflicting'):
        service.enrich({**payload(), 'technologies': []})


def test_explicit_reprocessing_refreshes_current_result_and_keeps_evidence_digest():
    db = Database(); matcher = Matcher(); service = VerifiedWPTEnrichment(db, matcher)
    first = service.enrich(payload())
    digest = db.saved['input_sha256']
    second = service.enrich(payload(), reprocess=True)
    assert len(matcher.calls) == 2
    assert second['created'] is False
    assert second['previous_enrichment'] == {k:v for k,v in first.items() if k not in {'status','created'}}
    assert db.saved['input_sha256'] == digest
    assert second['technology_resolution'][0]['status'] == 'EXACT_VERSION_MATCH'
    with pytest.raises(ValueError, match='conflicting'):
        service.enrich({**payload(), 'technologies': []}, reprocess=True)


@pytest.mark.parametrize('url', ['javascript:alert(1)', '', 'http://', 'http://user:password@localhost/', 'http://localhost:invalid/'])
def test_invalid_target_url_is_rejected(url):
    with pytest.raises(ValueError, match='URL'):
        normalize({**payload(), 'target': {'target_type': 'URL', 'target_value': url}})
