"""Cross-repository test: set VULNDESK_ROOT to the patched VulnDesk checkout."""
import importlib.util
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.request import Request, urlopen
import pytest
from mission_orchestrator.api_service import MissionOrchestratorHandler
from mission_orchestrator.repository import MissionRepository
from mission_orchestrator.service import CanonicalMissionService
from mission_orchestrator.task_routing import CtiSubsystemClient
from test_stage3_2_3_mission_pip_activation import mission_payload, lifecycle_request
from test_stage3_1_3_scope_roe_constraint_contract import contract_payload


def test_real_cti_publication_to_mission_http_and_activation(tmp_path):
    root=os.environ.get('VULNDESK_ROOT')
    if not root: pytest.skip('Set VULNDESK_ROOT for cross-repository CTI integration')
    fixture=Path(root)/'tests/test_pip_initialization_readback.py'
    spec=importlib.util.spec_from_file_location('cti_initialization_fixture',fixture)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    cti=mod.MemoryPipService()
    class CtiHandler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send_json(self,data):
            raw=json.dumps(data).encode();self.send_response(200);self.end_headers();self.wfile.write(raw)
        def do_GET(self): self.send_json({'status':'completed','pip':cti.get_pip(self.path.rsplit('/',1)[-1])})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            for key in ('asset_profiles','cpe_claims','vulnerability_correlations','attack_mappings'):body.setdefault(key,[])
            self.send_json(cti.build(**body))
    cti_server=ThreadingHTTPServer(('127.0.0.1',0),CtiHandler)
    svc=CanonicalMissionService(MissionRepository(driver='sqlite',sqlite_path=str(tmp_path/'mission.db')),
        cti_client=CtiSubsystemClient(base_url=f'http://127.0.0.1:{cti_server.server_port}'))
    class Handler(MissionOrchestratorHandler):
        service=svc
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threads=[Thread(target=s.serve_forever,daemon=True) for s in (cti_server,server)]
    for t in threads:t.start()
    def call(path,payload=None):
        r=Request(f'http://127.0.0.1:{server.server_port}'+path,
                  data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urlopen(r) as response:return json.load(response)
    try:
        mid=call('/api/missions',mission_payload('http-init',with_pip=False))['canonical_identity']['mission_id']
        prefix='/api/missions/'+mid
        call(prefix+'/scope-contract',contract_payload())
        built=call(prefix+'/pip-build',{})['pip']
        assert built['readiness']=='PARTIAL'
        p={'pip_id':built['pip_id'],'pip_version':str(built['revision']),'expected_envelope_version':1,
           'idempotency_key':'http-init','actor':'tester','reason':'CTI integration'}
        bound=call(prefix+'/pip-binding',p)
        assert bound['envelope_version']==2
        assert call(prefix+'/pip-binding',p)['idempotent_replay']
        assert len(call(prefix+'/pip-binding')['versions'])==2
        assert call(prefix+'/activation-contract')['mission_activation']['activation_ready']
        call(prefix+'/lifecycle/commands',lifecycle_request(svc,mid))
        assert call(prefix+'/state')['mission_state']['state']=='PIP_BOUND'
    finally:
        for s in (server,cti_server):s.shutdown();s.server_close()
        for t in threads:t.join()
