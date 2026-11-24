# Stage 3.2.2 — Lifecycle Transition Guard Matrix

Stage 3.2.2 strengthens **3.2 — Control Mission Lifecycle** by placing a deterministic, local, fail-closed guard matrix in front of Stage-3.2 lifecycle-command transitions.

## Guard contract

Schema: `apts-mission-lifecycle-guard-matrix-v1`

Mode: `DETERMINISTIC_LOCAL_PRECONDITION_FAIL_CLOSED`

Applies to: `LIFECYCLE_COMMAND`

Each lifecycle command is evaluated against three explicit checks before the canonical transition is committed:

1. `SOURCE_STATE_ALLOWED_FOR_COMMAND`
2. `CANONICAL_TARGET_TOPOLOGY_LEGAL`
3. `PIP_BINDING_COMPLETE_WHEN_REQUIRED`

Stage 3.2.2 does not replace the Stage-3.1.2 canonical state machine. Canonical topology remains authoritative. The new matrix adds command semantics and local prerequisites on top of that topology.

## Semantic source-state matrix

| Command | Allowed source states |
|---|---|
| `BIND_PIP` | `CREATED` |
| `START_PLANNING` | `PIP_BOUND` |
| `START` | `PLANNING`, `WAITING_EVIDENCE`, `WAITING_APPROVAL`, `REPLANNING` |
| `WAIT_FOR_EVIDENCE` | `PLANNING`, `RUNNING`, `REPLANNING` |
| `WAIT_FOR_APPROVAL` | `PLANNING`, `RUNNING`, `REPLANNING` |
| `PAUSE` | non-terminal operational states except `CLEANING_UP` |
| `RESUME` | `PAUSED` |
| `REPLAN` | `RUNNING`, `WAITING_EVIDENCE`, `WAITING_APPROVAL` |
| `BEGIN_CLEANUP` | `RUNNING`, `PAUSED` |
| `COMPLETE` | `CLEANING_UP` |
| `ABORT`, `FAIL`, `EXPIRE` | every non-terminal state |

This intentionally distinguishes **topology legality** from **lifecycle intent**. For example, `PAUSED -> RUNNING` is topologically legal, but `START` is rejected from `PAUSED`; the semantically correct command is `RESUME`.

## PIP prerequisite

Operational lifecycle progress requires the immutable canonical mission envelope to contain both:

- `bindings.pip.pip_id`
- `bindings.pip.pip_version`

`BIND_PIP`, planning/run/wait/replan/resume/cleanup/completion commands therefore fail closed when this binding is absent or incomplete.

Fail-safe controls are deliberately exempt from the PIP prerequisite:

- `PAUSE`
- `ABORT`
- `FAIL`
- `EXPIRE`

A malformed or incomplete mission must still be stoppable.

## Discovery API

`GET /api/missions/{mission_id}/lifecycle-command-contract`

The response now distinguishes:

- `topology_eligible_commands`
- `guard_eligible_commands`
- `guard_eligible_resume_targets`
- per-command `guard_evaluations`
- the static `lifecycle_guard_matrix` contract

Guard eligibility is explicitly **not Governance authorization**.

## Execution API

`POST /api/missions/{mission_id}/lifecycle/commands`

Successful responses include `lifecycle_guard` evidence. Guard failure occurs after the existing Stage-3.1.6 version-vector/state-version gate but before state mutation. The command is durably journaled as failed and no transition or `MISSION_COMMAND_COMPLETED` event is emitted.

The generic `POST /api/missions/{mission_id}/commands` path cannot bypass this guard when `operation=LIFECYCLE_COMMAND`.

## Compatibility and boundaries

- Repository migration level remains **8**.
- No Stage-3.2.2 database migration is introduced.
- The legacy Stage-3.1 direct state-transition API is preserved for compatibility.
- The Stage-3.2.2 guard applies to `LIFECYCLE_COMMAND` only.
- No Governance decision is synthesized.
- No Governance/CTI external query is made by the lifecycle guard.
- No target-action dispatch or actuation is added.
- aptsGSS remains the external authoritative Governance plane.

The following are explicitly deferred:

- evidence/approval dependency satisfaction: Stage 3.2.5
- cleanup verification and completion criteria: Stage 3.2.8

## Regression baseline

`140 passed`.
