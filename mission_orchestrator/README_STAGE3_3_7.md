# Stage 3.3.7 — Plan Versioning, Replanning & Supersession

## Purpose

Stage 3.3.7 turns the Stage-3.3 planning output into an append-only, versioned Plan lineage. It activates the first `VALIDATED_FEASIBLE` candidate as Plan version 1, creates deterministic successor versions during canonical Stage-3.2.6 `REPLANNING`, and projects older versions as `SUPERSEDED` without mutating their persisted contracts.

Stage 3.3.7 is a planning-lineage control. It does **not** authorize actions, schedule tasks, dispatch target actions, actuate targets, or move Governance authority into the Mission Orchestrator.

## Active control

- `control_version = stage3.3.7-plan-versioning-replanning-supersession`
- HTTP server = `APTSMissionOrchestrator/3.3.7`
- Plan-version schema = `apts-mission-plan-version-v1`
- Repository migration level = `15`
- Version-vector domain = `plan_versioning_version`

## Canonical semantics

### Initial activation

The first Plan version may be created only while the Mission is in `PLANNING` and only when Stage 3.3.6 has produced an immutable `VALIDATED_FEASIBLE` artifact bound to the current Stage-3.3.5 generated candidate.

The resulting record is:

- Plan version `1`;
- activation type `INITIAL_VALIDATED_PLAN`;
- effective status `ACTIVE`;
- predecessor = none;
- validation lineage = exact Stage-3.3.6 validation identity/hash.

### Replanning successor

A successor Plan may be created only while the Mission is in `REPLANNING` and only when:

- a Stage-3.3.7 active Plan head already exists;
- the caller presents the exact active version and active Plan hash;
- the Mission has a current canonical Stage-3.2.6 `replan_id` lineage;
- the caller presents that exact `replan_id`;
- no successor has already been committed for that replan episode;
- the persisted planning context still passes the Stage-3.3 snapshot consistency guard.

The local deterministic planner is re-invoked from the canonical Stage-3.3 planning artifacts. The successor version is exactly `predecessor + 1`.

## Supersession model

Version rows are append-only. Supersession does not update the old version record. Instead, one mutable CAS-protected head identifies the active Plan:

```text
Mission
  |
  +-- Plan version 1  [persisted immutable] -- effective SUPERSEDED
  |        |
  |        +-- predecessor: none
  |
  +-- Plan version 2  [persisted immutable] -- effective ACTIVE
           |
           +-- predecessor: v1
           +-- replan_id: Stage-3.2.6 lineage

mission_plan_version_heads -> v2
```

On a later replan, v3 is appended and the active head moves from v2 to v3 using optimistic compare-and-swap semantics.

## Lifecycle integration

When a Mission has entered Stage-3.3.7 versioned planning, `REPLANNING -> RUNNING` is fail-closed until the active Stage-3.2.6 replanning episode has a committed `REPLAN_SUCCESSOR` version. Existing Stage-3.2.6 readiness evidence remains required.

This creates the following controlled path:

```text
RUNNING
   |
   +-- REPLAN
   v
REPLANNING
   |
   +-- deterministic planner re-invocation
   +-- append successor Plan vN+1
   +-- active head CAS: vN -> vN+1
   +-- old vN projects SUPERSEDED
   |
   +-- readiness evidence
   v
RUNNING
```

## Persistence

Migration `015_stage3_3_7_plan_versioning_replanning_supersession.sql` adds:

- `mission_plan_versions` — append-only immutable Plan-version contracts;
- `mission_plan_version_heads` — one mutable active head per Mission.

Important uniqueness constraints include:

- one record identity;
- one version number per Mission;
- one idempotency request per Mission;
- at most one successor per `replan_id`.

The repository persistence manifest now includes `plan_versioning_store`, and integrity reconstruction validates the complete contiguous version chain plus active head.

## Event lineage

Stage 3.3.7 adds canonical event types:

- `MISSION_PLAN_VERSION_ACTIVATED`;
- `MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED`.

Exact idempotent replay does not append duplicate events.

## Authority boundary

The following invariants remain mandatory:

```text
PLAN      != AUTHORIZATION
TASK      != DISPATCH
READINESS != PERMISSION
PLANNER   != GOVERNANCE
```

Runtime declarations remain:

- `governance_authorization_authority = EXTERNAL_APTS_GSS`;
- Governance query during Plan versioning = `false`;
- scheduling = `false`;
- external model invocation = `false`;
- external network I/O for replanning = `false`;
- target-action dispatch = `false`;
- target actuation = `false`.

## Regression

Stage 3.3.7 adds `tests/test_stage3_3_7_plan_versioning_replanning_supersession.py` and rebases historical current-control/migration assertions to the new release level.

Validated patch-local results:

```text
428 passed
```

The Stage-3.3.7 focused file contributes 27 collected test cases, including parameterized boundary checks.

## Live acceptance

Run after applying migration 015 and restarting the Mission Orchestrator:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_3_7_ACCEPTANCE.ps1
```

Expected final result:

```text
==============================================================================
STAGE 3.3.7 ACCEPTANCE: PASS
==============================================================================
```
