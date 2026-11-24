# Stage 3.6.8 — Verified Completion Declaration & Lifecycle Handoff

Stage 3.6.8 converts a **verified, blocker-free Stage-3.6.7 readiness result** into an immutable Mission completion declaration and then hands lifecycle authority to the existing canonical Stage-3.2 command machinery. It is the first Stage-3.6 control that is authorized to complete the Mission, but it does **not** bypass the lifecycle guards that already govern cleanup and verified completion.

## Runtime identity

- control: `stage3.6.8-verified-completion-declaration-lifecycle-handoff`
- server: `APTSMissionOrchestrator/3.6.8`
- repository migration level: `43`
- migration: `043_stage3_6_8_verified_completion_declaration_lifecycle_handoff.sql`
- durable store: `mission_verified_completion_declarations`
- identity prefix: `mdecl-`
- declaration event: `MISSION_VERIFIED_COMPLETION_DECLARED`
- handoff event: `MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED`

## Verified completion chain

The declaration is fail-closed. Stage 3.6.8 requires the Mission to still be `RUNNING`, the exact active Plan head to remain unchanged, and the referenced Stage-3.6.7 decision to be current for the same state/version vector. The Stage-3.6.7 contract must report `READY`, `completion_ready=true`, and zero blockers. Stage 3.6.8 then re-verifies the linked Stage-3.6.6 evaluation (`SUCCESS_CRITERIA_SATISFIED`, every criterion `SATISFIED`) and the Stage-3.6.5 aggregation (`all_tasks_terminal=true`, `all_tasks_verified_complete=true`, `terminal_non_success_present=false`).

The resulting `mdecl-*` contract binds the Mission identity/version, active Plan, Stage-3.6.7 readiness decision, Stage-3.6.6 evaluation, and Stage-3.6.5 aggregation. The declaration is stored before any lifecycle mutation, providing a durable restart point.

## Lifecycle handoff

Completion is performed only by the canonical lifecycle API:

`RUNNING -> BEGIN_CLEANUP -> CLEANING_UP -> COMPLETE -> COMPLETED`

Stage 3.6.8 projects its verified declaration into the exact Stage-3.2.8 completion evidence shape: verified objective status, exact criterion coverage with evidence references, verified cleanup checks, and zero outstanding critical dependencies. The existing Stage-3.2.8 gate remains responsible for validating that evidence before the `COMPLETE` transition succeeds.

The handoff is restart-safe. A retry with the same idempotency key can recover when the declaration is durable but cleanup has not started, after `BEGIN_CLEANUP` has reached `CLEANING_UP`, or after `COMPLETE` has already reached `COMPLETED`. Canonical command journals and causation-keyed events prevent duplicate completion work.

## Authority boundary

Stage 3.6.8 exercises Mission-success completion authority only after the entire Stage-3.6 evidence chain verifies. It never performs a direct state-transition bypass and does not query Governance/runtime services, re-dispatch execution, perform external network I/O, or actuate a target. State mutation remains confined to `execute_mission_lifecycle_command`.

## API surface

- `POST /api/missions/{mission_id}/verified-completion-declarations`
- `GET /api/missions/{mission_id}/verified-completion-declarations`
- `GET /api/missions/{mission_id}/verified-completion-declarations/{declaration_id}`
- `GET /api/missions/{mission_id}/verified-completion-definition`

## Verification baseline

- canonical pytest inventory: **1122 tests**
- focused Stage-3.6.8 suite: **20 tests**
- Stage-3.6.1 through Stage-3.6.8 chain inventory: **159 tests**
- acceptance entry point: `STAGE3_6_8_ACCEPTANCE.ps1`

The next planned control is **Stage 3.6.9**.
