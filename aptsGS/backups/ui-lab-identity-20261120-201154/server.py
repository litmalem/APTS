"""Loopback-only BFF. Credentials remain in short-lived server-side sessions."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, parse_qs, urlencode, quote
import argparse
import os
import ipaddress
import json
import re
import secrets
import threading
import time

STATIC = Path(__file__).resolve().parent / 'static'
PREFIX = '/api/governance/'
GET_PATH = re.compile(r'^/api/governance/(?:console/(?:me|overview|records/(?:approvals|scopes|decisions|policies|audit|emergency-history)|approval/[A-Za-z0-9_-]+|policy/[A-Za-z0-9_-]+|scopes/[A-Za-z0-9_-]+/delegation-readiness)|diagnostics|runtime/status|architecture|human-layer|human-interaction|interfaces|outbox/status|emergency-stop|scope-contracts/[A-Za-z0-9_-]+|decisions/[A-Za-z0-9_-]+|correlation/missions/[A-Za-z0-9_.:-]+)$')
POST_PATH = re.compile(r'^/api/governance/(?:console/(?:scopes|scopes/[A-Za-z0-9_-]+/revoke|policies/[A-Za-z0-9_-]+)|approvals/[A-Za-z0-9_-]+/decision|decisions/[A-Za-z0-9_-]+/revoke|emergency-stop/(?:activate|release)|events/retry)$')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

class UpstreamError(Exception):
    def __init__(self, status, data): self.status, self.data = status, data

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, port=8802, api_port=8770, mission_port=8780, *, quick_login_token=""):
        self.api_url = f'http://127.0.0.1:{api_port}'
        self.mission_url = f'http://127.0.0.1:{mission_port}'
        self.quick_login_token = quick_login_token
        self.sessions = {}; self.login_attempts = []; self.lock = threading.Lock()
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        super().__init__(('127.0.0.1', port), Handler)

    def upstream(self, path, token, body=None):
        headers = {'Authorization': 'Bearer '+token, 'Accept': 'application/json'}
        if body is not None: headers['Content-Type'] = 'application/json'
        req = Request(self.api_url + path, headers=headers, data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(req, timeout=15) as response:
                data = response.read(4_000_001)
                if len(data) > 4_000_000: raise UpstreamError(502, {'detail': 'Response too large; narrow your query'})
                return json.loads(data)
        except HTTPError as exc:
            try: data = json.loads(exc.read(65536))
            except ValueError: data = {'detail': 'Governance request failed'}
            if exc.code >= 500: data = {'detail': 'GSS tidak siap. Periksa layanan, database, dan konfigurasi principal.'}
            raise UpstreamError(exc.code, data) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise UpstreamError(503, {'detail': 'GSS tidak terjangkau; hasil perubahan belum diketahui. Periksa keadaan sebelum mengulangi.' if body is not None else 'GSS tidak terjangkau; status tidak diketahui.'}) from None

    def mission_upstream(self, path, body=None):
        """Call the loopback Mission API using only server-constructed paths."""
        headers = {'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        req = Request(
            self.mission_url + path,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with self.opener.open(req, timeout=15) as response:
                data = response.read(4_000_001)
                if len(data) > 4_000_000:
                    raise UpstreamError(502, {'detail': 'Mission response too large; narrow your query'})
                return json.loads(data)
        except HTTPError as exc:
            try:
                data = json.loads(exc.read(65536))
            except ValueError:
                data = {'detail': 'Mission request failed'}
            if exc.code >= 500:
                data = {'detail': 'Mission Orchestrator tidak siap. Periksa layanan Mission.'}
            raise UpstreamError(exc.code, data) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise UpstreamError(503, {'detail': 'Mission Orchestrator tidak terjangkau; status tidak diketahui.'}) from None

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)
    def log_message(self, *args): pass  # No credentials or session identifiers in access logs.
    def reply(self, code, data, content='application/json; charset=utf-8', cookie=None):
        raw = json.dumps(data, ensure_ascii=False).encode() if content.startswith('application/json') else data
        self.send_response(code)
        for k,v in {'Content-Type':content, 'Content-Length':str(len(raw)), 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'DENY', 'Referrer-Policy':'no-referrer', 'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}.items(): self.send_header(k,v)
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers(); self.wfile.write(raw)
    def valid_request(self, write=False):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != origin[7:]: return False
        if self.headers.get('Origin') not in (None, origin): return False
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'): return False
        return not write or self.headers.get('Origin') == origin
    def session(self):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except Exception: return None, None
        sid = cookie.get('gss_session'); sid = sid.value if sid else ''
        with self.server.lock:
            now = time.monotonic()
            self.server.sessions = {k:v for k,v in self.server.sessions.items() if v['expires'] > now}
            return sid, self.server.sessions.get(sid)
    def do_GET(self):
        if not self.valid_request(): return self.reply(403, {'detail':'Invalid host/origin'})
        path = urlsplit(self.path).path
        if path == '/health': return self.reply(200, {'status':'ok', 'service':'aptsGSS Web', 'governance_status':'not_checked'})
        if path == '/api/login-options':
            return self.reply(200, {'quick_login': bool(self.server.quick_login_token), 'mode': 'LOCAL_TEST' if self.server.quick_login_token else 'STANDARD'})
        if path in ('/', '/app.js', '/style.css'):
            name, mime = {'/':('index.html','text/html'), '/app.js':('app.js','text/javascript'), '/style.css':('style.css','text/css')}[path]
            return self.reply(200, (STATIC/name).read_bytes(), mime+'; charset=utf-8')
        sid, session = self.session()
        if not session: return self.reply(401, {'detail':'Sesi berakhir. Silakan masuk.'})
        try:
            me = self.server.upstream(PREFIX+'console/me', session['token'])
            if path == '/api/session': return self.reply(200, {**me, 'csrf':session['csrf']})
            if path == '/api/human/mission-attention':
                query = parse_qs(urlsplit(self.path).query)
                try: limit = max(1, min(int((query.get('limit') or ['50'])[0]), 200))
                except ValueError: return self.reply(400, {'detail':'limit must be an integer'})
                return self.reply(200, self.server.mission_upstream('/api/operator/attention/advanced?'+urlencode({'limit':limit})))
            if path == '/api/human/missions':
                query = parse_qs(urlsplit(self.path).query)
                allowed = {'limit','offset','state','q','source_system','terminal'}
                if set(query) - allowed: return self.reply(400, {'detail':'Unsupported mission query'})
                clean = {}
                for key, values in query.items():
                    if len(values) != 1: return self.reply(400, {'detail':'Duplicate mission query field'})
                    clean[key] = values[0]
                try:
                    if 'limit' in clean: clean['limit'] = max(1, min(int(clean['limit']), 200))
                    if 'offset' in clean: clean['offset'] = max(0, int(clean['offset']))
                except ValueError: return self.reply(400, {'detail':'limit/offset must be integers'})
                target = '/api/missions' + (('?'+urlencode(clean)) if clean else '')
                return self.reply(200, self.server.mission_upstream(target))
            pip_match = re.fullmatch(r'/api/human/missions/([A-Za-z0-9_.:-]+)/pip-binding', path)
            if pip_match:
                return self.reply(200, self.server.mission_upstream('/api/missions/'+quote(pip_match.group(1), safe='')+'/pip-binding'))
            mission_match = re.fullmatch(r'/api/human/missions/([A-Za-z0-9_.:-]+)', path)
            if mission_match:
                mid = quote(mission_match.group(1), safe='')
                mission = self.server.mission_upstream('/api/missions/'+mid)
                state = self.server.mission_upstream('/api/missions/'+mid+'/state')
                envelope = self.server.mission_upstream('/api/missions/'+mid+'/envelope')
                try: visibility = self.server.mission_upstream('/api/missions/'+mid+'/governance-visibility')
                except UpstreamError as exc:
                    if exc.status == 404: visibility = None
                    else: raise
                return self.reply(200, {'status':'completed','mission':mission,'state':state,'envelope':envelope,'governance_visibility':visibility})
            if not GET_PATH.fullmatch(path): return self.reply(404, {'detail':'Endpoint not allowed'})
            return self.reply(200, self.server.upstream(self.path, session['token']))
        except UpstreamError as exc: return self.reply(exc.status, exc.data)
    def do_POST(self):
        if not self.valid_request(write=True): return self.reply(403, {'detail':'Invalid host/origin'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 131072: return self.reply(413, {'detail':'Invalid body size'})
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json': return self.reply(415, {'detail':'JSON required'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict): raise ValueError()
        except (ValueError, UnicodeError): return self.reply(400, {'detail':'Invalid JSON'})
        try:
            if self.path == '/api/login':
                with self.server.lock:
                    now = time.monotonic()
                    self.server.login_attempts = [t for t in self.server.login_attempts if now-t < 60]
                    if len(self.server.login_attempts) >= 10: return self.reply(429, {'detail':'Terlalu banyak percobaan. Tunggu satu menit.'})
                    self.server.login_attempts.append(now)
                if body.get('quick_login') is True:
                    if not self.server.quick_login_token or not ipaddress.ip_address(self.client_address[0]).is_loopback:
                        return self.reply(403, {'detail':'Login cepat lokal tidak aktif.'})
                    token = self.server.quick_login_token
                else:
                    token = body.get('token','')
                if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', token): return self.reply(401, {'detail':'Invalid credential'})
                me = self.server.upstream(PREFIX+'console/me', token)
                old, _ = self.session(); sid = secrets.token_urlsafe(32); csrf = secrets.token_urlsafe(32)
                with self.server.lock:
                    self.server.sessions.pop(old,None)
                    if len(self.server.sessions) >= 100: return self.reply(503, {'detail':'Session capacity reached'})
                    self.server.sessions[sid] = {'token':token, 'csrf':csrf, 'expires':time.monotonic()+1800}
                return self.reply(200, {**me, 'csrf':csrf}, cookie='gss_session='+sid+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=1800')
            sid, session = self.session()
            if not session: return self.reply(401, {'detail':'Sesi berakhir. Silakan masuk.'})
            if not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),session['csrf']): return self.reply(403, {'detail':'Invalid CSRF token'})
            if self.path == '/api/logout':
                with self.server.lock: self.server.sessions.pop(sid,None)
                return self.reply(200, {'status':'signed_out'}, cookie='gss_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            me = self.server.upstream(PREFIX+'console/me', session['token'])
            pip_match = re.fullmatch(r'/api/human/missions/([A-Za-z0-9_.:-]+)/(pip-build|pip-binding)', self.path)
            if pip_match:
                if 'mission_author' not in set(me.get('capabilities') or []):
                    return self.reply(403, {'detail':'CONSOLE_PERMISSION_REQUIRED: mission_author'})
                payload = dict(body)
                if pip_match.group(2) == 'pip-binding':
                    payload['actor'] = me['principal_id']
                return self.reply(200, self.server.mission_upstream('/api/missions/'+quote(pip_match.group(1), safe='')+'/'+pip_match.group(2), payload))
            if self.path == '/api/human/missions':
                if 'mission_author' not in set(me.get('capabilities') or []):
                    return self.reply(403, {'detail':'CONSOLE_PERMISSION_REQUIRED: mission_author'})
                allowed = {'client_request_id','mission_kind','objective','objective_type','success_criteria','budgets','required_subsystems','metadata'}
                if set(body) - allowed:
                    return self.reply(422, {'detail':'Unsupported Human Layer mission field'})
                objective = body.get('objective')
                if not isinstance(objective, str) or not objective.strip() or len(objective.strip()) > 4000:
                    return self.reply(422, {'detail':'objective must be a non-empty string up to 4000 characters'})
                mission_kind = str(body.get('mission_kind') or '').strip().upper()
                objective_type = str(body.get('objective_type') or '').strip().upper()
                mission_contracts = {'CTI_DATA_COLLECTION':['CTI'], 'AUTHORIZED_PENTEST':['CTI','PENTEST']}
                if mission_kind not in mission_contracts or objective_type != mission_kind:
                    return self.reply(422, {'detail':'mission_kind and objective_type must select CTI_DATA_COLLECTION or AUTHORIZED_PENTEST'})
                subsystems = mission_contracts[mission_kind]
                submitted_subsystems = body.get('required_subsystems')
                if submitted_subsystems is not None and submitted_subsystems != subsystems:
                    return self.reply(422, {'detail':'required_subsystems conflicts with the selected mission type'})
                success = body.get('success_criteria') or []
                budgets = body.get('budgets') or {}
                metadata = body.get('metadata') or {}
                if not isinstance(success, list) or not isinstance(budgets, dict) or not isinstance(metadata, dict):
                    return self.reply(422, {'detail':'success_criteria must be an array; budgets and metadata must be objects'})
                client_request_id = str(body.get('client_request_id') or ('hui-'+secrets.token_hex(12)))
                if not re.fullmatch(r'[A-Za-z0-9_.:-]{3,128}', client_request_id):
                    return self.reply(422, {'detail':'client_request_id has invalid format'})
                payload = {
                    'idempotency_key': 'human-ui-'+client_request_id,
                    'source_system': 'HUMAN_LAYER',
                    'created_by': me['principal_id'],
                    'client_request_id': client_request_id,
                    'mission_kind': mission_kind,
                    'objective': {'type': objective_type, 'goal': objective.strip()},
                    'success_criteria': success,
                    'budgets': budgets,
                    'required_subsystems': [str(x).upper() for x in subsystems],
                    'metadata': {**metadata, 'human_interaction': {'principal_id':me['principal_id'],'roles':me.get('roles') or [],'interface':'aptsGSS Web'}},
                }
                return self.reply(200, self.server.mission_upstream('/api/missions', payload))
            if not POST_PATH.fullmatch(self.path): return self.reply(404, {'detail':'Endpoint not allowed'})
            return self.reply(200, self.server.upstream(self.path, session['token'], body))
        except UpstreamError as exc: return self.reply(exc.status, exc.data)

def local_quick_login_token():
    """Opt-in local test login; the browser never receives this backend credential."""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    if os.getenv('GSS_DEV_QUICK_LOGIN', '').strip().lower() not in ('1','true','yes','on'):
        return ''
    path = os.getenv('GSS_DEV_QUICK_LOGIN_TOKEN_FILE', '')
    if not path:
        raise RuntimeError('GSS_DEV_QUICK_LOGIN_TOKEN_FILE belum dikonfigurasi')
    token = Path(path).read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', token):
        raise RuntimeError('Kredensial internal login cepat tidak valid')
    return token


def run():
    p = argparse.ArgumentParser(); p.add_argument('--port', type=int, default=8802); p.add_argument('--api-port', type=int, default=8770); p.add_argument('--mission-port', type=int, default=8780)
    args = p.parse_args(); server = Server(args.port, args.api_port, args.mission_port, quick_login_token=local_quick_login_token())
    print(f'aptsGSS Web: http://127.0.0.1:{server.server_port}', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
