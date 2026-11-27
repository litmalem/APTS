import copy
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mapping_source_services import SOURCES, PROVENANCE, parse_dataset, import_dataset, validate_source_url


def ctid(attack='T1190'):
    return json.dumps({'metadata': {'technology_domain': 'enterprise', 'mapping_framework': 'kev',
        'mapping_framework_version': '2025-07-28', 'attack_version': '16.1'}, 'mapping_objects': [
        {'status': 'complete', 'capability_id': 'CVE-2024-1234', 'attack_object_id': attack,
         'mapping_type': kind, 'comments': 'Published evidence', 'references': ['https://example.org/report']}
        for kind in ['primary_impact', 'exploitation_technique']]}).encode()


XML = b'''<Attack_Pattern_Catalog xmlns="http://capec.mitre.org/capec-3" Version="3.9">
<Attack_Patterns><Attack_Pattern ID="100" Name="Example" Status="Draft" Abstraction="Standard">
<Description>Nested <b>pattern description</b>.</Description>
<Likelihood_Of_Attack>High</Likelihood_Of_Attack><Typical_Severity>Medium</Typical_Severity>
<Prerequisites><Prerequisite>First prerequisite.</Prerequisite><Prerequisite>Second prerequisite.</Prerequisite></Prerequisites>
<Mitigations><Mitigation>Validate <b>input</b>.</Mitigation></Mitigations>
<Related_Weaknesses><Related_Weakness CWE_ID="89"/></Related_Weaknesses>
<Taxonomy_Mappings><Taxonomy_Mapping Taxonomy_Name="ATTACK"><Entry_ID>1190</Entry_ID>
<Entry_Name>Exploit Application</Entry_Name></Taxonomy_Mapping></Taxonomy_Mappings>
</Attack_Pattern><Attack_Pattern ID="101" Status="Deprecated">
<Related_Weaknesses><Related_Weakness CWE_ID="1"/></Related_Weaknesses>
</Attack_Pattern></Attack_Patterns></Attack_Pattern_Catalog>'''


class SqlCursor:
    """Translate only MariaDB upsert/locking syntax; execute real relational writes."""
    def __init__(self, db):
        self.db = db
    def execute(self, sql, params=()):
        sql = sql.replace('%s', '?').replace(' FOR UPDATE', '')
        if ' ON DUPLICATE KEY UPDATE ' in sql:
            import re
            sql = sql.replace(' ON DUPLICATE KEY UPDATE ', ' ON CONFLICT DO UPDATE SET ')
            sql = re.sub(r'VALUES\((\w+)\)', r'excluded.\1', sql)
        self.result = self.db.execute(sql, params)
    def fetchone(self):
        row = self.result.fetchone()
        return dict(row) if row else None
    def fetchall(self):
        return [dict(row) for row in self.result.fetchall()]


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        common = ','.join(name + ' TEXT' for name in PROVENANCE)
        self.db.executescript(f'''
        CREATE TABLE cti_mapping_datasets (source_id TEXT PRIMARY KEY,source_version TEXT,source_url TEXT,
            source_sha256 TEXT,counts_json TEXT,imported_at TEXT);
        CREATE TABLE cti_mapping_imports (source_id TEXT,source_version TEXT,source_url TEXT,
            source_sha256 TEXT,counts_json TEXT,PRIMARY KEY(source_id,source_sha256));
        CREATE TABLE vuln_attack_mappings (id INTEGER PRIMARY KEY,cve_id TEXT,cwe_id TEXT,
            attack_id TEXT,attack_name TEXT,mapping_level TEXT,mapping_source TEXT,confidence REAL,
            rationale TEXT,is_active INTEGER,{common},UNIQUE(source_dataset,record_key));
        CREATE TABLE capec_cwe_mappings (id INTEGER PRIMARY KEY,capec_id TEXT,cwe_id TEXT,
            mapping_type TEXT,is_active INTEGER,{common},UNIQUE(source_dataset,record_key),UNIQUE(capec_id,cwe_id));
        CREATE TABLE capec_attack_mappings (id INTEGER PRIMARY KEY,capec_id TEXT,attack_id TEXT,
            attack_name TEXT,confidence REAL,rationale TEXT,is_active INTEGER,{common},UNIQUE(source_dataset,record_key));
        CREATE TABLE capec_patterns (id INTEGER PRIMARY KEY,capec_id TEXT UNIQUE,name TEXT,
            abstraction TEXT,status TEXT,description TEXT,likelihood TEXT,severity TEXT,
            prerequisites TEXT,mitigations TEXT);
        INSERT INTO vuln_attack_mappings (id,cwe_id,attack_id,is_active,mapping_source) VALUES (40,'CWE-89','T1190',1,'seed');
        ''')
        self.cursor = SqlCursor(self.db)

    def test_ctid_preserves_multiple_relationship_types_and_references(self):
        d = parse_dataset('ctid-cve-attack', ctid(), SOURCES['ctid-cve-attack'])
        rows = list(d['rows']['vuln_attack_mappings'].values())
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['relationship_type'] for r in rows}, {'primary_impact','exploitation_technique'})
        self.assertEqual(json.loads(rows[0]['references_json']), ['https://example.org/report'])
        self.assertEqual(rows[0]['source_sha256'], d['sha256'])

    def test_capec_normalizes_ids_and_excludes_deprecated_patterns(self):
        d = parse_dataset('mitre-capec', XML, SOURCES['mitre-capec'])
        self.assertEqual(d['counts']['capec_cwe_mappings'], 1)
        row = next(iter(d['rows']['capec_attack_mappings'].values()))
        self.assertEqual(row['attack_id'], 'T1190')
        self.assertEqual(row['capec_id'], 'CAPEC-100')
        self.assertEqual(row['publisher_status'], 'Draft')
        self.assertEqual(d['counts']['capec_patterns'], 1)
        pattern = d['rows']['capec_patterns']['CAPEC-100']
        self.assertEqual(pattern['name'], 'Example')
        self.assertEqual(pattern['abstraction'], 'Standard')
        self.assertEqual(pattern['description'], 'Nested pattern description.')
        self.assertEqual(pattern['likelihood'], 'High')
        self.assertEqual(pattern['severity'], 'Medium')
        self.assertEqual(pattern['prerequisites'], 'First prerequisite.\n\nSecond prerequisite.')
        self.assertEqual(pattern['mitigations'], 'Validate input.')

    def test_capec_keeps_patterns_without_cwe_or_attack_mappings(self):
        xml = b'''<Attack_Pattern_Catalog xmlns="http://capec.mitre.org/capec-3" Version="3.9">
          <Attack_Patterns><Attack_Pattern ID="2" Name="Independent pattern" Status="Stable"/>
          </Attack_Patterns></Attack_Pattern_Catalog>'''
        d = parse_dataset('mitre-capec', xml, SOURCES['mitre-capec'])
        with self.db:
            result = import_dataset(self.cursor, d)
        self.assertEqual(result['patterns_updated'], 1)
        self.assertEqual(self.db.execute('SELECT name FROM capec_patterns').fetchone()[0], 'Independent pattern')

    def test_same_hash_backfills_old_catalog_without_rewriting_mapping_rows(self):
        dataset = parse_dataset('mitre-capec', XML, SOURCES['mitre-capec'])
        legacy = copy.deepcopy(dataset)
        del legacy['rows']['capec_patterns']
        del legacy['counts']['capec_patterns']
        with self.db:
            import_dataset(self.cursor, legacy)
        mappings_before = list(self.db.execute('SELECT * FROM capec_attack_mappings'))
        with self.db:
            result = import_dataset(self.cursor, dataset)
        self.assertFalse(result['unchanged'])
        self.assertEqual(result['patterns_updated'], 1)
        self.assertEqual(mappings_before, list(self.db.execute('SELECT * FROM capec_attack_mappings')))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cti_mapping_imports').fetchone()[0], 1)
        counts = json.loads(self.db.execute('SELECT counts_json FROM cti_mapping_datasets').fetchone()[0])
        self.assertEqual(counts['capec_patterns'], 1)
        before = self.db.total_changes
        with self.db:
            self.assertTrue(import_dataset(self.cursor, dataset)['unchanged'])
        self.assertEqual(self.db.total_changes, before + 1)  # Existing dataset lock-row upsert only.
        with self.db:
            self.db.execute("UPDATE capec_patterns SET description=NULL")
            result = import_dataset(self.cursor, dataset)
        self.assertEqual(result['patterns_updated'], 1)
        self.assertEqual(self.db.execute('SELECT description FROM capec_patterns').fetchone()[0], 'Nested pattern description.')

    def test_failed_capec_import_rolls_back_metadata_and_relations_together(self):
        broken = parse_dataset('mitre-capec', XML, SOURCES['mitre-capec'])
        next(iter(broken['rows']['capec_attack_mappings'].values()))['invalid_column'] = 1
        with self.assertRaises(sqlite3.OperationalError), self.db:
            import_dataset(self.cursor, broken)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM capec_patterns').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM capec_cwe_mappings').fetchone()[0], 0)

    def test_untrusted_endpoints_xml_entities_and_wrong_schema_are_rejected(self):
        for url in ['http://capec.mitre.org/data/xml/a.xml','https://evil.test/data.xml',
                    'https://capec.mitre.org.evil.test/data/xml/a.xml']:
            with self.assertRaises(ValueError): validate_source_url('mitre-capec',url)
        for data in [b'<!DOCTYPE root><root/>', b'<root/>']:
            with self.assertRaises(ValueError): parse_dataset('mitre-capec',data,SOURCES['mitre-capec'])
        with self.assertRaises(ValueError): parse_dataset('ctid-cve-attack',ctid('TA0001'),SOURCES['ctid-cve-attack'])

    def test_repeat_import_is_idempotent_and_refresh_retires_only_source_owned_rows(self):
        first = parse_dataset('ctid-cve-attack',ctid(),SOURCES['ctid-cve-attack'])
        with self.db: result = import_dataset(self.cursor,first)
        self.assertFalse(result['unchanged'])
        ids = [r[0] for r in self.db.execute('SELECT id FROM vuln_attack_mappings ORDER BY id')]
        with self.db: self.assertTrue(import_dataset(self.cursor,first)['unchanged'])
        self.assertEqual(ids,[r[0] for r in self.db.execute('SELECT id FROM vuln_attack_mappings ORDER BY id')])
        changed = parse_dataset('ctid-cve-attack',ctid('T1059'),SOURCES['ctid-cve-attack'])
        with self.db: import_dataset(self.cursor,changed)
        self.assertEqual(self.db.execute('SELECT is_active FROM vuln_attack_mappings WHERE id=40').fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM vuln_attack_mappings WHERE source_dataset IS NOT NULL AND is_active=1").fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cti_mapping_imports').fetchone()[0],2)

    def test_capec_manual_pair_is_preserved_and_failed_transaction_rolls_back(self):
        self.db.execute("INSERT INTO capec_cwe_mappings (capec_id,cwe_id,is_active) VALUES ('CAPEC-100','CWE-89',0)")
        self.db.commit()
        d = parse_dataset('mitre-capec',XML,SOURCES['mitre-capec'])
        with self.db: result = import_dataset(self.cursor,d)
        self.assertEqual(result['preserved_manual_rows'],1)
        self.assertEqual(self.db.execute('SELECT is_active FROM capec_cwe_mappings').fetchone()[0],0)
        self.db.execute('DELETE FROM cti_mapping_datasets'); self.db.commit()
        broken = copy.deepcopy(d)
        next(iter(broken['rows']['capec_attack_mappings'].values()))['bad_column'] = 1
        with self.assertRaises(sqlite3.OperationalError), self.db:
            import_dataset(self.cursor,broken)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cti_mapping_datasets').fetchone()[0],0)


if __name__ == '__main__': unittest.main()
