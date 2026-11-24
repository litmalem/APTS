"""Exercise inverse catalog joins against a relational fixture, including duplicate paths."""
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_cwe_attack_mapping as fixture
from backend import Adapter, AppError


class ReverseCursor(fixture.Cursor):
    def fetchone(self):
        row=self.result.fetchone()
        return dict(row) if row else None


class ReverseMappingTests(unittest.TestCase):
    def setUp(self):
        fixture.CweAttackMappingTests.setUp(self)
        for field,kind in [('description_text','TEXT'),('preferred_base_score','REAL'),
                           ('preferred_base_severity','TEXT'),('modified_at','TEXT')]:
            self.db.execute('ALTER TABLE vulnerabilities ADD COLUMN '+field+' '+kind)
        self.db.execute('CREATE TABLE attack_patterns (id INTEGER,attack_id TEXT,name TEXT,description_text TEXT,deprecated INTEGER,revoked INTEGER)')
        self.db.execute("INSERT INTO attack_patterns VALUES (1,'T1190','Exploit application','Context',0,0)")
        self.db.executescript('''
            INSERT INTO vuln_attack_mappings (id,cve_id,attack_id,confidence,is_active,mapping_level,source_dataset,source_version,relationship_type)
            VALUES (8,'CVE-2024-9999','T1190',0.75,1,'cve_to_attack','ctid-cve-attack','ATT&CK:16.1','primary_impact'),
                   (9,'CVE-2024-9999','T1190',0.75,1,'cve_to_attack','ctid-cve-attack','ATT&CK:16.1','exploitation_technique');
            INSERT INTO capec_cwe_mappings VALUES (1,'CWE-89','CAPEC-100',1),(2,'CWE-89','CAPEC-100',1);
            INSERT INTO capec_attack_mappings (id,capec_id,attack_id,confidence,is_active,source_dataset,source_version)
            VALUES (1,'CAPEC-100','T1190',0.6,1,'mitre-capec','CAPEC:3.9');
        ''')
        self.cursor=ReverseCursor(self.db)
        self.adapter=Adapter({'vulndesk_root':'.','service_ports':{}},'.')
        self.adapter.database=lambda:contextmanager(lambda:iter([self.cursor]))()
        self.changes=self.db.total_changes

    def test_unique_count_and_pagination_do_not_duplicate_multiple_paths(self):
        first=self.adapter.attack_vulnerabilities('T1190',{'limit':'2'})
        second=self.adapter.attack_vulnerabilities('T1190',{'limit':'2','page':'2'})
        self.assertEqual(first['total'],3)
        self.assertEqual([r['id'] for r in first['items']],[40,20])
        self.assertEqual([r['id'] for r in second['items']],[10])
        self.assertEqual(self.db.total_changes,self.changes)
        self.assertEqual(len(self.cursor.calls),10)  # One bounded batch per page, no per-CVE lookup.
        for row in first['items']+second['items']:
            self.assertEqual(row['mapping']['attack_id'],'T1190')
        self.assertEqual(len(second['items'][0]['mapping']['paths']),3)

    def test_kind_filters_keep_only_matching_paths_and_confidence(self):
        direct=self.adapter.attack_vulnerabilities('T1190',{'mapping_kind':'DIRECT_CVE'})
        self.assertEqual(direct['total'],1)
        self.assertEqual(direct['items'][0]['mapping']['mapping_status'],'CURATED')
        self.assertEqual(len(direct['items'][0]['mapping']['paths']),2)
        capec=self.adapter.attack_vulnerabilities('T1190',{'mapping_kind':'CAPEC'})
        self.assertEqual(capec['total'],1)
        m=capec['items'][0]['mapping']
        self.assertEqual(m['confidence'],0.6)
        self.assertEqual(m['mapping_status'],'INFERRED')
        self.assertEqual([p['mapping_kind'] for p in m['paths']],['CAPEC'])
        self.assertEqual(m['paths'][0]['source_version'],'CAPEC:3.9')
        self.assertEqual(self.adapter.attack_vulnerabilities('T1190',{'mapping_kind':'CWE_RULE'})['total'],2)

    def test_inactive_rules_and_inactive_capec_edges_are_excluded(self):
        self.db.execute('UPDATE capec_cwe_mappings SET is_active=0')
        self.assertEqual(self.adapter.attack_vulnerabilities('T1190',{'mapping_kind':'CAPEC'})['total'],0)
        self.db.execute('UPDATE vuln_attack_mappings SET is_active=0')
        result=self.adapter.attack_vulnerabilities('T1190',{'page':'99'})
        self.assertEqual((result['total'],result['page'],result['items']),(0,1,[]))

    def test_search_is_literal_and_values_are_bound(self):
        for text in ['%', '_', '=', "' OR 1=1 --"]:
            result=self.adapter.attack_vulnerabilities('T1190',{'search':text})
            self.assertEqual(result['total'],0)
        result=self.adapter.attack_vulnerabilities('T1190',{'search':'9999'})
        self.assertEqual([r['id'] for r in result['items']],[40])
        self.assertNotIn('9999',self.cursor.calls[-3][0])

    def test_validation_and_page_bounds(self):
        for attack,params in [("T1190';--",{}),('TA0001',{}),('T1190',{'mapping_kind':[]}),
                              ('T1190',{'search':'x'*101})]:
            with self.assertRaises(AppError):
                self.adapter._attack_vulnerabilities(self.cursor,attack,params)
        bounded=self.adapter.attack_vulnerabilities('T1190',{'page':'999999','limit':'999999'})
        self.assertEqual((bounded['page'],bounded['limit']),(1,50))

    def test_catalog_absence_is_distinct_from_absence_of_relations(self):
        self.db.execute("UPDATE attack_patterns SET attack_id='T9999'")
        result=self.adapter.attack_vulnerabilities('T1190',{})
        self.assertEqual(result['total'],3)
        self.assertNotIn('id',result['technique'])
        self.assertIn('belum ada',result['technique']['name'])

    def test_attack_catalog_detail_includes_first_inverse_page(self):
        row=self.adapter.data_detail('attack',1)
        self.assertEqual(row['related_vulnerabilities']['total'],3)
        self.assertEqual(row['attack_id'],'T1190')


if __name__=='__main__':unittest.main()
