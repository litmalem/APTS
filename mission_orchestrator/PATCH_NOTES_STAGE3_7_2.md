# Stage 3.7.2 Patch Notes — Adaptation Trigger Detection & Classification

## Change summary

Stage 3.7.2 adds a durable, deterministic classification layer on top of the immutable Stage-3.7.1 adaptation/replan detection contract.

### Added

- `mission_orchestrator/adaptation_trigger.py`
  - canonical reason/severity/source/scope taxonomies;
  - Stage-3.7.1 trigger-to-reason compatibility matrix;
  - request normalization and request fingerprinting;
  - immutable classification contract creation/verification;
  - `rcls-*` classification identity.
- migration `046_stage3_7_2_adaptation_trigger_detection_classification.sql`;
- durable store `mission_adaptation_trigger_classifications`;
- canonical Mission event `MISSION_ADAPTATION_TRIGGER_CLASSIFIED`;
- classification POST/GET/list/definition API surfaces;
- Stage-3.7.2 repository reconstruction/integrity checks;
- 22 focused Stage-3.7.2 regression tests;
- authoritative Stage-3.7.2 acceptance script.

### Changed

- runtime `control_version` -> `stage3.7.2-adaptation-trigger-detection-classification`;
- HTTP server version -> `APTSMissionOrchestrator/3.7.2`;
- repository migration level -> `46`;
- persistence manifest and repository record counts now include the classification store;
- historical current-head regression assertions were rebased to migration 46 / Stage 3.7.2 while preserving stage-local historical semantics;
- Stage-3.7.1 adaptation reads can expose `effective_episode_state=CLASSIFIED` and a compact classification projection without mutating the persisted Stage-3.7.1 contract.

## Deliberately not added

Stage 3.7.2 does not add replanning eligibility, lifecycle `REPLAN`, planner invocation, candidate/snapshot materialization, successor-Plan validation or commit, Plan supersession, dispatch, execution, external I/O, or target actuation.
