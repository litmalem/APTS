# P2 — Restore Archived Mission

Mission Control now supports restoring an archived mission to operational lists.
Restore changes administrative visibility only. It does not change the mission's
canonical lifecycle state, envelope, events, tasks, or evidence.

## Changes

- Added authenticated `POST /api/missions/{mission_id}/restore`.
- Reuses the server-side `MISSION_ARCHIVE_ADMIN_TOKEN` and actor configuration
  already used by Archive. The actor identity is assigned by the server.
- Requires the current `expected_state_version`, an audit `reason` of at least
  eight characters, and an `idempotency_key`.
- Rejects missions that are not archived, non-terminal missions, stale versions,
  and idempotency-key reuse with different request data.
- Removes the current archive visibility row and appends a `RESTORE` record to
  the same per-mission hash-chained administrative history. History is retained.
- Added Restore actions to archived mission rows and Mission Workspace.
- Updated existing SQLite installations by rebuilding only the archive history
  table when its old P1 constraint permits `ARCHIVE` alone. Existing history
  entries are copied unchanged. MySQL/MariaDB already allow operation values.

## Deployment

1. Back up the Mission Orchestrator database and source directory.
2. Deploy the updated `mission_orchestrator` and `mission_web` files together.
3. Keep the existing `MISSION_ARCHIVE_ADMIN_TOKEN` and
   `MISSION_ARCHIVE_ADMIN_ACTOR` server settings configured.
4. Restart the Mission Orchestrator service. SQLite schema adjustment runs at
   repository initialization; no canonical mission rows are altered.
5. Open Missions, select **Archived missions**, then use **Restore**. Enter a
   reason and the existing administrative token when prompted.

## Verification performed

- Restore unit tests: pass.
- Archive regression unit tests: pass.
- Python module compilation: pass.
- Mission Control JavaScript syntax check: pass.
- HTTP listener tests could not bind a local port in the restricted execution
  environment and should be run in the deployment test environment.
