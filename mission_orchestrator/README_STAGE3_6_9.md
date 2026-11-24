# Stage 3.6.9 — Outcome Lineage, Replay & Recovery

Stage 3.6.9 closes the durable outcome-traceability layer for the Stage-3.6 completion pipeline. It reconstructs the canonical Mission outcome trajectory from the persisted Stage-3.6.1 through Stage-3.6.8 evidence chain and the verified Mission event ledger, exposes a deterministic read-only outcome replay, and persists an immutable restart/recovery checkpoint without re-executing work, re-dispatching a target action, querying Governance/runtime services, or changing Mission lifecycle state.

## Runtime identity

- control: `stage3.6.9-outcome-lineage-replay-recovery`
- server: `APTSMissionOrchestrator/3.6.9`
- repository migration level: `44`
- migration: `044_stage3_6_9_outcome_lineage_replay_recovery.sql`
- durable store: `mission_outcome_recovery_checkpoints`
- recovery checkpoint prefix: `orecover-`
- lineage schema: `apts-outcome-event-lineage-v1`
- replay schema: `apts-outcome-event-replay-v1`
- recovery schema: `apts-outcome-recovery-checkpoint-v1`
- recovery event: `MISSION_OUTCOME_RECOVERY_CHECKPOINTED`
- allowed recovery Mission state: `COMPLETED`

## Canonical outcome lineage

The Stage-3.6.9 lineage is a bounded subchain of canonical Mission events. Before a Stage-3.6.9 checkpoint exists, the expected completion trajectory is:

1. `MISSION_TASK_OUTCOME_MATERIALIZED`
2. `MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED`
3. `MISSION_TASK_EVIDENCE_BINDING_VERIFIED`
4. `MISSION_TASK_COMPLETION_COMMITTED`
5. `MISSION_OUTCOME_AGGREGATED`
6. `MISSION_SUCCESS_CRITERIA_EVALUATED`
7. `MISSION_COMPLETION_READINESS_EVALUATED`
8. `MISSION_VERIFIED_COMPLETION_DECLARED`
9. `MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED`
10. `MISSION_OUTCOME_RECOVERY_CHECKPOINTED` after checkpoint creation.

The recovery checkpoint binds the exact Stage-3.6.8 verified-completion declaration and recursively verifies its Stage-3.6.7 readiness decision, Stage-3.6.6 success-criteria evaluation, Stage-3.6.5 mission-outcome aggregation, and the per-task Stage-3.6.1/3.6.2/3.6.3/3.6.4 chain. Every referenced artifact remains subject to its canonical hash verifier and repository-integrity checks.

## Deterministic read-only replay

`GET .../outcome-replay` produces a stable ordered projection of only the Stage-3.6 outcome event types. The projection carries event identity, causation, state/plan/policy observations, artifact identity/hash, event hash, previous-event hash, timestamp, event count, replay hash, and the current outcome-event tip.

Replay is explicitly observational. It is not execution, dispatch, runtime resumption, Governance authorization, lifecycle transition, or LLM reinterpretation. Calling replay repeatedly against unchanged repository state must produce the same replay projection and must create no events or side effects.

## Durable recovery checkpoint

`POST .../outcome-recovery-checkpoints` is fail-closed. The caller must bind the request to the current Mission version hash/state version, active Plan head, Stage-3.6.8 declaration id/hash, and current outcome-event count/tip hash. Stage 3.6.9 then reconstructs the completion state exclusively from durable canonical repository records and verifies that the Mission remains `COMPLETED`.

The resulting `orecover-*` checkpoint is immutable and self-verifying. One checkpoint is permitted per verified-completion declaration. The same idempotency request returns the original checkpoint; changing the request while reusing the key is a conflict. A restarted service can read and verify the same checkpoint directly from the repository without Governance/runtime calls, dispatch redelivery, new execution attempts, target actions, or lifecycle mutations.

## Authority boundary

Stage 3.6.9 is a reconstruction/audit/recovery control, not an action authority. It performs none of the following:

- execution or re-execution;
- dispatch or redispatch;
- runtime resume/control I/O;
- Governance authorization/query;
- external network I/O;
- new execution-attempt creation;
- new target-action dispatch;
- Mission lifecycle transition;
- Mission-success completion authority;
- target actuation;
- LLM reinterpretation of persisted evidence.

These negative guarantees are exposed in health metadata and verified by focused tests.

## API surface

- `GET /api/missions/{mission_id}/outcome-lineage`
- `GET /api/missions/{mission_id}/outcome-replay`
- `GET /api/missions/{mission_id}/outcome-recovery`
- `POST /api/missions/{mission_id}/outcome-recovery-checkpoints`
- `GET /api/missions/{mission_id}/outcome-recovery-checkpoints`
- `GET /api/missions/{mission_id}/outcome-recovery-checkpoints/{checkpoint_id}`
- `GET /api/missions/{mission_id}/outcome-lineage-definition`

## Verification baseline

- canonical pytest inventory: **1144 tests**
- focused Stage-3.6.9 suite: **22 tests**
- Stage-3.6.1 through Stage-3.6.9 chain inventory: **181 tests**
- Python compile gate: `python -m compileall -q mission_orchestrator tests`
- build-environment isolated regression: **59/59 files; 1144/1144 tests PASS**
- Stage-3.6.1 through Stage-3.6.9 chain: **181/181 PASS**
- focused Stage-3.6.9: **22/22 PASS**
- acceptance entry point: `STAGE3_6_9_ACCEPTANCE.ps1`

The next planned control is **Stage 3.6.10 — Outcome Acceptance / Regression Gate**.
