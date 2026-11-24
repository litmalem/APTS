# Patch Notes — Stage 5.2 Reconnaissance Agent

## Added

- `pentest_subsystem/reconnaissance.py`
  - canonical Stage-5.2 contract and definition;
  - strict Recon run request normalization;
  - deterministic Recon run identity;
  - host/domain/service/attack-surface aggregation;
  - Stage-4.9 Observation/Evidence lineage binding;
  - Stage-4.8 scope/RoE evaluation for discovery proposals;
  - local Pentest-task scope precheck;
  - governed `ACTION_PROPOSAL` publication with Stage-6 execution deferral;
  - SHA-bound Recon Evidence Bundle;
  - restart-safe/idempotent repository and Stage-5.1 progress handoff.
- `pentest_migrations/009_stage5_2_reconnaissance_agent.sql`.
- Stage-5.2 HTTP routes in `pentest_subsystem/api_service.py`.
- `tests/test_stage5_2_reconnaissance_agent.py` with 24 focused tests.
- `STAGE5_2_ACCEPTANCE.ps1` and Stage-5.2 packaging/evidence documentation.

## Changed

- Active Pentest API control is now `stage5.2-reconnaissance-agent` / `APTSPentestSubsystem/5.2`.
- `run/pentest_subsystem.py` describes Stage 5.2 as the active runtime.
- Package exports/docstring include the Reconnaissance Agent surface.

## Preserved boundaries

- Stage-5.1 remains the local multi-agent orchestration authority.
- Global Mission Orchestrator remains the global mission authority.
- Stage-4.8 and Stage-4.9 governance/evidence stores are reused rather than replaced.
- Recon specialist has no raw tool access, no direct network execution, no target actuation, and cannot mint authorization.
- Stage 6 remains the controlled execution plane.
