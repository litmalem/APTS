# Stage 3.7.4 — Canonical Replan Snapshot & Context Binding

## Purpose

Stage 3.7.4 advances the Stage-3.7 adaptation/replanning pipeline from an **ELIGIBLE Stage-3.7.3 governance gate** to a durable immutable **Canonical ReplanSnapshot** that freezes the exact local context that a later replanning stage may consume.

The stage answers one bounded question only:

> What canonical Mission, Plan, Governance, adaptation-trigger, eligibility, task/dependency, and outcome facts were durably true at the instant this eligible adaptation episode was bound for later replanning?

Stage 3.7.4 materializes that answer without issuing lifecycle `REPLAN`, without querying Governance again, and without invoking a planner or creating any successor Plan.

## Runtime identity

```text
control_version = stage3.7.4-canonical-replan-snapshot-context-binding
server_version  = APTSMissionOrchestrator/3.7.4
repository_migration_level = 48
migration = migrations/048_stage3_7_4_canonical_replan_snapshot_context_binding.sql
persistence_store = mission_replan_snapshots
```

Predecessor contracts remain independent and immutable:

```text
Stage 3.7.1 migration metadata = 45
Stage 3.7.1 store              = mission_adaptation_replan_contracts
Stage 3.7.1 persisted state    = DETECTED

Stage 3.7.2 migration metadata = 46
Stage 3.7.2 store              = mission_adaptation_trigger_classifications
Stage 3.7.2 persisted status   = CLASSIFIED

Stage 3.7.3 migration metadata = 47
Stage 3.7.3 store              = mission_replan_eligibility_governance_gates
Stage 3.7.3 eligibility status = ELIGIBLE / NOT_ELIGIBLE / REVIEW_REQUIRED
```

## Canonical snapshot contract

```text
stage schema    = apts-canonical-replan-snapshot-context-binding-v1
contract schema = apts-replan-snapshot-context-binding-contract-v1
identity prefix = rpsnap-
status          = SNAPSHOT_BOUND
event           = MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND
context mode    = CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH
authority       = MISSION_ORCHESTRATOR_REPLAN_CONTEXT_BINDING
```

The snapshot mode is:

```text
IMMUTABLE_CANONICAL_REPLAN_SNAPSHOT_BOUND_TO_ELIGIBLE_EPISODE_CURRENT_PLAN_LOCAL_DURABLE_CONTEXT_NO_EXTERNAL_REFRESH_NO_REPLAN_COMMAND_NO_PLANNER_NO_ACTUATION
```

Each snapshot is canonically hashed and binds the exact:

- Mission ID;
- Stage-3.7.1 AdaptationEpisode (`adpt-*`) and ReplanTrigger (`rpln-*`);
- Stage-3.7.1 immutable contract hash and detection event hash;
- Stage-3.7.2 Classification (`rcls-*`), classification hash, and classification event hash;
- Stage-3.7.3 EligibilityGate (`rpelig-*`), immutable eligibility hash, eligibility event hash, and bound authoritative Governance PolicyDecision hash;
- Mission state, state version, and version SHA-256;
- active Stage-3.3 Plan-version head (`pver-*`), Plan version/generation, canonical Plan ID, and Plan hash;
- current Mission scope snapshot/hash;
- current Governance binding snapshot/version/hash;
- canonical planned-task set;
- canonical dependency graph and dependency edges;
- durable task outcomes and task-completion records available for the bound source Plan;
- deterministic `task_context_sha256` over those task/dependency/outcome facts;
- request fingerprint, idempotency key, binder identity, reason/metadata, and canonical snapshot hash.

## Stage-3.7.3 eligibility prerequisite

A Stage-3.7.4 snapshot can be materialized only when the source Stage-3.7.3 gate is still:

```text
eligibility_status = ELIGIBLE
replan_eligible     = true
```

`NOT_ELIGIBLE` and `REVIEW_REQUIRED` gates are rejected.

The Stage-3.7.3 source must still bind the same Stage-3.7.1 and Stage-3.7.2 records, Mission state/version, active Plan head, scope, Governance binding, and PolicyDecision hash. Any drift fails closed.

## Local durable context only

Stage 3.7.4 deliberately **does not refresh external context**. The snapshot is built only from locally durable canonical records already controlled by Mission Orchestrator.

This means Stage 3.7.4 performs no new Governance authorization query and no external environment/context fetch. The authoritative Governance decision used by the snapshot is the immutable PolicyDecision already bound by Stage 3.7.3.

This separation is intentional: Stage 3.7.3 decides whether replanning is currently eligible under authoritative Governance; Stage 3.7.4 freezes the exact local canonical context for the next replanning step.

## Concurrency and drift protection

The bind request carries explicit expected values for:

```text
Stage-3.7.1 adaptation contract hash
Stage-3.7.2 classification hash
Stage-3.7.3 eligibility hash
PolicyDecision hash
Mission version hash and state version
active Plan-version record/version/hash
Mission scope snapshot/hash
Governance binding snapshot/version/hash
```

A mismatch is rejected rather than silently rebased. Mission-state drift after Stage-3.7.3 eligibility, active Plan-head drift, scope drift, Governance-binding drift, or predecessor-hash drift therefore cannot produce a snapshot from mixed versions of context.

## Task/dependency/outcome context binding

The snapshot binds a deterministic task-context digest derived from the current source Plan's durable canonical records. This includes:

```text
planned tasks
canonical dependency graph
dependency edges
task outcomes
task-completion records
```

The snapshot does not mutate any of those records. It records their identities and canonical hashes so a later replanning stage can prove which operational state it consumed.

## Idempotency and cardinality

Each adaptation episode can have exactly one Stage-3.7.4 snapshot. The schema additionally enforces unique binding to the source ReplanTrigger, Classification, and EligibilityGate.

Exact retry with the same idempotency material returns the durable snapshot and does not append a second Mission event. Reuse of an idempotency key with different request material fails closed.

## Event lineage and persistence

Migration 048 creates:

```text
mission_replan_snapshots
```

A newly bound snapshot appends exactly one canonical Mission event:

```text
MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND
```

Repository reconstruction/integrity verifies:

- the Stage-3.7.4 contract hash;
- Stage-3.7.1/3.7.2/3.7.3 source identities and hashes;
- ELIGIBLE source-gate semantics;
- current source Plan-version binding;
- Mission scope and Governance binding hashes;
- PolicyDecision hash;
- detection/classification/eligibility event hashes;
- Stage-3.7.4 event binding/cardinality;
- task-context hash;
- record counts and persistence manifest.

## API surface

```text
POST /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}/snapshot
GET  /api/missions/{mission_id}/adaptation-replans/{adaptation_episode_id}/snapshot
GET  /api/missions/{mission_id}/replan-snapshots
GET  /api/missions/{mission_id}/replan-snapshots/{replan_snapshot_id}
GET  /api/missions/{mission_id}/replan-snapshot-context-binding-definition
```

No Stage-3.7.4 HTTP surface exists for lifecycle REPLAN, planner invocation, Plan-delta calculation, candidate/successor Plan creation, replan commit, Plan supersession, dispatch, execution, or target actuation.

## Authority boundary

Stage 3.7.4 **does perform**:

```text
ELIGIBLE Stage-3.7.3 gate verification
predecessor lineage/hash verification
Mission state/version concurrency verification
active Plan-head verification
Mission scope and Governance-binding verification
local durable task/dependency/outcome context collection
immutable canonical ReplanSnapshot construction
snapshot persistence
canonical Mission event recording
repository reconstruction/integrity verification
```

Stage 3.7.4 does **not** perform:

```text
external context refresh
new Governance authorization query
Stage-3.2 lifecycle REPLAN
planner invocation
ReplanCandidate creation
successor Plan creation
Plan delta computation
successor-Plan validation
replan decision/commit
Plan supersession
historical Plan mutation
Mission state transition
runtime-control I/O
dispatch / execution-attempt creation
external target network I/O
target-action dispatch
target actuation
```

The next planned control is **Stage 3.7.5**.

## Validation status

The Stage-3.7.4 focused proof contains exactly 20 tests and validates the canonical snapshot contract, predecessor bindings, local-durable-only context rule, no-additional-Governance-query rule, task/dependency/outcome binding, drift rejection, idempotency/cardinality, persistence/reconstruction, API surface, and future-authority exclusions.

Build-sandbox validation completed with **1236/1236 canonical tests PASS** in **882.22s (14m42s)**, in addition to the **20/20 focused Stage-3.7.4 tests PASS**.

The authoritative target-host release acceptance gate is `STAGE3_7_4_ACCEPTANCE.ps1`. It reruns the complete canonical regression inventory and runtime preflight before target-host Stage 3.7.4 acceptance is recorded.
