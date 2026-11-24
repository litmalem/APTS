"""Local APTS process control and read-only monitoring. Python standard library only."""
import concurrent.futures, json, os, secrets, socket, subprocess, sys, threading, time, webbrowser, getpass
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs, quote

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
PROCESSES = {}
RESET_LOCK = threading.RLock()
RESET_STATE = {'status':'idle','updated_at':None,'result':None,'error':None,'output':None}
RESET_PLANS = {}
LOGS = ROOT / 'logs'
LOGS.mkdir(exist_ok=True)
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
STATE_ROOT = Path(os.getenv('LOCALAPPDATA') or os.getenv('XDG_STATE_HOME') or (Path.home() / '.local' / 'state')) / 'APTS' / 'ControlCenter'
WPT_INBOX_SECRET_FILE = STATE_ROOT / 'wpt-inbox.token'
WPT_DISPATCH_SECRET_FILE = STATE_ROOT / 'wpt-dispatch.token'
SPECS = {
 'vulndesk': ('Vulndesk', 'run/run_vulndesk_api.py', ['/api/cti/diagnostics', '/api/cti/components', '/api/cti/architecture']),
 'vulndesk_web': ('Vulndesk Web', 'server.py', ['/api/config']),
 'gss_web': ('aptsGSS Web', 'run_web.py', ['/health']),
 'gss': ('aptsGS', 'run.py', ['/api/governance/diagnostics', '/api/governance/runtime/status', '/api/governance/outbox/status', '/api/governance/emergency-stop']),
 'mission': ('Mission', 'run/run_stage6_10_mission.py', ['/api/subsystem-registry', '/api/subsystems']),
 'mission_web': ('Mission Web', 'run/run_stage6_10_mission.py', ['/api/dashboard/summary', '/api/missions', '/api/operator/attention']),
 'stage6_runtime': ('Stage 6.5 Execution Runtime', 'run/execution_runtime.py', ['/health']),
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

def _windows_principal():
 domain=os.getenv('USERDOMAIN','').strip()
 username=os.getenv('USERNAME') or getpass.getuser()
 return f'{domain}\\{username}' if domain else username

def _secure_state_root():
 """Create a private per-user directory for the shared Mission/WPT token."""
 STATE_ROOT.mkdir(parents=True,exist_ok=True)
 if os.name == 'nt':
  user=_windows_principal()
  result=subprocess.run(['icacls',str(STATE_ROOT),'/inheritance:r','/grant:r',f'{user}:(OI)(CI)F'],capture_output=True,text=True,shell=False)
  if result.returncode:
   detail=(result.stderr or result.stdout or '').strip()
   raise RuntimeError('Tidak dapat mengunci ACL penyimpanan token Control Center untuk akun Windows saat ini.'+(f' {detail}' if detail else ''))
 else:
  STATE_ROOT.chmod(0o700)

def _load_or_create_wpt_dispatch_token(configured):
 """Persist the separate WPT -> Mission bearer token with a private ACL."""
 if len(set(configured))>1:
  raise RuntimeError('Token dispatch WPT dan Mission berbeda. Samakan konfigurasi sebelum menjalankan layanan.')
 if WPT_DISPATCH_SECRET_FILE.exists():
  token=WPT_DISPATCH_SECRET_FILE.read_text(encoding='ascii').strip()
  if len(token)<32: raise RuntimeError('Secret dispatch WPT tidak valid; rotasi harus dilakukan secara eksplisit.')
  if configured and configured[0]!=token:
   raise RuntimeError('Token dispatch eksplisit berbeda dari secret Control Center. Rekonsiliasi dihentikan agar tidak memutus layanan.')
  return token
 token=configured[0] if configured else secrets.token_urlsafe(48)
 if len(token)<32: raise RuntimeError('Token dispatch harus minimal 32 karakter.')
 temp=WPT_DISPATCH_SECRET_FILE.with_suffix('.tmp')
 temp.write_text(token,encoding='ascii')
 if os.name=='nt':
  user=_windows_principal()
  result=subprocess.run(['icacls',str(temp),'/inheritance:r','/grant:r',f'{user}:F'],capture_output=True,text=True,shell=False)
  if result.returncode:
   temp.unlink(missing_ok=True)
   detail=(result.stderr or result.stdout or '').strip()
   raise RuntimeError('Tidak dapat mengunci ACL file token dispatch WPT.'+(f' {detail}' if detail else ''))
 else: temp.chmod(0o600)
 temp.replace(WPT_DISPATCH_SECRET_FILE)
 return token

def ensure_wpt_inbox_bridge():
 """Reconcile exact local Mission -> WPT inbox settings without logging secrets.

 A single random secret is persisted in the current user's private state folder,
 injected into both child processes, and reused on every Control Center start.
 Explicit conflicting credentials fail closed; they are never overwritten.
 """
 modules=CONFIG.setdefault('modules',{})
 mission=modules.setdefault('mission',{})
 wpt=modules.setdefault('wpt',{'root':'D:/APTS/WebTechnologyProfiler','port':8791,'python':'','env':{}})
 mission_env=mission.setdefault('env',{})
 wpt_env=wpt.setdefault('env',{})
 configured=[str(x).strip() for x in (
  mission_env.get('APTS_WPT_INBOX_TOKEN'),wpt_env.get('WTP_CLIENT_TOKEN'),
  os.getenv('APTS_WPT_INBOX_TOKEN'),os.getenv('WTP_CLIENT_TOKEN')) if str(x or '').strip()]
 if len(set(configured))>1:
  raise RuntimeError('Token inbox Mission dan WPT berbeda. Samakan konfigurasi sebelum menjalankan layanan.')
 _secure_state_root()
 if WPT_INBOX_SECRET_FILE.exists():
  token=WPT_INBOX_SECRET_FILE.read_text(encoding='ascii').strip()
  if len(token)<32: raise RuntimeError('Secret inbox Control Center tidak valid; rotasi harus dilakukan secara eksplisit.')
  if configured and configured[0]!=token:
   raise RuntimeError('Token inbox eksplisit berbeda dari secret Control Center. Rekonsiliasi dihentikan agar tidak memutus layanan.')
 else:
  token=configured[0] if configured else secrets.token_urlsafe(48)
  if len(token)<32: raise RuntimeError('Token inbox harus minimal 32 karakter.')
  temp=WPT_INBOX_SECRET_FILE.with_suffix('.tmp')
  temp.write_text(token,encoding='ascii')
  if os.name=='nt':
   user=_windows_principal()
   result=subprocess.run(['icacls',str(temp),'/inheritance:r','/grant:r',f'{user}:F'],capture_output=True,text=True,shell=False)
   if result.returncode:
    temp.unlink(missing_ok=True)
    detail=(result.stderr or result.stdout or '').strip()
    raise RuntimeError('Tidak dapat mengunci ACL file token inbox.'+(f' {detail}' if detail else ''))
  else: temp.chmod(0o600)
  temp.replace(WPT_INBOX_SECRET_FILE)
 mission_env['APTS_AUTONOMOUS_WPT_INTAKE']='1'
 stage6=modules.setdefault('stage6_runtime',{'root':mission.get('root','D:/APTS/mission_orchestrator'),'port':8792,'python':'','env':{}})
 mission_env['APTS_STAGE6_RUNTIME_URL']=f"http://127.0.0.1:{int(stage6.get('port',8792))}"
 # Control Center owns both local processes, so its configured WPT port is
 # authoritative; do not preserve a stale inbox URL from an old deployment.
 mission_env['APTS_WPT_INBOX_URL']=f"http://127.0.0.1:{int(wpt.get('port',8791))}"
 mission_env['APTS_WPT_INBOX_TOKEN']=token
 wpt_env['WTP_CLIENT_TOKEN']=token
 wpt_env.setdefault('WTP_HOST','127.0.0.1')
 wpt_env['WTP_PORT']=str(wpt.get('port',8791))
 # Configure the opposite direction independently: WPT -> Mission governed
 # intake. Never reuse the inbox credential for this bearer-authenticated API.
 dispatch_configured=[str(x).strip() for x in (
  mission_env.get('MISSION_WPT_INTAKE_TOKEN'),wpt_env.get('APTS_WTP_DISPATCH_TOKEN'),
  os.getenv('MISSION_WPT_INTAKE_TOKEN'),os.getenv('APTS_WTP_DISPATCH_TOKEN')) if str(x or '').strip()]
 dispatch_token=_load_or_create_wpt_dispatch_token(dispatch_configured)
 mission_env['MISSION_WPT_INTAKE_TOKEN']=dispatch_token
 wpt_env['APTS_WTP_DISPATCH_TOKEN']=dispatch_token
 wpt_env['APTS_WTP_DISPATCH_URL']=f"http://127.0.0.1:{int(mission.get('port',8780))}"
 return {'configured':True,'url':mission_env['APTS_WPT_INBOX_URL'],
         'stage6_runtime_url':mission_env['APTS_STAGE6_RUNTIME_URL'],'token_shared':True,
         'dispatch_configured':True,'dispatch_url':wpt_env['APTS_WTP_DISPATCH_URL'],
         'dispatch_token_shared':True}

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
 if key in ('mission','mission_web') and verb == 'start':
  # Mission's autonomous WPT worker submits admitted executions to this local
  # Stage 6.5 runtime. Start/check it first so Mission never boots with a dead
  # configured runtime endpoint.
  action('stage6_runtime','start')
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
  if launch_key in ('mission','wpt'):
   ensure_wpt_inbox_bridge()
   cfg=module_config(key)
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
 start_order=('vulndesk','vulndesk_web','gss','gss_web','stage6_runtime','mission','mission_web','pentest','pentest_web','wpt')
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
  except (ValueError,OSError,RuntimeError) as exc:
   results.append({'module':key,'ok':False,'message':str(exc)})
 return {'message':('Permintaan ON' if verb=='start' else 'Permintaan OFF')+' semua layanan selesai diproses.','results':results}

def _reset_python(key):
 cfg=module_config(key); root=Path(cfg['root']).resolve()
 configured=str(cfg.get('python') or '').strip()
 candidates=[Path(configured)] if configured else []
 candidates += [root/'.venv'/'Scripts'/'python.exe',root/'.venv'/'bin'/'python']
 return str(next((p for p in candidates if p.is_file()),Path(sys.executable)))

def _reset_environment():
 env=os.environ.copy()
 for key in ('gss','mission','wpt','vulndesk'):
  env.update(module_config(key).get('env',{}))
 return env

def _reset_command(preview=False, backup_root=None, selection=None):
 args=[_reset_python('gss'),str(ROOT/'reset_apts.py'),
       '--mission-root',str(Path(module_config('mission')['root']).resolve()),
       '--gss-root',str(Path(module_config('gss')['root']).resolve()),
       '--wtp-root',str(Path(module_config('wpt')['root']).resolve()),
       '--vulndesk-root',str(Path(module_config('vulndesk')['root']).resolve()),
       '--vulndesk-python',_reset_python('vulndesk')]
 ports=sorted({int(module_config(k)['port']) for k in ('vulndesk','gss','mission','pentest','wpt','vulndesk_web','gss_web')})
 for port in ports: args += ['--service-port',str(port)]
 if preview: args.append('--preview-json')
 if backup_root: args += ['--backup-root',str(backup_root)]
 if selection is not None: args += ['--selection-json',json.dumps(selection,separators=(',',':'))]
 return args

def _reset_preview():
 with RESET_LOCK:
  if RESET_STATE['status']=='running': raise ValueError('Reset sedang berjalan.')
 cmd=_reset_command(preview=True)
 result=subprocess.run(cmd,cwd=str(module_config('gss')['root']),env=_reset_environment(),
                       capture_output=True,text=True,timeout=240,shell=False)
 if result.returncode:
  raise ValueError((result.stderr or result.stdout or 'Preview reset gagal.')[-1800:])
 try: plan=json.loads(result.stdout.strip().splitlines()[-1])
 except Exception as exc: raise ValueError('Preview reset memberikan laporan yang tidak valid.') from exc
 plan_id=secrets.token_urlsafe(24)
 expires=time.time()+600
 with RESET_LOCK:
  RESET_PLANS.clear(); RESET_PLANS[plan_id]={'plan':plan,'expires':expires}
 return {'plan_id':plan_id,'expires_in_seconds':600,'plan':plan}

def _run_reset(plan_id, selection):
 try:
  # Stop only services started by this panel. Any externally started service
  # remains untouched and is rejected by the reset script's port guard.
  stopped=action_all('stop')
  failed=[item for item in (stopped.get('results') or []) if not item.get('ok')]
  if failed: raise RuntimeError('Tidak semua proses yang dikelola panel berhenti: '+', '.join(x.get('module','?') for x in failed))
  backup=Path(module_config('mission')['root']).resolve()/'backups'/('reset-ui-'+time.strftime('%Y%m%d-%H%M%S'))
  result=subprocess.run(_reset_command(backup_root=backup,selection=selection),cwd=str(module_config('gss')['root']),
                        env=_reset_environment(),capture_output=True,text=True,timeout=900,shell=False)
  with RESET_LOCK:
   RESET_STATE.update(status='succeeded' if result.returncode==0 else 'failed',updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),
                      result={'backup':str(backup),'managed_services_stop':stopped},
                      error=None if result.returncode==0 else (result.stderr or result.stdout or 'Reset gagal.')[-2500:],
                      output=(result.stdout or '')[-5000:])
 except Exception as exc:
  with RESET_LOCK:
   RESET_STATE.update(status='failed',updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),error=str(exc)[-2500:],output=None)

def _validate_reset_selection(plan, requested):
 if not isinstance(requested,dict): raise ValueError('Pilih cakupan data yang akan dihapus.')
 allowed_keys={'sqlite_databases','gss','vulndesk','vulndesk_uploads'}
 if set(requested)-allowed_keys: raise ValueError('Pilihan reset memuat cakupan yang tidak dikenal.')
 modules=plan.get('modules') or {}
 sqlite_rows=modules.get('Mission/Pentest/Execution/WPT') or []
 known_databases={str(item.get('database')) for item in sqlite_rows}
 databases=requested.get('sqlite_databases',[])
 if not isinstance(databases,list) or any(not isinstance(x,str) for x in databases):
  raise ValueError('Pilihan database SQLite tidak valid.')
 if len(set(databases))!=len(databases) or not set(databases)<=known_databases:
  raise ValueError('Pilihan database tidak cocok dengan preview. Buat preview baru.')
 for key in ('gss','vulndesk','vulndesk_uploads'):
  if type(requested.get(key,False)) is not bool: raise ValueError('Pilihan '+key+' harus boolean.')
 vulndesk=modules.get('Vulndesk') or {}
 if requested.get('vulndesk_uploads') and not int(vulndesk.get('uploaded_files') or 0):
  raise ValueError('Tidak ada file unggahan Vulndesk pada preview.')
 selection={'sqlite_databases':databases,'gss':requested.get('gss',False),
            'vulndesk':requested.get('vulndesk',False),
            'vulndesk_uploads':requested.get('vulndesk_uploads',False)}
 if not databases and not selection['gss'] and not selection['vulndesk'] and not selection['vulndesk_uploads']:
  raise ValueError('Pilih setidaknya satu cakupan data untuk dihapus.')
 return selection

def start_reset(plan_id, confirmation, backup_confirmed, requested_selection):
 if confirmation!='HAPUS DATA APTS' or backup_confirmed is not True:
  raise ValueError('Ketik HAPUS DATA APTS dan konfirmasi backup sebelum melanjutkan.')
 with RESET_LOCK:
  plan=RESET_PLANS.get(plan_id)
  if not plan or plan['expires']<time.time(): raise ValueError('Preview sudah kedaluwarsa. Buat preview baru.')
  if RESET_STATE['status']=='running': raise ValueError('Reset sedang berjalan.')
  selection=_validate_reset_selection(plan['plan'],requested_selection)
  RESET_STATE.update(status='running',updated_at=time.strftime('%Y-%m-%d %H:%M:%S'),result=None,error=None,output='Menghentikan layanan yang dikelola panel dan memulai reset…')
  RESET_PLANS.clear()
 threading.Thread(target=_run_reset,args=(plan_id,selection),name='apts-data-reset',daemon=True).start()
 return {'status':'running','message':'Reset dimulai. Jangan mulai ulang layanan sampai status berhasil atau gagal.'}

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
   if parsed.path == '/api/reset/status':
    with RESET_LOCK: return self.reply(200,dict(RESET_STATE))
   if parsed.path == '/api/reset/preview':
    return self.reply(200,_reset_preview())
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
  except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired) as exc: self.reply(400,{'error':str(exc)})
 def do_POST(self):
  if not self.valid_host() or self.headers.get('X-Control-Token') != TOKEN or self.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.server.server_port}'):
   return self.reply(403,{'error':'Invalid origin or token'})
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0 < length <= 65536: raise ValueError('Invalid body size')
   data=json.loads(self.rfile.read(length))
   if self.path == '/api/action':
    if data.get('action')=='start':
     with RESET_LOCK:
      if RESET_STATE['status']=='running': raise ValueError('Reset sedang berjalan; layanan tidak dapat dinyalakan.')
    return self.reply(200,action(data.get('module'),data.get('action')))
   if self.path == '/api/reset/execute':
    result=start_reset(data.get('plan_id'),data.get('confirmation'),data.get('backup_confirmed'),data.get('selection'))
    return self.reply(202,result)
   return self.reply(404,{'error':'Not found'})
  except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired) as exc: self.reply(400,{'error':str(exc)})

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
