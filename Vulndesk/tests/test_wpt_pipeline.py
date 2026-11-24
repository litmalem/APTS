import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
LIVE=Path(r'D:\APTS\Vulndesk')
sys.path.insert(0,str(LIVE))
package=types.ModuleType('cti_services')
package.__path__=[str(ROOT/'cti_services'),str(LIVE/'cti_services')]
sys.modules['cti_services']=package
from cti_services.wpt_pipeline import WptPipeline, build_scan
from cti_services.wpt_verified_enrichment import SCHEMA, canonical_bytes
from cti_services.asset_profiling_cpe_resolution_service import AssetProfilingCpeResolutionService
from cti_services.vulnerability_correlation_service import VulnerabilityCorrelationService
from cti_services.attack_mapping_service import AttackMappingService
from cti_services.cti_subsystem_orchestrator import CtiSubsystemOrchestrator


def payload():
    return {'schema_version':SCHEMA,'mission_id':'parent-one','task_id':'task-one','recon_run_id':'recon-one',
            'wpt_intake_id':'intake-one','evidence_manifest_sha256':'a'*64,'source_result_sha256':'b'*64,
            'target':{'target_type':'URL','target_value':'http://localhost:3000/'},
            'technologies':[{'name':'nginx','version':''}],'evidence_status':'SEALED'}


def result():
    p=payload()
    return {**p,'observed_technologies':p['technologies'],'cpe_candidates':[
        {'cpe23_uri':None,'reference_cpe23_uri':'cpe:2.3:a:f5:nginx:1.24.0:*:*:*:*:*:*:*',
         'vendor':'f5','product':'nginx','technology_name':'nginx','technology_version':'','match_confidence':0.9}]}


class Cursor:
    def __init__(self, db): self.db=db
    def execute(self, sql, params=()):
        sql=sql.replace(' FOR UPDATE','').replace('UTC_TIMESTAMP()','CURRENT_TIMESTAMP')
        sql=sql.replace('DATE_ADD(CURRENT_TIMESTAMP,INTERVAL 90 SECOND)',"datetime('now','+90 seconds')")
        sql=sql.replace('%s','?')
        sql=re.sub(r'%\((\w+)\)s',r':\1',sql)
        if ' ON DUPLICATE KEY UPDATE ' in sql:
            sql=sql.replace(' ON DUPLICATE KEY UPDATE ',' ON CONFLICT DO UPDATE SET ')
            sql=re.sub(r'VALUES\((\w+)\)',r'excluded.\1',sql)
        self.cur=self.db.execute(sql,params)
        return self.cur.rowcount
    def fetchone(self):
        r=self.cur.fetchone();return dict(r) if r else None
    def fetchall(self):return [dict(r) for r in self.cur.fetchall()]


class Db:
    def __init__(self):
        self.sql=sqlite3.connect(':memory:',check_same_thread=False);self.sql.row_factory=sqlite3.Row
        self.sql.executescript('''CREATE TABLE cti_wpt_pipeline_jobs (
            intake_id TEXT PRIMARY KEY,input_sha256 TEXT,parent_mission_id TEXT,pipeline_mission_id TEXT,
            status TEXT DEFAULT 'PENDING',attempt_count INTEGER DEFAULT 0,max_attempts INTEGER DEFAULT 3,lease_owner TEXT,lease_until TEXT,
            stage_status_json TEXT,summary_json TEXT,last_error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,completed_at TEXT);
            CREATE TABLE cti_wpt_verified_evidence (intake_id TEXT PRIMARY KEY,input_sha256 TEXT,
            mission_id TEXT,task_id TEXT,recon_run_id TEXT,evidence_manifest_sha256 TEXT,result_json TEXT);''')
        self.digest=hashlib.sha256(canonical_bytes(payload())).hexdigest()
        self.sql.execute('INSERT INTO cti_wpt_verified_evidence VALUES (?,?,?,?,?,?,?)',
            ('intake-one',self.digest,'parent-one','task-one','recon-one','a'*64,json.dumps(result())))
        self.sql.commit()
    @contextmanager
    def transaction(self):
        with self.sql:yield Cursor(self.sql)
    def fetch_one(self,sql,params):
        with self.transaction() as c:c.execute(sql,params);return c.fetchone()
    def execute(self,sql,params):
        with self.transaction() as c:return c.execute(sql,params)
    def job(self):return dict(self.sql.execute('SELECT * FROM cti_wpt_pipeline_jobs').fetchone())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.db=Db();self.addCleanup(self.db.sql.close)
        self.orch=MagicMock()
        self.worker=WptPipeline(self.db,self.orch);self.worker.transaction=self.db.transaction
        self.orch.run_scan.return_value={'component_outputs':{k:{'status':'completed'} for k in ['vulnerability','attack_mapping','risk','pip']},
                                        'pentest_intelligence_package':{'pip_id':'pip-one','readiness':'PARTIAL'}}

    def test_structured_sql_metadata_serializes_but_primitive_in_lists_are_preserved(self):
        from cti_services.db_adapter import normalize_sql_params
        values=normalize_sql_params({'support':[{'relationship':'impact'}],'nested':[[{'source':'CTID'}]],'ids':['one','two'],'pair':(1,2)})
        self.assertEqual(json.loads(values['support']),[{'relationship':'impact'}])
        self.assertEqual(json.loads(values['nested']),[[{'source':'CTID'}]])
        self.assertEqual(values['ids'],['one','two']);self.assertEqual(values['pair'],(1,2))

    def test_explicit_operator_retry_keeps_total_attempt_counter(self):
        self.worker.enqueue(payload());self.orch.run_scan.side_effect=RuntimeError('fixture failure')
        with patch('cti_services.wpt_pipeline.logging'):
            for _ in range(3):self.worker.process_one();self.worker.enqueue(payload())
        self.worker.retry_failed('intake-one')
        self.assertEqual(self.db.job()['attempt_count'],3)
        self.assertEqual(self.db.job()['max_attempts'],6)
        self.assertEqual(self.db.job()['status'],'PENDING')

    def test_datetime_persistence_converts_iso_without_mutating_runtime_evidence(self):
        from datetime import datetime
        from cti_services.threat_context_service import ThreatContextService
        svc=VulnerabilityCorrelationService.__new__(VulnerabilityCorrelationService)
        svc.db=MagicMock();svc.db.table_exists.return_value=True
        claim={'asset_id':'one','resolution_id':'two','status':'AMBIGUOUS','source_candidate':{'wpt_context_only':True}}
        corr=svc._correlation_from_match('child',claim,{'cve_id':'CVE-2024-1234'},None)
        original=corr['valid_from'];svc._persist(corr)
        self.assertIsInstance(svc.db.execute.call_args.args[1]['valid_from'],datetime)
        self.assertIsInstance(svc.db.execute.call_args.args[1]['evaluated_at'],datetime)
        self.assertEqual(corr['valid_from'],original)
        context=ThreatContextService.__new__(ThreatContextService);context.db=svc.db
        context._persist({'valid_from':original,'valid_until':None})
        self.assertIsInstance(svc.db.execute.call_args.args[1]['valid_from'],datetime)
        self.assertIsNone(svc.db.execute.call_args.args[1]['valid_until'])

    def test_api_worker_reuses_the_shared_orchestrator(self):
        import cti_services.pentest_enrichment_api_service as api_module
        with patch.object(api_module,'CtiSubsystemOrchestrator') as orch, patch.object(api_module,'VulnerabilityContextService'):
            api=api_module.PentestEnrichmentApiService(registry=MagicMock())
            self.assertIs(api.wpt_pipeline.orchestrator,orch.return_value)
            self.assertIs(api.wpt_pipeline.db,orch.return_value.db)

    def test_replay_is_idempotent_and_parent_is_not_used_as_child(self):
        self.worker.enqueue(payload());self.worker.enqueue(payload())
        self.assertEqual(self.db.job()['attempt_count'],0)
        self.worker.process_one();self.worker.enqueue(payload())
        self.assertFalse(self.worker.process_one())
        self.orch.run_scan.assert_called_once()
        scan=self.orch.run_scan.call_args.args[0]
        self.assertNotEqual(scan['mission_id'],'parent-one')
        self.assertEqual(self.db.job()['status'],'COMPLETED')
        self.assertEqual(json.loads(self.db.job()['summary_json'])['verified_vulnerability_count'],0)

    def test_conflicting_or_tampered_evidence_is_rejected(self):
        with self.assertRaises(ValueError):self.worker.enqueue({**payload(),'technologies':[]})
        self.worker.enqueue(payload())
        changed=result();changed['target']['target_value']='http://other.test/'
        self.db.sql.execute('UPDATE cti_wpt_verified_evidence SET result_json=?',(json.dumps(changed),));self.db.sql.commit()
        with patch('cti_services.wpt_pipeline.logging'):
            self.worker.process_one()
        self.assertEqual(self.db.job()['status'],'FAILED')
        self.orch.run_scan.assert_not_called()

    def test_failure_retry_is_bounded_and_each_attempt_gets_distinct_child(self):
        self.worker.enqueue(payload());self.orch.run_scan.side_effect=RuntimeError('fixture failure')
        children=[]
        with patch('cti_services.wpt_pipeline.logging'):
            for _ in range(3):
                self.worker.process_one();children.append(self.db.job()['pipeline_mission_id']);self.worker.enqueue(payload())
        self.assertEqual(len(set(children)),3)
        self.assertFalse(self.worker.process_one())
        self.assertEqual(self.db.job()['status'],'FAILED')

    def test_expired_lease_recovers_and_old_owner_cannot_finalize(self):
        self.worker.enqueue(payload());old=self.worker._claim()
        self.db.sql.execute("UPDATE cti_wpt_pipeline_jobs SET lease_until='2000-01-01'");self.db.sql.commit()
        other=WptPipeline(self.db,self.orch);other.transaction=self.db.transaction
        new=other._claim()
        self.assertNotEqual(old['pipeline_mission_id'],new['pipeline_mission_id'])
        self.worker._finish(old,'COMPLETED',{},None,None)
        self.assertEqual(self.db.job()['status'],'RUNNING')

    def test_unknown_version_never_inherits_reference_release_and_no_network_fetch(self):
        r=result();before=copy.deepcopy(r)
        scan=build_scan(payload(),r,'child-one')
        self.assertEqual(scan['cpe_candidates'][0]['cpe23_uri'].split(':')[5],'*')
        self.assertFalse(scan['auto_acquire_cti']);self.assertFalse(scan['cpe_auto_fetch'])
        self.assertEqual(r,before)
        binding=CtiSubsystemOrchestrator._mission_binding(scan,'child-one',{})
        self.assertEqual(binding['wpt_binding']['evidence_manifest_sha256'],'a'*64)

    def test_high_confidence_fingerprint_remains_unverified_through_mapping(self):
        svc=AssetProfilingCpeResolutionService.__new__(AssetProfilingCpeResolutionService)
        candidate=build_scan(payload(),result(),'child-one')['cpe_candidates'][0]
        candidate.update(match_method='official_cpe_exact_version',match_confidence=0.99)
        claims=svc._claims_for_candidates({'mission_id':'child-one','asset_id':'asset-one','asset_profile_id':'profile-one'},[],[candidate])
        self.assertEqual(claims[0]['status'],'AMBIGUOUS')
        corr=VulnerabilityCorrelationService.__new__(VulnerabilityCorrelationService)._correlation_from_match(
            'child-one',claims[0],{'cve_id':'CVE-2024-1234','match_method':'cpe_exact','match_confidence':0.99},None)
        self.assertEqual(corr['status'],'NEEDS_VERIFICATION');self.assertEqual(corr['symbolic_result'],'UNKNOWN')
        mapping=AttackMappingService.__new__(AttackMappingService)._verify_mapping(corr,{'attack_id':'T1190','mapping_source':'seed','confidence':0.99})
        self.assertEqual(mapping['verification_state'],'PROVISIONAL')


if __name__=='__main__':unittest.main()
