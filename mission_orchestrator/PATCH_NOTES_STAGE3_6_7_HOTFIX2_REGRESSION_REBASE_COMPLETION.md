# PATCH NOTES — Stage 3.6.7 Hotfix 2: Regression Rebase Completion

## Problem observed

After Hotfix 1, Stage 3.6.7 acceptance improved from 57 failures to 13 failures (1089 passed / 1102 total).
The remaining failures are all stale regression assertions in Stage 3.1.6–3.1.8 and Stage 3.2.1–3.2.9 test files that were not included in Hotfix 1.

The remaining drift is deterministic:

- current `control_version` still asserted `stage3.6.6-mission-success-criteria-evaluation`;
- current repository migration level still asserted `41` instead of `42`;
- Stage 3.2 `supported_controls` negative slices were still calibrated to a 56-control list and therefore needed a one-position rebase after Stage 3.6.7 appended the 57th control.

## Resolution

This hotfix updates only regression tests. It does not alter production runtime code, API contracts, durable stores, migrations, or authority boundaries.

Rebased current-head expectations:

- `control_version`: `stage3.6.7-completion-readiness-blockers`
- current repository migration level: `42`
- Stage 3.2 `supported_controls` positional slices: shifted one position to preserve the exact historical control range being validated.

Historical stage-local invariants are preserved.

## Verification

In the reconstructed Stage 3.6.7 workspace with Hotfix 1 already applied:

- the exact 13 node IDs reported by the host acceptance log: **13 passed**
- canonical collection: **1102 tests collected**
- no stale `control_version == stage3.6.6...` current-head assertions remain
- no stale `mission_repository_migration_level == 41` current-head assertions remain

The target host must still run the complete `STAGE3_6_7_ACCEPTANCE.ps1` suite before Stage 3.6.7 is declared accepted.
