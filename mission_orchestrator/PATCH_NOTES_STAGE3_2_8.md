# Patch Notes — Stage 3.2.8 Cleanup & Verified Completion Gate

## Added

- Cleanup/completion schema `apts-mission-cleanup-completion-gate-v1`.
- Mode `DURABLE_CLEANUP_LINEAGE_AND_EVIDENCE_GATED_VERIFIED_COMPLETION_FAIL_CLOSED`.
- Durable `mission_cleanup_control` evidence for `BEGIN_CLEANUP`.
- Stage-3.2.4 RUNNING activation-lineage prerequisite for cleanup.
- Cleanup blocker detection for unresolved waiting/replan/pause contexts.
- Structured `metadata.completion` verification contract.
- Exact canonical success-criteria coverage by `criterion_index`.
- Objective evidence, criterion evidence, cleanup-check evidence, and command-level evidence binding.
- Zero-outstanding-critical-dependencies completion requirement.
- Durable `mission_completion_verification` evidence for successful `COMPLETE`.
- Verified completion terminal status `VALID_VERIFIED_COMPLETION`.
- Legacy direct-completion detection `LEGACY_DIRECT_COMPLETED_NO_STAGE_3_2_8_EVIDENCE`.
- `GET /api/missions/{mission_id}/cleanup-completion-contract`.
- Stage-3.2.8 cleanup/completion projection embedded in lifecycle discovery.
- Stage-3.2.8 guard-matrix checks for run lineage, envelope integrity, cleanup lineage, blockers, completion declaration, success criteria, cleanup, dependencies, and evidence binding.
- Eighteen Stage-3.2.8 regression cases.
- `STAGE3_2_8_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.8-cleanup-verified-completion-gate`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.8`.
- `BEGIN_CLEANUP` now records durable local cleanup-control provenance.
- `COMPLETE` now fails closed unless the Stage-3.2.8 completion gate passes.
- `COMPLETED` terminal projection now distinguishes verified completion from legacy/direct completion.
- Lifecycle command discovery exposes structural completion readiness and request-at-execution evidence semantics.
- Stage-3.2.8 is removed from the deferred guard set; Governance authorization remains the only deferred external authority concern.
- Health now reports Stage-3.2.8 contract, evidence, lineage, completion, and authority-boundary fields.
- Prior regression fixtures are updated only where current-control metadata or historical Stage-3.2.8 completion deferral changed.

## Preserved

- Stage-3.1.2 canonical lifecycle topology and terminal-state immutability.
- Stage-3.1.6 version-vector/idempotency command gate.
- Stage-3.1.9 append-only Mission event lineage.
- Stage-3.2.2 local fail-closed guard matrix.
- Stage-3.2.3 PIP activation semantics.
- Stage-3.2.4 planning/run activation lineage.
- Stage-3.2.5 waiting dependency semantics.
- Stage-3.2.6 pause/resume/replan semantics.
- Stage-3.2.7 typed `ABORT`/`FAIL`/`EXPIRE` semantics, including fail-safe terminal exits from `CLEANING_UP`.
- Legacy direct state-transition API; direct cleanup/completion transitions do not fabricate Stage-3.2.8 evidence.
- Existing command journal, transition ledger, and Mission event schema.
- Repository migration level **8**.
- aptsGSS as sole Governance/authorization authority.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.
- No source changes in aptsGSS or VulnDesk.

## Deliberately deferred

- No target cleanup/compensation execution.
- No autonomous planner implementation or plan artifact generation.
- No external evidence retrieval/verification.
- No automatic completion scheduler.
- No terminal-state retry/recovery.
- No target action dispatch or actuation.
- No Stage-3.2.9 event-driven lifecycle automation.

## Validation

- Python compile: PASS.
- Full regression: **234 passed**.
- Fresh SQLite service/API smoke: PASS.
