# Patch Notes — Stage 4.6

## Added

- `pentest_subsystem/workflow_contract.py`
  - canonical Stage-4.6 workflow-orchestrator skeleton contract
  - deterministic workflow identity
  - strict start/result request schemas
  - exact Stage-4.5 predecessor SHA binding
  - fixed non-executing placeholder-worker contract
  - success-result validation against Stage-4.3 evidence/completion requirements
- `pentest_subsystem/workflow_repository.py`
  - Pentest repository migration level 4
  - durable workflow and immutable result persistence
  - idempotent/restart-safe workflow start
  - existing Stage-4.4 guarded lifecycle progression
  - existing Stage-4.5 event-runtime reuse
  - terminal task closure from structured placeholder results
- `pentest_subsystem/workflow_service.py`
  - Stage-4.6 health/contract projections
  - workflow start/result/query services
  - explicit non-execution response flags
- `pentest_migrations/004_stage4_6_pentest_workflow_orchestrator_skeleton.sql`
- `tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py`
  - 26 focused tests
- `START_STAGE4_6_PENTEST.ps1`
- `STAGE4_6_ACCEPTANCE.ps1`
- Stage-4.6 install/readme/evidence/manifest files

## Updated

- `pentest_subsystem/api_service.py`
  - historical Stage-4.1 through Stage-4.5 handlers retained
  - active Stage-4.6 handler added
  - workflow contract/start/result/query endpoints added
  - execution dispatch remains fail-closed
- `pentest_subsystem/__init__.py`
  - exports Stage-4.6 workflow symbols
- `run/pentest_subsystem.py`
  - active runtime description moved to Stage 4.6

## Persistence change

```text
Mission repository migration: 53 (unchanged)
Pentest repository migration:  3 -> 4
```

Stage 4.6 adds:

```text
pentest_workflows
pentest_workflow_results
```

No target-side execution state is stored because Stage 4.6 has no execution authority.

## Control-flow change

A canonical task in `RECEIVED` can now enter the local skeleton:

```text
receive task
→ create deterministic workflow
→ assign PENTEST_PLACEHOLDER_WORKER
→ guarded RECEIVED→VALIDATED→READY→PLANNING→RUNNING
→ accept structured placeholder result
→ guarded COMPLETED or FAILED closure
```

The Stage-4.5 event ledger remains the authoritative durable history of task materialization and
lifecycle transitions.

## Safety / authority boundary

This patch does **not** add full reasoning, replanning, capability selection, scanning,
enumeration, exploitation, target network I/O, tool execution, execution authorization, or
target actuation. Those boundaries remain fail-closed. Stage 4.7 will add the capability/tool
contract, while controlled target execution remains a later-stage concern.
