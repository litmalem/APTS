# Patch Notes — Stage 3.7.10

## Added

- `mission_orchestrator/adapt_replan_acceptance_gate.py`
- static Stage-3.7 closure schema `apts-mission-stage3.7-adapt-replan-acceptance-gate-v1`
- ordered declaration of the nine prerequisite Stage-3.7 controls
- 17 mandatory Adapt/Replan acceptance gates
- health metadata for declaration-only acceptance semantics
- 12 focused Stage-3.7.10 closure tests
- `STAGE3_7_10_ACCEPTANCE.ps1` target-host acceptance harness
- release documentation, manifest, regression evidence, file inventory, and SHA-256 payload digest list

## Changed

- runtime control advanced from `stage3.7.9-adapt-replan-lineage-replay-recovery` to `stage3.7.10-adapt-replan-acceptance-regression-gate`
- HTTP server version advanced from `APTSMissionOrchestrator/3.7.9` to `APTSMissionOrchestrator/3.7.10`
- `supported_controls` now ends with the complete Stage-3.7.1 through Stage-3.7.10 chain
- historical current-head regression expectations were rebased to Stage 3.7.10 while preserving Stage 3.7.9 as the immediate predecessor
- canonical pytest inventory advanced from **1344** to **1356**
- Stage-3.7 focused inventory advanced from **188** to **200**

## Deliberately unchanged

- repository migration level remains **53**
- latest migration remains `053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql`
- no migration `054` is introduced
- no Stage-3.7.10 durable store is introduced
- Stage 3.7.7 remains the authoritative successor-Plan commit/materialization control
- Stage 3.7.8 remains the atomic supersession/handoff authority
- Stage 3.7.9 remains read-only lineage/replay/recovery reconstruction
- Stage 3.7.10 performs no adaptation detection, trigger classification, eligibility decision, snapshot binding, candidate generation, validation, Plan commit, Plan supersession, handoff creation, or recovery execution
- no new Governance/runtime/external I/O, routing, delegation, dispatch, execution attempt, lifecycle transition, Plan mutation, target action, or target actuation is introduced

## Build validation

- compile: PASS
- canonical collection: 1356 tests
- Stage-3.7 collection: 200 tests
- focused Stage 3.7.10: 12 passed
- Stage 3.7.1–3.7.9 focused suites: 188 passed when executed individually
- Stage 3.4.10 / 3.5.10 / 3.6.10 closure suites: 12 passed each

The build sandbox did not produce a completed full 1356-test run, so no full-regression PASS is claimed here. `STAGE3_7_10_ACCEPTANCE.ps1` is the authoritative target-host release gate.
