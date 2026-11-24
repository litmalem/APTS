# Stage 3.7.5 — Deterministic Replan Candidate Generation

## Purpose

Stage 3.7.5 advances the Stage-3.7 adaptation/replanning pipeline from an immutable **Stage-3.7.4 ReplanSnapshot** to a durable deterministic **ReplanCandidate**. The stage is intentionally bounded: it computes a candidate successor-plan projection from the exact snapshot-bound task/dependency/outcome context, but it does **not** create or activate a successor Plan and does not validate, commit, supersede, dispatch, execute, or actuate anything.

The stage answers one bounded question:

> Given the immutable canonical ReplanSnapshot captured by Stage 3.7.4, what deterministic candidate remainder of the source Plan should be proposed for the next plan version without mutating current Mission or Plan state?

## Runtime identity

```text
control_version = stage3.7.5-deterministic-replan-candidate-generation
server_version  = APTSMissionOrchestrator/3.7.5
repository_migration_level = 49
migration = migrations/049_stage3_7_5_deterministic_replan_candidate_generation.sql
persistence_store = mission_replan_candidates
```

Predecessor migration metadata remains immutable:

```text
Stage 3.7.1 = 45
Stage 3.7.2 = 46
Stage 3.7.3 = 47
Stage 3.7.4 = 48
```

## Canonical candidate contract

```text
stage schema       = apts-deterministic-replan-candidate-generation-v1
contract schema    = apts-replan-candidate-generation-contract-v1
candidate prefix   = rpcand-
invocation prefix  = rpinv-
status             = CANDIDATE_GENERATED
event              = MISSION_REPLAN_CANDIDATE_GENERATED
authority          = MISSION_ORCHESTRATOR_DETERMINISTIC_REPLAN_CANDIDATE_GENERATION
planner profile    = CANONICAL_REPLAN_REMAINDER_DAG_V1
```

The Stage-3.7.5 operating mode is:

```text
DETERMINISTIC_LOCAL_PURE_FUNCTION_OVER_IMMUTABLE_REPLAN_SNAPSHOT_CANDIDATE_ONLY_NO_VALIDATION_NO_COMMIT_NO_SUPERSESSION_NO_ACTUATION
```

## Sole authoritative input

Stage 3.7.5 accepts one authoritative planning input only: the immutable Stage-3.7.4 ReplanSnapshot. The request supplies expected hashes and identities only as concurrency guards; it may not supply tasks, dependencies, a planner result, a Plan delta, successor-Plan content, validation decisions, commit material, routing, dispatch, execution, or target-action fields.

Generation fails closed if any of the following no longer matches the snapshot:

- ReplanSnapshot SHA-256;
- task-context SHA-256;
- source Plan-version record identity;
- source Plan version;
- source Plan SHA-256;
- source Mission state version;
- source Mission version SHA-256;
- current active Plan head;
- current Mission state/version.

This prevents candidate generation from silently rebasing onto state that changed after Stage 3.7.4 captured its immutable context.

## Deterministic local planner

The Stage-3.7.5 planner is not a free-form or externally refreshed model invocation. It is a deterministic local projection identified by:

```text
planner engine  = APTS_MO_LOCAL_DETERMINISTIC_REPLAN_PLANNER
engine version  = 1
planner profile = CANONICAL_REPLAN_REMAINDER_DAG_V1
```

The planner computes a canonical remainder DAG from the Stage-3.7.4 snapshot:

1. source tasks are ordered by `task_index`, then `planned_task_id`;
2. tasks with durable completion records are treated as historical completed work and are not regenerated;
3. remaining tasks are reindexed deterministically as candidate tasks;
4. dependencies between retained tasks remain candidate dependency edges;
5. dependencies from completed predecessors into retained tasks are recorded as already satisfied source predecessors;
6. candidate payload content is bound by a deterministic SHA-256 digest.

The result is a candidate projection, not an activated Plan.

## Candidate successor-plan projection

Each candidate binds the source Plan and targets the next Plan version numerically:

```text
candidate_plan_version = source_plan_version + 1
candidate_plan_generation = Stage-3.7.4 target_plan_generation
candidate_only = true
```

The candidate retains source task and dependency identities/hashes rather than creating new executable planned-task records. Stage 3.7.5 therefore records what a later stage may validate/commit, not a new runtime Plan head.

## Planner invocation evidence

Each generated ReplanCandidate includes a durable `rpinv-*` planner-invocation identity and canonical planner-invocation hash. The invocation binds:

- planner profile/engine/version;
- source ReplanSnapshot ID and SHA-256;
- source task-context SHA-256;
- deterministic execution flag;
- no external context refresh;
- no Governance query;
- generation timestamp.

## Idempotency and cardinality

The schema and service enforce:

```text
one ReplanCandidate per ReplanSnapshot
one ReplanCandidate per adaptation episode
unique planner invocation identity
unique candidate identity
unique (mission_id, idempotency_key)
```

An exact retry returns the durable candidate without appending a second candidate event. Reuse of an idempotency key with different request material fails closed.

## Event lineage and persistence

Migration 049 creates:

```text
mission_replan_candidates
```

A newly generated candidate appends exactly one canonical Mission event:

```text
MISSION_REPLAN_CANDIDATE_GENERATED
```

Repository reconstruction/integrity verifies the candidate contract, candidate hash, source snapshot/hash, task-context hash, source Plan binding, deterministic planner invocation, event binding/cardinality, and persistence-manifest representation.

## API surface

```text
POST /api/missions/{mission_id}/replan-snapshots/{replan_snapshot_id}/candidate
GET  /api/missions/{mission_id}/replan-snapshots/{replan_snapshot_id}/candidate
GET  /api/missions/{mission_id}/replan-candidates
GET  /api/missions/{mission_id}/replan-candidates/{replan_candidate_id}
GET  /api/missions/{mission_id}/deterministic-replan-candidate-generation-definition
```

No Stage-3.7.5 HTTP endpoint exists for replan commit or Plan supersession.

## Authority boundary

Stage 3.7.5 **does perform**:

```text
Stage-3.7.4 ReplanSnapshot integrity verification
source Mission/Plan concurrency verification
deterministic local planner invocation
canonical candidate task/dependency projection
candidate Plan-delta projection
ReplanCandidate contract hashing
candidate persistence
canonical candidate Mission event recording
repository reconstruction/integrity verification
```

Stage 3.7.5 does **not** perform:

```text
external context refresh
new Governance authorization query
free-form/non-deterministic planner generation
successor Plan creation or activation
successor-Plan validation
replan decision or commit
Plan supersession
historical Plan mutation
Mission state transition
routing or delegation
execution dispatch or execution-attempt creation
external target network I/O
target actuation
```

The next planned control is **Stage 3.7.6**.

## Validation status

The focused Stage-3.7.5 proof contains exactly **21 tests** and validates runtime/migration activation, canonical definition, deterministic payload generation and ordering, source-version targeting, no additional Governance/external refresh, no successor-Plan/commit/supersession/dispatch/actuation authority, concurrency guards, caller-content rejection, idempotency/cardinality, persistence/reconstruction, and HTTP surface boundaries.

Build-sandbox validation completed with:

```text
python -m compileall -q mission_orchestrator tests  -> PASS
python -m pytest --collect-only -q                  -> 1257 tests collected
focused Stage 3.7.5                                 -> 21 passed in 19.83s
full Stage 3.1-3.7.5 regression                     -> 1257 passed in 954.19s (15m54s)
Stage-3.7.4 predecessor/head probes                 -> 22 passed in 24.29s
release archive smoke                                -> 75/75 hashes OK; compile PASS; 1257 collected; 21/21 focused PASS
```

Full build-sandbox regression evidence is recorded in `REGRESSION_EVIDENCE_STAGE3_7_5.txt`. Formal target-host acceptance is authoritative only when `STAGE3_7_5_ACCEPTANCE.ps1` terminates with `STAGE 3.7.5 ACCEPTANCE: PASS`.
