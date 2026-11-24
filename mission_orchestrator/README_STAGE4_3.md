# Stage 4.3 — Pentest Mission & Task Contract

## Status

Implementation candidate for deployment-host acceptance.

Stage 4.3 extends the Pentest Subsystem after Stage 4.2 PIP ingestion/validation. The
Global Mission Orchestrator remains closed at:

`stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`

The active Pentest control becomes:

`stage4.3-pentest-mission-task-contract`

Default endpoints:

- Global Mission Orchestrator: `http://127.0.0.1:8780`
- Pentest Subsystem: `http://127.0.0.1:8790`

## Roadmap objective

Stage 4.3 implements the roadmap deliverables:

- **Pentest task contract**
- **Local task repository**

The roadmap fields are represented directly in the task artifact:

```text
pentest_task_id
target
scope
objective
constraints
evidence_requirement
authorization_reference
completion_criteria
```

Additional lineage fields (`mission_id`, `pentest_id`, `upstream_task_id`, and
`pip_reference`) prevent the local task from becoming detached from the Stage-4.1
boundary and Stage-4.2 PIP binding.

## Canonical contracts

`pentest_subsystem/task_contract.py` introduces:

- control contract: `apts-stage4.3-pentest-mission-task-contract-v1`
- task artifact: `apts-pentest-task-contract-v1`
- task-binding envelope: `apts-stage4.3-pentest-task-binding-envelope-v1`

The Stage-4.3 contract is SHA-bound to the exact Stage-4.2 PIP contract.

## Task binding rules

A local Pentest task is materialized only when all of the following pass:

1. Stage-4.2 PIP binding is valid.
2. `mission_id`, `pentest_id`, and `upstream_task_id` match the PIP lineage.
3. `pip_reference` exactly binds the PIP artifact and Stage-4.2 binding hashes.
4. task target is inside task scope.
5. task scope may narrow, but never widen, the Stage-4.2 bound scope.
6. bound exclusions cannot be removed.
7. v1 objective and constraints remain exact copies of the accepted boundary values.
8. `authorization_reference` is copied exactly; Stage 4.3 cannot mint authorization.
9. evidence requirements and completion criteria are explicit and integrity-bound.

The resulting task binding records nine validation dimensions:

```text
PIP_BINDING
MISSION_LINEAGE
TARGET
SCOPE
OBJECTIVE
CONSTRAINTS
AUTHORIZATION_REFERENCE
EVIDENCE_REQUIREMENT
COMPLETION_CRITERIA
```

## Local task repository

Stage 4.3 introduces an isolated Pentest SQLite repository, separate from the Global
Mission Orchestrator database.

Default file:

`data/pentest_subsystem.db`

Override with:

`APTS_PENTEST_DB`

Pentest migration level becomes **1** using:

`pentest_migrations/001_stage4_3_pentest_mission_task_contract.sql`

The repository stores immutable task and binding artifacts, supports exact-idempotent
replay by `pentest_task_id`, and rejects identity reuse with different content.

The Mission Orchestrator repository remains at migration **53** and is not modified.

## HTTP API

Read contracts:

```text
GET /health
GET /api/pentest/boundary-contract
GET /api/pentest/pip-contract
GET /api/pentest/task-contract
```

Materialize task:

```text
POST /api/pentest/tasks
{
  "boundary": { ... Stage-4.1 boundary ... },
  "pip":      { ... sealed Stage-4.2 PIP ... },
  "task":     { ... sealed Stage-4.3 task ... }
}
```

Read/query repository:

```text
GET /api/pentest/tasks/{pentest_task_id}
GET /api/pentest/tasks?mission_id=...
GET /api/pentest/tasks?pentest_id=...
GET /api/pentest/tasks?upstream_task_id=...
```

## Deliberate Stage-4.3 boundary

Stage 4.3 **does not** implement Stage 4.4 lifecycle semantics. Materializing a task does
not transition it to `RECEIVED`, `VALIDATED`, `READY`, `RUNNING`, or any other runtime
state.

It also does not:

- accept execution dispatches;
- invoke Pentest tools;
- perform external network I/O;
- actuate targets;
- mint authorization;
- decide task completion.

`POST /api/execution/dispatches` remains fail-closed with HTTP `409`.

## Regression status in the implementation environment

Validated before packaging:

- Python compile: PASS
- focused Stage 4.3: **18 passed**
- Stage 4.1 + 4.2 + 4.3: **48 passed**
- critical Stage-3 + Stage-4 predecessor chain: **107 passed**
- canonical inventory: **1623 tests collected**

The authoritative deployment-host gate remains `STAGE4_3_ACCEPTANCE.ps1`, which ends
with the full historical regression suite.

## Next stage

**Stage 4.4 — Pentest Lifecycle & State**
