# Stage 3.4.6 — Canonical Delegation Contract & Handoff Envelope

## Purpose

Stage 3.4.6 is the sixth control in **Stage 3.4 — Subsystem Routing & Task Delegation**. It consumes an immutable Stage-3.4.5 `AUTHORIZED` delegation authorization and materializes the first canonical **logical delegation** plus an immutable **handoff envelope** for the selected subsystem/capability.

This stage answers only:

1. Is the exact Stage-3.4.5 authorization still current for the Mission state, active Plan, planned task, route decision, Mission scope, and Governance binding?
2. Can the orchestrator create one immutable delegation contract that transfers logical control-plane responsibility to the selected subsystem/capability?
3. Can the complete handoff context be materialized as a canonical envelope without transmitting, acknowledging, dispatching, or executing it?

Stage 3.4.6 **does not** resolve a runtime endpoint, probe target health, allocate a concrete worker/resource, transmit the handoff envelope, accept ownership on behalf of the target subsystem, dispatch work, reuse the Stage-3.4.5 authorization as an execution grant, or actuate the target environment.

## Architectural position

```text
Stage 3.4.1 Canonical Subsystem Registry & Capability Contract
        |
        v
Stage 3.4.2 Task Routing Intent & Candidate Resolution
        |
        v
Stage 3.4.3 Routing Eligibility & Compatibility Gate
        |
        v
Stage 3.4.4 Deterministic Route Selection & Decision Record
        |
        v
Stage 3.4.5 Governance-Bound Delegation Authorization
        |
        v
Stage 3.4.6 Canonical Delegation Contract & Handoff Envelope  <-- this stage
        |
        v
Handoff transmission / ACK / runtime dispatch / execution   <-- NOT implemented here
```

The authority boundary is explicit:

```text
ROUTE_SELECTED       != AUTHORIZED
AUTHORIZED           != DELEGATED
DELEGATED            != HANDOFF_TRANSMITTED
HANDOFF_MATERIALIZED != OWNERSHIP_ACCEPTED
DELEGATED            != DISPATCHED
DELEGATED            != EXECUTION_AUTHORIZED
```

A successful Stage-3.4.6 run therefore means:

```text
delegation_performed        = true
handoff_envelope_materialized = true
handoff_transmitted         = false
handoff_acknowledged        = false
ownership_accepted          = false
dispatch_performed          = false
execution_authorized        = false
target_actuation            = false
```

## Required upstream evidence

A delegation is accepted only when all of the following remain current and internally consistent:

- Mission exists and is in `PLANNING` or `REPLANNING`;
- caller supplies the current Mission `state_version` and Mission version-vector SHA-256;
- active Stage-3.3.7 Plan version ID/version/hash matches the request;
- exact Stage-3.4.5 delegation authorization ID/hash exists and verifies canonically;
- authorization status is `AUTHORIZED` and `authorization_granted=true`;
- authorization is still bound to the current Mission state/version vector;
- authorization is still bound to the active Plan version;
- exact Stage-3.4.4 route-decision hash remains valid;
- canonical planned task still matches the selected subsystem/capability;
- current Mission scope contract is valid;
- current Governance binding exists, verifies, matches the authorization binding, and remains current for the Mission scope;
- the Stage-3.4.5 authorization has not already produced another immutable Stage-3.4.6 delegation.

All checks fail closed.

## Caller contract

The Stage-3.4.6 POST body accepts only concurrency/provenance identifiers:

```text
idempotency_key
expected_version_sha256
expected_state_version
expected_active_plan_version_record_id
expected_active_plan_version
expected_active_plan_sha256
expected_delegation_authorization_id
expected_delegation_authorization_sha256
planned_task_id
delegated_by
reason              (optional)
metadata            (optional object)
```

The caller **cannot** supply the recipient, capability, endpoint, objective, scope, RoE, constraints, expected outputs, completion criteria, evidence requirements, authorization verdict, ownership state, dispatch instruction, execution authorization, or target-action fields. Those are derived from canonical upstream artifacts.

## Canonical handoff envelope

Schema:

```text
apts-canonical-delegation-handoff-envelope-v1
```

Identity prefix:

```text
handoff-
```

Mode:

```text
IMMUTABLE_CONTEXT_HANDOFF_MATERIALIZED_NOT_TRANSMITTED
```

The envelope contains five major contexts:

### 1. Identity

- handoff envelope ID;
- delegation ID;
- Mission ID;
- active Plan version record/version;
- planned task ID and task key.

### 2. Sender and logical recipient

Sender is the Mission Orchestrator control plane. Recipient is derived from the Stage-3.4.4 route carried through Stage-3.4.5 authorization:

```text
subsystem_id
capability_id
capability_version
logical_recipient_only = true
runtime_endpoint = null
```

No endpoint discovery occurs here.

### 3. Work context

The envelope derives executable context from canonical sources rather than caller input:

- task type;
- objective;
- preconditions;
- Mission scope;
- rules of engagement;
- constraints;
- expected outputs;
- completion criteria;
- evidence requirements;
- priority.

Planned-task fields come from the canonical Stage-3.3 decomposition contract. Scope/RoE/constraints come from the current Mission scope contract.

### 4. Authority context

The envelope carries the exact Stage-3.4.5 authorization and authoritative Governance decision references, while preserving the critical distinction:

```text
authorization_purpose = PRE_DELEGATION_ONLY
authorization_granted = true
execution_authorized = false
target_action_authorized = false
pre_dispatch_governance_revalidation_required = true
```

Stage-3.4.6 performs **no new Governance query**. The Stage-3.4.5 decision authorizes logical delegation only. A later dispatch control must perform authoritative pre-dispatch Governance revalidation.

### 5. Source artifacts and provenance

The envelope records references to the exact planned task, active Plan, Mission scope, Stage-3.4.4 route decision, Stage-3.4.5 authorization, and Governance binding. It also records `delegated_by`, reason, metadata, and creation time.

The envelope is canonicalized with sorted UTF-8 JSON and domain-separated SHA-256.

## Canonical delegation contract

Schema:

```text
apts-canonical-delegation-contract-v1
```

Identity prefix:

```text
deleg-
```

Mode:

```text
AUTHORIZED_LOGICAL_DELEGATION_WITH_IMMUTABLE_HANDOFF_ENVELOPE_NO_DISPATCH
```

The delegation contract binds:

- Mission/source-state identity and version hash;
- active Plan ID/version/hash;
- planned task ID/hash;
- current scope snapshot/version/hash;
- current Governance binding version/hash;
- Stage-3.4.4 route-decision ID/hash;
- Stage-3.4.5 authorization ID/hash;
- authoritative PolicyDecision ID/hash/version;
- selected subsystem/capability/version;
- nested handoff envelope and its canonical SHA-256;
- explicit negative dispatch/execution semantics.

`responsibility_transfer_mode` is:

```text
LOGICAL_CONTROL_PLANE_DELEGATION
```

This is a durable control-plane delegation record, not proof that a remote subsystem has received or accepted the task.

## Idempotency and uniqueness

The request fingerprint is canonical and domain-separated. Exact replay of the same idempotency key/request returns the existing delegation and does not append a duplicate delegation event.

The repository also enforces:

```text
UNIQUE(mission_id, idempotency_key)
UNIQUE(mission_id, delegation_authorization_id)
UNIQUE(mission_id, plan_version, planned_task_id)
```

This ensures one immutable delegation for one Stage-3.4.5 authorization and one delegation per planned task within a Plan version.

## Persistence

Repository migration level is **23**.

New durable store:

```text
mission_task_delegations
```

Migration:

```text
migrations/023_stage3_4_6_canonical_delegation_contract_handoff_envelope.sql
```

Repository bootstrap supports both SQLite and MySQL paths. Restart reconstruction, persistence manifest accounting, direct-record counts, and repository integrity verification include the new store.

Stage 3.4.6 deliberately does **not** extend the Mission version vector.

## Mission event lineage

A newly persisted delegation emits exactly one canonical event:

```text
MISSION_TASK_DELEGATION_HANDOFF_MATERIALIZED
```

The event records the delegation, handoff envelope, authorization, route decision, planned task, selected subsystem/capability, and explicit boundary facts:

```text
delegation_performed = true
handoff_envelope_materialized = true
handoff_transmitted = false
handoff_acknowledged = false
ownership_accepted = false
dispatch_performed = false
execution_authorized = false
target_action_dispatch_enabled = false
```

Exact idempotent replay does not create a duplicate event.

## API

Materialize a logical delegation and immutable handoff envelope:

```text
POST /api/missions/{mission_id}/task-delegations
```

Read delegation history:

```text
GET /api/missions/{mission_id}/task-delegations
```

Read one immutable delegation:

```text
GET /api/missions/{mission_id}/task-delegations/{delegation_id}
```

Read the canonical Stage-3.4.6 definition:

```text
GET /api/missions/{mission_id}/task-delegation-definition
```

## Runtime identity

```text
control_version = stage3.4.6-canonical-delegation-contract-handoff-envelope
server_version  = APTSMissionOrchestrator/3.4.6
repository_migration_level = 23
```

## Regression rebase semantics

Historical Stage-3.4.2 through Stage-3.4.5 health tests previously asserted the aggregate current-runtime field:

```text
task_routing_delegation_performed = false
```

That assertion is no longer valid once Stage-3.4.6 is active, because the current runtime now intentionally implements logical delegation. Those historical health assertions are rebased to `true` while their **stage-local contracts remain unchanged**. In particular:

```text
delegation_authorization_is_delegation = false
```

still holds for Stage 3.4.5, and all current-runtime dispatch/execution flags remain false.

## Validation completed in the build environment

Python compilation completed successfully.

Complete suite collection:

```text
698 tests collected
```

Every collected test was executed successfully across exhaustive partitions:

```text
Stage 3.1                     111 passed
Stage 3.2                     156 passed
Stage 3.3.1–3.3.5             114 passed
Stage 3.3.6–3.3.7              47 passed
Stage 3.3.8–3.3.10             78 passed
Stage 3.4.1                     19 passed
Stage 3.4.2                     26 passed
Stage 3.4.3                     35 passed
Stage 3.4.4                     50 passed
Stage 3.4.5                     30 passed
Stage 3.4.6                     32 passed
------------------------------------------
TOTAL                          698 passed
```

The partitioning is only a build-environment execution-time constraint; the partitions cover the full 698-test collection with no omissions.

## Closure invariant

Stage 3.4.6 closes only when all of the following are simultaneously true:

```text
AUTHORIZED Stage-3.4.5 decision exists and is current
canonical logical delegation is persisted
a complete immutable handoff envelope is persisted
handoff has NOT been transmitted
recipient has NOT acknowledged or accepted ownership
no runtime endpoint has been resolved
no runtime health probe has been performed
no resource has been assigned
no dispatch has occurred
no execution authority has been granted
no target actuation has occurred
pre-dispatch Governance revalidation remains mandatory
```

The subsequent routing/delegation control should consume this immutable handoff envelope and explicitly own the next authority boundary rather than silently treating materialization as delivery or execution.
