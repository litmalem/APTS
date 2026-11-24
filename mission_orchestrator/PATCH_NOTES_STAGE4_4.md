# Patch Notes — Stage 4.4

## Added

- `pentest_subsystem/lifecycle_contract.py`
  - canonical Stage-4.4 control contract
  - nine-state Pentest lifecycle topology
  - immutable terminal-state semantics
  - guarded transition request contract
  - wait/resume and completion guards
  - lifecycle state/transition SHA-256 projections
- `pentest_subsystem/lifecycle_repository.py`
  - Pentest repository migration level 2
  - durable current lifecycle projection
  - optimistic state-version concurrency
  - exact-idempotent transition journal
  - Stage-4.3 → Stage-4.4 migration/backfill support
- `pentest_subsystem/lifecycle_service.py`
  - Stage-4.4 lifecycle API/service projection
  - task creation initializes `RECEIVED`
  - guarded transition application/history
- `pentest_migrations/002_stage4_4_pentest_lifecycle_state.sql`
- `tests/test_stage4_4_pentest_lifecycle_state.py`
  - 23 focused tests
- `START_STAGE4_4_PENTEST.ps1`
- `STAGE4_4_ACCEPTANCE.ps1`
- Stage-4.4 install/readme/evidence/manifest files

## Updated

- `pentest_subsystem/api_service.py`
  - historical Stage-4.1/4.2/4.3 handlers retained
  - active Stage-4.4 handler added
  - lifecycle contract/state/transition endpoints added
  - execution dispatch remains fail-closed
- `pentest_subsystem/__init__.py`
  - exports Stage-4.4 lifecycle symbols
- `run/pentest_subsystem.py`
  - active runtime description moved to Stage 4.4

## Persistence change

```text
Mission repository migration: 53 (unchanged)
Pentest repository migration:  1 -> 2
```

Stage 4.4 adds:

```text
pentest_task_lifecycle
pentest_task_lifecycle_transitions
```

The transition journal is lifecycle-control persistence, **not** the Stage-4.5 canonical
event runtime.

## Safety / authority boundary

This patch controls local Pentest state only. It does not add target-side execution,
network scanning, exploitation, workflow orchestration, capability dispatch, canonical
Pentest event emission, or local authorization authority.

The `RUNNING` state therefore means that the local lifecycle has entered its running phase;
it does not mean that tools or target actions have been executed.
