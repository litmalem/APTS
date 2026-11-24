# Stage 3.9.7 — Adaptation / Replanning E2E Scenario

## Status

Implementation candidate for host acceptance. The active control is
`stage3.9.7-adaptation-replanning-e2e-scenario`. Repository migration remains
**53**. This stage introduces no database migration, durable store, replanning
persistence authority, Governance authority, routing authority, dispatch authority,
or execution authority.

## Canonical E2E scenario

Stage 3.9.7 starts from the exact Stage 3.9.6 head: mission `RUNNING(v4)`, Plan v1
active, `collect-cti` completed with verified evidence, two unfinished plan tasks,
`SUCCESS_CRITERIA_NOT_SATISFIED`, and completion readiness `BLOCKED`.

The Stage 3.9.6 terminal event `MISSION_COMPLETION_READINESS_EVALUATED` is bound as
the adaptation source. Existing Stage 3.7 authorities are then exercised in order:

1. Stage 3.7.1 creates the canonical adaptation/replan trigger contract.
2. Stage 3.7.2 classifies it as `PLAN_STALE`, severity `MEDIUM`, source stage
   `STAGE3_6_OUTCOME_COMPLETION`, and `LEVEL_3_PARTIAL_PLAN`.
3. Stage 3.7.3 performs the replanning eligibility + authoritative Governance gate;
   the canonical decision is `ALLOW` and eligibility is `ELIGIBLE`.
4. Stage 3.7.4 freezes an immutable replanning snapshot over the source Plan v1,
   task/dependency state, completion evidence, scope, and Governance context.
5. Stage 3.7.5 generates a deterministic successor candidate. The already-completed
   `collect-cti` root is not regenerated; the successor contains exactly
   `analyze-cti` and `report-findings` with the remaining dependency edge.
6. Stage 3.7.6 validates the candidate as `VALIDATED_FOR_COMMIT`.
7. Stage 3.7.7 revalidates authoritative Governance at commit time and commits the
   successor as `COMMITTED_SUCCESSOR_PLAN`.
8. Stage 3.7.8 atomically supersedes the Plan v1 head, activates **Plan v2**, and
   emits `HANDOFF_READY`.

The mission lifecycle state intentionally remains `RUNNING(v4)`; replanning changes
planning authority state, not mission lifecycle state. The canonical head contains
**49 Mission events**: the 40-event Stage 3.9.6 prefix plus exactly nine Stage 3.9.7
adaptation/replanning events.

## Stage boundary

The Stage 3.9.7 segment terminates at `HANDOFF_READY` with next control
`STAGE3_4_ROUTING_THEN_STAGE3_5_DISPATCH`. It does **not** route the successor tasks,
dispatch a new execution attempt, perform target actuation, or create the Stage 3.7.9
replan recovery checkpoint. That checkpoint is intentionally reserved for
**Stage 3.9.8 — Restart / Replay / Recovery**.

This boundary lets Stage 3.9.8 prove that the committed Plan v2 and its nine-event
adaptation lineage can be reconstructed/replayed across restart before any new
execution side effect occurs.

## Scope continuity

The canonical Stage 3.9.4 scope now carries both `TARGET_RECON` and
`INTERNAL_REASONING` in `roe.allowed_action_classes`. `TARGET_RECON` preserves the
original routed reconnaissance execution. `INTERNAL_REASONING` authorizes the
existing Governance-bound Stage 3.7 replanning operations. Adding it at the original
canonical scope avoids fabricating a later Stage 3.9.7 scope revision solely to make
replanning legal.

## Qualification contract

Stage 3.9.7 adds a SHA-256-bound, read-only qualification contract anchored to the
Stage 3.9.6 contract digest. The verifier checks:

- exact Stage 3.9.6 event prefix and the complete 49-event trajectory;
- repository + Mission event-chain integrity and exact nonzero durable footprint;
- exactly one Stage 3.7.1–3.7.8 canonical artifact and no Stage 3.7.9 checkpoint;
- exact blocked-readiness event -> adaptation-trigger identity binding;
- `PLAN_STALE` -> `LEVEL_3_PARTIAL_PLAN` trigger classification;
- authoritative Governance `ALLOW` for replanning eligibility;
- immutable source Plan v1 snapshot and completed-root binding;
- deterministic two-task remainder DAG and satisfied-predecessor continuity;
- candidate validation before authoritative commit;
- atomic Plan v1 -> Plan v2 head transition with mission state unchanged;
- `HANDOFF_READY` with no downstream routing/dispatch/execution attempt; and
- exact nine-event pre-checkpoint replan replay boundary.

Read-only endpoints:

```text
GET /api/e2e/adaptation-replanning-qualification-contract
GET /api/missions/{mission_id}/e2e-adaptation-replanning-qualification
```

The qualification endpoint itself performs no Governance query, planner invocation,
replan mutation, routing, dispatch, execution, lifecycle transition, or target
actuation.

## Acceptance

Copy the overlay into `D:\mission_orchestrator`, restart the application, then run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_7_ACCEPTANCE.ps1
```

The acceptance script checks runtime activation, the Stage 3.9.7 contract route,
Python compilation, exact **1531-test** inventory, focused Stage 3.9.7 coverage, the
Stage 3.9.1–3.9.7 E2E chain, existing Stage 3.7 adaptation/replanning authorities,
and the complete historical regression. It performs no external target actuation.
