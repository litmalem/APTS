"""Execute the mapping joins against a relational fixture; no production writes."""
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Adapter


class Cursor:
    def __init__(self, db):
        self.db = db
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        self.result = self.db.execute(sql.replace('%s', '?'), params)

    def fetchall(self):
        return [dict(row) for row in self.result.fetchall()]


class CweAttackMappingTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE cwe_catalog (id INTEGER, cwe_id TEXT, cwe_name TEXT);
            CREATE TABLE vulnerability_cwes (vulnerability_id INTEGER, cwe_catalog_id INTEGER);
            CREATE TABLE vuln_attack_mappings (id INTEGER, cwe_id TEXT, attack_id TEXT,
                attack_name TEXT, tactic_name TEXT, mapping_source TEXT, confidence REAL,
                rationale TEXT, is_active INTEGER, mapping_level TEXT);
            INSERT INTO cwe_catalog VALUES (1,'CWE-89','SQL injection'), (2,'CWE-22','Traversal');
            INSERT INTO vulnerability_cwes VALUES (10,1),(10,1),(10,2),(20,2),(30,999);
            INSERT INTO vuln_attack_mappings VALUES
                (1,'CWE-89','T1190','Exploit application','Initial Access','seed',0.7,'SQL context',1,'cwe_to_attack'),
                (2,'CWE-22','T1190','Exploit application','Initial Access','seed',0.6,'Traversal context',1,'cwe_to_attack'),
                (3,'CWE-89','T1059','Interpreter','Execution','manual',0.5,'Secondary context',1,'cwe_to_attack'),
                (4,'CWE-89','T9999','Disabled','','seed',0.9,'',0,'cwe_to_attack'),
                (5,'CWE-89','T8888','Wrong level','','seed',0.9,'',1,'cve_to_attack'),
                (6,'CWE-89',NULL,'Missing ID','','seed',0.9,'',1,'cwe_to_attack'),
                (7,'CWE-89','  ','Blank ID','','seed',0.9,'',1,'cwe_to_attack');
        ''')
        provenance = 'source_dataset source_version source_url source_sha256 relationship_type references_json publisher_status'.split()
        self.db.execute('ALTER TABLE vuln_attack_mappings ADD COLUMN cve_id TEXT')
        for column in provenance:
            self.db.execute('ALTER TABLE vuln_attack_mappings ADD COLUMN '+column+' TEXT')
        self.db.execute('CREATE TABLE vulnerabilities (id INTEGER,cve_id TEXT)')
        self.db.executemany('INSERT INTO vulnerabilities VALUES (?,?)',[(10,'CVE-2024-1234'),(20,'CVE-2024-5678'),(40,'CVE-2024-9999')])
        self.db.execute('CREATE TABLE capec_cwe_mappings (id INTEGER,cwe_id TEXT,capec_id TEXT,is_active INTEGER)')
        self.db.execute('CREATE TABLE capec_attack_mappings (id INTEGER,capec_id TEXT,attack_id TEXT,attack_name TEXT,tactic_name TEXT,confidence REAL,rationale TEXT,is_active INTEGER,'+','.join(k+' TEXT' for k in provenance)+')')
        self.initial_changes = self.db.total_changes
        self.cursor = Cursor(self.db)

    def test_batch_groups_techniques_and_preserves_distinct_cwe_paths(self):
        rows = [{'id': 10}, {'id': 20}, {'id': 30}, {'id': 40}]
        Adapter._attach_cwe_attack_mappings(self.cursor, rows)
        self.assertEqual(len(self.cursor.calls), 1)
        self.assertEqual(self.cursor.calls[0][1], (10, 20, 30, 40) * 3)
        self.assertEqual(rows[0]['attack_technique_count'], 2)
        first = rows[0]['attack_mappings'][0]
        self.assertEqual(first['attack_id'], 'T1190')
        self.assertEqual(first['confidence'], 0.7)  # Never add confidence across paths.
        self.assertEqual({p['cwe_id'] for p in first['paths']}, {'CWE-89', 'CWE-22'})
        self.assertEqual(len(first['paths']), 2)  # Duplicate CVE/CWE association deduped.
        self.assertEqual(first['mapping_status'], 'INFERRED')
        self.assertEqual(rows[1]['attack_technique_count'], 1)
        self.assertEqual(rows[1]['attack_mappings'][0]['confidence'], 0.6)
        for row in rows[2:]:
            self.assertEqual(row['attack_mapping_status'], 'NO_CWE_MAPPING')
            self.assertEqual(row['attack_mappings'], [])
        self.assertEqual(self.db.total_changes, self.initial_changes)  # Lookup performed no writes.

    def test_direct_mapping_without_cwe_and_capec_paths_retain_provenance(self):
        self.db.execute("INSERT INTO vuln_attack_mappings (id,cve_id,attack_id,attack_name,confidence,is_active,mapping_level,source_dataset,relationship_type) VALUES (8,'CVE-2024-9999','T1059','Interpreter',0.75,1,'cve_to_attack','ctid-cve-attack','primary_impact')")
        self.db.execute("INSERT INTO capec_cwe_mappings VALUES (1,'CWE-89','CAPEC-100',1)")
        self.db.execute("INSERT INTO capec_attack_mappings (id,capec_id,attack_id,confidence,is_active,source_dataset,source_version) VALUES (1,'CAPEC-100','T1190',0.6,1,'mitre-capec','CAPEC:3.9')")
        rows = [{'id':40},{'id':10}]
        Adapter._attach_cwe_attack_mappings(self.cursor, rows)
        self.assertEqual(rows[0]['attack_mapping_status'],'MAPPED_DIRECT')
        self.assertEqual(rows[0]['attack_mappings'][0]['mapping_status'],'CURATED')
        self.assertEqual(rows[0]['attack_mappings'][0]['paths'][0]['relationship_type'],'primary_impact')
        self.assertEqual(rows[1]['attack_mapping_status'],'MAPPED_VIA_CAPEC')
        paths = rows[1]['attack_mappings'][0]['paths']
        self.assertEqual({p['mapping_kind'] for p in paths},{'CWE_RULE','CAPEC'})
        self.assertEqual(next(p for p in paths if p['capec_id'])['source_version'],'CAPEC:3.9')

    def test_empty_page_does_not_query(self):
        Adapter._attach_cwe_attack_mappings(self.cursor, [])
        self.assertEqual(self.cursor.calls, [])

    def test_ids_are_bound_values(self):
        bad_id = "10) OR 1=1;--"
        rows = [{'id': bad_id}]
        Adapter._attach_cwe_attack_mappings(self.cursor, rows)
        self.assertNotIn(bad_id, self.cursor.calls[0][0])
        self.assertEqual(rows[0]['attack_mappings'], [])

    def test_rule_changes_are_reflected_without_materializing_mission_results(self):
        self.db.execute('UPDATE vuln_attack_mappings SET is_active=0')
        rows = [{'id': 10}]
        Adapter._attach_cwe_attack_mappings(self.cursor, rows)
        self.assertEqual(rows[0]['attack_technique_count'], 0)

    def test_list_and_detail_include_mapping_contract(self):
        adapter = Adapter({'vulndesk_root': '.', 'service_ports': {}}, '.')
        cursor = MagicMock()
        adapter.database = lambda: contextmanager(lambda: iter([cursor]))()
        cursor.fetchone.return_value = {'total': 1}
        cursor.fetchall.side_effect = [[{'id': 10}], []]
        row = adapter.data_list('vulnerabilities', {})['items'][0]
        self.assertEqual(row['attack_mapping_status'], 'NO_CWE_MAPPING')
        cursor.fetchone.return_value = {'id': 10, 'cve_id': 'CVE-2026-1', 'raw_json': '{}'}
        cursor.fetchall.side_effect = [[], [], [], [], []]
        row = adapter.data_detail('vulnerabilities', 10)
        self.assertEqual(row['attack_technique_count'], 0)
        self.assertIn('attack_mappings', row)


if __name__ == '__main__':
    unittest.main()
