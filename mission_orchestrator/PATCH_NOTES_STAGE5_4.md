# Patch Notes — Stage 5.4 Vulnerability Hypothesis Agent

## Added

- `pentest_subsystem/vulnerability_hypothesis.py`
  - canonical Stage-5.4 contracts and definitions;
  - strict Vulnerability Hypothesis run request normalization;
  - deterministic Vulnerability Hypothesis run identity;
  - exact Stage-5.3 Enumeration predecessor identity/hash binding;
  - explicit knowledge/CTI provenance and content-hash validation;
  - deterministic evidence-backed product/version/technology/service/endpoint/target/configuration correlation;
  - integrity-bound `OPEN / UNVALIDATED` Hypothesis Model;
  - conservative knowledge/evidence confidence composition;
  - required-validation model with Stage-6 execution deferral;
  - Stage-4.9 Evidence-to-Hypothesis lineage binding;
  - explicit no-finding-before-validation semantics;
  - SHA-bound Vulnerability Hypothesis Evidence Bundle;
  - restart-safe/idempotent repository and Stage-5.1 progress handoff.
- `pentest_migrations/011_stage5_4_vulnerability_hypothesis_agent.sql`.
- Stage-5.4 HTTP routes in `pentest_subsystem/api_service.py`.
- `tests/test_stage5_4_vulnerability_hypothesis_agent.py` with 28 focused tests.
- `STAGE5_4_ACCEPTANCE.ps1` and Stage-5.4 packaging/evidence documentation.

## Changed

- Active Pentest API control is now `stage5.4-vulnerability-hypothesis-agent` / `APTSPentestSubsystem/5.4`.
- `run/pentest_subsystem.py` describes Stage 5.4 as the active runtime.
- Package exports/docstring include the Vulnerability Hypothesis Agent surface.
- Successful `vulnerability_analysis` completion now releases Stage-5.5 `attack_path_analysis` through the existing Stage-5.1 orchestration graph.

## Preserved boundaries

- Stage-5.1 remains the local multi-agent orchestration authority.
- Stage-5.3 remains the authoritative source of enumeration observations/assets.
- Stage-4.9 remains the authoritative Evidence/Hypothesis lineage foundation.
- Global Mission Orchestrator remains the global mission authority.
- Vulnerability Hypothesis specialist has no raw tool access, no direct network execution, no target actuation, and cannot mint authorization.
- Stage 5.4 does not execute vulnerability validation and does not create a confirmed `FINDING` from an unvalidated hypothesis.
- Stage 6 remains the controlled execution plane.
