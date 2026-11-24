"""Registry-to-client integration tests with fake external services, no network or MariaDB."""
from __future__ import annotations

import copy
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if "cti_services" not in sys.modules:
    package=types.ModuleType("cti_services");package.__path__=[str(ROOT/"cti_services")];sys.modules["cti_services"]=package
from cti_services.source_sync_connector import SourceSyncConnector
from cti_services.acquisition_freshness_agent import AcquisitionFreshnessAgent
from cti_source_config import apply_client_settings, source_binding


class ConnectorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.row={"source_id":"custom-feed","protocol":"REST_JSON","endpoint_ref":"https://mirror.example.org/cves/2.0",
                  "credential_ref":"env:MIRROR_API_KEY","enabled":1,"config_json":json.dumps({"adapter_type":"nvd-cve","max_pages":2,"page_size":123,"timeout_seconds":27,"auth_mode":"api-key"})}
        self.db=MagicMock();self.db.fetch_one.return_value=self.row
        self.client=types.SimpleNamespace(base_url='https://old.example.org/feed',api_key='old',timeout_seconds=90,request_delay_seconds=0.6,
                                         session=types.SimpleNamespace(headers={'apiKey':'old'}))
        self.service=MagicMock();self.service.api_client=self.client
        self.service.run_incremental_sync.return_value={"status":"SUCCESS","checkpoint":"cursor"}
        self.connector=SourceSyncConnector(db=self.db)
        self.proposal={"source_id":"custom-feed","source_binding":source_binding(self.row)}

    def test_updated_registry_endpoint_key_timeout_and_bounds_reach_actual_client(self):
        module=types.SimpleNamespace(SyncService=MagicMock(return_value=self.service))
        with patch.dict(sys.modules,{"services":module}),patch.dict(os.environ,{"MIRROR_API_KEY":"PRIVATE"}):
            result=self.connector.execute(self.proposal)
        self.assertEqual(self.client.base_url,"https://mirror.example.org/cves/2.0")
        self.assertEqual(self.client.timeout_seconds,27)
        self.assertEqual(self.client.session.headers["apiKey"],"PRIVATE")
        self.assertEqual(result["source_id"],"custom-feed")
        self.assertEqual(result["watermark_after_candidate"],"cursor")
        self.assertNotIn("PRIVATE",json.dumps(result))
        self.assertEqual(self.service.run_incremental_sync.call_args.kwargs["max_pages"],2)
        self.assertEqual(self.service.run_incremental_sync.call_args.kwargs["page_size"],123)

    def test_disabled_deleted_or_changed_source_stops_before_service_execution(self):
        for row in [None,{**self.row,"enabled":0},{**self.row,"endpoint_ref":"https://changed.example.org/feed"}]:
            self.db.fetch_one.return_value=row
            with self.subTest(row=row),self.assertRaises(ValueError):self.connector.execute(self.proposal)
        self.service.run_incremental_sync.assert_not_called()

    def test_builtins_keep_legacy_endpoint_and_credential_references(self):
        descriptor={**self.row,"source_id":"nvd-cve","endpoint_ref":"config:NVD_CVE_API","credential_ref":"secret-ref:NVD_API_KEY","config_json":"{}"}
        apply_client_settings(self.client,descriptor,{"NVD_API_URL":"https://configured.example.org/nvd","NVD_API_KEY":"LEGACY"})
        self.assertEqual(self.client.base_url,"https://configured.example.org/nvd")
        self.assertEqual(self.client.api_key,"LEGACY")

    def test_custom_cpe_dispatch_preserves_id_and_parameters(self):
        self.row['config_json']=json.dumps({'adapter_type':'nvd-cpe','keyword':'openssl','page_size':42,'max_pages':3})
        self.service.sync_keyword.return_value={'status':'SUCCESS'}
        module=types.SimpleNamespace(CpeDictionarySyncService=MagicMock(return_value=self.service))
        with patch.dict(sys.modules,{'cpe_dictionary_services':module}):
            result=self.connector.execute({'source_id':'custom-feed','source_binding':source_binding(self.row)})
        self.assertEqual(result['source_id'],'custom-feed')
        self.assertEqual(self.service.sync_keyword.call_args.args,('openssl',))
        self.assertEqual(self.service.sync_keyword.call_args.kwargs['page_size'],42)

    def test_taxii_collection_and_bearer_are_per_client(self):
        self.row['config_json']=json.dumps({'adapter_type':'mitre-attack','collection_id':'collection-new','auth_mode':'bearer'})
        self.client=types.SimpleNamespace(base_url='old',timeout=90,collection_id='old',session=types.SimpleNamespace(headers={}))
        self.service.api_client=self.client
        module=types.SimpleNamespace(MitreAttackSyncService=MagicMock(return_value=self.service))
        with patch.dict(sys.modules,{'mitre_attack_services':module}),patch.dict(os.environ,{'MIRROR_API_KEY':'PRIVATE'}):
            self.connector.execute({'source_id':'custom-feed'})
        self.assertEqual(self.client.collection_id,'collection-new')
        self.assertEqual(self.client.session.headers['Authorization'],'Bearer PRIVATE')
        self.service.run_incremental_sync.assert_called_once()

    def test_cwe_acquisition_is_bounded_to_configured_single_id(self):
        self.row['config_json']=json.dumps({'adapter_type':'mitre-cwe','cwe_id':'CWE-79','auth_mode':'none'})
        self.service.sync_single_cwe.return_value={'status':'SUCCESS'}
        module=types.SimpleNamespace(CweSyncService=MagicMock(return_value=self.service))
        with patch.dict(sys.modules,{'cwe_services':module}):
            result=self.connector.execute({'source_id':'custom-feed'})
        self.assertEqual(self.service.sync_single_cwe.call_args.args,('CWE-79',))
        self.assertEqual(result['source_id'],'custom-feed')

    def test_client_configuration_does_not_mutate_another_source_or_descriptor(self):
        other=copy.deepcopy(self.client)
        original=copy.deepcopy(self.row)
        apply_client_settings(self.client,self.row,{'MIRROR_API_KEY':'PRIVATE'})
        self.assertEqual(other.base_url,'https://old.example.org/feed')
        self.assertEqual(other.api_key,'old')
        self.assertEqual(self.row,original)

    def test_unsupported_source_is_excluded_from_agent_candidates(self):
        known={**self.row,'source_id':'nvd-cve','config_json':'{}'}
        pending={**self.row,'source_id':'future-api','config_json':'{"adapter_type":"registry-only"}'}
        self.db.table_exists.return_value=True;self.db.fetch_all.return_value=[known,pending]
        agent=AcquisitionFreshnessAgent(db=self.db,registry=MagicMock(),audit=MagicMock())
        self.assertEqual([r['source_id'] for r in agent.list_sources()],['nvd-cve'])


if __name__=='__main__': unittest.main()
