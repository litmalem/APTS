# Stage 3.2.6 — Pause, Resume & Replanning Control

Stage 3.2.6 turns `PAUSED` and `REPLANNING` from topology-only lifecycle states into durable control states with explicit local lineage. It preserves the Stage-3.1.2 canonical topology and Stage-3.2.1 command vocabulary while preventing legacy direct transitions from bypassing lifecycle intent.

This stage controls Mission lifecycle only. It does **not** invoke an autonomous planner, create a plan artifact, query aptsGSS, grant authorization, dispatch a target action, or actuate a target.

## Contract

Schema: `apts-mission-pause-resume-replan-control-v1`

Mode: `DURABLE_PAUSE_CONTEXT_MATCHED_RESUME_AND_REPLAN_READINESS_FAIL_CLOSED`

Commands:

- `PAUSE` → `PAUSED`;
- `RESUME` from `PAUSED` → a source-state-compatible target;
- `REPLAN` → `REPLANNING`;
- `START` from `REPLANNING` → `RUNNING` only with active Stage-3.2.6 replan lineage and non-empty readiness evidence.

## Durable pause context

`PAUSE` records `mission_pause_control` inside the existing append-only transition metadata. The evidence includes:

- deterministic `pause_id`;
- exact `from_state` and `from_state_version`;
- actor/reason/evidence refs;
- active Stage-3.2.5 waiting dependency when pausing a waiting state;
- active Stage-3.2.6 replan episode when pausing `REPLANNING`;
- explicit no-planner/no-Governance/no-target-execution semantics.

A legacy direct transition to `PAUSED` does not fabricate this evidence and therefore cannot use `RESUME`.

## Resume target policy

Stage 3.2.6 narrows `RESUME` by the state actually paused:

| Paused source | Allowed Stage-3.2.6 resume target |
|---|---|
| `CREATED` | none; containment-only |
| `PIP_BOUND` | `PIP_BOUND` |
| `PLANNING` | `PLANNING` |
| `RUNNING` | `RUNNING` |
| `WAITING_EVIDENCE` | `REPLANNING` |
| `WAITING_APPROVAL` | `REPLANNING` |
| `REPLANNING` | `REPLANNING` |

The policy intentionally prevents a paused waiting dependency from resuming directly to `RUNNING`, because that would bypass Stage-3.2.5 dependency satisfaction. The safe continuation is `REPLANNING`, with the abandoned dependency preserved in evidence.

Resume additionally validates prior activation/replan lineage appropriate to the paused source.

## Replanning control

`REPLAN` records a durable `mission_replan_control` episode with a deterministic `replan_id`, source state, trigger/reason, evidence refs, and any abandoned waiting dependency.

No planner is invoked and no plan artifact is created by this stage.

Progress from `REPLANNING` through `START`, `WAIT_FOR_EVIDENCE`, or `WAIT_FOR_APPROVAL` requires valid active Stage-3.2.6 replan lineage. A legacy direct transition into `REPLANNING` cannot bypass the control.

`START` from `REPLANNING` additionally requires non-empty `evidence_refs`. Successful return to `RUNNING` records `mission_replan_resolution` with:

- matching active `replan_id`;
- readiness status `READY`;
- resolver identity;
- readiness evidence refs;
- explicit non-authorization semantics.

## Read API

`GET /api/missions/{mission_id}/pause-resume-replan-contract`

The projection exposes active pause/replan lineage, allowed resume targets for the active pause, replan readiness semantics, and explicit authority boundaries.

The existing lifecycle discovery endpoint also embeds the Stage-3.2.6 projection:

`GET /api/missions/{mission_id}/lifecycle-command-contract`

## Guard-matrix extension

Stage 3.2.6 adds:

- `PAUSE_LINEAGE_FOR_RESUME`;
- `RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE`;
- `RESUME_PREREQUISITE_LINEAGE_FOR_TARGET`;
- `REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS`;
- `REPLAN_READINESS_EVIDENCE_FOR_RETURN`.

## Persistence and lineage

No new table or migration is introduced. Stage 3.2.6 reuses:

- Stage-3.1.6 command journal/idempotency gate;
- Stage-3.1.2 append-only state transition ledger;
- Stage-3.1.9 Mission event lineage;
- existing transition metadata for pause/resume/replan evidence.

Repository migration level remains **8**.

## Authority boundary

Stage 3.2.6 explicitly reports:

- `planner_invocation_performed = false`;
- `plan_artifact_created = false`;
- `governance_authorization_query_performed = false`;
- `authorization_granted = false`;
- `execution_authorized = false`;
- `target_action_dispatch_enabled = false`;
- `target_actuation = false`.

Governance authority remains `EXTERNAL_APTS_GSS`.

## Deliberately deferred

Stage 3.2.6 does not implement:

- Stage 3.2.7 terminal abort/failure/expiration semantics extension;
- autonomous planner invocation or plan generation;
- external event-driven automatic resume/replan;
- verified cleanup/completion gate (Stage 3.2.8);
- target-action dispatch or actuation.

## Regression baseline

`199 passed`.
