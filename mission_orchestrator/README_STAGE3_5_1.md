# Stage 3.5.1 — Canonical Execution Dispatch Contract & Identity

## Purpose

Stage 3.5.1 is the first execution-dispatch control after the Stage-3.4 routing/delegation closure. Its responsibility is deliberately narrow: materialize an **immutable canonical execution-dispatch identity and contract** for one active planned task that already has a delivered, acknowledged, and accepted Stage-3.4.7 ownership receipt.

Stage 3.5.1 does **not** dispatch work to a runtime target and does **not** authorize execution. It creates the durable control-plane object that later execution controls can reference without reconstructing mutable routing/delegation context.

The canonical identity is:

```text
xdispatch-<uuid>
```

The materialized contract is bound to exact immutable provenance from the active Mission state, Plan, route, Governance delegation authorization, delegation/handoff, delivery/ACK/ownership receipt, and any Stage-3.4.8 recovery-control state.

## Architectural position

```text
Stage 3.4.10  Routing & Delegation Acceptance / Regression Gate
      |
Stage 3.5.1   Canonical Execution Dispatch Contract & Identity
      |
      +--> immutable xdispatch-* identity
      +--> exact Mission state/version-vector binding
      +--> exact active Plan binding
      +--> exact Stage-3.4.4 route provenance
      +--> exact Stage-3.4.5 delegation-authorization provenance
      +--> exact Stage-3.4.6 delegation/handoff provenance
      +--> exact Stage-3.4.7 delivery/ACK/ownership provenance
      +--> Stage-3.4.8 recovery-control fail-closed binding
      +--> durable event + repository evidence
      |
      +--> NO runtime endpoint resolution
           NO runtime health probe
           NO resource assignment
           NO new Governance query
           NO execution authorization/grant
           NO dispatch attempt
           NO external network I/O
           NO target-action dispatch
           NO target actuation

Later Stage-3.5 controls must perform the required pre-dispatch Governance
revalidation and any actual execution-dispatch activity.
```

## Runtime identity

```text
control_version = stage3.5.1-canonical-execution-dispatch-contract-identity
server_version  = APTSMissionOrchestrator/3.5.1
repository_migration_level = 27
```

Stage 3.5.1 adds:

```text
migration 027
mission_execution_dispatch_contracts
MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED
```

## Canonical contract identity

Implementation:

```text
mission_orchestrator/execution_dispatch.py
```

Contract constants:

```text
schema_version = apts-canonical-execution-dispatch-contract-v1
identity_prefix = xdispatch-
status = MATERIALIZED_PENDING_PRE_DISPATCH_AUTHORIZATION
execution_authorization_status = NOT_EVALUATED
mode = IMMUTABLE_EXECUTION_DISPATCH_IDENTITY_BOUND_TO_OWNED_DELEGATION_PENDING_PRE_DISPATCH_AUTHORIZATION
allowed_source_states = RUNNING
```

The canonical dispatch target is **logical only**. `runtime_endpoint` is intentionally `null` at this stage.

## Preconditions and exact bindings

Stage 3.5.1 fails closed unless all of the following remain current and internally consistent:

1. Mission exists and is in `RUNNING` state.
2. `expected_state_version` matches the current Mission state version.
3. `expected_version_sha256` matches the complete current Mission version vector.
4. `expected_active_plan_version_record_id`, Plan version, and Plan hash match the active Plan head.
5. The Stage-3.4.7 delivery receipt exists and its exact hash matches.
6. The receipt is bound to the requested planned task and active Plan.
7. Delivery, acknowledgement, and control-plane ownership are all accepted.
8. The exact Stage-3.4.6 delegation and handoff envelope pass integrity verification.
9. The exact Stage-3.4.4 route-decision provenance remains intact.
10. The exact Stage-3.4.5 Governance-bound delegation authorization remains `AUTHORIZED` and is not reused as execution authority.
11. The Mission scope contract remains current and matches the ownership chain.
12. The Governance binding remains current and matches the ownership chain.
13. A conflict-frozen or unresolved Stage-3.4.8 recovery state blocks materialization.

## Identity and immutability rules

Stage 3.5.1 enforces:

```text
one xdispatch identity per (mission_id, plan_version, planned_task_id)
unique execution_dispatch_id
unique (mission_id, idempotency_key)
```

An exact replay of the same canonical request and idempotency key returns the existing contract with `idempotent_replay = true` and does not duplicate the Mission event. Reusing the same idempotency key for a different canonical request fails with a conflict.

The contract contains a domain-separated canonical SHA-256 digest and is reverified when read from persistence.

## Execution-authority boundary

The following separations are explicit invariants:

```text
OWNERSHIP != EXECUTION AUTHORITY
DELEGATION AUTHORIZATION != EXECUTION AUTHORIZATION
DISPATCH CONTRACT != DISPATCH
DISPATCH IDENTITY != EXECUTION AUTHORIZATION
LOGICAL TARGET != RUNTIME ENDPOINT
MATERIALIZATION != NETWORK DISPATCH
```

Stage 3.5.1 declares:

```text
pre_dispatch_governance_revalidation_required = true
ownership_is_execution_authority = false
dispatch_contract_is_dispatch = false
dispatch_identity_is_execution_authorization = false
runtime_endpoint_resolution_performed = false
runtime_health_probe_performed = false
resource_assignment_performed = false
governance_query_performed = false
execution_authorization_performed = false
dispatch_attempt_started = false
dispatch_performed = false
external_network_io_performed = false
target_action_dispatch_enabled = false
target_actuation = false
version_vector_extension_performed = false
```

## Persistence

Migration:

```text
migrations/027_stage3_5_1_canonical_execution_dispatch_contract_identity.sql
```

Durable store:

```text
mission_execution_dispatch_contracts
```

The store binds each dispatch identity to:

- Mission and active Plan identity;
- planned task and task key;
- delivery receipt;
- delegation and handoff;
- route decision;
- Governance-bound delegation authorization;
- logical target subsystem/capability;
- source Mission state and version-vector digest;
- request digest, idempotency key, canonical digest, creator, reason, and timestamp.

The Mission repository projection exposes the new store and repository integrity checks verify the persisted contract, provenance references, canonical digest, and matching materialization event.

## Mission event

Materialization records exactly one canonical event per dispatch identity:

```text
MISSION_EXECUTION_DISPATCH_CONTRACT_MATERIALIZED
```

Idempotent replay repairs/ensures event presence without creating duplicate event cardinality.

## HTTP API

Stage 3.5.1 adds:

```text
POST /api/missions/{mission_id}/execution-dispatch-contracts
GET  /api/missions/{mission_id}/execution-dispatch-contracts
GET  /api/missions/{mission_id}/execution-dispatch-contracts/{execution_dispatch_id}
GET  /api/missions/{mission_id}/execution-dispatch-contract-definition
```

POST returns `201` for first materialization and `200` for an idempotent replay.

Caller-supplied runtime endpoint, worker/resource assignment, execution payload, Governance decision, execution grant, dispatch attempt, command payload, target-action dispatch, or actuation fields are rejected by the canonical request validator.

## Acceptance coverage

`tests/test_stage3_5_1_canonical_execution_dispatch_contract_identity.py` contains 19 focused cases covering:

- active runtime identity and Stage-3.4.10 predecessor ordering;
- canonical definition and no-execution semantics;
- immutable `xdispatch-*` materialization;
- `RUNNING` state guard;
- stale Mission state/version-vector rejection;
- stale active-Plan rejection;
- missing/stale delivery receipt rejection;
- forbidden runtime/execution/dispatch inputs;
- idempotency and idempotency conflict;
- single immutable identity per active Plan task;
- no Governance query and no network/dispatch side effect;
- recovery conflict fail-closed semantics;
- restart persistence and integrity verification;
- repository projection and event lineage;
- tamper detection;
- HTTP route and migration registration.

## Package-construction regression evidence

The reconstructed Stage-3.5.1 source was verified in the build environment with partitioned execution of the complete collected suite:

```text
Stage 3.1          111 passed
Stage 3.2          156 passed
Stage 3.3          239 passed
Stage 3.4          273 passed
Stage 3.5.1         19 passed
--------------------------------
Total              798 passed
```

Pytest collection independently reported:

```text
798 tests collected
```

Python compilation also passed.

Partitioning was used only to accommodate the build-tool execution window. The target-host acceptance harness intentionally runs the normal full regression in one pytest invocation and remains the official deployment evidence.

## Acceptance harness

After installing the package, applying migration 027 where required, and restarting Mission Orchestrator, run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_5_1_ACCEPTANCE.ps1
```

The harness requires the active runtime to report Stage 3.5.1 and migration level 27, then runs compilation, verifies the 798-test inventory, runs the full regression, runs the focused Stage-3.5.1 suite, and validates the live no-dispatch/no-execution authority boundary.
