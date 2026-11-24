# Patch Notes — Stage 3.6.2

## Task Terminality & Completion Eligibility

Stage 3.6.2 adds a deterministic task-level gate over the immutable Stage-3.6.1 `toutcome-*` record. It produces a durable `telig-*` artifact that confirms terminality and records whether the terminal outcome is eligible for later completion evaluation.

### Added

- `mission_orchestrator/task_terminality.py`
  - request normalization/fingerprinting;
  - deterministic four-status terminality classification;
  - immutable `telig-*` contract builder/verifier;
  - explicit no-acceptance/no-completion authority boundary.
- `migrations/037_stage3_6_2_task_terminality_completion_eligibility.sql`
  - durable `mission_task_terminality_eligibility_gates` store;
  - one-gate-per-outcome and idempotency uniqueness.
- `tests/test_stage3_6_2_task_terminality_completion_eligibility.py`
  - 20 focused Stage-3.6.2 tests.
- event `MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED`.
- REST API for evaluating, reading, listing, and describing the gate.
- repository manifest/integrity support for Stage-3.6.2 gates.
- `STAGE3_6_2_ACCEPTANCE.ps1` with exact inventory, full-regression, focused, runtime, migration, classification, and authority-boundary checks.

### Changed

- runtime control head -> `stage3.6.2-task-terminality-completion-eligibility`;
- HTTP server identity -> `APTSMissionOrchestrator/3.6.2`;
- repository migration level -> `37`;
- historical regression assertions rebased for the appended Stage-3.6.2 control and migration 037.

### Deterministic semantics

- `VERIFIED_COMPLETED` -> terminal success, completion-eligible;
- `VERIFIED_FAILED` -> terminal failure, not completion-eligible;
- `VERIFIED_CANCELLED` -> terminal cancelled, not completion-eligible;
- `VERIFIED_TIMED_OUT` -> terminal timed out, not completion-eligible.

### Still outside Stage 3.6.2

No task-outcome acceptance, acceptance-criteria evaluation, completion commit, task-state mutation, dependency release, readiness recalculation, Plan progression, Mission completion, Governance query, runtime query/control I/O, redispatch, new execution attempt, external network I/O, or target actuation is authorized by this stage.
