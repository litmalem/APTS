import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
os.environ['WTP_DB_PATH']=str(Path(tempfile.mkdtemp())/'test.sqlite3')
os.environ['WTP_CLIENT_TOKEN']='test-secret'
spec=importlib.util.spec_from_file_location('wtp_app', ROOT/'app.py')
app=importlib.util.module_from_spec(spec); spec.loader.exec_module(app)

class ProfilerAPITest(unittest.TestCase):
 def test_cti_v4_intake_carries_candidates_but_cannot_supply_probes(self):
  original=app.CLIENT_TOKEN;app.CLIENT_TOKEN='v'*40
  self.addCleanup(setattr,app,'CLIENT_TOKEN',original)
  context={'source_cti_intake_id':'wptreq-cti-v4','enumeration_run_id':'enumrun-cti-v4',
   'enumeration_request_sha256':'a'*64,'recon_run_id':'reconrun-cti-v4','source_result_sha256':'b'*64,
   'technologies':[{'name':'PHP','version':'8.0.30'}],
   'cpe_candidates':[{'technology_name':'PHP','cpe23_uri':'cpe:2.3:a:php:php:8.0.30:*:*:*:*:*:*:*',
    'match_confidence':.99,'status':'CPE_CANDIDATE_NEEDS_VERIFICATION'}]}
  body={'schema_version':'apts-wpt-governed-intake-v4','intake_id':'wptreq-enum-v4',
   'idempotency_key':'idem-enum-v4','mission_id':'mission-gmo-v4','task_id':'ptask-v4',
   'target':{'target_type':'URL','target_value':'http://127.0.0.1/app/'},'profile':'enumeration',
   'enumeration_context':context}
  status,result=self.call('/api/governed-intakes','POST',body,auth=True)
  self.assertEqual(status,201);self.assertFalse(result['target_io_performed'])
  self.assertEqual(self.call('/api/governed-intakes','POST',body,auth=True)[0],200)
  with app.connection() as conn:
   row=conn.execute('SELECT * FROM governed_intakes WHERE intake_id=?',(body['intake_id'],)).fetchone()
   self.assertEqual(json.loads(row['enumeration_context_json']),context)
  context['probes']=['/admin']
  self.assertEqual(self.call('/api/governed-intakes','POST',body,auth=True)[0],400)

 def test_cti_enumeration_intake_is_bound_idempotent_and_does_not_scan(self):
  original=app.CLIENT_TOKEN;app.CLIENT_TOKEN='t'*40
  self.addCleanup(setattr,app,'CLIENT_TOKEN',original)
  context={'source_cti_intake_id':'wptreq-cti-source','enumeration_run_id':'enumrun-cti-one',
   'enumeration_request_sha256':'a'*64,'recon_run_id':'reconrun-cti-one','source_result_sha256':'b'*64,
   'technologies':[{'name':'PHP','version':'8.0.30'}]}
  body={'schema_version':'apts-wpt-governed-intake-v3','intake_id':'wptreq-enum-cti-one',
   'idempotency_key':'idem-enum-cti-one','mission_id':'mission-gmo-cti-one','task_id':'ptask-cti-one',
   'target':{'target_type':'URL','target_value':'http://127.0.0.1/app/'},'profile':'enumeration',
   'enumeration_context':context}
  status,result=self.call('/api/governed-intakes','POST',body,auth=True)
  self.assertEqual(status,201);self.assertFalse(result['target_io_performed'])
  self.assertEqual(self.call('/api/governed-intakes','POST',body,auth=True)[0],200)
  with app.connection() as conn:
   row=conn.execute('SELECT * FROM governed_intakes WHERE intake_id=?',(body['intake_id'],)).fetchone()
   self.assertEqual(json.loads(row['enumeration_context_json']),context)
   self.assertEqual(conn.execute('SELECT count(*) FROM jobs WHERE intake_id=?',(body['intake_id'],)).fetchone()[0],0)
  body['enumeration_context']={**context,'source_cti_intake_id':'wptreq-different'}
  self.assertEqual(self.call('/api/governed-intakes','POST',body,auth=True)[0],409)
  body['enumeration_context']={**context,'extra':'not-allowed'}
  self.assertEqual(self.call('/api/governed-intakes','POST',body,auth=True)[0],400)

 @classmethod
 def setUpClass(cls):
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
  cls.base=f'http://127.0.0.1:{cls.server.server_port}'
 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=3)
 def call(self,path,method='GET',body=None,auth=False):
  data=None if body is None else json.dumps(body).encode()
  headers={'Content-Type':'application/json'}
  if auth:headers['X-APTS-Client-Token']=app.CLIENT_TOKEN
  req=Request(self.base+path,data=data,headers=headers,method=method)
  try:
   with urlopen(req) as r:
    raw=r.read()
    try:return r.status,json.loads(raw)
    except Exception:return r.status,raw
  except HTTPError as e:return e.code,json.loads(e.read())
 def test_job_requires_apts_mission(self):
  status,data=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mode':'fingerprinting'})
  self.assertEqual(status,400);self.assertIn('Mission ID',data['error'])
 def test_ui_and_health_are_served(self):
  self.assertEqual(self.call('/api/health')[0],200)
  status,data=self.call('/')
  self.assertEqual(status,200);self.assertIn(b'Web Technology Profiler',data if isinstance(data,bytes) else b'')
 def test_create_job_only_proposes_no_scan(self):
  status,data=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mode':'fingerprinting','mission_id':'mission-gmo-test'})
  self.assertEqual(status,201);self.assertEqual(data['job']['status'],'PROPOSED')
  self.assertIn('Belum ada target I/O',data['note'])
 def test_standalone_scans_loopback_without_mission_or_task(self):
  status,data=self.call('/api/jobs','POST',{'target':self.base+'/#/','mode':'fingerprinting','execution_mode':'STANDALONE','local_authorized':True})
  self.assertEqual(status,201)
  job=data['job']
  self.assertEqual(job['status'],'COMPLETED');self.assertIsNone(job['mission_id']);self.assertIsNone(job['task_id'])
  self.assertEqual(job['execution_mode'],'STANDALONE');self.assertEqual(job['result']['execution_context'],'LOCAL_STANDALONE_LOOPBACK')
  self.assertEqual(job['target'],self.base)
  self.assertEqual(job['result']['request_count'],2)
  self.assertIsNotNone(job['scan_started_at']);self.assertIsNotNone(job['scan_finished_at'])
  self.assertGreaterEqual(job['scan_duration_ms'],0)
  self.assertEqual(job['result']['scan_timing']['timezone'],'UTC')
  self.assertTrue(all(o.get('request_started_at') and o.get('response_received_at') and o.get('duration_ms') is not None for o in job['result']['observations']))
  self.assertEqual(job['result']['tls_status'],'NOT_APPLICABLE_HTTP')
 def test_standalone_follows_only_in_scope_web_context_redirect(self):
  from http.server import BaseHTTPRequestHandler
  class RedirectHandler(BaseHTTPRequestHandler):
   def do_GET(self):
    if self.path == '/WebGoat/':
     self.send_response(302);self.send_header('Location','/WebGoat/login');self.end_headers()
    elif self.path == '/WebGoat/login':
     self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'<title>WebGoat login</title>')
    else:self.send_response(404);self.end_headers()
   def log_message(self,*a):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),RedirectHandler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   result=app.standalone_scan(f'http://127.0.0.1:{server.server_port}/WebGoat','fingerprinting')
   self.assertEqual(result['scan_metrics']['responses_received'],2)
   self.assertEqual(result['scan_metrics']['redirects_observed'],1)
   self.assertIn('/WebGoat/login',result['observations'][0]['final_url'])
   self.assertEqual(result['observations'][0]['page_title'],'WebGoat login')
  finally:server.shutdown();server.server_close();thread.join(timeout=3)
 def test_standalone_rejects_remote_target_and_requires_consent(self):
  status,data=self.call('/api/jobs','POST',{'target':'https://lab.example.test','execution_mode':'STANDALONE','local_authorized':True})
  self.assertEqual(status,400);self.assertIn('allowlist WTP',data['error'])
  from unittest.mock import patch
  with patch.dict(os.environ, {'WTP_REMOTE_ALLOWLIST':'lab.example.test:443'}):
   status,data=self.call('/api/jobs','POST',{'target':'https://lab.example.test','execution_mode':'STANDALONE','local_authorized':True})
   self.assertEqual(status,400);self.assertIn('kewenangan',data['error'])
   self.assertTrue(app.is_remote_allowlisted('https://lab.example.test/path'))
   self.assertFalse(app.is_remote_allowlisted('https://lab.example.test:444/path'))
  with patch.dict(os.environ, {'WTP_REMOTE_ALLOWLIST':'https://lab.example.test/'}):
   self.assertTrue(app.is_remote_allowlisted('https://lab.example.test/path'))
   self.assertFalse(app.is_remote_allowlisted('http://lab.example.test/path'))
  status,data=self.call('/api/jobs','POST',{'target':self.base,'execution_mode':'STANDALONE'})
  self.assertEqual(status,400);self.assertIn('Konfirmasi',data['error'])
 def test_remote_allowlist_can_be_managed_from_admin_api(self):
  status,data=self.call('/api/remote-allowlist','POST',{'entry':'https://scan.example.test/'},auth=True)
  self.assertEqual(status,201);self.assertEqual(data['entry'],'https://scan.example.test:443')
  self.assertTrue(app.is_remote_allowlisted('https://scan.example.test/app'))
  status,data=self.call('/api/remote-allowlist')
  self.assertEqual(status,200)
  item=next(x for x in data['entries'] if x['entry']=='https://scan.example.test:443')
  self.assertEqual(item['source'],'ui');self.assertEqual(item['created_by'],'operator-ui');self.assertTrue(item['removable'])
  status,data=self.call('/api/remote-allowlist','POST',{'entry':'*.example.test'},auth=True)
  self.assertEqual(status,400)
  status,data=self.call('/api/remote-allowlist','DELETE',{'entry':'https://scan.example.test:443'},auth=True)
  self.assertEqual(status,200);self.assertFalse(app.is_remote_allowlisted('https://scan.example.test/app'))
 def test_dispatch_fails_closed_without_stage6_capability(self):
  _,created=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mode':'enumeration','mission_id':'mission-gmo-test'})
  status,data=self.call('/api/jobs/'+created['job']['job_id']+'/dispatch','POST',{})
  self.assertEqual(status,503);self.assertEqual(data['status'],'BLOCKED_CONFIGURATION');self.assertFalse(data['target_io_performed'])
 def test_callback_requires_auth_and_records_agent_separately(self):
  _,created=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mission_id':'mission-gmo-test'})
  path='/api/jobs/'+created['job']['job_id']+'/deliveries/reconnaissance'
  self.assertEqual(self.call(path,'POST',{'delivery_id':'evt-1'})[0],401)
  self.assertEqual(self.call(path,'POST',{'delivery_id':'evt-1'},auth=True)[0],200)
  _,record=self.call('/api/jobs/'+created['job']['job_id'])
  self.assertEqual(record['job']['recon_status'],'DELIVERED');self.assertEqual(record['job']['enum_status'],'NOT_SENT')
 def test_result_rejects_response_body_and_cookie_fields(self):
  _,created=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mission_id':'mission-gmo-test'})
  path='/api/jobs/'+created['job']['job_id']+'/result'
  original=app.CLIENT_TOKEN
  app.CLIENT_TOKEN='t'*40
  try:
   result={'mission_id':'mission-gmo-test','target':'https://lab.example.test',
           'body':'private','set_cookie':'secret'}
   status,_=self.call(path,'POST',{'status':'COMPLETED','execution_id':'exec-test',
       'result':result,'result_sha256':app.canonical_sha256(result)},auth=True)
   self.assertEqual(status,400)
   _,record=self.call('/api/jobs/'+created['job']['job_id'])
   self.assertIsNone(record['job']['result'])
  finally:
   app.CLIENT_TOKEN=original

 def test_stage6_job_callback_rejects_authorized_status_without_authorization_id(self):
  original=app.CLIENT_TOKEN;app.CLIENT_TOKEN='z'*40
  self.addCleanup(setattr,app,'CLIENT_TOKEN',original)
  intake='wptreq-authz-guard-one'
  with app.connection() as c:
   c.execute('INSERT INTO governed_intakes(intake_id,idempotency_key,mission_id,task_id,target_type,target_url,profile,received_at) VALUES(?,?,?,?,?,?,?,?)',
    (intake,'idem-authz-one','mission-authz','task-authz','URL','http://127.0.0.1/','fingerprinting',app.now()))
  base=dict(schema_version='apts-wpt-stage6-job-v1',mission_id='mission-authz',task_id='task-authz',
   target='http://127.0.0.1/',profile='fingerprinting',execution_id='exec-authz-one')
  self.assertEqual(self.call('/api/stage6/intakes/'+intake+'/job','POST',{**base,'status':'AUTHORIZED','authorization_id':None},auth=True)[0],400)
  self.assertEqual(self.call('/api/stage6/intakes/'+intake+'/job','POST',{**base,'status':'AUTHORIZED','authorization_id':''},auth=True)[0],400)
  with app.connection() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM jobs WHERE intake_id=?',(intake,)).fetchone()[0],0)
  status,_=self.call('/api/stage6/intakes/'+intake+'/job','POST',{**base,'status':'AUTHORIZED','authorization_id':'eauth-authz-one'},auth=True)
  self.assertEqual(status,201)
  with app.connection() as c:
   self.assertEqual(c.execute('SELECT authorization_id FROM jobs WHERE intake_id=?',(intake,)).fetchone()[0],'eauth-authz-one')

 def test_result_refuses_to_seal_without_authorization_id(self):
  original=app.CLIENT_TOKEN;app.CLIENT_TOKEN='y'*40
  self.addCleanup(setattr,app,'CLIENT_TOKEN',original)
  jid='wpt-authz-seal-guard';ts=app.now()
  with app.connection() as c:
   c.execute('INSERT INTO jobs(job_id,created_at,updated_at,mission_id,task_id,target,requested_by,mode,status,authorization_id,execution_id,execution_mode,intake_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
    (jid,ts,ts,'mission-seal','task-seal','http://127.0.0.1/','mission-stage6','fingerprinting','AWAITING_STAGE6',None,'exec-seal','GOVERNED','wptreq-seal'))
  result={'mission_id':'mission-seal','task_id':'task-seal','target':'http://127.0.0.1/','mode':'fingerprinting','profile':'fingerprinting',
   'evidence':{'capture_status':'SEALED','manifest_sha256':'a'*64,'evidence_ref':'stage6-evidence://xevidence-'+'b'*24}}
  payload={'status':'COMPLETED','execution_id':'exec-seal','result':result,'result_sha256':app.canonical_sha256(result)}
  self.assertEqual(self.call('/api/jobs/'+jid+'/result','POST',payload,auth=True)[0],409)
  with app.connection() as c:
   self.assertIsNone(c.execute('SELECT result_sha256 FROM jobs WHERE job_id=?',(jid,)).fetchone()[0])
   c.execute('UPDATE jobs SET authorization_id=? WHERE job_id=?',('eauth-seal',jid))
  status,data=self.call('/api/jobs/'+jid+'/result','POST',payload,auth=True)
  self.assertEqual(status,200);self.assertEqual(data['status'],'COMPLETED')

 def test_governed_mission_intake_is_authenticated_idempotent_and_non_executing(self):
  original=app.CLIENT_TOKEN
  app.CLIENT_TOKEN='0123456789abcdef0123456789abcdef'
  body={'schema_version':'apts-wpt-governed-intake-v1','intake_id':'wptreq-test-one',
        'idempotency_key':'idem-test-one','mission_id':'mission-gmo-test',
        'task_id':'ptask-test-one','target':{'target_type':'URL','target_value':'https://lab.example.test/app'},
        'profile':'fingerprinting'}
  try:
   self.assertEqual(self.call('/api/governed-intakes','POST',body)[0],401)
   status,result=self.call('/api/governed-intakes','POST',body,auth=True)
   self.assertEqual(status,201);self.assertFalse(result['target_io_performed'])
   status,replay=self.call('/api/governed-intakes','POST',body,auth=True)
   self.assertEqual(status,200);self.assertFalse(replay['created'])
   status,data=self.call('/api/governed-intakes')
   self.assertEqual(status,200)
   row=next(x for x in data['intakes'] if x['intake_id']==body['intake_id'])
   self.assertEqual(row['target_url'],body['target']['target_value'])
   self.assertEqual(row['status'],'AWAITING_STAGE6')
   bad={**body,'target':{'target_type':'URL','target_value':'https://user:password@lab.example.test/'},'intake_id':'wptreq-test-bad','idempotency_key':'idem-test-bad'}
   self.assertEqual(self.call('/api/governed-intakes','POST',bad,auth=True)[0],400)
   conflict={**body,'target':{'target_type':'URL','target_value':'https://other.example.test/'}}
   self.assertEqual(self.call('/api/governed-intakes','POST',conflict,auth=True)[0],409)
  finally:
   app.CLIENT_TOKEN=original

 def test_v2_intake_persists_recon_unobserved_target_provenance(self):
  original=app.CLIENT_TOKEN;app.CLIENT_TOKEN='0123456789abcdef0123456789abcdef'
  body={'schema_version':'apts-wpt-governed-intake-v2','intake_id':'wptreq-recon-v2-one',
        'idempotency_key':'idem-recon-v2-one','mission_id':'mission-gmo-recon-v2',
        'task_id':'ptask-recon-v2-one','target':{'target_type':'URL','target_value':'https://lab.example.test/'},
        'profile':'fingerprinting','recon_target_key':'reconscope-target-one',
        'recon_target_sha256':'a'*64,'recon_target_status':'READY_FOR_COLLECTION','target_is_observed':False}
  status,result=self.call('/api/governed-intakes','POST',body,auth=True)
  self.assertEqual(status,201);self.assertFalse(result['target_io_performed'])
  _,data=self.call('/api/governed-intakes')
  row=next(x for x in data['intakes'] if x['intake_id']==body['intake_id'])
  self.assertEqual(row['recon_target_key'],'reconscope-target-one')
  self.assertEqual(row['recon_target_status'],'READY_FOR_COLLECTION')
  self.assertEqual(row['target_is_observed'],0)
  bad={**body,'intake_id':'wptreq-recon-v2-bad','idempotency_key':'idem-recon-v2-bad','target_is_observed':True}
  self.assertEqual(self.call('/api/governed-intakes','POST',bad,auth=True)[0],400)
  app.CLIENT_TOKEN=original

 def test_recon_prequeue_is_visible_non_executing_and_promotes_idempotently(self):
  original=app.CLIENT_TOKEN;app.CLIENT_TOKEN='0123456789abcdef0123456789abcdef'
  jobs_before={x['job_id'] for x in self.call('/api/jobs')[1]['jobs']}
  body={'schema_version':'apts-wpt-recon-prequeue-v1','intake_id':'wptreq-recon-prequeue-one',
        'idempotency_key':'idem-recon-prequeue-one','mission_id':'mission-gmo-prequeue-one',
        'task_id':'ptask-prequeue-one','target':{'target_type':'URL','target_value':'http://localhost:3000/'},
        'profile':'fingerprinting','recon_target_key':'reconscope-prequeue-one',
        'recon_target_sha256':'b'*64,'recon_target_status':'READY_FOR_COLLECTION',
        'target_is_observed':False,'task_materialized':False}
  try:
   self.assertEqual(self.call('/api/governed-intakes','POST',body)[0],401)
   status,result=self.call('/api/governed-intakes','POST',body,auth=True)
   self.assertEqual(status,201);self.assertEqual(result['status'],'AWAITING_PENTEST_TASK')
   self.assertFalse(result['target_io_performed'])
   status,replay=self.call('/api/governed-intakes','POST',body,auth=True)
   self.assertEqual(status,200);self.assertFalse(replay['created'])
   self.assertEqual(replay['status'],'AWAITING_PENTEST_TASK')
   _,data=self.call('/api/governed-intakes')
   row=next(x for x in data['intakes'] if x['intake_id']==body['intake_id'])
   self.assertEqual(row['status'],'AWAITING_PENTEST_TASK')
   blocked={**body,'waiting_reason_code':'GSS_TARGET_RECON_ALLOW_REQUIRED'}
   self.assertEqual(self.call('/api/governed-intakes','POST',blocked,auth=True)[0],200)
   _,data=self.call('/api/governed-intakes')
   row=next(x for x in data['intakes'] if x['intake_id']==body['intake_id'])
   self.assertEqual(row['waiting_reason_code'],'GSS_TARGET_RECON_ALLOW_REQUIRED')
   self.assertEqual(self.call('/api/governed-intakes','POST',
       {**blocked,'waiting_reason_code':'UNTRUSTED'},auth=True)[0],400)
   # Mission's normal v2 callback is sent only after its task-authority source
   # validates the running task and unique active orchestration.
   promoted={**body,'schema_version':'apts-wpt-governed-intake-v2'}
   promoted.pop('task_materialized')
   status,result=self.call('/api/governed-intakes','POST',promoted,auth=True)
   self.assertEqual(status,200);self.assertTrue(result['promoted'])
   self.assertEqual(result['status'],'AWAITING_STAGE6')
   _,data=self.call('/api/governed-intakes')
   row=next(x for x in data['intakes'] if x['intake_id']==body['intake_id'])
   self.assertEqual(row['status'],'AWAITING_STAGE6')
   self.assertIsNone(row['waiting_reason_code'])
   self.call('/api/governed-intakes','POST',blocked,auth=True)
   _,data=self.call('/api/governed-intakes')
   row=next(x for x in data['intakes'] if x['intake_id']==body['intake_id'])
   self.assertEqual(row['status'],'AWAITING_STAGE6')
   self.assertIsNone(row['waiting_reason_code'])
   jobs_after={x['job_id'] for x in self.call('/api/jobs')[1]['jobs']}
   self.assertEqual(jobs_after,jobs_before)
   obsolete={**body,'intake_id':'wptreq-prequeue-obsolete',
             'idempotency_key':'idem-prequeue-obsolete','recon_target_sha256':'c'*64}
   self.assertEqual(self.call('/api/governed-intakes','POST',obsolete,auth=True)[0],201)
   _,visible=self.call('/api/governed-intakes')
   self.assertNotIn(obsolete['intake_id'],{x['intake_id'] for x in visible['intakes']})
   _,history=self.call('/api/governed-intakes?include_history=1')
   self.assertIn(obsolete['intake_id'],{x['intake_id'] for x in history['intakes']})
   bad={**body,'intake_id':'wptreq-recon-prequeue-bad',
        'idempotency_key':'idem-recon-prequeue-bad','task_materialized':True}
   self.assertEqual(self.call('/api/governed-intakes','POST',bad,auth=True)[0],400)
  finally:
   app.CLIENT_TOKEN=original


class EngineTest(unittest.TestCase):
 def test_profiles_have_bounded_methods_and_no_redirect(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  f=profile_engine.plan_requests('https://lab.example.test','fingerprinting')
  e=profile_engine.plan_requests('https://lab.example.test','enumeration')
  self.assertEqual(len(f),2);self.assertEqual(len(e),5)
  self.assertEqual([x['method'] for x in f],['GET','GET'])
  self.assertEqual(f[1]['purpose'],'favicon_fingerprint')
  self.assertEqual(f[1]['max_response_bytes'],65536)
  self.assertTrue(all(not x['follow_redirects'] for x in e))
  self.assertTrue(all(x['method'] in ('GET','HEAD') for x in e))
 def test_normalizer_excludes_sensitive_headers_and_body(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  out=profile_engine.normalize_responses('https://lab.example.test','fingerprinting',[{'status_code':200,'headers':{'Server':'nginx','Set-Cookie':'s=secret','Content-Type':'text/html'},'cookie_names':['s'],'html_excerpt':'<title>Lab</title><meta name="generator" content="Django">'}])
  self.assertEqual(out['technology_claims'][0]['technology'],'Django')
  self.assertNotIn('set-cookie',out['observations'][0]['headers'])
  self.assertEqual(out['observations'][0]['cookie_names'],['s'])
  self.assertNotIn('secret',json.dumps(out))
  self.assertNotIn('body',out)
 def test_fingerprinting_reports_measurable_rule_evidence_without_raw_html(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  html='<html><head><title>Example</title><meta name="generator" content="WordPress 6.5"><script src="/wp-content/themes/site/app.js"></script></head></html>'
  out=profile_engine.normalize_responses('https://lab.example.test','fingerprinting',[
   {'status_code':200,'headers':{'Server':'nginx','Content-Type':'text/html'},'cookie_names':['wordpress_test_cookie'],'html_excerpt':html},
   {'status_code':200,'headers':{'Content-Type':'image/x-icon'},'body_sha256':'b'*64,'body_bytes_observed':4321}])
  wp=next(x for x in out['technology_findings'] if x['technology']=='WordPress')
  self.assertEqual(wp['evidence_strength_score'],100)
  self.assertEqual(wp['confidence_level'],'high')
  self.assertEqual(wp['observed_version'],'6.5')
  self.assertEqual(out['scan_metrics']['response_rate_percent'],100)
  self.assertEqual(out['scan_metrics']['fingerprints_matched'],2)
  self.assertEqual(out['scan_metrics']['favicon_fingerprints'],1)
  self.assertEqual(out['observations'][1]['favicon_fingerprint']['bytes_observed'],4321)
  self.assertIn('cookie_name', [e['family'] for e in wp['evidence']])
  self.assertNotIn(html,json.dumps(out))
  self.assertNotIn('set-cookie',json.dumps(out).lower())
 def test_yii_and_php_signatures_are_reported_with_technology_layers(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  html='<html><head><title>Login</title><script src="/assets/631da222/yii.js"></script><script src="/assets/631da222/yii.validation.js"></script><script src="/assets/631da222/yii.activeForm.js"></script></head></html>'
  out=profile_engine.normalize_responses('https://cis.example.test','fingerprinting',[
   {'status_code':200,'headers':{'Server':'nginx','Content-Type':'text/html','X-Frame-Options':'SAMEORIGIN','X-Content-Type-Options':'nosniff'},'cookie_names':['PHPSESSID','_csrf'],'html_excerpt':html},
   {'status_code':200,'headers':{'Content-Type':'image/x-icon'},'body_sha256':'c'*64,'body_bytes_observed':1150}])
  findings={item['technology']:item for item in out['technology_findings']}
  self.assertEqual(findings['nginx']['technology_type'],'web_server_or_reverse_proxy')
  self.assertEqual(findings['Yii Framework']['technology_type'],'application_framework')
  self.assertEqual(findings['PHP']['technology_type'],'server_runtime')
  self.assertNotIn('observed_version',findings['Yii Framework'])
  hints={item['category']:item for item in out['security_review_hints']}
  self.assertIn('Content Security Policy',hints)
  self.assertIn('Cookie sesi',hints)
  self.assertIn('Metadata TLS',hints)
  self.assertEqual(hints['Clickjacking protection']['status'],'OBSERVED')
  self.assertEqual(hints['MIME sniffing protection']['status'],'OBSERVED')
 def test_https_tls_unavailable_is_not_reported_as_certificate_failure(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  out=profile_engine.normalize_responses('https://cis.example.test','fingerprinting',[
   {'status_code':200,'headers':{'Content-Type':'text/html'},'html_excerpt':'<title>Login</title>'},
   {'status_code':200,'headers':{'Content-Type':'image/x-icon'},'body_sha256':'d'*64,'body_bytes_observed':100}])
  self.assertEqual(out['tls_status'],'UNAVAILABLE')
  self.assertIn('bukan hasil validasi kepercayaan sertifikat',out['tls_diagnostic'])
 def test_webgoat_redirect_fingerprints_servlet_and_redacts_session_identifier(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  secret='EC40210F68A9B55EC128ED4BCF2E30F0'
  out=profile_engine.normalize_responses('http://localhost:8080/WebGoat','fingerprinting',[
   {'status_code':200,'headers':{'Content-Type':'text/html;charset=UTF-8'},'html_excerpt':'<title>Login Page</title>',
    'redirect_count':1,'final_url':'http://localhost:8080/WebGoat/login'},
   {'status_code':302,'headers':{'Location':f'http://localhost:8080/WebGoat/login;jsessionid={secret}'}}])
  servlet=next(x for x in out['technology_findings'] if x['technology']=='Java Servlet')
  self.assertEqual(servlet['confidence_level'],'medium')
  self.assertEqual(out['favicon_status'],'REDIRECTED')
  self.assertEqual(out['scan_metrics']['redirects_observed'],2)
  serialized=json.dumps(out)
  self.assertNotIn(secret,serialized)
  self.assertIn('jsessionid=[REDACTED]',serialized)
 def test_html_fallback_is_not_counted_as_favicon(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  out=profile_engine.normalize_responses('http://localhost:3000','fingerprinting',[
   {'status_code':200,'headers':{'Content-Type':'text/html'},'html_excerpt':'<title>App</title>'},
   {'status_code':200,'headers':{'Content-Type':'text/html'},'body_sha256':'b'*64,'body_bytes_observed':9000}])
  self.assertEqual(out['favicon_status'],'NON_IMAGE_RESPONSE')
  self.assertEqual(out['scan_metrics']['favicon_fingerprints'],0)
 def test_no_response_is_reported_as_failed_coverage(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  out=profile_engine.normalize_responses('http://127.0.0.1:1','fingerprinting',[
   {'status_code':None,'headers':{},'error':'Connection refused'}, {'status_code':None,'headers':{},'error':'Connection refused'}])
  self.assertEqual(out['scan_metrics']['scan_status'],'NO_RESPONSE')
  self.assertEqual(out['scan_metrics']['response_rate_percent'],0)
  self.assertEqual(out['scan_metrics']['request_errors'],2)

 def test_tls_metadata_is_normalized_and_http_is_explicitly_not_applicable(self):
  from sys import path
  path.insert(0,str(ROOT/'adapters'))
  import profile_engine
  cert={'subject':[[('commonName','localhost')]],'issuer':[[('commonName','local CA')]],'san':[{'type':'DNS','value':'localhost'}],
        'not_before':'Oct 15 00:00:00 2026 GMT','not_after':'Oct 15 00:00:00 2027 GMT','sha256':'a'*64}
  out=profile_engine.normalize_responses('https://localhost','fingerprinting',[
   {'status_code':200,'headers':{'Content-Type':'text/html'},'html_excerpt':'<title>secure</title>',
    'tls':{'protocol':'TLSv1.3','cipher':'TLS_AES_256_GCM_SHA384','certificate':cert,'validation_status':'NOT_VALIDATED'}},
   {'status_code':404,'headers':{}}])
  self.assertEqual(out['tls_status'],'OBSERVED')
  self.assertEqual(out['tls_observations'][0]['protocol'],'TLSv1.3')
  self.assertEqual(out['tls_observations'][0]['certificate']['sha256'],'a'*64)
  http=profile_engine.normalize_responses('http://localhost','fingerprinting',[{'status_code':200,'headers':{}}])
  self.assertEqual(http['tls_status'],'NOT_APPLICABLE_HTTP')

 def test_redirect_is_limited_to_origin_and_application_path(self):
  from sys import path
  path.insert(0,str(ROOT))
  import app as wtp_app
  from urllib.request import Request
  handler=wtp_app.ScopedRedirect('http://127.0.0.1:8080/WebGoat')
  request=Request('http://127.0.0.1:8080/WebGoat/')
  self.assertIsNotNone(handler.redirect_request(request,None,302,'Found',{},'/WebGoat/login'))
  self.assertIsNotNone(handler.redirect_request(request,None,302,'Found',{},'/WebGoat/login2'))
  self.assertIsNone(handler.redirect_request(request,None,302,'Found',{},'/WebGoat/login3'))
  self.assertEqual(handler.redirect_count,2)
  with self.assertRaises(wtp_app.ScopeRedirectBlocked):
   handler.redirect_request(request,None,302,'Found',{},'/login')
  with self.assertRaises(wtp_app.ScopeRedirectBlocked):
   handler.redirect_request(request,None,302,'Found',{},'http://example.com/WebGoat/login')


if __name__=='__main__':unittest.main()
