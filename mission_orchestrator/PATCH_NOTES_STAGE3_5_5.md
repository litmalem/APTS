# Patch Notes — Stage 3.5.5

## Added

- Canonical Stage-3.5.5 execution-delivery contract (`xack-*`).
- Runtime endpoint resolution and health probing after all local/durable guards pass.
- Immutable `xenv-*` runtime delivery with downstream idempotency binding.
- Strict execution acknowledgement normalization and fail-closed protocol validation.
- Durable `mission_execution_deliveries` store (migration 031).
- API routes for create/history/get/definition of execution deliveries.
- Canonical event `MISSION_EXECUTION_DISPATCH_DELIVERED_ACKNOWLEDGED`.
- Repository reconstruction, persistence-manifest projection, record counts, and tamper detection for Stage 3.5.5.
- 19 focused Stage-3.5.5 tests.

## Preserved boundaries

- Stage 3.5.3 remains the authoritative Governance decision point; Stage 3.5.5 does not issue a new Governance query.
- Stage 3.5.4 remains the durable initial execution-attempt and immutable-envelope identity boundary.
- Stage 3.5.5 performs runtime delivery and records acceptance only.
- Stage 3.5.6 remains responsible for RUNNING state and heartbeat semantics.
- Stage 3.5.5 performs no target actuation.

## Runtime/version changes

- `control_version`: `stage3.5.5-dispatch-delivery-execution-acknowledgement`
- server: `APTSMissionOrchestrator/3.5.5`
- repository migration: `31`
- canonical test inventory: `875`
