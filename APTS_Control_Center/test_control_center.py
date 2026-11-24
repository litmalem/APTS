"""Isolated tests: synthetic HTTP service, no actual APTS databases or target actions."""
import importlib.util, json, socket, sys, tempfile, threading, time, unittest
from unittest.mock import patch
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

spec=importlib.util.spec_from_file_location('hub',Path(__file__).with_name('server.py'))
hub=importlib.util.module_from_spec(spec); spec.loader.exec_module(hub)
class Fake(BaseHTTPRequestHandler):
 def do_GET(self):
  data=json.dumps({'status':'ok','path':self.path}).encode()
  self.send_response(200);self.end_headers();self.wfile.write(data)
 def log_message(self,*args): pass

class ControlCenterTests(unittest.TestCase):
 def test_cti_enumeration_consumers_receive_local_credentials_and_enablement(self):
  modules={'vulndesk':{'port':9876,'env':{'APTS_WPT_CTI_SHARED_TOKEN':'test-secret'}},
   'mission':{'root':'mission','port':8780,'env':{}},'pentest':{'env':{}}}
  with patch.dict(hub.CONFIG,{'modules':modules}):
   for key in ('mission','pentest','pentest_web','mission_web'):
    env=hub.module_config(key)['env']
    self.assertEqual(env['APTS_CTI_ENUMERATION_URL'],'http://127.0.0.1:9876')
    self.assertEqual(env['APTS_WPT_CTI_SHARED_TOKEN'],'test-secret')
   self.assertEqual(hub.module_config('mission')['env']['APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY'],'1')
   self.assertEqual(modules['pentest']['env'],{})
   modules['mission']['env']['APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY']='0'
   self.assertEqual(hub.module_config('mission')['env']['APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY'],'0')
   modules['pentest']['env']['APTS_WPT_CTI_SHARED_TOKEN']='conflicting-secret'
   with self.assertRaisesRegex(ValueError,'Token CTI consumer'):
    hub.module_config('pentest')

 @classmethod
 def setUpClass(cls):
  cls.log_directory=tempfile.TemporaryDirectory()
  cls.original_logs=hub.LOGS;hub.LOGS=Path(cls.log_directory.name)
  cls.fake=ThreadingHTTPServer(('127.0.0.1',0),Fake)
  cls.server=ThreadingHTTPServer(('127.0.0.1',0),hub.Handler)
  for s in (cls.fake,cls.server): threading.Thread(target=s.serve_forever,daemon=True).start()
  cls.url=f'http://127.0.0.1:{cls.server.server_port}'
 @classmethod
 def tearDownClass(cls):
  for s in (cls.fake,cls.server): s.shutdown();s.server_close()
  hub.LOGS=cls.original_logs;cls.log_directory.cleanup()
 def request(self,path,body=None,token=True,host=None):
  headers={'X-Control-Token':hub.TOKEN} if token else {}
  if host:headers['Host']=host
  req=Request(self.url+path,headers=headers,data=json.dumps(body).encode() if body else None)
  with urlopen(req) as r:return r.read()
 def test_page_token_and_assets(self):
  self.assertIn(hub.TOKEN.encode(),self.request('/'))
  self.assertIn(b'async function',self.request('/app.js'))
 def test_token_required(self):
  with self.assertRaises(HTTPError) as c:self.request('/api/status',token=False)
  self.assertEqual(c.exception.code,403)
 def test_rebinding_host_blocked(self):
  with self.assertRaises(HTTPError) as c:self.request('/',host='attacker.example')
  self.assertEqual(c.exception.code,403)
 def test_external_service_not_stopped(self):
  with self.assertRaises(HTTPError) as c:self.request('/api/action',{'module':'gss','action':'stop'})
  self.assertEqual(c.exception.code,400)
 def test_arbitrary_proxy_path_rejected(self):
  with self.assertRaises(HTTPError) as c:self.request('/api/inspect?module=gss&path=http://example.com')
  self.assertEqual(c.exception.code,400)
 def test_read_only_proxy(self):
  old=hub.CONFIG['modules']['pentest']['port'];hub.CONFIG['modules']['pentest']['port']=self.fake.server_port
  try:
   r=json.loads(self.request('/api/inspect?module=pentest&path=/api/pentest/tasks'))
   self.assertTrue(r['ok']);self.assertEqual(r['data']['path'],'/api/pentest/tasks')
   self.assertIn('sudah aktif',hub.action('pentest','start')['message'])
  finally:hub.CONFIG['modules']['pentest']['port']=old
 def test_owned_process_start_stop_and_log(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'run').mkdir();(root/'run/run_vulndesk_api.py').write_text('import time\nprint("synthetic worker",flush=True)\ntime.sleep(30)\n')
   old=hub.CONFIG['modules']['vulndesk'].copy();hub.CONFIG['modules']['vulndesk']['root']=tmp
   try:
    started=hub.action('vulndesk','start');self.assertGreater(started['pid'],0)
    self.assertEqual(hub.action('vulndesk','start')['pid'],started['pid'])
    hub.action('vulndesk','stop');self.assertIsNotNone(hub.PROCESSES['vulndesk'].poll())
   finally:
    p=hub.PROCESSES.pop('vulndesk',None)
    if p and p.poll() is None:p.kill();p.wait()
    hub.CONFIG['modules']['vulndesk']=old

 def test_web_legacy_config_defaults(self):
  modules={key:value for key,value in hub.CONFIG['modules'].items() if key!='vulndesk_web'}
  modules['vulndesk']={'root':'custom Vulndesk','port':8765,'python':sys.executable,'env':{'SHARED_SETTING':'inherited'}}
  with patch.dict(hub.CONFIG,{'modules':modules}):
   cfg=hub.module_config('vulndesk_web')
   self.assertEqual(cfg['root'],str(Path('custom Vulndesk')/'Vulndesk_Web'))
   self.assertEqual(cfg['port'],8801)
   self.assertEqual(cfg['python'],sys.executable)
   self.assertEqual(cfg['env']['SHARED_SETTING'],'inherited')

 def test_web_interpreter_and_environment_overrides(self):
  base={'root':'Vulndesk','port':8765,'python':'base-python','env':{'SHARED':'base','BASE_ONLY':'kept'}}
  web={'root':'separate Web folder','port':8802,'python':'','env':{'SHARED':'web'}}
  with patch.dict(hub.CONFIG['modules'],{'vulndesk':base,'vulndesk_web':web}):
   cfg=hub.module_config('vulndesk_web')
   self.assertEqual(cfg['python'],'base-python')
   self.assertEqual(cfg['root'],'separate Web folder')
   self.assertEqual(cfg['port'],8802)
   self.assertEqual(cfg['env'],{'SHARED':'web','BASE_ONLY':'kept'})
   web['python']='web-python'
   self.assertEqual(hub.module_config('vulndesk_web')['python'],'web-python')

 def test_web_status_and_monitor_use_database_free_config(self):
  with patch.dict(hub.CONFIG['modules'],{'vulndesk_web':{'port':self.fake.server_port}}):
   r=hub.status('vulndesk_web')
   self.assertTrue(r['ok']);self.assertEqual(r['data']['path'],'/api/config')
   r=json.loads(self.request('/api/inspect?module=vulndesk_web'))
   self.assertEqual(r['data']['path'],'/api/config')
   overview=json.loads(self.request('/api/status'))
   self.assertEqual(len(overview['modules']),9)
   self.assertIn('vulndesk_web',[item['id'] for item in overview['modules']])
   with self.assertRaises(HTTPError) as c:self.request('/api/inspect?module=vulndesk_web&path=/api/runtime/start')
   self.assertEqual(c.exception.code,400)

 def test_web_port_busy_and_external_process_not_stopped(self):
  with patch.dict(hub.CONFIG['modules'],{'vulndesk_web':{'port':self.fake.server_port}}),patch.object(hub.subprocess,'Popen') as popen:
   result=json.loads(self.request('/api/action',{'module':'vulndesk_web','action':'start'}))
   self.assertIn('sudah aktif',result['message'])
   with self.assertRaises(HTTPError) as c:self.request('/api/action',{'module':'vulndesk_web','action':'stop'})
   self.assertEqual(c.exception.code,400)
   popen.assert_not_called()
   self.assertTrue(hub.status('vulndesk_web')['ok'])

 def test_web_open_uses_local_browser_and_configured_port(self):
  with patch.dict(hub.CONFIG['modules'],{'vulndesk_web':{'port':self.fake.server_port}}),patch.object(hub.webbrowser,'open_new_tab',return_value=True) as opened:
   r=json.loads(self.request('/api/action',{'module':'vulndesk_web','action':'open'}))
   url=f'http://127.0.0.1:{self.fake.server_port}'
   self.assertEqual(r['url'],url);opened.assert_called_once_with(url)
   with self.assertRaises(HTTPError) as c:self.request('/api/action',{'module':'gss','action':'open'})
   self.assertEqual(c.exception.code,400)

 def test_web_open_offline_rejected(self):
  with patch.object(hub,'fetch',return_value={'ok':False}),patch.object(hub.webbrowser,'open_new_tab') as opened:
   with self.assertRaises(HTTPError) as c:self.request('/api/action',{'module':'vulndesk_web','action':'open'})
   self.assertEqual(c.exception.code,400)
   opened.assert_not_called()

 def test_all_services_uses_unique_processes_and_dependency_order(self):
  called=[]
  with patch.object(hub,'action',side_effect=lambda key,verb: called.append((key,verb)) or {'message':'queued'}):
   result=hub.action_all('start')
  self.assertEqual(called,[('vulndesk','start'),('vulndesk_web','start'),('gss','start'),('gss_web','start'),('mission','start'),('mission_web','start'),('pentest','start'),('pentest_web','start'),('wpt','start')])
  self.assertEqual(len(result['results']),9)
  self.assertIn('mission_web',[key for key,_ in called])
  self.assertIn('pentest_web',[key for key,_ in called])

 def test_all_services_continues_after_runtime_configuration_error(self):
  called=[]
  def start_or_fail(key,verb):
   called.append((key,verb))
   if key=='mission':raise RuntimeError('Inbox token mismatch')
   return {'message':'queued'}
  with patch.object(hub,'action',side_effect=start_or_fail):
   result=hub.action_all('start')
  self.assertEqual(len(called),9)
  self.assertEqual(called[-1],('wpt','start'))
  mission=next(item for item in result['results'] if item['module']=='mission')
  self.assertFalse(mission['ok'])
  self.assertEqual(mission['message'],'Inbox token mismatch')
  self.assertTrue(next(item for item in result['results'] if item['module']=='wpt')['ok'])

 def test_runtime_action_error_returns_json_instead_of_dropping_connection(self):
  with patch.object(hub,'action',side_effect=RuntimeError('Inbox ACL setup failed')):
   with self.assertRaises(HTTPError) as c:
    self.request('/api/action',{'module':'mission','action':'start'})
  self.assertEqual(c.exception.code,400)
  self.assertEqual(json.loads(c.exception.read()),{'error':'Inbox ACL setup failed'})

 def test_start_monitors_healthy_mission_running_outside_panel(self):
  with patch.object(hub,'fetch',return_value={'ok':True}), patch.object(hub.subprocess,'Popen') as popen, patch.object(hub,'ensure_wpt_inbox_bridge') as bridge:
   result=hub.action('mission_web','start')
  self.assertIsNone(result['pid'])
  self.assertIn('sudah aktif',result['message'])
  popen.assert_not_called()
  bridge.assert_not_called()

 def test_windows_principal_includes_domain_separator(self):
  with patch.dict('os.environ',{'USERDOMAIN':'APTS-LAB','USERNAME':'operator'}):
   self.assertEqual(hub._windows_principal(),r'APTS-LAB\operator')

 def test_wpt_module_config_and_health_route(self):
  with patch.dict(hub.CONFIG['modules'],{},clear=True):
   cfg=hub.module_config('wpt')
  self.assertEqual(cfg['port'],8791)
  self.assertEqual(cfg['env']['WTP_HOST'],'127.0.0.1')
  self.assertEqual(hub.health_path('wpt'),'/api/health')
  self.assertEqual(hub.web_url('wpt'),'http://127.0.0.1:8791')
  with patch.dict(hub.CONFIG['modules'],{'wpt':{'port':self.fake.server_port}}),patch.object(hub.webbrowser,'open_new_tab',return_value=True) as opened:
   result=hub.action('wpt','open')
   self.assertEqual(result['url'],f'http://127.0.0.1:{self.fake.server_port}')
   opened.assert_called_once_with(result['url'])

 def test_wpt_bridge_generates_one_shared_secret_and_local_url(self):
  with tempfile.TemporaryDirectory() as tmp:
   modules={k:{**v,'env':dict(v.get('env',{}))} for k,v in hub.CONFIG['modules'].items()}
   modules['mission']['env'].pop('APTS_WPT_INBOX_TOKEN',None)
   modules['mission']['env']['APTS_WPT_INBOX_URL']='https://stale.invalid/inbox'
   modules['wpt']['env'].pop('WTP_CLIENT_TOKEN',None)
   with patch.dict(hub.CONFIG['modules'],modules,clear=True), patch.object(hub,'STATE_ROOT',Path(tmp)), patch.object(hub,'WPT_INBOX_SECRET_FILE',Path(tmp)/'wpt-inbox.token'), patch.dict('os.environ',{'APTS_WPT_INBOX_TOKEN':'','WTP_CLIENT_TOKEN':''},clear=False):
    result=hub.ensure_wpt_inbox_bridge()
    mission=hub.CONFIG['modules']['mission']['env'];wpt=hub.CONFIG['modules']['wpt']['env']
    self.assertTrue(result['configured']);self.assertNotIn('token',result)
    self.assertEqual(mission['APTS_WPT_INBOX_TOKEN'],wpt['WTP_CLIENT_TOKEN'])
    self.assertGreaterEqual(len(mission['APTS_WPT_INBOX_TOKEN']),32)
    self.assertEqual(mission['APTS_WPT_INBOX_URL'],f"http://127.0.0.1:{hub.CONFIG['modules']['wpt']['port']}")
    self.assertEqual(Path(tmp,'wpt-inbox.token').read_text(encoding='ascii'),mission['APTS_WPT_INBOX_TOKEN'])

 def test_wpt_bridge_rejects_conflicting_explicit_tokens(self):
  modules={k:{**v,'env':dict(v.get('env',{}))} for k,v in hub.CONFIG['modules'].items()}
  modules['mission']['env']['APTS_WPT_INBOX_TOKEN']='a'*48
  modules['wpt']['env']['WTP_CLIENT_TOKEN']='b'*48
  with patch.dict(hub.CONFIG['modules'],modules,clear=True):
   with self.assertRaisesRegex(RuntimeError,'berbeda'):
    hub.ensure_wpt_inbox_bridge()

 def test_wpt_owned_process_lifecycle(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   (root/'app.py').write_text('''import os
from http.server import BaseHTTPRequestHandler,HTTPServer
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(b'{"status":"ok"}')
 def log_message(self,*args):pass
HTTPServer(('127.0.0.1',int(os.environ['WTP_PORT'])),H).serve_forever()
''',encoding='utf-8')
   with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   config={'root':tmp,'port':port,'python':sys.executable,'env':{'WTP_HOST':'127.0.0.1','WTP_PORT':str(port)}}
   with patch.dict(hub.CONFIG['modules'],{'wpt':config}), patch.object(hub,'STATE_ROOT',Path(tmp)/'state'), patch.object(hub,'WPT_INBOX_SECRET_FILE',Path(tmp)/'state'/'wpt-inbox.token'):
    try:
     started=hub.action('wpt','start')
     deadline=time.monotonic()+5
     while time.monotonic()<deadline and not hub.status('wpt')['ok']:time.sleep(.05)
     state=hub.status('wpt')
     self.assertTrue(state['ok'],state)
     self.assertEqual(state['pid'],started['pid'])
     self.assertEqual(state['web_url'],f'http://127.0.0.1:{port}')
     hub.action('wpt','stop')
     self.assertIsNotNone(hub.PROCESSES['wpt'].poll())
    finally:
     child=hub.PROCESSES.pop('wpt',None)
     if child and child.poll() is None:child.kill();child.wait()

 def test_owned_web_process_cli_lifecycle_and_logs(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'Vulndesk source with spaces';web=root/'Vulndesk_Web';web.mkdir(parents=True)
   (web/'server.py').write_text('''import argparse, json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
parser=argparse.ArgumentParser()
parser.add_argument('--vulndesk-root',required=True)
parser.add_argument('--port',type=int,required=True)
args=parser.parse_args()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path!='/api/config':
   self.send_error(404);return
  data=json.dumps({'vulndesk_root':args.vulndesk_root,'cwd':os.getcwd(),
                   'inherited':os.environ.get('WEB_TEST_BASE'),'override':os.environ.get('WEB_TEST_OVERRIDE')}).encode()
  self.send_response(200);self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
print('synthetic Vulndesk Web',flush=True)
HTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
''',encoding='utf-8')
   with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   base={'root':str(root),'port':8765,'python':sys.executable,'env':{'WEB_TEST_BASE':'inherited','WEB_TEST_OVERRIDE':'base'}}
   config={'root':str(web),'port':port,'python':'','env':{'WEB_TEST_OVERRIDE':'web'}}
   with patch.dict(hub.CONFIG['modules'],{'vulndesk':base,'vulndesk_web':config}):
    try:
     started=json.loads(self.request('/api/action',{'module':'vulndesk_web','action':'start'}))
     deadline=time.monotonic()+5
     while True:
      state=hub.status('vulndesk_web')
      if state['ok'] or time.monotonic()>=deadline:break
      time.sleep(.05)
     self.assertTrue(state['ok'],state)
     self.assertTrue(state['owned']);self.assertEqual(state['pid'],started['pid'])
     self.assertEqual(state['data']['vulndesk_root'],str(root.resolve()))
     self.assertEqual(state['data']['cwd'],str(web.resolve()))
     self.assertEqual(state['data']['inherited'],'inherited')
     self.assertEqual(state['data']['override'],'web')
     again=json.loads(self.request('/api/action',{'module':'vulndesk_web','action':'start'}))
     self.assertEqual(again['pid'],started['pid'])
     log=json.loads(self.request('/api/logs?module=vulndesk_web'))['log']
     self.assertIn('synthetic Vulndesk Web',log)
     self.request('/api/action',{'module':'vulndesk_web','action':'stop'})
     self.assertIsNotNone(hub.PROCESSES['vulndesk_web'].poll())
    finally:
     child=hub.PROCESSES.pop('vulndesk_web',None)
     if child and child.poll() is None:child.kill();child.wait()

if __name__=='__main__':unittest.main(verbosity=2)
