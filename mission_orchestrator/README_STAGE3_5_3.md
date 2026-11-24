# Stage 3.5.3 — Authoritative Pre-Dispatch Governance Revalidation

## Purpose

Stage 3.5.3 converts the durable Stage-3.5.2 `xelig-*` eligibility result into a **fresh, authoritative, fail-closed Governance decision** immediately before any later runtime-dispatch stage may proceed.

A positive Stage-3.5.3 result means:

```text
ALLOW from authoritative APTS GSS
        +
all Stage-3.5.2 static/durable preconditions revalidated as current
        =
AUTHORIZED_BY_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE
```

This is an **execution authorization**, but it is still **not a dispatch**. Stage 3.5.3 deliberately performs no runtime endpoint resolution, runtime health probe, resource assignment, target network I/O, dispatch attempt, or target actuation.

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
      +--> re-read current RUNNING Mission state + version vector
      +--> re-read active Plan head + readiness projection
      +--> re-verify xdispatch-* integrity/provenance
      +--> re-verify xelig-* integrity/provenance
      +--> re-read delegation / route / ownership chain
      +--> re-read current Scope + Governance binding
      +--> re-read recovery controls + canonical subsystem registry
      +--> re-evaluate Stage-3.5.2 static preconditions
      +--> verify authoritative Governance scope still matches binding
      +--> issue/recover exactly one authoritative PolicyDecision operation
      +--> persist immutable append-only xreval-* evidence
      +--> emit MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED
      |
      +--> ALLOW  -> execution authorization = true
      +--> DENY   -> execution authorization = false (fail closed)
      +--> REVIEW -> execution authorization = false (fail closed)
      |
      +--> NO endpoint resolution
           NO health probe
           NO resource assignment
           NO dispatch attempt
           NO target network I/O
           NO target actuation
      |
      v
Later Stage 3.5.x: runtime resolution / dispatch controls
```

## Runtime identity

```text
control_version = stage3.5.3-authoritative-pre-dispatch-governance-revalidation
server_version  = APTSMissionOrchestrator/3.5.3
repository_migration_level = 29
```

Stage 3.5.3 adds:

```text
migration 029
mission_pre_dispatch_governance_revalidations
MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED
```

## Canonical contract

Implementation:

```text
mission_orchestrator/pre_dispatch_governance.py
```

Key constants:

```text
schema_version = apts-authoritative-pre-dispatch-governance-revalidation-v1
identity_prefix = xreval-
operation_prefix = xreval-op-
mode = AUTHORITATIVE_PRE_DISPATCH_FAIL_CLOSED
authority = EXTERNAL_APTS_GSS
action_class = TASK_EXECUTION
action_name = AUTHORIZE_EXECUTION_DISPATCH
resource_type = SUBSYSTEM_CAPABILITY
allowed_source_states = RUNNING
```

The `xreval-*` evidence is immutable, canonical-JSON hashed with SHA-256, and append-only per Stage-3.5.2 eligibility gate.

## Freshness and serialization boundary

Stage 3.5.3 does not trust the earlier Stage-3.5.2 result as sufficient authority. Before the Governance query, the service re-reads and verifies the current canonical artifacts while Mission mutation is serialized. The authoritative query is also executed inside the Governance serialization lock.

The boundary therefore protects against stale authorization caused by intervening changes in:

- Mission state/state version;
- Mission version vector;
- active Plan head;
- Stage-3.5.1 dispatch identity;
- Stage-3.5.2 eligibility evidence;
- task readiness;
- delegation delivery/ACK/ownership;
- route/delegation authorization;
- Scope or Governance binding;
- recovery-control set;
- canonical subsystem registry/capability state.

If any refreshed prerequisite fails, the Governance PolicyDecision query is not issued.

## Authoritative Governance binding

Immediately before authorization, Stage 3.5.3 retrieves the authoritative Governance scope and verifies that the returned scope contract id, scope version, and contract hash still match the immutable Mission Governance binding.

Only then may the service evaluate:

```text
action_class  = TASK_EXECUTION
action_name   = AUTHORIZE_EXECUTION_DISPATCH
resource_type = SUBSYSTEM_CAPABILITY
resource      = <subsystem_id>:<capability_id>
```

The decision is validated against the Mission id, scope contract, scope version, and policy set.

## Decision semantics

```text
ALLOW
  -> AUTHORIZED_BY_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE
  -> execution_authorized = true
  -> eligible_for_execution = true

DENY
  -> DENIED_BY_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE
  -> execution_authorized = false
  -> eligible_for_execution = false

REVIEW / requires human approval
  -> REVIEW_REQUIRED_BY_AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE
  -> execution_authorized = false
  -> eligible_for_execution = false
```

In all three cases:

```text
dispatch_authorized = false
authorization_is_dispatch = false
runtime_endpoint_resolution_performed = false
runtime_health_probe_performed = false
resource_assignment_performed = false
dispatch_attempt_started = false
dispatch_performed = false
external_target_network_io_performed = false
target_action_dispatch_enabled = false
target_actuation = false
version_vector_extension_performed = false
```

## Idempotency and response-loss recovery

The caller supplies an idempotency key. Stage 3.5.3 derives a canonical request SHA-256 and deterministic `xreval-op-*` operation id.

Semantics:

```text
same idempotency key + same canonical request
    -> replay persisted xreval-* result
    -> no duplicate Governance query
    -> no duplicate row
    -> no duplicate lineage event

same idempotency key + different canonical request
    -> conflict
```

If the authoritative Governance service commits a PolicyDecision but the response is lost, the Mission Orchestrator can recover the previously committed decision by operation id and persist the local `xreval-*` record without issuing a second authoritative authorization decision.

## Persistence and lineage

Migration:

```text
migrations/029_stage3_5_3_authoritative_pre_dispatch_governance_revalidation.sql
```

Durable store:

```text
mission_pre_dispatch_governance_revalidations
```

Important uniqueness constraints:

```text
unique pre_dispatch_revalidation_id
unique (mission_id, idempotency_key)
unique (mission_id, dispatch_eligibility_id, revalidation_sequence)
```

Mission event:

```text
MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATED
```

Repository reconstruction verifies the canonical `xreval-*` hash, predecessor references, Governance-decision semantics, authorization semantics, persistence cardinality, and lineage event linkage. Tampering causes repository integrity failure.

## HTTP API

```text
POST /api/missions/{mission_id}/pre-dispatch-governance-revalidations
GET  /api/missions/{mission_id}/pre-dispatch-governance-revalidations
GET  /api/missions/{mission_id}/pre-dispatch-governance-revalidations/{pre_dispatch_revalidation_id}
GET  /api/missions/{mission_id}/pre-dispatch-governance-revalidation-definition
```

Caller-supplied Governance decisions, authorization results, runtime endpoints, health results, resource assignments, execution payloads, dispatch attempts, target actions, and actuation fields are rejected. Those outcomes are derived from canonical state and the authoritative Governance response.

## Acceptance coverage

Focused proof:

```text
tests/test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation.py
```

The 19 tests cover runtime activation, canonical definition, ALLOW authorization, exactly-one fresh Governance query, DENY, REVIEW/human-approval fail-closed behavior, forbidden caller-supplied authority fields, stale state/version/Plan/eligibility guards, idempotent replay, idempotency conflicts, append-only repeated revalidation, Governance-unavailable behavior, response-loss recovery, state-change rejection, authoritative scope drift, repository projection, and tamper detection.

Canonical regression inventory after Stage 3.5.3:

```text
836 tests
```
