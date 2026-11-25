import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
package = types.ModuleType('cti_services')
package.__path__ = [str(ROOT / 'cti_services'), r'D:\APTS\Vulndesk\cti_services']
sys.modules.setdefault('cti_services', package)
from cti_services.attack_mapping_service import AttackMappingService
from cti_services.source_sync_connector import SourceSyncConnector
from mapping_source_services import SOURCES
from cti_source_config import source_binding


class IntegrationTests(unittest.TestCase):
    def test_technique_only_lookup_skips_threat_profiles_and_keeps_legacy_default(self):
        from cti_services.vulnerability_context_service import VulnerabilityContextService
        service = VulnerabilityContextService.__new__(VulnerabilityContextService)
        service.attack_mapper = MagicMock()
        service.attack_mapper.map_vulnerability.side_effect = lambda *args: [{'attack_id':'T1189'}]
        service.threat_context = MagicMock()
        candidate = {'cve_id': 'CVE-2025-66412'}
        result = service.map_attack({'candidate': candidate, 'include_threat_context': False})
        self.assertEqual(result['attack_context'], [{'attack_id':'T1189'}])
        service.threat_context.enrich_attack_context.assert_not_called()
        service.map_attack({'candidate': candidate})
        service.threat_context.enrich_attack_context.assert_called_once()
        with self.assertRaises(ValueError):
            service.map_attack({'candidate': candidate, 'include_threat_context': 'false'})

    def test_cve_resolves_all_catalog_cwes_and_keeps_strongest_mapping(self):
        service = AttackMappingService.__new__(AttackMappingService)
        service.registry = MagicMock()
        service.db = MagicMock()
        service.db.table_exists.return_value = True
        service.db.fetch_all.return_value = [
            {'cwe_id': 'CWE-79', 'cwe_name': 'XSS'},
            {'cwe_id': 'CWE-918', 'cwe_name': 'SSRF'},
            {'cwe_id': 'CWE-79', 'cwe_name': 'XSS'},
        ]
        service._map_by_cve = MagicMock(return_value=[])
        service._map_by_capec = MagicMock(return_value=[])
        service._map_by_cwe = MagicMock(side_effect=lambda h: [{
            'attack_id': 'T1189', 'cwe_id': h['cwe_id'], 'mapping_source': 'seed',
            'mapping_level': 'cwe_to_attack', 'confidence': 0.45 if h['cwe_id']=='CWE-79' else 0.6}])
        service._map_by_vuln_type = MagicMock(return_value=[])
        service._map_by_keywords = MagicMock(return_value=[])
        service._map_by_endpoint_heuristic = MagicMock(return_value=[])
        service._complete_attack_metadata = lambda m: {**m, 'mapping_confidence': m['confidence']}
        candidate = {'cve_id': 'CVE-2025-66412', 'cwe_id': 'CWE-79'}
        result = service.map_vulnerability(candidate)
        self.assertEqual(service._map_by_cwe.call_count, 2)
        self.assertEqual(service._map_by_capec.call_count, 2)
        self.assertEqual(result[0]['confidence'], 0.6)
        self.assertEqual({m['cwe_id'] for m in result[0]['supporting_mappings']}, {'CWE-79','CWE-918'})
        self.assertEqual(candidate, {'cve_id': 'CVE-2025-66412', 'cwe_id': 'CWE-79'})

    def test_keyword_rce_requires_a_whole_word(self):
        service = AttackMappingService.__new__(AttackMappingService)
        service._query_vuln_attack_mappings = MagicMock(return_value=[])
        for text in ['Resource URL', 'source language', 'policy enforcement', 'PercentPipe']:
            self.assertEqual(service._map_by_keywords({'description': text}), [])
        for text in ['RCE', 'Potential (rce).', 'remote code execution']:
            self.assertEqual(service._map_by_keywords({'description': text})[0]['attack_id'], 'T1190')

    def test_imported_context_is_provisional_and_dedupe_retains_relationship_types(self):
        service = AttackMappingService.__new__(AttackMappingService)
        rows = [service._verify_mapping({}, {'attack_id':'T1190','confidence':0.75,
                 'source_dataset':'ctid-cve-attack','relationship_type':kind})
                for kind in ['exploitation_technique','primary_impact']]
        self.assertTrue(all(row['verification_state']=='PROVISIONAL' for row in rows))
        result = service._rank_and_dedupe(rows)
        self.assertEqual(len(result),1)
        self.assertEqual({m['relationship_type'] for m in result[0]['supporting_mappings']},
                         {'exploitation_technique','primary_impact'})

    def test_imported_metadata_lookup_avoids_column_metadata_scan(self):
        service = AttackMappingService.__new__(AttackMappingService)
        service.db = MagicMock()
        service.db.table_exists.return_value = True
        service.db.fetch_one.return_value = {'stix_id':'attack-pattern--example','name':'Example'}
        result = service._complete_attack_metadata({'attack_id':'T1190','source_dataset':'ctid-cve-attack','confidence':0.75})
        self.assertEqual(result['attack_pattern_stix_id'],'attack-pattern--example')
        service.db.columns.assert_not_called()

    def test_governed_connector_routes_both_sources_and_preserves_binding_check(self):
        for kind,url in SOURCES.items():
            db = MagicMock()
            descriptor = {'source_id':kind,'endpoint_ref':url,'protocol':'REST_JSON',
                          'enabled':1,'config_json':json.dumps({'adapter_type':kind,'timeout_seconds':27})}
            db.fetch_one.return_value = descriptor
            connector = SourceSyncConnector(db=db)
            proposal = {'source_id':kind,'source_binding':source_binding(descriptor)}
            with patch('mapping_source_services.sync',return_value={'status':'SUCCESS','sha256':'abc'}) as run:
                outcome = connector.execute(proposal)
                self.assertEqual(run.call_args.args[:2],(kind,url))
                self.assertEqual(run.call_args.kwargs['timeout'],27)
                self.assertEqual(outcome['watermark_after_candidate'],'abc')
                self.assertEqual(outcome['validation_status'],'valid')
            proposal['source_binding']='outdated'
            with patch('mapping_source_services.sync') as run, self.assertRaises(ValueError):
                connector.execute(proposal)
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
