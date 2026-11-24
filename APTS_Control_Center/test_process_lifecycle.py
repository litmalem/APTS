"""Loopback-only synthetic process; never starts a real APTS launcher."""
from pathlib import Path
import socket
import json
import subprocess
import sys
import tempfile
import time
import unittest
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from unittest.mock import patch

import server as hub


class SyntheticLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='win32','Native Windows recovery')
    def test_external_relative_launcher_stops_through_control_center_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'run.py').write_text('import http.server,sys\nhttp.server.HTTPServer(("127.0.0.1",int(sys.argv[1])),http.server.SimpleHTTPRequestHandler).serve_forever()\n',encoding='utf-8')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            child=subprocess.Popen([sys.executable,'-u','run.py',str(port)],cwd=tmp,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            panel=ThreadingHTTPServer(('127.0.0.1',0),hub.Handler)
            threading.Thread(target=panel.serve_forever,daemon=True).start()
            cfg={'root':tmp,'port':port,'python':sys.executable,'env':{}}
            try:
                deadline=time.monotonic()+8
                while not hub.local_processes.port_open(port) and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(hub.local_processes.port_open(port))
                with patch.dict(hub.CONFIG['modules'],gss=cfg),patch.dict(hub.PROCESSES,{},clear=True):
                    hub.local_processes.listeners(fresh=True)
                    state=hub.status('gss')
                    self.assertFalse(state['owned'])
                    self.assertTrue(state['can_stop'],state)
                    self.assertEqual(state['pid'],child.pid)
                    request=Request(f'http://127.0.0.1:{panel.server_port}/api/action',data=json.dumps({'module':'gss','action':'stop'}).encode(),headers={'X-Control-Token':hub.TOKEN,'Content-Type':'application/json'})
                    with urlopen(request,timeout=15) as response:result=json.load(response)
                    self.assertEqual(result['pid'],child.pid)
                    child.wait(timeout=5)
                    self.assertFalse(hub.local_processes.port_open(port))
            finally:
                panel.shutdown();panel.server_close()
                if child.poll() is None:child.kill();child.wait(timeout=5)

    def test_owned_http_process_stops_and_closes_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'run.py').write_text(
                'import os\nfrom http.server import HTTPServer,BaseHTTPRequestHandler\n'
                'class H(BaseHTTPRequestHandler):\n'
                ' def do_GET(self):\n'
                '  self.send_response(200);self.end_headers();self.wfile.write(b\'{"status":"ok"}\')\n'
                ' def log_message(self,*args): pass\n'
                'HTTPServer(("127.0.0.1",int(os.environ["GOV_PORT"])),H).serve_forever()\n',
                encoding='utf-8')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            cfg = {'root': tmp, 'port': port, 'python': sys.executable, 'env': {}}
            with patch.dict(hub.CONFIG['modules'], gss=cfg), patch.dict(hub.PROCESSES, {}, clear=True), patch.object(hub, 'LOGS', root):
                child = None
                try:
                    started = hub.action('gss', 'start')
                    child = hub.PROCESSES['gss']
                    deadline = time.monotonic() + 8
                    while not hub.fetch('gss')['ok'] and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertTrue(hub.fetch('gss')['ok'])
                    self.assertTrue(hub.status('gss')['can_stop'])
                    self.assertEqual(started['pid'], hub.action('gss', 'start')['pid'])
                    self.assertEqual(started['pid'], hub.action('gss', 'stop')['pid'])
                    self.assertIsNotNone(child.poll())
                    self.assertFalse(hub.local_processes.port_open(port))
                finally:
                    if child and child.poll() is None:
                        child.kill()
                        child.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
