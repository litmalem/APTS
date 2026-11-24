# APTS Mission Control — P1 Archive Mission + Archived filter

Source baseline: `Mission(20261010-051939).zip` (2026-10-10).

## Scope

This is a **non-destructive administrative archive**. It does not DELETE/UPDATE canonical mission identity, envelope, lifecycle state, transition, event, plan, or evidence records. Archive is not a mission lifecycle state, not Abort and not Purge. P2 Restore is not included.

- Mission UI: active / archived / all filter; archive button on terminal missions only, including dashboard and mission workspace.
- `GET /api/missions?visibility=ACTIVE|ARCHIVED|ALL`; default `ALL` retains compatibility for existing clients.
- `GET /api/missions/{mission_id}/archive` returns archive status.
- `POST /api/missions/{mission_id}/archive` archives the terminal mission; protected by required `X-Mission-Archive-Token` (environment variable `MISSION_ARCHIVE_ADMIN_TOKEN`).
- Dashboard uses operational (not archived) metrics, also displays historical and archived counts; Requires Attention excludes archived missions.
- Two additive tables are auto-created by `MissionRepository.ensure_schema()` for SQLite and MariaDB/MySQL: `mission_archive_state` and append-only `mission_archive_history`.
- Rejected conditions: nonterminal mission, changed state version, duplicate/archive already archived, missing or incorrect token, malformed input. Requests include audit reason and idempotency key; archive records maintain per-mission hash continuity.

## Install on Windows PowerShell

1. **Back up your working repository and database, and stop Mission API / APTS Control Center processes.**
2. Extract this patch to a temporary folder, for example `D:\APTS_Archive_Mission_P1_Patch`.
3. In PowerShell, run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass -Force
   & 'D:\APTS_Archive_Mission_P1_Patch\INSTALL_APTS_ARCHIVE_P1.ps1' -MissionRoot 'D:\mission_orchestrator'
   ```

   This copies **only eight named source/test files** into the existing tree and backs up overwritten source files in `_backup_archive_p1_<timestamp>`. It does **not** replace production database files or evidence files.

4. Configure an administrative token, preferably using a managed secret:

   ```powershell
   $env:MISSION_ARCHIVE_ADMIN_TOKEN = '<your long random secret>'
   $env:MISSION_ARCHIVE_ADMIN_ACTOR = 'mission-archive-admin'
   ```

   The API refuses archive if the token is unconfigured. This local administrative service credential is **not** an aptsGSS per-user authorization integration. Do not expose API externally without HTTPS, access control, and governance integration. Keep the token out of source control and command history if possible.

5. Start Mission API as you ordinarily do using **the same environment**, then browse `http://127.0.0.1:8780/ui/#missions`. If APTS Control Center starts the Mission service, launch Control Center from an environment carrying these variables, or configure them in its process service manager.

6. On `Missions`, choose `Active missions`, `Archived missions`, or `All missions`. Click `Archive` for a terminal mission, enter a reason and token. A successful archive disappears from `Active` but remains selectable under `Archived` and `All`.

## Validation

Using a local non-production **copy** of the SQLite DB, the development tests passed (4 repository/service acceptance tests and 2 HTTP API tests), plus 10 existing Mission Console regression tests. Frontend syntax validated with `node --check`.

To rerun with your local database (tests **copy** that SQLite file into an ephemeral temporary directory before writing):

```powershell
cd D:\mission_orchestrator
.\.venv\Scripts\python.exe -m pytest -q tests\test_archive_feature_p1.py tests\test_archive_http_p1.py tests\test_mission_console_phase1_readonly.py tests\test_mission_console_phase2_human_interaction.py tests\test_mission_console_phase3_advanced_operations.py
```

## Limitations / next security gate

- Governance & Safety Service policy binding, user-level authentication, and remote runtime in-flight verification across Pentest/CTI are **not** provided by this P1 feature. Archive only affects operational visibility; it does not stop running actions or revoke authorization. A mission's terminal state is checked atomically against the GMO repository, but external runtime cleanliness must still be verified operationally.
- SQL schema migration for MariaDB is additive through `ensure_schema`, but no live MariaDB integration environment was available for this test run. Make a production backup and perform staging rollout first.
- Archive history is append-only at application level. A privileged database administrator can still modify it; external immutable audit anchoring is a separate task.
- Archive token is requested per operation through a browser prompt, not stored in localStorage or sessionStorage. For multi-user deployment, replace this service token with server-verified GSS principal/role and a governed decision.
