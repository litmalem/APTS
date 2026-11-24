from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

from mission_orchestrator import mission_wpt_inbox_delivery as delivery


def test_delivery_posts_only_the_governed_intake_and_uses_service_token(monkeypatch):
    seen = {}
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            seen['path'] = self.path
            seen['token'] = self.headers.get('X-APTS-Client-Token')
            seen['body'] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            raw = json.dumps({'created': True, 'intake_id': seen['body']['intake_id']}).encode()
            self.send_response(201); self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        monkeypatch.setenv('APTS_WPT_INBOX_URL', f'http://127.0.0.1:{server.server_port}')
        monkeypatch.setenv('APTS_WPT_INBOX_TOKEN', '0123456789abcdef0123456789abcdef')
        intake = {'schema_version':'apts-wpt-governed-intake-v1','intake_id':'wptreq-auto-test',
                  'idempotency_key':'idem-auto-test','mission_id':'mission-gmo-test','task_id':'ptask-test',
                  'target':{'target_type':'URL','target_value':'https://lab.example.test/'},'profile':'fingerprinting',
                  'authority_snapshot':{'untrusted':'must not be forwarded'}}
        result = delivery.deliver(intake)
        assert result == {'status':'DELIVERED','created':True,'intake_id':'wptreq-auto-test'}
        assert seen['path'] == '/api/governed-intakes'
        assert seen['token'] == '0123456789abcdef0123456789abcdef'
        assert set(seen['body']) == {'schema_version','intake_id','idempotency_key','mission_id','task_id','target','profile'}
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
