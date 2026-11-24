# Stage 3.9.7 patch notes

- Added the read-only **Adaptation / Replanning E2E Scenario** qualification contract,
  evaluator, health fields, and two GET routes.
- Extended the canonical Stage 3.9.6 blocked-completion head through the existing
  Stage 3.7.1–3.7.8 adaptation/replanning authorities; no new replanning authority
  or durable store is introduced.
- Binds the exact Stage 3.9.6 `MISSION_COMPLETION_READINESS_EVALUATED` event as an
  `EVIDENCE_CHANGE` adaptation trigger and classifies it as `PLAN_STALE`, severity
  `MEDIUM`, with `LEVEL_3_PARTIAL_PLAN` scope.
- Requires authoritative Governance `ALLOW`, binds an immutable replan snapshot,
  deterministically removes the already-completed `collect-cti` root task, and
  preserves the unfinished `analyze-cti -> report-findings` remainder DAG.
- Validates the candidate before authoritative commit and atomically advances the
  plan head from Plan v1 to **Plan v2**, while mission lifecycle state remains
  `RUNNING(v4)`.
- Produces `HANDOFF_READY` to `STAGE3_4_ROUTING_THEN_STAGE3_5_DISPATCH` but
  deliberately stops before new routing, dispatch, execution, or target actuation.
- Leaves Stage 3.7.9 recovery checkpoint creation to Stage 3.9.8 Restart / Replay /
  Recovery, preserving the intended E2E stage boundary.
- Canonical trajectory is **49 Mission events**, of which the Stage 3.9.7 replan
  segment is exactly **9 events**.
- Extended the canonical Stage 3.9.4 scope with `INTERNAL_REASONING` so the
  pre-existing Stage 3.7 Governance-bound replanning authorities can be exercised
  without inventing a Stage 3.9.7 scope mutation.
- Added 16 focused tests covering positive continuity, exact footprint, source-event
  binding, deterministic remainder-DAG construction, atomic plan-head advance,
  read-only qualification, idempotent replay, partial/stale/tamper rejection,
  restart reconstruction, HTTP routes, and the Stage 3.9.8 handoff boundary.
- Rebases historical active-control/server-version assertions to Stage 3.9.7 while
  preserving Stage 3.9.6 in the ordered `supported_controls` chain.
- Repository migration remains **53**.
