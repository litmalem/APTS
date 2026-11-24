# Stage 3.2.9 — Event-Driven Lifecycle Automation & Reliability

Stage 3.2.9 adds a typed event-ingress layer to the canonical Mission lifecycle. Source events no longer need a caller to manually translate them into lifecycle commands. Instead, Mission Orchestrator normalizes each event, binds it to the exact observed Mission state/version vector, derives one deterministic Stage-3.2 lifecycle command, and sends that command through the **existing** Stage-3.1.6 command journal plus the Stage-3.2.2–3.2.8 lifecycle guard chain.

The automation layer is therefore a **trigger/proposal layer**, not a direct state mutator and not a new authority. It does not synthesize Governance authorization, invoke the planner, dispatch target actions, or subscribe to an external event bus.

## Contract

Schema:

`apts-mission-lifecycle-automation-v1`

Mode:

`TYPED_EVENT_TO_GUARDED_IDEMPOTENT_LIFECYCLE_COMMAND_FAIL_CLOSED`

Authority semantics:

`MISSION_LIFECYCLE_EVENT_TRIGGER_ONLY_NOT_GOVERNANCE_AUTHORIZATION_PLANNER_OR_TARGET_EXECUTION`

Reliability semantics:

- source identity: `source_component + event_id`;
- source-event fingerprint: canonical SHA-256 over the normalized event;
- exact state binding: `observed_state + observed_state_version + observed_version_sha256`;
- deterministic generated lifecycle `command_id` and `idempotency_key`;
- existing Stage-3.1.6 command journal remains the mutation/idempotency gate;
- existing Stage-3.1.9 append-only Mission event ledger remains the audit/lineage substrate;
- stale/out-of-order events fail closed before state mutation;
- exact applied-event replay is side-effect free;
- exact rejected-event replay returns the durable rejection without re-evaluating a now-different Mission state;
- reuse of the same source identity with a different canonical payload is rejected as a conflict.

## API

Stage 3.2.9 adds:

`GET /api/missions/{mission_id}/lifecycle-automation-contract`

and:

`POST /api/missions/{mission_id}/lifecycle/events`

The existing lifecycle command endpoint remains authoritative for command execution:

`POST /api/missions/{mission_id}/lifecycle/commands`

The event endpoint does **not** call the direct state-transition API.

## Typed source-event contract

A lifecycle event uses this envelope:

```json
{
  "event_id": "source-event-001",
  "event_type": "PIP_BIND_REQUESTED",
  "source_component": "MISSION-EVENT-ADAPTER",
  "occurred_at": "2026-09-04T02:15:00Z",
  "observed_state": "CREATED",
  "observed_state_version": 1,
  "observed_version_sha256": "<64-lowercase-hex>",
  "actor": "mission-event-adapter",
  "reason_code": "AUTO_PIP_BIND_REQUESTED",
  "reason": "PIP binding condition became ready",
  "evidence_refs": [],
  "metadata": {}
}
```

`occurred_at` must be timezone-aware ISO-8601. Unknown top-level fields are rejected; extension data belongs under `metadata`.

`RESUME_REQUESTED` additionally requires `target_state`. Waiting/resolution/completion event families retain the existing Stage-3.2 semantic payloads:

- `EVIDENCE_REQUIRED` / `APPROVAL_REQUIRED` require `metadata.dependency`;
- `EVIDENCE_READY` / `APPROVAL_GRANTED` require `metadata.dependency_resolution`;
- `COMPLETION_VERIFIED` requires the Stage-3.2.8 `metadata.completion` declaration and its evidence bindings.

## Event-to-command mapping

| Source event | Existing lifecycle command | Valid observed source state(s) |
|---|---|---|
| `PIP_BIND_REQUESTED` | `BIND_PIP` | `CREATED` |
| `PLANNING_START_REQUESTED` | `START_PLANNING` | `PIP_BOUND` |
| `RUN_START_REQUESTED` | `START` | `PLANNING` |
| `EVIDENCE_REQUIRED` | `WAIT_FOR_EVIDENCE` | `PLANNING`, `RUNNING`, `REPLANNING` |
| `APPROVAL_REQUIRED` | `WAIT_FOR_APPROVAL` | `PLANNING`, `RUNNING`, `REPLANNING` |
| `EVIDENCE_READY` | `START` | `WAITING_EVIDENCE` |
| `APPROVAL_GRANTED` | `START` | `WAITING_APPROVAL` |
| `PAUSE_REQUESTED` | `PAUSE` | supported non-terminal pausable states |
| `RESUME_REQUESTED` | `RESUME` | `PAUSED` |
| `REPLAN_REQUESTED` | `REPLAN` | `RUNNING`, `WAITING_EVIDENCE`, `WAITING_APPROVAL` |
| `REPLAN_READY` | `START` | `REPLANNING` |
| `CLEANUP_REQUESTED` | `BEGIN_CLEANUP` | `RUNNING`, `PAUSED` |
| `COMPLETION_VERIFIED` | `COMPLETE` | `CLEANING_UP` |
| `ABORT_REQUESTED` | `ABORT` | all non-terminal states |
| `FAILURE_DETECTED` | `FAIL` | all non-terminal states |
| `EXPIRATION_REACHED` | `EXPIRE` | all non-terminal states |

The source-state table is an ingress validation contract only. A mapped command still has to pass canonical topology and all applicable lifecycle guards.

## Processing pipeline

The contract exposes this explicit pipeline:

1. `NORMALIZE_TYPED_EVENT`
2. `DURABLE_RECEIPT_AND_FINGERPRINT_DEDUP`
3. `EXACT_STATE_AND_VERSION_VECTOR_CHECK`
4. `TRANSLATE_TO_CANONICAL_LIFECYCLE_COMMAND`
5. `EXISTING_COMMAND_JOURNAL_IDEMPOTENCY_GATE`
6. `STAGE_3_2_LIFECYCLE_GUARD_CHAIN`
7. `CANONICAL_STATE_TRANSITION_COMMIT`
8. `DURABLE_APPLIED_OR_REJECTED_OUTCOME_EVENT`

There is no direct/blind lifecycle mutation path.

## Durable event provenance

Three canonical Mission event types are added to the existing Stage-3.1.9 hash-chained event ledger:

- `MISSION_LIFECYCLE_EVENT_RECEIVED`
- `MISSION_LIFECYCLE_EVENT_APPLIED`
- `MISSION_LIFECYCLE_EVENT_REJECTED`

For an event that successfully causes a state transition, the normal event sequence is:

```text
MISSION_LIFECYCLE_EVENT_RECEIVED
        ↓
MISSION_STATE_TRANSITIONED
        ↓
MISSION_COMMAND_COMPLETED
        ↓
MISSION_LIFECYCLE_EVENT_APPLIED
```

The RECEIVED and APPLIED/REJECTED records carry `upstream_event_id`, so the Stage-3.1.9 lineage projection can reconstruct the relationship between the source signal and the local Mission events.

For a stale or guard-rejected event, the event layer records `RECEIVED -> REJECTED` and does not claim state mutation. Guard failures that entered the existing command journal retain the command-journal failure record as well.

## Stale/out-of-order event control

An event may be syntactically valid but operationally stale. Before invoking the generated lifecycle command, Stage 3.2.9 requires all three observations to equal the current Mission projection:

- `observed_state`;
- `observed_state_version`;
- `observed_version_sha256`.

Any mismatch is rejected with the existing concurrency/version conflict semantics before the event can mutate Mission state. This prevents an old event delivered late from being interpreted against a newer Mission state.

## Source-event idempotency and conflict detection

The durable source identity is derived from:

`source_component + event_id`

The full normalized event is separately fingerprinted. The rules are:

1. first delivery creates a durable receipt;
2. same identity + same fingerprint + previously applied -> replay the already-completed generated command, with no new transition/events;
3. same identity + same fingerprint + previously rejected -> replay the durable rejection, without re-evaluating the current Mission state;
4. same identity + different fingerprint -> `MISSION_COMMAND_CONFLICT`.

This prevents accidental event-ID reuse from silently changing the meaning of a source event.

## Existing lifecycle semantics remain authoritative

Stage 3.2.9 deliberately reuses the controls already closed in Stage 3.2.1–3.2.8:

- PIP activation lineage from Stage 3.2.3;
- planning/run activation from Stage 3.2.4;
- evidence/approval dependency control from Stage 3.2.5;
- pause/resume/replanning lineage from Stage 3.2.6;
- typed abort/failure/expiration semantics from Stage 3.2.7;
- cleanup and verified-completion gate from Stage 3.2.8.

For example, `APPROVAL_GRANTED` means that a **workflow approval dependency** is satisfied. It does not mean that aptsGSS issued a Governance authorization. Likewise `COMPLETION_VERIFIED` still has to pass the full Stage-3.2.8 completion evidence gate.

## Persistence

No new table or migration is introduced. Stage 3.2.9 reuses:

- `mission_command_journal`;
- `mission_events`;
- the append-only mission state-transition ledger;
- existing lifecycle transition metadata.

Repository migration level therefore remains **8**.

## Authority boundary

Stage 3.2.9 preserves:

- `governance_authorization_authority = EXTERNAL_APTS_GSS`;
- `mission_lifecycle_automation_governance_query_performed = false`;
- `mission_lifecycle_automation_planner_invocation_performed = false`;
- `mission_lifecycle_automation_external_event_delivery_enabled = false`;
- `mission_lifecycle_automation_direct_state_mutation_allowed = false`;
- `target_action_dispatch_enabled = false`;
- `target_actuation = false`.

The new endpoint accepts already-delivered typed events. Connection to Kafka/NATS/RabbitMQ/webhooks/other external event transport is deliberately outside this stage.

## Deliberately deferred

Stage 3.2.9 does not implement:

- an external event broker/subscription worker;
- planner invocation from events;
- Governance decision synthesis or bypass;
- autonomous target execution;
- automatic retry of policy denial or terminal missions;
- arbitrary event-to-state mappings outside the canonical lifecycle command vocabulary;
- Stage 3.2.10 lifecycle acceptance/regression closure beyond the Stage-3.2.9 acceptance artifact itself.

## Regression baseline

`255 passed`.
