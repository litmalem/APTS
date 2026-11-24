# Stage 3.5.4 — Idempotent Dispatch & Execution Attempt Identity

## Purpose

Stage 3.5.4 converts the fresh Stage-3.5.3 authoritative execution authorization into a **durable, idempotent dispatch commit** with two stable identities:

```text
xattempt-*  = canonical execution-attempt identity
xenv-*      = immutable dispatch-envelope identity
```

The stage closes the ambiguity between “authorized to execute” and “an execution attempt has been durably committed”. It guarantees that retries, response loss, or repeated client calls cannot create multiple initial dispatch attempts for the same canonical Stage-3.5.1 execution dispatch.

A successful Stage-3.5.4 commit means:

```text
latest Stage-3.5.3 xreval-* == ALLOW
        +
current Mission/Plan/version/dispatch/eligibility provenance still matches
        +
exactly one durable dispatch commit for the xdispatch-* identity
        =
COMMITTED_IDEMPOTENT_PENDING_DELIVERY
        +
stable xattempt-* / xenv-* identities
```

This is **not target delivery** and **not execution start**. Stage 3.5.4 deliberately performs no runtime endpoint resolution, runtime health probe, resource assignment, target network I/O, delivery acknowledgement, execution start, target action dispatch, or target actuation. Those concerns remain outside this stage and begin with Stage 3.5.5.

## Architectural position

```text
Stage 3.5.1  Canonical Execution Dispatch Contract & Identity
      |
      v
Stage 3.5.2  Dispatch Eligibility & Execution Preconditions
      |
      v
Stage 3.5.3  Authoritative Pre-Dispatch Governance Revalidation
      |
      +--> latest xreval-* MUST be ALLOW
      +--> execution_authorized = true
      |
      v
Stage 3.5.4  Idempotent Dispatch & Execution Attempt Identity
      |
      +--> re-read current RUNNING Mission state + version vector
      +--> re-read active Plan head
      +--> verify xdispatch-* integrity + active Plan binding
      +--> verify xelig-* PASSED integrity + dispatch binding
      +--> verify latest xreval-* integrity + ALLOW authorization
      +--> enforce one canonical initial attempt per xdispatch-*
      +--> persist immutable xattempt-* contract
      +--> materialize immutable xenv-* dispatch envelope
      +--> emit MISSION_EXECUTION_ATTEMPT_COMMITTED exactly once
      |
      +--> NO new Governance query
           NO endpoint resolution
           NO health probe
           NO resource assignment
           NO target delivery
           NO delivery acknowledgement
           NO execution start
           NO external target network I/O
           NO target action dispatch
           NO target actuation
      |
      v
Stage 3.5.5  target delivery / acknowledgement / execution-start boundary
```

## Runtime identity

```text
control_version = stage3.5.4-idempotent-dispatch-execution-attempt-identity
server_version  = APTSMissionOrchestrator/3.5.4
repository_migration_level = 30
```

Stage 3.5.4 adds:

```text
migration 030
mission_execution_attempts
MISSION_EXECUTION_ATTEMPT_COMMITTED
```

The execution-control tail is now:

```text
stage3.5.1-canonical-execution-dispatch-contract-identity
stage3.5.2-dispatch-eligibility-execution-preconditions
stage3.5.3-authoritative-pre-dispatch-governance-revalidation
stage3.5.4-idempotent-dispatch-execution-attempt-identity
```

## Canonical contract

Implementation:

```text
mission_orchestrator/execution_attempt.py
```

Key constants:

```text
schema_version = apts-idempotent-dispatch-execution-attempt-v1
execution_attempt_identity_prefix = xattempt-
dispatch_envelope_identity_prefix = xenv-
mode = IDEMPOTENT_DURABLE_DISPATCH_COMMIT_WITH_STABLE_EXECUTION_ATTEMPT_IDENTITY_PENDING_DELIVERY
authority = GLOBAL_MISSION_ORCHESTRATOR_IDEMPOTENT_DISPATCH_COMMIT
allowed_source_states = RUNNING
dispatch_commit_status = COMMITTED_IDEMPOTENT_PENDING_DELIVERY
execution_attempt_status = CREATED_NOT_DELIVERED
```

The contract is canonical-JSON hashed with SHA-256. Caller-supplied attempt identity, envelope identity, runtime endpoint, health result, resource assignment, execution payload, delivery result, acknowledgement result, execution-start result, target-action result, or actuation result is rejected.

## Stable identities

The orchestrator, not the caller, creates both identities:

```text
xattempt-<uuid>
xenv-<uuid>
```

`xattempt-*` identifies the durable initial execution attempt associated with one canonical `xdispatch-*` record. `xenv-*` identifies the immutable logical dispatch envelope that Stage 3.5.5 can later deliver.

The envelope binds:

- Mission id;
- Plan version record/version;
- planned task id and task key;
- Stage-3.5.1 execution dispatch;
- Stage-3.5.2 dispatch eligibility;
- latest Stage-3.5.3 Governance revalidation;
- authoritative PolicyDecision id/hash/version;
- logical subsystem/capability target;
- work context;
- execution authorization evidence.

The runtime endpoint remains `null` at this stage.

## Idempotency semantics

The caller supplies an idempotency key and the service computes a canonical request SHA-256.

```text
same idempotency key + same canonical request
    -> return the same persisted xattempt-*
    -> return the same persisted xenv-*
    -> idempotent_replay = true
    -> no second mission_execution_attempts row
    -> no duplicate MISSION_EXECUTION_ATTEMPT_COMMITTED event
    -> no Governance query
    -> no target delivery

same idempotency key + different canonical request
    -> MISSION_EXECUTION_ATTEMPT_CONFLICT

different idempotency key + same xdispatch-* after initial commit
    -> MISSION_EXECUTION_ATTEMPT_CONFLICT
```

The persistence layer also enforces uniqueness for `(mission_id, idempotency_key)`, `(mission_id, execution_dispatch_id)`, and `(mission_id, execution_dispatch_id, attempt_ordinal)` so concurrency cannot create duplicate initial attempts.

## Freshness and fail-closed commit boundary

Before creating the attempt, Stage 3.5.4 verifies:

- Mission exists and is still `RUNNING`;
- state version still matches the caller's expected state version;
- complete Mission version vector still matches its expected SHA-256;
- active Plan head id/version/hash still matches;
- Stage-3.5.1 `xdispatch-*` exists, verifies, and is bound to the active Plan;
- Stage-3.5.2 `xelig-*` exists, verifies, is `PASSED`, and is bound to that dispatch;
- Stage-3.5.3 `xreval-*` exists, verifies, is bound to the same dispatch/eligibility chain, and is the **latest** revalidation for the eligibility gate;
- the latest Governance decision is `ALLOW` and execution authorization is true.

The repository repeats critical state/Plan/dispatch/eligibility/latest-revalidation checks inside the durable transaction immediately before insert. Any drift fails closed.

## Governance boundary

Stage 3.5.4 consumes the latest authoritative Stage-3.5.3 authorization. It **does not issue a new Governance query**.

This distinction is intentional:

```text
Stage 3.5.3 = authoritative decision / execution authorization
Stage 3.5.4 = durable idempotent attempt identity and logical envelope commit
Stage 3.5.5 = later delivery / acknowledgement / execution-start boundary
```

The `xattempt-*` contract therefore records:

```text
authoritative_governance_query_performed = false
execution_authorized = true
eligible_for_delivery = true
eligible_for_execution_start = false
```

## Persistence and lineage

Migration:

```text
migrations/030_stage3_5_4_idempotent_dispatch_execution_attempt_identity.sql
```

Durable store:

```text
mission_execution_attempts
```

Important uniqueness constraints:

```text
unique execution_attempt_id
unique dispatch_envelope_id
unique (mission_id, idempotency_key)
unique (mission_id, execution_dispatch_id)
unique (mission_id, execution_dispatch_id, attempt_ordinal)
```

Mission event:

```text
MISSION_EXECUTION_ATTEMPT_COMMITTED
```

Repository reconstruction verifies the execution-attempt canonical hash, predecessor hashes, latest Governance authorization semantics, one-attempt-per-dispatch invariant, event linkage, and record cardinality. Tampering with persisted attempt evidence causes repository integrity failure.

## HTTP API

```text
POST /api/missions/{mission_id}/execution-attempts
GET  /api/missions/{mission_id}/execution-attempts
GET  /api/missions/{mission_id}/execution-attempts/{execution_attempt_id}
GET  /api/missions/{mission_id}/execution-attempt-definition
```

POST returns HTTP `201` for the first durable commit and `200` for an idempotent replay.

## Acceptance coverage

Focused proof:

```text
tests/test_stage3_5_4_idempotent_dispatch_execution_attempt_identity.py
```

The 20 focused tests cover runtime activation, canonical definition, stable attempt/envelope identity, no-new-Governance-query semantics, latest-ALLOW requirement, DENY/REVIEW fail-closed behavior, stale state/version/Plan/dispatch/eligibility/revalidation guards, idempotent replay, idempotency-key conflicts, one-attempt-per-dispatch enforcement, forbidden caller-supplied side-effect fields, state-change rejection, repository projection/tamper detection, and restart durability.

Canonical regression inventory after Stage 3.5.4:

```text
856 tests
```


## Final package verification

Package-construction verification completed on the Stage-3.5.4 source tree:

```text
python -m compileall -q mission_orchestrator tests
PASS

python -m pytest --collect-only -q
856 tests collected

python -m pytest -q
856 passed in 552.39s (0:09:12)

independent prior full regression
856 passed in 539.12s (0:08:59)

python -m pytest -q tests/test_stage3_5_4_idempotent_dispatch_execution_attempt_identity.py
20 passed in 30.07s
```

The package is therefore closed at the source/regression level. Deployment acceptance on the target Windows host remains the responsibility of `STAGE3_5_4_ACCEPTANCE.ps1`, because that gate also validates the active runtime on port 8780 and the migrated repository.
