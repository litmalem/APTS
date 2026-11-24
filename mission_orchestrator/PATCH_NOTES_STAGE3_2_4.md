# Patch Notes — Stage 3.2.4 Planning and Run Activation

## Added

- Planning/run activation contract schema `apts-mission-planning-run-activation-v1`.
- Explicit lifecycle activation chain `PIP_BOUND -> PLANNING -> RUNNING`.
- Durable Stage-3.2.3 PIP-activation lineage prerequisite for `START_PLANNING`.
- Durable Stage-3.2.4 planning-activation lineage prerequisite for the initial `START` from `PLANNING`.
- Guard checks:
  - `PIP_ACTIVATION_EVIDENCE_FOR_PLANNING`
  - `PLANNING_ACTIVATION_EVIDENCE_FOR_INITIAL_RUN`
  - `CANONICAL_ENVELOPE_INTEGRITY_FOR_PLANNING_RUN_ACTIVATION`
- `GET /api/missions/{mission_id}/planning-run-activation-contract`.
- Planning/run activation projection embedded in lifecycle-command discovery.
- Durable `mission_planning_run_activation` transition metadata and command response evidence.
- Activation-chain reconstruction from the append-only state-transition ledger.
- Fourteen Stage-3.2.4 regression cases.
- `STAGE3_2_4_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.4-planning-run-activation`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.4`.
- Lifecycle guard discovery now evaluates Stage-3.2.4 activation-lineage prerequisites.
- Previous regression assertions recognize Stage 3.2.4 as current while preserving Stage 3.2.3 in `supported_controls`.

## Preserved

- Stage 3.1.2 canonical topology authority.
- Stage 3.1.6 version-vector/idempotency command gate.
- Stage 3.2.2 deterministic local guard matrix.
- Stage 3.2.3 immutable PIP activation evidence.
- Immutable Mission envelope and exact PIP id/version.
- Existing command journal, state transition ledger, and Mission event lineage.
- Legacy direct state-transition API surface; however, direct topology transitions do not fabricate lifecycle activation evidence.
- Repository migration level **8**.
- aptsGSS as sole external Governance/authorization authority.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.
- No source changes in aptsGSS or VulnDesk.

## Deliberately deferred

- No autonomous planner implementation.
- No plan artifact persistence/schema.
- No evidence/approval dependency resolver; Stage 3.2.5.
- No pause/resume/replanning control extension; Stage 3.2.6.
- No verified cleanup/completion gate; Stage 3.2.8.
- No target action dispatch or actuation.

## Validation

- Python compile: PASS.
- Full regression: **166 passed**.
