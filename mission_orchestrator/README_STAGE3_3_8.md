# Stage 3.3.8 — Task Readiness & Scheduling Projection

## Purpose

Stage 3.3.8 projects the currently active Stage-3.3.7 canonical Plan into a deterministic **structural task-readiness view** and a **dependency-wave scheduling projection**.

This stage answers two planning questions only:

1. Which planned tasks are structurally ready because they have no predecessor dependencies?
2. In which dependency layers/waves can the canonical task graph be considered for later scheduling?

It does **not** authorize, dispatch, execute, actuate, assign runtime resources, or create wall-clock schedules.

## Active control

- `control_version = stage3.3.8-task-readiness-scheduling-projection`
- HTTP server = `APTSMissionOrchestrator/3.3.8`
- projection schema = `apts-task-readiness-scheduling-projection-v1`
- repository migration level = `16`
- version-vector domain = `task_readiness_projection_version`
- persistence store = `mission_task_readiness_projections`

## Canonical semantics

A projection can be created only when:

- Mission state is `PLANNING` or `REPLANNING`;
- an active Stage-3.3.7 Plan head exists;
- the caller presents the exact Mission state version and version-vector SHA-256;
- the caller presents the exact active Plan record ID, Plan version, and active Plan SHA-256;
- the active Plan-version contract passes integrity verification;
- that Plan version does not already have a projection.

The projection is immutable and one-to-one with a Plan version.

### Readiness states

Stage 3.3.8 deliberately uses only structural readiness:

- `READY` — task has no predecessor dependency in the canonical DAG;
- `BLOCKED_DEPENDENCY` — task has one or more predecessor task keys.

For each task, the projection records the dependency keys, unmet dependency keys, planning layer, required subsystem/capability, and explicit boundary markers:

```text
authorization_granted = false
dispatch_performed    = false
```

`READY` therefore means *structurally eligible in the Plan graph*, not *authorized to execute*.

## Scheduling projection

The scheduling view is:

```text
DEPENDENCY_LAYER_WAVES_NO_CLOCK_NO_RESOURCE_ASSIGNMENT
```

Each validated planning layer becomes one deterministic wave. A wave may identify parallelism candidates when it contains multiple tasks, but it does not assign agents/workers, timestamps, start times, deadlines, or runtime resources.

```text
Plan DAG
  |
  +-- Wave 1: root task(s)
  |
  +-- Wave 2: tasks whose predecessors are in earlier layers
  |
  +-- Wave N: later dependency layer
```

Every wave explicitly declares:

```text
clock_time_assigned            = false
resource_assignment_performed = false
dispatch_performed             = false
```

## Replanning and supersession

Readiness projections follow Plan-version lineage rather than mutating in place.

```text
Plan v1  -> readiness projection v1  -> effective SUPERSEDED
   |
   +-- REPLANNING -> Plan v2
                         |
                         +-> readiness projection v2 -> ACTIVE
```

The v1 projection remains immutable. Effective status is derived from the current Stage-3.3.7 active Plan head.

## Idempotency and concurrency

Exact replay of the same `idempotency_key` and canonical request returns the same projection without creating a duplicate event.

Stage 3.3.8 fails closed on:

- stale Mission `state_version`;
- stale version-vector SHA-256;
- stale active Plan record ID/version/hash;
- a second projection for the same Plan version;
- reuse of an idempotency key with different canonical content;
- caller-supplied task status, completion, authorization, permission, schedule, resource assignment, dispatch, execution, or target-action fields.

## Event lineage

Stage 3.3.8 adds:

```text
MISSION_TASK_READINESS_PROJECTED
```

The event is bound to the projection identity and Plan version. Exact replay creates no duplicate event.

## Persistence and restart

Migration `016_stage3_3_8_task_readiness_scheduling_projection.sql` adds `mission_task_readiness_projections` with one immutable projection per Mission/Plan version.

Repository integrity verifies:

- projection hash integrity;
- exact Plan-version identity/hash binding;
- exact candidate Plan hash binding;
- uniqueness by Plan version;
- persistence-manifest cardinality.

A restart reconstructs the active projection from the repository without re-running the planner or querying an external authority.

## Authority boundary

The Stage-3 planning invariants remain mandatory:

```text
PLAN      != AUTHORIZATION
TASK      != DISPATCH
READINESS != PERMISSION
PLANNER   != GOVERNANCE
```

Runtime declarations remain:

- Governance authority = `EXTERNAL_APTS_GSS`;
- Governance authorization query during projection = `false`;
- `READY` is authorized = `false`;
- wall-clock scheduling = `false`;
- resource assignment = `false`;
- target-action dispatch = `false`;
- target actuation = `false`.

## APIs

```text
GET  /api/missions/{mission_id}/task-readiness-projection-definition
POST /api/missions/{mission_id}/task-readiness-projection
GET  /api/missions/{mission_id}/task-readiness-projection
GET  /api/missions/{mission_id}/task-readiness-projections
```

## Regression

Stage 3.3.8 adds `tests/test_stage3_3_8_task_readiness_scheduling_projection.py` with 28 collected cases.

Patch validation by test partitions:

```text
Stage 3.1 tests : 111 passed
Stage 3.2 tests : 156 passed
Stage 3.3 tests : 189 passed (all Stage-3.3 files verified; 3.3.8 = 28 passed)
Total          : 456 tests
```

## Live acceptance

After applying migration 016 and restarting Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_8_ACCEPTANCE.ps1
```

Expected final result:

```text
==============================================================================
STAGE 3.3.8 ACCEPTANCE: PASS
==============================================================================
```
