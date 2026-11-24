# Stage 3.6.1 — Canonical Task Outcome Contract & Identity

## Purpose

Stage 3.6.1 opens **Stage 3.6 — Task Outcome Acceptance & Plan Progression** by materializing a canonical, immutable identity for the outcome of one planned task after the Stage-3.5 execution trajectory has already reached a verified terminal condition.

The new `toutcome-*` record does **not** accept the task, commit task completion, release dependencies, recalculate readiness, advance the Plan, complete the Mission, contact Governance/runtime, redispatch work, create a new execution attempt, or actuate the target. Those boundaries remain reserved for later Stage-3.6 controls.

The stage establishes a durable bridge from execution evidence to task-level semantics:

```text
Stage 3.5 terminal execution trajectory
  xattempt-*  execution attempt
      |
  xresult-*   terminal result + evidence/artifacts
      |
  xprop-*     verified terminal outcome propagation
      |
  xrecover-*  durable execution recovery checkpoint
      |
Stage 3.6.1
  toutcome-*  canonical immutable task-outcome identity
      |
      +--> pending task-outcome acceptance (Stage 3.6.2)
```

## Runtime identity

```text
control_version             = stage3.6.1-canonical-task-outcome-contract-identity
server_version              = APTSMissionOrchestrator/3.6.1
repository_migration_level  = 36
persistence_store           = mission_task_outcomes
next_stage                  = 3.6.2
```

## Canonical contract identity

Implementation:

```text
mission_orchestrator/task_outcome.py
```

Canonical constants:

```text
stage_schema_version = apts-task-outcome-contract-identity-v1
schema_version       = apts-canonical-task-outcome-contract-v1
identity_prefix      = toutcome-
mode                 = IMMUTABLE_TASK_OUTCOME_IDENTITY_BOUND_TO_VERIFIED_TERMINAL_EXECUTION_PENDING_ACCEPTANCE
authority            = MISSION_ORCHESTRATOR_TASK_OUTCOME_MATERIALIZATION
contract_status      = MATERIALIZED_PENDING_TASK_OUTCOME_ACCEPTANCE
```

Allowed source Mission states:

```text
RUNNING
FAILED
ABORTED
```

Allowed canonical Stage-3.5 task-outcome statuses:

```text
VERIFIED_COMPLETED
VERIFIED_FAILED
VERIFIED_CANCELLED
VERIFIED_TIMED_OUT
```

## Source bindings

A `toutcome-*` contract is materialized only when the current Mission state/version, active Plan head, and exact Stage-3.5 terminal artifact chain are still current and integrity-valid.

The contract binds:

```text
Mission version vector / source state
active pver-* Plan version
xattempt-* Stage-3.5.4 execution attempt
xresult-*  Stage-3.5.7 terminal result capture
xprop-*    Stage-3.5.8 verified outcome propagation
xrecover-* Stage-3.5.9 recovery checkpoint
result evidence-manifest hash
result artifact-manifest hash
```

Each binding carries canonical SHA-256 evidence. Materialization fails closed on stale version vectors, stale active Plan hashes, mismatched terminal artifacts, missing recovery checkpoints, broken source integrity, or a non-contiguous execution lineage.

## Identity and idempotency invariants

Stage 3.6.1 enforces:

```text
one immutable toutcome-* identity per (mission_id, plan_version, planned_task_id)
one idempotency request identity per (mission_id, idempotency_key)
one use of a given xprop-* terminal propagation per Mission
one use of a given xrecover-* checkpoint per Mission
exactly one MISSION_TASK_OUTCOME_MATERIALIZED event per toutcome-* causation id
```

A replay of the exact same canonical request returns the existing `toutcome-*` identity with `idempotent_replay=true`; it does not create a duplicate outcome or event. Reusing the same idempotency key with different request content fails with conflict.

## Authority boundary

The most important semantic separation is:

```text
EXECUTION RESULT              != TASK OUTCOME IDENTITY
TASK OUTCOME IDENTITY         != TASK OUTCOME ACCEPTANCE
TASK OUTCOME IDENTITY         != TASK COMPLETION COMMIT
TASK OUTCOME IDENTITY         != DEPENDENCY RELEASE
TASK OUTCOME IDENTITY         != PLAN PROGRESSION
TASK OUTCOME IDENTITY         != MISSION COMPLETION
```

The Stage-3.6.1 contract explicitly records all of the following as `false`:

```text
task_outcome_acceptance_performed
acceptance_criteria_evaluation_performed
task_completion_commit_performed
task_state_transition_performed
dependency_release_performed
readiness_recalculation_performed
plan_progression_performed
mission_success_completion_authority_exercised

governance_query_performed
runtime_query_performed
runtime_control_io_performed
dispatch_redelivery_performed
new_execution_attempt_created
new_target_action_dispatch_performed
external_network_io_performed
target_actuation
mission_state_transition_performed
```

This makes Stage 3.6.1 a **materialization boundary**, not an acceptance or execution boundary.

## Persistence

Migration:

```text
migrations/036_stage3_6_1_canonical_task_outcome_contract_identity.sql
```

New durable store:

```text
mission_task_outcomes
```

The table stores canonical identity, plan/task bindings, Stage-3.5 terminal artifact identities and hashes, request/idempotency data, source state/version, canonical JSON, and canonical SHA-256.

Important uniqueness constraints protect:

- `task_outcome_id`;
- `(mission_id, idempotency_key)`;
- `(mission_id, plan_version, planned_task_id)`;
- `(mission_id, outcome_propagation_id)`;
- `(mission_id, execution_recovery_checkpoint_id)`.

Repository integrity verification includes the `canonical_task_outcome_store` and verifies both persisted contracts and their exactly-once lineage events.

## API surface

Stage 3.6.1 adds:

```text
POST /api/missions/{mission_id}/task-outcomes
GET  /api/missions/{mission_id}/task-outcomes
GET  /api/missions/{mission_id}/task-outcomes/{task_outcome_id}
GET  /api/missions/{mission_id}/task-outcome-definition
```

The POST request is deliberately narrow. It accepts only identity/version/hash expectations, idempotency metadata, creator, reason, and caller metadata. Caller-supplied fields attempting to choose outcome status, task acceptance, completion, dependency release, Mission completion, runtime action, Governance decision, dispatch, or actuation are rejected.

## Event lineage

New canonical event:

```text
MISSION_TASK_OUTCOME_MATERIALIZED
```

Its `causation_id` is the `toutcome-*` identity. Event payload includes the canonical hash and records the non-authorizing Stage-3.6.1 boundary (`task_outcome_acceptance_performed=false`, `task_completion_commit_performed=false`, `dependency_release_performed=false`).

## Test coverage

`tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py` adds 19 focused tests covering:

1. runtime identity and migration 36;
2. canonical definition and exact Stage-3.5 prerequisites;
3. immutable `toutcome-*` materialization;
4. binding to the exact Stage-3.5 terminal trajectory;
5. no acceptance/completion/release/progression side effects;
6. stale Mission version rejection;
7. stale active Plan hash rejection;
8. stale terminal artifact rejection;
9. missing recovery checkpoint fail-closed behavior;
10. rejection of caller-supplied acceptance/completion/side-effect fields;
11. idempotent replay and exactly-once event behavior;
12. idempotency conflict detection;
13. one immutable outcome identity per Plan task;
14. no runtime or Governance contact during materialization/replay;
15. restart persistence of the same immutable identity;
16. causal event binding;
17. repository projection/integrity coverage;
18. tamper detection;
19. API, migration, definition, and history registration.

Package-construction verification:

```text
python -m compileall -q mission_orchestrator tests                     PASS
python -m pytest --collect-only -q                                    982 tests
python -m pytest -q tests/test_stage3_6_1_...py                        19 passed
python -m pytest -q tests/test_stage3_5_10_...py                       12 passed
```

The complete 982-test regression must be rerun on the target host by `STAGE3_6_1_ACCEPTANCE.ps1` before Stage 3.6.1 is declared accepted there.

## Next boundary

Stage 3.6.1 intentionally leaves the `toutcome-*` contract in:

```text
MATERIALIZED_PENDING_TASK_OUTCOME_ACCEPTANCE
```

The next implementation boundary is **Stage 3.6.2 — Task Outcome Acceptance & Completion Eligibility Gate**. Stage 3.6.2 may evaluate whether the immutable outcome satisfies the task's completion/acceptance contract; Stage 3.6.1 itself must never pre-empt that authority.
