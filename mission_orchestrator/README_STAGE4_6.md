# Stage 4.6 — Pentest Workflow Orchestrator Skeleton

## Status

Implementation candidate for deployment-host acceptance.

Stage 4.6 extends the Stage-4.5 durable Pentest event runtime with the first **local Pentest
workflow orchestrator skeleton**. It deliberately remains non-agentic and non-executing: the
orchestrator can receive a Pentest task, track workflow state, assign one fixed placeholder
worker, accept a structured result, and close the existing guarded lifecycle, but it cannot yet
reason, replan, select capabilities, invoke tools, perform network I/O, or actuate a target.

The Global Mission Orchestrator remains closed at:

`stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`

The active Pentest control becomes:

`stage4.6-pentest-workflow-orchestrator-skeleton`

Default endpoints:

- Global Mission Orchestrator: `http://127.0.0.1:8780`
- Pentest Subsystem: `http://127.0.0.1:8790`

## Roadmap objective

Stage 4.6 implements the roadmap skeleton:

```text
receive task
→ track workflow
→ assign placeholder worker
→ maintain state
→ receive result
→ close task
```

Full reasoning and replanning are intentionally deferred. The Stage-4.6 deliverable is the
**local Pentest orchestrator skeleton**, not specialist-agent autonomy or controlled target
execution.

## Canonical contract

`pentest_subsystem/workflow_contract.py` adds:

- control contract: `apts-stage4.6-pentest-workflow-orchestrator-skeleton-v1`
- workflow schema: `apts-pentest-workflow-v1`
- start request schema: `apts-pentest-workflow-start-request-v1`
- result schema: `apts-pentest-workflow-result-v1`
- control version: `stage4.6-pentest-workflow-orchestrator-skeleton`
- exact SHA-256 binding to the Stage-4.5 event-runtime contract
- deterministic `pworkflow-...` identity derived from `pentest_task_id`

The orchestrator has one fixed worker assignment:

```text
worker_id           = PENTEST_PLACEHOLDER_WORKER
worker_kind         = PLACEHOLDER
tool_access         = false
execution_authority = false
```

The start/result request schemas reject arbitrary worker, command, or tool fields. Extension
metadata must remain under the canonical `metadata` object.

## Workflow state and existing lifecycle authority

Stage 4.6 does not introduce a second Pentest lifecycle authority. It composes the existing
Stage-4.4 guarded lifecycle and Stage-4.5 event runtime.

Starting a workflow from a newly materialized task advances the canonical path:

```text
RECEIVED
  ↓
VALIDATED
  ↓
READY
  ↓
PLANNING
  ↓
RUNNING
```

Each state transition is committed through the Stage-4.4 transition guards and is therefore
projected into the Stage-4.5 append-only event stream.

A successful structured placeholder result closes through:

```text
RUNNING → COMPLETED
```

A failed structured placeholder result closes fail-safe through:

```text
RUNNING → FAILED
```

For `SUCCEEDED`, the result must satisfy the immutable Stage-4.3 task completion contract:
minimum evidence references and every required completion criterion must be present before
closure is accepted.

`RUNNING` remains a **local workflow/lifecycle state**. It does not mean a target-side command
was dispatched or executed.

## Idempotency and restart behavior

Workflow identity is deterministic per `pentest_task_id`. A start request is persisted before
lifecycle progression and can be safely replayed using the same request and idempotency key.
Exact replay returns the same workflow and does not duplicate lifecycle transitions or events.

Result intake is likewise immutable and idempotent. Exact replay returns the same result and
does not duplicate the terminal lifecycle event.

The repository can resume an already-persisted `STARTING` workflow after interruption by
applying only missing lifecycle transitions. Existing Stage-4.5 event reconciliation remains
active.

## Durable repository

Stage 4.6 upgrades the isolated Pentest repository from migration **3 → 4**.

Migration:

`pentest_migrations/004_stage4_6_pentest_workflow_orchestrator_skeleton.sql`

New tables:

```text
pentest_workflows
pentest_workflow_results
```

The stores retain mission/Pentest/task lineage, workflow and result request hashes,
idempotency identities, fixed worker assignment, terminal status, and timestamps.

The Global Mission Orchestrator repository remains migration **53** and is not modified.

## HTTP API

Historical Stage-4.1 through Stage-4.5 contract and query endpoints remain available.

Stage-4.6 contract:

```text
GET /api/pentest/workflow-contract
GET /api/contracts/pentest-workflow
```

Workflow operations:

```text
POST /api/pentest/tasks/{pentest_task_id}/workflow/start
GET  /api/pentest/tasks/{pentest_task_id}/workflow
GET  /api/pentest/workflows
GET  /api/pentest/workflows/{workflow_id}
POST /api/pentest/workflows/{workflow_id}/result
GET  /api/pentest/workflows/{workflow_id}/result
```

`GET /api/pentest/workflows` supports exact filters:

```text
mission_id
pentest_id
workflow_status
limit
```

The existing event endpoints remain the canonical history source for task materialization and
lifecycle transitions.

## Deliberate Stage-4.6 boundary

Stage 4.6 enables orchestration mechanics only. Explicitly disabled:

- full reasoning;
- replanning;
- Stage-4.7 capability registry and capability selection;
- arbitrary worker selection;
- execution intake/dispatch;
- command or tool invocation;
- external network I/O;
- target actuation;
- authorization minting;
- Stage-4.9 evidence/finding proof semantics.

`POST /api/execution/dispatches` remains fail-closed with HTTP `409` and
`STAGE4_6_EXECUTION_INTAKE_NOT_ENABLED`.

## Running Stage 4.6

From `D:\mission_orchestrator` in a separate PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE4_6_PENTEST.ps1
```

Equivalent direct command:

```powershell
python -m run.pentest_subsystem --host 127.0.0.1 --port 8790
```

Keep the Global Mission Orchestrator running on port `8780`.

## Regression status in the implementation environment

Validated before packaging:

- Python compile: **PASS**
- focused Stage 4.6: **26 passed**
- Stage 4.1 → 4.6: **122 passed**
- critical Stage-3 + Stage-4 predecessor chain: **181 passed**
- canonical inventory: **1697 tests collected**

The authoritative deployment-host gate is `STAGE4_6_ACCEPTANCE.ps1`. It validates the live
runtime and then runs the full historical regression suite as the final PASS/FAIL authority.
The full 1697-test execution was not run in this packaging environment.

## Next stage

**Stage 4.7 — Capability Registry & Tool Contract**
