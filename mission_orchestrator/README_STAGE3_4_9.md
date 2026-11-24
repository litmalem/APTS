# Stage 3.4.9 — Routing/Delegation Event Lineage, Replay & Recovery

## Purpose

Stage 3.4.9 closes the observability and recoverability layer for **Stage 3.4 — Subsystem Routing & Task Delegation**. It projects the canonical Mission event ledger into a routing/delegation-only causal lineage, provides deterministic read-only replay, and persists restart-safe recovery checkpoints that reconstruct the exact routing/delegation state from durable canonical artifacts.

The stage answers three operational questions:

1. What exact routing/delegation event chain produced the current delegated ownership state?
2. Can that chain be replayed deterministically for audit/debugging without repeating any side effect?
3. Can the routing/delegation state be reconstructed after restart from durable repository evidence without rerouting, reauthorizing, redelivering, transferring ownership, dispatching, or executing anything?

Stage 3.4.9 is therefore an **evidence/replay/recovery control**, not a new execution authority.

## Architectural position

```text
Stage 3.4.1 Canonical Subsystem Registry & Capability Contract
        |
Stage 3.4.2 Task Routing Intent & Candidate Resolution
        |
Stage 3.4.3 Routing Eligibility & Compatibility Gate
        |
Stage 3.4.4 Deterministic Route Selection & Decision Record
        |
Stage 3.4.5 Governance-Bound Delegation Authorization
        |
Stage 3.4.6 Canonical Delegation Contract & Handoff Envelope
        |
Stage 3.4.7 Delegation Delivery, Acknowledgement & Ownership
        |
Stage 3.4.8 Retry, Fallback, Reassignment & Conflict Control
        |
Stage 3.4.9 Routing/Delegation Event Lineage, Replay & Recovery
        |
        +--> audit / deterministic replay / restart recovery only
             no reroute / no reauthorization / no redelivery
             no ownership transfer / no dispatch / no execution
```

## Runtime identity

```text
control_version = stage3.4.9-routing-delegation-event-lineage-replay-recovery
server_version  = APTSMissionOrchestrator/3.4.9
repository_migration_level = 26
lineage_schema_version = apts-routing-delegation-event-lineage-v1
replay_schema_version = apts-routing-delegation-event-replay-v1
recovery_checkpoint_schema_version = apts-routing-delegation-recovery-checkpoint-v1
store = mission_routing_delegation_recovery_checkpoints
event = MISSION_ROUTING_DELEGATION_RECOVERY_CHECKPOINTED
```

## Canonical routing/delegation chain

The canonical lineage definition covers:

```text
ROUTING_INTENT
  -> ELIGIBILITY_GATE
  -> ROUTE_DECISION
  -> GOVERNANCE_BOUND_DELEGATION_AUTHORIZATION
  -> DELEGATION_AND_HANDOFF
  -> DELIVERY_ACKNOWLEDGEMENT_OWNERSHIP
  -> ZERO_OR_MORE_RECOVERY_CONTROLS
```

The event family is filtered from the already verified Mission event chain. Stage 3.4.9 does not create an independent competing event ledger.

Canonical event types include:

- `MISSION_TASK_ROUTING_CANDIDATES_RESOLVED`
- `MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED`
- `MISSION_TASK_ROUTE_DECISION_RECORDED`
- `MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED`
- `MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED`
- `MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED`
- `MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED`
- `MISSION_ROUTING_DELEGATION_RECOVERY_CHECKPOINTED`

## Read-only deterministic replay

Replay is generated from verified canonical Mission events in their committed causal order. The replay artifact contains replay sequence, event identity/type, causation, state/plan/policy versions, artifact identity, event SHA-256, predecessor SHA-256, and timestamp.

The replay contract explicitly guarantees:

```text
read_only = true
side_effects_performed = false
replay_is_execution = false
```

Calling replay never invokes routing, Governance, handoff delivery, retry/fallback, ownership transfer, dispatch, or target execution.

## Durable recovery checkpoint

A Stage-3.4.9 checkpoint binds the exact durable trajectory visible at creation time:

- current Mission state and version vector;
- Stage-3.4.4 route decision ID/SHA-256;
- Stage-3.4.6 delegation ID/SHA-256;
- Stage-3.4.7 delivery/ownership receipt ID/SHA-256;
- exact Stage-3.4.8 recovery-control count and control-chain tip when present;
- exact routing/delegation event count and event-chain tip SHA-256;
- active Plan version record / planned task binding;
- deterministic recovery state reconstructed from those durable artifacts.

Only one checkpoint is allowed for a given `(mission, delivery_receipt, recovery_control_count)` snapshot. A new checkpoint becomes valid only after the Stage-3.4.8 control chain advances.

## Recovery semantics

Recovery reads the latest durable checkpoint and re-verifies its source artifacts. It performs no external refresh and no side effect.

```text
reconstructed_from_durable_repository = true
external_network_io_performed = false
governance_query_performed = false
replay_is_execution = false
recovery_is_authorization = false
recovery_is_routing = false
recovery_is_redelivery = false
recovery_is_ownership_transfer = false
dispatch_performed = false
execution_authorized = false
target_action_dispatch_enabled = false
target_actuation = false
```

A corrupted checkpoint, corrupted source artifact, incomplete Stage-3.4.8 control chain, or mismatched control-chain tip fails closed through repository integrity verification.

## Canonical checkpoint request

POST:

```text
/api/missions/{mission_id}/routing-delegation-recovery-checkpoints
```

Canonical request fields:

```json
{
  "idempotency_key": "stage349-checkpoint-...",
  "expected_version_sha256": "<64 hex>",
  "expected_state_version": 1,
  "expected_delivery_receipt_id": "drecv-...",
  "expected_delivery_receipt_sha256": "<64 hex>",
  "expected_delegation_id": "deleg-...",
  "expected_delegation_sha256": "<64 hex>",
  "expected_route_decision_id": "rdec-...",
  "expected_route_decision_sha256": "<64 hex>",
  "expected_recovery_control_count": 0,
  "expected_routing_delegation_event_count": 6,
  "expected_routing_delegation_event_tip_sha256": "<64 hex>",
  "created_by": "APTS-MO01",
  "reason": "optional explanation",
  "metadata": {}
}
```

Caller-supplied route candidates, authorization decisions, handoff envelopes, ownership state, recovery-control content, dispatch commands, or execution content are rejected.

## Read APIs

```text
GET /api/missions/{mission_id}/routing-delegation-lineage
GET /api/missions/{mission_id}/routing-delegation-replay
GET /api/missions/{mission_id}/routing-delegation-recovery
GET /api/missions/{mission_id}/routing-delegation-recovery-checkpoints
GET /api/missions/{mission_id}/routing-delegation-recovery-checkpoints/{checkpoint_id}
GET /api/missions/{mission_id}/routing-delegation-lineage-definition
```

## Persistence and integrity

Migration 026 adds:

```text
mission_routing_delegation_recovery_checkpoints
```

The store enforces immutable checkpoint identity, Mission/idempotency uniqueness, per-snapshot uniqueness, and monotonic checkpoint versioning. Repository manifest accounting and integrity checks include the Stage-3.4.9 store. The canonical checkpoint contract is domain-separated and SHA-256 verified, while checkpoint events remain protected by the existing Mission event hash chain.

## Authority boundary

Stage 3.4.9 does **not**:

- resolve or choose a new route;
- change Stage-3.4.4 route decision evidence;
- make a Governance authorization decision;
- refresh or reuse Stage-3.4.5 evidence as execution permission;
- create or mutate a Stage-3.4.6 delegation/handoff;
- redeliver the handoff;
- acknowledge or transfer Stage-3.4.7 ownership;
- create Stage-3.4.8 retry/fallback/reassignment controls;
- resolve runtime endpoints or probe runtime health;
- allocate execution resources;
- perform external network I/O;
- dispatch work or target actions;
- grant execution authorization;
- actuate a target.

`REPLAY != EXECUTION` and `RECOVERY != AUTHORIZATION / ROUTING / REDELIVERY / OWNERSHIP TRANSFER / DISPATCH` are explicit invariants.

## Acceptance evidence

The final package is gated by:

```text
Python compile                     PASS
Full Stage 3.1-3.4.9 regression    767 passed in 430.18s
Focused Stage 3.4.9                22 passed in 29.77s
```

Cumulative regression checkpoints:

```text
Stage 3.1 closure                 111
Stage 3.2 cumulative             267
Stage 3.3 cumulative             506
Stage 3.4.1 cumulative           525
Stage 3.4.2 cumulative           551
Stage 3.4.3 cumulative           586
Stage 3.4.4 cumulative           636
Stage 3.4.5 cumulative           666
Stage 3.4.6 cumulative           698
Stage 3.4.7 cumulative           717
Stage 3.4.8 cumulative           745
Stage 3.4.9 cumulative           767
```
