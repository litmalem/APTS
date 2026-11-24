# Stage 3.4.4 — Deterministic Route Selection & Decision Record

## Purpose

Stage 3.4.4 is the fourth control in **Stage 3.4 — Subsystem Routing & Task Delegation**. It consumes the immutable Stage-3.4.3 eligibility gate, ranks **only** the candidates already marked `ELIGIBLE`, deterministically selects rank 1 when an eligible route exists, and persists an immutable route-decision record.

Stage 3.4.4 answers only:

1. **Which Stage-3.4.3 eligible candidate is deterministically rank 1?**
2. **What immutable logical route decision was produced from the exact canonical source artifacts?**
3. **Can that decision be replayed, reconstructed, and integrity-verified without consulting runtime availability or Governance?**

It does **not** resolve endpoints, probe subsystem health, allocate resources, query Governance, grant authorization, delegate work, dispatch a task, execute an action, or actuate a target.

## Architectural position

```text
Stage 3.4.1 Canonical Subsystem Registry & Capability Contract
        |
        v
Stage 3.4.2 Routing Intent & Candidate Resolution
        |
        v
Stage 3.4.3 Routing Eligibility & Compatibility Gate
        |
        v
Stage 3.4.4 Deterministic Route Selection & Decision Record   <-- this stage
        |
        v
Stage 3.4.5 Governance-Bound Delegation Authorization         <-- next control
        |
        v
Delegation / Dispatch / Execution                             <-- NOT implemented here
```

The decisive boundary is:

```text
ELIGIBLE != SELECTED ROUTE
SELECTED ROUTE = LOGICAL SUBSYSTEM/CAPABILITY IDENTITY ONLY
SELECTED ROUTE != RUNTIME AVAILABILITY
SELECTED ROUTE != AUTHORIZATION
ROUTE SELECTION != DELEGATION
ROUTE SELECTION != DISPATCH
ROUTE SELECTION != EXECUTION
```

## Canonical inputs

A materialized Stage-3.4.4 decision is bound to all of the following immutable/canonical artifacts:

- current Mission state in `PLANNING` or `REPLANNING`;
- current Mission version hash and state version;
- active Stage-3.3.7 Plan version record and canonical hash;
- active Stage-3.3.8 task-readiness projection and canonical hash;
- exactly one canonical `READY` planned task;
- one immutable Stage-3.4.2 routing intent and canonical hash;
- one immutable Stage-3.4.3 eligibility gate and canonical hash;
- the Stage-3.4.1 registry snapshot/hash bound by the upstream artifacts.

Caller-supplied candidate lists, ranking, score, priority, selected subsystem/capability, endpoint, health, resource assignment, authorization, delegation, dispatch, execution, or target-action fields are rejected by request normalization.

## Deterministic selection policy

Canonical policy:

```text
STAGE343_ELIGIBLE_CANONICAL_TUPLE_ASC_V1
```

Only `Stage-3.4.3 eligibility_gate.eligible_candidates` participate. No rejected candidate is resurrected and no new candidate is synthesized.

Candidates are sorted ascending by the canonical tuple:

```text
(candidate_index, subsystem_id, capability_id, capability_version)
```

The ordered candidates receive contiguous ranks `1..N`. Rank 1 is selected as the logical route.

For every ranked candidate and the selected route, runtime state remains explicitly unknown/unprobed:

```text
endpoint_resolved = false
health_probed     = false
availability      = UNKNOWN_NOT_PROBED
```

## Decision outcomes

When one or more Stage-3.4.3 eligible candidates exist:

```text
decision_status = ROUTE_SELECTED
route_selected  = true
```

When no Stage-3.4.3 eligible candidate exists:

```text
decision_status = NO_ELIGIBLE_ROUTE
route_selected  = false
selected_route  = null
```

`NO_ELIGIBLE_ROUTE` is a valid durable evidence record; it does not fall back to an ineligible candidate.

## Durable contract

New immutable contract:

- schema: `apts-task-deterministic-route-selection-decision-v1`;
- ID prefix: `rdec-`;
- mode: `DETERMINISTIC_ELIGIBLE_CANDIDATE_ROUTE_SELECTION_WITH_IMMUTABLE_DECISION_RECORD`;
- policy: `STAGE343_ELIGIBLE_CANONICAL_TUPLE_ASC_V1`;
- integrity: canonical sorted JSON + domain-separated SHA-256.

The contract binds Mission state/version, Plan version, readiness projection, routing intent, eligibility gate, registry snapshot/hash, deterministic ranked candidates, selected logical route, provenance, and explicit negative authority/runtime assertions.

One immutable decision is allowed per Stage-3.4.3 eligibility gate and per active plan/task binding. Exact request replay is idempotent; reuse of an idempotency key with a different canonical request fails closed.

## Persistence

Repository migration level is **21**.

New durable store:

```text
mission_task_route_decisions
```

Migration:

```text
migrations/021_stage3_4_4_deterministic_route_selection_decision_record.sql
```

The per-Mission persistence manifest and repository integrity verification include the new store. Persisted contracts are reconstructed and reverified after restart. Tampering with canonical route-decision JSON or ranking/selection semantics causes integrity verification failure.

Stage 3.4.4 deliberately does **not** extend the Mission version vector.

## Mission event lineage

A newly materialized decision emits exactly one canonical event:

```text
MISSION_TASK_ROUTE_DECISION_RECORDED
```

The event is causally bound to `route_decision_id` and records the eligibility-gate binding, decision status, whether a route was selected, selected subsystem/capability when present, and explicit negative authority/delegation/dispatch assertions. Idempotent replay does not append a duplicate event.

## API

Read history:

```text
GET /api/missions/{mission_id}/task-route-decisions
```

Read one immutable decision:

```text
GET /api/missions/{mission_id}/task-route-decisions/{route_decision_id}
```

Read canonical definition:

```text
GET /api/missions/{mission_id}/task-route-selection-definition
```

Materialize decision:

```text
POST /api/missions/{mission_id}/task-route-decisions
```

## Authority boundary

Stage 3.4.4 performs **local deterministic route ranking and logical selection only**.

It does not perform:

- runtime endpoint resolution;
- runtime health probing;
- resource assignment;
- Governance query;
- authorization grant;
- delegation or handoff;
- dispatch;
- target-action dispatch;
- target actuation/execution.

`aptsGSS / GOV-PLANE` remains the sole Governance/authorization authority:

```text
governance_authorization_authority = EXTERNAL_APTS_GSS
```

## Validation

Focused Stage-3.4.4 test module:

```text
50 passed
```

Cumulative Stage-3.4 modules:

```text
Stage 3.4.1 = 19 passed
Stage 3.4.2 = 26 passed
Stage 3.4.3 = 35 passed
Stage 3.4.4 = 50 passed
Total       = 130 passed
```

Complete collected regression set:

```text
636 tests
```

All 636 tests were validated in partitioned Stage/module runs in the build environment. A single uninterrupted combined invocation exceeded the execution-session timeout; no partition failed.

## Next control

The next control is **Stage 3.4.5 — Governance-Bound Delegation Authorization**. It must consume the immutable Stage-3.4.4 logical route decision and obtain authoritative Governance approval without allowing route selection itself to become authorization.
