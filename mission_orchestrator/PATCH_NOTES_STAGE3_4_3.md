# Patch Notes — Stage 3.4.3 Routing Eligibility & Compatibility Gate

## Added

- `mission_orchestrator/task_routing_eligibility.py`
  - canonical Stage-3.4.3 request/contract schemas and SHA-256 domains;
  - fail-closed request normalization;
  - static candidate eligibility/compatibility evaluator;
  - immutable eligibility-gate builder/verifier;
  - canonical Stage-3.4.3 definition.
- durable store `mission_task_routing_eligibility_gates`.
- migration `020_stage3_4_3_routing_eligibility_compatibility_gate.sql`.
- GET/POST API routes for eligibility gate history, individual gate, creation, and definition.
- Stage-3.4.3-specific API error mapping.
- canonical Mission event `MISSION_TASK_ROUTING_ELIGIBILITY_EVALUATED`.
- repository reconstruction and integrity verification for persisted eligibility gates.
- `tests/test_stage3_4_3_routing_eligibility_compatibility_gate.py` with 35 focused tests.
- Stage-3.4.3 README, install guide, acceptance script, patch manifest, and SHA-256 inventory.

## Changed

- active control -> `stage3.4.3-routing-eligibility-compatibility-gate`;
- HTTP server identity -> `APTSMissionOrchestrator/3.4.3`;
- repository migration level -> `20`;
- per-Mission persistence manifest now includes `mission_task_routing_eligibility_gates`;
- package declaration -> through Stage 3.4.3;
- historical regression assertions that intentionally pin current runtime control/server/migration/repository metadata were rebased to Stage 3.4.3.

## Eligibility semantics

Stage 3.4.3 evaluates only candidates already frozen by Stage 3.4.2. Static checks cover Mission subsystem scope, exact subsystem/capability matching, registry contract presence/integrity/hash binding, registration/enabled state, task-schema compatibility, exact match semantics, capability subsystem binding, and `delegation_eligible` semantics.

Zero candidates or zero eligible candidates produce a durable fail-closed result:

```text
FAILED_CLOSED / NO_ELIGIBLE_CANDIDATE
```

One or more eligible candidates produce:

```text
PASSED / ELIGIBLE_CANDIDATES_AVAILABLE
```

## Preserved

- Stage-3.4.2 remains the sole source of the candidate set;
- no candidate synthesis or resurrection;
- no route ranking or final route selection;
- no runtime endpoint resolution or subsystem health probe;
- no resource assignment;
- no Governance query or authorization grant;
- no delegation;
- no dispatch;
- no target action or actuation;
- no Mission version-vector extension;
- `EXTERNAL_APTS_GSS` remains the Governance authorization authority.

## Boundary

```text
CANDIDATE != ELIGIBLE
ELIGIBLE != SELECTED ROUTE
ELIGIBILITY != AUTHORIZATION
COMPATIBILITY != RUNTIME AVAILABILITY
ELIGIBILITY != DELEGATION
ELIGIBILITY != EXECUTION
```

## Validation

Focused Stage-3.4.3 verification:

```text
35 passed
```

Complete collected regression set:

```text
586 tests
```

All 586 tests were validated through complete partitioned Stage/module runs in the build environment. A single all-at-once invocation was also started but exceeded the execution-session timeout; no failing test was observed in the partitioned complete run.
