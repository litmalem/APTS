# Stage 3.8.4 Hotfix 1 — Regression Baseline Rebase

This hotfix rebases historical regression expectations after activation of Stage 3.8.4 — Live Mission State & Execution Projection.

## Triggering host evidence

The authoritative Windows host acceptance reached the canonical suite with:

- runtime contract active: PASS
- Python compilation: PASS
- canonical inventory: 1389 tests
- full regression: 1314 passed, 75 failed

The failures were concentrated in historical regression assertions that still treated Stage 3.8.3 as the current runtime/server control, plus a small number of `supported_controls` tail assertions that did not account for the Stage 3.8.1–3.8.3 observability controls preceding Stage 3.8.4.

## Root cause

The Stage 3.8.4 runtime was correctly active as:

- `control_version = stage3.8.4-live-mission-state-execution-projection`
- `server_version = APTSMissionOrchestrator/3.8.4`
- repository migration level = `53`

However, older Stage 3.1–3.7 regression modules retained the Stage 3.8.3 current-control baseline. Those assertions were no longer valid once Stage 3.8.4 became the active control.

## Hotfix scope

Test-only regression rebase:

- current `control_version` expectations are rebased from Stage 3.8.3 to Stage 3.8.4;
- current `server_version` expectations are rebased from 3.8.3 to 3.8.4;
- historical Stage 3.7 control-window assertions are anchored to the stable `[60:70]` control range instead of suffix ranges whose meaning changes when later controls are appended;
- Stage 3.4.10 and Stage 3.5.10 complete-tail checks now include Stage 3.8.1, Stage 3.8.2, Stage 3.8.3, and Stage 3.8.4 in canonical order;
- Stage 3.6.10 / Stage 3.7.7 / Stage 3.7.8 / Stage 3.7.9 assertions separate historical lineage checks from the current-control tail assertion.

No production runtime module, endpoint, projection algorithm, authority boundary, persistence schema, durable store, or database migration is changed.

## Local qualification result

- Python compilation: PASS
- canonical collection: `1389 tests collected`
- focused Stage 3.8.1–3.8.4 regression: `33 passed in 1.58s`
- full canonical regression: `1389 passed in 1116.30s (0:18:36)`

This establishes local regression closure for the hotfix package. The Windows deployment host must still rerun `STAGE3_8_4_ACCEPTANCE.ps1` to record authoritative Stage 3.8.4 acceptance.

## Invariants preserved

Stage 3.8.4 remains:

- control: `stage3.8.4-live-mission-state-execution-projection`
- server: `APTSMissionOrchestrator/3.8.4`
- migration level: `53`
- canonical inventory: `1389`
- live projection: deterministic, restart-stable, read-only
- new durable store: none

Run `STAGE3_8_4_HOTFIX1_VERIFY.ps1` first, then rerun `STAGE3_8_4_ACCEPTANCE.ps1` for authoritative closure on the deployment host.
