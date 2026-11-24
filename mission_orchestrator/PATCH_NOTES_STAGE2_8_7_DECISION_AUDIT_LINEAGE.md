# VulnDesk Stage 2.8.7 — Decision / Audit Lineage

## Baseline analyzed

- VulnDesk baseline control version: `hybrid-event-driven-2.9.1-revocation-race-hardening`.
- Stage 2.8 migration 07 already reserves the required first-class columns on `cti_decision_traces`:
  `lineage_trace_id`, `proposal_id`, `task_id`, `policy_decision_id`,
  `authorization_request_id`, and `revalidation_id`.
- `cti_audit_log` already contains `trace_id` and `downstream_event_ref`.
- aptsGSS already owns authoritative `PolicyDecision`, `greval-*`, and `gevent-*` identities. No aptsGSS source or schema change is required.

Therefore Stage 2.8.7 requires **no new database migration**.

## New control version

`hybrid-event-driven-2.10-decision-audit-lineage`

## Canonical identity model

Stage 2.8.7 deliberately separates two trace concepts:

- `cti_decision_traces.trace_id`: unique identity of one decision record (`arb-*` / `dtrace-*`).
- `cti_decision_traces.lineage_trace_id`: stable proposal / TaskContract lineage root.

The audit/event bridge is:

`cti_audit_log.trace_id -> cti_decision_traces.trace_id`

and

`cti_audit_log.downstream_event_ref -> cti_events.event_id`

Task/business reconstruction then continues through:

`cti_decision_traces.lineage_trace_id -> cti_task_contracts.trace_id -> cti_events.trace_id`.

## Implemented decision traces

### ARBITRATION

Existing arbitration rows are enriched with:

- `lineage_trace_id = selected proposal_id`
- `proposal_id = selected proposal_id`

No synthetic task ID is added before TaskContract commit.

### TASK_COMMIT

Every successful TaskContract commit creates a `TASK_COMMIT` decision trace containing:

- proposal/task lineage
- authorization mode and local guard snapshot
- authoritative PolicyDecision binding references when authorization is REQUIRED
- the exact `TASK_COMMITTED` event ID as execution outcome

Its audit row points to `TASK_COMMITTED` through `downstream_event_ref`.

### PRE_DISPATCH_REVALIDATION

Every REQUIRED pre-dispatch authoritative revalidation creates a dedicated trace containing:

- exact `decision_id`
- exact `request_id`
- exact `revalidation_id`
- immutable binding reference snapshot
- ALLOW/BLOCK result returned by aptsGSS
- downstream `TASK_AUTHORIZATION_REVALIDATED` or `TASK_DISPATCH_BLOCKED` event

### TASK_RESULT

Terminal task/source outcomes create `TASK_RESULT` traces for:

- `TASK_COMPLETED`
- `TASK_FAILED`
- `SOURCE_SYNC_COMPLETED`
- `SOURCE_SYNC_DEGRADED`
- `SOURCE_SYNC_FAILED`

### Safety / revocation enforcement

The following task safety outcomes also become explicit decision/audit traces:

- `TASK_AUTHORIZATION_REVOKED` -> `AUTHORIZATION_REVOCATION`
- `TASK_DISPATCH_BLOCKED` -> `DISPATCH_BLOCK`
- `TASK_REVOCATION_STOP_REQUESTED` -> `REVOCATION_STOP`

Their execution outcome snapshots preserve local `causation_event_id` and external `upstream_event_id`, so Stage 2.8.6 causality remains reconstructable from decision/audit records.

## Authority invariants

Stage 2.8.7 does not create or reinterpret authority.

- aptsGSS/GOV-PLANE remains the sole authoritative owner of PolicyDecision.
- internal `NOT_REQUIRED_INTERNAL` task traces retain null Governance identifiers.
- REQUIRED task traces only copy stable references already bound into the TaskContract.
- PolicyDecision hash and revalidation semantics are unchanged.
- Stage 2.8.6.1 revocation precedence and fail-closed behavior are unchanged.

## Files changed

- `cti_services/cti_subsystem_orchestrator.py`
- `tests/test_decision_audit_lineage_stage2_8_7.py` (new)
- `STAGE2_8_7_ACCEPTANCE.sql` (new)

## Validation in build environment

- Stage 2.8.7 focused: `5 passed`
- Stage 2.8 combined regression: `50 passed`
- Broad regression excluding `test_nvd_bulk_upsert.py`: `83 passed`
- Full suite could not be collected in the build environment because `pymysql` is not installed there; the user's local baseline already provides that dependency.

Expected local full-suite target after adding five tests: approximately `87 passed`, with the existing SQLAlchemy `datetime.utcnow()` warnings remaining non-blocking.
