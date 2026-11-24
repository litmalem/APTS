# Patch Notes — Stage 5.7 Post-Exploitation & Impact Agent

## Added

- `pentest_subsystem/post_exploitation_impact.py`
  - canonical Stage-5.7 contract and definition;
  - strict post-exploitation impact request;
  - deterministic `imprun-*` identity;
  - exact Stage-5.6 run/output/evidence hash binding;
  - Stage-5.5 attack-path provenance verification;
  - roadmap-complete `ImpactAnalysis` projection;
  - provisional `PostValidationFinding` artifacts;
  - explicit evidence-sufficiency and stop-condition semantics;
  - operator-declared business criticality context;
  - SHA-bound Stage-5.7 output/evidence bundle;
  - idempotent/restart-safe repository persistence;
  - Stage-5.1 `impact_analysis` completion handoff.
- `pentest_migrations/014_stage5_7_post_exploitation_impact_agent.sql`.
- Stage-5.7 HTTP routes and active handler in `pentest_subsystem/api_service.py`.
- `tests/test_stage5_7_post_exploitation_impact_agent.py` with 28 focused tests.
- `STAGE5_7_ACCEPTANCE.ps1` and Stage-5.7 packaging/evidence documentation.

## Changed

- Active Pentest API control is now `stage5.7-post-exploitation-impact-agent` / `APTSPentestSubsystem/5.7`.
- Pentest repository migration advances from 13 to 14.
- `run/pentest_subsystem.py` identifies Stage 5.7 as the active runtime.
- Package exports/docstring include the Stage-5.7 surface.
- Successful Stage-5.7 analysis marks Stage-5.1 `impact_analysis` complete, completing the current seven-specialist Stage-5 task graph and handing control toward Stage 5.8 shared-state/feedback/replanning.

## Preserved boundaries

- Stage-5.1 remains local multi-agent orchestration authority.
- Stage-5.6 remains authoritative source of exploitation/validation proposals.
- Stage-5.5 remains authoritative source of attack-path provenance.
- Stage-4.8 decisions remain scope/RoE eligibility, not `PolicyDecision` authorization.
- Stage-4.9 remains evidence/lineage foundation; Stage-5.7 provisional findings are not confirmed `FINDING` records.
- Stage 5.7 does not create execution requests/results or new target execution evidence.
- Stage 5.7 has no raw tool access, target-network I/O, target actuation, credential extraction, or lateral-movement execution.
- Stage 6 remains the controlled execution and target-evidence authority.
