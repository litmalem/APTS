# Stage 3.3.10 — Planning Acceptance & Regression Gate

## Purpose

Stage 3.3.10 closes **Stage 3.3 — Canonical Mission Planning & Task Decomposition**. It is a release/closure gate only; it does not add a new planner, authorization authority, scheduler, dispatch path, durable store, or database migration.

The gate proves that Stage 3.3.1 through Stage 3.3.9 compose correctly as one canonical planning stack:

```text
Mission in PLANNING
      |
      +-> Canonical Plan Contract
      +-> Planner Input Snapshot
      +-> Canonical Task Decomposition
      +-> Validated Dependency DAG
      +-> Deterministic Planner Invocation
      +-> GENERATED_UNVALIDATED Candidate Plan
      +-> VALIDATED_FEASIBLE Plan
      +-> Active Plan Version / Replanning Successor
      +-> Structural Task Readiness + Dependency Waves
      +-> Planning Event Replay + Durable Recovery Checkpoint
```

## Active control

- `control_version = stage3.3.10-planning-acceptance-regression-gate`
- HTTP server = `APTSMissionOrchestrator/3.3.10`
- closure schema = `apts-mission-stage3.3-planning-acceptance-gate-v1`
- closure mode = `FULL_REGRESSION_PLUS_LIVE_CANONICAL_PLANNING_PROBES`
- closure baseline = `STAGE_3_3_1_THROUGH_3_3_9`
- repository migration level = `17`
- database change mode = `NO_NEW_DATABASE_MIGRATION`

The runtime only **declares** the acceptance contract. It never self-certifies that the external acceptance script has executed or passed.

## Stage-3.3 closure scope

The acceptance gate covers:

1. Stage 3.3.1 — Canonical Plan Contract & Identity.
2. Stage 3.3.2 — Planner Input Snapshot & Context Binding.
3. Stage 3.3.3 — Canonical Task Decomposition Contract.
4. Stage 3.3.4 — Task Dependency Graph & Structural Validation.
5. Stage 3.3.5 — Planner Invocation & Plan Generation.
6. Stage 3.3.6 — Plan Validation & Feasibility Gate.
7. Stage 3.3.7 — Plan Versioning, Replanning & Supersession.
8. Stage 3.3.8 — Task Readiness & Scheduling Projection.
9. Stage 3.3.9 — Planning Event Lineage, Replay & Recovery.
10. Stage 3.3.10 — Planning Acceptance & Regression Gate.

## Closure invariants

The Stage-3.3 cognitive/planning capability is active, but authority remains bounded:

```text
PLAN      != AUTHORIZATION
TASK      != DISPATCH
READINESS != PERMISSION
PLANNER   != GOVERNANCE
REPLAY    != EXECUTION
RECOVERY  != AUTHORIZATION
```

The local deterministic Stage-3.3.5 planner remains available. Stage 3.3.10 adds no second planner capability and does not widen its authority.

Required runtime invariants remain:

```text
governance_authorization_authority = EXTERNAL_APTS_GSS
external model invocation          = false
external planning network I/O      = false
wall-clock scheduling              = false
resource assignment                = false
task dispatch added                = false
target action dispatch             = false
target actuation                   = false
```

## Database compatibility

Stage 3.3.10 introduces **no migration** and **no durable store**.

The latest migration remains:

```text
migrations/017_stage3_3_9_planning_event_lineage_replay_recovery.sql
```

Expected repository migration level remains `17`.

Do not create migration `018` for Stage 3.3.10.

## Regression

Stage 3.3.10 adds:

```text
tests/test_stage3_3_10_planning_acceptance_regression_gate.py
```

with **12 closure cases** covering:

- Stage-3.3 health/closure metadata;
- static acceptance contract;
- end-to-end Stage-3.3.1–3.3.9 artifact materialization;
- exact canonical hash/binding lineage;
- planning event lineage and deterministic replay;
- read-only replay/recovery behavior;
- restart reconstruction without external work;
- replanning successor/supersession across Plan/readiness/recovery artifacts;
- planning version-vector heads;
- repository manifest and integrity;
- no migration/store expansion;
- final planning/Governance/scheduling/execution authority matrix.

Collected regression baseline:

```text
Stage 3.1                 : 111 passed
Stage 3.2                 : 156 passed
Stage 3.3.1–3.3.4         : 77 passed
Stage 3.3.5–3.3.6         : 57 passed
Stage 3.3.7               : 27 passed
Stage 3.3.8               : 28 passed
Stage 3.3.9               : 38 passed
Stage 3.3.10              : 12 passed
Total                     : 506 tests
```

`python -m pytest --collect-only -q` confirms **506 tests collected**.

## Live acceptance

After applying the patch and restarting the Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_10_ACCEPTANCE.ps1
```

Expected final result:

```text
==============================================================================
STAGE 3.3.10 ACCEPTANCE: PASS
==============================================================================
```

A PASS closes Stage 3.3 and establishes the canonical planning regression baseline for the next Mission Orchestrator workstream.
