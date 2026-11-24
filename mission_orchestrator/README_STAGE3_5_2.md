# Stage 3.5.2 — Dispatch Eligibility & Execution Preconditions

## Purpose

Stage 3.5.2 introduces a fail-closed, durable **dispatch-eligibility and execution-precondition gate** between the immutable Stage-3.5.1 `xdispatch-*` identity and the later authoritative pre-dispatch Governance authorization/dispatch stages.

A positive Stage-3.5.2 result means only:

```text
ELIGIBLE_FOR_PRE_DISPATCH_GOVERNANCE_REVALIDATION
```

It does **not** mean `EXECUTION_AUTHORIZED`, and it does not perform a runtime dispatch.

## Architectural position

```text
Stage 3.5.1  Canonical Execution Dispatch Contract & Identity
      |
      v
Stage 3.5.2  Dispatch Eligibility & Execution Preconditions
      |
      +--> validate exact RUNNING Mission state/version vector
      +--> validate active Plan + readiness projection
      +--> validate immutable Stage-3.5.1 xdispatch provenance
      +--> validate Stage-3.4.4 route provenance
      +--> validate Stage-3.4.5 delegation authorization boundary
      +--> validate Stage-3.4.6 delegation/handoff integrity
      +--> validate Stage-3.4.7 delivery/ACK/ownership acceptance
      +--> validate Stage-3.4.8 recovery-control set has not drifted
      +--> validate current Scope + Governance binding
      +--> validate registered/enabled target capability
      +--> persist immutable xelig-* gate + lineage event
      |
      +--> NO Governance authorization query
           NO execution grant
           NO runtime endpoint resolution
           NO health probe
           NO resource assignment
           NO dispatch attempt
           NO external network I/O
           NO target actuation
      |
      v
Later Stage 3.5.x: authoritative pre-dispatch Governance revalidation
and runtime dispatch controls
```

## Runtime identity

```text
control_version = stage3.5.2-dispatch-eligibility-execution-preconditions
server_version  = APTSMissionOrchestrator/3.5.2
repository_migration_level = 28
```

Stage 3.5.2 adds:

```text
migration 028
mission_execution_dispatch_eligibility_gates
MISSION_DISPATCH_ELIGIBILITY_PRECONDITIONS_SATISFIED
```

## Canonical contract

Implementation:

```text
mission_orchestrator/dispatch_eligibility.py
```

Key constants:

```text
schema_version = apts-dispatch-eligibility-execution-preconditions-v1
identity_prefix = xelig-
mode = FAIL_CLOSED_CANONICAL_DISPATCH_ELIGIBILITY_AND_EXECUTION_PRECONDITIONS
gate_result = PASSED
eligibility_status = ELIGIBLE_FOR_PRE_DISPATCH_GOVERNANCE_REVALIDATION
execution_precondition_status = SATISFIED_PENDING_PRE_DISPATCH_AUTHORIZATION
allowed_source_states = RUNNING
```

The gate is immutable and domain-separated with a canonical SHA-256 digest.

## Preconditions

The canonical evaluator checks 25 independent preconditions, including:

1. Mission is `RUNNING`.
2. Mission version vector is complete and current.
3. Stage-3.5.1 `xdispatch-*` remains bound to the active Plan.
4. Stage-3.5.1 dispatch contract passes integrity verification.
5. Dispatch status is still materialized/pending authorization.
6. Execution authorization remains `NOT_EVALUATED`.
7. No dispatch attempt or target actuation has occurred.
8. Active readiness projection passes integrity verification.
9. Planned task is structurally `READY` with no unmet dependencies.
10. Stage-3.4.7 delivery receipt passes integrity verification.
11. Delivery, acknowledgement, and ownership are accepted.
12. Delivery receipt matches the exact Stage-3.5.1 provenance.
13. Stage-3.4.6 delegation and handoff pass integrity verification.
14. Delegation/handoff match Stage-3.5.1 provenance.
15. Stage-3.4.4 route decision is valid and selected.
16. Selected logical target matches Stage-3.5.1.
17. Stage-3.4.5 delegation authorization passes integrity verification.
18. Delegation authorization remains delegation-only, not execution authority.
19. Mission Scope binding remains current.
20. Governance binding remains current.
21. Stage-3.4.8 recovery-control set has not changed since Stage-3.5.1.
22. Canonical subsystem registry passes integrity verification.
23. Target subsystem is registered and enabled.
24. Target capability is registered, enabled, delegation-eligible, and version-matched.
25. Runtime endpoint resolution remains deferred.

Any failed precondition produces an in-memory `FAILED_CLOSED` evaluation and the service rejects materialization. Only a `PASSED` gate is persisted.

## Authority boundary

Stage 3.5.2 makes these invariants explicit:

```text
DISPATCH ELIGIBILITY != EXECUTION AUTHORIZATION
EXECUTION PRECONDITIONS != EXECUTION AUTHORIZATION
PASSED != ELIGIBLE_FOR_EXECUTION
OWNERSHIP != EXECUTION AUTHORITY
DELEGATION AUTHORIZATION != EXECUTION AUTHORIZATION
LOGICAL TARGET != RUNTIME ENDPOINT
```

A persisted Stage-3.5.2 gate always declares:

```text
eligible_for_pre_dispatch_governance_revalidation = true
eligible_for_execution = false
pre_dispatch_governance_revalidation_required = true
governance_query_performed = false
runtime_endpoint_resolution_performed = false
runtime_health_probe_performed = false
resource_assignment_performed = false
execution_authorization_performed = false
dispatch_attempt_started = false
dispatch_performed = false
external_network_io_performed = false
target_action_dispatch_enabled = false
target_actuation = false
version_vector_extension_performed = false
```

## Persistence and lineage

Migration:

```text
migrations/028_stage3_5_2_dispatch_eligibility_execution_preconditions.sql
```

Durable store:

```text
mission_execution_dispatch_eligibility_gates
```

Immutability rules:

```text
unique dispatch_eligibility_id
unique (mission_id, idempotency_key)
unique (mission_id, execution_dispatch_id)
```

Event:

```text
MISSION_DISPATCH_ELIGIBILITY_PRECONDITIONS_SATISFIED
```

The repository persistence manifest includes `dispatch_eligibility_execution_preconditions_store`; repository reconstruction verifies canonical hashes, Stage-3.5.1 dispatch references, readiness references, gate status, no-execution semantics, and event cardinality.

## HTTP API

```text
POST /api/missions/{mission_id}/dispatch-eligibility-gates
GET  /api/missions/{mission_id}/dispatch-eligibility-gates
GET  /api/missions/{mission_id}/dispatch-eligibility-gates/{dispatch_eligibility_id}
GET  /api/missions/{mission_id}/dispatch-eligibility-definition
```

Caller-supplied eligibility outcomes, precondition outcomes, Governance decisions, execution grants, runtime endpoints, health results, resource assignments, execution payloads, dispatch attempts, target actions, or actuation fields are rejected.

## Acceptance coverage

Focused proof:

```text
tests/test_stage3_5_2_dispatch_eligibility_execution_preconditions.py
```

The suite contains 19 tests covering runtime activation, canonical definition, happy path, state/version/Plan/dispatch/readiness concurrency guards, forbidden authority/runtime inputs, idempotency, single-gate immutability, no-Governance/no-network/no-actuation boundary, fail-closed capability evaluation, repository projection/event lineage, tamper detection, API/migration registration, and version-vector non-extension.
