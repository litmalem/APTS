# Stage 3.6.2 — Task Terminality & Completion Eligibility

## Purpose

Stage 3.6.2 consumes the immutable `toutcome-*` artifact produced by Stage 3.6.1 and creates a deterministic, immutable `telig-*` gate that answers two narrowly scoped questions:

1. Is the task outcome terminal?
2. Is that terminal outcome eligible to proceed to the later task-completion evaluation/commit boundary?

Stage 3.6.2 deliberately **does not** accept the task outcome, evaluate domain acceptance criteria, commit task completion, transition task state, release dependencies, recalculate readiness, progress the Plan, complete the Mission, contact Governance/runtime, redispatch work, create another execution attempt, or actuate a target.

```text
Stage 3.6.1
  toutcome-*  immutable canonical task outcome
      |
Stage 3.6.2
  telig-*     deterministic terminality + completion-eligibility gate
      |
      +--> Stage 3.6.3 (later acceptance/completion boundary)
```

## Runtime identity

```text
control_version             = stage3.6.2-task-terminality-completion-eligibility
server_version              = APTSMissionOrchestrator/3.6.2
repository_migration_level  = 37
persistence_store           = mission_task_terminality_eligibility_gates
next_stage                  = 3.6.3
```

## Deterministic classification matrix

| Stage-3.6.1 source status | Terminality | Completion eligibility | completion_eligible |
|---|---|---|---|
| `VERIFIED_COMPLETED` | `TERMINAL_SUCCESS` | `ELIGIBLE_FOR_COMPLETION_EVALUATION` | `true` |
| `VERIFIED_FAILED` | `TERMINAL_FAILURE` | `NOT_ELIGIBLE_FOR_COMPLETION` | `false` |
| `VERIFIED_CANCELLED` | `TERMINAL_CANCELLED` | `NOT_ELIGIBLE_FOR_COMPLETION` | `false` |
| `VERIFIED_TIMED_OUT` | `TERMINAL_TIMED_OUT` | `NOT_ELIGIBLE_FOR_COMPLETION` | `false` |

The classification is a local deterministic projection of the immutable Stage-3.6.1 artifact. A caller cannot supply or override terminality or eligibility values.

## Canonical contract

Implementation:

```text
mission_orchestrator/task_terminality.py
```

Canonical constants:

```text
stage_schema_version = apts-task-terminality-completion-eligibility-v1
schema_version       = apts-task-terminality-completion-eligibility-contract-v1
identity_prefix      = telig-
mode                 = DETERMINISTIC_LOCAL_TERMINALITY_AND_COMPLETION_ELIGIBILITY_NO_COMPLETION_COMMIT
authority            = MISSION_ORCHESTRATOR_TASK_TERMINALITY_COMPLETION_ELIGIBILITY
gate_status          = EVALUATED
```

The `telig-*` contract binds the current Mission state/version, active `pver-*` Plan version, exact `toutcome-*` identity and SHA-256, source terminal status, and outcome classification. The gate is integrity-protected with a canonical SHA-256.

## Invariants

Stage 3.6.2 enforces:

```text
one immutable telig-* gate per Stage-3.6.1 task outcome
one idempotency request identity per (mission_id, idempotency_key)
active Plan head must still match the toutcome-* source
Mission state/version must still match the toutcome-* source
exactly one MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED event per telig-* causation id
```

Exact replay of the same canonical request returns the same `telig-*` artifact with `idempotent_replay=true`. Reusing an idempotency key with different canonical content fails closed.

## Authority boundary

The following distinctions are explicit:

```text
TERMINALITY CONFIRMED          != TASK OUTCOME ACCEPTED
COMPLETION ELIGIBLE            != TASK COMPLETED
COMPLETION ELIGIBLE            != TASK STATE TRANSITION
COMPLETION ELIGIBLE            != DEPENDENCY RELEASE
COMPLETION ELIGIBLE            != PLAN PROGRESSION
COMPLETION ELIGIBLE            != MISSION COMPLETION
```

The Stage-3.6.2 contract records these as `false`:

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

## Persistence

Migration:

```text
migrations/037_stage3_6_2_task_terminality_completion_eligibility.sql
```

New durable store:

```text
mission_task_terminality_eligibility_gates
```

Important uniqueness constraints protect the gate identity, `(mission_id, idempotency_key)`, `(mission_id, task_outcome_id)`, and `(mission_id, plan_version, planned_task_id)`.

Repository integrity verification includes `task_terminality_completion_eligibility_store` and cross-checks the persisted gate against its Stage-3.6.1 source, active Plan record, deterministic classification, and exactly-once lineage event.

## API surface

```text
POST /api/missions/{mission_id}/task-terminality-eligibility
GET  /api/missions/{mission_id}/task-terminality-eligibility
GET  /api/missions/{mission_id}/task-terminality-eligibility/{eligibility_gate_id}
GET  /api/missions/{mission_id}/task-terminality-eligibility-definition
```

## Event lineage

New event:

```text
MISSION_TASK_TERMINALITY_COMPLETION_ELIGIBILITY_EVALUATED
```

Its `causation_id` is the `telig-*` gate identity.

## Test coverage

`tests/test_stage3_6_2_task_terminality_completion_eligibility.py` adds 20 focused tests covering runtime identity, contract declaration, deterministic classification, source bindings, strict authority boundaries, stale-state/hash rejection, missing-source fail-closed behavior, forbidden caller fields, idempotency, one-gate-per-outcome uniqueness, no Governance/runtime I/O, durable restart behavior, exactly-once lineage, repository integrity/tamper detection, API/migration registration, and the complete four-status classification matrix.

Canonical inventory after this stage: **1002 tests**.
