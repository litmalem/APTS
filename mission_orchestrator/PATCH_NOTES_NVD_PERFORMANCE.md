# VulnDesk NVD Synchronization Performance Patch

## Changes

1. **NVD API key enabled through `.env`**
   - The key is loaded from the application directory in both source and PyInstaller builds.
   - `.env.example` intentionally contains no credential.
   - `.env` remains excluded by `.gitignore`.

2. **Persistent, rate-aware NVD HTTP client**
   - Reuses one `requests.Session` and HTTP connection pool.
   - Does not sleep before the first request.
   - Enforces the configured start-to-start interval for subsequent requests.
   - Preserves exponential backoff and `Retry-After` handling.

3. **Bulk database synchronization**
   - Maps a page first and writes it in configurable chunks.
   - Loads existing CVE IDs and modification times in one query per chunk.
   - Inserts/updates parent rows with executemany/bulk operations.
   - Deletes child rows once per table for the changed CVE set.
   - Bulk inserts CVSS, CWE links, references, and CPE matches.
   - Loads and creates CWE catalog rows in batches.

4. **Skip unchanged or older records**
   - A CVE is skipped when the local `modified_at` is equal to or newer than the NVD record.
   - Timestamps are normalized to UTC, timezone-naive, second precision to match the MariaDB `DATETIME` schema.
   - The UI now displays `skipped` counts.

5. **Reduced savepoint overhead**
   - Uses one savepoint per database batch instead of one per CVE.
   - If a batch fails, VulnDesk falls back to isolated CVE processing so one malformed record does not stop the page.

6. **Duplicate-index cleanup**
   - At startup, exact duplicate indexes from the supplied legacy schema are removed only when their retained counterpart exists.
   - The migration is restricted to MySQL/MariaDB and is idempotent.

## New configuration

```env
NVD_DB_BATCH_SIZE=250
NVD_SKIP_UNCHANGED=true
```

`NVD_DB_BATCH_SIZE` may be lowered if the database has a very small packet limit, or raised toward 500 after monitoring memory and transaction size.

## Validation performed

- Python compilation for the full source tree.
- SQLite integration test covering bulk insert, unchanged skip, update, child replacement, CWE reuse, and older-record skip.
- API configuration loading test.

A live NVD request could not be completed from the isolated build environment because outbound access timed out. The application retains normal timeout, retry, HTTP status, and authentication-error reporting for execution on the target machine.
