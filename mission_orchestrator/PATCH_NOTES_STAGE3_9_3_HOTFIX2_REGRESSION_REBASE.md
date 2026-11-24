# PATCH NOTES — Stage 3.9.3 Hotfix 2

## Change

Rebased seven stale historical `supported_controls` suffix/tail expectations so the canonical runtime chain preserves the already-accepted Stage 3.9.2 control immediately before Stage 3.9.3.

Canonical suffix is now:

`... -> stage3.8.10 -> stage3.9.1 -> stage3.9.2 -> stage3.9.3`

## Why

The authoritative Windows host completed the Stage 3.9.3 runtime preflight, live canonical qualification, compilation, focused Stage 3.9.3 tests, Stage 3.9.1/3.9.2 predecessor tests, and Stage 3.3.1-3.3.4 structural planning regression successfully. The complete 1473-test regression then ended with exactly seven failures, all in historical `supported_controls` tail/suffix assertions.

Those assertions had already been rebased to the Stage 3.9.3 current control, but omitted:

`stage3.9.2-intake-lifecycle-e2e-segment-qualification`

between Stage 3.9.1 and Stage 3.9.3. The production runtime control chain itself is correct.

## Files changed

Test-only:

- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py`
- `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`
- `tests/test_stage3_8_6_deterministic_mission_timeline_reconstruction.py`
- `tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py`
- `tests/test_stage3_8_8_observability_metrics_health_operator_diagnostics.py`
- `tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py`

## Runtime impact

None.

- no production Python module change
- no API change
- no Stage 3.9.3 semantic change
- no migration
- no durable store
- no authority expansion
- `control_version` remains `stage3.9.3-planning-task-graph-dependency-verification`
- repository migration remains `53`
- canonical inventory remains `1473`

## Local qualification

- modified-test Python compilation: PASS
- canonical collection: `1473 tests collected`
- exact seven host-failing tests: `7 passed in 3.90s`

Authoritative closure still requires rerunning `STAGE3_9_3_ACCEPTANCE.ps1` on the Windows deployment host.
