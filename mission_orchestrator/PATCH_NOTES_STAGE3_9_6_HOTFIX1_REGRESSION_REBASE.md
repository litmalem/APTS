# Stage 3.9.6 Hotfix 1 — Regression Rebase

## Trigger

The authoritative Windows acceptance run for Stage 3.9.6 passed runtime activation, contract API, Python compilation, canonical collection, focused Stage 3.9.6 qualification, the Stage 3.9 predecessor chain, and the terminal execution/outcome authority regression. The final historical regression completed with:

- `9 failed`
- `1506 passed`
- canonical inventory unchanged at `1515`

All nine failures were stale `supported_controls` ordering/cardinality assertions in predecessor regression tests.

The runtime control chain correctly contains:

`... -> stage3.9.4 -> stage3.9.5 -> stage3.9.6`

but the affected historical assertions were still rebased as if Stage 3.9.5 did not exist:

`... -> stage3.9.4 -> stage3.9.6`.

## Scope

This hotfix changes regression expectations only. It does **not** change:

- production runtime code;
- Stage 3.9.6 semantics;
- task completion authority;
- mission outcome authority;
- database schema or migration level;
- durable stores;
- HTTP API semantics;
- mission lifecycle state;
- adaptation/replanning handoff semantics.

Repository migration remains `53` and active control remains:

`stage3.9.6-task-completion-mission-outcome-closure`.

## Files changed

Test-only:

- `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py`
- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py`
- `tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py`
- `tests/test_stage3_8_6_deterministic_mission_timeline_reconstruction.py`
- `tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py`
- `tests/test_stage3_8_8_observability_metrics_health_operator_diagnostics.py`
- `tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py`

Documentation/checksum files are added for this hotfix only.

## Rebase details

The regression expectations now preserve the canonical suffix:

`stage3.9.1 -> stage3.9.2 -> stage3.9.3 -> stage3.9.4 -> stage3.9.5 -> stage3.9.6`.

The hotfix updates:

- exact supported-control lists;
- suffix slice cardinalities;
- absolute tail indexes;
- negative tail indexes;
- uniqueness/cardinality checks.

This prevents a second-wave failure after the first equality assertion is repaired.

## Local qualification

- modified test files compile: PASS
- canonical collection: `1515 tests collected`
- exact nine host-failing node IDs: `9 passed in 4.39s`

A broader sandbox run of the modified historical files plus Stage 3.9.6 exceeded the sandbox execution ceiling before completion and produced no failure before termination. Therefore authoritative closure still requires rerunning the normal Stage 3.9.6 acceptance gate on the Windows host.

## Host closure command

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_9_6_ACCEPTANCE.ps1
```

The expected canonical inventory remains `1515` tests. Acceptance is closed only when the full historical regression and the final Stage 3.9.6 gate both PASS.
