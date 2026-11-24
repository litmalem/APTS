# Stage 3.9.5 patch notes

- Added the read-only Dispatch → Execution → Evidence qualification contract,
  evaluator, health contract fields, and two GET routes.
- Qualified an actual Stage 3.9.4 canonical handoff through the existing
  lifecycle and Stage 3.5.1–3.5.7 APIs with one fresh Stage 3.5.3 Governance
  decision; correlated seven execution artifacts with Stage 3.5.9 event replay.
- Added focused positive, denial, stale-input, missing-evidence, tamper,
  idempotency, restart, and HTTP tests.
- Rebases historical test assertions for the active control and server version;
  preserves all earlier controls in `supported_controls`.
- No migration beyond 53, new store, new external authority, or task/mission
  completion action. Stage 3.9.6 remains the completion and outcome handoff.
