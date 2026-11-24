# Patch Notes — Stage 5.8 Cross-Agent Feedback, Shared State & Replanning

## Added

- `pentest_subsystem/cross_agent_feedback.py` with:
  - canonical Stage-5.8 contract;
  - versioned authoritative shared-state projection;
  - deterministic shared-state identity/source fingerprint;
  - agent-handoff contract and persistence;
  - evidence-bound, ownership-checked cross-agent feedback;
  - deterministic local replan decisions;
  - governance escalation and Stage-6 deferral;
  - SHA integrity, idempotency, restart recovery, and fail-closed checks.
- `pentest_migrations/015_stage5_8_cross_agent_feedback_shared_state_replanning.sql`.
- Stage-5.8 API routes and active handler in `pentest_subsystem/api_service.py`.
- `tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py` with 24 focused tests.
- `STAGE5_8_ACCEPTANCE.ps1` and Stage-5.8 package/evidence files.

## Changed

- Active Pentest control: `stage5.8-cross-agent-feedback-shared-state-replanning`.
- Active HTTP server signature: `APTSPentestSubsystem/5.8`.
- Pentest repository migration: 14 → 15.
- Canonical test inventory: 1985 → 2009.
- `run/pentest_subsystem.py` identifies Stage 5.8 as active.
- package exports/docstring expose the Stage-5.8 contracts and service.

## Preserved authority boundaries

- Stage 5.1 remains authoritative owner of the active local orchestration plan.
- Stage 5.2–5.7 remain authoritative owners of their specialist artifacts.
- Stage 5.8 derives shared state; callers cannot directly inject shared facts/evidence/findings.
- Stage 4.8 remains scope/RoE eligibility enforcement; Stage 5.8 cannot mint authorization.
- Stage 5.8 local replanning is projection-only and does not auto-run specialists.
- Stage 6 remains controlled execution and target-evidence authority.
