# Patch Notes — Stage 3.7.8

## Added

- `mission_orchestrator/replan_handoff.py`
- migration `052_stage3_7_8_atomic_replan_commit_supersession_handoff.sql`
- durable `mission_replan_handoffs` repository store
- `rphof-*` immutable handoff identities
- event `MISSION_REPLAN_HANDOFF_READY`
- deterministic `KEEP / DRAIN / CANCEL / SUPERSEDE / REPLACE` task disposition model
- fail-closed active-head/state revalidation inside the handoff database transaction
- Stage-3.7.8 API, health metadata, repository reconstruction, and integrity checks
- 18 focused Stage-3.7.8 tests
- host acceptance script `STAGE3_7_8_ACCEPTANCE.ps1`

## Changed

- runtime control advanced from Stage 3.7.7 to Stage 3.7.8
- Mission Orchestrator HTTP server version advanced to `3.7.8`
- repository migration level advanced from 51 to 52
- canonical repository manifest now contains `atomic_replan_supersession_handoff_store`
- historical regression expectations rebased to the current runtime/migration while retaining Stage-3.7.7 as the immediate predecessor control

## Deliberately unchanged

- Stage 3.7.7 remains the only control that materializes the successor Plan and performs the active-head CAS.
- No Mission lifecycle transition is introduced in Stage 3.7.8.
- No Stage-3.5 cancellation request is sent by Stage 3.7.8; `CANCEL` is a handoff disposition only.
- No routing, delegation, dispatch, execution-attempt creation, external action dispatch, or target actuation is performed.

## Next stage

Stage 3.7.9 — Adaptation/Replan Event Lineage, Replay & Recovery.
