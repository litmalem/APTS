# Patch Notes — Stage 3.5.8

## Timeout, Cancellation, Abort & Failure Propagation

Stage 3.5.8 extends the Stage-3.5 execution chain with explicit runtime termination control and verified terminal-outcome propagation.

### Added

- `mission_orchestrator/execution_termination.py`
  - canonical Stage-3.5.8 schema;
  - `xterm-*` immutable termination-control contract;
  - `xprop-*` immutable terminal-outcome propagation contract;
  - strict request normalization and caller-field rejection;
  - deterministic lifecycle command identity for fail/abort propagation and recovery;
  - terminal outcome classification for `SUCCEEDED`, `FAILED`, `TIMED_OUT`, and `CANCELLED`;
  - control-action-aware distinction among cancellation, abort, and timeout semantics.
- `migrations/034_stage3_5_8_timeout_cancellation_abort_failure_propagation.sql`
  - `mission_execution_termination_controls`;
  - `mission_execution_outcome_propagations`;
  - unique idempotency/cardinality constraints and relational bindings.
- `tests/test_stage3_5_8_timeout_cancellation_abort_failure_propagation.py`
  - 20 focused tests.

### Updated

- `mission_orchestrator/execution_delivery.py`
  - downstream runtime `execution_control(...)` POST support.
- `mission_orchestrator/errors.py`
  - termination-control and outcome-propagation conflict/not-found/guard errors.
- `mission_orchestrator/mission_events.py`
  - `MISSION_EXECUTION_TERMINATION_CONTROL_ACKNOWLEDGED`;
  - `MISSION_EXECUTION_TERMINAL_OUTCOME_PROPAGATED`.
- `mission_orchestrator/repository.py`
  - SQLite/MySQL DDL and durable CRUD/idempotency/cardinality methods for both Stage-3.5.8 stores.
- `mission_orchestrator/repository_model.py`
  - migration level `34`;
  - persistence-manifest projections for termination controls and outcome propagations.
- `mission_orchestrator/service.py`
  - activates `stage3.5.8-timeout-cancellation-abort-failure-propagation`;
  - runtime termination-control service flow;
  - terminal outcome verification;
  - deterministic non-success lifecycle propagation;
  - idempotent replay and crash-recovery path;
  - event emission and repository-integrity verification;
  - Stage-3.5.8 health/definition declarations.
- `mission_orchestrator/api_service.py`
  - HTTP server version `APTSMissionOrchestrator/3.5.8`;
  - termination-control and outcome-propagation routes;
  - canonical Stage-3.5.8 error mappings.
- Historical tests were rebased where necessary to the active Stage-3.5.8 control lineage, HTTP version, repository migration level 34, migration inventory 034, and extended Stage-3.5 supported-control tail while preserving each earlier stage's own authority boundary.

### Semantics

- `TIMEOUT`, `CANCEL`, and `ABORT` are explicit runtime control intents and never create a new dispatch.
- Termination control requires the exact current RUNNING execution lineage and must occur before Stage-3.5.7 terminal-result capture.
- `SUCCEEDED` → `VERIFIED_SUCCESS`; no Mission transition is performed.
- `FAILED` → canonical lifecycle `FAIL` → Mission `FAILED`.
- `TIMED_OUT` → canonical lifecycle `FAIL` → Mission `FAILED`.
- `CANCELLED` → canonical lifecycle `ABORT` → Mission `ABORTED`, except a prior `TIMEOUT` intent classifies the terminal `CANCELLED` result as verified timeout and fails the Mission.
- `CANCELLED` after explicit `ABORT` is classified `VERIFIED_ABORT`.
- `SUCCEEDED` after an acknowledged termination control is rejected as an inconsistent runtime trajectory.

### Safety / authority boundary

Stage 3.5.8 performs no new Governance authorization, no runtime endpoint re-resolution, no dispatch redelivery, and no new target-action dispatch.

Success verification is intentionally separated from Mission completion authority. Only non-success outcomes are propagated immediately to canonical terminal Mission states through the existing Stage-3.2 lifecycle command mechanism.

### Next boundary

Declared next stage: **Stage 3.5.9**.
