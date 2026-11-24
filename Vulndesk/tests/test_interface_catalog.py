from __future__ import annotations

import unittest
from unittest.mock import patch

from cti_services.interface_catalog import consumed_interfaces, provided_interfaces


class InterfaceCatalogTests(unittest.TestCase):
    def test_provided_interfaces_use_runtime_host_and_port(self):
        rows = provided_interfaces(host="0.0.0.0", port=9999)
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(row.direction == "PROVIDED" for row in rows))
        self.assertTrue(all(row.host == "0.0.0.0" for row in rows))
        self.assertTrue(all(row.port == 9999 for row in rows))
        self.assertTrue(any("/api/cti/events/publish" in row.interface for row in rows))
        self.assertTrue(any("Pentest Subsystem" in row.peer for row in rows))

    def test_consumed_interfaces_reflect_effective_configuration(self):
        with patch("cti_services.interface_catalog.Config.GOVERNANCE_BASE_URL", "http://10.10.10.10:18770"), \
             patch("cti_services.interface_catalog.Config.DB_HOST", "db.local"), \
             patch("cti_services.interface_catalog.Config.DB_PORT", 13307), \
             patch("cti_services.interface_catalog.Config.DB_NAME", "vulndesk_test"):
            rows = consumed_interfaces()

        governance = next(row for row in rows if "GovernanceClient" in row.entity)
        database = next(row for row in rows if row.protocol == "MYSQL/TCP")
        self.assertEqual(governance.host, "10.10.10.10")
        self.assertEqual(governance.port, 18770)
        self.assertIn("authorization/evaluate", governance.interface)
        self.assertEqual(database.host, "db.local")
        self.assertEqual(database.port, 13307)
        self.assertIn("vulndesk_test", database.peer)

    def test_https_external_apis_resolve_to_443(self):
        rows = consumed_interfaces()
        external_https = [row for row in rows if row.protocol == "HTTPS"]
        self.assertGreaterEqual(len(external_https), 4)
        self.assertTrue(all(row.port == 443 for row in external_https))
        peers = " ".join(row.peer for row in external_https)
        self.assertIn("NVD CVE", peers)
        self.assertIn("NVD CPE", peers)
        self.assertIn("ATT&CK", peers)
        self.assertIn("CWE", peers)


if __name__ == "__main__":
    unittest.main()
