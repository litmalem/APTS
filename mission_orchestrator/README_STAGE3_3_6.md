# Stage 3.3.6 — Plan Validation & Feasibility Gate

## Purpose

Stage 3.3.6 introduces the first canonical validation gate over the immutable `GENERATED_UNVALIDATED` candidate Plan produced by Stage 3.3.5. The gate is deterministic and local: it verifies that the candidate is still bound to the current Mission planning context and that its task/dependency structure remains structurally and contractually feasible.

The stage deliberately does **not** activate the Plan, compute task readiness, schedule work, ask Governance for authorization, dispatch target actions, or actuate a target.

## Canonical semantics

A successful validation materializes one immutable validation artifact:

- schema: `apts-plan-validation-feasibility-v1`
- identity prefix: `pvalidate-`
- validation version: `1`
- required Mission state: `PLANNING`
- successful status: `VALIDATED_FEASIBLE`
- validation mode: deterministic/local/fail-closed
- persistence store: `mission_plan_validations`
- Mission event: `MISSION_PLAN_VALIDATED_FEASIBLE`
- version-vector domain: `plan_validation_version`

The invariant remains:

```text
PLAN != AUTHORIZATION
FEASIBLE != AUTHORIZED
VALIDATION != ACTIVATION
TASK != DISPATCH
READINESS != PERMISSION
PLANNER != GOVERNANCE
```

## Feasibility checks

Stage 3.3.6 verifies the current Stage-3.3.5 candidate against the canonical planning artifacts already persisted by Stages 3.3.1–3.3.5. The gate checks, at minimum:

1. generated-plan integrity and expected `GENERATED_UNVALIDATED` status;
2. task-decomposition integrity;
3. validated dependency-graph integrity;
4. exact candidate task-set coverage/cardinality;
5. exact dependency-edge cardinality;
6. per-task canonical hash bindings;
7. non-empty required capabilities;
8. required subsystem membership in the Mission contract;
9. expected-output, success-criteria, and evidence-requirement presence;
10. preservation of the non-authorizing/non-dispatching authority boundary.

Any stale or inconsistent binding fails closed.

## API

New read/write surfaces:

```text
POST /api/missions/{mission_id}/plan-validation
GET  /api/missions/{mission_id}/plan-validation
GET  /api/missions/{mission_id}/plan-validation-definition
```

The POST request binds to the current Mission version/state and exact generated Plan ID/hash. It accepts no caller-supplied authorization, feasibility conclusion, readiness, scheduling, dispatch, or execution surface.

## Persistence and migration

Stage 3.3.6 adds:

```text
migrations/014_stage3_3_6_plan_validation_feasibility_gate.sql
```

Repository migration level becomes `14`. The new table is `mission_plan_validations`, with immutable bindings back to Mission/Plan/generated-Plan identities and hashes.

## Authority boundary

After Stage 3.3.6:

```text
planner invocation performed       = true   (Stage 3.3.5)
plan generation performed          = true   (Stage 3.3.5)
feasibility validation performed   = true   (Stage 3.3.6)
plan activation performed          = false
readiness projection performed     = false
scheduling performed               = false
governance authorization authority = EXTERNAL_APTS_GSS
governance query performed         = false
target action dispatch             = false
target actuation                   = false
```

Thus Stage 3.3.6 extends **planning verification**, not operational authority.

## Regression

Stage 3.3.6 adds 20 focused regression tests. The complete repository now contains **401 collected tests** (381 prior baseline + 20 Stage-3.3.6 tests).

Focused validation performed during patch construction:

```text
tests/test_stage3_3_6_plan_validation_feasibility_gate.py
20 passed
```

The supplied acceptance script runs the complete suite on the target Windows repository and requires:

```text
401 passed
```

before executing live API probes.

## Live acceptance

With Mission Orchestrator Stage 3.3.6 running at port 8780:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_6_ACCEPTANCE.ps1
```

Expected terminal result:

```text
==============================================================================
STAGE 3.3.6 ACCEPTANCE: PASS
==============================================================================
```
