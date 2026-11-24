# Stage 3.9.6 patch notes

- Added the read-only **Task Completion → Mission Outcome Closure** qualification
  contract, evaluator, health fields, and two GET routes.
- Extended the canonical Stage 3.9.5 head through existing Stage 3.5.8, 3.5.9,
  and Stage 3.6.1–3.6.7 authorities, producing the exact 40-event trajectory.
- Bound terminal `SUCCEEDED` execution evidence through recovery checkpoint,
  canonical task outcome, terminality eligibility, evidence verification, and
  dependency-aware task completion.
- Added mission aggregation, success-criteria evaluation, and fail-closed
  completion-readiness qualification. The canonical result is intentionally
  `BLOCKED` because two active-Plan tasks remain.
- Explicitly prevents premature Stage 3.6.8 verified completion, Stage 3.6.9
  outcome-recovery closure, or mission lifecycle transition; the mission remains
  `RUNNING(v4)` and hands off to Stage 3.9.7 Adaptation & Replanning.
- Added 15 focused tests covering positive continuity, exact footprint,
  idempotency, stale/partial/tamper rejection, restart, HTTP, and authority
  boundaries.
- Rebases historical active-control/server-version assertions to Stage 3.9.6 and
  preserves Stage 3.9.5 in the ordered `supported_controls` chain.
- Repository migration remains 53. No new durable store or completion authority
  is introduced.
