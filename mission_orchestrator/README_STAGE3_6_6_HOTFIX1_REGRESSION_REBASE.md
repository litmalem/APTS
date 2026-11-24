# Stage 3.6.6 Hotfix 1 — Regression Baseline Rebase

This hotfix corrects stale regression assertions exposed after Stage 3.6.6 became the current runtime head.

## Scope

No runtime implementation, API contract, durable store, schema, or migration is changed by this hotfix. The Stage 3.6.6 implementation remains:

- control_version: `stage3.6.6-mission-success-criteria-evaluation`
- server_version: `APTSMissionOrchestrator/3.6.6`
- repository migration level: `41`
- canonical pytest inventory: `1082`

The hotfix updates regression tests that were still pinned to the Stage 3.6.5 current-head assumptions.

## Corrected assertion classes

1. Current runtime control assertions:
   - old: `stage3.6.5-mission-outcome-aggregation`
   - new: `stage3.6.6-mission-success-criteria-evaluation`

2. Current repository head assertions:
   - old total migration count / repository level: `40`
   - new current repository level: `41`
   - historical Stage 3.6.5 migration metadata remains `40`.

3. Migration manifest expectations:
   - adds `041_stage3_6_6_mission_success_criteria_evaluation.sql` to current-head migration lists.

4. `supported_controls` positional slices:
   - rebased by one position because Stage 3.6.6 appended one canonical control after Stage 3.6.5.
   - no control ordering was changed.

5. Stage 3.4 / Stage 3.5 tail assertions:
   - include the Stage 3.6.5 predecessor immediately before Stage 3.6.6 where the test is validating the current complete control tail.

## Verification performed in the patch workspace

- Python compile: PASS
- pytest collection: `1082 tests collected`
- Stage 3.6.6 focused suite: `20 passed`
- current-head health/supported-control/migration regression subset: `66 passed`
- all `56` node IDs that failed in the host acceptance log were rerun against the hotfix and passed

A complete 1082-test run must still be executed on the target host through `STAGE3_6_6_ACCEPTANCE.ps1` before Stage 3.6.6 is declared accepted.
