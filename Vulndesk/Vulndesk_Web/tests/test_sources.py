"""Exercise real registry SQL against a persistent SQLite fixture, plus the HTTP boundary.

SQLite translates only placeholders and FOR UPDATE; MariaDB locking and deployment
are deliberately not claimed by this offline suite.
"""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager, closing
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Adapter, AppError
from server import DEFAULTS, make_handler


class SqlCursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, sql, params=()):
        sql = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        values = [str(value) if isinstance(value, Decimal) else value for value in params]
        self.cursor.execute(sql, values)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]


class SourceFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "registry.sqlite"
        self.adapter = Adapter({**DEFAULTS, "vulndesk_root": self.temp.name, "service_ports": dict(DEFAULTS["service_ports"])}, self.temp.name)
        self.adapter.environment = lambda: {"NVD_API_KEY": "SECRET_VALUE_NEVER_RETURNED"}
        self.adapter.database = self.database
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript("""
              CREATE TABLE cti_source_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT UNIQUE COLLATE NOCASE,protocol TEXT,
                endpoint_ref TEXT,credential_ref TEXT,incremental_strategy TEXT,freshness_sla_seconds INTEGER,
                criticality NUMERIC,rate_limit_per_window INTEGER,rate_window_seconds INTEGER,max_payload_bytes INTEGER,
                trust_tier TEXT,config_json TEXT,enabled INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT);
              CREATE TABLE cti_source_state (
                source_id TEXT UNIQUE,status TEXT,watermark_value TEXT,last_success_at TEXT,last_attempt_at TEXT,
                failure_count INTEGER,circuit_state TEXT,health_score NUMERIC,next_retry_at TEXT);
              CREATE TABLE vulnerabilities (id INTEGER PRIMARY KEY,cve_id TEXT);
              INSERT INTO vulnerabilities VALUES(1,'CVE-TEST-PRESERVED');
            """)

    @contextmanager
    def database(self, write=False):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield SqlCursor(connection)
            connection.commit() if write else connection.rollback()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def body(source_id="mirror-cve", **overrides):
        return {"source_id": source_id, "display_name": "CVE mirror", "adapter_type": "nvd-cve",
                "endpoint_ref": "https://cti.example.org/cves/2.0", "credential_ref": "env:NVD_API_KEY",
                "enabled": True, "auth_mode": "api-key", **overrides}

    def update_body(self, source_id="mirror-cve", **overrides):
        row = self.adapter.source_detail(source_id)
        return self.body(source_id, expected_revision=row["revision"], **overrides)


class SourceTests(SourceFixture, unittest.TestCase):
    def test_empty_registry_lists_all_builtin_api_templates(self):
        data = self.adapter.sources({})
        self.assertEqual(data["items"], [])
        self.assertEqual({t["source_id"] for t in data["templates"]}, {"nvd-cve", "nvd-cpe", "mitre-attack", "mitre-cwe", "ctid-cve-attack", "mitre-capec"})
        self.assertNotIn("SECRET_VALUE_NEVER_RETURNED", json.dumps(data))

    def test_mapping_sources_accept_official_endpoints_and_reject_other_hosts(self):
        from mapping_source_services import SOURCES
        for kind, endpoint in SOURCES.items():
            created = self.adapter.create_source(self.body(kind,adapter_type=kind,endpoint_ref=endpoint,
                                                         credential_ref=None,auth_mode='none'))
            self.assertTrue(created['source']['acquisition_supported'])
        with self.assertRaises(AppError):
            self.adapter.create_source(self.body('bad-mapping',adapter_type='mitre-capec',
                endpoint_ref='https://evil.example/catalog.xml',credential_ref=None,auth_mode='none'))

    def test_create_read_update_and_reopen_persist_configuration(self):
        created = self.adapter.create_source(self.body())
        self.assertEqual(created["source"]["source_id"], "mirror-cve")
        self.assertTrue(created["source"]["credential_configured"])
        self.assertEqual(self.adapter.sources({})["total"], 1)
        body = self.update_body(endpoint_ref="https://new.example.org/nvd", display_name="Updated mirror", enabled=False, timeout_seconds=27)
        updated = self.adapter.update_source(body)["source"]
        self.assertNotEqual(updated["revision"], created["source"]["revision"])
        self.assertFalse(updated["enabled"])
        # Each database() call opens a new connection; detail verifies persistence beyond the write connection.
        saved = self.adapter.source_detail("mirror-cve")
        self.assertEqual(saved["endpoint_url"], "https://new.example.org/nvd")
        self.assertEqual(saved["timeout_seconds"], 27)
        self.assertEqual(saved["display_name"], "Updated mirror")
        with closing(sqlite3.connect(self.path)) as connection, connection:
            config = json.loads(connection.execute("SELECT config_json FROM cti_source_registry").fetchone()[0])
        self.assertTrue(config["bounded_agent_refresh"])

    def test_duplicate_id_is_409_including_database_case_collation(self):
        self.adapter.create_source(self.body())
        for source_id in ["mirror-cve", "MIRROR-CVE"]:
            with self.subTest(source_id=source_id), self.assertRaises(AppError) as error:
                self.adapter.create_source(self.body(source_id))
            self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.adapter.sources({})["total"], 1)

    def test_stale_edit_and_delete_are_rejected_without_lost_updates(self):
        self.adapter.create_source(self.body())
        stale = self.update_body()
        self.adapter.update_source({**stale, "display_name": "Other operator edit"})
        with self.assertRaises(AppError) as error:
            self.adapter.update_source(stale)
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(AppError) as error:
            self.adapter.delete_source({"source_id": "mirror-cve", "expected_revision": stale["expected_revision"], "confirm": True})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.adapter.source_detail("mirror-cve")["display_name"], "Other operator edit")

    def test_delete_requires_confirmation_and_preserves_cti_and_source_history(self):
        self.adapter.create_source(self.body())
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO cti_source_state(source_id,status,watermark_value) VALUES(?,?,?)", ("mirror-cve", "SUCCESS", "old-cursor"))
        body = {"source_id": "mirror-cve", "expected_revision": self.adapter.source_detail("mirror-cve")["revision"], "confirm": False}
        with self.assertRaises(AppError):
            self.adapter.delete_source(body)
        self.adapter.delete_source({**body, "confirm": True})
        with self.assertRaises(AppError) as error:
            self.adapter.source_detail("mirror-cve")
        self.assertEqual(error.exception.status, 404)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            self.assertEqual(connection.execute("SELECT cve_id FROM vulnerabilities").fetchone()[0], "CVE-TEST-PRESERVED")
            self.assertEqual(connection.execute("SELECT watermark_value FROM cti_source_state").fetchone()[0], "old-cursor")

    def test_invalid_fields_fail_before_any_write(self):
        examples = [dict(endpoint_ref="http://cti.example.org/feed"), dict(endpoint_ref="https://localhost/feed"),
            dict(endpoint_ref="https://127.0.0.1/feed"), dict(endpoint_ref="https://cti.example.org/?api_key=PRIVATE"),
            dict(endpoint_ref="https://user:PRIVATE@cti.example.org/feed"), dict(source_id="bad id"), dict(enabled="true"),
            dict(adapter_type="unimplemented"), dict(criticality="NaN"), dict(criticality=1.1), dict(timeout_seconds=301),
            dict(max_pages=0), dict(page_size=2001), dict(credential_ref="PRIVATE-RAW-KEY"), dict(credential_ref="env:DB_PASSWORD"),
            dict(auth_mode="bearer"), dict(api_key="PRIVATE"), dict(config_json={"api_key": "PRIVATE"})]
        for invalid in examples:
            with self.subTest(invalid=invalid), self.assertRaises(AppError):
                self.adapter.create_source(self.body(**invalid))
        self.assertEqual(self.adapter.sources({})["total"], 0)

    def test_legacy_reference_and_hidden_config_remain_compatible(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO cti_source_registry(source_id,protocol,endpoint_ref,credential_ref,config_json,enabled) VALUES(?,?,?,?,?,1)",
                ("nvd-cve", "REST_JSON", "config:NVD_CVE_API", "secret-ref:NVD_API_KEY", json.dumps({"semantic_role":"vulnerability_source", "api_key":"LEGACY_SECRET", "internal_note":"KEEP"})))
        row = self.adapter.source_detail("nvd-cve")
        self.assertEqual(row["endpoint_url"], "https://services.nvd.nist.gov/rest/json/cves/2.0")
        self.assertTrue(row["acquisition_supported"])
        self.assertNotIn("LEGACY_SECRET", json.dumps(row))
        self.adapter.update_source(self.update_body("nvd-cve"))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            config = json.loads(connection.execute("SELECT config_json FROM cti_source_registry").fetchone()[0])
            self.assertEqual(config["internal_note"], "KEEP")
        self.assertNotIn("LEGACY_SECRET", json.dumps(self.adapter.sources({})))

    def test_filters_pagination_health_and_search_injection(self):
        for i in range(12):
            self.adapter.create_source(self.body(f"mirror-{i:02}", enabled=i%2==0))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO cti_source_state(source_id,status,failure_count,circuit_state) VALUES('mirror-00','FAILED',2,'OPEN')")
        data = self.adapter.sources({"enabled": "1", "limit": "3", "page": "2"})
        self.assertEqual((data["total"], len(data["items"]), data["page"]), (6, 3, 2))
        self.assertEqual(data["stats"]["attention"], 1)
        self.assertEqual(self.adapter.sources({"search":"';DROP TABLE cti_source_registry;--"})["total"], 0)
        self.assertEqual(self.adapter.sources({"search":"mirror-11"})["total"], 1)
        self.assertEqual(self.adapter.sources({})["total"], 12)

    def test_registry_only_source_can_be_saved_but_cannot_start_acquisition(self):
        self.adapter.create_source(self.body(adapter_type="registry-only", credential_ref="", auth_mode="none"))
        self.adapter.upstream = MagicMock()
        with self.assertRaises(AppError) as error:
            self.adapter.start_mission({"mission_id":"m-test","scope_contract_id":"s-1","source_id":"mirror-cve"})
        self.assertEqual(error.exception.status, 409)
        self.adapter.upstream.assert_not_called()

    def test_enabled_custom_source_uses_governed_mission_route(self):
        self.adapter.create_source(self.body())
        self.adapter.mission = MagicMock(side_effect=AppError("missing",404))
        self.adapter.upstream = MagicMock(return_value={"status":"accepted","mission_id":"m-custom"})
        self.adapter.start_mission({"mission_id":"m-custom","scope_contract_id":"scope-1","source_id":"mirror-cve"})
        service,path,payload=self.adapter.upstream.call_args.args
        self.assertEqual((service,path),("cti","/api/cti/missions/start"))
        self.assertEqual(payload["cti_source_set"],["mirror-cve"])
        self.assertEqual(payload["policy_context"]["governance_authority"],"aptsGSS")
        self.assertNotIn("decision",payload)

    def test_adapter_change_clears_only_stale_parameters(self):
        self.adapter.create_source(self.body(keyword="ignored",max_pages=5,page_size=400))
        body=self.update_body(adapter_type="mitre-cwe",cwe_id="CWE-79",auth_mode="none",credential_ref="")
        self.adapter.update_source(body)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            config=json.loads(connection.execute("SELECT config_json FROM cti_source_registry").fetchone()[0])
        self.assertEqual(config["cwe_id"],"CWE-79")
        self.assertNotIn("max_pages",config)
        self.assertNotIn("page_size",config)


class SourceHttpTests(SourceFixture, unittest.TestCase):
    # Reuse only the fixture, not the inherited test suite.
    def setUp(self):
        super().setUp()
        self.httpd=ThreadingHTTPServer(("127.0.0.1",0),lambda *a,**kw:None)
        self.port=self.httpd.server_address[1]
        handler=make_handler(self.adapter,"test-csrf","live",self.port)
        handler.log_message=lambda *args:None
        self.httpd.RequestHandlerClass=handler
        self.thread=threading.Thread(target=self.httpd.serve_forever,daemon=True)
        self.thread.start()
        self.url=f"http://127.0.0.1:{self.port}"
        self.addCleanup(self.finish_http)

    def finish_http(self):
        self.httpd.shutdown();self.httpd.server_close();self.thread.join(timeout=2)

    def request(self,path,body=None,csrf=True):
        headers={"Content-Type":"application/json","Origin":self.url}
        if csrf: headers["X-Vulndesk-CSRF"]="test-csrf"
        request=Request(self.url+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
        try: response=urlopen(request,timeout=3)
        except HTTPError as error: response=error
        with response: return response.status,json.loads(response.read())

    def test_http_roundtrip_and_csrf_boundary(self):
        self.assertEqual(self.request('/api/sources/create',self.body(),csrf=False)[0],403)
        status,data=self.request('/api/sources/create',self.body())
        self.assertEqual(status,200)
        self.assertEqual(self.request('/api/sources?search=mirror')[1]['total'],1)
        status,row=self.request('/api/sources/mirror-cve')
        self.assertEqual(status,200)
        status,data=self.request('/api/sources/update',self.body(expected_revision=row['revision'],display_name='HTTP edit'))
        self.assertEqual(status,200)
        row=data['source']
        self.assertEqual(self.request('/api/sources/delete',{'source_id':row['source_id'],'expected_revision':row['revision'],'confirm':True})[0],200)
        self.assertEqual(self.request('/api/sources/mirror-cve')[0],404)


if __name__ == '__main__':
    unittest.main()
