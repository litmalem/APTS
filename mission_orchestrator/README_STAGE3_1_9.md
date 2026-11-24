# Stage 3.1.9 — Mission Event & Lineage Foundation

## Purpose

Stage 3.1.9 adds the **Mission Event & Lineage Foundation** to the Global Mission Orchestrator (`APTS-MO01`). The stage makes important local Mission mutations auditable as durable canonical events and exposes a read-only lineage projection without moving policy, CTI, planning, or target-execution authority into the Mission Orchestrator.

Stage 3.1.9 builds directly on the stable Stage-3.1.8 Canonical Mission API and Stage-3.1.7 durable repository model.

Authority boundaries remain unchanged:

- `APTS-MO01` owns canonical global Mission identity/state/contracts and the new local Mission event ledger.
- `aptsGSS / GOV-PLANE` remains the sole authority for policy decisions, approval, revocation, hard-deny, and emergency-stop semantics.
- VulnDesk/CTI remains authoritative for CTI-local `state_version` and `plan_version`.
- The Stage-3.1.9 lineage API does not query Governance or CTI.
- No Global Planner, target-action dispatch, or target actuation is introduced.

## Event contract

Stage 3.1.9 declares:

- `mission_event_schema_version = apts-mission-event-v1`
- `mission_lineage_schema_version = apts-mission-lineage-v1`
- `mission_event_mode = DURABLE_APPEND_ONLY_HASH_CHAIN`
- `mission_lineage_mode = MISSION_ROOT_TRACE_BUSINESS_CAUSATION_LOCAL_PARENT_CHAIN`
- `source_component = APTS-MO01`

Every canonical Mission event contains the required lineage fields:

- `event_id` — immutable local event identifier.
- `mission_id` — canonical global Mission identifier.
- `trace_id` — root local Mission event identifier. The first recorded event is its own trace root; later events inherit it.
- `correlation_id` — canonical Mission envelope correlation identifier.
- `causation_id` — durable business mutation/artifact identifier that caused the event, for example an envelope, transition, snapshot, binding, task, dispatch attempt, or command identifier.
- `parent_event_id` — immediate preceding local Mission event, creating an ordered local causal chain.
- `source_component` — `APTS-MO01` for this ledger.
- `event_type` — canonical event taxonomy value.
- `state_version` — canonical Mission state version observed at the event.
- `plan_version` — downstream plan version when available; otherwise null.
- `policy_version` — authoritative Governance policy version previously persisted in the Mission authorization binding when available; otherwise null.
- `occurred_at` — event occurrence timestamp.

The durable row also stores:

- `previous_event_sha256` — digest of the preceding local event.
- `canonical_sha256` — SHA-256 over the immutable event material and hash-domain discriminator.
- `recorded_at` — durable repository recording timestamp.
- structured `payload` — event-specific audit evidence.

## Canonical event taxonomy

The Stage-3.1.9 ledger recognizes these event types:

1. `MISSION_REGISTERED`
2. `MISSION_STATE_TRANSITIONED`
3. `MISSION_SCOPE_CONTRACT_COMMITTED`
4. `MISSION_GOVERNANCE_BOUND`
5. `MISSION_AUTHORIZATION_BOUND`
6. `MISSION_ROUTING_TASK_CREATED`
7. `MISSION_ROUTING_TASK_DISPATCHED`
8. `MISSION_COMMAND_COMPLETED`

Events are emitted only from successful local Mission-Orchestrator mutation paths. There is deliberately **no public event-create API**, preventing callers from forging canonical Mission lineage.

## Hash-chain integrity

For each Mission, events are ordered by the local append sequence. The first event has:

- `trace_id == event_id`
- `parent_event_id = null`
- `previous_event_sha256 = null`

Every subsequent event must:

- keep the root `trace_id` unchanged;
- set `parent_event_id` to the immediately previous local event;
- set `previous_event_sha256` to the previous event's `canonical_sha256`;
- pass its own canonical SHA-256 verification.

Event and lineage reads verify the complete Mission event chain. A corrupted row therefore fails closed with `MISSION_EVENT_INTEGRITY_ERROR` rather than returning a partially trusted projection. Stage-3.1.7 repository reconstruction also includes this chain as an integrity gate.

## Idempotency

The repository enforces one canonical event per:

`(mission_id, event_type, causation_id)`

This prevents a replayed canonical mutation from producing duplicate audit events. Event identifiers remain unique globally within the Mission repository.

## Historical behavior

Stage 3.1.9 deliberately uses:

`NO_SYNTHETIC_HISTORICAL_EVENTS`

Existing Stage-3.1.1 through Stage-3.1.8 durable rows are **not** rewritten into invented historical events. If a pre-3.1.9 Mission has no event history, the first new Stage-3.1.9 mutation becomes the local trace root and the projection reports:

`history_complete_from_registration = false`

New Missions created under Stage 3.1.9 begin with `MISSION_REGISTERED` and report complete local history from registration.

## Read-only APIs

Stage 3.1.9 adds:

- `GET /api/missions/{mission_id}/events`
- `GET /api/missions/{mission_id}/events/{event_id}`
- `GET /api/missions/{mission_id}/lineage`

### Event collection

`GET /api/missions/{mission_id}/events` returns the verified ordered event ledger, event count, history-completeness flag, and `integrity_status=PASS`.

### Single event

`GET /api/missions/{mission_id}/events/{event_id}` returns one event only after verifying the **whole Mission chain**, not just the selected row.

### Lineage projection

`GET /api/missions/{mission_id}/lineage` returns:

- Mission/trace/correlation identity;
- ordered canonical events;
- `LOCAL_PARENT` causal edges;
- external upstream references when a stored event payload contains an authoritative Governance event reference;
- integrity status and explicit authority/execution-boundary flags.

The lineage projection is local and read-only:

- `external_authority_query_performed = false`
- `target_action_dispatch_enabled = false`
- `target_actuation = false`

## External-event references

When an already-received Governance response carries an authoritative event ID, Stage 3.1.9 stores that identifier in the local event payload as an upstream reference. It does **not** redefine a Governance event as an APTS-MO01 event and does not overload `parent_event_id` with cross-subsystem authority semantics.

## Repository integration

Stage-3.1.7 persistence reconstruction now includes:

- `mission_events` in record counts;
- `mission_event_store` in the persistence manifest;
- `mission_event_append_only_hash_chain` as an integrity check.

The persistence manifest remains deterministic over durable content and includes event references in its canonical repository digest.

## Database migration

Stage 3.1.9 adds:

`migrations/008_stage3_1_9_mission_event_lineage_foundation.sql`

The repository migration level advances from **7 to 8**.

The migration creates `mission_events` with:

- unique `event_id`;
- unique `(mission_id, event_type, causation_id)` replay gate;
- Mission, trace, correlation, parent, and causation indexes;
- canonical hash-chain fields;
- a foreign key to `global_missions`.

For SQLite local development, `MissionRepository.ensure_schema()` materializes the same table automatically and updates repository metadata to migration level 8. For MariaDB/MySQL deployment, apply migration 008 before restarting the Stage-3.1.9 service.

## Health contract

`GET /health` reports, among others:

- `control_version=stage3.1.9-mission-event-lineage-foundation`
- repository migration level `8`
- the event and lineage schema versions/modes;
- the canonical event taxonomy;
- `mission_event_audit_hooks_enabled=true`
- `mission_event_external_delivery_enabled=false`
- `mission_event_external_authority_queries=false`
- `mission_event_historical_backfill_mode=NO_SYNTHETIC_HISTORICAL_EVENTS`

Existing safety boundaries remain:

- `dispatch_enabled=false`
- `target_action_dispatch_enabled=false`
- `target_actuation=false`

The existing Stage-3.1.5 **subsystem routing** path remains a governed metadata/control-plane handoff and is not reclassified as target-action execution.

## Explicit non-goals

Stage 3.1.9 does not implement:

- a public event-ingestion endpoint;
- an external event bus or event delivery worker;
- synthetic historical event reconstruction;
- a new policy or authorization authority;
- a Global Planner;
- target-action dispatch or target actuation;
- replacement of CTI/Pentest subsystem-local authority;
- mutation of aptsGSS or VulnDesk source code.

## Validation evidence

Patch-local validation:

- `python -m compileall -q mission_orchestrator tests` — PASS
- `python -m pytest -q` — **101 passed**
- live HTTP `/health` — PASS
- live HTTP Mission create → root event — PASS
- live HTTP state transition → chained event — PASS
- live HTTP `/events` — PASS
- live HTTP `/events/{event_id}` — PASS
- live HTTP `/lineage` — PASS
- live HTTP `/repository` event-manifest/integrity projection — PASS

