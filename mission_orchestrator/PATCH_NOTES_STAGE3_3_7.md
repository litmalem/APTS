# Patch Notes — Stage 3.3.7 Plan Versioning, Replanning & Supersession

## Added

- `mission_orchestrator/plan_versioning.py` defining canonical Plan-version contracts, request normalization, hashing, lineage verification, and Stage-3.3.7 discovery metadata.
- Migration `015_stage3_3_7_plan_versioning_replanning_supersession.sql`.
- Durable stores `mission_plan_versions` and `mission_plan_version_heads` for SQLite/MySQL repository implementations.
- Service APIs for initial Plan activation, active Plan reads, version history, versioning definition, and replanning successor creation.
- HTTP endpoints:
  - `POST /api/missions/{mission_id}/plan-versions/activate`
  - `POST /api/missions/{mission_id}/plan-versions/replan`
  - `GET /api/missions/{mission_id}/plan-versions`
  - `GET /api/missions/{mission_id}/plan-versions/active`
  - `GET /api/missions/{mission_id}/plan-versioning-definition`
- Typed Stage-3.3.7 conflict/not-found/guard errors.
- Canonical events `MISSION_PLAN_VERSION_ACTIVATED` and `MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED`.
- Version-vector domain `plan_versioning_version`.
- Repository persistence-manifest and integrity checks for the entire version chain and active head.
- Lifecycle guard requiring a committed current replan successor before a versioned Mission may return from `REPLANNING` to `RUNNING`.
- `tests/test_stage3_3_7_plan_versioning_replanning_supersession.py`.
- `STAGE3_3_7_ACCEPTANCE.ps1` and release documentation.

## Changed

- Current control advances to `stage3.3.7-plan-versioning-replanning-supersession`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.3.7`.
- Repository migration level advances `14 -> 15`.
- Historical tests that intentionally track the *current* release control/migration are rebased while preserving historical Stage-3.1 through Stage-3.3.6 contracts.

## Preserved

- Stage-3.3.1 canonical base Plan remains immutable.
- Stage-3.3.2 planner-input snapshot and Stage-3.3.3/3.3.4 planning artifacts are not mutated by supersession.
- Stage-3.3.6 validation remains a feasibility result, not Governance authorization.
- Governance authority remains `EXTERNAL_APTS_GSS`.
- No task scheduling, target dispatch, target actuation, external model call, or external network I/O is introduced by Stage 3.3.7.

## Validation

- Python compile: PASS.
- Focused Stage-3.3.7: **27 passed**.
- Full regression: **428 passed**.
