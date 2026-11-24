# Patch Notes — Stage 3.2.2 Lifecycle Transition Guard Matrix

## Added

- Guard matrix schema `apts-mission-lifecycle-guard-matrix-v1`.
- Deterministic command/source-state matrix for every Stage-3.2.1 lifecycle command.
- Local PIP prerequisite check using immutable mission-envelope `pip_id` + `pip_version`.
- Fail-safe exemption so `PAUSE`, `ABORT`, `FAIL`, and `EXPIRE` remain available when operational prerequisites are invalid.
- Guard-aware lifecycle contract discovery:
  - `guard_eligible_commands`
  - `guard_eligible_resume_targets`
  - `guard_evaluations`
  - `lifecycle_guard_matrix`
- Guard evidence returned on successful lifecycle commands.
- Dedicated HTTP error `MISSION_LIFECYCLE_GUARD_REJECTED` (409) for topology-legal but Stage-3.2.2-invalid lifecycle intent/prerequisite failures.
- `last_error` exposed in mission command read models for failed-command auditability.
- Fifteen Stage-3.2.2 regression cases.
- `STAGE3_2_2_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.2-lifecycle-transition-guard-matrix`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.2`.
- `mission_lifecycle_command_stage3_2_2_guard_matrix_enabled=true`.
- Previous regression assertions recognize Stage 3.2.2 as the current control while keeping Stage 3.2.1 explicitly listed in `supported_controls`.
- Stage-3.2.1 lifecycle test missions now carry immutable PIP identity so their command-contract regression remains valid under the Stage-3.2.2 prerequisite layer.

## Preserved

- Stage-3.1.2 remains canonical topology authority.
- Canonically illegal transitions retain the existing `MISSION_STATE_TRANSITION_ILLEGAL` semantics; Stage 3.2.2 does not mask topology errors with a new guard error.
- Stage-3.1.6 remains version-vector/idempotency command gate.
- Stage-3.1.9 remains event/lineage foundation.
- Existing command journal is reused; no new durable store.
- Repository migration level **8**.
- aptsGSS remains sole external Governance/authorization authority.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.
- No source changes required in aptsGSS or VulnDesk.

## Deliberately deferred

- No automatic resolution of evidence/approval waiting dependencies; Stage 3.2.5 remains future work.
- No verified completion gate or success-criteria enforcement; Stage 3.2.8 remains future work.
- No planner, scheduler, target execution, approval decision, or external lifecycle event automation.
- No removal of the legacy Stage-3.1 direct state-transition API.

## Validation

- Python compile: PASS.
- Full regression: **140 passed**.
- Local HTTP smoke: PASS.
