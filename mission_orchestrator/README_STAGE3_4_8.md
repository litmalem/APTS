# Stage 3.4.8 — Retry, Fallback, Reassignment & Conflict Control

## Purpose

Stage 3.4.8 is the eighth control in **Stage 3.4 — Subsystem Routing & Task Delegation**. It consumes an immutable Stage-3.4.7 delivery/acknowledgement/ownership receipt and adds an append-only, fail-closed control layer for bounded retry, deterministic fallback proposal, deterministic reassignment proposal, and ownership-conflict freeze.

The stage answers four operational questions without crossing the execution boundary:

1. May the current canonical owner receive another bounded retry admission?
2. If retry should stop, which alternate subsystem/capability is the next deterministic candidate from the immutable Stage-3.4.4 ranked eligible set?
3. Can a reassignment proposal be recorded without silently transferring ownership?
4. Can conflicting recovery activity be frozen fail-closed with an auditable predecessor chain?

Stage 3.4.8 **does not** resolve a runtime endpoint, probe runtime health, allocate a worker/resource, perform external network I/O, dispatch work, authorize execution, issue a target command, actuate a target, or perform a new Governance query.

## Architectural position

```text
Stage 3.4.1 Canonical Subsystem Registry & Capability Contract
        |
Stage 3.4.2 Task Routing Intent & Candidate Resolution
        |
Stage 3.4.3 Routing Eligibility & Compatibility Gate
        |
Stage 3.4.4 Deterministic Route Selection & Decision Record
        |
Stage 3.4.5 Governance-Bound Delegation Authorization
        |
Stage 3.4.6 Canonical Delegation Contract & Handoff Envelope
        |
Stage 3.4.7 Delegation Delivery, Acknowledgement & Ownership
        |
Stage 3.4.8 Retry, Fallback, Reassignment & Conflict Control
        |
        +--> control-plane evidence only
             no dispatch / no execution / no target actuation
```

The Stage-3.4.7 ownership receipt remains the authoritative current owner. A Stage-3.4.8 fallback or reassignment result is only a **proposal**. It cannot mutate Stage-3.4.6/3.4.7 records and cannot become ownership by itself.

## Runtime identity

```text
control_version = stage3.4.8-retry-fallback-reassignment-conflict-control
server_version  = APTSMissionOrchestrator/3.4.8
repository_migration_level = 25
schema_version = apts-canonical-delegation-retry-fallback-reassignment-conflict-control-v1
store = mission_delegation_recovery_controls
event = MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED
```

## Canonical actions

| Action | Meaning | Result boundary |
|---|---|---|
| `RETRY_CURRENT_OWNER` | Admit another retry for the existing Stage-3.4.7 owner | Maximum 3 admitted retries; no dispatch occurs here |
| `FALLBACK_NEXT_ELIGIBLE` | Derive the next candidate from the immutable Stage-3.4.4 ranked eligible set | Proposal only; requires route reselection, fresh Governance authorization, and a new delegation/handoff |
| `REASSIGN_NEXT_ELIGIBLE` | Derive the next candidate as a reassignment proposal | Proposal only; no ownership transfer occurs here |
| `FREEZE_OWNERSHIP_CONFLICT` | Freeze the recovery chain fail-closed | Blocks subsequent recovery controls for that ownership receipt |

## Retry semantics

The canonical retry budget is:

```text
MAX_RETRY_ATTEMPTS = 3
```

The first three retry controls produce `RETRY_ADMITTED_CURRENT_OWNER`. A fourth retry request is materialized as `RETRY_BUDGET_EXHAUSTED_FAIL_CLOSED`; any later retry against the same Stage-3.4.7 ownership receipt is rejected fail-closed.

Retry is an admission/control-plane fact only. It is explicitly **not** a dispatch attempt.

## Fallback and reassignment semantics

Fallback and reassignment candidates are never accepted from caller input. The candidate is derived only from:

```text
IMMUTABLE_STAGE344_RANKED_ELIGIBLE_CANDIDATES_ONLY
```

The current owner is located in the immutable Stage-3.4.4 ranking and the next higher-ranked eligible candidate is selected deterministically. No new registry expansion, runtime health query, endpoint lookup, or resource scheduling is performed.

When an alternate candidate exists, Stage 3.4.8 records:

```text
ownership_transition_pending = true
ownership_transfer_performed = false
route_reselection_required = true
fresh_governance_authorization_required = true
new_delegation_handoff_required = true
```

If no alternate candidate exists, the outcome is `NO_ALTERNATE_ELIGIBLE_CANDIDATE_FAIL_CLOSED`.

## Conflict control

Each recovery chain is scoped to one immutable Stage-3.4.7 `delivery_receipt_id`.

Concurrency is controlled by:

```text
expected_control_count
+ repository transactional sequence guard
+ immutable predecessor id/hash binding
```

Every control after the first binds the immediately preceding recovery-control ID and SHA-256. A stale `expected_control_count` fails closed. Once `FREEZE_OWNERSHIP_CONFLICT` is recorded, later controls for that ownership receipt are rejected.

If a fallback/reassignment proposal is already pending, conflicting retry/fallback/reassignment activity is blocked; only a conflict-freeze action may follow.

## Immutable source bindings

Every Stage-3.4.8 contract binds the exact:

- current Mission state and `state_version`;
- Mission version-vector SHA-256;
- active Plan version record and Plan SHA-256;
- Stage-3.4.4 route decision and SHA-256;
- Stage-3.4.6 delegation and SHA-256;
- Stage-3.4.6 handoff-envelope SHA-256;
- Stage-3.4.7 delivery/ownership receipt and SHA-256;
- previous Stage-3.4.8 recovery-control ID/SHA-256, when present.

The current Mission scope and Governance binding are also checked before a recovery control is accepted. Stage 3.4.8 does not revive a stale ownership chain.

## Canonical request

POST:

```text
/api/missions/{mission_id}/delegation-recovery-controls
```

Required request fields:

```json
{
  "idempotency_key": "stage348-...",
  "expected_version_sha256": "<64 hex>",
  "expected_state_version": 1,
  "expected_active_plan_version_record_id": "pver-...",
  "expected_active_plan_version": 1,
  "expected_active_plan_sha256": "<64 hex>",
  "expected_route_decision_id": "rdec-...",
  "expected_route_decision_sha256": "<64 hex>",
  "expected_delegation_id": "deleg-...",
  "expected_delegation_sha256": "<64 hex>",
  "expected_delivery_receipt_id": "drecv-...",
  "expected_delivery_receipt_sha256": "<64 hex>",
  "expected_control_count": 0,
  "control_action": "RETRY_CURRENT_OWNER",
  "requested_by": "APTS-MO01",
  "reason": "optional explanation",
  "metadata": {}
}
```

Caller-supplied candidate/recipient overrides, runtime endpoint/health, resource assignment, Governance decision, dispatch flags, execution authorization, command payload, and target-action fields are rejected.

## Read APIs

```text
GET /api/missions/{mission_id}/delegation-recovery-controls
GET /api/missions/{mission_id}/delegation-recovery-controls/{recovery_control_id}
GET /api/missions/{mission_id}/delegation-recovery-control-definition
```

## Persistence and lineage

Migration 025 adds append-only store:

```text
mission_delegation_recovery_controls
```

The store enforces unique recovery-control identity, mission/idempotency uniqueness, and per-ownership-receipt control sequence uniqueness. SQLite and MySQL paths both apply transactional sequence guards.

Each accepted control appends:

```text
MISSION_TASK_DELEGATION_RECOVERY_CONTROL_RECORDED
```

The event records the action/outcome, current owner, proposed candidate when applicable, conflict state, and explicit `false` values for ownership transfer, Governance query, dispatch, execution authorization, target-action dispatch, and target actuation.

## Authority and execution boundary

Stage 3.4.8 preserves these invariants:

```text
ownership_transfer_performed = false
runtime_endpoint_resolution_performed = false
runtime_health_probe_performed = false
resource_assignment_performed = false
external_network_io_performed = false
governance_query_performed = false
dispatch_performed = false
execution_authorized = false
target_action_dispatch_enabled = false
target_actuation = false
pre_dispatch_governance_revalidation_required = true
version_vector_extension_performed = false
```

The Stage-3.4.5 authorization remains pre-delegation evidence. Any later execution/dispatch stage must obtain authoritative pre-dispatch Governance revalidation.

## Acceptance evidence in the build environment

Validation completed using partitioned regression processes to avoid cross-test process interference in the Linux build harness:

```text
Python compile                     PASS
Stage 3.1                          111 passed
Stage 3.2                          156 passed
Stage 3.3                          239 passed
Stage 3.4.1                        19 passed
Stage 3.4.2                        26 passed
Stage 3.4.3                        35 passed
Stage 3.4.4                        50 passed
Stage 3.4.5                        30 passed
Stage 3.4.6                        32 passed
Stage 3.4.7                        19 passed
Stage 3.4.8 focused                28 passed
--------------------------------------------
Exhaustive partitioned total       745 passed
```

The Windows acceptance harness additionally runs `python -m pytest -q` as the canonical full-suite gate on the target runtime.
