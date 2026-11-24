# Stage 3.7.1 Hotfix 1 — Regression Baseline Rebase

This hotfix corrects the single stale regression expectation exposed by the authoritative Stage 3.7.1 host acceptance run.

## Host evidence that triggered the hotfix

The Stage 3.7.1 acceptance run reached the full canonical regression and completed with:

- `1175` tests collected
- `1174 passed`
- `1 failed`
- failing node: `tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_health_declares_stage34_closure_without_new_authority_or_migration`

The runtime itself was active with:

- `control_version = stage3.7.1-canonical-adaptation-replan-contract-identity`
- `mission_repository_migration_level = 45`
- Stage 3.7.1 schema/prefix/store health fields present as expected

## Root cause

One historical Stage 3.4.10 regression assertion hard-coded the current `supported_controls[30:]` tail but skipped the Stage 3.6.10 closure control:

`stage3.6.10-outcome-acceptance-regression-gate`

The actual runtime tail is correct and includes Stage 3.6.10 immediately before the Stage 3.7.1 current control. The same test module already verifies this correct ordering later with:

- `tail[29] == stage3.6.10-outcome-acceptance-regression-gate`
- `tail[30] == stage3.7.1-canonical-adaptation-replan-contract-identity`
- `len(tail) == 31`

Therefore the failure is a stale test baseline, not a runtime/control/migration defect.

## Scope

Test-only change. No runtime implementation, API contract, persistence store, schema, control authority, or database migration is changed.

Stage 3.7.1 remains:

- control version: `stage3.7.1-canonical-adaptation-replan-contract-identity`
- server version: `APTSMissionOrchestrator/3.7.1`
- repository migration level: `45`
- canonical pytest inventory: `1175`

## Verification in hotfix workspace

- Python compile: PASS
- canonical pytest collection: `1175 tests collected`
- exact formerly failing node: `1 passed`
- full Stage 3.4.10 test module + Stage 3.7.1 focused suite: `31 passed in 22.83s`

The authoritative full `1175`-test regression must be rerun on the target host through `STAGE3_7_1_ACCEPTANCE.ps1` before recording formal Stage 3.7.1 acceptance.
