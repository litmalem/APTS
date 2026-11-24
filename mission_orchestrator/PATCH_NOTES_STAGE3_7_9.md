# Patch Notes — Stage 3.7.9

## Added

- `mission_orchestrator/replan_lineage.py`
- migration `053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql`
- durable `mission_replan_recovery_checkpoints` repository store
- immutable `rplin-*` recovery checkpoint identities
- canonical Stage-3.7 event-lineage schema `apts-replan-event-lineage-v1`
- deterministic read-only replay schema `apts-replan-event-replay-v1`
- recovery-checkpoint schema `apts-replan-recovery-checkpoint-v1`
- event `MISSION_REPLAN_RECOVERY_CHECKPOINTED`
- exact event-count/event-tip binding before checkpoint creation
- durable restart reconstruction with active-successor/state consistency checks
- Stage-3.7.9 API, health metadata, repository manifest, and integrity checks
- 22 focused Stage-3.7.9 tests
- host acceptance script `STAGE3_7_9_ACCEPTANCE.ps1`

## Changed

- runtime control advanced from Stage 3.7.8 to Stage 3.7.9
- Mission Orchestrator HTTP server version advanced to `3.7.9`
- repository migration level advanced from 52 to 53
- canonical repository manifest now contains `adapt_replan_lineage_replay_recovery_store`
- canonical Stage-3.7 event vocabulary now includes the terminal recovery checkpoint event
- historical regression expectations were rebased to the current runtime/migration while preserving Stage 3.7.8 as the immediate predecessor control
- canonical test inventory advanced from 1322 to 1344

## Fail-closed recovery boundary

Checkpoint creation requires exact agreement on Mission version/state, Stage-3.7.8 handoff identity/hash, active Stage-3.7.7 successor Plan identity/version/hash, and the pre-checkpoint Stage-3.7 event count/tip. Stale values, duplicate checkpoints, idempotency-key reuse with changed request material, or tampered persisted checkpoints are rejected.

## Deliberately unchanged

- Stage 3.7.7 remains the only control that materializes the successor Plan and performs active-head CAS.
- Stage 3.7.8 remains the control that proves supersession and declares `HANDOFF_READY`.
- Stage 3.7.9 does not rerun planning or reinterpret the adaptation trajectory.
- No Governance/runtime query, lifecycle transition, historical Plan mutation, active-head CAS, cancellation I/O, routing, delegation, redispatch, execution-attempt creation, target dispatch, or target actuation is introduced.

## Next stage

Stage 3.7.10 — Adapt/Replan Acceptance / Regression Gate.
