# Stage 3.3.2 — Planner Input Snapshot & Context Binding

## Purpose

Stage 3.3.2 advances **Stage 3.3 — Canonical Mission Planning & Task Decomposition** by creating a durable, immutable **planner-input snapshot** from context that is already canonical and locally persisted by the Mission Orchestrator.

The snapshot freezes the exact planning basis that a later planner stage may consume. It is bound to the Stage-3.3.1 canonical Plan identity, the exact `PLANNING` state/version and Stage-3.2.4 activation lineage, the immutable Mission envelope, the Plan-bound canonical Scope when present, the current locally persisted Governance binding when present, and the immutable PIP reference.

Stage 3.3.2 deliberately **does not invoke a planner and does not synthesize a plan or task graph**. It establishes deterministic, auditable planner context first.

The architecture invariants remain explicit:

- `SNAPSHOT != AUTHORIZATION`
- `CONTEXT != PERMISSION`
- `PLAN != AUTHORIZATION`
- `TASK != DISPATCH`
- `READINESS != PERMISSION`
- `PLANNER != GOVERNANCE`

`aptsGSS / GOV-PLANE` remains the sole Governance/authorization authority.

## Runtime contract

The runtime advertises:

- `control_version = stage3.3.2-planner-input-snapshot-context-binding`
- `planner_input_snapshot_schema_version = apts-planner-input-snapshot-v1`
- `planner_input_snapshot_mode = IMMUTABLE_LOCAL_CONTEXT_BOUND_TO_CANONICAL_PLAN_AND_EXACT_PLANNING_STATE`
- `planner_input_snapshot_context_mode = CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH`
- creation state = `PLANNING`
- initial snapshot version = `1`
- Stage-3.3.1 canonical Plan is mandatory
- exact Plan id/version/SHA-256 are mandatory
- exact Mission state version is mandatory
- current Scope must remain exactly the Scope captured by the Plan
- caller-supplied planner output/tasks/dependencies/tools/authorization/dispatch fields are rejected
- one immutable Stage-3.3.2 snapshot per canonical Plan

## What the snapshot binds

The canonical snapshot contains the following context layers.

1. **Mission context** — Mission/envelope identity and hash, mission kind, objective, success criteria, budgets, and required subsystems.
2. **Plan binding** — exact Plan id, version, schema, SHA-256, status, and the still-unmaterialized task graph (`task_count = 0`, `dependency_edge_count = 0`).
3. **Lifecycle context** — exact `PLANNING` state/version, source transition, and complete Stage-3.2.4 planning activation evidence.
4. **Scope context** — the exact Plan-bound canonical Scope contract and hash when Scope existed at Plan registration; otherwise an explicit `UNBOUND` context.
5. **Governance context** — the current locally persisted Governance binding when present. This is constraint context only and never execution permission. No Governance authorization request is performed while snapshotting.
6. **Knowledge context** — immutable PIP id/version reference only. Stage 3.3.2 performs no CTI/knowledge refresh.
7. **Context binding** — a canonical `source_context` plus its own SHA-256, provenance requirement, and `IMMUTABLE_AS_OF_CAPTURE` freshness semantics.

The complete snapshot is itself protected by a canonical SHA-256 integrity digest in the `MISSION_PLANNER_INPUT_SNAPSHOT_V1` hash domain.

## API

### Discover the snapshot contract

`GET /api/missions/{mission_id}/planner-input-snapshot-definition`

The endpoint is available before either the Stage-3.3.1 Plan or Stage-3.3.2 snapshot exists. It reports whether each prerequisite/artifact is registered and exposes the static contract.

### Register the planner-input snapshot

`POST /api/missions/{mission_id}/planner-input-snapshot`

Minimal request after the canonical Plan exists:

```json
{
  "idempotency_key": "snapshot-20260904-001",
  "expected_plan_id": "<current canonical plan id>",
  "expected_plan_version": 1,
  "expected_plan_sha256": "<current canonical plan sha256>",
  "expected_state_version": 3,
  "created_by": "planner-supervisor",
  "reason": "Freeze deterministic local planner context",
  "metadata": {
    "stage": "3.3.2"
  }
}
```

The request is intentionally a **binding/concurrency request**, not planner content. Fields such as `tasks`, `dependencies`, `planner_output`, `tools`, `authorization`, and `dispatch` are rejected.

### Read the stored snapshot

`GET /api/missions/{mission_id}/planner-input-snapshot`

The artifact is reconstructable solely from the Mission repository. Reading it does not query CTI, Governance, or any target system.

## Guard and context-drift semantics

Snapshot creation fails closed unless all of the following are true:

- the Stage-3.3.1 canonical Plan exists and passes integrity verification;
- the request names the exact Plan id/version/SHA-256;
- the Mission is still in the exact `PLANNING` state/version to which the Plan was bound;
- the Plan source transition still resolves to the exact Stage-3.2.4 guarded `START_PLANNING` activation lineage;
- the current canonical Scope head exactly matches the Scope captured by the Plan;
- if a local Governance binding exists, it passes integrity verification and is still bound to that exact Scope snapshot.

This prevents a planner from later receiving a silent mixture of a Plan created under one context and Scope/Governance state that changed afterward. Context drift must be resolved by a later explicit planning/revision stage rather than hidden inside snapshot construction.

## Persistence, event lineage, and versioning

Stage 3.3.2 introduces migration:

- `migrations/010_stage3_3_2_planner_input_snapshot_context_binding.sql`

Repository migration level advances from `9` to `10`.

New store:

- `mission_planner_input_snapshots`

The store retains the canonical JSON, canonical SHA-256, request fingerprint, idempotency key, exact Plan identity/version/hash, source state version, creator/reason, and creation timestamp.

A successful snapshot registration appends exactly one canonical Mission event:

- `MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED`

The Mission version vector now includes `planner_input_snapshot_version`, which is `0` before snapshot registration and `1` after registration. The repository persistence manifest and integrity checks include the new store/artifact.

## Idempotency and immutability

An exact retry with the same idempotency key and identical canonical request returns the same snapshot identity/hash and does not create a duplicate store row or duplicate registration event.

The following fail closed:

- same idempotency key with a different request;
- a second Stage-3.3.2 snapshot for the same canonical Plan;
- stale Plan id/version/hash tokens;
- stale Mission state version;
- snapshot creation outside `PLANNING`;
- a Plan not bound to the current `PLANNING` version;
- Scope drift after Plan creation;
- stale/misaligned local Governance context;
- caller-supplied planner/task/action/authorization material.

## Authority and execution boundary

Stage 3.3.2 only prepares **planner input**. It does not increase operational authority:

- planner input readiness: **true**;
- planner invocation: **false**;
- plan synthesis: **false**;
- task decomposition/materialization: **false**;
- Plan revision: **false**;
- external CTI/context refresh: **false**;
- Governance authorization query: **false**;
- target-action dispatch: **false**;
- target actuation: **false**;
- snapshot is authorization: **false**;
- context is permission: **false**.

## Regression

Stage 3.3.2 adds `tests/test_stage3_3_2_planner_input_snapshot_context_binding.py` with **16 focused tests** covering contract discovery, guards, Plan/state/PIP/Scope binding, context drift, immutability, idempotency, integrity verification, version-vector lineage, events, persistence/reconstruction, and zero external reads.

Validated baseline:

- `python -m compileall -q mission_orchestrator tests` — PASS
- focused Stage-3.3.2 tests — **16 passed**
- `python -m pytest -q` — **296 passed**

## Live acceptance

After starting Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_2_ACCEPTANCE.ps1
```

Expected final output:

```text
==============================================================================
STAGE 3.3.2 ACCEPTANCE: PASS
==============================================================================
```
