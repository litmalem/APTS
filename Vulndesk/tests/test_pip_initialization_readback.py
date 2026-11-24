import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
if 'cti_services' not in sys.modules:
    pkg=types.ModuleType('cti_services'); pkg.__path__=[str(ROOT/'cti_services')];sys.modules['cti_services']=pkg
from cti_services.pip_assembly_validation_service import PipAssemblyValidationService


class MemoryPipService(PipAssemblyValidationService):
    def __init__(self):
        self.row=None
        db=SimpleNamespace(table_exists=lambda name:True,fetch_one=lambda *a,**k:self.row)
        registry=SimpleNamespace(is_enabled=lambda _:True,update_status=lambda *a,**k:None)
        super().__init__(db=db,registry=registry,audit=SimpleNamespace(append=lambda **k:None))
    def _next_revision(self,mid): return 1
    def _persist(self,record):
        self.row={**record,'revision_no':record['revision'],'artifact_json':json.dumps(record['artifact'])}


def build(service):
    return service.build(mission_id='mission-real-test',mission_binding={'scope':{'targets':[{'target_type':'URL','target_value':'http://localhost/dvwa/login.php'}]},'mission_scope_sha256':'a'*64,'mission_scope_snapshot_id':'snapshot-test'},asset_profiles=[],cpe_claims=[],vulnerability_correlations=[],attack_mappings=[])


def test_published_partial_pip_readback_revalidates_all_gates():
    service=MemoryPipService();built=build(service)['pip'];read=service.get_pip(built['pip_id'])
    assert read['readiness']=='PARTIAL'
    assert len(read['validation_results'])==10
    assert all(r['passed'] for r in read['validation_results'])
    assert read['canonical_sha256']==built['canonical_sha256']
    assert read['artifact']['intelligence']['vulnerability_correlations']==[]


def test_readback_detects_tampered_persisted_bytes():
    service=MemoryPipService();built=build(service)['pip']
    data=json.loads(service.row['artifact_json']);data['mission_binding']['scope']={'targets':['wrong']}
    service.row['artifact_json']=json.dumps(data)
    read=service.get_pip(built['pip_id'])
    assert read['readiness']=='REJECTED'
    assert not next(r for r in read['validation_results'] if r['gate_id']=='QG-H4')['passed']
