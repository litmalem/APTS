# Stage 3.9.4 — Routing → Delegation → Governance Continuity

## Status

Implementation candidate complete for host acceptance.

Active control:

`stage3.9.4-routing-delegation-governance-continuity`

Repository migration remains **53**. No new durable store or database migration is introduced.

## Purpose

Stage 3.9.4 extends the canonical Stage 3.9 E2E mission from the verified Stage 3.9.3 planning DAG into the already-established planning/routing/delegation/governance authorities. It deliberately does **not** introduce a parallel router, delegation authority, governance authority, dispatch authority, or executor.

Canonical continuity path:

```text
Stage 3.9.3 verified DAG
  → Stage 3.3.5 planner invocation / generated plan
  → Stage 3.3.6 feasibility validation
  → Stage 3.3.7 Plan v1 activation
  → Stage 3.3.8 readiness projection
  → canonical mission Scope/RoE
  → external authoritative Governance binding
  → Stage 3.4.2 routing intent / candidate resolution
  → Stage 3.4.3 eligibility + compatibility
  → Stage 3.4.4 deterministic route selection
  → Stage 3.4.5 authoritative pre-delegation Governance decision
  → Stage 3.4.6 immutable delegation + handoff envelope
  → Stage 3.4.7 acknowledgement + ownership acceptance
```

The canonical root task is `collect-cti`. Its deterministic route is `CTI / cti.read.context`. The dependent tasks `analyze-cti` and `report-findings` remain blocked by the readiness projection and are not routed.

## Qualified segment head

The Stage 3.9.4 qualified head freezes the following properties:

- Mission head remains `PLANNING`, state version `3`.
- Active plan is version `1`.
- Exactly one task is READY: `collect-cti`.
- Exactly one routing intent, eligibility gate, route decision, delegation authorization, delegation, and delivery receipt are materialized.
- The authoritative Governance decision is `ALLOW` / `AUTHORIZED` before delegation.
- Delegation handoff is acknowledged and ownership is accepted.
- Exactly 22 mission events exist in the frozen canonical sequence.
- No Stage 3.9.5 dispatch, execution attempt, runtime delivery, execution result, target network action, or target actuation is materialized.
- Pre-dispatch governance revalidation remains mandatory for Stage 3.9.5.

## Runtime verifier

New read-only endpoints:

```text
GET /api/e2e/routing-delegation-governance-qualification-contract
GET /api/missions/{mission_id}/e2e-routing-delegation-governance-qualification
```

The verifier reconstructs qualification solely from persisted Mission Orchestrator state. It does not issue a new governance query, route a task, create a delegation, dispatch execution, perform external target I/O, or actuate a target.

## Governance testing model

The Stage 3.9.1 environment contract is a control-plane sandbox. Therefore the focused Stage 3.9.4 regression uses an injected deterministic Governance authority double while exercising the real Mission Orchestrator Scope/RoE binding and Stage 3.4.5 governance authorization path. The runtime verifier itself remains read-only and restart-safe.

A Governance `DENY` is persisted as fail-closed evidence; delegation and delivery do not materialize, and the Stage 3.9.4 qualification is rejected.

## Test inventory

Canonical collection after this patch: **1485 tests**.

Container qualification performed during patch construction:

- Stage 3.9.4 focused suite: **12 passed**.
- Stage 3.9.1–3.9.4 E2E chain: **54 passed**.
- Additional broad/Stage 3.3 regression runs were started and showed no failures before the execution environment time limit; the supplied PowerShell acceptance gate performs the authoritative full regression on the deployment host.

## Acceptance

Run from `D:\mission_orchestrator` after replacing the source tree with this package:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_4_ACCEPTANCE.ps1
```

Stage 3.9.4 is ready for host acceptance. Stage 3.9.5 remains responsible for **Dispatch → Execution → Evidence**.
