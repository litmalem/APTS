# Stage 3.7.9 — Adapt/Replan Lineage, Replay & Recovery

Stage 3.7.9 makes the complete Stage-3.7 adaptation/replanning trajectory reconstructable from durable evidence. It adds a canonical event subchain, deterministic read-only replay, and an immutable recovery checkpoint after the Stage-3.7.8 handoff is already `HANDOFF_READY`.

## Runtime contract

- `control_version`: `stage3.7.9-adapt-replan-lineage-replay-recovery`
- repository migration: `53`
- event-lineage schema: `apts-replan-event-lineage-v1`
- event-replay schema: `apts-replan-event-replay-v1`
- recovery-checkpoint schema: `apts-replan-recovery-checkpoint-v1`
- recovery identity prefix: `rplin-`
- persistence store: `mission_replan_recovery_checkpoints`
- recovery event: `MISSION_REPLAN_RECOVERY_CHECKPOINTED`
- lineage status: `ACTIVE`
- next stage: `3.7.10`

## Canonical Stage-3.7 lineage

Before a recovery checkpoint is created, the canonical replan event subchain contains exactly these nine causal events:

1. `MISSION_ADAPTATION_REPLAN_DETECTED`
2. `MISSION_ADAPTATION_TRIGGER_CLASSIFIED`
3. `MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED`
4. `MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND`
5. `MISSION_REPLAN_CANDIDATE_GENERATED`
6. `MISSION_REPLAN_DECISION_RECORDED`
7. `MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED`
8. `MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED`
9. `MISSION_REPLAN_HANDOFF_READY`

Creating the immutable recovery checkpoint adds the tenth terminal lineage event, `MISSION_REPLAN_RECOVERY_CHECKPOINTED`.

## Replay semantics

Replay is a deterministic projection of durable Mission events. It is deliberately read-only:

- it does not rerun the planner;
- it does not reinterpret the trajectory with an LLM;
- it does not query Governance or runtime controls;
- it does not route, delegate, redispatch, or create a new execution attempt;
- it does not cancel work or perform external network I/O;
- it does not mutate Mission lifecycle state, historical Plan rows, or the active Plan head;
- it performs no target action dispatch or target actuation.

The replay projection records the ordered Stage-3.7 event sequence, event count, event-tip SHA-256, and a canonical replay SHA-256. Identical durable event history therefore yields an identical replay projection.

## Recovery checkpoint

A checkpoint may be created only after Stage 3.7.8 has produced an exact `HANDOFF_READY` artifact and the Stage-3.7.7 successor Plan is still the active Plan head. The request must bind to the current Mission version vector/state version, exact handoff identity/hash, exact active successor Plan identity/version/hash, and exact pre-checkpoint replan event count/tip.

The checkpoint:

- has an immutable `rplin-*` identity;
- binds the complete Stage-3.7.1 through Stage-3.7.8 artifact chain;
- binds the exact predecessor/successor Plan relation;
- records that the effective adaptation state is `HANDOFF_READY`;
- self-verifies through its canonical SHA-256;
- is unique per Stage-3.7.8 handoff/episode/successor;
- can be reconstructed after process restart from the durable repository without re-executing adaptation logic.

The repository repeats active-successor and Mission-state guards inside the checkpoint transaction, making stale or conflicting recovery attempts fail closed.

## Recovery request fields

The checkpoint API accepts only canonical recovery-binding material:

- `idempotency_key`
- `expected_version_sha256`
- `expected_state_version`
- `expected_adaptation_episode_id`
- `expected_replan_handoff_id`
- `expected_replan_handoff_sha256`
- `expected_active_plan_version_record_id`
- `expected_active_plan_version`
- `expected_active_plan_sha256`
- `expected_replan_event_count`
- `expected_replan_event_tip_sha256`
- `created_by`, `reason`, and optional `metadata`

Caller-supplied replacement plans, lifecycle commands, governance decisions, runtime commands, cancellation commands, routing/delegation/dispatch commands, or target actions are rejected.

## API

- `GET /api/missions/{mission_id}/replan-lineage`
- `GET /api/missions/{mission_id}/replan-replay`
- `POST /api/missions/{mission_id}/replan-recovery-checkpoints`
- `GET /api/missions/{mission_id}/replan-recovery-checkpoints`
- `GET /api/missions/{mission_id}/replan-recovery-checkpoints/{checkpoint_id}`
- `GET /api/missions/{mission_id}/replan-recovery`
- `GET /api/missions/{mission_id}/replan-lineage-definition`

## Repository integrity

Mission repository projection now includes `adapt_replan_lineage_replay_recovery_store`. Repository integrity verifies checkpoint self-hashes, exact Stage-3.7.8 handoff bindings, one causal recovery event per persisted checkpoint, and all declared no-side-effect flags. Persisted checkpoint tampering causes repository integrity reconstruction to fail.

## Verification inventory

- canonical collection: 1344 tests
- focused Stage 3.7.9 suite: 22 tests
- focused Stage 3.7.8 predecessor suite: 18 tests

Run `STAGE3_7_9_ACCEPTANCE.ps1` on the target host for the authoritative full Stage 3.1–3.7.9 regression gate.
