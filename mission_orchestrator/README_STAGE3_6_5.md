# Stage 3.6.5 — Mission Outcome Aggregation

Stage 3.6.5 adds a **deterministic, persisted mission-level outcome snapshot** over the authoritative active Plan. It consumes the durable execution/completion evidence already established by Stages 3.6.1–3.6.4 and summarizes each active-plan task without mutating task state, advancing the Plan, or deciding Mission success.

## Purpose

The control closes the gap between per-task completion and later Mission success-criteria evaluation. For every task in the active Plan it derives exactly one classification:

- `VERIFIED_COMPLETE` — a valid Stage-3.6.4 completion commit exists for the same active Plan/task;
- `FAILED` — the Stage-3.6.1 canonical task outcome is `VERIFIED_FAILED`;
- `CANCELLED` — the canonical task outcome is `VERIFIED_CANCELLED`;
- `TIMED_OUT` — the canonical task outcome is `VERIFIED_TIMED_OUT`;
- `RUNNING` — a same-plan running projection exists and no higher-priority terminal source applies;
- `BLOCKED` — either a verified-success task has not yet reached canonical Stage-3.6.4 completion, or active-plan prerequisites are not completed;
- `PENDING` — no terminal/running source applies and the task is not dependency-blocked.

The snapshot also stores deterministic counts, `all_tasks_terminal`, `all_tasks_verified_complete`, `terminal_non_success_present`, task-level provenance, and `source_snapshot_sha256`.

## Canonical contract

- control: `stage3.6.5-mission-outcome-aggregation`
- stage schema: `apts-mission-outcome-aggregation-v1`
- contract schema: `apts-mission-outcome-aggregation-contract-v1`
- identity prefix: `moutcome-`
- persistence store: `mission_outcome_aggregations`
- migration: `040_stage3_6_5_mission_outcome_aggregation.sql`
- canonical event: `MISSION_OUTCOME_AGGREGATED`

Every aggregation is bound to the Mission, active `plan_version_record_id`, active Plan version/hash, Mission source state/version/vector hash, normalized request fingerprint, and deterministic source snapshot.

## Authority boundary

Stage 3.6.5 is an **aggregation control only**. It explicitly does **not**:

- evaluate Mission success criteria;
- decide Mission completion readiness;
- exercise Mission-success completion authority;
- release task dependencies or recalculate task readiness;
- progress/supersede a Plan;
- mutate task outcomes or completion commits;
- query Governance or runtime-control services;
- dispatch/redeliver execution work or actuate a target;
- transition Mission state.

`all_tasks_verified_complete=true` is therefore a factual aggregate, not an authorization to mark the Mission `COMPLETED`.

## API surface

- `POST /api/missions/{mission_id}/mission-outcome-aggregations`
- `GET /api/missions/{mission_id}/mission-outcome-aggregations`
- `GET /api/missions/{mission_id}/mission-outcome-aggregations/{aggregation_id}`
- `GET /api/missions/{mission_id}/mission-outcome-aggregation-definition`

Create requests use idempotency plus optimistic source/active-plan bindings. Reuse of an idempotency key with a different canonical request is rejected.

## Integrity and replay evidence

The repository integrity projection verifies the canonical contract hash, persisted scalar projection, source-state/version bindings, and a one-to-one `MISSION_OUTCOME_AGGREGATED` causation record. Database-field tampering that diverges from the canonical contract is detected.

## Tests

Focused suite: `tests/test_stage3_6_5_mission_outcome_aggregation.py` (20 tests).

Stage-3.6 chain inventory after this stage: 99 tests across Stages 3.6.1–3.6.5.

Canonical repository inventory after this stage: 1062 tests.

## Next stage

**3.6.6 — Mission Success Criteria Evaluation** consumes the Stage-3.6.5 aggregate as evidence and evaluates the Mission contract's explicit success criteria. Stage 3.6.6, not Stage 3.6.5, owns that semantic decision boundary.
