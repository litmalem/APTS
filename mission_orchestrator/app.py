from __future__ import annotations

import json
import os
import hashlib
import re
import secrets
import sqlite3
import threading
import time
import ipaddress
import socket
import ssl
import tempfile
import _ssl
from contextlib import contextmanager
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('WTP_DB_PATH', str(ROOT / 'data' / 'profiler.sqlite3')))
WEB = ROOT / 'web'
HOST = os.getenv('WTP_HOST', '127.0.0.1')
PORT = int(os.getenv('WTP_PORT', '8791'))
CLIENT_TOKEN = os.getenv('WTP_CLIENT_TOKEN', '')
DISPATCH_URL = os.getenv('APTS_WTP_DISPATCH_URL', '').rstrip('/')
DISPATCH_TOKEN = os.getenv('APTS_WTP_DISPATCH_TOKEN', '')
MAX_BODY = 65536


def now():
    return datetime.now(timezone.utc).isoformat()


def _elapsed_ms(started, finished):
    try:
        a=datetime.fromisoformat(str(started).replace('Z','+00:00'))
        b=datetime.fromisoformat(str(finished).replace('Z','+00:00'))
        return max(0.0, round((b-a).total_seconds()*1000, 3))
    except (TypeError, ValueError):
        return None


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS jobs (
      job_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      mission_id TEXT, task_id TEXT, target TEXT NOT NULL, requested_by TEXT NOT NULL,
      mode TEXT NOT NULL, status TEXT NOT NULL, authorization_id TEXT,
      execution_id TEXT, result_json TEXT, error TEXT,
      recon_status TEXT NOT NULL DEFAULT 'NOT_SENT', recon_delivery_id TEXT,
      recon_delivered_at TEXT, enum_status TEXT NOT NULL DEFAULT 'NOT_SENT',
      enum_delivery_id TEXT, enum_delivered_at TEXT,
      execution_mode TEXT NOT NULL DEFAULT 'GOVERNED',
      scan_started_at TEXT, scan_finished_at TEXT, scan_duration_ms REAL
    )''')
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(jobs)')}
    if 'execution_mode' not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'GOVERNED'")
    for name, declaration in (('scan_started_at','TEXT'),('scan_finished_at','TEXT'),('scan_duration_ms','REAL')):
        if name not in columns: conn.execute(f'ALTER TABLE jobs ADD COLUMN {name} {declaration}')
    conn.execute('''CREATE TABLE IF NOT EXISTS remote_allowlist (
      entry TEXT PRIMARY KEY, created_at TEXT NOT NULL, created_by TEXT NOT NULL
    )''')
    return conn


@contextmanager
def connection():
    conn = db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def safe_target(value: str) -> str:
    value = (value or '').strip()
    p = urlparse(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Target harus berupa URL HTTP/HTTPS lengkap tanpa kredensial.')
    if len(value) > 2048:
        raise ValueError('URL target terlalu panjang.')
    # A fragment (for example, a SPA route such as /#/) is browser-side only.
    clean = urlunparse(p._replace(fragment=''))
    return clean.rstrip('/') or p.scheme + '://' + p.netloc



def serialize(row):
    obj = dict(row)
    if obj.get('result_json'):
        try: obj['result'] = json.loads(obj.pop('result_json'))
        except json.JSONDecodeError: obj['result'] = None
    else:
        obj.pop('result_json', None)
        obj['result'] = None
    return obj


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('redirect rejected by profiler policy')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('redirect rejected by profiler policy')


def dispatch_job(job: dict) -> dict:
    """Submit a proposal to Mission's governed intake; never perform target I/O."""
    if not DISPATCH_URL:
        raise RuntimeError('Mission WPT intake belum dikonfigurasi. Tidak ada koneksi ke target yang dilakukan.')
    parsed = urlparse(DISPATCH_URL)
    if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise RuntimeError('Mission intake URL harus HTTPS atau loopback HTTP.')
    if not job.get('mission_id') or not job.get('task_id') or not job.get('idempotency_key'):
        raise RuntimeError('Mission ID, Task ID, dan idempotency key wajib tersedia.')
    payload = {'schema_version':'apts-wpt-governed-intake-v1',
        'intake_id':job['job_id'].replace('wtp-', 'wptreq-', 1),
        'idempotency_key':job['idempotency_key'], 'mission_id':job['mission_id'],
        'task_id':job['task_id'], 'target':{'target_type':'URL','target_value':job['target']},
        'profile':job['mode']}
    data = json.dumps(payload, separators=(',', ':')).encode()
    headers = {'Content-Type':'application/json','Accept':'application/json','User-Agent':'APTS-WebTechnologyProfiler/1.0'}
    if DISPATCH_TOKEN: headers['Authorization'] = 'Bearer ' + DISPATCH_TOKEN
    req = Request(DISPATCH_URL + '/api/wpt/intakes', data=data, headers=headers, method='POST')
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=10) as response:
            if response.status not in (200, 201, 202): raise RuntimeError(f'Mission WPT intake returned HTTP {response.status}')
            result = json.loads(response.read(65537).decode())
            if len(json.dumps(result)) > MAX_BODY: raise RuntimeError('Mission response exceeded limit')
            return result
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f'Mission WPT intake failed: {exc}') from exc


class Handler(BaseHTTPRequestHandler):
    server_version = 'WebTechnologyProfiler/1.0'

    def log_message(self, fmt, *args):
        # Keep access logs local; never log headers, tokens, or response bodies.
        print('%s - %s' % (self.address_string(), fmt % args))

    def _send(self, status, payload, content_type='application/json; charset=utf-8'):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw))); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get('Content-Length','0'))
        if n <= 0 or n > MAX_BODY: raise ValueError('Invalid request body size.')
        data = json.loads(self.rfile.read(n))
        if not isinstance(data, dict): raise ValueError('JSON body must be an object.')
        return data

    def _auth(self):
        if not CLIENT_TOKEN: return False
        supplied = self.headers.get('X-APTS-Client-Token','')
        return secrets.compare_digest(supplied, CLIENT_TOKEN)

    def _operator_auth(self):
        # Local-only operator UI; remote access requires the shared secret.
        if CLIENT_TOKEN and self.client_address[0] not in ('127.0.0.1','::1'):
            return self._auth()
        return True

    def _admin_auth(self):
        # Allowlist administration is local-only unless a shared secret is configured.
        if self.client_address[0] in ('127.0.0.1','::1'):
            return True
        return bool(CLIENT_TOKEN) and self._auth()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            return self._send(200, (WEB/'index.html').read_bytes(), 'text/html; charset=utf-8')
        if path in ('/app.js','/style.css'):
            return self._send(200, (WEB/path[1:]).read_bytes(), 'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
        if path == '/api/health':
            return self._send(200, {'status':'ok','service':'Web Technology Profiler','apts_dispatch_configured':bool(DISPATCH_URL),'scan_execution':'STAGE6_ONLY','direct_target_io':False,'stage6_execution_available':False})
        if path == '/api/remote-allowlist':
            return self._send(410, {'error':'Standalone dinonaktifkan; target scope dikelola Mission/Governance.'})
        if path == '/api/jobs':
            with connection() as c: rows=c.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 200').fetchall()
            return self._send(200, {'jobs':[serialize(x) for x in rows]})
        if path.startswith('/api/jobs/'):
            ident=path.split('/')[-1]
            with connection() as c: row=c.execute('SELECT * FROM jobs WHERE job_id=?',(ident,)).fetchone()
            return self._send(200, {'job':serialize(row)}) if row else self._send(404, {'error':'Job tidak ditemukan.'})
        return self._send(404, {'error':'Not found'})

    def do_POST(self):
        path=urlparse(self.path).path
        if path == '/api/remote-allowlist':
            return self._send(410, {'error':'Standalone dinonaktifkan; target scope dikelola Mission/Governance.'})
        if path == '/api/jobs':
            if not self._operator_auth(): return self._send(401, {'error':'Unauthorized client'})
            try:
                data=self._body(); target=safe_target(data.get('target',''))
                mode=data.get('mode','fingerprinting')
                if mode not in ('fingerprinting','enumeration'): raise ValueError('mode harus fingerprinting atau enumeration.')
                execution_mode=str(data.get('execution_mode') or 'GOVERNED').upper()
                if execution_mode != 'GOVERNED':
                    raise ValueError('WPT hanya mendukung eksekusi melalui Stage 6; mode mandiri dinonaktifkan.')
                mission_id=str(data.get('mission_id') or '').strip()
                task_id=str(data.get('task_id') or '').strip()[:200]
                requested_by=str(data.get('requested_by') or 'operator').strip()[:150]
                if not mission_id.startswith('mission-gmo-'): raise ValueError('Mission ID aktif wajib diisi.')
                if not task_id.startswith('ptask-'): raise ValueError('Task ID aktif dengan format ptask- wajib diisi.')
                if not requested_by: raise ValueError('requested_by wajib diisi.')
                job_id='wtp-'+uuid.uuid4().hex
                idempotency_key='idem-'+uuid.uuid4().hex
                item={'job_id':job_id,'created_at':now(),'updated_at':now(),'mission_id':mission_id[:200],
                      'task_id':task_id,'target':target,'requested_by':requested_by,
                      'mode':mode,'status':'PROPOSED','execution_mode':'GOVERNED',
                      'authorization_id':None,'idempotency_key':idempotency_key}
                with connection() as c:
                    columns={row['name'] for row in c.execute('PRAGMA table_info(jobs)')}
                    if 'idempotency_key' not in columns: c.execute('ALTER TABLE jobs ADD COLUMN idempotency_key TEXT')
                    c.execute('INSERT INTO jobs(job_id,created_at,updated_at,mission_id,task_id,target,requested_by,mode,status,authorization_id,execution_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                              (job_id,item['created_at'],item['updated_at'],item['mission_id'],task_id,target,requested_by,mode,'PROPOSED',None,'GOVERNED'))
                    c.execute('UPDATE jobs SET idempotency_key=? WHERE job_id=?',(idempotency_key,job_id))
                return self._send(201, {'job':item,'note':'Proposal tersimpan. WPT tidak melakukan target I/O; Mission dan Stage 6 harus menerima serta mengotorisasi eksekusi.'})
            except (ValueError, json.JSONDecodeError) as exc: return self._send(400, {'error':str(exc)})
        if path.endswith('/dispatch') and path.startswith('/api/jobs/'):
            if not self._operator_auth(): return self._send(401, {'error':'Unauthorized client'})
            ident=path.split('/')[-2]
            with connection() as c: row=c.execute('SELECT * FROM jobs WHERE job_id=?',(ident,)).fetchone()
            if not row: return self._send(404, {'error':'Job tidak ditemukan.'})
            job=serialize(row)
            if job['status'] in ('DISPATCHED','RUNNING','COMPLETED'):
                return self._send(409, {'error':'Job sudah dikirim atau sudah memiliki hasil; tidak akan dikirim ulang otomatis.'})
            try:
                response=dispatch_job(job)
                record=response.get('record') or {}
                if record.get('status') != 'ACCEPTED_PENDING_STAGE6': raise RuntimeError('Mission did not accept the governed WPT intake.')
                with connection() as c: c.execute("UPDATE jobs SET status='AWAITING_STAGE6',updated_at=? WHERE job_id=?",(now(),ident))
                return self._send(202, {'job_id':ident,'status':'AWAITING_STAGE6','target_io_performed':False,'mission_intake':response})
            except RuntimeError as exc:
                with connection() as c: c.execute("UPDATE jobs SET status='BLOCKED_CONFIGURATION',error=?,updated_at=? WHERE job_id=?",(str(exc),now(),ident))
                return self._send(503, {'job_id':ident,'status':'BLOCKED_CONFIGURATION','error':str(exc),'target_io_performed':False})
        if path.startswith('/api/jobs/') and '/deliveries/' in path:
            if not CLIENT_TOKEN or not self._auth(): return self._send(401, {'error':'Authenticated APTS client required'})
            bits=path.split('/'); ident=bits[3]; agent=bits[5]
            if agent not in ('reconnaissance','enumeration'): return self._send(404, {'error':'Unknown agent'})
            try:
                data=self._body(); delivery=str(data.get('delivery_id') or '').strip()
                if not delivery: raise ValueError('delivery_id wajib diisi.')
                field='recon' if agent=='reconnaissance' else 'enum'
                with connection() as c:
                    row=c.execute('SELECT status FROM jobs WHERE job_id=?',(ident,)).fetchone()
                    if not row: return self._send(404, {'error':'Job tidak ditemukan.'})
                    c.execute(f'UPDATE jobs SET {field}_status=?,{field}_delivery_id=?,{field}_delivered_at=?,updated_at=? WHERE job_id=?',
                              ('DELIVERED',delivery,now(),now(),ident))
                return self._send(200, {'job_id':ident,'agent':agent,'status':'DELIVERED','delivery_id':delivery})
            except ValueError as exc: return self._send(400, {'error':str(exc)})
        if path.startswith('/api/jobs/') and path.endswith('/result'):
            if not CLIENT_TOKEN or not self._auth(): return self._send(401, {'error':'Authenticated APTS client required'})
            ident=path.split('/')[-2]
            try:
                data=self._body(); status=str(data.get('status','COMPLETED')).upper()
                if status not in ('COMPLETED','FAILED','CANCELLED'): raise ValueError('Unsupported terminal status.')
                result=data.get('result')
                if not isinstance(result,dict): raise ValueError('result harus object.')
                with connection() as c: row=c.execute('SELECT * FROM jobs WHERE job_id=?',(ident,)).fetchone()
                if not row: return self._send(404, {'error':'Job tidak ditemukan.'})
                execution_id=str(data.get('execution_id') or '').strip()
                evidence=result.get('evidence') or {}
                digest=str(evidence.get('manifest_sha256') or '')
                if not execution_id or evidence.get('capture_status')!='SEALED' or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest.lower()):
                    raise ValueError('Stage 6 result harus memiliki execution_id dan evidence manifest SEALED yang valid.')
                if result.get('mission_id') not in (None, row['mission_id']) or result.get('target') not in (None, row['target']):
                    raise ValueError('Result mission/target tidak cocok dengan job.')
                timing=result.get('scan_timing') if isinstance(result.get('scan_timing'),dict) else {}
                observations=result.get('observations') if isinstance(result.get('observations'),list) else []
                request_starts=[o.get('request_started_at') for o in observations if isinstance(o,dict) and o.get('request_started_at')]
                response_ends=[o.get('response_received_at') for o in observations if isinstance(o,dict) and o.get('response_received_at')]
                started=timing.get('scan_started_at') or (min(request_starts) if request_starts else row['scan_started_at'] or now())
                finished=timing.get('scan_finished_at') or (max(response_ends) if response_ends else now())
                duration=timing.get('duration_ms')
                if duration is None: duration=_elapsed_ms(started,finished)
                with connection() as c:
                    # Never accept raw response bodies/cookies as evidence.
                    safe={k:v for k,v in result.items() if k not in ('body','response_body','cookies','set_cookie','response_b64')}
                    c.execute('UPDATE jobs SET status=?,result_json=?,execution_id=?,scan_started_at=?,scan_finished_at=?,scan_duration_ms=?,updated_at=?,error=NULL WHERE job_id=?',
                              (status,json.dumps(safe,ensure_ascii=False),execution_id,started,finished,duration,now(),ident))
                return self._send(200, {'job_id':ident,'status':status})
            except (ValueError, json.JSONDecodeError) as exc: return self._send(400, {'error':str(exc)})
        return self._send(404, {'error':'Not found'})

    def do_DELETE(self):
        return self._send(410, {'error':'Standalone dinonaktifkan; target scope dikelola Mission/Governance.'})


def serve():
    if HOST not in ('127.0.0.1','localhost','::1') and os.getenv('WTP_ALLOW_REMOTE','').lower() != 'true':
        raise SystemExit('Refusing non-loopback bind. Set WTP_ALLOW_REMOTE=true only behind authenticated TLS/reverse proxy.')
    db().close()
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    print(f'Web Technology Profiler listening at http://{HOST}:{PORT}')
    print('APTS Stage 6 dispatch configured:', bool(DISPATCH_URL))
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': serve()
