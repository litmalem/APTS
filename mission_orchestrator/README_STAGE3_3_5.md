# Stage 3.3.5 — Planner Invocation & Plan Generation

## Purpose

Stage 3.3.5 is the first Stage-3.3 increment that **actually invokes a planner**. It consumes the exact immutable canonical planning artifacts already established by Stage 3.3.1–3.3.4 and materializes one deterministic candidate plan without crossing into authorization, scheduling, readiness, or execution authority.

The canonical planning chain is now:

```text
Canonical Mission
  -> Canonical Plan (3.3.1)
  -> Planner Input Snapshot (3.3.2)
  -> Canonical Task Decomposition (3.3.3)
  -> Validated Dependency DAG (3.3.4)
  -> Planner Invocation + GENERATED_UNVALIDATED Candidate Plan (3.3.5)
```

The planner is intentionally local and deterministic for this stage. It does not call an external LLM/model provider or perform network I/O. This gives Stage 3.3.5 a reproducible, auditable planner boundary before later stages add feasibility validation, replanning/version supersession, or readiness/scheduling semantics.

## Planner contracts

Planner invocation schema:

`apts-planner-invocation-v1`

Generated plan schema:

`apts-generated-mission-plan-v1`

Identity namespaces:

- planner invocation: `pinvoke-*`
- generated candidate plan: `pgen-*`

Initial generation version: `1`.

Required Mission lifecycle state: `PLANNING`.

Generated candidate status:

`GENERATED_UNVALIDATED`

Planner profile:

`CANONICAL_DAG_STRUCTURAL_PLANNER_V1`

Planner engine:

`APTS_MO_LOCAL_DETERMINISTIC_GRAPH_PLANNER`

Planning strategy:

`DEPENDENCY_LAYERED_TOPOLOGICAL_V1`

## Exact input binding

Invocation is fail-closed and is bound to the current canonical Mission version vector plus exact identity/version/hash values for:

- Stage-3.3.1 canonical Plan;
- Stage-3.3.2 planner-input snapshot;
- Stage-3.3.3 task decomposition;
- Stage-3.3.3 task-set SHA-256;
- Stage-3.3.4 validated dependency graph;
- Stage-3.3.4 node-set SHA-256;
- Stage-3.3.4 edge-set SHA-256;
- current `PLANNING` state version.

The snapshot context is rechecked against the current local Scope/Governance heads before invocation. Stale state, stale Plan/snapshot/decomposition/graph bindings, or context drift fail closed.

## Deterministic plan generation

The Stage-3.3.5 planner consumes canonical planned-task contracts and the validated DAG. It derives:

- deterministic topological task order;
- per-task dependency references;
- dependency-layered planning groups;
- plan steps containing task objective, required subsystem/capability, preconditions, expected outputs, success criteria, evidence requirements, and priority;
- candidate task/dependency/layer cardinalities;
- canonical planner-output SHA-256.

Parallelism may be identified structurally when multiple tasks occupy the same dependency layer. This is **not** a readiness decision and **not** an execution schedule.

## Persistence and idempotency

Migration `013_stage3_3_5_planner_invocation_plan_generation.sql` adds:

- `mission_planner_invocations`
- `mission_generated_plans`

Repository migration level advances from `12` to `13`.

Planner invocation evidence and the generated candidate plan are persisted transactionally. Exactly one immutable Stage-3.3.5 generation is allowed for the current canonical Plan version. Exact request replay is idempotent and does not duplicate Mission events.

The persistence manifest and repository-integrity projection now include both stores. Durable restart reconstruction reads the committed planner artifacts and **does not rerun the planner**.

## Version vector

A new local version domain is exposed:

`planner_generation_version`

It is `0` before Stage-3.3.5 invocation and `1` after successful immutable generation. Stage-3.3.1 Plan, Stage-3.3.2 snapshot, Stage-3.3.3 decomposition, and Stage-3.3.4 graph versions remain unchanged.

## Mission events

Successful generation emits exactly one of each:

- `MISSION_PLANNER_INVOKED`
- `MISSION_PLAN_GENERATED`

Exact idempotent replay does not append duplicates.

## API

New Stage-3.3.5 surface:

- `GET /api/missions/{mission_id}/planner-generation-definition`
- `POST /api/missions/{mission_id}/planner-invocation`
- `GET /api/missions/{mission_id}/planner-invocation`
- `GET /api/missions/{mission_id}/generated-plan`

The POST request does not accept caller-supplied tasks, dependency graphs, planner output, prompt/model/provider selection, readiness, schedule, authorization, dispatch, tools, or execution commands. The planner output is produced by the configured Stage-3.3.5 planner from canonical artifacts only.

## Authority boundary

Stage 3.3.5 enables planning cognition, not operational authority.

```text
PLAN != AUTHORIZATION
TASK != DISPATCH
READINESS != PERMISSION
PLANNER != GOVERNANCE
```

The following remain false:

- external model invocation;
- external planner network I/O;
- Stage-3.3.6 feasibility validation;
- plan activation;
- Stage-3.3.8 readiness projection;
- scheduling;
- Governance authorization query;
- target-action dispatch;
- target actuation.

`EXTERNAL_APTS_GSS` remains the sole Governance/authorization authority.

## Validation

Patch-local validation:

- focused Stage-3.3.5 regression: **37 passed**;
- full regression: **381 passed**.

Run live acceptance after applying migration 013 and restarting Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_5_ACCEPTANCE.ps1
```

Expected final verdict:

```text
==============================================================================
STAGE 3.3.5 ACCEPTANCE: PASS
==============================================================================
```
