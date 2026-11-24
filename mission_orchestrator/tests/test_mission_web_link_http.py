"""Regression: the actual Mission console and its dashboard must be reachable."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import build_opener, ProxyHandler
from urllib.error import HTTPError

from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService


class MissionWebHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'mission.db'
        service = CanonicalMissionService(repository=MissionRepository(sqlite_path=str(self.db)))
        class Handler(MissionOrchestratorHandler):
            def log_message(self, *args):
                pass
        Handler.service = service
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def test_console_assets_and_dashboard_read_models(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        for path, marker in [('/ui/', b'/ui/app.js'), ('/ui', b'/ui/app.css'),
                             ('/ui/app.js', b'/api/dashboard/summary'), ('/ui/app.css', b'{')]:
            with self.subTest(path=path), self.opener.open(self.base + path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(marker, response.read())
        for path in ['/api/dashboard/summary', '/api/missions?visibility=ACTIVE',
                     '/api/operator/attention', '/api/operator/attention/advanced']:
            with self.subTest(path=path), self.opener.open(self.base + path) as response:
                self.assertTrue(json.load(response)['read_only'])
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())

    def test_static_traversal_and_invalid_parameters_are_rejected(self):
        for path, status in [('/ui/../mission_orchestrator/service.py', 404),
                             ('/ui/missing.js', 404), ('/api/missions?limit=bad', 400),
                             ('/api/operator/attention?limit=bad', 400)]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                self.opener.open(self.base + path)
            self.assertEqual(caught.exception.code, status)

if __name__ == '__main__':
    unittest.main()
