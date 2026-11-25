import base64
import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import Adapter, AppError, clean_result, query_plan
from server import DEFAULTS, make_handler


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.adapter = Adapter({**DEFAULTS, "vulndesk_root": self.temp.name, "service_ports": dict(DEFAULTS["service_ports"])}, self.temp.name)
        self.adapter.environment = lambda: {}
        self.adapter._wpt_pipeline_status = lambda *args: None

    def test_wpt_pipeline_status_uses_child_mission_and_distinguishes_empty_completed_stage(self):
        cursor=MagicMock()
        cursor.fetchone.return_value={'status':'COMPLETED','pipeline_mission_id':'ctiwpt-child','attempt_count':1,
            'summary_json':json.dumps({'vulnerability_correlations':0,'attack_mappings':0,'risk_priorities':0}),
            'stage_status_json':json.dumps({'vulnerability_correlation':'COMPLETED','attack_mapping':'COMPLETED','risk_prioritization':'COMPLETED','pip_assembly':'COMPLETED'})}
        self.adapter._downstream_stage_status=MagicMock(return_value=({'pip_assembly':'ASSEMBLED_WITH_EVIDENCE'},{}))
        status,details,job=Adapter._wpt_pipeline_status(self.adapter,cursor,'intake-one','a'*64)
        self.assertEqual(status['attack_mapping'],'COMPLETED')
        self.assertEqual(details['attack_mapping']['intake_record_count'],0)
        self.assertEqual(job['pipeline_mission_id'],'ctiwpt-child')
        self.adapter._downstream_stage_status.assert_called_once_with(cursor,'ctiwpt-child','intake-one','a'*64)

    def test_enrichment_returns_target_and_sort_is_allowlisted(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'total': 1}
        cursor.fetchall.return_value = [{'intake_id': 'one', 'result_json': json.dumps({
            'target': {'target_type': 'URL', 'target_value': 'http://localhost:3000/'},
            'technologies': [{'name': 'PHP', 'version': '8.4.27'}], 'technology_count': 1,
            'enrichment_version': 2, 'cpe_candidates': []})}]
        self.adapter.database = lambda: contextmanager(lambda: iter([cursor]))()
        result = self.adapter.enrichment_list({'search': "localhost';--", 'direction': 'asc'})
        self.assertEqual(result['items'][0]['target']['target_value'], 'http://localhost:3000/')
        sql, params = cursor.execute.call_args.args
        self.assertIn('ORDER BY e.created_at ASC, e.intake_id ASC', sql)
        self.assertNotIn("localhost';--", sql)
        self.assertEqual(params[:4], ["%localhost';--%"] * 4)
        self.adapter.enrichment_list({'direction': 'ASC; DROP TABLE x'})
        self.assertIn('e.created_at DESC', cursor.execute.call_args.args[0])

    def test_legacy_enrichment_does_not_invent_target_technology_or_stage_status(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'intake_id': 'old', 'result_json': json.dumps({
            'technology_count': 3, 'verified_vulnerability_count': 0})}
        self.adapter.database = lambda: contextmanager(lambda: iter([cursor]))()
        result = self.adapter.enrichment_detail('old')
        self.assertIsNone(result['target'])
        self.assertEqual(result['technologies'], [])
        self.assertEqual(result['pipeline_status'], {})
        self.assertEqual(result['evidence_status'], 'UNKNOWN')
        self.assertEqual(result['technology_count'], 3)

    def test_downstream_stage_status_is_derived_from_stage_tables(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {'intake_id': 'i1', 'mission_id': 'm1', 'evidence_manifest_sha256': 'abc', 'result_json': json.dumps({
                'pipeline_status': {'cpe_resolution': 'COMPLETED_WITH_CANDIDATES', 'vulnerability_correlation': 'NOT_RUN',
                                    'attack_mapping': 'NOT_RUN', 'risk_prioritization': 'NOT_RUN', 'pip_assembly': 'NOT_RUN'}})},
            {'n': 0}, {'n': 0}, {'n': 3}]
        cursor.fetchall.return_value = [{'revision_no': 1, 'readiness': 'PARTIAL', 'created_at': None,
                                         'has_intake': 0, 'has_manifest': 0}]
        self.adapter.database = lambda: contextmanager(lambda: iter([cursor]))()
        result = self.adapter.enrichment_detail('i1')
        status = result['pipeline_status']
        self.assertEqual(status['cpe_resolution'], 'COMPLETED_WITH_CANDIDATES')
        self.assertEqual(status['vulnerability_correlation'], 'NOT_RECORDED')
        self.assertEqual(status['attack_mapping'], 'NOT_RECORDED')
        self.assertEqual(status['risk_prioritization'], 'RECORDED_FOR_MISSION')
        self.assertEqual(status['pip_assembly'], 'ASSEMBLED_WITHOUT_EVIDENCE')
        self.assertEqual(result['pipeline_details']['pip_assembly']['latest_revision'], 1)
        cursor.fetchall.return_value = [{'revision_no': 2, 'readiness': 'READY', 'created_at': None, 'has_intake': 1, 'has_manifest': 0}]
        cursor.fetchone.side_effect = [
            {'intake_id': 'i1', 'mission_id': 'm1', 'evidence_manifest_sha256': 'abc', 'result_json': json.dumps({
                'pipeline_status': {'pip_assembly': 'NOT_RUN'}})}, {'n': 0}, {'n': 0}, {'n': 0}]
        self.assertEqual(self.adapter.enrichment_detail('i1')['pipeline_status']['pip_assembly'], 'ASSEMBLED_WITH_EVIDENCE')

    def test_downstream_lookup_failure_reports_unknown_not_hardcoded_not_run(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {'intake_id': 'i1', 'mission_id': 'm1', 'result_json': json.dumps({
            'pipeline_status': {'pip_assembly': 'NOT_RUN'}})}
        cursor.execute.side_effect = [None, RuntimeError('table missing')]
        self.adapter.database = lambda: contextmanager(lambda: iter([cursor]))()
        status = self.adapter.enrichment_detail('i1')['pipeline_status']
        self.assertEqual(status['pip_assembly'], 'UNKNOWN')
        self.assertEqual(status['vulnerability_correlation'], 'UNKNOWN')

    def test_search_and_sort_input_never_become_sql_identifiers(self):
        attack = "'; DROP TABLE vulnerabilities; --"
        count, sql, params, page, limit = query_plan("vulnerabilities", {"search": attack, "sort": attack, "limit": "999999", "page": "-1"})
        self.assertNotIn(attack, sql)
        self.assertNotIn(attack, count)
        self.assertTrue(all(v == "%" + attack + "%" for v in params))
        self.assertIn("ORDER BY v.id DESC", sql)
        self.assertEqual((page, limit), (1, 250))

    def test_unknown_catalog_and_bad_cvss_fail_before_connection(self):
        for dataset, args in [("secrets", {}), ("vulnerabilities", {"min": "NaN"}), ("vulnerabilities", {"max": "11"}), ("vulnerabilities", {"severity": "';--"})]:
            with self.subTest(dataset=dataset, args=args), self.assertRaises(AppError):
                query_plan(dataset, args)

    def test_cwe_filter_joins_actual_catalog_foreign_key(self):
        _, sql, params, _, _ = query_plan("vulnerabilities", {"cwe": "CWE-20", "has_cpe": "1", "year": "2026"})
        self.assertIn("cw.id=vc.cwe_catalog_id", sql)
        self.assertIn("cp.vulnerability_id=v.id", sql)
        self.assertEqual(params, ["2026-01-01", "2027-01-01", "CWE-20"])
        self.assertIn("cw.cwe_id=%s", sql)

    def test_cwe_filter_non_numeric_falls_back_to_partial_match(self):
        _, sql, params, _, _ = query_plan("vulnerabilities", {"cwe": "NVD-CWE-noinfo"})
        self.assertIn("cw.cwe_id LIKE %s", sql)
        self.assertEqual(params, ["%NVD-CWE-NOINFO%"])

    def test_read_queries_start_read_only_transaction_and_rollback(self):
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        fake = SimpleNamespace(connect=MagicMock(return_value=connection), cursors=SimpleNamespace(DictCursor=dict))
        with patch.dict(sys.modules, {"pymysql": fake}):
            with self.adapter.database() as handle:
                handle.execute("SELECT 1")
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "START TRANSACTION READ ONLY")
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()

    def test_unavailable_db_does_not_leak_dsn_or_password(self):
        fake = SimpleNamespace(connect=MagicMock(side_effect=RuntimeError("password=SUPER_SECRET")), cursors=SimpleNamespace(DictCursor=dict))
        with patch.dict(sys.modules, {"pymysql": fake}), self.assertRaises(AppError) as error:
            with self.adapter.database():
                pass
        self.assertNotIn("SUPER_SECRET", str(error.exception))

    def test_mission_wrapper_does_not_hide_running_state(self):
        self.adapter.upstream = MagicMock(return_value={"status": "completed", "mission": {"mission_id": "m-1", "status": "RUNNING"}})
        self.assertEqual(self.adapter.mission("m-1", "status")["status"], "RUNNING")

    def test_native_not_found_wrapper_becomes_404(self):
        self.adapter.upstream = MagicMock(return_value={"status": "completed", "mission": {"status": "NOT_FOUND"}})
        with self.assertRaises(AppError) as error:
            self.adapter.mission("m-1", "status")
        self.assertEqual(error.exception.status, 404)

    def test_mission_proposal_preserves_governance_boundary_and_is_not_repeated(self):
        self.adapter.source_detail = MagicMock(return_value={"enabled": True, "acquisition_supported": True, "endpoint_error": None})
        self.adapter.upstream = MagicMock(side_effect=[{"status": "completed", "mission": {"status": "NOT_FOUND"}}, {"status": "accepted", "mission_id": "m-new"}])
        body = {"mission_id": "m-new", "scope_contract_id": "scope-1", "source_id": "nvd-cve"}
        result = self.adapter.start_mission(body)
        self.assertEqual(result["status"], "accepted")
        service, path, payload = self.adapter.upstream.call_args.args
        self.assertEqual((service, path), ("cti", "/api/cti/missions/start"))
        self.assertEqual(payload["cti_source_set"], ["nvd-cve"])
        self.assertEqual(payload["cti_acquisition_max_actions"], 1)
        self.assertEqual(payload["assets"], [])
        self.assertNotIn("decision", payload)
        self.assertNotIn("command", payload)
        with self.assertRaises(AppError) as error:
            self.adapter.start_mission(body)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.adapter.upstream.call_count, 2)

    def test_mission_rejects_authorization_injection_and_disabled_governance(self):
        body = {"mission_id": "m-new", "scope_contract_id": "scope-1", "source_id": "nvd-cve"}
        self.adapter.upstream = MagicMock()
        with self.assertRaises(AppError):
            self.adapter.start_mission({**body, "policy_context": {"decision": "ALLOW"}})
        self.adapter.environment = lambda: {"GOVERNANCE_ENABLED": "false"}
        with self.assertRaises(AppError):
            self.adapter.start_mission(body)
        self.adapter.upstream.assert_not_called()

    def test_http_success_without_readiness_is_reachable(self):
        self.adapter.upstream = MagicMock(return_value={"status": "ok"})
        self.assertEqual(self.adapter._probe(("cti", "CTI"))["status"], "REACHABLE")
        self.adapter.upstream.return_value = {"status": "degraded", "readiness_status": "READY"}
        self.assertEqual(self.adapter._probe(("cti", "CTI"))["status"], "DEGRADED")

    def test_stop_rejects_external_process(self):
        with patch("backend.subprocess.Popen") as popen, self.assertRaises(AppError):
            self.adapter.stop_api()
        popen.assert_not_called()

    def test_start_rejects_occupied_port_without_launching(self):
        with patch("backend.socket.socket") as socket, patch("backend.subprocess.Popen") as popen:
            socket.return_value.__enter__.return_value.connect_ex.return_value = 0
            with self.assertRaises(AppError) as error:
                self.adapter.start_api()
            self.assertEqual(error.exception.status, 409)
            popen.assert_not_called()

    def test_stop_terminates_only_its_owned_child(self):
        child = MagicMock()
        child.poll.return_value = None
        self.adapter._child = child
        self.adapter.stop_api()
        child.terminate.assert_called_once()
        child.wait.assert_called_once()
        self.assertIsNone(self.adapter._child)

    def test_invalid_csv_does_not_touch_database(self):
        self.adapter.database = MagicMock()
        body = {"dataset_type": "tweet_topics", "file_name": "example.csv", "content_base64": base64.b64encode(b"Something\nabc\n").decode()}
        with self.assertRaises(AppError):
            self.adapter.import_dataset(body)
        self.adapter.database.assert_not_called()

    def test_delete_rejects_file_outside_upload_storage(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"id": 1, "row_count": 1, "stored_file_path": str(Path(self.temp.name) / "outside.csv")}]
        @contextmanager
        def fake_db(write=False):
            yield cursor
        self.adapter.database = fake_db
        with self.assertRaises(AppError):
            self.adapter.delete_dataset({"dataset_type": "tweet_topics", "upload_date": "2026-10-05", "confirm": True})
        self.assertEqual(cursor.execute.call_count, 1)

    def test_runtime_diagnostics_redact_credentials(self):
        result = clean_result({"source": {"api_key": "secret", "scope_contract_id": "s-1"}, "password": "secret"})
        self.assertEqual(result["source"]["scope_contract_id"], "s-1")
        self.assertNotIn("secret", json.dumps(result))


class HttpBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = SimpleNamespace(root=Path("/tmp/vulndesk"), ports=dict(DEFAULTS["service_ports"]), api_owned=False,
            summary=MagicMock(return_value={"counts": {}}), components=MagicMock(return_value={"items": []}),
            upstream=MagicMock(), data_detail=MagicMock(), data_list=MagicMock(return_value={"items": [], "total": 0}),
            mission=MagicMock(), toggle=MagicMock(return_value={"enabled": True}), start_mission=MagicMock(),
            import_dataset=MagicMock(), delete_dataset=MagicMock(), start_api=MagicMock(return_value={"message": "started"}), stop_api=MagicMock())
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **kw: None)
        cls.port = cls.httpd.server_address[1]
        handler = make_handler(cls.adapter, "test-session", "demo", cls.port)
        handler.log_message = lambda *a: None
        cls.httpd.RequestHandlerClass = handler
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.url + path, data=data, headers=headers or {}, method="GET" if body is None else "POST")
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, raw, response.headers

    def test_reverse_mapping_route_preserves_filters_and_rejects_invalid_paths(self):
        self.adapter.attack_vulnerabilities=MagicMock(return_value={'attack_id':'T1505.003','items':[],'total':0})
        status,raw,_=self.request('/api/attack/T1505.003/vulnerabilities?page=2&mapping_kind=CAPEC&search=CVE-2024')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['attack_id'],'T1505.003')
        self.adapter.attack_vulnerabilities.assert_called_once_with('T1505.003',{'page':'2','mapping_kind':'CAPEC','search':'CVE-2024'})
        self.assertEqual(self.request('/api/attack/T1190%27%3B/vulnerabilities')[0],404)
        self.assertEqual(self.request('/api/attack/T1190/vulnerabilities',headers={'Origin':'https://evil.example'})[0],403)

    def test_local_bootstrap_contains_only_session_config(self):
        status, raw, headers = self.request("/bootstrap.js")
        self.assertEqual(status, 200)
        self.assertIn(b'"local": true', raw)
        self.assertNotIn(b"DB_PASSWORD", raw)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_untrusted_host_is_denied(self):
        self.assertEqual(self.request("/api/config", headers={"Host": "evil.example"})[0], 403)

    def test_cross_origin_is_denied(self):
        self.assertEqual(self.request("/api/config", headers={"Origin": "https://evil.example"})[0], 403)

    def test_mutation_requires_session_token(self):
        self.assertEqual(self.request("/api/runtime/start", {}, {"Content-Type": "application/json"})[0], 403)

    def test_runtime_route_accepts_only_empty_body(self):
        headers = {"Content-Type": "application/json", "X-Vulndesk-CSRF": "test-session", "Origin": self.url}
        self.assertEqual(self.request("/api/runtime/start", {"command": "whoami"}, headers)[0], 400)
        self.assertEqual(self.request("/api/runtime/start", {}, headers)[0], 200)

    def test_traversal_and_arbitrary_proxy_are_denied(self):
        for path in ("/../config.json", "/%2e%2e/config.json", "/config.json", "/api/proxy?url=http://example.com"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)


if __name__ == "__main__":
    unittest.main()
