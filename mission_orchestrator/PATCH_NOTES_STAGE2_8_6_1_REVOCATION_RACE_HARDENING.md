# VulnDesk Stage 2.8.6.1 — Revocation / Pre-dispatch Race Hardening

## Why this patch exists

Stage 2.8.6 E2E acceptance exposed a real interleaving defect that unit tests did not previously cover:

1. A governed TaskContract was committed and paused at the deterministic pre-dispatch test gate.
2. aptsGSS revoked the exact PolicyDecision.
3. VulnDesk's HTTP-ingress fast path correctly projected `VERIFIED_REVOKED` and blocked dispatch.
4. After gate release, authoritative pre-dispatch revalidation correctly returned invalid/revoked.
5. The generic revalidation persistence overwrote the task status from the revocation-specific state to `BLOCKED_AUTHORIZATION`.
6. Mission terminalization then caused the queued `AUTHORIZATION_REVOKED` handler to return before materializing `TASK_AUTHORIZATION_REVOKED -> TASK_DISPATCH_BLOCKED` causal audit events.

Safety remained fail-closed, but the status semantics and causal audit chain were incomplete.

## Fix 1 — Revocation status has precedence

`_persist_pre_dispatch_revalidation()` now atomically preserves revocation-specific state:

- `VERIFIED_REVOKED*` -> `BLOCKED_REVOKED`
- `FAIL_CLOSED*` -> `BLOCKED_REVOKED`
- `revoked_at IS NOT NULL` -> `BLOCKED_REVOKED`
- otherwise invalid authorization -> `BLOCKED_AUTHORIZATION`

The existing revocation-specific `error_text` is also preserved when present.

## Fix 2 — Terminal missions still project safety/audit causality

`AUTHORIZATION_REVOKED` on a terminal mission no longer triggers operational replanning, rescheduling, or mission resurrection. It **does** materialize durable task-level audit events from the already-verified fast-path projection:

`AUTHORIZATION_REVOKED -> TASK_AUTHORIZATION_REVOKED -> TASK_DISPATCH_BLOCKED`

(or `TASK_REVOCATION_STOP_REQUESTED` for a previously running task).

The external `gevent-*` identity remains in `upstream_event_id` for the task-level children.

## Control version

`hybrid-event-driven-2.9.1-revocation-race-hardening`

## Database

No new migration is required. Migration 07 / Stage 2.7-2.8 schema already contains all necessary fields and indexes.

## Files changed

- `cti_services/cti_subsystem_orchestrator.py`

## Files added

- `tests/test_revocation_race_hardening_stage2_8_6_1.py`
- `STAGE2_8_6_1_ACCEPTANCE.sql`
- `BUILD_VALIDATION_STAGE2_8_6_1.txt`

## Deployment

Replace the patched orchestrator, restart VulnDesk, and repeat only the Stage 2.8.6 revocation acceptance scenario. Internal and normal governed causal scenarios do not need to be recreated, although regression tests should still be rerun.
