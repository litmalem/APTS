# Patch Notes — Stage 3.2.6 Pause, Resume & Replanning Control

## Added

- Pause/resume/replan contract schema `apts-mission-pause-resume-replan-control-v1`.
- Mode `DURABLE_PAUSE_CONTEXT_MATCHED_RESUME_AND_REPLAN_READINESS_FAIL_CLOSED`.
- Durable `mission_pause_control` evidence with deterministic pause identity and exact paused source context.
- Deterministic source-state-specific resume target policy.
- Resume prerequisite checks against Stage-3.2.3/3.2.4 activation lineage or active Stage-3.2.6 replan lineage.
- Safe paused-waiting continuation through `REPLANNING`, without synthesizing dependency satisfaction.
- Durable `mission_resume_control` evidence.
- Durable `mission_replan_control` episodes with deterministic replan identity and abandoned waiting dependency provenance.
- Durable `mission_replan_resolution` evidence for `REPLANNING -> RUNNING`.
- Replan readiness status `READY` with mandatory non-empty readiness `evidence_refs`.
- Guard checks:
  - `PAUSE_LINEAGE_FOR_RESUME`;
  - `RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE`;
  - `RESUME_PREREQUISITE_LINEAGE_FOR_TARGET`;
  - `REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS`;
  - `REPLAN_READINESS_EVIDENCE_FOR_RETURN`.
- `GET /api/missions/{mission_id}/pause-resume-replan-contract`.
- Stage-3.2.6 projection embedded in lifecycle-command discovery.
- Seventeen Stage-3.2.6 regression cases.
- `STAGE3_2_6_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.6-pause-resume-replanning-control`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.6`.
- `RESUME` now requires canonical Stage-3.2.6 pause lineage and a target compatible with the actual paused source.
- A paused `WAITING_EVIDENCE` / `WAITING_APPROVAL` cannot resume directly to `RUNNING`; safe continuation is `REPLANNING`.
- Progress from `REPLANNING` through `START` or a wait command requires active Stage-3.2.6 replan lineage.
- `START` from `REPLANNING` requires non-empty readiness evidence refs.
- Stage-3.2.6 pause/resume/replan guard is no longer deferred; Stage 3.2.7 and Stage 3.2.8 remain deferred.
- Prior regression fixtures are updated only for current-control metadata and Stage-3.2.6 superseding lifecycle semantics.

## Preserved

- Stage-3.1.2 canonical lifecycle topology.
- Stage-3.1.6 version-vector/idempotency command gate.
- Stage-3.2.2 local fail-closed guard matrix.
- Stage-3.2.3 immutable PIP activation proof.
- Stage-3.2.4 planning/run activation lineage.
- Stage-3.2.5 waiting dependency semantics and Governance separation.
- Existing command journal, transition ledger, and Mission event lineage.
- Legacy direct state-transition API; direct PAUSED/REPLANNING transitions do not fabricate Stage-3.2.6 evidence.
- Repository migration level **8**.
- aptsGSS as sole Governance/authorization authority.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.
- No source changes in aptsGSS or VulnDesk.

## Deliberately deferred

- No autonomous planner implementation or plan artifact generation.
- No automatic event-driven resume/replan.
- No Stage-3.2.7 terminal abort/failure/expiration extension.
- No verified cleanup/completion gate; Stage 3.2.8.
- No target action dispatch or actuation.

## Validation

- Python compile: PASS.
- Full regression: **199 passed**.
- Fresh SQLite HTTP smoke: PASS.
