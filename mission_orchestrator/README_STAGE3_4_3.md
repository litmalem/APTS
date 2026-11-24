# Stage 3.4.3 — Routing Eligibility & Compatibility Gate

## Purpose

Stage 3.4.3 is the third control in **Stage 3.4 — Subsystem Routing & Task Delegation**. It consumes the immutable candidate set produced by Stage 3.4.2 and evaluates whether each candidate is statically eligible and contract-compatible with the canonical Mission, active Plan/readiness state, and Stage-3.4.1 subsystem registry.

Stage 3.4.3 answers only:

1. **Is each Stage-3.4.2 candidate eligible under immutable Mission scope and canonical registry contracts?**
2. **Is the candidate contract-compatible with the planned task schema and exact subsystem/capability requirement?**
3. **Does at least one eligible candidate remain after fail-closed evaluation?**

It does **not** select or rank a route, bind a runtime endpoint, probe subsystem health, allocate resources, query Governance, grant authorization, delegate work, dispatch a task, execute an action, or actuate a target.

## Architectural position

```text
Stage 3.3.8 READY task projection
        |
        v
Stage 3.4.1 Canonical Subsystem Registry & Capability Contract
        |
        v
Stage 3.4.2 Routing Intent & Candidate Resolution
        |
        v
Stage 3.4.3 Routing Eligibility & Compatibility Gate   <-- this stage
        |
        v
Stage 3.4.4 Route Ranking / Selection                  <-- NOT implemented here
        |
        v
Governance / Delegation / Dispatch                     <-- NOT implemented here
```

The decisive boundary is:

```text
CANDIDATE != ELIGIBLE
ELIGIBLE != SELECTED ROUTE
ELIGIBILITY != AUTHORIZATION
COMPATIBILITY != RUNTIME AVAILABILITY
ELIGIBILITY != DELEGATION
ELIGIBILITY != EXECUTION
```

## Canonical inputs

A materialized Stage-3.4.3 gate is bound to all of the following canonical artifacts:

- current Mission state in `PLANNING` or `REPLANNING`;
- current Mission version hash and state version;
- active Stage-3.3.7 Plan version record and canonical hash;
- active Stage-3.3.8 task-readiness projection and canonical hash;
- exactly one canonical `READY` planned task;
- one immutable Stage-3.4.2 routing intent and canonical hash;
- the current canonical Stage-3.4.1 subsystem registry snapshot;
- immutable Mission `required_subsystems`.

Caller-supplied eligibility decisions, candidate lists, ranking, route selection, endpoints, health, resource assignment, authorization, delegation, dispatch, execution, or target-action fields are rejected by request normalization.

## Eligibility and compatibility predicates

For each candidate inherited from Stage 3.4.2, the gate verifies static canonical predicates, including:

- exact required subsystem match;
- exact required capability match;
- subsystem membership in immutable Mission `required_subsystems`;
- subsystem/capability contract presence;
- subsystem/capability contract integrity;
- candidate-to-registry contract hash binding;
- subsystem and capability registration/enabled state;
- task-schema compatibility at subsystem and capability level;
- exact capability-match semantics;
- required-subsystem binding declared by the capability;
- `delegation_eligible` capability semantics;
- preservation of the Stage-3.4.2 invariant that runtime endpoint resolution and health probing have not occurred.

The evaluator never synthesizes, resurrects, or expands the Stage-3.4.2 candidate set.

## Gate result

The gate produces deterministic candidate evaluations with:

- `ELIGIBLE` or `INELIGIBLE` per candidate;
- explicit compatibility checks;
- explicit rejection reasons;
- `eligible_candidates` and `ineligible_candidates` projections;
- candidate counts;
- gate-level result and status.

Successful static eligibility:

```text
gate_result        = PASSED
eligibility_status = ELIGIBLE_CANDIDATES_AVAILABLE
```

No candidate or no surviving eligible candidate:

```text
gate_result        = FAILED_CLOSED
eligibility_status = NO_ELIGIBLE_CANDIDATE
```

A failed gate is still a valid durable evidence artifact; it does not grant any downstream authority.

## Durable contract

New immutable contract:

- schema: `apts-task-routing-eligibility-compatibility-gate-v1`;
- ID prefix: `relig-`;
- mode: `FAIL_CLOSED_CANONICAL_CANDIDATE_ELIGIBILITY_AND_COMPATIBILITY_GATE`;
- evaluation mode: `STATIC_CANONICAL_CONTRACT_COMPATIBILITY_ONLY`;
- integrity: canonical sorted JSON + SHA-256 domain separation.

One immutable eligibility gate is allowed per `(mission_id, routing_intent_id)` and per active plan/task binding. Exact request replay is idempotent; a reused idempotency key with a different canonical request fails closed.

## Persistence

Repository migration level is **20**.

New durable store:

```text
mission_task_routing_eligibility_gates
```

Migration:

```text
migrations/020_stage3_4_3_routing_eligibility_compatibility_gate.sql
```

The per-Mission persistence manifest and repository integrity verification now include the Stage-3.4.3 gate store. Persisted eligibility contracts are reconstructed and reverified after restart. Tampered canonical eligibility JSON causes repository integrity failure rather than silent acceptance.

Stage 3.4.3 deliberately does **not** extend the Mission version vector.

## Mission event lineage

A newly materialized gate emits exactly one canonical event:

```text
MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED
```

The event is causally bound to the `eligibility_gate_id` and records gate result, candidate counts, and explicit negative authority assertions. Idempotent replay does not append a duplicate event.

## API

Read history:

```text
GET /api/missions/{mission_id}/task-routing-eligibility-gates
```

Read one immutable gate:

```text
GET /api/missions/{mission_id}/task-routing-eligibility-gates/{eligibility_gate_id}
```

Read canonical definition:

```text
GET /api/missions/{mission_id}/task-routing-eligibility-definition
```

Materialize gate:

```text
POST /api/missions/{mission_id}/task-routing-eligibility-gates
```

HTTP conflict/not-found/guard failures are mapped to Stage-3.4.3-specific error codes.

## Active control and runtime metadata

```text
control_version                          = stage3.4.3-routing-eligibility-compatibility-gate
HTTP server identity                     = APTSMissionOrchestrator/3.4.3
mission_repository_migration_level       = 20
task_routing_intent_database_migration_level = 19
task_routing_eligibility_database_migration_level = 20
```

The health contract explicitly reports that eligibility is static-contract-only and that the following remain false:

- eligible candidate is selected route;
- eligibility is authorization;
- eligibility is runtime availability;
- route selection and ranking;
- runtime endpoint resolution and health probing;
- resource assignment;
- Governance query or authorization grant;
- delegation;
- dispatch;
- target-action dispatch;
- target actuation.

`EXTERNAL_APTS_GSS` remains the Governance authorization authority.

## Verification

Focused Stage-3.4.3 test module:

```text
35 passed
```

Complete repository collection:

```text
586 tests
```

The complete 586-test set was validated in partitioned Stage/module runs in the build environment because a single uninterrupted full-suite invocation exceeded the execution-session timeout. The user-side acceptance script still runs the normal complete `python -m pytest -q` command first.

## Next control

Stage 3.4.3 intentionally stops before route ranking and final route selection. The next architectural concern should consume only eligible candidates and must preserve the distinction between **selection** and **Governance authorization**.
