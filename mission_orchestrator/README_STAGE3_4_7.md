# Stage 3.4.7 — Delegation Delivery, Acknowledgement & Ownership

## Purpose

Stage 3.4.7 is the seventh control in **Stage 3.4 — Subsystem Routing & Task Delegation**. It consumes one immutable Stage-3.4.6 delegation/handoff envelope and records the control-plane transition from a merely materialized handoff to an immutable **delivery + acknowledgement + ownership receipt** for the exact canonical recipient.

This stage answers only:

1. Is the exact Stage-3.4.6 delegation/handoff still current for the Mission state, active Plan, scope, Governance binding, and recipient?
2. Can the canonical handoff be marked delivered to the logical recipient without endpoint discovery or external network I/O?
3. Can the exact recipient acknowledge that handoff and accept delegated task ownership at the control-plane level?
4. Can these facts be persisted and linked into Mission event lineage without dispatching or executing the task?

Stage 3.4.7 **does not** resolve a runtime endpoint, probe subsystem health, allocate a worker/resource, perform external network I/O, dispatch work, authorize execution, issue a target command, actuate a target, or reuse the Stage-3.4.5 authorization as an execution grant.

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
        v
Stage 3.4.7 Delegation Delivery, Acknowledgement & Ownership  <-- this stage
        |
        v
Pre-dispatch Governance revalidation / dispatch / execution   <-- NOT implemented here
```

The authority boundary is explicit:

```text
HANDOFF_MATERIALIZED != HANDOFF_TRANSMITTED
HANDOFF_TRANSMITTED  != HANDOFF_ACKNOWLEDGED
HANDOFF_ACKNOWLEDGED != OWNERSHIP_ACCEPTED
OWNERSHIP_ACCEPTED   != DISPATCHED
OWNERSHIP_ACCEPTED   != EXECUTION_AUTHORIZED
```

A successful Stage-3.4.7 receipt means:

```text
handoff_transmitted   = true
handoff_acknowledged  = true
ownership_accepted    = true
dispatch_performed    = false
execution_authorized  = false
target_actuation      = false
```

## Canonical receipt

Schema:

```text
apts-canonical-delegation-delivery-acknowledgement-ownership-v1
```

Receipt ID prefix:

```text
drecv-
```

Mode:

```text
CONTROL_PLANE_HANDOFF_DELIVERY_WITH_RECIPIENT_ACK_AND_OWNERSHIP_ACCEPTANCE_NO_DISPATCH
```

Delivery channel:

```text
CANONICAL_RECIPIENT_CONTROL_PLANE_INBOX
```

Statuses:

```text
delivery_status        = DELIVERED
acknowledgement_status = ACKNOWLEDGED
ownership_status       = ACCEPTED
ownership_scope        = DELEGATED_TASK_CONTROL_PLANE_RESPONSIBILITY_ONLY
```

The receipt binds the exact Mission, active Plan, planned task, Stage-3.4.6 delegation ID/hash, handoff-envelope ID/hash, recipient subsystem/capability/version, source state/version, acknowledgement identity, ownership-acceptance identity, and provenance metadata.

## Required upstream evidence

Delivery fails closed unless all required evidence remains current and internally consistent:

- Mission exists and remains in `PLANNING` or `REPLANNING`;
- caller supplies the current Mission `state_version` and version-vector SHA-256;
- active Stage-3.3 Plan version ID/version/hash exactly matches;
- exact Stage-3.4.6 delegation ID/hash exists and verifies canonically;
- exact Stage-3.4.6 handoff-envelope ID/hash exists and verifies canonically;
- the Stage-3.4.6 delegation remains bound to the active Plan and current Mission version;
- current Mission scope still matches the Stage-3.4.6 source binding;
- current Governance binding still matches the Stage-3.4.6 source binding and current scope;
- requested recipient subsystem and capability exactly match the canonical Stage-3.4.6 handoff recipient;
- `acknowledged_by` equals the canonical recipient subsystem identity;
- `ownership_accepted_by` equals the canonical recipient subsystem identity;
- the delegation has not already produced another immutable Stage-3.4.7 receipt.

## Caller contract

The POST body accepts only exact provenance/concurrency references plus recipient acknowledgement identity:

```text
idempotency_key
expected_version_sha256
expected_state_version
expected_active_plan_version_record_id
expected_active_plan_version
expected_active_plan_sha256
expected_delegation_id
expected_delegation_sha256
expected_handoff_envelope_id
expected_handoff_envelope_sha256
recipient_subsystem_id
recipient_capability_id
acknowledged_by
ownership_accepted_by
reason              (optional)
metadata            (optional object)
```

The following classes of caller input are intentionally rejected: runtime endpoint, concrete worker/resource assignment, dispatch instructions, execution authorization, command payload, and target-action fields.

## Delivery semantics

Stage 3.4.7 models delivery as an auditable **control-plane delivery receipt**. It does not perform endpoint discovery or external network transport:

```text
logical_recipient_only                = true
runtime_endpoint                      = null
runtime_endpoint_resolution_performed = false
external_network_io_performed         = false
```

This preserves a deterministic and replayable boundary between orchestration-state ownership and later runtime dispatch.

## Acknowledgement and ownership

The acknowledgement records the exact Stage-3.4.6 handoff hash accepted by the canonical recipient. Ownership acceptance then transfers only delegated task **control-plane responsibility**:

```text
execution_authority_transferred   = false
target_action_authority_transferred = false
```

Ownership therefore means “the selected subsystem is now the canonical control-plane owner of this delegated task,” not “the subsystem may execute arbitrary target actions.”

## Governance boundary

Stage 3.4.7 performs **no new Governance query**. It validates that the Stage-3.4.6 source bindings remain current, but it does not reinterpret the Stage-3.4.5 authorization as execution authority.

The following invariant remains mandatory:

```text
pre_dispatch_governance_revalidation_required = true
```

Any later dispatch/execution stage must perform authoritative pre-dispatch Governance revalidation before runtime execution may begin.

## Idempotency and uniqueness

The request is canonicalized and domain-separated before hashing. Exact replay of the same idempotency key/request returns the same receipt and does not append a duplicate ownership event.

The repository enforces one immutable Stage-3.4.7 receipt per Stage-3.4.6 delegation:

```text
UNIQUE(mission_id, idempotency_key)
UNIQUE(mission_id, delegation_id)
```

Stage-3.4.6 records remain immutable; Stage 3.4.7 appends a new receipt rather than mutating the original delegation/handoff contract.

## Persistence

Repository migration level is **24**.

New durable store:

```text
mission_delegation_deliveries
```

Migration:

```text
migrations/024_stage3_4_7_delegation_delivery_acknowledgement_ownership.sql
```

Repository bootstrap supports SQLite and MySQL. Persistence manifest accounting, direct-record counts, restart reconstruction, and repository integrity verification include the new store.

Stage 3.4.7 does **not** extend the Mission version vector.

## Mission event lineage

A newly persisted Stage-3.4.7 receipt emits exactly one canonical event:

```text
MISSION_TASK_DELEGATION_OWNERSHIP_ACCEPTED
```

The event records the receipt, delegation, handoff envelope, planned task, recipient, and explicit boundary facts:

```text
handoff_transmitted            = true
handoff_acknowledged           = true
ownership_accepted             = true
dispatch_performed             = false
execution_authorized           = false
target_action_dispatch_enabled = false
target_actuation               = false
```

Exact idempotent replay does not create a duplicate event.

## API

Create the immutable delivery/ACK/ownership receipt:

```text
POST /api/missions/{mission_id}/delegation-deliveries
```

Read receipt history:

```text
GET /api/missions/{mission_id}/delegation-deliveries
```

Read one receipt:

```text
GET /api/missions/{mission_id}/delegation-deliveries/{delivery_receipt_id}
```

Read the canonical Stage-3.4.7 definition:

```text
GET /api/missions/{mission_id}/delegation-delivery-definition
```

## Runtime identity

```text
control_version = stage3.4.7-delegation-delivery-acknowledgement-ownership
server_version  = APTSMissionOrchestrator/3.4.7
repository_migration_level = 24
```

## Validation

Build-environment verification:

```text
Python compile                         PASS
Stage 3.1 partition                    111 passed
Stage 3.2 partition                    156 passed
Stage 3.3 exhaustive partition         239 passed
Stage 3.4.1-3.4.3 partition             80 passed
Stage 3.4.4                              50 passed
Stage 3.4.5                              30 passed
Stage 3.4.6                              32 passed
Stage 3.4.7 focused                      19 passed
--------------------------------------------------
Exhaustive total                         717 passed
```

Cumulative checkpoints:

```text
Stage 3.1 closure       = 111
Stage 3.2 cumulative   = 267
Stage 3.3 cumulative   = 506
Stage 3.4.1 cumulative = 525
Stage 3.4.2 cumulative = 551
Stage 3.4.3 cumulative = 586
Stage 3.4.4 cumulative = 636
Stage 3.4.5 cumulative = 666
Stage 3.4.6 cumulative = 698
Stage 3.4.7 cumulative = 717
```
