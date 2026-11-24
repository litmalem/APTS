# Patch Notes — Stage 5.5 Attack-Path Planning Agent

## Added

- `pentest_subsystem/attack_path_planning.py`
  - canonical Stage-5.5 contract and definitions;
  - strict Attack-Path Planning run-request normalization;
  - deterministic run identity;
  - exact Stage-5.4 hypothesis-run/output/evidence hash binding;
  - four-stage conditional candidate-path model;
  - evidence-bound Attack-Path Graph;
  - deterministic validation-priority ranking;
  - path provenance binding hypothesis, knowledge, evidence, enumerated-asset integrity, and predecessor hashes;
  - explicit no-execution/no-finding/no-execution-request semantics;
  - SHA-bound Stage-5.5 evidence bundle;
  - restart-safe/idempotent repository and Stage-5.1 progress handoff.
- `pentest_migrations/012_stage5_5_attack_path_planning_agent.sql`.
- Stage-5.5 HTTP routes in `pentest_subsystem/api_service.py`.
- `tests/test_stage5_5_attack_path_planning_agent.py` with 28 focused tests.
- `STAGE5_5_ACCEPTANCE.ps1` and Stage-5.5 packaging/evidence documentation.

## Changed

- Active Pentest API control is now `stage5.5-attack-path-planning-agent` / `APTSPentestSubsystem/5.5`.
- Pentest repository migration advances from 11 to 12.
- `run/pentest_subsystem.py` describes Stage 5.5 as the active runtime.
- Package exports/docstring include the Attack-Path Planning Agent surface.
- Successful `attack_path_analysis` completion now releases the Stage-5.6 `validation` subtask through the existing Stage-5.1 orchestration graph.

## Preserved boundaries

- Stage-5.1 remains the local multi-agent orchestration authority.
- Stage-5.4 remains the authoritative source of vulnerability hypotheses.
- Stage-4.9 remains the evidence/lineage foundation.
- Global Mission Orchestrator remains global mission authority.
- The Stage-5.5 planner has no raw tool access, no direct target-network execution, no target actuation, and cannot mint authorization.
- Candidate paths are not treated as confirmed reachability or exploitability.
- Stage 5.5 does not validate hypotheses, create confirmed findings, or create execution requests.
- Stage 6 remains the controlled execution plane.
