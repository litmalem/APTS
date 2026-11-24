# Stage 3.5.9 — Execution Event Lineage, Replay & Recovery

Stage 3.5.9 closes the execution evidence/recovery boundary over the durable Stage 3.5.1–3.5.8 trajectory. It does **not** execute or resume target work. It reconstructs a terminal execution state from canonical Mission Orchestrator artifacts and the verified Mission event ledger.

## Runtime identity

- `control_version`: `stage3.5.9-execution-event-lineage-replay-recovery`
- HTTP server: `APTSMissionOrchestrator/3.5.9`
- repository migration: **35**
- canonical pytest inventory: **951** tests
- focused Stage 3.5.9 proof: **20** tests

## Canonical contracts

| Contract | Value |
|---|---|
| Execution lineage schema | `apts-execution-event-lineage-v1` |
| Execution replay schema | `apts-execution-event-replay-v1` |
| Recovery checkpoint schema | `apts-execution-recovery-checkpoint-v1` |
| Recovery identity | `xrecover-*` |
| Persistence store | `mission_execution_recovery_checkpoints` |
| Recovery event | `MISSION_EXECUTION_RECOVERY_CHECKPOINTED` |

A recovery checkpoint is immutable and bound to exactly one Stage-3.5.8 `xprop-*` terminal outcome propagation. A Stage-3.5.8 termination control (`xterm-*`) is optional and has cardinality 0 or 1.

## Source chain reconstructed

Stage 3.5.9 verifies and binds the current active Plan plus the canonical execution trajectory:

1. Stage 3.5.4 `xattempt-*` execution-attempt identity.
2. Stage 3.5.5 `xack-*` delivery/acknowledgement.
3. Stage 3.5.6 `xrun-*` RUNNING/heartbeat projection.
4. Stage 3.5.7 `xresult-*` terminal result + evidence/artifact manifests.
5. Optional Stage 3.5.8 `xterm-*` termination-control acknowledgement.
6. Stage 3.5.8 `xprop-*` verified terminal outcome propagation.
7. The verified execution-event subchain from the append-only Mission event ledger.

The minimum complete trajectory without `xterm-*` contains eight execution events before the Stage-3.5.9 checkpoint event. Checkpoint creation appends `MISSION_EXECUTION_RECOVERY_CHECKPOINTED`, extending the lineage without creating a new target action.

## Replay semantics

Replay is deterministic and read-only. `GET .../execution-replay` filters the verified Mission event chain to execution events, preserves canonical event ordering, artifact causation, event hashes, and returns a replay digest. Replay does not call the runtime, Governance, routing, or target systems.

## Recovery semantics

`recover_execution_state()` reconstructs the terminal execution snapshot solely from durable repository records. Recovery explicitly performs **none** of the following:

- runtime health probe or terminal-result query;
- runtime control I/O or endpoint resolution;
- external network I/O or Governance query;
- dispatch redelivery or a new execution attempt;
- a new target-action dispatch or target actuation;
- Mission lifecycle transition or failure propagation;
- Mission-success completion authority.

`REPLAY != EXECUTION`, and recovery is neither authorization, dispatch, runtime resumption, nor lifecycle transition.

## HTTP surface

Read endpoints:

- `GET /api/missions/{mission_id}/execution-lineage`
- `GET /api/missions/{mission_id}/execution-replay`
- `GET /api/missions/{mission_id}/execution-recovery`
- `GET /api/missions/{mission_id}/execution-recovery-checkpoints`
- `GET /api/missions/{mission_id}/execution-recovery-checkpoints/{checkpoint_id}`
- `GET /api/missions/{mission_id}/execution-lineage-definition`

Mutation endpoint:

- `POST /api/missions/{mission_id}/execution-recovery-checkpoints`

Checkpoint requests are optimistic-concurrency guarded by Mission state/version, active Plan identity/hash, source artifact identities/hashes, optional termination-control cardinality, execution-event count, and execution-event tip hash. Caller-supplied runtime observations, authorization decisions, recovery state, replay payloads, dispatch commands, and target actions are rejected.

## Persistence/integrity

Migration `035_stage3_5_9_execution_event_lineage_replay_recovery.sql` adds `mission_execution_recovery_checkpoints`. The repository persistence manifest now includes `execution_event_lineage_replay_recovery_store`, and repository verification checks checkpoint self-integrity, outcome binding, checkpoint event causation, and record counts.

## Verification

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_5_9_ACCEPTANCE.ps1
```

The acceptance script requires an active Stage-3.5.9 runtime on `http://127.0.0.1:8780`, compiles source/tests, verifies the 951-test inventory, executes the full Stage 3.1–3.5.9 regression, runs the 20 focused Stage-3.5.9 tests, and checks the non-actuating recovery declarations.

## Next boundary

Stage **3.5.10 — Execution Acceptance & Regression Gate**.
