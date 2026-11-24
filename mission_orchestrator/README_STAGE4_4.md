# Stage 4.4 — Pentest Lifecycle & State

## Status

Implementation candidate for deployment-host acceptance.

Stage 4.4 extends the isolated Pentest Subsystem after Stage 4.3 task materialization. The
Global Mission Orchestrator remains closed at:

`stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`

The active Pentest control becomes:

`stage4.4-pentest-lifecycle-state`

Default endpoints:

- Global Mission Orchestrator: `http://127.0.0.1:8780`
- Pentest Subsystem: `http://127.0.0.1:8790`

## Roadmap objective

Stage 4.4 implements the roadmap deliverables:

- **Pentest state machine**
- **State transition guards**

Canonical states:

```text
RECEIVED
→ VALIDATED
→ READY
→ PLANNING
→ RUNNING
↔ WAITING
→ COMPLETED

Any non-terminal state may also fail closed to:
FAILED
ABORTED
```

`FAILED`, `ABORTED`, and `COMPLETED` are immutable terminal states.

## Canonical contract

`pentest_subsystem/lifecycle_contract.py` adds:

- control contract: `apts-stage4.4-pentest-lifecycle-state-v1`
- lifecycle state projection: `apts-pentest-lifecycle-state-v1`
- lifecycle transition artifact: `apts-pentest-lifecycle-transition-v1`

The Stage-4.4 contract is SHA-256-bound to the exact Stage-4.3 task contract.

## Lifecycle semantics

A newly materialized Stage-4.4 Pentest task is initialized to:

```text
state         = RECEIVED
state_version = 1
```

State transitions are explicit and guarded. The request carries:

```text
transition_id
idempotency_key
expected_state_version
to_state
actor
reason_code
reason
evidence_refs
metadata
```

Every successful transition increments `state_version` exactly once. Reusing the same
transition identity with the same immutable request is idempotent; reusing it for different
content fails closed.

## Transition topology

Operational edges are deliberately narrow:

```text
RECEIVED  -> VALIDATED
VALIDATED -> READY
READY     -> PLANNING
PLANNING  -> RUNNING | WAITING
RUNNING   -> WAITING | COMPLETED
WAITING   -> PLANNING | RUNNING
```

`FAILED` and `ABORTED` remain fail-safe exits from every non-terminal state.

The state machine does not permit shortcut transitions such as `RECEIVED -> READY` or
`READY -> RUNNING`.

## State transition guards

Stage 4.4 evaluates the following canonical guards:

```text
STATE_VERSION_MATCH
SOURCE_STATE_NON_TERMINAL
TARGET_TRANSITION_ALLOWED
STAGE4_3_TASK_ARTIFACT_INTEGRITY
STAGE4_3_TASK_BINDING_INTEGRITY
TASK_STATE_LINEAGE_MATCH
READY_REQUIRES_BOUND_AUTHORIZATION
WAITING_REQUIRES_WAIT_CONTEXT
WAIT_RESUME_REQUIRES_RESOLUTION
COMPLETION_REQUIRES_DECLARED_CRITERIA_SATISFACTION
COMPLETION_REQUIRES_MINIMUM_EVIDENCE_REFERENCES
```

Important semantics:

- `VALIDATED` rechecks the immutable Stage-4.3 task and binding integrity.
- `READY` requires the exact bound authorization reference with
  `execution_authorized=true`; Stage 4.4 does not mint or query authorization.
- entering `WAITING` requires explicit wait context.
- leaving `WAITING` requires explicit resolution metadata.
- `COMPLETED` requires all declared required completion criteria to be marked satisfied
  and at least the configured minimum number of evidence references.
- those evidence references are lifecycle declarations only; Stage 4.4 does **not** claim
  Stage-4.9 evidence capture/proof.
- `FAILED` and `ABORTED` remain available as fail-safe terminal exits even if operational
  task-content validation is no longer trustworthy.

## Durable repository

Stage 4.4 upgrades the isolated Pentest repository from migration **1 → 2**.

Migration:

`pentest_migrations/002_stage4_4_pentest_lifecycle_state.sql`

New tables:

```text
pentest_task_lifecycle
pentest_task_lifecycle_transitions
```

The first table stores the current durable state projection. The second is a lifecycle
transition journal used for concurrency, idempotency, and state reconstruction inside the
Stage-4.4 control.

The journal is **not** the canonical Pentest event runtime. Stage 4.5 remains responsible
for the event contract and event persistence.

Existing Stage-4.3 tasks are backfilled to `RECEIVED` during migration 2.

The Global Mission Orchestrator repository remains migration **53** and is not modified.

## HTTP API

Read contracts:

```text
GET /health
GET /api/pentest/boundary-contract
GET /api/pentest/pip-contract
GET /api/pentest/task-contract
GET /api/pentest/lifecycle-contract
```

Materialize a task and initialize its lifecycle:

```text
POST /api/pentest/tasks
```

Read current state:

```text
GET /api/pentest/tasks/{pentest_task_id}/lifecycle
```

Apply a guarded state transition:

```text
POST /api/pentest/tasks/{pentest_task_id}/lifecycle/transitions
```

Read the Stage-4.4 transition journal:

```text
GET /api/pentest/tasks/{pentest_task_id}/lifecycle/transitions
```

## Deliberate Stage-4.4 boundary

Stage 4.4 enables lifecycle state only. In particular:

- `RUNNING` is a **local workflow lifecycle state**, not proof that a tool or target-side
  execution has started;
- no Stage-4.5 canonical event runtime is emitted;
- no Stage-4.6 workflow orchestrator is invoked;
- no capability/tool runtime is invoked;
- no external network I/O is performed;
- no target actuation occurs;
- no authorization is minted;
- `POST /api/execution/dispatches` remains fail-closed with HTTP `409`.

## Running Stage 4.4

From `D:\mission_orchestrator` in a separate PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE4_4_PENTEST.ps1
```

Equivalent direct command:

```powershell
python -m run.pentest_subsystem --host 127.0.0.1 --port 8790
```

Keep the Global Mission Orchestrator running on port `8780`.

## Regression status in the implementation environment

Validated before packaging:

- Python compile: **PASS**
- focused Stage 4.4: **23 passed**
- Stage 4.1 + 4.2 + 4.3 + 4.4: **71 passed**
- critical Stage-3 + Stage-4 predecessor chain: **130 passed**
- canonical inventory: **1646 tests collected**

The authoritative deployment-host gate remains `STAGE4_4_ACCEPTANCE.ps1`, which ends
with the full historical regression suite.

## Next stage

**Stage 4.5 — Pentest Event Runtime & Contract**
