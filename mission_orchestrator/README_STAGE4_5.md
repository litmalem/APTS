# Stage 4.5 — Pentest Event Runtime & Contract

## Status

Implementation candidate for deployment-host acceptance.

Stage 4.5 extends the Stage-4.4 guarded lifecycle with a canonical, durable Pentest event
runtime. The Global Mission Orchestrator remains closed at:

`stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`

The active Pentest control becomes:

`stage4.5-pentest-event-runtime-contract`

Default endpoints:

- Global Mission Orchestrator: `http://127.0.0.1:8780`
- Pentest Subsystem: `http://127.0.0.1:8790`

## Roadmap objective

Stage 4.5 implements the roadmap deliverables:

- **Pentest event schema**
- **Event persistence**

The roadmap canonical event fields are represented directly:

```text
event_id
pentest_id
mission_id
task_id
agent_id
event_type
state_before
state_after
evidence_refs
timestamp
```

The implementation adds explicit integrity/provenance fields around this minimum schema so
the event ledger can be verified and recovered without changing the roadmap fields.

## Canonical contract

`pentest_subsystem/event_contract.py` adds:

- control contract: `apts-stage4.5-pentest-event-runtime-contract-v1`
- event schema: `apts-pentest-event-v1`
- control version: `stage4.5-pentest-event-runtime-contract`
- exact SHA-256 binding to the Stage-4.4 lifecycle contract

Canonical event types in Stage 4.5 are deliberately narrow:

```text
PENTEST_TASK_RECEIVED
PENTEST_LIFECYCLE_STATE_TRANSITIONED
```

Stage 4.5 does **not** accept arbitrary external event injection. Events are derived only from
existing authoritative local sources:

```text
Stage-4.3 immutable Pentest task materialization
        ↓
PENTEST_TASK_RECEIVED

Stage-4.4 guarded lifecycle transition journal
        ↓
PENTEST_LIFECYCLE_STATE_TRANSITIONED
```

This prevents a caller from manufacturing lifecycle history independently of the task/state
repositories.

## Event identity, ordering, and integrity

Each derived event uses a deterministic `pevent-...` identity based on immutable source
identity. Replaying the same task materialization or lifecycle transition therefore resolves to
the same event instead of appending a duplicate.

Events are persisted as an append-only stream per `pentest_id` with:

```text
event_sequence
parent_event_id
previous_event_sha256
canonical_sha256
source_type
source_id
source_sha256
```

The stream is a local SHA-256 hash chain. Each event after the stream root binds the exact
immediate predecessor event hash. The event also binds its authoritative source hash:

- task-received event → Stage-4.3 `task_binding_sha256`
- lifecycle-transition event → Stage-4.4 `transition_sha256`

`task_id` in the Stage-4.5 event schema means the local Stage-4.3 `pentest_task_id`.
`upstream_task_id` is retained separately for cross-subsystem correlation.

`evidence_refs` remain references only. Stage 4.5 does not claim Stage-4.9 evidence/finding
integrity semantics.

## Durable repository

Stage 4.5 upgrades the isolated Pentest repository from migration **2 → 3**.

Migration:

`pentest_migrations/003_stage4_5_pentest_event_runtime.sql`

New table:

```text
pentest_events
```

The table enforces:

- unique `event_id`;
- unique immutable `(source_type, source_id)`;
- unique `(pentest_id, event_sequence)`;
- durable event JSON plus canonical hash;
- indexes for mission, Pentest stream, task, event type, and parent event.

The Global Mission Orchestrator repository remains migration **53** and is not modified.

## Upgrade and restart reconciliation

When a Stage-4.4 repository is opened by Stage 4.5, the runtime migrates it to level 3 and
reconciles canonical events from existing durable Stage-4.3/4.4 source records. This gives two
properties:

1. historical tasks/transitions already present at upgrade receive canonical Stage-4.5 events;
2. if a process stops after a predecessor commit but before the derived event append, the next
   repository initialization restores the missing event idempotently.

Reconciliation never synthesizes target execution, tool results, evidence proof, or workflow
orchestration.

## HTTP API

Historical contracts remain available:

```text
GET /health
GET /api/pentest/boundary-contract
GET /api/pentest/pip-contract
GET /api/pentest/task-contract
GET /api/pentest/lifecycle-contract
```

Stage-4.5 contract:

```text
GET /api/pentest/event-contract
GET /api/contracts/pentest-event
```

Event queries:

```text
GET /api/pentest/events
GET /api/pentest/events/{event_id}
GET /api/pentest/tasks/{pentest_task_id}/events
GET /api/pentest/event-streams/{pentest_id}/verify
```

`GET /api/pentest/events` supports exact filters:

```text
mission_id
pentest_id
task_id
event_type
limit
```

Task creation and lifecycle transition APIs remain the event producers:

```text
POST /api/pentest/tasks
POST /api/pentest/tasks/{pentest_task_id}/lifecycle/transitions
```

Their Stage-4.5 responses now include the persisted canonical `event`.

## Deliberate Stage-4.5 boundary

Stage 4.5 is an event-runtime stage, not a workflow-execution stage. In particular:

- Stage-4.4 lifecycle guards remain authoritative for state changes;
- no Stage-4.6 local Pentest workflow orchestrator is invoked;
- no Stage-4.7 capability/tool runtime is invoked;
- no external network I/O is performed;
- no target actuation occurs;
- no authorization is minted;
- `POST /api/execution/dispatches` remains fail-closed with HTTP `409`;
- a lifecycle `RUNNING` event records local state only and does not prove target-side execution.

## Running Stage 4.5

From `D:\mission_orchestrator` in a separate PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE4_5_PENTEST.ps1
```

Equivalent direct command:

```powershell
python -m run.pentest_subsystem --host 127.0.0.1 --port 8790
```

Keep the Global Mission Orchestrator running on port `8780`.

## Regression status in the implementation environment

Validated before packaging:

- Python compile: **PASS**
- focused Stage 4.5: **25 passed**
- Stage 4.1 + 4.2 + 4.3 + 4.4 + 4.5: **96 passed**
- critical Stage-3 + Stage-4 predecessor chain: **155 passed**
- canonical inventory: **1671 tests collected**

The authoritative deployment-host gate is `STAGE4_5_ACCEPTANCE.ps1`, which ends with the
full historical regression suite.

## Next stage

**Stage 4.6 — Pentest Workflow Orchestrator Skeleton**
