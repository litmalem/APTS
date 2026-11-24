# Stage 3.9.8 — Restart / Replay / Recovery E2E Verification

## Status

Implementation candidate for host acceptance. Active control:
`stage3.9.8-restart-replay-recovery-e2e-verification`.
Repository migration remains **53**. No new database migration, durable store, planner,
Governance, routing, dispatch, execution, or recovery authority is introduced.

## Canonical E2E continuation

Stage 3.9.8 begins at the exact Stage 3.9.7 head:

- mission `RUNNING(v4)`;
- Plan v1 historical/effectively superseded;
- Plan v2 active;
- canonical replan handoff `HANDOFF_READY`;
- 49 Mission events;
- nine pre-checkpoint replan events;
- no successor routing/dispatch/execution side effect.

The stage then invokes the existing **Stage 3.7.9** recovery authority exactly once to
persist a canonical `mission_replan_recovery_checkpoints` record. That append produces
`MISSION_REPLAN_RECOVERY_CHECKPOINTED`, taking the canonical mission trajectory to
**50 events** and the replan replay trajectory to **10 events**.

A fresh `CanonicalMissionService` is then opened against the same SQLite repository to
model process restart. Verification is performed from durable state only; the restart path
does not rerun planning, reinterpret the plan with an LLM, re-query Governance, query the
execution runtime, route/delegate successor work, redeliver dispatch, create an execution
attempt, mutate mission lifecycle state, or actuate a target.

## Restart equivalence requirements

The restarted service must reconstruct exactly the same:

- mission state and state version;
- active Plan v2 identity and hash;
- repository record counts and repository integrity;
- 50-event canonical Mission event chain and tip hash;
- 10-event adaptation/replan replay sequence;
- Stage 3.7.9 recovery checkpoint identity and hash; and
- `recovery_consistency = PASS` durable recovery projection.

Exact replay of the original checkpoint request after restart must be idempotent and must
not append another event or durable record.

## Read-only qualification API

```text
GET /api/e2e/restart-replay-recovery-qualification-contract
GET /api/missions/{mission_id}/e2e-restart-replay-recovery-qualification
```

The qualification route is read-only. It verifies the persisted checkpoint and recovered
projection but does not itself create a checkpoint or perform operational side effects.

## Acceptance

After copying the overlay into `D:\mission_orchestrator`, restart the application and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_8_ACCEPTANCE.ps1
```

The canonical inventory is **1545 tests**. The focused Stage 3.9.8 suite contains
**14 tests** covering contract integrity, runtime activation, exact event/repository
footprint, durable restart equivalence, deterministic replay, recovery consistency,
read-only verification, idempotent checkpoint replay, tamper rejection, side-effect
boundaries, and HTTP routes.

Next stage: **3.9.9 — Observation / Reconstruction / Forensic Equivalence**.
