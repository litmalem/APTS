# Stage 3.7.4 Patch Notes — Canonical Replan Snapshot & Context Binding

## Change summary

Stage 3.7.4 adds a durable immutable context-freezing layer above the Stage-3.7.3 Replan Eligibility & Governance Gate. An eligible adaptation episode can now be bound to an exact canonical ReplanSnapshot without issuing lifecycle `REPLAN`, re-querying Governance, invoking a planner, creating a successor Plan, or performing any dispatch/actuation.

### Added

- `mission_orchestrator/replan_snapshot.py`
  - strict Stage-3.7.4 request normalization;
  - deterministic request fingerprinting;
  - canonical `rpsnap-*` identity generation;
  - Stage-3.7.1/3.7.2/3.7.3 predecessor verification;
  - ELIGIBLE-gate enforcement;
  - Mission state/version and active Plan-head concurrency binding;
  - Mission scope/Governance-binding verification;
  - canonical task/dependency/outcome context digest;
  - immutable ReplanSnapshot construction and contract verification;
  - explicit local-durable-context-only semantics;
  - explicit no-external-refresh/no-Governance-query/no-REPLAN/no-planner/no-candidate/no-delta/no-commit/no-supersession/no-dispatch/no-actuation boundary.
- migration `048_stage3_7_4_canonical_replan_snapshot_context_binding.sql`;
- durable store `mission_replan_snapshots`;
- canonical Mission event `MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND`;
- Stage-3.7.4 POST/GET/list/by-episode/definition API surfaces;
- Stage-3.7.4 repository persistence and reconstruction/integrity checks;
- 20 focused Stage-3.7.4 regression tests;
- Stage-3.7.4 target-host acceptance script and release metadata.

### Modified

- `mission_orchestrator/service.py`
  - activates `stage3.7.4-canonical-replan-snapshot-context-binding`;
  - exposes Stage-3.7.4 service methods and health metadata;
  - binds canonical durable source facts;
  - extends repository reconstruction/integrity and persistence manifest.
- `mission_orchestrator/repository.py`
  - creates SQLite/MySQL-compatible Stage-3.7.4 store;
  - adds get/list/by-episode/by-idempotency/store operations;
  - adds persistence record-count support.
- `mission_orchestrator/repository_model.py`
  - raises repository migration head from 47 to **48**.
- `mission_orchestrator/api_service.py`
  - server version becomes `APTSMissionOrchestrator/3.7.4`;
  - adds Stage-3.7.4 snapshot routes.
- `mission_orchestrator/mission_events.py`
  - registers `MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND`.
- `mission_orchestrator/errors.py`
  - adds Stage-3.7.4 conflict/not-found/guard-rejected errors.

### Historical regression rebase

Tests whose assertions intentionally follow the **current repository head** were rebased from Stage 3.7.3 / migration 47 / server 3.7.3 to Stage 3.7.4 / migration 48 / server 3.7.4. Stage-local historical constants that document the original stage remain unchanged.

### Explicit non-goals

Stage 3.7.4 does not add authority for:

- lifecycle `REPLAN`;
- fresh Governance authorization;
- planner invocation;
- Plan-delta generation;
- ReplanCandidate/successor Plan creation;
- successor-Plan validation;
- replan decision/commit;
- Plan supersession;
- Mission state transition;
- dispatch/execution;
- external target I/O or actuation.

The next planned control remains **Stage 3.7.5**.


## Build validation

- Python compile: PASS.
- Canonical pytest inventory: 1236 tests.
- Focused Stage 3.7.4: 20/20 PASS.
- Full Stage 3.1–3.7.4 build-sandbox regression: **1236/1236 PASS in 882.22s (14m42s)**.
- Formal target-host acceptance remains gated by `STAGE3_7_4_ACCEPTANCE.ps1`.
