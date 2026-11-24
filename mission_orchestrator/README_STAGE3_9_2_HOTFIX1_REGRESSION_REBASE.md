# Stage 3.9.2 Hotfix 1 — Supported-Control Regression Rebase

This hotfix repairs three stale historical `supported_controls` assertions exposed by the authoritative Windows-host Stage 3.9.2 acceptance run.

## Host evidence

The Stage 3.9.2 runtime itself passed all pre-regression qualification checks:

- Stage 3.9.2 active with Stage 3.9.1 predecessor and no authority expansion;
- qualification contract deterministic and bound to Stage 3.9.1;
- canonical Mission intake reached `CREATED`;
- lifecycle segment reached `PLANNING(v3)`;
- read-only verifier proved exact lineage;
- exact replays remained idempotent;
- Python compilation passed;
- canonical inventory remained 1458 tests.

The full regression then finished with `3 failed, 1455 passed`.

All three failures are historical supported-control chain assertions. The runtime correctly preserves:

`... -> stage3.8.10 -> stage3.9.1 -> stage3.9.2`

but those three assertions expected Stage 3.9.2 immediately after Stage 3.8.10 and therefore omitted the already-accepted Stage 3.9.1 control.

## Root cause

This is a regression-baseline defect, not a Stage 3.9.2 runtime defect.

The Stage 3.9.2 implementation correctly appends:

- `stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract`
- `stage3.9.2-intake-lifecycle-e2e-segment-qualification`

in canonical order.

Three older closure/observability tests were rebased to the new current control but their fixed tail lengths / suffix lists were not expanded to preserve Stage 3.9.1.

## Files changed

Test-only:

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`

Verification/documentation:

- `STAGE3_9_2_HOTFIX1_VERIFY.ps1`
- `README_STAGE3_9_2_HOTFIX1_REGRESSION_REBASE.md`
- `PATCH_NOTES_STAGE3_9_2_HOTFIX1_REGRESSION_REBASE.md`
- `REGRESSION_EVIDENCE_STAGE3_9_2_HOTFIX1.txt`

## Exact corrections

### Stage 3.4.10 historical tail

The tail beginning at control index 30 now explicitly ends with:

`stage3.8.10 -> stage3.9.1 -> stage3.9.2`

The expected unique tail cardinality changes from 51 to 52.

### Stage 3.5.10 historical tail

`stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract` is inserted before the Stage 3.9.2 current control. Negative suffix indices are shifted by one consistently.

### Stage 3.8.1 observability predecessor-chain assertion

The suffix window expands from the last 12 controls to the last 13 controls and now preserves Stage 3.9.1 before Stage 3.9.2.

## Runtime impact

None.

- production Python modules unchanged;
- API routes unchanged;
- Stage 3.9.2 qualification semantics unchanged;
- `control_version` remains `stage3.9.2-intake-lifecycle-e2e-segment-qualification`;
- server version remains `APTSMissionOrchestrator/3.9.2`;
- repository migration remains 53;
- canonical inventory remains 1458;
- no new durable store;
- no authority expansion.

## Local qualification after hotfix

Using a fresh `Mission(10).zip` baseline with the Stage 3.9.2 overlay and this hotfix applied:

- Python compilation: PASS;
- canonical collection: **1458 tests collected**;
- exact three previously failing tests: **3/3 PASS**;
- complete Stage 3.4.10 + Stage 3.5.10 + Stage 3.8.1 + Stage 3.9.1 + Stage 3.9.2 modules: **63/63 PASS**.

The complete 1458-test regression must still be rerun on the authoritative Windows host using `STAGE3_9_2_ACCEPTANCE.ps1`.
