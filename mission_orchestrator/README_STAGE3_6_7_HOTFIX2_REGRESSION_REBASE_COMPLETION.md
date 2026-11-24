# Stage 3.6.7 Hotfix 2 — Regression Rebase Completion

This is a test-only follow-up to Hotfix 1.

## Scope

No runtime implementation is changed. Stage 3.6.7 remains:

- control version: `stage3.6.7-completion-readiness-blockers`
- repository migration level: `42`
- canonical pytest inventory: `1102`

The hotfix updates the 12 test files responsible for the 13 remaining host failures.

## Files changed

- Stage 3.1.6–3.1.8 regression tests: current runtime control expectation
- Stage 3.2.1–3.2.9 regression tests: current runtime control, repository migration head, and supported-control positional slice rebase

## Installation

Extract this archive directly into `D:\mission_orchestrator` and overwrite matching files under `tests\`.
No database migration and no runtime restart are required for this hotfix.

Then run `STAGE3_6_7_ACCEPTANCE.ps1` again.
