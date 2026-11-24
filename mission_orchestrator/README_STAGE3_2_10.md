# Stage 3.2.10 — Lifecycle Acceptance & Regression Gate

## Purpose

Stage 3.2.10 closes **Stage 3.2 — Control Mission Lifecycle**. It is a release/closure gate, not a new autonomy feature. The gate proves that Stage 3.2.1 through Stage 3.2.9 compose correctly as one deterministic, durable, event-traceable Mission lifecycle while preserving the architecture boundaries established in Stage 3.1.

The closed lifecycle now covers: lifecycle command contract; transition guard matrix; PIP activation; planning/run activation; evidence and approval waiting; pause/resume/replanning; abort/failure/expiration; cleanup and verified completion; and typed event-driven lifecycle automation with replay/stale-event reliability.

## Closure contract

The runtime advertises:

- `control_version = stage3.2.10-lifecycle-acceptance-regression-gate`
- `stage3_2_lifecycle_acceptance_gate_schema_version = apts-mission-stage3.2-lifecycle-acceptance-gate-v1`
- `stage3_2_lifecycle_acceptance_gate_mode = FULL_REGRESSION_PLUS_LIVE_LIFECYCLE_CONTRACT_PROBES`
- `stage3_2_lifecycle_acceptance_gate_baseline = STAGE_3_2_1_THROUGH_3_2_9`
- `stage3_2_lifecycle_acceptance_gate_runtime_change_mode = NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY`
- `stage3_2_lifecycle_acceptance_gate_database_change_mode = NO_NEW_DATABASE_MIGRATION`
- `stage3_2_lifecycle_acceptance_gate_expected_migration_level = 8`
- `stage3_2_lifecycle_acceptance_gate_declared_only = true`
- `stage3_2_lifecycle_acceptance_gate_runtime_self_certification = false`
- `stage3_2_lifecycle_acceptance_gate_external_execution_required = true`

`/health` declares the release contract only. It never claims that the external acceptance script has executed or passed.

## Required gates

1. Python compile.
2. Full pytest regression.
3. Mission health and authority boundary.
4. Lifecycle command and guard discovery.
5. PIP/planning/run activation.
6. Waiting evidence and approval resolution.
7. Pause/resume/replanning control.
8. Abort/failure/expiration finality.
9. Cleanup and verified completion.
10. Event automation idempotency and stale rejection.
11. Event lineage and repository integrity.
12. Restart reconstruction without external reads (covered by pytest closure probe).
13. Final no-Governance/no-target-execution expansion invariant.

## Authority boundary

Stage 3.2.10 adds no new runtime authority. `APTS-MO01` controls Mission lifecycle only. `aptsGSS / GOV-PLANE` remains the sole Governance/authorization authority. No planner is invoked, no target action is dispatched, no target actuation is enabled, and no external event-delivery worker is added.

The important invariants remain:

- `governance_authorization_authority = EXTERNAL_APTS_GSS`
- `target_action_dispatch_enabled = false`
- `target_actuation = false`
- `mission_lifecycle_automation_external_event_delivery_enabled = false`
- repository migration level = `8`

## Database compatibility

No Stage-3.2.10 migration is introduced. The latest migration remains:

`migrations/008_stage3_1_9_mission_event_lineage_foundation.sql`

## Regression

Stage-3.2.10 adds `tests/test_stage3_2_10_lifecycle_acceptance_regression_gate.py` and updates historical current-control assertions to recognize Stage 3.2.10 as the active release control while preserving Stage 3.2.1–3.2.9 as supported controls.

Patch-local validation:

- `python -m compileall -q mission_orchestrator tests` — PASS
- `python -m pytest -q` — **267 passed**

## Live acceptance

Run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_2_10_ACCEPTANCE.ps1
```

Expected final output:

```text
==============================================================================
STAGE 3.2.10 ACCEPTANCE: PASS
==============================================================================
```

A PASS closes Stage 3.2 and establishes the regression baseline for the next Stage-3 workstream.
