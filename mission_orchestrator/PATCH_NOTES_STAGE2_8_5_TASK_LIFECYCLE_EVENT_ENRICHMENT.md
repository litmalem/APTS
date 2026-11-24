# Patch Notes — Stage 2.8.5 Task Lifecycle Event Enrichment

## Baseline analyzed

- VulnDesk source: `vulndesk(20260819-013600).zip`
- VulnDesk DB schema: `vulndesk(5).sql`
- aptsGSS source: `aptsGSS(5).zip`
- aptsGSS DB schema: `aptsGSS(3).sql`
- Previous control version: `hybrid-event-driven-2.7-task-committed-lineage`

## Baseline findings

Stage 2.8.4 correctly emitted `TASK_COMMITTED` with first-class lineage (`trace_id`, `proposal_id`, `task_id`, and governance binding identifiers where applicable). The remaining lifecycle events still stored their task identifiers mostly inside `payload_json`, leaving the v2 first-class columns NULL.

Affected lifecycle events:

- `TASK_AUTHORIZATION_REVALIDATED`
- `TASK_DISPATCHED`
- `TASK_DISPATCH_BLOCKED`
- `TASK_AUTHORIZATION_REVOKED`
- `TASK_REVOCATION_STOP_REQUESTED`
- `TASK_COMPLETED`
- `TASK_FAILED`

The Stage 2.8.4 DB already contains all columns required by Stage 2.8.5. No new migration is required.

## Implementation

### 1. Stable TaskContract lineage propagation

Added reusable lineage helpers to CTI-A01:

- `_task_lineage_from_contract(...)`
- `_task_lineage_from_snapshot(...)`

The helpers project only business lineage fields:

- `trace_id`
- `proposal_id`
- `task_id`
- `policy_decision_id`
- `authorization_request_id`
- `revalidation_id`

`causation_event_id` and `upstream_event_id` are intentionally NOT assigned in this patch. They remain Stage 2.8.6 scope.

### 2. Internal TaskContract lifecycle

For ordinary internal CTI tasks, the exact lineage created by `TASK_COMMITTED` is now propagated to:

- `TASK_DISPATCHED`
- `TASK_COMPLETED`
- `TASK_FAILED`

Internal tasks remain `NOT_REQUIRED_INTERNAL`; no external PolicyDecision identifiers are fabricated.

### 3. Required-authority lifecycle

For CTI source acquisition, the exact committed TaskContract lineage is now propagated to:

- `TASK_AUTHORIZATION_REVALIDATED`
- `TASK_DISPATCHED`
- `TASK_DISPATCH_BLOCKED`

The `revalidation_id` returned by aptsGSS is persisted as a first-class event field.

### 4. Granular revocation lifecycle

The Stage 2.7 TaskContract projection now retrieves:

- `trace_id`
- `authorization_request_id`
- `pre_dispatch_revalidation_id`

and propagates them to:

- `TASK_AUTHORIZATION_REVOKED`
- `TASK_DISPATCH_BLOCKED`
- `TASK_REVOCATION_STOP_REQUESTED`

Granular enforcement semantics are unchanged.

### 5. Control version

New VulnDesk control version:

`hybrid-event-driven-2.8-task-lifecycle-lineage`

## Database impact

No schema changes. Migration 07 already supplies:

- `cti_events.trace_id`
- `cti_events.proposal_id`
- `cti_events.task_id`
- `cti_events.policy_decision_id`
- `cti_events.authorization_request_id`
- `cti_events.revalidation_id`

`cti_task_contracts` already supplies the durable source values.

## aptsGSS impact

No aptsGSS source or database changes are required for Stage 2.8.5. aptsGSS remains authoritative for PolicyDecision lifecycle, pre-dispatch revalidation, and granular revocation. Stage 2.8.5 only propagates the already-issued identifiers through VulnDesk task lifecycle events.

## Validation

Focused Stage 2.8.5 test:

- `5 passed`

Stage 2.5–2.8.5 regression group:

- `36 passed`

Broad VulnDesk regression excluding NVD bulk-upsert:

- `69 passed`

The build environment used for this patch does not contain `PyMySQL`, so `tests/test_nvd_bulk_upsert.py` cannot be collected here. This environment limitation does not affect Stage 2.8.5 logic. The user workstation already runs the full suite with PyMySQL installed.
