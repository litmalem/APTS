# Patch Notes — Stage 3.2.7 Abort, Failure & Expiration Semantics

## Added

- Terminal contract schema `apts-mission-terminal-semantics-v1`.
- Mode `DURABLE_TYPED_TERMINATION_CAUSE_WITH_IMMUTABLE_FINALITY_FAIL_CLOSED`.
- Typed semantic profiles:
  - `ABORT -> ABORTED / CONTROLLED_STOP / INTENTIONAL_ABORT`;
  - `FAIL -> FAILED / FAILURE / UNRECOVERABLE_FAILURE`;
  - `EXPIRE -> EXPIRED / EXPIRATION / VALIDITY_EXPIRED`.
- Durable `mission_terminal_control` evidence with deterministic terminal identity and exact source-state provenance.
- Preservation of abandoned Stage-3.2.5 waiting dependency and Stage-3.2.6 pause/replan contexts.
- Explicit no-success/no-completion/no-auto-retry/no-resume semantics.
- Optional structured terminal context from `metadata.terminal`.
- Terminal lineage reconstruction and legacy-direct-terminal detection.
- Explicit `COMPLETED` deferral to Stage 3.2.8 completion semantics.
- Guard check `TERMINAL_INTENT_TARGET_CONSISTENCY`.
- `GET /api/missions/{mission_id}/terminal-semantics-contract`.
- Stage-3.2.7 projection embedded in lifecycle-command discovery.
- Seventeen Stage-3.2.7 regression cases.
- `STAGE3_2_7_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.7-abort-failure-expiration-semantics`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.7`.
- `ABORT`, `FAIL`, and `EXPIRE` now persist typed terminal cause/disposition evidence when invoked through the lifecycle command path or generic guarded lifecycle operation.
- Lifecycle discovery now exposes Stage-3.2.7 terminal semantics.
- Health now reports Stage-3.2.7 terminal contract, recovery, immutability, and authority-boundary fields.
- Prior regression fixtures are updated only for current-control metadata and Stage-3.2.7 activation status.

## Preserved

- Stage-3.1.2 canonical lifecycle topology and terminal immutability.
- Stage-3.1.6 version-vector/idempotency command gate.
- Stage-3.2.2 local fail-closed guard matrix.
- Stage-3.2.3 PIP activation semantics.
- Stage-3.2.4 planning/run activation lineage.
- Stage-3.2.5 waiting dependency semantics.
- Stage-3.2.6 pause/resume/replan semantics.
- Fail-safe terminal availability without PIP or evidence references.
- Existing command journal, transition ledger, and Mission event lineage.
- Legacy direct state-transition API; direct terminal transitions do not fabricate Stage-3.2.7 typed evidence.
- Repository migration level **8**.
- aptsGSS as sole Governance/authorization authority.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.
- No source changes in aptsGSS or VulnDesk.

## Deliberately deferred

- No Stage-3.2.8 verified cleanup/completion gate.
- No automatic expiration scheduler.
- No automatic terminal-state retry/recovery.
- No autonomous planner implementation or plan artifact generation.
- No target action dispatch or actuation.

## Validation

- Python compile: PASS.
- Full regression: **216 passed**.
- Fresh SQLite HTTP smoke: PASS.
