"""Ephemeral SQLite-backed server for UI tests; never connects to production services."""
import json
import signal
import threading
import unittest
from http.server import ThreadingHTTPServer

from test_sources import SourceFixture
from server import make_handler


class Fixture(SourceFixture, unittest.TestCase):
    def runTest(self):
        pass


def main():
    fixture = Fixture()
    fixture.setUp()
    adapter = fixture.adapter
    adapter.create_source(fixture.body("nvd-cve", display_name="NVD — Kerentanan CVE", endpoint_ref="https://services.nvd.nist.gov/rest/json/cves/2.0"))
    adapter.create_source(fixture.body("nvd-cpe", display_name="NVD — Kamus produk CPE", adapter_type="nvd-cpe", endpoint_ref="https://services.nvd.nist.gov/rest/json/cpes/2.0"))
    adapter.create_source(fixture.body("mitre-attack", display_name="MITRE ATT&CK", adapter_type="mitre-attack", endpoint_ref="https://attack-taxii.mitre.org/api/v21", auth_mode="none", credential_ref=""))
    adapter.create_source(fixture.body("community-example", display_name="Community CTI — contoh", adapter_type="registry-only", enabled=False, auth_mode="none", credential_ref=""))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **kw: None)
    port = httpd.server_address[1]
    handler = make_handler(adapter, "fixture-csrf", "live", port)
    handler.log_message = lambda *args: None
    httpd.RequestHandlerClass = handler
    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, lambda *args: threading.Thread(target=httpd.shutdown, daemon=True).start())
    print(json.dumps({"url": f"http://127.0.0.1:{port}", "synthetic_fixture": True}), flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        fixture.doCleanups()


if __name__ == "__main__":
    main()
