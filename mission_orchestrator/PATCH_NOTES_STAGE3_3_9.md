# Patch Notes — Stage 3.3.9 Planning Event Lineage, Replay & Recovery

## Added

- `mission_orchestrator/planning_event_lineage.py`
  - canonical planning-event filtering;
  - deterministic read-only replay;
  - immutable recovery-checkpoint contract and hash verification.
- `mission_planning_recovery_checkpoints` durable repository store.
- migration `017_stage3_3_9_planning_event_lineage_replay_recovery.sql`.
- canonical event `MISSION_PLANNING_RECOVERY_CHECKPOINTED`.
- version-vector domain `planning_recovery_version`.
- Stage-3.3.9 APIs for planning lineage, replay, checkpoint history, and durable recovery.
- repository integrity checks for recovery checkpoint/Plan/readiness/event causality.
- `tests/test_stage3_3_9_planning_event_lineage_replay_recovery.py` with 38 cases.
- `STAGE3_3_9_ACCEPTANCE.ps1`.

## Changed

- active control -> `stage3.3.9-planning-event-lineage-replay-recovery`;
- HTTP server identity -> `APTSMissionOrchestrator/3.3.9`;
- repository migration level -> `17`;
- package declaration -> through Stage 3.3.9;
- historical regression assertions that intentionally track the active control, current migration level, supported-control tail, or current version-vector domains are rebased to Stage 3.3.9.

## Recovery semantics

Recovery checkpoints are one-per-Plan-version and immutable. They freeze exact bindings to the active Plan, active Stage-3.3.8 readiness projection, Mission state/version vector, and planning-event replay tip.

Recovery reads only durable canonical artifacts. It does not re-run the planner, invoke an external model, perform network I/O, query Governance authorization, dispatch a task, or actuate a target.

## Preserved authority boundaries

```text
PLAN      != AUTHORIZATION
TASK      != DISPATCH
READINESS != PERMISSION
PLANNER   != GOVERNANCE
REPLAY    != EXECUTION
RECOVERY  != AUTHORIZATION
```

`EXTERNAL_APTS_GSS` remains the sole Governance authorization authority.

## Validation

- Python compile: PASS.
- Stage 3.1: 111 passed.
- Stage 3.2: 156 passed.
- Stage 3.3.1–3.3.8: 189 passed by focused partitions.
- Stage 3.3.9: 38 passed.
- Total collected baseline: **494 tests**.
