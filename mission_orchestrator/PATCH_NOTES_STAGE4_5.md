# Patch Notes — Stage 4.5

## Added

- `pentest_subsystem/event_contract.py`
  - canonical Stage-4.5 control contract
  - canonical Pentest event schema and required roadmap fields
  - deterministic event identity
  - SHA-256 event hashing and per-Pentest hash-chain verification
  - exact Stage-4.4 predecessor contract binding
- `pentest_subsystem/event_repository.py`
  - Pentest repository migration level 3
  - append-only `pentest_events` ledger
  - task/lifecycle-derived event persistence
  - source-hash binding and stream verification
  - Stage-4.4 upgrade/backfill and restart reconciliation
- `pentest_subsystem/event_service.py`
  - Stage-4.5 health/contract projections
  - event-returning task/lifecycle operations
  - event query and stream verification service
- `pentest_migrations/003_stage4_5_pentest_event_runtime.sql`
- `tests/test_stage4_5_pentest_event_runtime_contract.py`
  - 25 focused tests
- `START_STAGE4_5_PENTEST.ps1`
- `STAGE4_5_ACCEPTANCE.ps1`
- Stage-4.5 install/readme/evidence/manifest files

## Updated

- `pentest_subsystem/api_service.py`
  - historical Stage-4.1/4.2/4.3/4.4 handlers retained
  - active Stage-4.5 handler added
  - event contract/query/stream-verification endpoints added
  - execution dispatch remains fail-closed
- `pentest_subsystem/__init__.py`
  - exports Stage-4.5 event symbols
- `run/pentest_subsystem.py`
  - active runtime description moved to Stage 4.5

## Persistence change

```text
Mission repository migration: 53 (unchanged)
Pentest repository migration:  2 -> 3
```

Stage 4.5 adds:

```text
pentest_events
```

Existing Stage-4.3 tasks and Stage-4.4 lifecycle transitions are reconciled into canonical
Stage-4.5 events at repository initialization.

## Safety / authority boundary

This patch adds local event runtime and persistence only. It does not add workflow-worker
assignment, capability dispatch, target-side execution, network scanning, exploitation,
authorization minting, or Stage-4.9 evidence/finding proof semantics.
