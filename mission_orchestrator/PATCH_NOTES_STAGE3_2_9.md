# Patch Notes — Stage 3.2.9 Event-Driven Lifecycle Automation & Reliability

## Added

- New module `mission_orchestrator/mission_lifecycle_automation.py`.
- Lifecycle automation schema `apts-mission-lifecycle-automation-v1`.
- Typed event-to-command mapping for PIP binding, planning/run activation, waiting dependencies, pause/resume, replanning, cleanup/completion, and terminal controls.
- Exact `observed_state + observed_state_version + observed_version_sha256` event binding.
- Deterministic generated lifecycle command IDs/idempotency keys derived from source event identity.
- Canonical source-event SHA-256 fingerprint conflict detection.
- Durable event outcomes:
  - `MISSION_LIFECYCLE_EVENT_RECEIVED`;
  - `MISSION_LIFECYCLE_EVENT_APPLIED`;
  - `MISSION_LIFECYCLE_EVENT_REJECTED`.
- Durable exact replay for applied events and durable no-re-evaluation replay for rejected events.
- `GET /api/missions/{mission_id}/lifecycle-automation-contract`.
- `POST /api/missions/{mission_id}/lifecycle/events`.
- Lifecycle automation contract embedded in lifecycle command discovery.
- Stage-3.2.9 health/authority/reliability fields.
- Twenty-one Stage-3.2.9 regression tests.
- `STAGE3_2_9_ACCEPTANCE.ps1`.

## Changed

- Current control advances to `stage3.2.9-event-driven-lifecycle-automation-reliability`.
- HTTP server identity advances to `APTSMissionOrchestrator/3.2.9`.
- Canonical Mission event vocabulary now includes received/applied/rejected lifecycle-automation events.
- Prior current-control regression assertions advance from Stage 3.2.8 to Stage 3.2.9 while retaining Stage 3.2.8 as historical supported control.

## Preserved

- Canonical lifecycle topology and optimistic state transitions.
- Stage-3.1.6 command journal as the mutation/idempotency authority.
- Stage-3.1.9 append-only hash-chained Mission event ledger.
- Stage-3.2.2 lifecycle guard matrix.
- Stage-3.2.3 PIP activation semantics.
- Stage-3.2.4 planning/run activation semantics.
- Stage-3.2.5 waiting evidence/approval semantics.
- Stage-3.2.6 pause/resume/replanning semantics.
- Stage-3.2.7 abort/failure/expiration semantics.
- Stage-3.2.8 cleanup and verified-completion gate.
- `EXTERNAL_APTS_GSS` as Governance authorization authority.
- No planner invocation from Mission lifecycle automation.
- No target action dispatch or target actuation.
- Repository migration level 8.

## Reliability behavior

- A late event with stale state/version/hash is rejected before state mutation.
- Exact event replay does not duplicate state transitions, command completion events, or automation outcomes.
- A previously rejected event is not reinterpreted merely because the Mission later moves to another state.
- Reuse of one `(source_component, event_id)` with different canonical content fails as a conflict.
- Event automation uses existing lifecycle guards instead of bypassing them.

## Regression

- Previous baseline: `234 passed`.
- Stage-3.2.9 tests added: `21`.
- New baseline: `255 passed`.
