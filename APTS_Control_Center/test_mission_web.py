import json
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from test_control_center import hub


class FakeMission(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/ui/':
            body = b'<html><script src="/ui/app.js"></script></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path not in ('/health', '/api/dashboard/summary', '/api/missions', '/api/operator/attention'):
            self.send_error(404)
            return
        body = json.dumps({'status': 'ok', 'path': self.path}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class MissionWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeMission)
        import threading
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.fake.shutdown()
        cls.fake.server_close()

    def test_mission_web_inherits_authoritative_mission_root_and_port(self):
        base = {
            'root': 'D:/mission source',
            'port': self.fake.server_port,
            'python': sys.executable,
            'env': {'MISSION_TEST': 'base'},
        }
        web = {
            'root': 'ignored',
            'port': 19999,
            'python': '',
            'env': {'MISSION_WEB_TEST': 'web'},
        }
        with patch.dict(hub.CONFIG['modules'], {'mission': base, 'mission_web': web}):
            cfg = hub.module_config('mission_web')
            self.assertEqual(cfg['root'], 'D:/mission source')
            self.assertEqual(cfg['port'], self.fake.server_port)
            self.assertEqual(cfg['env'], {'MISSION_TEST': 'base', 'MISSION_WEB_TEST': 'web'})
            state = hub.status('mission_web')
            self.assertTrue(state['ok'])
            self.assertEqual(state['data']['ui'], 'Mission Web')
            self.assertTrue(state['shared_process'])
            self.assertEqual(state['process_owner'], 'mission')

    def test_mission_web_opens_ui_route(self):
        base = {'root': 'D:/mission', 'port': self.fake.server_port, 'python': sys.executable, 'env': {}}
        with patch.dict(hub.CONFIG['modules'], {'mission': base, 'mission_web': {}}), \
             patch.object(hub.webbrowser, 'open_new_tab', return_value=True) as opened:
            result = hub.action('mission_web', 'open')
            expected = f'http://127.0.0.1:{self.fake.server_port}/ui/'
            self.assertEqual(result['url'], expected)
            opened.assert_called_once_with(expected)

    def test_mission_web_shares_mission_process_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'Mission source with spaces'
            (root / 'run').mkdir(parents=True)
            worker = root / 'run' / 'run_stage6_10_mission.py'
            worker.write_text(
                "import argparse,json\n"
                "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
                "p=argparse.ArgumentParser();p.add_argument('--host');p.add_argument('--port',type=int);a=p.parse_args()\n"
                "class H(BaseHTTPRequestHandler):\n"
                " def do_GET(self):\n"
                "  if self.path == '/ui/':\n"
                "   b=b'<script src=\"/ui/app.js\"></script>';self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b);return\n"
                "  if self.path not in ('/health','/api/dashboard/summary'):\n"
                "   self.send_error(404);return\n"
                "  b=json.dumps({'status':'ok','path':self.path}).encode();self.send_response(200);self.end_headers();self.wfile.write(b)\n"
                " def log_message(self,*args):pass\n"
                "print('synthetic Mission Web host',flush=True)\n"
                "HTTPServer((a.host,a.port),H).serve_forever()\n",
                encoding='utf-8',
            )
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            base = {'root': str(root), 'port': port, 'python': sys.executable, 'env': {}}
            old_logs = hub.LOGS
            with tempfile.TemporaryDirectory() as logtmp:
                hub.LOGS = Path(logtmp)
                with patch.dict(hub.CONFIG['modules'], {'mission': base, 'mission_web': {}}):
                    try:
                        started = hub.action('mission_web', 'start')
                        self.assertGreater(started['pid'], 0)
                        deadline = time.monotonic() + 5
                        while True:
                            web = hub.status('mission_web')
                            mission = hub.status('mission')
                            if (web['ok'] and mission['ok']) or time.monotonic() >= deadline:
                                break
                            time.sleep(0.05)
                        self.assertTrue(web['ok'], web)
                        self.assertTrue(mission['ok'], mission)
                        self.assertTrue(web['owned'])
                        self.assertTrue(mission['owned'])
                        self.assertEqual(web['pid'], mission['pid'])
                        self.assertEqual(web['pid'], started['pid'])
                        log = (hub.LOGS / 'mission.log').read_text(encoding='utf-8', errors='replace')
                        self.assertIn('synthetic Mission Web host', log)
                        hub.action('mission_web', 'stop')
                        self.assertIsNotNone(hub.PROCESSES['mission'].poll())
                    finally:
                        child = hub.PROCESSES.pop('mission', None)
                        if child and child.poll() is None:
                            child.kill()
                            child.wait()
                        hub.LOGS = old_logs


if __name__ == '__main__':
    unittest.main(verbosity=2)
