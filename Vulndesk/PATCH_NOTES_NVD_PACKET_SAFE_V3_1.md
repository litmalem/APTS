# VulnDesk NVD packet-safe sync V3.1

## Fix

The V3 manual migration defined `vulnerability_id` as signed `INT`, while the
existing VulnDesk schema defines `vulnerabilities.id` as `BIGINT(20) UNSIGNED`.
MariaDB requires both sides of a foreign key to match exactly, including the
`UNSIGNED` attribute, so the FK creation failed with errno 150.

V3.1 changes both the migration and SQLAlchemy model to use a MySQL-specific
`BIGINT UNSIGNED` type while retaining SQLite `INTEGER` behavior for tests.

## Installation

1. Back up the database.
2. Run `NVD_RAW_JSON_CHUNKS_MIGRATION.sql`.
3. Confirm `SHOW CREATE TABLE vulnerability_raw_json_chunks` succeeds.
4. Replace the application source with V3.1.
5. Restart VulnDesk and resume Full Sync.

The checkpoint was not advanced for the failed NVD page, so the application
will retry it safely. Existing CVEs with an equal or newer `modified_at` are
skipped.
