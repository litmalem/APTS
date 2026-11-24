# Patch Notes — Stage 3.5.9

## Added

- `mission_orchestrator/execution_lineage.py`
  - execution event filtering and deterministic replay;
  - immutable `xrecover-*` recovery checkpoint contract;
  - strict request normalization and caller-injection rejection;
  - canonical recovery definition and hash verification.
- durable `mission_execution_recovery_checkpoints` repository store;
- migration `035_stage3_5_9_execution_event_lineage_replay_recovery.sql`;
- `MISSION_EXECUTION_RECOVERY_CHECKPOINTED` canonical Mission event;
- Stage-3.5.9 service/API endpoints for lineage, replay, checkpointing, and restart recovery;
- repository manifest/integrity coverage for execution recovery checkpoints;
- 20 focused Stage-3.5.9 tests;
- Windows acceptance script.

## Runtime rebasing

- control version: `stage3.5.9-execution-event-lineage-replay-recovery`
- HTTP server: `APTSMissionOrchestrator/3.5.9`
- repository migration: `35`
- canonical test inventory: `951`

## Preserved authority boundaries

Stage 3.5.9 consumes the durable authority established by Stages 3.5.1–3.5.8. It does not introduce a new authorization authority, execute a new dispatch, contact the target runtime during replay/recovery, or alter Mission lifecycle state.
