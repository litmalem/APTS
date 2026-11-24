# Stage 3.6.7 — Completion Readiness & Blockers

Stage 3.6.7 adds a deterministic, immutable, fail-closed Mission-completion readiness decision. It consumes one exact Stage-3.6.6 success-criteria evaluation from the current active Plan, binds the current Mission lifecycle/version vector, and derives an explicit blocker set. It **does not** transition Mission state or exercise Mission-success completion authority.

## Canonical identity

- control: `stage3.6.7-completion-readiness-blockers`
- server: `APTSMissionOrchestrator/3.6.7`
- stage schema: `apts-mission-completion-readiness-blockers-v1`
- contract schema: `apts-mission-completion-readiness-blockers-contract-v1`
- identity prefix: `mready-`
- migration: `042_stage3_6_7_completion_readiness_blockers.sql`
- store: `mission_completion_readiness_decisions`
- event: `MISSION_COMPLETION_READINESS_EVALUATED`

## Readiness semantics

A decision is either `READY` or `BLOCKED`. `READY` is possible only when no blocker is derived. The stage fails closed and exposes deterministic blockers including lifecycle-state mismatch, success criteria not satisfied/indeterminate, non-terminal tasks, missing verified completion, and terminal non-success outcomes.

Stage 3.6.7 never guesses the meaning of arbitrary success criteria. It trusts the immutable Stage-3.6.6 criterion-level evaluation and consumes only its evidence-bound result and supported observations.

## Authority boundary

Stage 3.6.7 decides readiness only. It does not transition the Mission, mark it completed, progress/supersede the Plan, release dependencies, re-dispatch work, query Governance/runtime services, perform external network I/O, or actuate targets. The actual successful Mission terminal transition remains reserved for a later stage.

## API

- `POST /api/missions/{mission_id}/completion-readiness-decisions`
- `GET /api/missions/{mission_id}/completion-readiness-decisions`
- `GET /api/missions/{mission_id}/completion-readiness-decisions/{readiness_id}`
- `GET /api/missions/{mission_id}/completion-readiness-definition`

Create requests bind optimistic Mission state/version, the active Plan head, and one exact Stage-3.6.6 evaluation id/hash. Idempotency-key reuse with a different canonical request is rejected.

## Verification status in this build

- Python module compilation: PASS.
- Canonical pytest inventory collection: **1102 tests**.
- Focused Stage-3.6.7 suite: **20 passed**.
- Full host regression remains authoritative through `STAGE3_6_7_ACCEPTANCE.ps1`.

## Next stage

Stage **3.6.8** should consume a `READY` decision and implement the explicitly governed Mission-success completion transition/commit while preserving the fail-closed authority boundary.
