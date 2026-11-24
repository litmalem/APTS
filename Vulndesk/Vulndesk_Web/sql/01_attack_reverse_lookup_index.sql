-- Cover the reverse CWE -> CVE join without fetching each association table row.
-- Existing indexes and data remain intact; MariaDB supports concurrent DML here.
ALTER TABLE vulnerability_cwes
    ADD INDEX IF NOT EXISTS idx_vc_cwe_vulnerability (cwe_catalog_id, vulnerability_id),
    ALGORITHM=INPLACE, LOCK=NONE;
