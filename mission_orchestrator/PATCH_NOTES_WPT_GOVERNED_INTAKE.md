# Mission WPT governed intake

This patch adds a Mission-owned intake API on the Mission service (default port
8780). WPT submits only a Mission ID, upstream Task ID, declared target, fixed
profile name, intake ID, and idempotency key. It cannot supply scope, RoE,
request limits, authorization, evidence, or execution status.

## Endpoint and authentication

- `POST /api/wpt/intakes` submits a job for governed intake.
- `GET /api/wpt/intakes/{intake_id}` reads one durable intake record.
- `GET /api/wpt/intakes?mission_id=...&task_id=...` lists records for that task.
- All routes require `Authorization: Bearer <token>`.
- Configure `MISSION_WPT_INTAKE_TOKEN` on Mission with a random secret of at
  least 32 characters. The token is never stored in intake records.
- `APTS_WPT_INTAKE_DB` optionally selects the separate SQLite intake store.

Example request body:

```json
{
  "schema_version": "apts-wpt-governed-intake-v1",
  "intake_id": "wptreq-20261017-example",
  "idempotency_key": "idem-20261017-example",
  "mission_id": "mission-gmo-example",
  "task_id": "ptask-example",
  "target": {
    "target_type": "URL",
    "target_value": "https://example.test/"
  },
  "profile": "fingerprinting"
}
```

Allowed profiles are `fingerprinting` and `enumeration`; each maps to its own
fixed Mission registry capability. Mission reads current Mission scope/RoE and
governance binding plus the immutable Pentest task, task lifecycle, and active
orchestration from their authoritative stores. It rejects targets outside
scope, excluded targets, inactive tasks, stale or invalid records, and
techniques not explicitly allowed by current RoE. Request limits are bounded
by the fixed profile and the current Mission/task budget. The intake store
enforces idempotency and atomically reserves the available per-task budget.

## Current execution boundary

An accepted record has status `ACCEPTED_PENDING_STAGE6`. It is a durable,
scope-checked intake only: it does **not** authorize, dispatch, or scan a
target. WPT profiles remain `REGISTERED_NOT_EXECUTABLE` until the Stage 6
adapter and evidence implementation is delivered and independently governed.
The next integration step must revalidate the current bindings and execute only
through Stage 6.

## Stage 6 result validation and storage

The Mission intake service now accepts a result reference at
`POST /api/wpt/intakes/{intake_id}/stage6-results`. The body is limited to the
matching intake ID plus an exact Stage 6 execution ID and runtime attempt ID;
WPT cannot submit result content, evidence, a target, capability, or a claimed
status. Mission resolves the attempt from the configured Stage 6.6 execution
database (`APTS_EXECUTION_DB`) and reads the runtime result and sealed manifest
from that verified ledger. It fails closed when the database is unavailable.

Mission checks the intake's executable profile, mission/task/target/capability
bindings, successful terminal state, and Stage 6.6 manifest binding to the
attempt and adapter result hash. Only a bounded sanitized observation and the
result/evidence hashes are persisted in an append-only SQLite result table.
Raw bodies, cookies, authorization values, and credentials are rejected. The
stored record is integrity-sealed and idempotent; `GET /api/wpt/intakes/{id}`
and task intake lists include the stored result when present.

This does not activate either WPT capability. Both remain
`REGISTERED_NOT_EXECUTABLE`, so result submission rejects today's pending
intakes. A Stage 6.4 WPT adapter and its execution request path must be enabled
before this result path can accept a real scan result.

## Durable WPT-to-Recon handoff

After Mission has validated and stored a successful sealed result, WPT may
request its delivery to Recon:

```text
POST /api/wpt/intakes/{intake_id}/recon-handoff
GET  /api/wpt/intakes/{intake_id}/recon-handoff
```

The POST body is limited to a parent Recon run and an Action Request already
published by that parent:

```json
{
  "schema_version": "apts-wpt-recon-handoff-request-v1",
  "parent_recon_run_id": "reconrun-parent",
  "action_id": "rareq-action"
}
```

Mission writes a sealed event to a SQLite outbox before invoking Recon. The
receiver checks the immutable parent/action binding, target, mission/task and
sealed Stage 6 evidence, then appends a Recon iteration containing only the
sanitized observation and evidence references. The ACK is accepted only when
it includes the same intake ID and Stage 6 result hash plus the persisted Recon
run ID. Mission changes the outbox state to `DELIVERED` only after that ACK;
otherwise it retains `PENDING` with an attempt count and bounded error code.
`GET` exposes the durable status. Replaying the same request after a process
restart uses the same event and Recon idempotency key, so a lost ACK does not
create a second Recon run. Reusing an intake with a different parent/action
binding is rejected.

The handoff requires an already existing Recon parent run and an Action
Request in that run for the exact WPT target. A handoff does not create a scan,
grant execution authority, classify a vulnerability, or mutate the parent run.
