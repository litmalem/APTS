# CTI Component Manager — Interfaces & Ports

This patch adds an operational interface inventory to the **CTI Component Manager** without changing the CTI database schema.

## UI change

A new **Interfaces & Ports** tab contains two separate inventories:

1. **Port / Service Interface yang Disediakan VulnDesk**
   - VulnDesk Pentest Enrichment API listener (`CTI-INF01`).
   - Host/port are taken from the current UI/runtime values.
   - Logical consumers are shown explicitly: Pentest/mission orchestration clients, aptsGSS event publishing, and diagnostics/integration clients.
   - Endpoint groups such as mission start, enrichment, PIP retrieval, governance event ingress, health, architecture, and event trace are listed.

2. **Service Interface yang Digunakan VulnDesk**
   - aptsGSS Governance & Safety Plane (`GOV-PLANE`) including port and authorization endpoint.
   - MariaDB including effective host, port, and database name; credentials are never displayed.
   - NIST NVD CVE API.
   - NIST NVD CPE API.
   - MITRE ATT&CK TAXII API.
   - MITRE CWE REST API.

## Configuration behavior

The external interface catalog reads the effective `Config` values, so local `.env` changes such as:

- `DB_PORT=3307`
- `GOVERNANCE_BASE_URL=http://127.0.0.1:8770`
- source API URL overrides

are reflected automatically after restarting VulnDesk and pressing **Refresh Interfaces / Ports**.

The catalog never displays `DB_PASSWORD`, `NVD_API_KEY`, or other credentials.

## Files

- `cti_services/interface_catalog.py` — new declarative interface inventory.
- `cti_ui/service_manager_window.py` — adds the new tab and dynamic tables.
- `tests/test_interface_catalog.py` — catalog regression tests.

## No SQL migration

No database schema modification is required.
