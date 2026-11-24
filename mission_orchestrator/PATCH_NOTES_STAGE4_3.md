# Patch Notes — Stage 4.3

## Added

- `pentest_subsystem/task_contract.py`
  - canonical Stage-4.3 control contract
  - strict Pentest task artifact
  - PIP-bound task-binding envelope
  - fail-closed scope/lineage/authorization validation
- `pentest_subsystem/task_repository.py`
  - isolated SQLite local task repository
  - migration level 1
  - immutable identity + exact-idempotent replay
  - mission/pentest/upstream-task query projection
- `pentest_subsystem/task_service.py`
  - Stage-4.3 task contract and materialization service
- `pentest_migrations/001_stage4_3_pentest_mission_task_contract.sql`
- `tests/test_stage4_3_pentest_mission_task_contract.py`
  - 18 focused tests
- `START_STAGE4_3_PENTEST.ps1`
- `STAGE4_3_ACCEPTANCE.ps1`
- Stage-4.3 install/readme/evidence/manifest files

## Updated

- `pentest_subsystem/api_service.py`
  - historical Stage-4.1 and Stage-4.2 handlers retained
  - active Stage-4.3 handler added
  - task contract/create/get/list endpoints added
  - execution dispatch remains rejected
- `pentest_subsystem/__init__.py`
  - exports Stage-4.3 contract/repository symbols
- `run/pentest_subsystem.py`
  - active runtime description moved to Stage 4.3

## Persistence change

Stage 4.3 is the first Stage-4 Pentest step that adds durable local persistence.

```text
Mission repository migration: 53 (unchanged)
Pentest repository migration:  0 -> 1
```

Default Pentest database:

`data/pentest_subsystem.db`

The new database is isolated from `data/mission_orchestrator.db`.

## Safety / authority boundary

This patch materializes task contracts only. It does not add target-side execution,
network scanning, exploitation, lifecycle state transitions, tool invocation, or a local
authorization authority.

Authorization remains a referenced external APTS-GSS artifact and must exactly match the
accepted boundary.
