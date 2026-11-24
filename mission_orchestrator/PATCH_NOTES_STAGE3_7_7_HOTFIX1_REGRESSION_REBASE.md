# PATCH NOTES — Stage 3.7.7 Hotfix 1: Regression Baseline Rebase

## Problem observed

The host Stage 3.7.7 acceptance completed the canonical regression with `4 failed, 1300 passed` out of `1304` tests. All four failures are stale regression assertions; the Stage 3.7.7 runtime preflight and authority-boundary checks passed.

## Resolution

Only four test files are changed:

- `tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py`
- `tests/test_stage3_7_3_replan_eligibility_governance_gate.py`
- `tests/test_stage3_7_4_canonical_replan_snapshot_context_binding.py`
- `tests/test_stage3_7_5_deterministic_replan_candidate_generation.py`

Changes:

1. Rebase Stage 3.5.10 supported-control negative indexes for the Stage 3.7.6 + 3.7.7 current tail and add explicit Stage 3.7.6 positional verification.
2. Replace stale Stage 3.7.3–3.7.5 global-handler assertions that prohibited `replan-commit` with assertions that preserve each predecessor route and verify the legitimate Stage 3.7.7 commit surface.
3. Preserve the existing `replan-supersession` negative boundary where applicable.

No runtime or migration change is included.

## Verification

- compileall: PASS
- `1304 tests collected`
- exact four rebased checks: `4 passed`
- focused Stage 3.7.7: `22 passed in 26.46s`
