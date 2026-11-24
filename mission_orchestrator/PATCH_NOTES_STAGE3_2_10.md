# Patch Notes — Stage 3.2.10 Lifecycle Acceptance & Regression Gate

## Added
- `mission_orchestrator/lifecycle_acceptance_gate.py` with the static Stage-3.2 closure contract.
- Stage-3.2 closure metadata in `/health`.
- `tests/test_stage3_2_10_lifecycle_acceptance_regression_gate.py` covering end-to-end lifecycle closure, terminal finality, event automation, restart reconstruction, and migration invariants.
- `STAGE3_2_10_ACCEPTANCE.ps1` for compile/regression plus live lifecycle probes.
- Stage-3.2.10 installation, manifest, hash, and release documentation.

## Changed
- Current control advances to `stage3.2.10-lifecycle-acceptance-regression-gate`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.10`.
- Package description advances through Stage 3.2.10.
- Historical regression assertions that track the active control version are advanced to Stage 3.2.10; Stage 3.2.9 remains explicitly supported.

## Preserved
- Repository migration level 8; no migration 009.
- Canonical state topology, command journal, append-only transition ledger, Mission event hash chain, and existing Stage-3.2 lifecycle semantics.
- `EXTERNAL_APTS_GSS` as sole Governance authorization authority.
- No planner invocation, target-action dispatch, target actuation, or external event-delivery worker.

## Validation
- Python compile: PASS.
- Full regression: **267 passed**.
- Live acceptance: `STAGE3_2_10_ACCEPTANCE.ps1`.
