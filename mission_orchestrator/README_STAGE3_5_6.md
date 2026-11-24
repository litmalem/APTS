# Stage 3.5.6 — Running Execution State & Heartbeat Projection

Stage 3.5.6 converts the Stage-3.5.5 downstream execution-intake acknowledgement into an **observable RUNNING execution projection**. It does not create new execution authority and it does not redeliver the dispatch. Instead, it reuses the exact Stage-3.5.5 runtime binding, probes that runtime, reads authoritative execution state plus heartbeat evidence, validates all immutable identities, and persists an append-only `xrun-*` projection.

## Runtime identity

- `control_version`: `stage3.5.6-running-execution-state-heartbeat-projection`
- HTTP server: `APTSMissionOrchestrator/3.5.6`
- repository migration: `32`
- schema: `apts-running-execution-state-heartbeat-projection-v1`
- identity prefix: `xrun-`
- store: `mission_execution_running_projections`
- execution state: `RUNNING`
- attempt projection status: `RUNNING_HEARTBEAT_CONFIRMED`
- normalized heartbeat status: `ALIVE`

## Execution-control lineage

`Stage 3.5.1 xdispatch -> Stage 3.5.2 xelig -> Stage 3.5.3 xreval -> Stage 3.5.4 xattempt/xenv -> Stage 3.5.5 xack -> Stage 3.5.6 xrun`

The Stage-3.5.4 attempt and Stage-3.5.5 acknowledgement remain immutable source records. Stage 3.5.6 adds an append-only operational projection; it does not rewrite those records.

## Boundary semantics

Stage 3.5.6 requires all of the following before runtime observation:

1. Mission remains in canonical `RUNNING` state and the caller supplies the current state/version-vector concurrency guards.
2. The active Plan head exactly matches the supplied `pver-*` identity, version, and canonical SHA-256.
3. The referenced Stage-3.5.5 `xack-*` exists, verifies cryptographically, is bound to the active Plan, and is `DELIVERED_TO_RUNTIME / ACKNOWLEDGED_ACCEPTED_FOR_EXECUTION / DELIVERED_ACKNOWLEDGED_PENDING_RUNNING`.
4. The referenced Stage-3.5.4 `xattempt-*` and `xenv-*` exactly match the Stage-3.5.5 delivery and retain their canonical hashes.
5. The exact historical Stage-3.5.3 authorization bound into that attempt still exists and verifies as `ALLOW` execution evidence.

Only then does Stage 3.5.6 perform runtime observation.

## Why a later Governance DENY does not suppress observation

Stage 3.5.6 is deliberately an **observation boundary**, not a new authorization boundary. A later Governance decision can govern subsequent control/revocation behavior, but it must not make an already-running worker invisible to the orchestrator. Therefore Stage 3.5.6 verifies the historical Stage-3.5.3 ALLOW that authorized the delivered attempt, but it does **not** require that ALLOW to still be the latest decision and it issues **no new Governance query**.

This separation is intentional: authorization decides whether execution may be dispatched; runtime projection records what an already-delivered execution is actually doing.

## Runtime observation protocol

Stage 3.5.6 reuses the persisted Stage-3.5.5 runtime endpoint. It does not resolve the endpoint again.

1. `GET <runtime>/health`
2. `GET <runtime>/api/execution/attempts/{execution_attempt_id}/status?mission_id=...&dispatch_envelope_id=...`

The status path can be overridden with:

`MISSION_EXECUTION_STATUS_PATH_TEMPLATE`

Default:

`/api/execution/attempts/{execution_attempt_id}/status`

The runtime response must bind exactly to:

- `mission_id`
- `execution_attempt_id`
- `dispatch_envelope_id`
- target `subsystem_id` via `observed_by`
- `execution_state = RUNNING`
- `execution_started = true`
- stable `started_at`
- `target_actuation = false`
- heartbeat object containing `heartbeat_id`, positive integer `sequence`, `observed_at`, and `status=alive|healthy`

The Mission Orchestrator normalizes heartbeat status to `ALIVE`.

## Append-only heartbeat projection

Each successful observation creates a new `xrun-*` record. For one execution attempt:

- heartbeat sequence must strictly increase;
- heartbeat identity and sequence are unique;
- `started_at` must remain stable;
- exact request replay is idempotent and performs no new runtime I/O;
- a reused idempotency key with different request content fails closed.

This preserves temporal execution evidence without mutating earlier observations.

## Explicit non-authorities

Stage 3.5.6 performs:

- runtime health probe: **yes**
- runtime execution-state query: **yes**
- execution start observation: **yes**
- RUNNING state projection: **yes**
- heartbeat projection: **yes**

Stage 3.5.6 performs **not**:

- new Governance query
- runtime endpoint resolution
- dispatch redelivery
- new target-action dispatch
- target actuation

`target_actuation` remains `false` throughout the Stage-3.5.6 contract and event evidence.

## Persistence and lineage

Migration `032_stage3_5_6_running_execution_state_heartbeat_projection.sql` adds `mission_execution_running_projections` with uniqueness constraints over:

- `running_projection_id`
- `(mission_id, idempotency_key)`
- `(mission_id, execution_attempt_id, heartbeat_id)`
- `(mission_id, execution_attempt_id, heartbeat_sequence)`

Each durable projection emits `MISSION_EXECUTION_RUNNING_HEARTBEAT_PROJECTED`. Repository reconstruction verifies the projection contract, source `xack-*` and `xattempt-*` hashes, runtime binding, heartbeat monotonicity, event payload, record count, and persistence-manifest inclusion.

## API surface

- `POST /api/missions/{mission_id}/execution-running-projections`
- `GET /api/missions/{mission_id}/execution-running-projections`
- `GET /api/missions/{mission_id}/execution-running-projections/{running_projection_id}`
- `GET /api/missions/{mission_id}/execution-running-projection-definition`

## Verification

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_5_6_ACCEPTANCE.ps1
```

Focused Python proof:

```powershell
python -m pytest -q tests\test_stage3_5_6_running_execution_state_heartbeat_projection.py
```

Stage 3.5.6 closes only the RUNNING/heartbeat observation boundary. The next lifecycle concern remains Stage 3.5.7.
