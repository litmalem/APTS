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
  if auth:headers['X-APTS-Client-Token']='test-secret'
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
  status,health=self.call('/api/health');self.assertEqual(status,200);self.assertEqual(health['scan_execution'],'STAGE6_ONLY');self.assertFalse(health['direct_target_io'])
  status,data=self.call('/')
  self.assertEqual(status,200);self.assertIn(b'Web Technology Profiler',data if isinstance(data,bytes) else b'');self.assertNotIn(b'STANDALONE',data if isinstance(data,bytes) else b'')
 def test_create_job_only_proposes_no_scan(self):
  status,data=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mode':'fingerprinting','mission_id':'mission-gmo-test','task_id':'ptask-test'})
  self.assertEqual(status,201);self.assertEqual(data['job']['status'],'PROPOSED')
  self.assertIn('tidak melakukan target I/O',data['note'])
 def test_standalone_execution_is_rejected_without_target_io(self):
  status,data=self.call('/api/jobs','POST',{'target':self.base,'execution_mode':'STANDALONE','local_authorized':True})
  self.assertEqual(status,400);self.assertIn('Stage 6',data['error'])
  self.assertFalse(hasattr(app,'standalone_scan'))
 def test_standalone_allowlist_api_is_retired(self):
  status,data=self.call('/api/remote-allowlist')
  self.assertEqual(status,410);self.assertIn('Mission/Governance',data['error'])
 def test_dispatch_submits_governed_intake_and_stays_pending_stage6(self):
  from unittest.mock import patch
  _,created=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mode':'fingerprinting','mission_id':'mission-gmo-test','task_id':'ptask-test'})
  job_id=created['job']['job_id']
  accepted={'record':{'status':'ACCEPTED_PENDING_STAGE6','semantics':{'target_io_performed':False}}}
  with patch.object(app,'dispatch_job',return_value=accepted):
   status,data=self.call('/api/jobs/'+job_id+'/dispatch','POST',{})
  self.assertEqual(status,202);self.assertEqual(data['status'],'AWAITING_STAGE6')
  self.assertFalse(data['target_io_performed'])
  _,saved=self.call('/api/jobs/'+job_id)
  self.assertEqual(saved['job']['status'],'AWAITING_STAGE6')
  self.assertIsNone(saved['job']['result'])
 def test_dispatch_fails_closed_without_stage6_capability(self):
  _,created=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mode':'enumeration','mission_id':'mission-gmo-test','task_id':'ptask-test'})
  status,data=self.call('/api/jobs/'+created['job']['job_id']+'/dispatch','POST',{})
  self.assertEqual(status,503);self.assertEqual(data['status'],'BLOCKED_CONFIGURATION');self.assertFalse(data['target_io_performed'])
 def test_callback_requires_auth_and_records_agent_separately(self):
  _,created=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mission_id':'mission-gmo-test','task_id':'ptask-test'})
  path='/api/jobs/'+created['job']['job_id']+'/deliveries/reconnaissance'
  self.assertEqual(self.call(path,'POST',{'delivery_id':'evt-1'})[0],401)
  self.assertEqual(self.call(path,'POST',{'delivery_id':'evt-1'},auth=True)[0],200)
  _,record=self.call('/api/jobs/'+created['job']['job_id'])
  self.assertEqual(record['job']['recon_status'],'DELIVERED');self.assertEqual(record['job']['enum_status'],'NOT_SENT')
 def test_result_drops_response_body_and_cookie_fields(self):
  _,created=self.call('/api/jobs','POST',{'target':'https://lab.example.test','mission_id':'mission-gmo-test','task_id':'ptask-test'})
  path='/api/jobs/'+created['job']['job_id']+'/result'
  self.assertEqual(self.call(path,'POST',{'status':'COMPLETED','execution_id':'exec-test','result':{'mission_id':'mission-gmo-test','task_id':'ptask-test','target':'https://lab.example.test','technology_claims':['Apache'],'evidence':{'capture_status':'SEALED','manifest_sha256':'a'*64},'body':'private','set_cookie':'secret'}},auth=True)[0],200)
  _,record=self.call('/api/jobs/'+created['job']['job_id'])
  self.assertEqual(record['job']['result'],{'mission_id':'mission-gmo-test','task_id':'ptask-test','target':'https://lab.example.test','technology_claims':['Apache'],'evidence':{'capture_status':'SEALED','manifest_sha256':'a'*64}})

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

if __name__=='__main__':unittest.main()
