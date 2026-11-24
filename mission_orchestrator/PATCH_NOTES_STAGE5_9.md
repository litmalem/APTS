# Patch Notes — Stage 5.9 Governance-Bound Multi-Agent Pentest E2E

## Added

- `pentest_subsystem/governance_bound_e2e.py` implementing the complete non-executing Stage-5 E2E assurance trajectory.
- Seven roadmap scenarios: success, denied action, stale intelligence, target outside scope, agent failure, conflicting evidence, and partial results.
- SHA-bound `Pentest E2E evidence`, deterministic run identity, idempotency, restart recovery, and tamper detection.
- Reuse of Stage-5.8 authoritative shared state, agent handoffs, cross-agent feedback, and deterministic local replanning.
- Fail-closed governance control-plane probes for denied-action and out-of-scope-target scenarios.
- `pentest_migrations/016_stage5_9_governance_bound_multi_agent_pentest_e2e.sql`.
- Stage-5.9 HTTP contract/run/list/get routes and active handler.
- `tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py` with 21 focused tests.
- `STAGE5_9_ACCEPTANCE.ps1` and Stage-5.9 package/evidence files.

## Changed

- Active Pentest control: `stage5.9-governance-bound-multi-agent-pentest-e2e`.
- Active HTTP server signature: `APTSPentestSubsystem/5.9`.
- Pentest repository migration: 15 → 16.
- Canonical test inventory: 2009 → 2030.
- `run/pentest_subsystem.py` identifies Stage 5.9 as active.
- Package exports/docstring expose Stage-5.9 contracts, repository, service, scenarios, and evidence verifier.

## Preserved authority boundaries

- Stage 5 remains the decision/proposal/coordination plane.
- Stage 5.9 E2E scenario injection is control-plane-only and accepts no arbitrary command/payload/target fields.
- Stage 4.8 remains scope/RoE governance authority for local eligibility semantics.
- Stage 5.8 remains authoritative shared-state/feedback/replanning implementation.
- Stage 5.9 does not create execution requests, action results, target evidence, confirmed findings, or authorizations.
- Stage 6 remains controlled execution and target-evidence authority.
