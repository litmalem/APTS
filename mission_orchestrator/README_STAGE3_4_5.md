# Stage 3.4.5 — Governance-Bound Delegation Authorization

## Purpose

Stage 3.4.5 is the fifth control in **Stage 3.4 — Subsystem Routing & Task Delegation**. It consumes an immutable Stage-3.4.4 `ROUTE_SELECTED` decision and asks the external **aptsGSS / GOV-PLANE** for an authoritative PolicyDecision that determines whether the selected logical route may proceed toward delegation.

This stage answers only:

1. Is the exact Stage-3.4.4 logical route still bound to the current Mission, active Plan, task, and Governance scope?
2. Does the authoritative Governance service return `ALLOW`, `DENY`, or `REVIEW` for the delegation request?
3. Can that authorization decision be persisted, replayed, correlated, reconstructed, and integrity-verified without performing delegation or execution?

It does **not** delegate a task, dispatch work, resolve a runtime endpoint, probe subsystem health, allocate resources, authorize the target action itself, or actuate a target.

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
Stage 3.4.5 Governance-Bound Delegation Authorization   <-- this stage
        |
        v
Delegation / Dispatch / Execution                      <-- NOT implemented here
```

The decisive authority boundary is:

```text
ROUTE_SELECTED != AUTHORIZED
AUTHORIZED      != DELEGATED
AUTHORIZED      != DISPATCHED
AUTHORIZED      != EXECUTION_AUTHORIZED

Mission Orchestrator = requester + durable evidence holder
aptsGSS / GOV-PLANE  = authoritative authorization authority
```

## Canonical source bindings

A materialized Stage-3.4.5 authorization is bound to:

- current Mission state (`PLANNING` or `REPLANNING`);
- current Mission version hash/state version;
- active Stage-3.3.7 Plan version and canonical hash;
- exact Stage-3.4.4 route-decision ID/hash;
- route status `ROUTE_SELECTED`;
- exact planned task ID;
- selected logical subsystem ID and capability ID;
- current Mission Governance binding;
- current canonical Governance scope;
- authoritative external PolicyDecision and its decision identity/hash.

Caller-supplied route selection, authorization result, target endpoint, delegation, dispatch, execution, or target-action fields are rejected. The caller cannot manufacture either the selected route or the Governance verdict.

## Governance request semantics

Canonical mode:

```text
AUTHORITATIVE_GOVERNANCE_PRE_DELEGATION_FAIL_CLOSED
```

The external authorization request uses:

```text
action_class = TASK_DELEGATION
action_name  = delegate_planned_task
resource_type = SUBSYSTEM_CAPABILITY
resource_value = <selected_subsystem_id>:<selected_capability_id>
```

Its context carries Mission/Plan/task identity, the immutable Stage-3.4.4 route-decision hash, the selected logical route, and an explicit `PRE_DELEGATION_ONLY` purpose. It explicitly states that target-action authority is **not** being requested.

## Authorization outcomes

An authoritative Governance `ALLOW` becomes:

```text
authorization_status = AUTHORIZED
authorized           = true
```

A Governance `DENY` becomes a durable fail-closed record:

```text
authorization_status = DENIED
authorized           = false
```

A non-ALLOW/non-DENY policy outcome is represented as:

```text
authorization_status = REVIEW_REQUIRED
authorized           = false
```

All three outcomes are evidence. A negative result is not discarded and does not fall through into delegation.

## Lost-response correlation and idempotency

Stage 3.4.5 derives a deterministic external operation ID from the canonical authorization request. Before issuing a new Governance evaluation, the Mission Orchestrator checks the Governance correlation snapshot for an already committed PolicyDecision with that operation ID.

This supports the failure mode:

```text
Governance committed decision
        |
network response lost
        |
Mission Orchestrator retries
        |
correlation snapshot recovers existing decision
        |
NO duplicate external authorization decision
```

Exact request replay is locally idempotent. Reusing an idempotency key with different canonical content fails closed. One immutable Stage-3.4.5 authorization record is allowed per Stage-3.4.4 route decision.

## Durable contract

New immutable contract:

```text
schema = apts-governance-bound-delegation-authorization-v1
ID prefix = dauth-
operation ID prefix = dauthop-
mode = AUTHORITATIVE_GOVERNANCE_PRE_DELEGATION_FAIL_CLOSED
```

Integrity uses canonical sorted JSON and domain-separated SHA-256. The contract binds the source Mission/Plan/route/Governance artifacts and the authoritative PolicyDecision.

The contract also persists explicit negative boundary assertions:

```text
authorization_is_delegation = false
delegation_performed        = false
dispatch_performed          = false
execution_authorized        = false
target_action_authorized    = false
runtime_endpoint_resolved   = false
runtime_health_probed       = false
version_vector_extended     = false
```

## Persistence

Repository migration level is **22**.

New durable store:

```text
mission_delegation_authorizations
```

Migration:

```text
migrations/022_stage3_4_5_governance_bound_delegation_authorization.sql
```

The Mission persistence manifest, direct-record counts, restart reconstruction, and integrity verification include the new store. Stage 3.4.5 deliberately does **not** extend the Mission version vector.

## Mission event lineage

A newly persisted authorization emits exactly one canonical event:

```text
MISSION_TASK_DELEGATION_AUTHORIZATION_RECORDED
```

The event is causally bound to the authorization ID and records route-decision identity, selected subsystem/capability, Governance result, grant state, and explicit non-delegation/non-dispatch semantics. Idempotent replay does not append a duplicate event.

## API

Materialize authoritative pre-delegation authorization:

```text
POST /api/missions/{mission_id}/task-delegation-authorizations
```

Read history:

```text
GET /api/missions/{mission_id}/task-delegation-authorizations
```

Read one immutable authorization:

```text
GET /api/missions/{mission_id}/task-delegation-authorizations/{authorization_id}
```

Read the canonical Stage-3.4.5 definition:

```text
GET /api/missions/{mission_id}/task-delegation-authorization-definition
```

## Pre-delegation invariant

An `AUTHORIZED` record is a prerequisite/evidence for a later delegation control; it is not a reusable blanket execution grant. The next delegation control must revalidate the authoritative Governance state before dispatch, consistent with the existing fail-closed pre-dispatch governance architecture.

## Validation

Focused Stage-3.4.5 module:

```text
30 passed
```

Historical Stage-3.4 focused modules retained:

```text
Stage 3.4.1 = 19 tests
Stage 3.4.2 = 26 tests
Stage 3.4.3 = 35 tests
Stage 3.4.4 = 50 tests
Stage 3.4.5 = 30 tests
Stage 3.4 total = 160 tests
```

Complete suite collection after Stage 3.4.5:

```text
666 tests collected
```

Stage-3.1 and Stage-3.2 regression partitions passed (`111` and `156` tests respectively). Earlier Stage-3.3/Stage-3.4 aggregate invocations in this build environment exceeded the execution-session timeout rather than returning a test failure; focused Stage-3.4.5 is green.

## Next control

The next control should perform the actual **authorized delegation handoff**, while preserving a strict boundary between authorization, delegation, dispatch, subsystem runtime availability, and target execution.
