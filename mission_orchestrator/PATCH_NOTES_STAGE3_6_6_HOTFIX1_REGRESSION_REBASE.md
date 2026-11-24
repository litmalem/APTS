# PATCH NOTES — Stage 3.6.6 Hotfix 1: Regression Baseline Rebase

## Problem observed

The Stage 3.6.6 acceptance run reached the full regression phase with runtime activation, Python compilation, and the 1082-test inventory all passing, but the full suite reported 56 failures. The failures were regression-expectation drift rather than Stage 3.6.6 runtime failures.

The failure set clustered into three deterministic categories:

- tests still asserting current `control_version == stage3.6.5-mission-outcome-aggregation`;
- tests still asserting current repository migration level / migration-file count `40` after migration 041 was introduced;
- tests using negative `supported_controls` slices calibrated for a 55-control list, which shifted after Stage 3.6.6 appended the 56th control.

Two additional migration-manifest assertions still ended at migration 040, and a Stage 3.5 closure test still ended its control tail at Stage 3.6.4/3.6.6 without explicitly including Stage 3.6.5.

## Resolution

The regression suite was rebased to the Stage 3.6.6 current head while preserving all historical stage-local invariants. In particular, the Stage 3.6.5-specific database migration marker remains 40; only current repository-head assertions now use 41.

No production module was changed.
