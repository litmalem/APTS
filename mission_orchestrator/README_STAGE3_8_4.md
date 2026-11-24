# Stage 3.8.4 — Live Mission State & Execution Projection

Stage 3.8.4 adds a deterministic, restart-stable, read-only live operational projection of canonical Mission state, plan/task progress, routing/delegation counts, execution attempts/running/result/termination state, adaptation/replan activity, and the current causal head.

The projection is derived on demand from existing authoritative Stage 3.1–3.7 stores plus the verified Stage 3.8.2 normalized event ledger and Stage 3.8.3 global causal graph. It is not a second source of truth and adds no durable projection store or database migration.

Runtime control: `stage3.8.4-live-mission-state-execution-projection`. Server: `APTSMissionOrchestrator/3.8.4`. Repository migration remains 53.

Read APIs:
- `GET /api/missions/{mission_id}/observability-live-state`
- `GET /api/observability/live-state-contract`

The projection performs no authorization, Governance query, runtime probe, external network I/O, telemetry export, routing, delegation, dispatch, execution attempt creation, Mission lifecycle transition, target action, or target actuation.

Canonical inventory after this patch: 1389 tests. Authoritative deployment-host gate: `STAGE3_8_4_ACCEPTANCE.ps1`.
