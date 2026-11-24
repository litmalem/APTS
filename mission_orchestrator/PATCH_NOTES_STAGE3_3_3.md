# Patch Notes — Stage 3.3.3 Canonical Task Decomposition Contract

## Added

- `mission_orchestrator/task_decomposition.py`
  - canonical decomposition and planned-task schemas;
  - `mdecomp-*` and `ptask-*` identities;
  - strict request/task normalization;
  - request, task, task-set, and decomposition SHA-256 domains;
  - immutable Plan/snapshot/source-context bindings;
  - planned-task integrity verification;
  - static Stage-3.3.3 contract definition.
- `migrations/011_stage3_3_3_canonical_task_decomposition_contract.sql`
  - `mission_task_decompositions`;
  - `mission_planned_tasks`;
  - repository migration level `11`.
- typed decomposition/planned-task errors.
- canonical event `MISSION_TASK_DECOMPOSITION_REGISTERED`.
- `task_decomposition_version` in Mission version vectors.
- decomposition and planned-task repository reconstruction/integrity projections.
- API surfaces for decomposition discovery/create/read and planned-task list/read.
- `tests/test_stage3_3_3_canonical_task_decomposition_contract.py` with **19 focused tests**.
- `STAGE3_3_3_ACCEPTANCE.ps1` and release documentation.

## Changed

- current control -> `stage3.3.3-canonical-task-decomposition-contract`;
- HTTP server identity -> `APTSMissionOrchestrator/3.3.3`;
- repository migration level `10 -> 11`;
- repository manifest adds task-decomposition/planned-task stores;
- historical current-control/migration/version-vector assertions advance to the Stage-3.3.3 baseline;
- package description advances through Stage 3.3.3.

## Guard semantics

- Stage-3.3.1 Plan and Stage-3.3.2 planner-input snapshot are mandatory.
- Exact Mission version SHA, Plan id/version/hash, snapshot id/version/hash, and state version are mandatory concurrency tokens.
- Mission must remain at exact snapshot-bound `PLANNING` state/version.
- Scope/Governance local context heads must still match the immutable snapshot.
- Tasks must use Mission-declared `required_subsystems`.
- Empty tasks, duplicate keys, malformed outputs/success criteria, and premature graph/tool/authorization/dispatch fields fail closed.

## Preserved

- immutable Stage-3.3.1 Plan contract;
- immutable Stage-3.3.2 planner-input snapshot;
- Plan task graph remains `NOT_MATERIALIZED`, `task_count=0`;
- planner invocation remains false;
- dependency graph/DAG validation remains reserved for Stage 3.3.4;
- `EXTERNAL_APTS_GSS` remains Governance/authorization authority;
- target dispatch/actuation remain false.

## Validation

- Python compile: PASS.
- Focused Stage-3.3.3 tests: **19 passed**.
- Full regression: **315 passed**.
- Live acceptance entry point: `STAGE3_3_3_ACCEPTANCE.ps1`.
