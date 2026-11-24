# Stage 3.3.9 — Planning Event Lineage, Replay & Recovery

## Purpose

Stage 3.3.9 makes the canonical planning stack from Stage 3.3.1 through Stage 3.3.8 **traceable, replayable, and recoverable** without turning replay or recovery into a new planning, authorization, scheduling, or execution path.

The stage adds three tightly bounded capabilities:

1. a planning-only causal projection over the already verified canonical Mission event ledger;
2. a deterministic, read-only replay representation of those planning events;
3. one immutable durable recovery checkpoint per Plan version, bound to the active Plan and its Stage-3.3.8 readiness projection.

Recovery reconstructs planning state from durable canonical artifacts. It does not re-run the planner and performs no external model call, network read, Governance query, task dispatch, or target actuation.

## Active control

- `control_version = stage3.3.9-planning-event-lineage-replay-recovery`
- HTTP server = `APTSMissionOrchestrator/3.3.9`
- planning lineage schema = `apts-planning-event-lineage-v1`
- planning replay schema = `apts-planning-event-replay-v1`
- recovery checkpoint schema = `apts-planning-recovery-checkpoint-v1`
- recovery checkpoint identity prefix = `precover-`
- repository migration level = `17`
- version-vector domain = `planning_recovery_version`
- persistence store = `mission_planning_recovery_checkpoints`

## Planning-event lineage

The canonical Mission event hash chain remains the source of truth. Stage 3.3.9 does not create a second authoritative event ledger. Instead, it verifies the complete Mission event chain and projects the planning-related subset in canonical order.

The planning event family includes the planning artifacts already emitted by Stage 3.3.1–3.3.8, including:

```text
MISSION_PLAN_CONTRACT_REGISTERED
MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED
MISSION_TASK_DECOMPOSITION_REGISTERED
MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED
MISSION_PLANNER_INVOKED
MISSION_PLAN_GENERATED
MISSION_PLAN_VALIDATED_FEASIBLE
MISSION_PLAN_VERSION_ACTIVATED
MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED
MISSION_TASK_READINESS_PROJECTED
```

Stage 3.3.9 additionally emits:

```text
MISSION_PLANNING_RECOVERY_CHECKPOINTED
```

Lifecycle transitions that enter or leave `PLANNING` / `REPLANNING` are also included in the planning replay projection when applicable.

The resulting projection exposes:

- ordered planning events;
- planning-event count;
- planning-event tip event ID and SHA-256;
- deterministic planning-replay SHA-256;
- proof that the complete Mission event chain was verified first.

## Read-only replay

Planning replay is a deterministic serialization of the verified planning-event projection.

```text
canonical Mission event chain
          |
          +--> verify full SHA-256 chain
          |
          +--> select planning events
          |
          +--> preserve canonical order
          |
          +--> deterministic replay SHA-256
```

Replay is explicitly observational:

```text
read_only                         = true
side_effects_performed            = false
planner_rerun_performed           = false
external_model_invocation         = false
external_network_io               = false
governance_authorization_query    = false
target_action_dispatch            = false
target_actuation                  = false
```

Repeated GET replay requests therefore cannot mutate Mission, Plan, readiness, event, or execution state.

## Durable planning recovery checkpoint

A checkpoint can be created only when:

- Mission state is `PLANNING` or `REPLANNING`;
- an active Stage-3.3.7 Plan version exists;
- an active Stage-3.3.8 readiness projection exists for that exact Plan version;
- the caller presents the exact Mission state version and version-vector SHA-256;
- the caller presents the exact active Plan record/version/hash;
- the caller presents the exact readiness projection identity/hash;
- the caller presents the exact planning-event count/tip SHA-256;
- complete durable repository and Mission event integrity verification passes.

The checkpoint freezes references to:

```text
Mission state/version vector
        |
        +--> active Plan version + Plan SHA-256
        |
        +--> active readiness projection + SHA-256
        |
        +--> planning event count/tip
        |
        +--> deterministic replay SHA-256
        |
        +--> recoverable task/readiness/wave projection
```

The checkpoint never accepts caller-supplied Plan, tasks, readiness status, authorization, dispatch, execution, recovery state, or replay state. Those values are derived from canonical durable artifacts only.

## Immutability, idempotency, and concurrency

There is at most one immutable recovery checkpoint per Mission/Plan version.

Exact replay of the same `idempotency_key` plus canonical request returns the existing checkpoint and emits no duplicate event.

Stage 3.3.9 fails closed on stale:

- Mission `state_version`;
- version-vector SHA-256;
- active Plan record ID/version/hash;
- readiness projection ID/hash;
- planning-event count;
- planning-event tip SHA-256.

A reused idempotency key with different canonical content is rejected.

## Replanning and supersession

Recovery checkpoints follow Plan-version lineage rather than being mutated:

```text
Plan v1 -> readiness v1 -> recovery checkpoint v1 -> effective SUPERSEDED
   |
   +-- REPLANNING
          |
          +-> Plan v2 -> readiness v2 -> recovery checkpoint v2 -> ACTIVE
```

The old checkpoint remains immutable and auditable. Effective status is derived from the Stage-3.3.7 active Plan head.

## Recovery after restart

Recovery reads the active checkpoint, active Plan version, readiness projection, repository manifest, and event ledger from durable storage. It verifies the bindings and then reconstructs the planning state.

A process restart must not silently call the planner again. The committed Plan is an artifact and remains the source of truth.

```text
restart
   |
   +--> durable repository
           |
           +--> verify repository/event integrity
           +--> active Plan head
           +--> active readiness projection
           +--> active recovery checkpoint
           |
           +--> reconstruct planning state

planner rerun = false
```

## Repository integrity

Migration `017_stage3_3_9_planning_event_lineage_replay_recovery.sql` adds `mission_planning_recovery_checkpoints`.

Repository integrity now verifies, among other checks:

- recovery checkpoint canonical SHA-256;
- checkpoint-version uniqueness;
- one checkpoint per Plan version;
- exact active historical Plan-version binding;
- exact readiness-projection binding;
- checkpoint source planning-event tip precedes its checkpoint event;
- checkpoint event causation and payload hash match the checkpoint;
- persistence-manifest and record-count consistency.

## APIs

```text
GET  /api/missions/{mission_id}/planning-lineage
GET  /api/missions/{mission_id}/planning-replay
GET  /api/missions/{mission_id}/planning-lineage-definition

POST /api/missions/{mission_id}/planning-recovery-checkpoint
GET  /api/missions/{mission_id}/planning-recovery-checkpoint
GET  /api/missions/{mission_id}/planning-recovery-checkpoints
GET  /api/missions/{mission_id}/planning-recovery
```

## Authority boundary

All Stage-3 planning invariants remain mandatory:

```text
PLAN      != AUTHORIZATION
TASK      != DISPATCH
READINESS != PERMISSION
PLANNER   != GOVERNANCE
REPLAY    != EXECUTION
RECOVERY  != REPLANNING
RECOVERY  != AUTHORIZATION
```

Runtime declarations remain:

- Governance authority = `EXTERNAL_APTS_GSS`;
- recovery Governance query = `false`;
- recovery planner rerun = `false`;
- recovery external model call = `false`;
- recovery external network I/O = `false`;
- task dispatch = `false`;
- target-action dispatch = `false`;
- target actuation = `false`.

## Regression

Stage 3.3.9 adds `tests/test_stage3_3_9_planning_event_lineage_replay_recovery.py` with **38 cases**.

Verified regression partitions:

```text
Stage 3.1 tests          : 111 passed
Stage 3.2 tests          : 156 passed
Stage 3.3.1–3.3.4       : 77 passed
Stage 3.3.5–3.3.6       : 57 passed
Stage 3.3.7              : 27 passed
Stage 3.3.8              : 28 passed
Stage 3.3.9              : 38 passed
Total collected baseline : 494 tests
```

`python -m pytest --collect-only -q` confirms **494 tests collected**.

## Live acceptance

After applying migration 017 and restarting Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_9_ACCEPTANCE.ps1
```

Expected final result:

```text
==============================================================================
STAGE 3.3.9 ACCEPTANCE: PASS
==============================================================================
```
