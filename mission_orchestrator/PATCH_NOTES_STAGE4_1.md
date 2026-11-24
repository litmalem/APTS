# Stage 4.1 patch notes — Pentest Boundary & Canonical Contract

- Added a separate `pentest_subsystem` package so Stage 4 does not overwrite the closed Stage-3 Global Mission Orchestrator control.
- Added SHA-bound boundary contract `apts-stage4.1-pentest-boundary-canonical-contract-v1`.
- Bound the Stage-4.1 contract to the canonical Stage-3.9.10 closure contract and the Stage-3.4.1 registered `PENTEST` subsystem contract.
- Added the required handoff fields: `pentest_id`, `mission_id`, `task_id`, `scope`, `objective`, `constraints`, `roe`, and `authorization_reference`.
- Added an explicit ownership model separating Mission Orchestrator identity/task/scope authority, external `aptsGSS` authorization authority, and Pentest local `pentest_id` authority.
- Added fail-closed validation for unknown/missing handoff fields, noncanonical identity prefixes, malformed authorization references, non-SHA-256 decision hashes, invalid policy versions, and non-authorized handoffs.
- Added deterministic SHA-bound validation envelopes that are explicitly **not** execution acceptance records.
- Added Pentest runtime health and read-only canonical contract endpoints on the new default runtime port `8790`.
- Added validation-only endpoint `POST /api/pentest/boundary/validate`.
- Added explicit HTTP `409` rejection on `POST /api/execution/dispatches` because execution intake belongs to later Stage-4 work.
- Added `START_STAGE4_1_PENTEST.ps1` and `run/pentest_subsystem.py`.
- Added 15 focused Stage-4.1 tests.
- Canonical inventory increases from 1575 to **1590 tests**.
- No existing Mission Orchestrator production code, repository schema, or migration was changed.
- Mission Orchestrator remains at server/control `APTSMissionOrchestrator/3.9.10` / `stage3.9.10-global-mission-orchestrator-acceptance-regression-gate` and migration 53.
- Pentest Stage-4.1 repository migration level is `0`: no local durable store exists yet.
- No PIP ingestion, local Pentest task persistence, workflow lifecycle, tool invocation, external target I/O, or target actuation is introduced.
- Next stage: **4.2 — PIP Ingestion, Validation & Binding**.
