# Patch Notes — Stage 3.3.5 Planner Invocation & Plan Generation

## Added

- `mission_orchestrator/planner_generation.py`
  - strict planner-invocation request contract;
  - local deterministic planner profile and engine;
  - dependency-layered topological plan generation;
  - immutable planner-invocation contract;
  - immutable `GENERATED_UNVALIDATED` candidate-plan contract;
  - canonical hashing and verification;
  - explicit no-Governance/no-dispatch/no-actuation semantics.
- migration `013_stage3_3_5_planner_invocation_plan_generation.sql`.
- durable stores:
  - `mission_planner_invocations`
  - `mission_generated_plans`
- Stage-3.3.5 create/read/definition API routes.
- canonical Mission events:
  - `MISSION_PLANNER_INVOKED`
  - `MISSION_PLAN_GENERATED`
- version-vector domain `planner_generation_version`.
- Stage-3.3.5 repository-integrity and persistence-manifest projections.
- `tests/test_stage3_3_5_planner_invocation_plan_generation.py`.
- Stage-3.3.5 acceptance, installation, README, manifest, and SHA-256 artifacts.

## Changed

- current control advances to `stage3.3.5-planner-invocation-plan-generation`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.3.5`.
- repository migration level advances `12 -> 13`.
- repository schema bootstrap includes planner invocation/generated-plan stores.
- active-control, migration, supported-control, and version-vector regression assertions are rebaselined to Stage 3.3.5.

## Planner semantics

Stage 3.3.5 is intentionally deterministic and local:

- planner profile: `CANONICAL_DAG_STRUCTURAL_PLANNER_V1`;
- planner engine: `APTS_MO_LOCAL_DETERMINISTIC_GRAPH_PLANNER`;
- strategy: `DEPENDENCY_LAYERED_TOPOLOGICAL_V1`;
- generated status: `GENERATED_UNVALIDATED`;
- external model invocation: false;
- external network I/O: false.

It consumes the exact immutable Stage-3.3.2 snapshot, Stage-3.3.3 planned-task set, and Stage-3.3.4 validated DAG. It does not accept caller-injected planner outputs.

## Preserved

- Stage-3.3.1 canonical Plan remains immutable.
- Stage-3.3.2 planner-input snapshot remains immutable.
- Stage-3.3.3 task decomposition/planned-task contracts remain immutable.
- Stage-3.3.4 validated dependency graph remains immutable.
- Stage-3.3.6 feasibility validation is not performed.
- Stage-3.3.8 readiness/scheduling is not performed.
- no Governance authorization query is introduced.
- no routed-task creation, target-action dispatch, or target actuation is introduced.
- `EXTERNAL_APTS_GSS` remains authorization authority.

## Validation

- focused Stage-3.3.5: **37 passed**.
- full regression: **381 passed**.
