# Patch Notes — Stage 5.3 Enumeration Agent

## Added

- `pentest_subsystem/enumeration.py`
  - canonical Stage-5.3 contract and definition;
  - strict Enumeration run request normalization;
  - deterministic Enumeration run identity;
  - exact Stage-5.2 Recon predecessor identity/hash binding;
  - service, technology, version, endpoint, and configuration observation normalization;
  - deterministic integrity-bound Enumerated Asset Model;
  - Stage-4.9 Observation/Evidence lineage binding;
  - out-of-local-task-scope observed-only handling;
  - Stage-4.8 scope/RoE evaluation for enumeration proposals;
  - local Pentest-task scope precheck;
  - governed `ACTION_PROPOSAL` publication with Stage-6 execution deferral;
  - SHA-bound Enumeration Evidence Bundle;
  - restart-safe/idempotent repository and Stage-5.1 progress handoff.
- `pentest_migrations/010_stage5_3_enumeration_agent.sql`.
- Stage-5.3 HTTP routes in `pentest_subsystem/api_service.py`.
- `tests/test_stage5_3_enumeration_agent.py` with 26 focused tests.
- `STAGE5_3_ACCEPTANCE.ps1` and Stage-5.3 packaging/evidence documentation.

## Changed

- Active Pentest API control is now `stage5.3-enumeration-agent` / `APTSPentestSubsystem/5.3`.
- `run/pentest_subsystem.py` describes Stage 5.3 as the active runtime.
- Package exports/docstring include the Enumeration Agent surface.

## Preserved boundaries

- Stage-5.1 remains the local multi-agent orchestration authority.
- Stage-5.2 remains the authoritative Reconnaissance predecessor.
- Global Mission Orchestrator remains the global mission authority.
- Stage-4.8 and Stage-4.9 governance/evidence stores are reused rather than replaced.
- Enumeration specialist has no raw tool access, no direct network execution, no target actuation, and cannot mint authorization.
- Stage 6 remains the controlled execution plane.
