# Patch Notes — Stage 4.10

## Added

- `pentest_subsystem/acceptance_gate.py`
  - SHA-256-bound Stage-4.10 Pentest Foundation Acceptance Gate contract
  - exact Stage-4.1…4.9 control/hash binding
  - exact 11 roadmap acceptance dimensions
  - explicit regression-evidence bindings per acceptance dimension
  - Stage-3.9.10 global mission root binding
  - no-new-authority closure semantics
- `pentest_subsystem/acceptance_service.py`
  - Stage-4.10 health projection
  - read-only acceptance-gate contract service
  - migration level 7 preserved
- `tests/test_stage4_10_pentest_foundation_acceptance_gate.py`
  - 15 focused closure-contract, API, lineage-root, no-mutation, and authority-boundary tests
- `STAGE4_10_ACCEPTANCE.ps1`
  - external final acceptance harness
  - explicit validation of all 11 roadmap acceptance dimensions
  - full historical regression as final PASS/FAIL authority

## Changed

- `pentest_subsystem/api_service.py`
  - added `PentestSubsystemStage410Handler`
  - server version advanced to `APTSPentestSubsystem/4.10`
  - added read-only Stage-4.10 contract route
  - retained Stage-4.9 historical handler and added `serve_stage49()`
  - current `serve()` now activates Stage 4.10
- `pentest_subsystem/__init__.py`
  - exports Stage-4.10 acceptance contract primitives
  - package summary advanced through Stage 4.10
- `run/pentest_subsystem.py`
  - runtime description advanced to Stage 4.10

## Acceptance invariants

1. Stage 4.10 is declarative; runtime self-certification is forbidden.
2. External acceptance harness is the deployment PASS/FAIL authority.
3. Stage-4.1 through Stage-4.9 canonical controls and hashes are frozen into the gate contract.
4. Persistence, restart, replay, idempotency, duplicate PIP, stale PIP, invalid scope, denied action, stop/kill, event ordering, and cross-subsystem lineage are mandatory acceptance dimensions.
5. Stage-3.9.10 remains the global mission root authority.
6. Pentest repository migration remains 7; no new durable store is created.
7. No authorization minting, tool invocation, external network I/O, execution intake, or target actuation authority is added.
8. Controlled execution remains Stage 6 authority.
9. PASS closes Stage 4 with output `PENTEST_SUBSYSTEM_PLATFORM` and hands off to Stage 5.1.
