import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen, Request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('wpt_recovery', ROOT / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class Target(BaseHTTPRequestHandler):
    def do_GET(self):
        data = b'\x00\x00\x01\x00favicon' if self.path.endswith('favicon.ico') else b'<title>Local fixture</title><meta name="generator" content="WordPress 6.5">'
        self.send_response(200)
        self.send_header('Content-Type', 'image/x-icon' if self.path.endswith('favicon.ico') else 'text/html')
        self.send_header('Server', 'nginx')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class RecoveryTest(unittest.TestCase):
    def test_runtime_denial_updates_job_and_intake_without_progress_regression(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as folder, \
                patch.object(app,'DB_PATH',Path(folder)/'jobs.db'), \
                patch.object(app,'CLIENT_TOKEN','t'*40):
            intake='wptreq-status-regression'
            with app.connection() as c:
                c.execute('INSERT INTO governed_intakes(intake_id,idempotency_key,mission_id,task_id,target_type,target_url,profile,received_at) VALUES(?,?,?,?,?,?,?,?)',
                    (intake,'idem-status','mission-status','task-status','URL','http://localhost','fingerprinting',app.now()))
            payload=dict(schema_version='apts-wpt-stage6-job-v1',mission_id='mission-status',
                task_id='task-status',target='http://localhost',profile='fingerprinting',
                execution_id='exec-status',authorization_id=None,status='BLOCKED',reason_code='AUTHORITATIVE_DENY')
            def post():
                with urlopen(Request(self.base+'/api/stage6/intakes/'+intake+'/job',
                        data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',
                        'X-APTS-Client-Token':'t'*40})) as response:
                    return json.load(response)
            result=post()
            self.assertEqual(result['job']['status'],'BLOCKED')
            self.assertEqual(result['job']['error'],'AUTHORITATIVE_DENY')
            payload['status']='AWAITING_STAGE6'
            payload.pop('reason_code')
            self.assertEqual(post()['job']['status'],'BLOCKED')
            with app.connection() as c:
                self.assertEqual(c.execute('SELECT status FROM governed_intakes').fetchone()[0],'BLOCKED')
            payload.update(status='FAILED', authorization_id='eauth-current',
                           reason_code='RESOLVED_ADDRESS_OUTSIDE_SCOPE')
            result=post()
            self.assertEqual(result['job']['status'],'FAILED')
            self.assertEqual(result['job']['error'],'RESOLVED_ADDRESS_OUTSIDE_SCOPE')

    def test_retry_updates_one_job_and_ignores_previous_attempt_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as folder, \
                patch.object(app,'DB_PATH',Path(folder)/'jobs.db'), \
                patch.object(app,'CLIENT_TOKEN','t'*40):
            intake='wptreq-retry-regression'
            with app.connection() as c:
                c.execute('INSERT INTO governed_intakes(intake_id,idempotency_key,mission_id,task_id,target_type,target_url,profile,received_at) VALUES(?,?,?,?,?,?,?,?)',
                    (intake,'idem-retry','mission-retry','task-retry','URL','http://localhost','fingerprinting',app.now()))
            payload=dict(schema_version='apts-wpt-stage6-job-v1',mission_id='mission-retry',
                task_id='task-retry',target='http://localhost',profile='fingerprinting',
                execution_id='exec-retry',authorization_id='eauth-retry',status='FAILED',
                reason_code='ADAPTER_WALL_TIMEOUT',runtime_attempt_number=1,
                runtime_attempt_id='xattempt-original')
            def post():
                with urlopen(Request(self.base+'/api/stage6/intakes/'+intake+'/job',
                        data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',
                        'X-APTS-Client-Token':'t'*40})) as response:
                    return json.load(response)
            original=post()['job']
            payload.update(status='RUNNING',runtime_attempt_number=2,runtime_attempt_id='xattempt-nextretry')
            payload.pop('reason_code')
            current=post()['job']
            self.assertEqual(current['job_id'],original['job_id'])
            self.assertEqual(current['status'],'RUNNING')
            self.assertIsNone(current['error'])
            payload.update(status='FAILED',runtime_attempt_number=1,runtime_attempt_id='xattempt-original')
            self.assertTrue(post()['historical_status_ignored'])
            with app.connection() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT status FROM jobs').fetchone()[0],'RUNNING')

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_ui_assets_are_served(self):
        for path, content_type in [('/', 'text/html'), ('/app.js', 'text/javascript'), ('/style.css', 'text/css')]:
            with self.subTest(path=path), urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), content_type)
                self.assertTrue(response.read())

    def test_missing_asset_returns_http_error_instead_of_empty_connection(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as folder, patch.object(app, 'WEB', Path(folder)):
            for path in ['/', '/app.js', '/style.css']:
                with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                    urlopen(self.base + path)
                self.assertEqual(caught.exception.code, 503)
                self.assertIn('error', json.loads(caught.exception.read()))

    def test_standalone_engine_runs_bounded_local_probe(self):
        target = ThreadingHTTPServer(('127.0.0.1', 0), Target)
        thread = threading.Thread(target=target.serve_forever, daemon=True)
        thread.start()
        try:
            result = app.standalone_scan(f'http://127.0.0.1:{target.server_port}', 'fingerprinting')
            self.assertEqual(result['scan_metrics']['responses_received'], 2)
            self.assertEqual(result['scan_metrics']['scan_status'], 'COMPLETED')
            self.assertIn('WordPress', [claim['technology'] for claim in result['technology_claims']])
            self.assertEqual(result['scan_metrics']['favicon_fingerprints'], 1)
            self.assertNotIn('html_excerpt', json.dumps(result))
        finally:
            target.shutdown()
            target.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
