# Patch Notes — Stage 3.3.4 Task Dependency Graph & Structural Validation

## Added

- `mission_orchestrator/task_dependency_graph.py`
  - canonical graph/edge schemas;
  - deterministic request normalization;
  - exact canonical node projection;
  - dangling/self/duplicate/cycle rejection;
  - deterministic topological ordering;
  - root/leaf/isolated projections;
  - canonical graph/edge hashing and verification.
- migration `012_stage3_3_4_task_dependency_graph_structural_validation.sql`.
- durable stores `mission_task_dependency_graphs` and `mission_task_dependency_edges`.
- graph create/read/definition and edge read-model APIs.
- canonical `MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED` event.
- `task_dependency_graph_version` version-vector domain.
- Stage-3.3.4 repository-integrity and persistence-manifest projection.
- `tests/test_stage3_3_4_task_dependency_graph_structural_validation.py`.
- Stage-3.3.4 acceptance, install, manifest, README, and SHA-256 artifacts.

## Changed

- current control advances to `stage3.3.4-task-dependency-graph-structural-validation`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.3.4`.
- repository migration level advances `11 -> 12`.
- repository schema bootstrap now includes Stage-3.3.4 graph/edge stores.
- persistence manifest now includes graph and normalized dependency edges.
- historical active-control/migration regression assertions are rebaselined to Stage 3.3.4 while preserving prior control contracts.

## Preserved

- Stage-3.3.1 Plan artifact remains immutable.
- Stage-3.3.2 planner-input snapshot remains immutable.
- Stage-3.3.3 task decomposition and planned task contracts remain immutable.
- no planner invocation or planner-output consumption.
- no readiness projection or scheduler semantics.
- no Governance authorization query.
- no target-action dispatch or target actuation.
- `EXTERNAL_APTS_GSS` remains authorization authority.

## Validation

- focused: **29 passed**.
- full regression: **344 passed**.
