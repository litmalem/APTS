# Stage 4.2 patch notes — PIP Ingestion, Validation & Binding

- Added `pentest_subsystem/pip_contract.py` with canonical Stage-4.2 control
  `stage4.2-pip-ingestion-validation-binding`.
- Added SHA-bound Stage-4.2 contract
  `apts-stage4.2-pip-ingestion-validation-binding-v1` bound to the exact canonical
  Stage-4.1 boundary contract.
- Added canonical PIP schema `apts-pentest-intelligence-package-v1`.
- Added canonical PIP-binding envelope
  `apts-stage4.2-pip-ingestion-binding-envelope-v1`.
- Implemented the eight roadmap validation dimensions: PIP identity, mission binding,
  source CTI, freshness, integrity, scope, confidence, and provenance.
- PIP identity is versioned and namespaced under `pip-`; Mission, Pentest, and upstream
  task identities must exactly bind the Stage-4.1 handoff, and the Stage-4.2 envelope
  carries the canonical Stage-4.1 boundary-envelope SHA-256.
- Source CTI metadata requires source type/system, artifact id/version, and SHA-256
  artifact digest; Stage 4.2 performs no external CTI query.
- Freshness is fail-closed: `issued_at <= validation_time < expires_at`, using canonical
  RFC3339 UTC timestamps ending in `Z`.
- PIP content is SHA-256 bound over deterministic UTF-8 sorted JSON.
- Stage 4.2 binds PIP scope **exactly** to the accepted Stage-4.1 boundary scope. Scope
  transformation/narrowing policy remains outside this stage and is not silently inferred.
- Confidence must be a finite numeric value in `[0, 1]`.
- Provenance requires a producer and non-empty, duplicate-free source references.
- Added `PentestPIPService` and active Stage-4.2 HTTP handler while preserving the
  historical Stage-4.1 service/handler for regression compatibility.
- Added read-only PIP contract routes:
  - `GET /api/pentest/pip-contract`
  - `GET /api/contracts/pip-ingestion`
- Added PIP ingestion/binding route:
  - `POST /api/pentest/pip/ingest`
- Preserved Stage-4.1 boundary routes and validation semantics.
- `POST /api/execution/dispatches` remains explicitly rejected with HTTP `409`, now
  using `STAGE4_2_EXECUTION_INTAKE_NOT_ENABLED` on the active Stage-4.2 runtime.
- Added `START_STAGE4_2_PENTEST.ps1` and `STAGE4_2_ACCEPTANCE.ps1`.
- Added 15 focused Stage-4.2 tests.
- Canonical test inventory increases from 1590 to **1605 tests**.
- No Mission Orchestrator production code, repository schema, or migration was changed.
- Mission Orchestrator remains at migration 53 and control
  `stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`.
- Pentest repository migration remains `0`; Stage 4.2 adds no durable store.
- No local Pentest task materialization, workflow lifecycle, specialist-agent autonomy,
  tool invocation, external target I/O, or target actuation is introduced.
- Next stage: **4.3 — Pentest Mission & Task Contract**.
