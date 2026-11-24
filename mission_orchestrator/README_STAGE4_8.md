# Stage 4.8 — Governance, Scope & Rules-of-Engagement Enforcement

Stage 4.8 implements a **machine-enforceable, fail-closed local eligibility gate** for the Pentest Subsystem. It preserves the authoritative Stage-3 mission scope/RoE boundary and does **not** mint governance authorization or execute target actions.

## Active control

`stage4.8-governance-scope-roe-enforcement`

Predecessor: `stage4.7-capability-registry-tool-contract`  
Pentest repository migration: `6`  
Next stage: `4.9 — Evidence, Finding & Lineage Foundation`

## Enforced dimensions

- target allowlist
- target denylist
- network range
- credential boundary
- action/technique restrictions
- authorized time window
- impact/destructive-action ceiling
- rate/concurrency limits
- stop conditions

## Decision semantics

The local result is one of:

- `ELIGIBLE`
- `INELIGIBLE`
- `REVIEW_REQUIRED`

These are **scope/RoE eligibility states, not PolicyDecision authorization**. Stage 4.8 never converts eligibility into executable authority.

## New runtime/API

- `GET /api/pentest/governance-contract`
- `POST /api/pentest/governance/evaluate`
- `GET /api/pentest/governance/decisions/{decision_id}`
- `GET /api/pentest/tasks/{pentest_task_id}/governance-decisions`

`POST /api/execution/dispatches` remains fail-closed with HTTP 409 and `STAGE4_8_EXECUTION_INTAKE_NOT_ENABLED`.

## Persistence

Migration `006_stage4_8_governance_scope_roe_enforcement.sql` adds append-only `pentest_scope_roe_decisions` with canonical request/decision hashes, idempotency key, task/mission/pentest lineage, status, and immutable JSON payloads.

## Safety / authority boundary

Stage 4.8 performs no raw tool access, no external target I/O, no command execution, no target actuation, and no authorization minting. Controlled execution remains Stage 6 authority.

## Validation performed in this package

- Python compilation: PASS
- Focused Stage 4.8 tests: **24 passed**
- Stage 4.1 → 4.8 regression: **173 passed**
- Critical Stage 3 + Stage 4 regression: **79 passed**
- Canonical inventory: **1748 tests collected**

Run `STAGE4_8_ACCEPTANCE.ps1` on Windows after restarting the Pentest Subsystem so the active control is 4.8.
