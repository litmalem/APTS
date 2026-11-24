# Stage 3.2.7 — Abort, Failure & Expiration Semantics

Stage 3.2.7 turns the fail-safe terminal lifecycle commands `ABORT`, `FAIL`, and `EXPIRE` into explicit typed terminal semantics with durable local lineage. The canonical Stage-3.1.2 topology already contained `ABORTED`, `FAILED`, and `EXPIRED`; this stage adds the meaning, provenance, and finality contract required to distinguish those outcomes operationally.

This stage controls Mission lifecycle termination only. It does **not** decide Governance authorization, invoke a planner, perform cleanup, claim successful completion, dispatch a target action, or actuate a target.

## Contract

Schema: `apts-mission-terminal-semantics-v1`

Mode: `DURABLE_TYPED_TERMINATION_CAUSE_WITH_IMMUTABLE_FINALITY_FAIL_CLOSED`

Typed terminal commands:

| Command | Terminal state | Cause family | Disposition |
|---|---|---|---|
| `ABORT` | `ABORTED` | `CONTROLLED_STOP` | `INTENTIONAL_ABORT` |
| `FAIL` | `FAILED` | `FAILURE` | `UNRECOVERABLE_FAILURE` |
| `EXPIRE` | `EXPIRED` | `EXPIRATION` | `VALIDITY_EXPIRED` |

The semantic distinction is intentional:

- `ABORT` means the mission was stopped by explicit control intent;
- `FAIL` means the mission cannot continue toward its objective under the current mission;
- `EXPIRE` means the mission validity/time horizon no longer permits continuation.

## Durable terminal evidence

Every lifecycle-command terminalization records `mission_terminal_control` inside the existing append-only transition metadata. The evidence contains:

- deterministic `terminal_id`;
- exact terminal command and terminal state;
- exact `from_state` and `from_state_version`;
- actor, `reason_code`, reason, and evidence references;
- optional structured `metadata.terminal` context;
- active Stage-3.2.5 waiting dependency being abandoned;
- active Stage-3.2.6 pause/replan context being abandoned;
- explicit no-success/no-completion claim;
- explicit immutable finality and no-resume/no-auto-retry semantics;
- explicit no-Governance/no-target-execution semantics.

No new table or migration is introduced.

## Fail-safe availability

`ABORT`, `FAIL`, and `EXPIRE` remain fail-safe exits from every non-terminal canonical state, including `CREATED` and `CLEANING_UP`.

They deliberately do **not** require:

- PIP binding;
- non-empty evidence references;
- Governance availability;
- planner readiness;
- waiting-dependency satisfaction.

This preserves the ability of the control plane to stop an invalid, degraded, stale, or otherwise non-continuable mission.

## Terminal finality

`ABORTED`, `FAILED`, and `EXPIRED` remain immutable terminal states under the canonical Stage-3.1.2 state machine. No lifecycle command or legacy direct transition may leave a terminal state.

Recovery semantics are explicit:

`NEW_MISSION_OR_EXPLICIT_REVISION_REQUIRED_NO_RESUME`

Stage 3.2.7 does not synthesize a hidden resume/retry path after terminalization.

## Legacy direct terminal transitions

The Stage-3.1 direct state-transition API remains preserved for compatibility. A legacy direct transition into `ABORTED`, `FAILED`, or `EXPIRED` does **not** fabricate Stage-3.2.7 typed evidence.

The terminal read model reports this explicitly as:

`LEGACY_DIRECT_TERMINAL_TRANSITION_NO_STAGE_3_2_7_EVIDENCE`

This keeps compatibility without falsely claiming typed terminal provenance.

## COMPLETED remains separate

`COMPLETED` is also terminal in the canonical state model, but it is not an abort/failure/expiration outcome. Stage 3.2.7 therefore reports completion semantics as deferred to Stage 3.2.8:

`COMPLETED_TERMINAL_DEFERRED_TO_STAGE_3_2_8`

No verified-cleanup or success gate is claimed here.

## Read API

`GET /api/missions/{mission_id}/terminal-semantics-contract`

The existing lifecycle discovery endpoint also embeds the Stage-3.2.7 projection:

`GET /api/missions/{mission_id}/lifecycle-command-contract`

## Guard-matrix extension

Stage 3.2.7 adds:

- `TERMINAL_INTENT_TARGET_CONSISTENCY`

This prevents a low-level lifecycle evaluation from pairing a terminal command with the wrong terminal state, e.g. `ABORT -> FAILED`.

## Persistence and lineage

Stage 3.2.7 reuses:

- Stage-3.1.6 command journal/idempotency gate;
- Stage-3.1.2 append-only state transition ledger;
- Stage-3.1.9 Mission event lineage;
- existing transition metadata for terminal evidence.

Repository migration level remains **8**.

## Authority boundary

Stage 3.2.7 explicitly reports:

- `governance_authorization_query_performed = false`;
- `authorization_granted = false`;
- `execution_authorized = false`;
- `target_action_dispatch_enabled = false`;
- `target_actuation = false`;
- `verified_completion_claimed = false`;
- `cleanup_completion_gate_applied = false`.

Governance authority remains `EXTERNAL_APTS_GSS`.

## Deliberately deferred

Stage 3.2.7 does not implement:

- Stage 3.2.8 verified cleanup/completion gate;
- autonomous planner invocation or plan generation;
- event-driven automatic expiration scheduling;
- automatic mission retry/recovery after terminal state;
- target-action dispatch or actuation.

## Regression baseline

`216 passed`.
