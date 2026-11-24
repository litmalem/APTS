# Patch Notes — Stage 3.4.4 Deterministic Route Selection & Decision Record

## Added

- `mission_orchestrator/task_route_selection.py`
  - Stage-3.4.4 request normalization;
  - deterministic eligible-candidate ranking;
  - immutable route-decision contract builder/verifier;
  - canonical definition and SHA-256 domains.
- durable store `mission_task_route_decisions`.
- migration `021_stage3_4_4_deterministic_route_selection_decision_record.sql`.
- GET/POST API routes for route-decision history, individual decision, creation, and definition.
- Stage-3.4.4-specific conflict/not-found/guard error mapping.
- canonical Mission event `MISSION_TASK_ROUTE_DECISION_RECORDED`.
- repository reconstruction and integrity verification for persisted route decisions.
- `tests/test_stage3_4_4_deterministic_route_selection_decision_record.py` with 50 focused tests.
- Stage-3.4.4 README, install guide, acceptance script, patch manifest, and SHA-256 inventory.

## Changed

- active control -> `stage3.4.4-deterministic-route-selection-decision-record`;
- HTTP server identity -> `APTSMissionOrchestrator/3.4.4`;
- repository migration level -> `21`;
- per-Mission persistence manifest now includes `mission_task_route_decisions`;
- package declaration -> through Stage 3.4.4;
- historical regression assertions that intentionally pin current runtime control/server/migration/repository metadata were rebased to Stage 3.4.4.

## Deterministic selection semantics

Only the immutable Stage-3.4.3 `ELIGIBLE` candidate projection is ranked. The policy is:

```text
STAGE343_ELIGIBLE_CANONICAL_TUPLE_ASC_V1
```

Canonical ascending key:

```text
(candidate_index, subsystem_id, capability_id, capability_version)
```

Rank 1 becomes the selected **logical** route. No runtime endpoint or availability is bound.

When no eligible candidate exists, the decision is durably recorded as:

```text
NO_ELIGIBLE_ROUTE
```

No rejected candidate is used as fallback.

## Preserved

- Stage-3.4.3 remains the sole eligible-candidate source;
- no candidate synthesis or resurrection;
- no runtime endpoint resolution or health probe;
- no resource assignment;
- no Governance query or authorization grant;
- no delegation/handoff;
- no dispatch;
- no target action or actuation;
- no Mission version-vector extension;
- `EXTERNAL_APTS_GSS` remains the Governance authorization authority.

## Boundary

```text
ELIGIBLE != SELECTED ROUTE
SELECTED ROUTE != RUNTIME AVAILABILITY
SELECTED ROUTE != AUTHORIZATION
ROUTE SELECTION != DELEGATION
ROUTE SELECTION != DISPATCH
ROUTE SELECTION != EXECUTION
```

## Validation

```text
Stage 3.4.4 focused: 50 passed
Stage 3.4.1:         19 passed
Stage 3.4.2:         26 passed
Stage 3.4.3:         35 passed
Stage 3.4 cumulative: 130 passed
Total collected regression set: 636 tests
```

The 636-test set was validated by complete partitioned Stage/module execution in the build environment. One all-at-once Stage-3.4/full-suite invocation exceeded the execution-session timeout; no partition failed.
