# Stage 3.5.5 — Dispatch Delivery & Execution Acknowledgement

Stage 3.5.5 opens the first **runtime delivery boundary** in the Stage-3.5 execution lifecycle. It consumes the durable Stage-3.5.4 `xattempt-*` + immutable `xenv-*`, resolves the canonical target subsystem runtime endpoint, verifies runtime health, delivers the immutable dispatch envelope, and persists a canonical downstream acknowledgement.

## Control identity

- `control_version`: `stage3.5.5-dispatch-delivery-execution-acknowledgement`
- HTTP server: `APTSMissionOrchestrator/3.5.5`
- repository migration level: `31`
- schema: `apts-dispatch-delivery-execution-acknowledgement-v1`
- identity: `xack-*`
- persistence store: `mission_execution_deliveries`
- canonical event: `MISSION_EXECUTION_DISPATCH_DELIVERED_ACKNOWLEDGED`

## Lifecycle boundary

The execution chain is now:

`Stage 3.5.1 xdispatch -> Stage 3.5.2 xelig -> Stage 3.5.3 xreval -> Stage 3.5.4 xattempt/xenv -> Stage 3.5.5 xack`

Stage 3.5.5 is intentionally **not** Stage 3.5.6. A successful Stage-3.5.5 record means the downstream subsystem accepted the immutable dispatch envelope for execution intake. It does **not** mean that execution is already RUNNING.

Canonical statuses after successful delivery:

- delivery: `DELIVERED_TO_RUNTIME`
- acknowledgement: `ACKNOWLEDGED_ACCEPTED_FOR_EXECUTION`
- attempt projection: `DELIVERED_ACKNOWLEDGED_PENDING_RUNNING`
- `execution_started = false`
- `running_state_recorded = false`
- `heartbeat_recorded = false`
- `target_actuation = false`

Stage 3.5.6 owns the RUNNING/heartbeat boundary.

## Safety and authority rules

Before any external network I/O, Mission Orchestrator revalidates all durable/local invariants:

1. Mission must still be `RUNNING` with the exact expected state version and Mission version-vector hash.
2. The exact active Plan head must still match.
3. The referenced Stage-3.5.4 execution attempt must exist, verify cryptographically, remain bound to the active Plan, and still be `COMMITTED_IDEMPOTENT_PENDING_DELIVERY / CREATED_NOT_DELIVERED`.
4. The Stage-3.5.4 attempt must still reference the **latest** Stage-3.5.3 revalidation.
5. That latest revalidation must still be an authoritative `ALLOW` with execution authorization.
6. The target subsystem/capability must still be present, registered, enabled, and version-consistent in the canonical subsystem registry.
7. No existing Stage-3.5.5 acknowledgement may already exist for the same `xattempt-*`.

Only after those checks pass does Stage 3.5.5 resolve an endpoint, perform a runtime health probe, and deliver the immutable envelope.

## No new Governance decision

Stage 3.5.5 performs **no new Governance query**. It consumes and verifies the authorization evidence created by Stage 3.5.3 and bound into Stage 3.5.4. If a newer Stage-3.5.3 decision supersedes the referenced authorization, delivery fails closed before external runtime I/O.

## Downstream idempotency

The immutable `xenv-*` identity is the downstream runtime idempotency key. This is deliberate: if the network loses an acknowledgement after the target accepted a dispatch, a retry can present the exact same envelope identity to the target instead of inventing a second execution identity.

Mission Orchestrator separately maintains local Stage-3.5.5 idempotency using the caller-provided request `idempotency_key`. Once a canonical `xack-*` is persisted, an exact local replay returns the same acknowledgement without re-delivering to the target.

## Runtime protocol

Default target endpoint resolution:

- CTI: `MISSION_CTI_EXECUTION_BASE_URL`, then `MISSION_CTI_BASE_URL`, default `http://127.0.0.1:8765`
- PENTEST: `MISSION_PENTEST_EXECUTION_BASE_URL`, then `MISSION_PENTEST_BASE_URL`, default `http://127.0.0.1:8790`

Runtime health probe:

- `GET <runtime>/health`

Delivery endpoint:

- default `POST <runtime>/api/execution/dispatches`
- override path with `MISSION_EXECUTION_DISPATCH_PATH`

Timeout:

- `MISSION_EXECUTION_DELIVERY_TIMEOUT_SECONDS`, default `5.0`

The downstream acknowledgement must bind the exact `mission_id`, `execution_attempt_id`, and `dispatch_envelope_id`, identify the expected target subsystem, report `ACKNOWLEDGED_ACCEPTED_FOR_EXECUTION`, and explicitly confirm both `execution_started=false` and `target_actuation=false`.

## API

- `POST /api/missions/{mission_id}/execution-deliveries`
- `GET /api/missions/{mission_id}/execution-deliveries`
- `GET /api/missions/{mission_id}/execution-deliveries/{execution_delivery_id}`
- `GET /api/missions/{mission_id}/execution-delivery-definition`

Caller-supplied runtime endpoint, health result, recipient rewrite, acknowledgement, execution-start, and target-actuation fields are forbidden. Those values are derived from authoritative sources or the downstream runtime response.

## Persistence and reconstruction

Migration `031_stage3_5_5_dispatch_delivery_execution_acknowledgement.sql` introduces `mission_execution_deliveries` and uniqueness constraints for:

- local idempotency key per mission;
- one Stage-3.5.5 acknowledgement per execution attempt;
- one Stage-3.5.5 acknowledgement per immutable dispatch envelope.

Repository reconstruction verifies the contract hash, source Stage-3.5.4 attempt binding, policy provenance, runtime/target identity, acknowledgement identity/hash, event lineage, and explicit non-RUNNING/non-actuation semantics. The Stage-3.5.5 store is included in the persistence manifest and record-count projection.

## Verification

Focused proof:

```powershell
python -m pytest -q tests\test_stage3_5_5_dispatch_delivery_execution_acknowledgement.py
```

Acceptance gate:

```powershell
.\STAGE3_5_5_ACCEPTANCE.ps1
```

The package contains **875 canonical tests**: the previous 856-test Stage-3.5.4 inventory plus 19 focused Stage-3.5.5 tests.
