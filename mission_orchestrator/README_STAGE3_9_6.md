# Stage 3.9.6 — Task Completion → Mission Outcome Closure

## Status

Implementation candidate for host acceptance. The active control is
`stage3.9.6-task-completion-mission-outcome-closure`. Repository migration remains
**53**; this stage adds no database migration, durable store, completion authority,
Governance authority, dispatch authority, or execution authority.

## Canonical E2E trajectory

The qualified Stage 3.9.5 handoff is the input: mission state is `RUNNING(v4)`,
the root task `collect-cti` has one authorized execution attempt, runtime
acknowledgement, `RUNNING` heartbeat, and terminal `SUCCEEDED` result with
verified evidence/artifact references. Stage 3.9.6 exercises the existing
authorities in this order:

1. Stage 3.5.8 propagates the terminal execution result as a verified successful task outcome source.
2. Stage 3.5.9 commits the execution recovery checkpoint that binds the terminal result and propagation identity.
3. Stage 3.6.1 materializes the canonical task outcome for `collect-cti`.
4. Stage 3.6.2 evaluates task terminality and completion eligibility.
5. Stage 3.6.3 verifies the evidence binding required for completion.
6. Stage 3.6.4 commits dependency-aware task completion.
7. Stage 3.6.5 aggregates the active Plan's three task outcomes.
8. Stage 3.6.6 evaluates mission success criteria against that aggregate.
9. Stage 3.6.7 evaluates completion readiness and materializes canonical blockers.

The resulting canonical head contains **40 Mission events**. `collect-cti` is
`COMPLETED_DEPENDENCY_CONSISTENT`, but the active Plan still contains
`analyze-cti` and `report-findings`. Therefore the aggregate is intentionally
nonterminal: one task is verified complete, one is pending, one is dependency
blocked, and not all tasks are terminal or verified complete.

The mission success evaluation is `SUCCESS_CRITERIA_NOT_SATISFIED`. Completion
readiness is `BLOCKED` with exactly these blockers, in canonical order:

1. `SUCCESS_CRITERIA_NOT_SATISFIED`
2. `TASKS_NOT_ALL_VERIFIED_COMPLETE`

This is the correct **Mission Outcome Closure assessment** for this E2E segment;
it is not a premature mission lifecycle completion. The mission remains
`RUNNING(v4)`. Stage 3.6.8 verified completion is not invoked, no
`mission_verified_completion_declarations` row is created, and Stage 3.6.9
outcome-recovery closure is not fabricated. The blocked nonterminal head is the
explicit handoff to **Stage 3.9.7 — Adaptation & Replanning**.

## Qualification and authority boundary

Stage 3.9.6 adds a SHA-256-bound, read-only qualification contract that anchors
the Stage 3.9.5 contract digest. The verifier checks:

- the exact Stage 3.9.5 event prefix and complete 40-event trajectory;
- full durable repository and Mission event-chain integrity;
- the exact repository footprint and single-artifact cardinality for the new closure segment;
- canonical hashes for Stage 3.5.8/3.5.9 and Stage 3.6.1–3.6.7 artifacts;
- execution propagation → recovery checkpoint → task outcome identity continuity;
- terminality → evidence binding → dependency-aware task completion continuity;
- mission aggregation and success-evaluation continuity;
- fail-closed completion-readiness blockers; and
- absence of any premature Stage 3.6.8/3.6.9 or lifecycle completion artifact.

Read-only endpoints:

```text
GET /api/e2e/completion-outcome-qualification-contract
GET /api/missions/{mission_id}/e2e-completion-outcome-qualification
```

The verifier performs no Governance query, runtime I/O, dispatch redelivery,
execution-attempt creation, verified-completion declaration, lifecycle state
transition, or target actuation.

## Focused qualification coverage

The Stage 3.9.6 focused suite covers the positive canonical trajectory, exact
40-event/repository footprint, terminal execution-to-task-completion binding,
blocked mission outcome, read-only repeated qualification, idempotent replay of
each existing mutation authority, partial-chain rejection, stale-input
rejection, durable repository tamper detection, restart reconstruction, HTTP
routes, and explicit non-fabrication of Stage 3.6.8/3.6.9 closure artifacts.

## Acceptance

Copy the overlay into `D:\mission_orchestrator`, restart the application, then run
from that directory:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_6_ACCEPTANCE.ps1
```

The script checks runtime activation, the qualification contract endpoint,
compilation, exact test inventory, focused Stage 3.9.6 coverage, the Stage 3.9
E2E chain, Stage 3.5.8/3.5.9 + Stage 3.6 outcome authorities, and the complete
historical regression. It performs no external target actuation.
