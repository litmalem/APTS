# Patch Notes — Stage 3.5.6

## Added

- Canonical `xrun-*` Running Execution State & Heartbeat Projection contract.
- Runtime execution-status read through the exact Stage-3.5.5 persisted endpoint.
- Strict runtime identity binding for Mission, execution attempt, dispatch envelope, and target subsystem.
- Normalized `RUNNING / RUNNING_HEARTBEAT_CONFIRMED / ALIVE` projection semantics.
- Append-only heartbeat history with monotonic per-attempt sequence enforcement.
- Durable `mission_execution_running_projections` store and migration level 32.
- `MISSION_EXECUTION_RUNNING_HEARTBEAT_PROJECTED` event lineage.
- Repository reconstruction, record-count projection, persistence manifest, and tamper detection for Stage 3.5.6.
- REST APIs for creation, history, individual projection lookup, and canonical definition.
- Focused Stage-3.5.6 tests.

## Preserved boundaries

- Stage 3.5.3 remains the authority that granted the execution authorization used by the delivered attempt.
- Stage 3.5.4 remains the immutable execution-attempt / dispatch-envelope identity boundary.
- Stage 3.5.5 remains the runtime delivery and execution-intake acknowledgement boundary.
- Stage 3.5.6 observes an already-delivered execution; it does not create a new authorization decision.
- No new Governance query.
- No endpoint re-resolution.
- No dispatch redelivery.
- No target-action dispatch.
- `target_actuation=false`.

A later Governance decision does not suppress observation of a worker that is already running. Stage 3.5.6 validates the historical ALLOW evidence bound to the delivered attempt and keeps runtime observability independent from subsequent revocation/control handling.

## Runtime

- `control_version`: `stage3.5.6-running-execution-state-heartbeat-projection`
- server: `APTSMissionOrchestrator/3.5.6`
- migration: `32`
- schema: `apts-running-execution-state-heartbeat-projection-v1`
- persistence store: `mission_execution_running_projections`
