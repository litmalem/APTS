"""Selective deletion tests use an isolated SQLite fixture, never a live database."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import threading
import time
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch

import reset_apts
import reset_vulndesk as reset
import server


class Connection:
    def __init__(self, db): self.db=db
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def exec_driver_sql(self,sql):
        if sql=='SHOW TABLES':
            return self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        cursor=self.db.execute(sql)
        class Result:
            def scalar_one(self):return cursor.fetchone()[0]
        return Result()


class Raw:
    def __init__(self,db):self.db=db
    def cursor(self):return self
    def execute(self,sql):
        if not sql.startswith('SET FOREIGN_KEY_CHECKS='):self.db.execute(sql)
    def commit(self):self.db.commit()
    def rollback(self):self.db.rollback()
    def close(self):pass


class Engine:
    def __init__(self,db):self.db=db
    def connect(self):return Connection(self.db)
    def raw_connection(self):return Raw(self.db)


class EnrichmentResetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.backup=self.root/'backup';self.backup.mkdir()
        (self.backup/'vulndesk-operational-before.sql').write_text('-- synthetic backup\n')
        self.uploads=self.root/'uploads';self.uploads.mkdir()
        (self.uploads/'keep.csv').write_text('catalog data')
        db=sqlite3.connect(':memory:');self.db=db;self.addCleanup(db.close)
        for table,count in [('cti_wpt_verified_evidence',2),('cti_missions',3),('target_cpe_candidates',4),('nvd_catalog',5)]:
            db.execute('CREATE TABLE '+table+' (id INTEGER PRIMARY KEY, value TEXT)')
            db.executemany('INSERT INTO '+table+' VALUES (?,?)',[(i,'keep-'+str(i)) for i in range(count)])
        db.commit()
        uploads=self.uploads;root=self.root
        class Config:
            DB_NAME='synthetic'
            @staticmethod
            def upload_dir():return str(uploads)
            @staticmethod
            def app_base_dir():return str(root)
        loader=patch.object(reset,'_load',return_value=(Engine(db),Config))
        loader.start();self.addCleanup(loader.stop)
        self.preview=reset.preview()
        self.plan={'modules':{'Vulndesk':self.preview,'Mission/Pentest/Execution/WPT':[],'GSS':[]}}

    def rows(self,table):return list(self.db.execute('SELECT * FROM '+table))

    def test_preview_partitions_without_double_counting(self):
        p=self.preview
        self.assertEqual(p['enrichment_tables'],[{'table':'cti_wpt_verified_evidence','rows':2}])
        self.assertNotIn('cti_wpt_verified_evidence',[r['table'] for r in p['operational_tables']])
        self.assertEqual(sum(r['rows'] for r in p['tables']),sum(r['rows'] for r in p['enrichment_tables']+p['operational_tables']))

    def test_enrichment_only_clears_evidence_and_preserves_other_rows_and_files(self):
        before={name:self.rows(name) for name in ('cti_missions','target_cpe_candidates','nvd_catalog')}
        result=reset.apply(self.backup,{'delete_cti_enrichment':True,'delete_database':False,'delete_uploads':False})
        self.assertEqual(result['rows_removed'],2)
        self.assertEqual(self.rows('cti_wpt_verified_evidence'),[])
        for name,rows in before.items():self.assertEqual(self.rows(name),rows)
        self.assertEqual((self.uploads/'keep.csv').read_text(),'catalog data')
        self.assertEqual(result['uploaded_files_removed'],0)

    def test_other_operational_scope_preserves_enrichment(self):
        before=self.rows('cti_wpt_verified_evidence')
        reset.apply(self.backup,{'delete_database':True,'delete_cti_enrichment':False,'delete_uploads':False})
        self.assertEqual(self.rows('cti_wpt_verified_evidence'),before)
        self.assertEqual(self.rows('cti_missions'),[])
        self.assertEqual(len(self.rows('nvd_catalog')),5)

    def test_combined_scopes_delete_each_table_once(self):
        result=reset.apply(self.backup,{'delete_database':True,'delete_cti_enrichment':True,'delete_uploads':False})
        self.assertEqual(result['rows_removed'],9)
        self.assertEqual(len(result['tables']),3)

    def test_empty_explicit_selection_does_not_delete(self):
        result=reset.apply(self.backup,{})
        self.assertEqual(result['rows_removed'],0)
        self.assertEqual(len(self.rows('cti_wpt_verified_evidence')),2)
        self.assertTrue((self.uploads/'keep.csv').is_file())

    def test_backup_required(self):
        (self.backup/'vulndesk-operational-before.sql').unlink()
        with self.assertRaisesRegex(RuntimeError,'backup'):
            reset.apply(self.backup,{'delete_cti_enrichment':True})
        self.assertEqual(len(self.rows('cti_wpt_verified_evidence')),2)

    def test_backend_and_cli_accept_enrichment_only(self):
        selected={'cti_enrichment':True}
        api=server._validate_reset_selection(self.plan,selected)
        cli=reset_apts._parse_selection(json.dumps(selected),[],self.preview)
        self.assertEqual(api,cli)
        self.assertTrue(api['cti_enrichment'])
        self.assertFalse(api['vulndesk'])
        self.assertFalse(api['gss'])
        self.assertFalse(api['vulndesk_uploads'])
        self.assertEqual(api['sqlite_databases'],[])

    def test_non_boolean_flag_is_rejected_in_all_layers(self):
        with self.assertRaises(ValueError):server._validate_reset_selection(self.plan,{'cti_enrichment':1})
        with self.assertRaises(ValueError):reset_apts._parse_selection('{"cti_enrichment":1}',[],self.preview)
        with self.assertRaises(ValueError):reset.apply(self.backup,{'delete_cti_enrichment':1})

    def test_missing_table_cannot_be_selected(self):
        self.preview['enrichment_tables']=[]
        with self.assertRaises(ValueError):server._validate_reset_selection(self.plan,{'cti_enrichment':True})
        with self.assertRaises(ValueError):reset_apts._parse_selection('{"cti_enrichment":true}',[],self.preview)

    def test_legacy_full_database_selection_includes_enrichment(self):
        selected=server._validate_reset_selection(self.plan,{'vulndesk':True})
        self.assertTrue(selected['cti_enrichment'])
        result=reset.apply(self.backup,{'delete_database':True,'delete_uploads':False})
        self.assertEqual(result['rows_removed'],9)

    def test_empty_ui_selection_is_rejected(self):
        with self.assertRaises(ValueError):server._validate_reset_selection(self.plan,{})
        with self.assertRaises(ValueError):reset_apts._parse_selection('{}',[],self.preview)

    def test_seven_scopes_validate_and_start_through_http_without_running_reset(self):
        databases=[str(self.root/('fixture-'+str(i)+'.db')) for i in range(5)]
        self.plan['modules']['Mission/Pentest/Execution/WPT']=[{'database':p,'tables':[]} for p in databases]
        selection={'sqlite_databases':databases,'gss':True,'vulndesk':False,'cti_enrichment':True,'vulndesk_uploads':False}
        panel=server.ControlCenterServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=panel.serve_forever,daemon=True).start()
        completed=threading.Event()
        try:
            with patch.dict(server.RESET_PLANS,{'synthetic':{'plan':self.plan,'expires':time.time()+60}},clear=True),patch.dict(server.RESET_STATE,{'status':'idle'},clear=True),patch.object(server,'_run_reset',side_effect=lambda *args:completed.set()) as worker:
                def post(path,body):
                    req=Request(f'http://127.0.0.1:{panel.server_port}'+path,data=json.dumps(body).encode(),headers={'X-Control-Token':server.TOKEN,'Content-Type':'application/json'})
                    with urlopen(req,timeout=10) as response:return json.load(response)
                result=post('/api/reset/validate',{'plan_id':'synthetic','selection':selection})
                self.assertEqual(result['selection'],selection)
                self.assertEqual(result['reset_contract'],server.RESET_CONTRACT)
                worker.assert_not_called()
                self.assertEqual(len(self.rows('cti_wpt_verified_evidence')),2)
                started=post('/api/reset/execute',{'plan_id':'synthetic','selection':selection,'confirmation':'HAPUS DATA APTS','backup_confirmed':True})
                self.assertEqual(started['status'],'running')
                self.assertTrue(completed.wait(2))
                worker.assert_called_once_with('synthetic',selection)
                self.assertEqual(len(self.rows('cti_wpt_verified_evidence')),2)
        finally:
            panel.shutdown();panel.server_close()

    @unittest.skipUnless(__import__('os').name=='nt','Windows exclusive binding')
    def test_second_panel_cannot_bind_same_port(self):
        first=server.ControlCenterServer(('127.0.0.1',0),server.Handler)
        try:
            with self.assertRaises(OSError):
                second=server.ControlCenterServer(('127.0.0.1',first.server_port),server.Handler)
                second.server_close()
        finally:first.server_close()


if __name__=='__main__':unittest.main()
