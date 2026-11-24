# Patch Notes — Stage 3.7.1

## Stage

**3.7.1 — Canonical Adaptation / Replan Contract & Identity**

## Active runtime identity

```text
control_version = stage3.7.1-canonical-adaptation-replan-contract-identity
server_version  = APTSMissionOrchestrator/3.7.1
repository_migration_level = 45
```

## Changes

### Canonical adaptation/replan domain

Added `mission_orchestrator/adaptation_replan.py` with deterministic normalization, request fingerprinting, immutable contract construction/verification, canonical state/trigger definitions, and identity namespaces:

```text
adpt-   AdaptationEpisode
rpln-   ReplanTrigger
rpsnap- ReplanSnapshot (reserved)
rpcand- ReplanCandidate (reserved)
rpdec-  ReplanDecision (reserved)
rpcom-  ReplanCommit (reserved)
```

Stage 3.7.1 materializes only `adpt-*` and `rpln-*` and fixes the initial episode state at `DETECTED`.

### Durable persistence and repository integrity

Added migration:

```text
migrations/045_stage3_7_1_canonical_adaptation_replan_contract_identity.sql
```

and durable store:

```text
mission_adaptation_replan_contracts
```

Repository support includes idempotency lookup, episode/trigger lookup, history, transactional creation, optimistic Mission/Plan-head checks, optional source-event hash binding, record counts, manifest projection, and integrity reconstruction.

### Service materialization

Added service methods for creation, retrieval, history, definition, response projection, and canonical detection-event recording. Creation is constrained to `RUNNING`, `WAITING_EVIDENCE`, or `WAITING_APPROVAL`, binds the exact active Plan generation `N`, records target generation `N+1`, and rejects terminal or already-`REPLANNING` Missions.

### Canonical event

Added:

```text
MISSION_ADAPTATION_REPLAN_DETECTED
```

Exact replay is idempotent and does not append a duplicate event.

### HTTP API

Added:

```text
POST /api/missions/{mission_id}/adaptation-replans
GET  /api/missions/{mission_id}/adaptation-replans
GET  /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}
GET  /api/missions/{mission_id}/adaptation-replan-definition
```

New adaptation/replan conflicts/not-found/guard rejections are mapped to the existing API error handling model.

### Runtime health and identity

`/health` now exposes Stage-3.7.1 schemas, mode, authority, identity prefixes, state model, trigger vocabulary, current-Plan binding rule, migration/store identity, and explicit negative authority flags. `supported_controls` now closes with Stage 3.6.9, Stage 3.6.10, then Stage 3.7.1.

### Regression rebase

Historical tests that assert the current runtime control, current repository migration, migration inventory, server version, or supported-control tail were rebased to the Stage-3.7.1 head while preserving historical stage-specific metadata such as Stage-3.6.9 migration 44 and Stage-3.6.10's declared expected migration 44.

## Boundary guarantees

Stage 3.7.1 does not perform classification, eligibility evaluation, snapshot binding, lifecycle REPLAN transition, planner invocation, candidate creation, Plan-delta computation, successor validation/commit, Plan supersession, Mission lifecycle transition, Governance/runtime I/O, dispatch, execution-attempt creation, external network I/O, target action dispatch, target actuation, or terminal-state reopening.

## Tests added

`tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py` contributes **19 test items** covering runtime identity, future identity reservations, canonical materialization, source-state guards, current-Plan concurrency binding, no-side-effect boundaries, event/evidence binding, idempotency, conflict behavior, restart persistence, repository integrity/tamper detection, and HTTP surface.

Canonical inventory after this patch:

```text
previous Stage-3.6.10 inventory = 1156
new Stage-3.7.1 tests           =   19
current canonical inventory     = 1175
```
