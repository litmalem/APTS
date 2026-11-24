# Stage 3.3.4 — Task Dependency Graph & Structural Validation

## Purpose

Stage 3.3.4 materializes the dependency structure that Stage 3.3.3 deliberately left `NOT_MATERIALIZED`. It converts the exact canonical planned-task set into one immutable, deterministic directed acyclic graph (DAG) and validates graph structure before any planner invocation, readiness projection, scheduling, Governance authorization, dispatch, or target actuation is allowed.

The Stage-3.3 planning chain is now:

```text
Canonical Mission
  -> Canonical Plan (3.3.1)
  -> Planner Input Snapshot (3.3.2)
  -> Canonical Task Decomposition (3.3.3)
  -> Task Dependency Graph + Structural Validation (3.3.4)
```

## Canonical graph contract

Graph schema:

`apts-canonical-task-dependency-graph-v1`

Edge schema:

`apts-canonical-task-dependency-edge-v1`

Identity namespaces:

- graph: `mgraph-*`
- dependency edge: `medge-*`

Initial graph version: `1`.

Registration state: `PLANNING` only.

Graph mode:

`IMMUTABLE_COMPLETE_DAG_BOUND_TO_EXACT_CANONICAL_TASK_DECOMPOSITION`

## Dependency semantics

An edge:

```json
{"from_task_key":"collect-cti","to_task_key":"analyze-cti"}
```

means **`collect-cti` is a prerequisite that must precede `analyze-cti`**.

Stage 3.3.4 materializes every Stage-3.3.3 canonical planned task as a graph node. Tasks with no incoming or outgoing edge are valid isolated nodes; they are not silently removed from the graph.

## Structural validation

Registration is fail-closed. The graph is rejected if any of the following is detected:

- graph node set does not correspond to the exact canonical Stage-3.3.3 task set;
- dangling `from_task_key` or `to_task_key`;
- self dependency;
- duplicate directed edge;
- directed cycle;
- incomplete or invalid topological ordering;
- stale Plan/snapshot/decomposition/task-set/state/version binding;
- local Scope or Governance binding drift since the Stage-3.3.2 planner-input snapshot.

A successful graph includes deterministic topological order, root tasks, leaf tasks, isolated tasks, per-task incoming/outgoing dependency bindings, node-set SHA-256, edge-set SHA-256, and canonical graph SHA-256.

## Immutability and concurrency

Exactly one Stage-3.3.4 graph may be registered for the current Stage-3.3.3 decomposition. The request is bound to:

- current Mission version SHA-256;
- Plan identity/version/SHA-256;
- planner-input snapshot identity/version/SHA-256;
- task decomposition identity/version/SHA-256;
- task-set SHA-256;
- current canonical state version.

Equivalent edge arrays are canonicalized before request fingerprinting, so order-only differences replay idempotently. Reusing an idempotency key for a different graph fails closed.

## Persistence

Migration `012_stage3_3_4_task_dependency_graph_structural_validation.sql` adds:

- `mission_task_dependency_graphs`
- `mission_task_dependency_edges`

Repository migration level advances from `11` to `12`.

The persistence manifest and repository integrity reconstruction now include the graph and normalized edge store. Restart reconstruction uses durable local state and does not invoke the planner or external authorities.

## Version vector

A new local version domain is exposed:

`task_dependency_graph_version`

It is `0` before graph registration and `1` after the immutable Stage-3.3.4 graph is registered. Stage-3.3.1 Plan, Stage-3.3.2 snapshot, and Stage-3.3.3 decomposition versions are not mutated by graph registration.

## Mission events

Successful registration emits exactly one canonical event:

`MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED`

Exact idempotent replay does not append a duplicate event.

## API

New read/write surface:

- `GET /api/missions/{mission_id}/task-dependency-graph-definition`
- `POST /api/missions/{mission_id}/task-dependency-graph`
- `GET /api/missions/{mission_id}/task-dependency-graph`
- `GET /api/missions/{mission_id}/task-dependency-edges`

## Authority boundary

Stage 3.3.4 is structural planning control only.

```text
PLAN != AUTHORIZATION
TASK != DISPATCH
GRAPH != SCHEDULING
READINESS != PERMISSION
PLANNER != GOVERNANCE
```

The following remain false:

- planner invocation;
- planner-output consumption;
- readiness projection;
- scheduling;
- Governance authorization query;
- target-action dispatch;
- target actuation.

`EXTERNAL_APTS_GSS` remains the sole Governance/authorization authority.

## Validation

Patch-local validation:

- focused Stage-3.3.4 tests: **29 passed**;
- full Stage-3 regression: **344 passed**.

Run live acceptance after restarting Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_4_ACCEPTANCE.ps1
```

Expected final verdict:

```text
==============================================================================
STAGE 3.3.4 ACCEPTANCE: PASS
==============================================================================
```
