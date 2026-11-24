# Stage 3.6.4 — Dependency-Aware Task Completion

## Purpose

Stage 3.6.4 is the first Stage-3.6 control that **accepts a verified terminal task outcome and commits canonical task completion**. It consumes the immutable Stage-3.6.3 `ebind-*` verification, resolves the exact task in the current active Plan, derives that task's prerequisite set from the Plan DAG, and commits one immutable `tcomp-*` record only when every prerequisite already has a valid Stage-3.6.4 completion in the **same active Plan version**.

```text
Stage 3.5.7  xresult-*  execution result + evidence/artifact manifests
       |
       v
Stage 3.6.1  toutcome-* canonical task outcome identity
       |
       v
Stage 3.6.2  telig-*    TERMINAL_SUCCESS + completion eligible
       |
       v
Stage 3.6.3  ebind-*    VERIFIED evidence/artifact reference binding
       |
       v
Stage 3.6.4  tcomp-*    ACCEPTED + dependency-consistent completion commit
       |
       +--> Stage 3.6.5 dependency release / downstream readiness boundary
```

The key Stage-3.6.4 invariant is:

```text
Task T may receive an immutable tcomp-* completion only if:

1. T is the exact task bound by the current active pver-*;
2. T has a valid VERIFIED ebind-* lineage;
3. T is backed by TERMINAL_SUCCESS + completion_eligible=true;
4. every dependency declared by T in the active Plan DAG has its own valid tcomp-*;
5. every dependency tcomp-* belongs to that same active Plan version;
6. the completion request still matches the Mission/Plan concurrency vector.
```

A root task with no prerequisites therefore has `dependency_count = 0` and may complete as soon as its Stage-3.6.3 source lineage is valid. A non-root task fails closed until all declared prerequisites have canonical same-Plan completion records.

## Runtime identity

```text
control_version             = stage3.6.4-dependency-aware-task-completion
server_version              = APTSMissionOrchestrator/3.6.4
repository_migration_level  = 39
persistence_store           = mission_task_completion_commits
identity_prefix             = tcomp-
completion_status           = COMPLETED_DEPENDENCY_CONSISTENT
acceptance_status           = ACCEPTED_FOR_TASK_COMPLETION
dependency_status           = DEPENDENCIES_SATISFIED
next_stage                  = 3.6.5
```

## Canonical contract

Implementation:

```text
mission_orchestrator/task_completion.py
```

Canonical constants:

```text
stage_schema_version = apts-dependency-aware-task-completion-v1
schema_version       = apts-dependency-aware-task-completion-contract-v1
identity_prefix      = tcomp-
mode                 = DETERMINISTIC_DEPENDENCY_AWARE_TASK_COMPLETION_COMMIT_NO_DEPENDENCY_RELEASE_NO_READINESS_RECALCULATION_NO_PLAN_OR_MISSION_PROGRESSION
authority            = MISSION_ORCHESTRATOR_DEPENDENCY_AWARE_TASK_COMPLETION
status               = COMPLETED_DEPENDENCY_CONSISTENT
```

Each completion contract binds:

- Mission ID, Mission state/version and version SHA-256;
- active `pver-*` record, Plan version and Plan canonical SHA-256;
- exact `planned_task_id` and `task_key`;
- exact Stage-3.6.3 `ebind-*` ID and canonical SHA-256;
- exact Stage-3.6.1 `toutcome-*` and Stage-3.6.2 `telig-*` identities carried by the verified binding;
- the dependency keys derived from the active Plan task;
- canonical references to the same-Plan `tcomp-*` records satisfying each dependency;
- a deterministic dependency-binding SHA-256;
- the completion decision and its canonical SHA-256.

## Dependency semantics

Stage 3.6.4 never trusts caller-supplied dependency lists. The prerequisite set comes only from the currently active Plan contract. The service then loads existing completion records for that active Plan and checks the exact dependency keys.

The stage fails closed when:

- an active-Plan dependency key is unknown;
- a prerequisite has no completion record;
- the dependency completion set contains an unexpected task;
- a dependency completion belongs to another or superseded Plan version;
- `planned_task_id`, task key, completion status, or canonical hash is inconsistent;
- the `ebind-*` source is absent, stale, non-VERIFIED, or no longer bound to the active Plan;
- Mission state/version or active-Plan concurrency expectations are stale.

This prevents a completion from one Plan generation from satisfying a dependency in a replanned/superseding Plan merely because the human-readable task key happens to match.

## Authority boundary

Stage 3.6.4 **does perform**:

- deterministic task-outcome acceptance for completion;
- dependency precondition evaluation against the active Plan DAG;
- immutable `tcomp-*` completion commitment;
- durable persistence and exactly-once completion lineage event recording.

Stage 3.6.4 **does not perform**:

- task lifecycle/state transition;
- downstream dependency release;
- readiness recalculation;
- scheduler activation;
- Plan progression;
- Mission-success completion;
- Governance query/re-authorization;
- runtime query/control I/O;
- dispatch/redelivery;
- creation of a new execution attempt;
- new target-action dispatch;
- external network I/O;
- target actuation;
- Mission state transition.

These boundaries are intentional. Completion truth and downstream activation remain separate authorities. Stage 3.6.5 should consume `tcomp-*` records to perform dependency release/readiness effects rather than mutating them inside Stage 3.6.4.

## Persistence

Migration:

```text
migrations/039_stage3_6_4_dependency_aware_task_completion.sql
```

Durable store:

```text
mission_task_completion_commits
```

Important uniqueness constraints include:

- unique `task_completion_id`;
- unique `(mission_id, idempotency_key)`;
- unique `(mission_id, evidence_binding_verification_id)`;
- unique `(mission_id, plan_version, planned_task_id)`.

The final constraint is the exactly-once completion boundary for a specific task in a specific Plan version.

## Event lineage

Stage 3.6.4 registers:

```text
MISSION_TASK_COMPLETION_COMMITTED
```

The event is caused by the immutable `tcomp-*` identity and carries the completion hash plus its Stage-3.6.3 source reference. Idempotent replay does not create a duplicate event.

## API surface

```text
POST /api/missions/{mission_id}/task-completions
GET  /api/missions/{mission_id}/task-completions
GET  /api/missions/{mission_id}/task-completions/{task_completion_id}
GET  /api/missions/{mission_id}/task-completion-definition
```

The POST body accepts only concurrency/source expectations, operator identity/reason, and metadata. Caller-provided dependency lists, acceptance decisions, completion flags, release/readiness/progression instructions, Governance/runtime actions, dispatch, or actuation fields are rejected.

## Verification suite

Stage 3.6.4 adds 20 focused tests covering:

- runtime identity, migration 039 and durable store registration;
- contract/definition boundaries;
- root-task completion;
- exact source binding to Plan + Stage-3.6.1/3.6.2/3.6.3 lineage;
- acceptance and canonical commit semantics;
- stale Mission/Plan/evidence-binding concurrency rejection;
- missing source fail-closed behavior;
- rejection of caller-injected dependency/release/progression fields;
- idempotent replay and idempotency conflict;
- one immutable completion per active-Plan task;
- no Governance/runtime I/O;
- restart reconstruction;
- exactly-once event lineage;
- repository manifest/integrity coverage;
- persisted-row tamper detection;
- API/migration registration;
- active-Plan-aware dependency derivation, including incomplete and superseded dependency rejection.

Canonical inventory after Stage 3.6.4:

```text
1042 tests collected
```

Run authoritative target-host acceptance with:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_6_4_ACCEPTANCE.ps1
```
