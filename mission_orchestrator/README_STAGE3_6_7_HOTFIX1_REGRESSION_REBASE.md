# Stage 3.6.7 Hotfix 1 — Regression Baseline Rebase

This hotfix corrects stale regression assertions exposed after Stage 3.6.7 became the current runtime head.

## Scope

No runtime implementation, API contract, durable store, schema, or database migration is changed.
The Stage 3.6.7 implementation remains:

- `control_version`: `stage3.6.7-completion-readiness-blockers`
- server version: `APTSMissionOrchestrator/3.6.7`
- repository migration level: `42`
- canonical pytest inventory: `1102`

## Corrected regression expectation classes

1. Current runtime control assertions were rebased from Stage 3.6.6 to Stage 3.6.7.
2. Current repository-head assertions were rebased from migration level / file count `41` to `42` while historical stage-local migration markers remain unchanged.
3. Migration manifest expectations now include `042_stage3_6_7_completion_readiness_blockers.sql`.
4. Historical `supported_controls` positional slices were shifted by one because Stage 3.6.7 appends one canonical control after Stage 3.6.6.
5. Stage 3.4 and Stage 3.5 closure-tail assertions were extended to include Stage 3.6.6 followed by Stage 3.6.7 where applicable.

## Verification in patch workspace

- Previously failing host node IDs: `57 passed`.
- Focused rerun time: `18.32s`.
- A complete 1102-test run was started in the constrained patch workspace but could not finish within the execution window; authoritative full regression remains the target-host acceptance script.
