"""Durable, local-only WPT -> existing CTI DAG bridge; no target execution."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import logging
import threading
import uuid

from .wpt_verified_enrichment import normalize, canonical_bytes, TABLE, SCHEMA
from .db_adapter import to_json

JOBS = 'cti_wpt_pipeline_jobs'
STAGES = {'vulnerability_correlation':'vulnerability', 'attack_mapping':'attack_mapping',
          'risk_prioritization':'risk', 'pip_assembly':'pip'}


def migrate(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS cti_wpt_pipeline_jobs (
        intake_id varchar(191) PRIMARY KEY, input_sha256 char(64) NOT NULL,
        parent_mission_id varchar(191) NOT NULL, pipeline_mission_id varchar(120),
        status varchar(30) NOT NULL DEFAULT 'PENDING', attempt_count int NOT NULL DEFAULT 0, max_attempts int NOT NULL DEFAULT 3,
        lease_owner char(32), lease_until datetime, stage_status_json longtext,
        summary_json longtext, last_error varchar(500), created_at datetime DEFAULT CURRENT_TIMESTAMP,
        started_at datetime, completed_at datetime, updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        KEY idx_wpt_pipeline_pending(status,lease_until)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    cursor.execute('ALTER TABLE '+JOBS+' ADD COLUMN IF NOT EXISTS max_attempts int NOT NULL DEFAULT 3')


def build_scan(payload, result, child_id):
    """Use the authenticated observation, never a reference release as target version."""
    payload = normalize(payload)
    evidence = [payload['wpt_intake_id'], payload['evidence_manifest_sha256'],
                payload['source_result_sha256'], payload['recon_run_id']]
    candidates = []
    for original in result.get('cpe_candidates') or []:
        uri = original.get('cpe23_uri') or original.get('reference_cpe23_uri') or ''
        parts = uri.split(':')
        if len(parts) != 13 or parts[:2] != ['cpe','2.3']:
            continue
        version = original.get('technology_version') or ''
        parts[5] = version or '*'
        candidate = {**original, 'cpe23_uri':':'.join(parts), 'version':version,
                     'wpt_context_only':True, 'exploitability_confirmed':False}
        candidates.append(candidate)
    return {
        'mission_id':child_id, 'scan_job_id':payload['wpt_intake_id'],
        'target_url':payload['target']['target_value'],
        'asset_id':'wpt-asset-'+hashlib.sha256(payload['target']['target_value'].encode()).hexdigest()[:24],
        'technologies':payload['technologies'], 'cpe_candidates':candidates,
        'auto_acquire_cti':False, 'cpe_auto_fetch':False, 'wpt_context_only':True,
        'evidence_refs':evidence,
        'wpt_binding':{k:payload[k] for k in ('mission_id','task_id','recon_run_id','wpt_intake_id',
                                           'evidence_manifest_sha256','source_result_sha256')},
        'assumptions_and_gaps':[{'gap_code':'WPT_OBSERVATION_REQUIRES_CONFIGURATION_EVIDENCE',
                                 'severity':'MEDIUM','evidence_refs':evidence}],
        'cti_runtime_timeout_seconds':600,
    }


def payload_from_record(row):
    result=json.loads(row['result_json'])
    payload={'schema_version':SCHEMA,'mission_id':row['mission_id'],'task_id':row['task_id'],
             'recon_run_id':row['recon_run_id'],'wpt_intake_id':row['intake_id'],
             'evidence_manifest_sha256':row['evidence_manifest_sha256'],
             'source_result_sha256':result['source_result_sha256'],'target':result['target'],
             'technologies':result['observed_technologies'],'evidence_status':result['evidence_status']}
    payload=normalize(payload)
    if hashlib.sha256(canonical_bytes(payload)).hexdigest()!=row['input_sha256']:
        raise ValueError('Stored WPT observation does not match sealed envelope hash')
    return payload


class WptPipeline:
    def __init__(self, db, orchestrator):
        self.db, self.orchestrator = db, orchestrator
        self.owner = uuid.uuid4().hex
        self.stop_event = threading.Event()
        self.thread = None

    @contextmanager
    def transaction(self):
        with self.db.connect() as connection:
            with connection.cursor() as cursor:
                yield cursor

    def enqueue(self, payload):
        payload = normalize(payload)
        digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        with self.transaction() as cursor:
            cursor.execute('SELECT input_sha256 FROM '+TABLE+' WHERE intake_id=%s', (payload['wpt_intake_id'],))
            evidence = cursor.fetchone()
            if not evidence or evidence['input_sha256'] != digest:
                raise ValueError('Durable WPT evidence identity mismatch')
            cursor.execute('INSERT INTO '+JOBS+' (intake_id,input_sha256,parent_mission_id) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE intake_id=VALUES(intake_id)',
                           (payload['wpt_intake_id'],digest,payload['mission_id']))
            cursor.execute('SELECT * FROM '+JOBS+' WHERE intake_id=%s FOR UPDATE',(payload['wpt_intake_id'],))
            job = cursor.fetchone()
            if job['input_sha256'] != digest:
                raise ValueError('WPT pipeline replay conflicts with sealed evidence')
            # A repeated authenticated delivery may retry a failed run, bounded
            # to three attempts. Completed jobs never create another mission.
            if job['status']=='FAILED' and job['attempt_count'] < job['max_attempts']:
                cursor.execute('UPDATE '+JOBS+" SET status='PENDING',last_error=NULL WHERE intake_id=%s",(job['intake_id'],))
                job['status']='PENDING'
        return {key:job.get(key) for key in ('intake_id','status','pipeline_mission_id','attempt_count')}

    def retry_failed(self, intake_id):
        # Explicit operator action only; HMAC replays never extend the budget.
        # Keep total attempt_count and every child mission for audit.
        self.db.execute('UPDATE '+JOBS+" SET status='PENDING',max_attempts=attempt_count+3,lease_owner=NULL,lease_until=NULL WHERE intake_id=%(id)s AND status='FAILED'", {'id':intake_id})

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self._loop,daemon=True,name='cti-wpt-pipeline')
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _claim(self):
        with self.transaction() as cursor:
            cursor.execute('UPDATE '+JOBS+" SET status='FAILED',last_error='LEASE_EXPIRED_RETRY_LIMIT',lease_until=NULL WHERE status='RUNNING' AND lease_until<UTC_TIMESTAMP() AND attempt_count>=max_attempts")
            cursor.execute('SELECT * FROM '+JOBS+" WHERE (status='PENDING' OR (status='RUNNING' AND lease_until<UTC_TIMESTAMP())) AND attempt_count<max_attempts ORDER BY created_at,intake_id LIMIT 1 FOR UPDATE")
            job=cursor.fetchone()
            if not job:
                return None
            attempt=job['attempt_count']+1
            child='ctiwpt-'+hashlib.sha256((job['intake_id']+':'+job['input_sha256']+':'+str(attempt)).encode()).hexdigest()[:48]
            cursor.execute('UPDATE '+JOBS+" SET status='RUNNING',attempt_count=%s,pipeline_mission_id=%s,lease_owner=%s,lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 90 SECOND),started_at=UTC_TIMESTAMP(),completed_at=NULL,stage_status_json=NULL,summary_json=NULL,last_error=NULL WHERE intake_id=%s",
                           (attempt,child,self.owner,job['intake_id']))
            job.update(attempt_count=attempt,pipeline_mission_id=child,status='RUNNING')
            return job

    def _load(self, job):
        row=self.db.fetch_one('SELECT * FROM '+TABLE+' WHERE intake_id=%(id)s',{'id':job['intake_id']})
        if not row or row['input_sha256'] != job['input_sha256']:
            raise ValueError('WPT evidence changed before pipeline processing')
        return build_scan(payload_from_record(row),json.loads(row['result_json']),job['pipeline_mission_id'])

    def enqueue_stored(self, intake_id):
        row=self.db.fetch_one('SELECT * FROM '+TABLE+' WHERE intake_id=%(id)s',{'id':intake_id})
        if not row:
            raise ValueError('Stored WPT intake not found')
        return self.enqueue(payload_from_record(row))

    def _heartbeat(self, job, done):
        while not done.wait(15) and not self.stop_event.is_set():
            try:
                self.db.execute('UPDATE '+JOBS+" SET lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 90 SECOND) WHERE intake_id=%(id)s AND lease_owner=%(owner)s AND status='RUNNING'",
                                {'id':job['intake_id'],'owner':self.owner})
            except Exception:
                logging.getLogger(__name__).exception('WPT pipeline lease renewal failed')

    def process_one(self):
        job=self._claim()
        if not job:
            return False
        done=threading.Event()
        heartbeat=threading.Thread(target=self._heartbeat,args=(job,done),daemon=True)
        heartbeat.start()
        try:
            response=self.orchestrator.run_scan(self._load(job))
            outputs=response.get('component_outputs') or {}
            # A disabled/skipped service is not reported as a completed stage.
            stages={stage:('COMPLETED' if outputs.get(key,{}).get('status')=='completed' else 'NOT_COMPLETED')
                    for stage,key in STAGES.items()}
            if any(value!='COMPLETED' for value in stages.values()):
                raise RuntimeError('CTI pipeline did not complete every required stage')
            pip=response.get('pentest_intelligence_package') or {}
            summary={**(response.get('summary') or {}),'pip_id':pip.get('pip_id'),
                     'readiness':pip.get('readiness') or (pip.get('quality') or {}).get('readiness'),
                     'verified_vulnerability_count':0,'target_io_performed_by_cti':False,
                     'execution_authorized':False}
            self._finish(job,'COMPLETED',stages,summary,None)
        except Exception as exc:
            logging.getLogger(__name__).exception('WPT local CTI pipeline failed for %s',job['intake_id'])
            self._finish(job,'FAILED',{},None,(type(exc).__name__+': '+str(exc))[:500])
        finally:
            done.set()
            heartbeat.join(timeout=1)
        return True

    def _finish(self, job, status, stages, summary, error):
        self.db.execute('UPDATE '+JOBS+' SET status=%(status)s,stage_status_json=%(stages)s,summary_json=%(summary)s,last_error=%(error)s,completed_at=UTC_TIMESTAMP(),lease_until=NULL WHERE intake_id=%(id)s AND lease_owner=%(owner)s',
                        {'status':status,'stages':to_json(stages),'summary':to_json(summary),'error':error,
                         'id':job['intake_id'],'owner':self.owner})

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                if self.process_one():
                    continue
            except Exception:
                logging.getLogger(__name__).exception('WPT pipeline queue unavailable')
            self.stop_event.wait(3)
