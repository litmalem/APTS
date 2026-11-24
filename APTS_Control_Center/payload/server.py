"""Local APTS process control and read-only monitoring. Python standard library only."""
import concurrent.futures, json, os, secrets, socket, subprocess, sys, threading, time, webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs, quote

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
PROCESSES = {}
LOGS = ROOT / 'logs'
LOGS.mkdir(exist_ok=True)
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
SPECS = {
 'vulndesk': ('Vulndesk', 'run/run_vulndesk_api.py', ['/api/cti/diagnostics', '/api/cti/components', '/api/cti/architecture']),
 'vulndesk_web': ('Vulndesk Web', 'server.py', ['/api/config']),
 'gss_web': ('aptsGSS Web', 'run_web.py', ['/health']),
 'gss': ('aptsGS', 'run.py', ['/api/governance/diagnostics', '/api/governance/runtime/status', '/api/governance/outbox/status', '/api/governance/emergency-stop']),
 'mission': ('Mission', 'run/run_stage6_10_mission.py', ['/api/subsystem-registry', '/api/subsystems']),
 'mission_web': ('Mission Web', 'run/run_stage6_10_mission.py', ['/api/dashboard/summary', '/api/missions', '/api/operator/attention']),
 'pentest_web': ('Web Pentest', 'run/pentest_subsystem.py', ['/health', '/api/pentest/tasks']),
 'pentest': ('Pentest Subsystem', 'run/pentest_subsystem.py', ['/api/pentest/tasks', '/api/pentest/boundary-contract', '/api/pentest/lifecycle-contract']),
 'wpt': ('Web Technology Profiler', 'app.py', ['/api/health', '/api/jobs'])
}
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self, *args, **kwargs): return None
OPENER = build_opener(ProxyHandler({}), NoRedirect())

def module_config(key):
 if key == 'wpt':
  cfg=CONFIG['modules'].get(key,{'root':'D:/APTS/WebTechnologyProfiler','port':8791,'python':'','env':{'WTP_HOST':'127.0.0.1','WTP_PORT':'8791'}})
  return {**cfg,'env':{**cfg.get('env',{}),'WTP_HOST':cfg.get('env',{}).get('WTP_HOST','127.0.0.1'),'WTP_PORT':str(cfg.get('port',8791))}}
 if key == 'pentest_web': return CONFIG['modules']['pentest'].copy()
 if key == 'mission_web':
  # Mission Web is served by the same Mission Orchestrator process and port.
  # The optional block exists only for forward-compatible env/python overrides;
  # root and port intentionally stay authoritative on modules.mission.
  base=CONFIG['modules']['mission']; web=CONFIG['modules'].get(key,{})
  return {'root':base['root'],'port':base['port'],'python':web.get('python') or base.get('python') or sys.executable,'env':{**base.get('env',{}),**web.get('env',{})}}
 if key == 'gss_web':
  base=CONFIG['modules']['gss']; web=CONFIG['modules'].get(key,{})
  root=web.get('root') or base['root']
  venv=Path(root)/'.venv'/'Scripts'/'python.exe'
  linux_venv=Path(root)/'.venv'/'bin'/'python'
  python=web.get('python') or base.get('python') or (str(venv) if venv.is_file() else str(linux_venv) if linux_venv.is_file() else sys.executable)
  return {'root':root,'port':web.get('port',8802),'python':python,'env':{**base.get('env',{}),**web.get('env',{})}}
 if key != 'vulndesk_web': return CONFIG['modules'][key]
 base = CONFIG['modules']['vulndesk']
 web = CONFIG['modules'].get(key, {})
 return {
  'root': web.get('root') or str(Path(base['root']) / 'Vulndesk_Web'),
  'port': web.get('port', 8801),
  'python': web.get('python') or base.get('python') or sys.executable,
  'env': {**base.get('env', {}), **web.get('env', {})}
 }

def process_owner_key(key):
 return {'mission_web':'mission','pentest_web':'pentest'}.get(key,key)

def log_owner_key(key):
 return process_owner_key(key)

def health_path(key):
 if key == 'wpt': return '/api/health'
 if key == 'pentest_web': return '/pentest/'
 if key == 'vulndesk_web': return '/api/config'
 if key == 'mission_web': return '/ui/'
 return '/health'

def web_url(key):
 cfg=module_config(key)
 suffix={'mission_web':'/ui/','pentest_web':'/pentest/'}.get(key,'')
 return f"http://127.0.0.1:{int(cfg['port'])}{suffix}"

def fetch(key, path=None):
 cfg = module_config(key)
 if path is None: path = health_path(key)
 start = time.monotonic()
 try:
  with OPENER.open(Request(f"http://127.0.0.1:{int(cfg['port'])}" + path, headers={'Accept':'application/json'}), timeout=4) as response:
   raw = response.read(2_000_001)
   if len(raw)>2_000_000: raise ValueError('Response exceeds 2 MB')
   if key == 'mission_web' and path == '/ui/':
    if 'text/html' not in response.headers.get('Content-Type','') or b'/ui/app.js' not in raw:
     raise ValueError('UI Mission belum tersedia. Pasang perbaikan Mission Web lalu restart Mission.')
    data={'ui':'Mission Web','url':web_url(key)}
   elif key == 'pentest_web' and path == '/pentest/':
    if 'text/html' not in response.headers.get('Content-Type','') or b'/pentest/app.js' not in raw:
     raise ValueError('UI Pentest belum tersedia. Pasang APTS_Pentest_UI_Phase1 lalu restart Pentest.')
    data={'ui':'Web Pentest','url':web_url(key)}
   else: data=json.loads(raw)
   return {'ok':True, 'http_status':response.status, 'data':data, 'latency_ms':round((time.monotonic()-start)*1000)}
 except HTTPError as exc:
  return {'ok':False, 'http_status':exc.code, 'error':str(exc), 'data':exc.read(65536).decode('utf-8',errors='replace')}
 except Exception as exc: return {'ok':False, 'error':str(exc)}

def status(key):
 result = fetch(key)
 cfg = module_config(key)
 with LOCK:
  owner=process_owner_key(key)
  p = PROCESSES.get(owner)
  owned = p is not None and p.poll() is None
 result.update(id=key,name=SPECS[key][0],port=cfg['port'],root=cfg['root'],owned=owned,pid=p.pid if owned else None,exit_code=p.poll() if p else None,shared_process=(owner!=key),process_owner=owner,web_url=web_url(key) if key in ('vulndesk_web','gss_web','mission_web','pentest_web','wpt') else None)
 return result

def action(key, verb):
 if key == 'all':
  if verb not in ('start','stop'): raise ValueError('Kontrol semua layanan hanya mendukung start atau stop.')
  return action_all(verb)
 if key not in SPECS or verb not in ('start','stop','open'): raise ValueError('Unknown action')
 owner=process_owner_key(key)
 if verb == 'open':
  if key not in ('vulndesk_web','gss_web','mission_web','pentest_web','wpt'): raise ValueError('Buka Web hanya tersedia untuk modul web.')
  if not fetch(key)['ok']: raise ValueError('Layanan web belum terhubung. Tekan Mulai dan tunggu status WEB AKTIF.')
  url = web_url(key)
  # Open through the local browser launcher: the Web App rejects cross-origin navigation.
  if not webbrowser.open_new_tab(url): raise ValueError('Browser tidak dapat dibuka otomatis. Buka '+url+' melalui alamat browser.')
  return {'message':SPECS[key][0]+' dibuka di browser', 'url':url}
 with LOCK:
  p = PROCESSES.get(owner)
  if verb == 'stop':
   if p is None or p.poll() is not None: raise ValueError('Layanan ini tidak dimulai oleh panel; hentikan melalui terminal asal.')
   p.terminate()
   try: p.wait(timeout=5)
   except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=5)
   msg='Proses Mission dihentikan; Mission Web menggunakan proses Mission yang sama' if key=='mission_web' else 'Proses dihentikan'
   if key=='pentest_web': msg='Pentest dihentikan; Web Pentest dan API menggunakan proses yang sama'
   return {'message':msg, 'pid':p.pid}
  if p and p.poll() is None: return {'message':'Proses masih berjalan', 'pid':p.pid}
  # Treat a healthy process started outside this panel as already ON; never launch a duplicate.
  health = fetch(key)
  if health.get('ok'): return {'message':'Layanan sudah aktif; panel memantau proses yang berjalan', 'pid':None}
  # Mission Web is only a read-only view hosted by Mission; starting it starts Mission.
  launch_key=owner
  cfg = module_config(key)
  with socket.socket() as probe:
   probe.settimeout(.4)
   if probe.connect_ex(('127.0.0.1',int(cfg['port']))) == 0: raise ValueError('Port sudah digunakan. Panel memantau layanan yang sudah berjalan tanpa mengambil alih prosesnya.')
  cwd = Path(cfg['root']).resolve()
  script = cwd / SPECS[launch_key][1]
  if not script.is_file(): raise ValueError('Launcher tidak ditemukan: '+str(script)+'. Periksa config.json.')
  python = cfg.get('python') or sys.executable
  args = [python, '-u', str(script)]
  env = os.environ.copy()
  env.update(cfg.get('env',{}))
  if launch_key == 'wpt': pass  # WPT reads WTP_HOST/WTP_PORT from its environment.
  elif launch_key == 'vulndesk_web': args += ['--vulndesk-root',str(Path(CONFIG['modules']['vulndesk']['root']).resolve()),'--port',str(cfg['port'])]
  elif launch_key == 'gss_web': args += ['--port',str(cfg['port']),'--api-port',str(CONFIG['modules']['gss']['port']),'--mission-port',str(CONFIG['modules']['mission']['port'])]
  elif launch_key == 'gss': env.update(GOV_HOST='127.0.0.1',GOV_PORT=str(cfg['port']),GOV_DEBUG='false')
  else: args += ['--host','127.0.0.1','--port',str(cfg['port'])]
  with (LOGS/(log_owner_key(key)+'.log')).open('ab') as output:
   output.write(('\n--- START '+time.strftime('%Y-%m-%d %H:%M:%S')+' ---\n').encode()); output.flush()
   p = subprocess.Popen(args,cwd=str(cwd),env=env,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,shell=False)
  PROCESSES[owner] = p
  if key=='pentest_web':
   return {'message':'Pentest dimulai; tunggu Web Pentest menjadi WEB AKTIF', 'pid':p.pid}
  if key=='mission_web':
   return {'message':'Mission dimulai; tunggu Mission Web menjadi WEB AKTIF', 'pid':p.pid}
  return {'message':'Proses dimulai; tunggu status WEB AKTIF' if launch_key == 'vulndesk_web' else 'Proses dimulai; tunggu pemeriksaan health', 'pid':p.pid}

def action_all(verb):
 # Include shared web views so all-service results cover both Mission and Mission Web.
 # action() maps each view to its single owning process, so no duplicate process is started.
 start_order=('vulndesk','vulndesk_web','gss','gss_web','mission','mission_web','pentest','pentest_web','wpt')
 keys=start_order if verb=='start' else tuple(reversed(start_order))
 results=[]
 for key in keys:
  if verb=='stop':
   with LOCK:
    p=PROCESSES.get(process_owner_key(key))
    if p is None or p.poll() is not None:
     continue
  try:
   result=action(key,verb)
   results.append({'module':key,'ok':True,'message':result.get('message','')})
  except (ValueError,OSError) as exc:
   results.append({'module':key,'ok':False,'message':str(exc)})
 return {'message':('Permintaan ON' if verb=='start' else 'Permintaan OFF')+' semua layanan selesai diproses.','results':results}

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def reply(self, code, value, content='application/json; charset=utf-8'):
  payload = json.dumps(value,ensure_ascii=False).encode() if content.startswith('application/json') else value
  self.send_response(code); self.send_header('Content-Type',content); self.send_header('Content-Length',str(len(payload))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(payload)
 def valid_host(self): return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
 def do_GET(self):
  if not self.valid_host(): return self.reply(403,{'error':'Invalid Host'})
  parsed = urlsplit(self.path); qs = parse_qs(parsed.query)
  if parsed.path in ('/','/app.js','/style.css'):
   filename = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[parsed.path]
   content = (ROOT/'web'/filename).read_bytes().replace(b'__TOKEN__',TOKEN.encode())
   return self.reply(200,content,{'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[filename])
  if self.headers.get('X-Control-Token') != TOKEN: return self.reply(403,{'error':'Invalid token'})
  try:
   if parsed.path == '/api/status':
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SPECS)) as pool: items=list(pool.map(status,SPECS))
    return self.reply(200,{'modules':items,'checked_at':time.strftime('%Y-%m-%d %H:%M:%S')})
   key=qs.get('module',[''])[0]
   if key not in SPECS: raise ValueError('Unknown module')
   if parsed.path == '/api/logs':
    path=LOGS/(log_owner_key(key)+'.log')
    if path.exists():
     with path.open('rb') as f: f.seek(max(0,path.stat().st_size-65536)); data=f.read().decode('utf-8',errors='replace')
    else: data='Belum ada log. Log tersedia untuk proses yang dimulai melalui panel.'
    return self.reply(200,{'log':data})
   if parsed.path == '/api/inspect':
    path=qs.get('path',[health_path(key)])[0]
    allowed=[health_path(key)]+SPECS[key][2]
    mission=qs.get('mission',[''])[0].strip()
    if mission:
     ident=quote(mission,safe='')
     if key in ('mission','mission_web'): allowed += [f'/api/missions/{ident}',f'/api/missions/{ident}/state',f'/api/missions/{ident}/events',f'/api/missions/{ident}/observability-timeline',f'/api/missions/{ident}/observability-diagnostics']
     if key=='vulndesk': allowed += [f'/api/cti/missions/{ident}/diagnostics',f'/api/cti/missions/{ident}/lineage']
     if key=='gss': allowed += [f'/api/governance/correlation/missions/{ident}']
     if key in ('pentest','pentest_web'): allowed += ['/api/pentest/tasks?mission_id='+ident]
    if path not in allowed: raise ValueError('Endpoint tidak diizinkan')
    return self.reply(200,fetch(key,path))
   return self.reply(404,{'error':'Not found'})
  except ValueError as exc: self.reply(400,{'error':str(exc)})
 def do_POST(self):
  if not self.valid_host() or self.headers.get('X-Control-Token') != TOKEN or self.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.server.server_port}'):
   return self.reply(403,{'error':'Invalid origin or token'})
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0 < length <= 4096: raise ValueError('Invalid body size')
   data=json.loads(self.rfile.read(length))
   if self.path != '/api/action': return self.reply(404,{'error':'Not found'})
   self.reply(200,action(data.get('module'),data.get('action')))
  except (ValueError,OSError) as exc: self.reply(400,{'error':str(exc)})

if __name__ == '__main__':
 server=ThreadingHTTPServer(('127.0.0.1',int(CONFIG.get('ui_port',8800))),Handler)
 print(f'APTS Control Center: http://127.0.0.1:{server.server_port}',flush=True)
 if '--no-browser' not in sys.argv: webbrowser.open(f'http://127.0.0.1:{server.server_port}')
 try: server.serve_forever()
 except KeyboardInterrupt: pass
 finally:
  server.server_close()
  for key,p in list(PROCESSES.items()):
   if p.poll() is None:
    try: action(key,'stop')
    except Exception: pass
