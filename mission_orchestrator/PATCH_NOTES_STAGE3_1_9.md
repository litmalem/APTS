# Patch Notes — Stage 3.1.9 Mission Event & Lineage Foundation

## Added

- Durable append-only `mission_events` repository store.
- Canonical event schema `apts-mission-event-v1`.
- Canonical lineage projection schema `apts-mission-lineage-v1`.
- Mission-root trace identity, canonical Mission correlation, business causation IDs, local parent-event chaining, and SHA-256 hash continuity.
- Canonical event hooks for registration, state transition, Scope contract commit, Governance binding, authorization binding, governed routing-task creation/dispatch, and completed Mission commands.
- Event replay guard on `(mission_id, event_type, causation_id)`.
- Read-only APIs for event collection, single-event retrieval, and Mission lineage.
- Event-chain verification integrated into Stage-3.1.7 repository integrity reconstruction.
- `mission_event_store` included in the durable persistence manifest.
- Migration `008_stage3_1_9_mission_event_lineage_foundation.sql`; repository migration level is now 8.
- Stage-3.1.9 unit/regression tests and PowerShell acceptance script.

## Preserved

- Stage-3.1.8 canonical Mission API and fail-closed validation pipeline.
- aptsGSS as the sole policy/approval/revocation/emergency-stop authority.
- CTI/VulnDesk ownership of subsystem-local state/plan versions.
- Existing governed subsystem-routing boundary.
- `dispatch_enabled=false` for target-action execution.
- `target_action_dispatch_enabled=false`.
- `target_actuation=false`.

## Deliberately not added

- No external event bus/outbox delivery in Stage 3.1.9.
- No public API that can forge canonical Mission events.
- No synthetic backfill of pre-3.1.9 Mission history.
- No Global Planner.
- No target-action dispatch/actuation.
- No Stage-3.1.9 source patch for aptsGSS or VulnDesk.

## Compatibility

- New Missions automatically start a complete local event history with `MISSION_REGISTERED`.
- Existing Missions remain valid. Their historical local rows are not synthesized into events; the first later Stage-3.1.9 mutation becomes their local trace root and `history_complete_from_registration=false`.
- SQLite schema materializes automatically through `ensure_schema()`.
- MariaDB/MySQL deployments must apply migration 008 before service restart.

## Validation

- Python compile: PASS.
- Full regression: **101 passed**.
- Live HTTP Stage-3.1.9 smoke: PASS.
