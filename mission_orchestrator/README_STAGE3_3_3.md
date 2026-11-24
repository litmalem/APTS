# Stage 3.3.3 — Canonical Task Decomposition Contract

## Purpose

Stage 3.3.3 materializes the first **canonical structured planned-task contracts** for a Mission. It converts an already registered Stage-3.3.1 canonical Plan plus the exact immutable Stage-3.3.2 planner-input snapshot into a durable, hash-verifiable task set owned by `APTS-MO01`.

This stage is intentionally **not** the dependency-graph stage and **not** the planner-invocation stage. Stage 3.3.3 defines *what a planned task is* and binds each task to exact Mission/Plan/snapshot context. Stage 3.3.4 will materialize and validate dependency/DAG structure; Stage 3.3.5 will introduce actual planner invocation.

The engineering rationale follows the project’s Agentic-AI model: planning decomposes goals into structured work units, while action/tool use and authorization remain separate control concerns. This preserves traceability and bounded autonomy rather than conflating a proposed task with permission to execute it.

## Canonical invariants

- `PLAN != AUTHORIZATION`
- `DECOMPOSITION != AUTHORIZATION`
- `TASK != DISPATCH`
- `READINESS != PERMISSION`
- `PLANNER != GOVERNANCE`
- Stage 3.3.3 does **not** invoke a planner.
- Stage 3.3.3 does **not** materialize dependency edges or perform DAG validation.
- Stage 3.3.3 does **not** query Governance authorization.
- Stage 3.3.3 does **not** dispatch or actuate target actions.
- Stage 3.3.3 does **not** mutate the immutable Stage-3.3.1 Plan or Stage-3.3.2 snapshot.

`aptsGSS / GOV-PLANE` remains the sole Governance/authorization authority.

## Runtime contract

The active runtime advertises:

- `control_version = stage3.3.3-canonical-task-decomposition-contract`
- `task_decomposition_schema_version = apts-canonical-task-decomposition-v1`
- `planned_task_schema_version = apts-canonical-planned-task-v1`
- decomposition identity prefix = `mdecomp-*`
- planned-task identity prefix = `ptask-*`
- initial decomposition version = `1`
- creation state = `PLANNING`
- maximum planned tasks per Stage-3.3.3 decomposition = `128`
- task materialization status = `TASKS_MATERIALIZED`
- dependency graph status = `NOT_MATERIALIZED`
- planner invocation = `false`
- dependency validation = `false`
- Governance query = `false`
- target dispatch = `false`
- target actuation = `false`

## Prerequisites

Task decomposition fails closed unless:

1. the canonical Mission exists;
2. the Stage-3.3.1 Plan exists and verifies;
3. the Stage-3.3.2 planner-input snapshot exists and verifies;
4. exact Plan id/version/SHA-256 tokens match;
5. exact snapshot id/version/SHA-256 tokens match;
6. exact current Mission version-vector SHA-256 matches;
7. Mission is still in the exact snapshot-bound `PLANNING` state/version;
8. the Stage-3.3.2 snapshot is marked planner-input ready;
9. Plan/snapshot still expose a zero-task `NOT_MATERIALIZED` graph boundary;
10. current Scope/Governance local heads still exactly match the snapshot context;
11. every planned task targets a subsystem already declared in the canonical Mission `required_subsystems`.

Any context drift requires a later explicit planning/revision workflow rather than hidden rebinding.

## Task contract

A Stage-3.3.3 task is a structured artifact with fields such as:

```json
{
  "task_key": "collect-cti",
  "task_type": "CTI_COLLECTION",
  "objective": {
    "goal": "Collect relevant canonical CTI context"
  },
  "required_capability": "cti.read.context",
  "required_subsystem": "CTI",
  "preconditions": [
    {"kind": "PIP_BOUND", "required": true}
  ],
  "expected_outputs": [
    {"artifact": "cti_context", "format": "STRUCTURED"}
  ],
  "success_criteria": [
    {"metric": "cti_context_available", "expected": true}
  ],
  "evidence_requirements": [
    {"type": "SOURCE_PROVENANCE"}
  ],
  "priority": 10,
  "metadata": {}
}
```

Each materialized task receives a canonical `ptask-*` identity and SHA-256 integrity digest. Its dependency binding is explicitly initialized as:

```json
{
  "status": "NOT_MATERIALIZED",
  "dependencies": [],
  "dependency_edge_count": 0,
  "structural_validation_performed": false
}
```

Fields such as `dependencies`, `depends_on`, `tools`, `authorization`, `dispatch`, `target_action`, or `execution_command` are rejected at the authoritative Stage-3.3.3 task surface. They belong to later graph/execution/authorization stages.

## Decomposition artifact

The complete `mdecomp-*` artifact binds:

- Mission id;
- exact Plan id/version/SHA-256;
- exact planner-input snapshot id/version/SHA-256;
- exact Mission version-vector SHA-256 before decomposition;
- exact `PLANNING` state/version;
- snapshot context hash;
- Mission envelope hash;
- Scope snapshot/hash when bound;
- local Governance-binding snapshot/hash when bound;
- PIP id/version;
- ordered planned-task contracts;
- canonical task-set SHA-256;
- provenance and creator/reason metadata.

The decomposition and every task are immutable/hash-verifiable artifacts.

## API

### Discover contract

`GET /api/missions/{mission_id}/task-decomposition-definition`

### Register one canonical decomposition

`POST /api/missions/{mission_id}/task-decomposition`

The request carries exact Mission/Plan/snapshot concurrency tokens and a structured `tasks` array. It does not carry planner output, dependency graph, authorization, or dispatch instructions.

### Read decomposition

`GET /api/missions/{mission_id}/task-decomposition`

### List planned tasks

`GET /api/missions/{mission_id}/planned-tasks`

### Read one planned task

`GET /api/missions/{mission_id}/planned-tasks/{planned_task_id}`

## Idempotency and immutability

An exact retry with the same idempotency key and identical canonical request returns the same `mdecomp-*` identity/hash without creating duplicate tasks or duplicate registration events.

Fail-closed cases include:

- same idempotency key with different canonical content;
- second decomposition under the current Stage-3.3.3 single-Plan model;
- stale Mission version hash;
- stale Plan identity/version/hash;
- stale snapshot identity/version/hash;
- stale state version;
- Mission no longer in `PLANNING`;
- Scope/Governance context drift after snapshot capture;
- undeclared `required_subsystem`;
- empty/duplicate/invalid task contracts;
- premature dependency/tool/authorization/dispatch fields.

## Persistence and migration

Stage 3.3.3 adds:

- `migrations/011_stage3_3_3_canonical_task_decomposition_contract.sql`
- `mission_task_decompositions`
- `mission_planned_tasks`

Repository migration level advances:

`10 -> 11`

The repository persistence manifest, record counts, restart reconstruction, and integrity checks now include both stores.

## Event lineage and versioning

A successful registration appends exactly one canonical Mission event:

`MISSION_TASK_DECOMPOSITION_REGISTERED`

The Mission version vector adds:

`task_decomposition_version`

It is `0` before decomposition and `1` after the Stage-3.3.3 artifact is committed. No routed-task count is increased and no dispatch state is created.

## Validation

Stage 3.3.3 adds **19 focused tests** covering contract discovery, prerequisite guards, canonical task materialization, exact bindings, idempotency, typed conflicts, stale tokens, schema restrictions, Scope drift, state drift, Plan/snapshot immutability, version-vector lineage, task read models, Mission event cardinality, persistence/restart reconstruction, integrity tampering, typed not-found behavior, and migration invariants.

Validated baseline:

- `python -m compileall -q mission_orchestrator tests` — PASS
- focused Stage-3.3.3 tests — **19 passed**
- `python -m pytest -q` — **315 passed**

## Live acceptance

After installing migration 011 and restarting the Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_3_ACCEPTANCE.ps1
```

Expected final output:

```text
==============================================================================
STAGE 3.3.3 ACCEPTANCE: PASS
==============================================================================
```

A PASS means Stage 3.3.3 is accepted and the next implementation boundary is **3.3.4 — Task Dependency Graph & Structural Validation**.
