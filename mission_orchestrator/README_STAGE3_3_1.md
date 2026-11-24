# Stage 3.3.1 — Canonical Plan Contract & Identity

## Purpose

Stage 3.3.1 opens **Stage 3.3 — Canonical Mission Planning & Task Decomposition** by creating the first durable canonical Plan artifact. This stage deliberately stops at **Plan contract and identity**: it defines what a Plan is, gives it a stable immutable identity, binds it to the exact canonical Mission and the exact Stage-3.2.4 PLANNING activation lineage, and persists the result as verifiable state.

It does **not** invoke a planner, decompose the Mission into tasks, create a dispatchable task graph, authorize execution, or actuate a target.

The architecture invariants are explicit:

- `PLAN != AUTHORIZATION`
- `TASK != DISPATCH`
- `READINESS != PERMISSION`
- `PLANNER != GOVERNANCE`

`aptsGSS / GOV-PLANE` remains the sole Governance/authorization authority.

## Canonical Plan contract

The runtime advertises:

- `control_version = stage3.3.1-canonical-plan-contract-identity`
- `mission_plan_contract_schema_version = apts-mission-plan-contract-v1`
- `mission_plan_contract_mode = IMMUTABLE_CANONICAL_PLAN_IDENTITY_BOUND_TO_MISSION_AND_PLANNING_ACTIVATION`
- creation state = `PLANNING`
- initial Plan version = `1`
- initial Plan status = `DRAFT`
- task graph status = `NOT_MATERIALIZED`
- Stage-3.2.4 planning-activation lineage is mandatory
- exact Mission version-vector SHA-256 is mandatory
- exact Mission state version is mandatory
- one immutable Plan identity per Mission in Stage 3.3.1

The stored contract binds the Plan to:

1. canonical `mission_id` and immutable Mission envelope;
2. envelope version and envelope SHA-256;
3. Mission objective, success criteria, budgets, and required subsystems;
4. PIP identity/version;
5. exact current local Scope snapshot, when one exists;
6. exact `PLANNING` state version;
7. exact Stage-3.2.4 `PIP_BOUND -> PLANNING` transition and activation evidence;
8. request provenance; and
9. a canonical SHA-256 integrity digest.

## API

### Discover the static contract

`GET /api/missions/{mission_id}/plan-contract-definition`

This endpoint is available before a Plan is registered. It describes the Stage-3.3.1 contract and reports whether a Plan identity already exists for the Mission.

### Register canonical Plan identity

`POST /api/missions/{mission_id}/plan-contract`

Minimal request:

```json
{
  "idempotency_key": "plan-20260904-001",
  "expected_version_sha256": "<current mission version-vector sha256>",
  "expected_state_version": 3,
  "created_by": "planner-supervisor",
  "reason": "Register immutable canonical plan identity",
  "metadata": {
    "stage": "3.3.1"
  }
}
```

The request intentionally has **no task list, dependency graph, planner output, tool call, authorization token, or dispatch instruction**. Such fields are rejected at this stage.

### Read canonical Plan

`GET /api/missions/{mission_id}/plan-contract`

The Plan is persisted and reconstructable from the Mission repository without querying CTI or Governance.

## Lifecycle guard

Registration fails closed unless the Mission is currently in `PLANNING` and that state was reached through the Stage-3.2.4 guarded lifecycle command path. A legacy/direct state transition to `PLANNING` does not satisfy the Plan-creation guard.

The exact Stage-3.2.4 activation evidence must still show:

- `activation_ready = true`
- `planner_invocation_performed = false`
- `plan_artifact_created = false`
- `governance_authorization_query_performed = false`
- `execution_authorized = false`
- `target_action_dispatch_enabled = false`
- `target_actuation = false`

Stage 3.3.1 then creates the Plan identity locally; it does not reinterpret activation readiness as permission.

## Persistence and lineage

Stage 3.3.1 introduces migration `009_stage3_3_1_canonical_plan_contract_identity.sql` and advances the repository migration level from `8` to `9`.

New store:

- `mission_plans`

The store enforces a unique Plan identity per Mission at Stage 3.3.1 and retains the canonical JSON, canonical SHA-256, request fingerprint, idempotency key, source state version, and source planning transition.

A successful registration appends a canonical Mission event:

- `MISSION_PLAN_CONTRACT_REGISTERED`

The event carries `plan_version = 1` and causally references the Plan identity. The Mission version vector now includes `mission_plan_version`, which is `0` before registration and `1` afterward.

## Idempotency and immutability

An exact retry with the same `idempotency_key` and canonical request returns the same Plan identity and does not create a duplicate Plan row or duplicate Plan-registration event.

The following fail closed:

- same idempotency key with a different request;
- a second Plan identity for the same Mission;
- stale `expected_version_sha256`;
- stale `expected_state_version`;
- Plan registration outside `PLANNING`;
- PLANNING reached without valid Stage-3.2.4 activation lineage;
- task/dependency/planner fields submitted to the Stage-3.3.1 endpoint.

Plan revision/version increment beyond version `1` is intentionally deferred to a later Stage-3.3 increment.

## Authority and execution boundary

Stage 3.3.1 does not expand runtime authority:

- planner invocation: **disabled**;
- task decomposition: **not performed**;
- Plan revision: **not performed**;
- Governance authorization query during Plan registration: **not performed**;
- target-action dispatch: **disabled**;
- target actuation: **disabled**;
- Plan is authorization: **false**;
- task is dispatch: **false**;
- readiness is permission: **false**;
- planner is Governance: **false**.

This separation is consistent with the project engineering principle that goal/plan state, action contracts, permissions, governance gates, and execution evidence remain distinct inspectable contracts rather than being collapsed into one autonomous decision.

## Regression

Stage 3.3.1 adds `tests/test_stage3_3_1_canonical_plan_contract_identity.py` with 13 focused tests and advances historical current-runtime assertions while retaining all Stage-3.1 and Stage-3.2 contracts as regression requirements.

Validated baseline:

- `python -m compileall -q mission_orchestrator tests` — PASS
- `python -m pytest -q` — **280 passed**

## Live acceptance

Run after starting Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_1_ACCEPTANCE.ps1
```

Expected final output:

```text
==============================================================================
STAGE 3.3.1 ACCEPTANCE: PASS
==============================================================================
```
