# Patch Notes — Stage 5.10 Agentic Pentest Acceptance & Regression Gate

## Added

- `pentest_subsystem/agentic_pentest_acceptance_gate.py`
  - SHA-256-bound Stage-5 closure contract;
  - exact Stage-5.1…5.9 control/hash binding;
  - exact 12 roadmap acceptance dimensions;
  - explicit specialist/role identity binding;
  - Stage-4.10 foundation-root binding;
  - seven Stage-5.9 scenario requirements;
  - no-new-authority closure semantics.
- `pentest_subsystem/agentic_pentest_acceptance_service.py`
  - Stage-5.10 health projection;
  - read-only closure-contract service;
  - migration 16 preserved.
- `tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py`
  - 15 focused closure, identity, hash-binding, API, read-only, and authority-boundary tests.
- `STAGE5_10_ACCEPTANCE.ps1`
  - final external Stage-5 acceptance harness;
  - full historical regression as final deployment PASS/FAIL authority.

## Changed

- `pentest_subsystem/api_service.py`
  - adds `PentestSubsystemStage510Handler`;
  - active server version becomes `APTSPentestSubsystem/5.10`;
  - read-only Stage-5.10 contract routes;
  - Stage-5.9 handler retained;
  - active `serve()` advances to Stage 5.10.
- `pentest_subsystem/__init__.py`
  - exports Stage-5.10 contract/service primitives.
- `run/pentest_subsystem.py`
  - runtime description advances to Stage 5.10.

## Preserved boundaries

- no migration 17;
- no new durable store;
- no `PolicyDecision` minting;
- no `ExecutionRequest` or `ActionResult` creation;
- no raw tool invocation;
- no external target network I/O;
- no target actuation;
- Stage 6 remains controlled execution and target-evidence authority.
