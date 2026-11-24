# Patch Notes — Stage 3.5.7

## Execution Result / Evidence / Artifact Capture

Stage 3.5.7 extends the Stage-3.5 execution chain with authoritative terminal-result acquisition from the downstream subsystem runtime.

### Added

- `mission_orchestrator/execution_result.py`
  - canonical `xresult-*` contract;
  - strict request normalization and concurrency/source guards;
  - authoritative runtime terminal-result normalization;
  - mandatory evidence manifest and optional artifact manifest;
  - content-free reference/digest persistence;
  - idempotency fingerprinting and contract verification.
- `migrations/033_stage3_5_7_execution_result_evidence_artifact_capture.sql`
  - durable `mission_execution_result_captures` store;
  - unique result-capture identity;
  - `(mission_id, idempotency_key)` uniqueness;
  - one terminal result per `(mission_id, execution_attempt_id)`;
  - foreign-key binding to mission, plan, task, dispatch, attempt, delivery, and running projection.
- `tests/test_stage3_5_7_execution_result_evidence_artifact_capture.py`
  - 18 focused regression/acceptance tests.

### Updated

- `mission_orchestrator/service.py`
  - runtime control activation `stage3.5.7-execution-result-evidence-artifact-capture`;
  - result-capture service methods;
  - source-binding guards against active Plan, Stage 3.5.4 attempt, Stage 3.5.5 delivery, and latest Stage 3.5.6 running projection;
  - canonical result event emission;
  - repository reconstruction/integrity verification;
  - Stage-3.5.7 health declarations.
- `mission_orchestrator/repository.py`
  - SQLite/MySQL persistence, lookup, history, idempotency, and one-result-per-attempt enforcement.
- `mission_orchestrator/repository_model.py`
  - migration level `33` and `mission_execution_result_captures` persistence-manifest projection.
- `mission_orchestrator/api_service.py`
  - server version `APTSMissionOrchestrator/3.5.7`;
  - POST/GET result-capture routes and canonical error mapping.
- `mission_orchestrator/execution_delivery.py`
  - downstream runtime terminal-result read support.
- `mission_orchestrator/mission_events.py`
  - `MISSION_EXECUTION_RESULT_EVIDENCE_ARTIFACT_CAPTURED` event support.
- `mission_orchestrator/errors.py`
  - Stage-3.5.7 not-found/guard/conflict error types.
- Compatibility regression expectations across prior Stage 3.1–3.5.6 tests were rebased to the active Stage-3.5.7 control lineage, HTTP version, repository migration level 33, and migration inventory while preserving historical stage contracts.

### Safety / authority boundary

Stage 3.5.7 is evidence capture, not execution authorization and not completion authority. It performs no new Governance query, no endpoint resolution, no redelivery, no new target-action dispatch, and no mission-state transition.

Raw evidence/artifact payload persistence is forbidden. Only references, hashes, metadata, counts, provenance, and canonical manifests are retained.

### Next boundary

Stage 3.5.8 — execution outcome verification / completion semantics.
