"""Exercise metadata and mapping-only CAPEC catalogs without production writes."""
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Adapter, AppError, query_plan


class Cursor:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        self.result = self.db.execute(sql.replace('%s', '?').replace('%%', '%'), params)

    def fetchone(self):
        row = self.result.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self.result.fetchall()]


class CapecCatalogTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''
          CREATE TABLE capec_patterns (id INTEGER,capec_id TEXT,name TEXT,abstraction TEXT,
            status TEXT,description TEXT,likelihood TEXT,severity TEXT,created_at TEXT,
            updated_at TEXT,prerequisites TEXT,mitigations TEXT);
          CREATE TABLE capec_cwe_mappings (id INTEGER,capec_id TEXT,cwe_id TEXT,is_active INTEGER);
          CREATE TABLE capec_attack_mappings (id INTEGER,capec_id TEXT,attack_id TEXT,is_active INTEGER);
          CREATE TABLE cwe_catalog (cwe_id TEXT,cwe_name TEXT);
          INSERT INTO capec_patterns (id,capec_id,name,description,prerequisites,mitigations)
            VALUES (1,'CAPEC-10','Test pattern','Pattern description','Prerequisite','Mitigation');
          INSERT INTO capec_cwe_mappings VALUES
            (1,'CAPEC-2','CWE-89',1),(2,'CAPEC-2','CWE-89',1),(3,'CAPEC-99','CWE-20',0);
          INSERT INTO capec_attack_mappings VALUES (1,'CAPEC-2','T1190',1),(2,'CAPEC-2','T1059',0);
          INSERT INTO cwe_catalog VALUES ('CWE-89','SQL Injection');
        ''')
        self.adapter = Adapter({'vulndesk_root': str(Path.cwd()), 'service_ports': {}}, Path.cwd())
        @contextmanager
        def database():
            yield Cursor(self.db)
        self.adapter.database = database

    def test_mapping_only_catalog_deduplicates_and_sorts_numerically(self):
        result = self.adapter.data_list('capec', {'sort': 'capec_id', 'direction': 'asc'})
        self.assertEqual(result['total'], 2)
        self.assertEqual([r['capec_id'] for r in result['items']], ['CAPEC-2', 'CAPEC-10'])
        self.assertIsNone(result['items'][0]['name'])
        self.assertEqual(result['items'][0]['cwe_count'], 1)
        self.assertEqual(result['items'][0]['attack_count'], 1)

    def test_pagination_search_and_bound_query_values(self):
        result = self.adapter.data_list('capec', {'search': 'Pattern', 'limit': 1, 'page': 1})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['capec_id'], 'CAPEC-10')
        self.assertEqual(self.adapter.data_list('capec', {'limit': 1, 'page': 3})['items'], [])
        _, sql, params, _, _ = query_plan('capec', {'search': "'; DROP TABLE x", 'sort': 'bad;--'})
        self.assertNotIn('DROP', sql)
        self.assertNotIn('bad;', sql)
        self.assertIn("%'; DROP TABLE x%", params)

    def test_detail_metadata_and_active_relations_without_writes(self):
        before = self.db.total_changes
        detail = self.adapter.data_detail('capec', 'CAPEC-2')
        self.assertIsNone(detail['name'])
        self.assertEqual(detail['cwe_mappings'][0]['cwe_name'], 'SQL Injection')
        self.assertEqual([m['attack_id'] for m in detail['attack_mappings']], ['T1190'])
        self.assertEqual(self.adapter.data_detail('capec', 'CAPEC-10')['mitigations'], 'Mitigation')
        self.assertEqual(self.db.total_changes, before)
        with self.assertRaises(AppError):
            self.adapter.data_detail('capec', 'CAPEC-404')


if __name__ == '__main__':
    unittest.main()
