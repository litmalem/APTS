# PATCH NOTES — Stage 3.6.7 Hotfix 1: Regression Baseline Rebase

## Problem observed

The host acceptance run passed runtime activation, Python compilation, and the exact 1102-test inventory, then reported `57 failed, 1045 passed` during full regression.

The failures are deterministic regression-expectation drift, not evidence that the Stage 3.6.7 runtime contract itself is broken. They cluster into:

- stale `control_version == stage3.6.6-mission-success-criteria-evaluation` expectations;
- stale current repository migration level / migration-file count `41` after migration 042 was added;
- `supported_controls` slices calibrated before Stage 3.6.7 appended the new control;
- two closure-tail/count assertions that omitted the new Stage 3.6.7 tail member;
- migration-tail assertions that did not account for migration 041 before migration 042.

## Resolution

Regression tests are rebased to the Stage 3.6.7 current head while preserving historical stage-local invariants. No production module is changed by this hotfix.

## Verification

All 57 node IDs from the supplied host failure summary were rerun against the hotfix and passed (`57 passed in 18.32s`).
