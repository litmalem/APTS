# Patch Notes — Stage 3.3.6 Plan Validation & Feasibility Gate

## Added

- `mission_orchestrator/plan_validation.py`
  - strict validation-request normalization;
  - deterministic feasibility evaluator;
  - immutable validation-contract builder/verifier;
  - canonical Stage-3.3.6 definition.
- `mission_plan_validations` durable repository store.
- migration `014_stage3_3_6_plan_validation_feasibility_gate.sql`.
- `plan_validation_version` Mission version-vector domain.
- canonical Mission event `MISSION_PLAN_VALIDATED_FEASIBLE`.
- POST/GET Plan-validation API surfaces plus definition discovery.
- typed validation conflict/not-found/guard errors.
- 20 focused Stage-3.3.6 tests.
- `STAGE3_3_6_ACCEPTANCE.ps1`.

## Changed

- active control: `stage3.3.6-plan-validation-feasibility-gate`.
- HTTP server identity: `APTSMissionOrchestrator/3.3.6`.
- repository migration level: `14`.
- repository integrity/persistence manifest includes Plan validation.
- historical active-control and migration assertions rebaselined to Stage 3.3.6.

## Preserved

- Stage-3.3.5 generated candidate remains immutable and `GENERATED_UNVALIDATED`; Stage 3.3.6 writes a separate validation artifact rather than mutating the candidate.
- `EXTERNAL_APTS_GSS` remains sole Governance authorization authority.
- no Plan activation.
- no readiness projection.
- no scheduling.
- no Governance authorization query.
- no target-action dispatch.
- no target actuation.

## Regression baseline

- prior Stage-3.3.5 baseline: 381 tests.
- new Stage-3.3.6 tests: 20.
- collected Stage-3.3.6 baseline: **401 tests**.
- focused Stage-3.3.6 suite: **20 passed**.
- final full-suite/live verdict is performed by `STAGE3_3_6_ACCEPTANCE.ps1` on the target runtime.
