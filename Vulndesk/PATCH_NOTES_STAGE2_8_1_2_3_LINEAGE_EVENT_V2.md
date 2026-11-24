# Stage 2.8.1-2.8.3 — Task Lineage Foundation & CTI Event Envelope v2

Status: **IMPLEMENTED IN SOURCE**. Apply migration 07 before claiming durable v2 lineage persistence in MariaDB.

## 2.8.1 — Canonical lineage semantics

The CTI runtime now uses the following explicit meanings:

- `event_id`: unique local CTI event identifier.
- `trace_id`: stable end-to-end proposal/task lifecycle root. CTI-A01 currently derives TaskContract `trace_id` from `proposal_id`; it must not be replaced during revalidation, dispatch, result, or revocation.
- `causation_event_id`: immediate local CTI event that caused the current event.
- `upstream_event_id`: event identifier originating in another subsystem, such as `gevent-*` from aptsGSS.
- `proposal_id`, `task_id`, `policy_decision_id`, `authorization_request_id`, `revalidation_id`: business identifiers exposed as first-class lineage fields rather than requiring payload JSON parsing.

`TaskContract.validate()` now rejects an empty `trace_id`.

## 2.8.2 — Migration 07

Apply:

`sql_update_cti_harmonized/07_task_lineage_event_traceability.sql`

The migration is non-destructive and adds:

### `cti_events`

- `event_schema_version`
- `trace_id`
- `causation_event_id`
- `upstream_event_id`
- `proposal_id`
- `task_id`
- `policy_decision_id`
- `authorization_request_id`
- `revalidation_id`

It also adds indexes for mission/trace, task, PolicyDecision, upstream event, and causation lookup.

Existing rows default to `cti-event-v1`.

### `cti_decision_traces`

The migration reserves explicit lifecycle binding columns:

- `lineage_trace_id`
- `proposal_id`
- `task_id`
- `policy_decision_id`
- `authorization_request_id`
- `revalidation_id`

The existing `trace_id` remains the unique decision-trace row identifier (`arb-*`). Population of richer TaskCommit/TaskResult traces belongs to Stage 2.8.7.

## 2.8.3 — Additive CTI event envelope v2

`cti_services/event_bus.py` now emits `cti-event-v2` in memory and supports the first-class lineage fields above.

Backward compatibility is deliberate:

- if migration 07 is installed, `_persist_event()` writes the full v2 column set;
- if the database still has the legacy `cti_events` schema, event persistence falls back to the v1 columns instead of losing the event write;
- `recent_events()` normalizes legacy rows so callers receive the same response shape with `event_schema_version='cti-event-v1'` and null lineage fields;
- `enqueue_existing()` treats an unversioned historical event as v1 rather than pretending it has complete v2 lineage.

`CtiSubsystemOrchestrator._emit_event()` and `publish_external_event()` now accept optional lineage arguments, but existing lifecycle call sites are intentionally unchanged in this patch. Actual enrichment of `TASK_COMMITTED`, revalidation, dispatch, result, and revocation events starts at Stage 2.8.4.

## Control version

`hybrid-event-driven-2.6-lineage-event-envelope`

## Authority invariant

This patch does **not** change:

- PolicyDecision authority ownership (`aptsGSS/GOV-PLANE`),
- PolicyDecision hash calculation,
- pre-dispatch fail-closed semantics,
- granular revocation semantics,
- internal-task `NOT_REQUIRED_INTERNAL` authority behavior.
