# Stage 3.4.2 — Task Routing Intent & Candidate Resolution

## Purpose

Stage 3.4.2 is the second control in **Stage 3.4 — Subsystem Routing & Task Delegation**. It converts one exact canonical task from the active Plan into an immutable routing intent and resolves the set of registered subsystem candidates that exactly match the task's declared subsystem/capability requirements.

Stage 3.4.2 answers only:

1. **What routing requirement is canonically implied by this READY task?**
2. **Which registered subsystem capability contracts match that requirement exactly?**

It does **not** determine whether a candidate is eligible, does **not** rank/select a route, does **not** query Governance, and does **not** delegate or execute the task.

## Active control

- `control_version = stage3.4.2-task-routing-intent-candidate-resolution`
- HTTP server = `APTSMissionOrchestrator/3.4.2`
- repository migration level = `19`
- routing-intent schema = `apts-task-routing-intent-candidate-resolution-v1`
- routing-intent id prefix = `rint-`
- candidate-resolution mode = `EXACT_REQUIRED_CAPABILITY_AND_REQUIRED_SUBSYSTEM`
- allowed source Mission states = `PLANNING`, `REPLANNING`

## Canonical flow

```text
ACTIVE PLAN VERSION
        |
        v
Stage 3.3.8 active readiness projection
        |
        +-- task != READY ----------> FAIL CLOSED
        |
        v
Exact planned_task_id
        |
        v
required_subsystem + required_capability
        |
        v
Stage 3.4.1 canonical registry
        |
        v
exact subsystem/capability/schema matching
        |
        v
IMMUTABLE ROUTING INTENT + CANDIDATE SET
```

## Routing intent source-of-truth

The caller cannot supply routing authority fields. Stage 3.4.2 derives routing requirements from durable canonical artifacts:

- active Stage-3.3.7 Plan version;
- active Stage-3.3.8 readiness projection;
- exact `planned_task_id`;
- Stage-3.4.1 canonical subsystem registry.

The request is allowed to carry only concurrency/idempotency binding, the exact planned task id, actor/reason, and metadata. Caller-supplied route/authorization/execution surfaces are rejected.

Forbidden examples include:

```text
required_capability
required_subsystem
candidates
eligible
selected_subsystem
endpoint
health
resource_assignment
authorization
delegation
dispatch
target_action
```

## READY guard

Stage 3.4.2 requires the exact task to be represented once in the active readiness projection with:

```text
readiness_status = READY
structurally_ready = true
```

A `BLOCKED_DEPENDENCY` task fails closed. The readiness projection and active Plan must agree on the task's `required_subsystem` and `required_capability`.

## Candidate resolution

Resolution is deterministic and registry-local. A candidate is emitted only when all of the following hold:

```text
capability_id == planned_task.required_capability
subsystem_id  == planned_task.required_subsystem
subsystem registration = REGISTERED + enabled
capability registration = REGISTERED + enabled
planned-task schema accepted by subsystem contract
planned-task schema accepted by capability contract
capability match mode = EXACT_CAPABILITY_ID
```

A candidate record includes canonical subsystem/capability identity, contract hashes, exact-match evidence, and explicit unknown runtime availability:

```json
{
  "runtime": {
    "endpoint_resolved": false,
    "health_probed": false,
    "availability": "UNKNOWN_NOT_PROBED"
  }
}
```

Zero matches are represented explicitly as:

```text
resolution_status = NO_REGISTERED_CANDIDATE
candidate_count   = 0
```

This is not an eligibility failure; eligibility belongs to Stage 3.4.3.

## Immutable contract and persistence

Stage 3.4.2 persists one immutable routing intent per:

```text
(mission_id, plan_version, planned_task_id)
```

Migration `019_stage3_4_2_task_routing_intent_candidate_resolution.sql` adds:

```text
mission_task_routing_intents
```

The store is included in the canonical per-Mission persistence manifest and is reconstructed and integrity-checked after restart.

The routing-intent contract is SHA-256 bound and binds to:

- Mission id;
- source Mission state/version vector;
- active Plan version record/version/hash;
- active readiness projection id/hash;
- exact planned task id/key/type;
- required subsystem/capability;
- canonical subsystem-registry hash;
- deterministic candidate-resolution result.

## Idempotency and conflict control

Exact replay with the same `idempotency_key` and canonical request returns the same immutable intent without adding another event.

A different request attempting to create another authoritative routing intent for the same task and Plan version fails closed.

## Event lineage

Successful creation emits:

```text
MISSION_TASK_ROUTING_CANDIDATES_RESOLVED
```

The event records the routing intent id, Plan-version binding, task identity, required subsystem/capability, resolution status, and candidate count.

## API

```text
POST /api/missions/{mission_id}/task-routing-intents
GET  /api/missions/{mission_id}/task-routing-intents
GET  /api/missions/{mission_id}/task-routing-intents/{routing_intent_id}
GET  /api/missions/{mission_id}/task-routing-intent-definition
```

## Authority boundary

Stage 3.4.2 intentionally advertises:

```text
candidate_is_eligibility_decision         = false
eligibility_gate_performed                = false
route_selection_performed                 = false
route_ranking_performed                   = false
selected_subsystem                        = null
runtime_endpoint_resolution_performed     = false
runtime_health_probe_performed            = false
resource_assignment_performed             = false
governance_query_performed                = false
authorization_granted                     = false
delegation_performed                      = false
dispatch_performed                        = false
target_action_dispatch_enabled            = false
target_actuation                          = false
version_vector_extension_performed        = false
```

Governance authorization authority remains:

```text
EXTERNAL_APTS_GSS
```

Canonical boundary:

```text
CANDIDATE != ELIGIBLE
CANDIDATE != SELECTED ROUTE
ROUTING INTENT != AUTHORIZATION
ROUTING INTENT != DELEGATION
ROUTING INTENT != EXECUTION
```

## Tests

Focused Stage 3.4.2 coverage: **26 tests**.

Combined Stage 3.4.1 + 3.4.2 coverage: **44 tests**.

Key cases include:

- active control/migration declarations;
- exact READY-task guard;
- exact CTI candidate resolution;
- zero-candidate outcome;
- required-subsystem mismatch exclusion;
- deterministic resolution;
- route/authorization/dispatch injection rejection;
- stale version/Plan/readiness CAS rejection;
- idempotent replay;
- one immutable intent per task/Plan version;
- restart reconstruction;
- persistence-manifest integration;
- tamper detection;
- event-lineage binding;
- API surface;
- migration-019 contract;
- preservation of no eligibility/selection/Governance/delegation/dispatch authority.

## Acceptance

With Mission Orchestrator running on port `8780`:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_4_2_ACCEPTANCE.ps1
```

Expected final result:

```text
STAGE 3.4.2 ACCEPTANCE: PASS
```

## Definition of Done

Stage 3.4.2 is complete when an exact canonical READY task from the active Plan can be transformed into one immutable, hash-verifiable routing intent; candidate subsystems can be resolved deterministically from the canonical registry using exact subsystem/capability/schema compatibility; zero-candidate outcomes are explicit; the artifact survives restart and participates in repository integrity; and no Stage-3.4.3 eligibility, Stage-3.4.4 route selection, Governance authorization, delegation, dispatch, or target actuation authority has been introduced.
