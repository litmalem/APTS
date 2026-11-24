# Patch Notes — Stage 5.6 Exploitation Agent

## Added

- `pentest_subsystem/exploitation.py`
  - canonical Stage-5.6 contract and definitions;
  - strict exploitation run request with executable-content rejection;
  - deterministic run identity;
  - exact Stage-5.5 attack-path run/output/evidence hash binding;
  - non-executing `ValidationTask` generation;
  - non-executing `ExploitActionProposal` generation;
  - Stage-4.8 scope/RoE eligibility for `validation` and `exploitation` capabilities;
  - Stage-4.9 `ACTION_PROPOSAL` lineage rooted in the Stage-5.4 hypothesis;
  - SHA-bound Stage-5.6 output and evidence bundle;
  - idempotent/restart-safe repository persistence;
  - Stage-5.1 validation/exploitation progress handoff that releases Stage 5.7.
- `pentest_migrations/013_stage5_6_exploitation_agent.sql`.
- Stage-5.6 HTTP routes and current active handler in `pentest_subsystem/api_service.py`.
- `tests/test_stage5_6_exploitation_agent.py` with 28 focused tests.
- `STAGE5_6_ACCEPTANCE.ps1` and Stage-5.6 packaging/evidence documentation.

## Changed

- Active Pentest API control is now `stage5.6-exploitation-agent` / `APTSPentestSubsystem/5.6`.
- Pentest repository migration advances from 12 to 13.
- `run/pentest_subsystem.py` identifies Stage 5.6 as the active runtime.
- Package exports/docstring include the Stage-5.6 surface.
- Successful proposal preparation marks Stage-5.1 `validation` and `exploitation` subtasks complete as **proposal-plane work**, then releases Stage-5.7 `impact_analysis`.

## Preserved boundaries

- Stage-5.1 remains local multi-agent orchestration authority.
- Stage-5.5 remains authoritative source of candidate attack paths.
- Stage-4.8 decisions remain eligibility/scope-RoE decisions, not `PolicyDecision` authorization.
- Stage-4.9 remains evidence/lineage authority.
- Stage 5.6 does not create execution requests/results or new target execution evidence.
- Stage 5.6 has no raw tool access, target-network I/O, or target actuation.
- Stage 6 remains the controlled execution plane.
