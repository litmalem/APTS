# Patch Notes — Stage 3.4.2 Task Routing Intent & Candidate Resolution

## Added

- `mission_orchestrator/task_routing_intent.py`
  - canonical routing-intent schema and hash domains;
  - request normalization with route-authority injection rejection;
  - exact registry candidate resolver;
  - immutable routing-intent contract builder/verifier;
  - canonical Stage-3.4.2 definition.
- `mission_task_routing_intents` durable repository store.
- migration `019_stage3_4_2_task_routing_intent_candidate_resolution.sql`.
- API endpoints for create/list/get/definition of routing intents.
- `MISSION_TASK_ROUTING_CANDIDATES_RESOLVED` canonical Mission event.
- repository reconstruction/integrity verification for persisted routing intents.
- `tests/test_stage3_4_2_task_routing_intent_candidate_resolution.py` with 26 focused tests.
- Stage-3.4.2 README, install guide, acceptance script, patch manifest, and SHA-256 inventory.

## Changed

- active control -> `stage3.4.2-task-routing-intent-candidate-resolution`;
- HTTP server identity -> `APTSMissionOrchestrator/3.4.2`;
- repository migration level -> `19`;
- per-Mission persistence manifest now includes `mission_task_routing_intents`;
- package declaration -> through Stage 3.4.2;
- historical tests that intentionally assert current runtime control/server/migration metadata are rebased to Stage 3.4.2.

## Preserved

- Stage-3.4.1 canonical registry remains the sole candidate-resolution vocabulary source;
- Stage-3.1.5 historical `supported_routing_subsystems` runtime scope remains CTI-only;
- no endpoint resolution or health probing;
- no Stage-3.4.3 eligibility decision;
- no Stage-3.4.4 ranking/route selection;
- no resource assignment;
- no Governance authorization query/grant;
- no task delegation;
- no dispatch;
- no target actuation;
- `EXTERNAL_APTS_GSS` remains Governance authorization authority.

## Boundary

```text
CANDIDATE != ELIGIBLE
CANDIDATE != SELECTED ROUTE
ROUTING INTENT != AUTHORIZATION
ROUTING INTENT != DELEGATION
ROUTING INTENT != EXECUTION
```

## Validation

Focused verification:

```text
Stage 3.4.1 + 3.4.2 : 44 passed
Stage 3.4.2 focused : 26 passed
```

The historical regression suite remains available through `python -m pytest -q`; on constrained environments it may be run per Stage/test module to avoid external execution time limits.
