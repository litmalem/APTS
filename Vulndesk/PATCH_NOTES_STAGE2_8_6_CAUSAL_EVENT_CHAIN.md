# VulnDesk Stage 2.8.6 — Causal Event Chain

## Baseline analyzed

- VulnDesk control version: `hybrid-event-driven-2.8-task-lifecycle-lineage`
- Migration 07 already provides `causation_event_id` and `upstream_event_id` on `cti_events`, including indexes.
- aptsGSS transactional outbox already generates `gevent-*` and injects it into the delivered payload as `governance_event_id`.
- Therefore Stage 2.8.6 requires no new database migration and no aptsGSS source change.

## New control version

`hybrid-event-driven-2.9-causal-event-chain`

## Implemented causal semantics

### Internal task

`TASK_COMMITTED -> TASK_DISPATCHED -> TASK_COMPLETED/TASK_FAILED`

Each child stores the immediate predecessor in `causation_event_id`.

### Governed task

`TASK_COMMITTED -> TASK_AUTHORIZATION_REVALIDATED -> TASK_DISPATCHED`

A failed pre-dispatch revalidation produces:

`TASK_COMMITTED -> TASK_DISPATCH_BLOCKED`

### Governed CTI acquisition outcome

`TASK_DISPATCHED -> SOURCE_SYNC_PROGRESS* -> SOURCE_SYNC_COMPLETED/DEGRADED/FAILED`

The source-sync events also keep the TaskContract business lineage from Stage 2.8.5.

### Cross-subsystem revocation

`aptsGSS gevent-G1 -> VulnDesk AUTHORIZATION_REVOKED C1 -> TASK_AUTHORIZATION_REVOKED C2 -> TASK_DISPATCH_BLOCKED/STOP_REQUESTED C3`

- `C1.upstream_event_id = gevent-G1`
- `C2.causation_event_id = C1.event_id`
- `C3.causation_event_id = C2.event_id`
- child revocation events retain the same `upstream_event_id` for direct cross-system lookup.

## Persistence strategy

The orchestrator keeps an in-process per-task causal head. A best-effort DB fallback can recover the latest task event after runtime reconstruction. TaskContract itself is not mutated to store causal event state.

## Scope boundary

Stage 2.8.6 does not modify:

- PolicyDecision ownership or hash semantics
- authorization/revalidation rules
- granular revocation enforcement
- decision/audit lineage (Stage 2.8.7)
- event schema or database structure

## Tests added

`tests/test_causal_event_chain_stage2_8_6.py`

Focused coverage:

1. internal commit -> dispatch -> completed causal chain
2. failure caused by dispatch
3. governed revalidation continues from task causal head
4. revalidation failure is caused by prior commit
5. external `governance_event_id` becomes `upstream_event_id`
6. gevent -> local ingress -> task revoke -> block causal chain
