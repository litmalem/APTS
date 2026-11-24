# Patch Notes — Stage 3.3.8 Task Readiness & Scheduling Projection

## Added

- `mission_orchestrator/task_readiness_projection.py` — immutable Plan-bound readiness/scheduling projection contract, deterministic derivation, hashing, request validation, and verification.
- `mission_task_readiness_projections` repository store and migration 016.
- API create/read/history/definition routes for task readiness projection.
- canonical `MISSION_TASK_READINESS_PROJECTED` event.
- `task_readiness_projection_version` version-vector domain.
- repository manifest/integrity coverage for readiness projections.
- typed readiness projection conflict/not-found/guard errors.
- `tests/test_stage3_3_8_task_readiness_scheduling_projection.py` with 28 collected cases.
- `STAGE3_3_8_ACCEPTANCE.ps1`.

## Changed

- active control advances to `stage3.3.8-task-readiness-scheduling-projection`;
- HTTP identity advances to `APTSMissionOrchestrator/3.3.8`;
- repository migration level advances from 15 to 16;
- historical current-control/current-repository assertions are rebased to Stage 3.3.8.

## Readiness semantics

- root tasks -> `READY`;
- dependent tasks -> `BLOCKED_DEPENDENCY`;
- one immutable projection per Plan version;
- old projections derive `SUPERSEDED` when a later active Plan version is installed;
- scheduling is dependency-layer wave projection only.

## Preserved boundaries

- `READINESS != PERMISSION`;
- `READY` does not imply authorization;
- no Governance authorization query;
- no wall-clock schedule;
- no resource assignment;
- no task/target dispatch;
- no target actuation.

## Validation

- compile: PASS;
- Stage 3.1: 111 passed;
- Stage 3.2: 156 passed;
- Stage 3.3.1–3.3.7 verified individually;
- Stage 3.3.8 focused: 28 passed;
- total collected regression baseline: 456 tests.
