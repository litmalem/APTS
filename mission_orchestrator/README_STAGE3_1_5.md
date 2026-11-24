# Stage 3.1.5 — Governed Task Routing

## Purpose

Stage 3.1.5 extends the canonical mission contract from definition and Governance binding into **governed high-level subsystem routing**.

The Global Mission Orchestrator (`APTS-MO01`) can now create an immutable, hashed routing-task contract from the exact current:

1. canonical mission envelope (Stage 3.1.1),
2. canonical mission state (Stage 3.1.2),
3. Scope/RoE/Constraint snapshot (Stage 3.1.3), and
4. Governance binding/capability contract (Stage 3.1.4).

The first supported downstream destination is the existing VulnDesk CTI subsystem (`CTI-*`) through:

`POST /api/cti/missions/start`

This stage deliberately routes a **subsystem mission**, not a target action. Target-action authorization, revalidation, and actuation remain outside Mission Orchestrator authority.

## Roadmap naming note

`Canonical Mission State Model` is the Stage-3.1.2 control already present in this repository. Stage 3.1.5 is `Governed Task Routing`; the Stage-3.1.2 state model remains authoritative and is reused by this stage as the lifecycle gate for task creation and dispatch.

## Authority boundary

| Concern | Authority in Stage 3.1.5 |
|---|---|
| Canonical mission identity/envelope | APTS-MO01 |
| Canonical mission lifecycle state | APTS-MO01 |
| Canonical Scope/RoE/Constraints | APTS-MO01 |
| Capability binding definition | APTS-MO01 |
| Policy ALLOW/DENY/REVIEW | **aptsGSS / GOV-PLANE** |
| Approval, revocation, hard-deny, emergency stop | **aptsGSS / GOV-PLANE** |
| High-level subsystem route selection | APTS-MO01, derived from a bound capability |
| CTI subsystem mission execution | VulnDesk / CTI subsystem |
| Target-action authorization/revalidation | **aptsGSS / GOV-PLANE** |
| Target action / actuation | Downstream governed subsystem, not Stage 3.1.5 |

The Mission Orchestrator cannot use this routing path to bypass aptsGSS. Stage 3.1.5 only accepts capabilities whose Stage-3.1.4 binding declares:

- `authorization_mode = NOT_REQUIRED_INTERNAL`, and
- `action_class = INTERNAL_REASONING` or `REPORTING`.

A `REQUIRED` target-action capability is rejected fail-closed by the routing API.

## Core routing invariant

The caller does **not** supply a destination endpoint.

The destination is derived from the immutable Stage-3.1.4 capability `subject_component`. In this release:

- `CTI-*` -> subsystem `CTI`
- dispatch operation -> `CTI_MISSION_START`
- path -> `/api/cti/missions/start`

The destination subsystem must also be declared in the immutable Stage-3.1.1 mission envelope under `required_subsystems`.

This prevents request-time endpoint substitution.

## Governed routing task lifecycle

A Stage-3.1.5 routing task is an immutable contract plus a mutable routing status.

Current statuses used by the runtime include:

- `READY` — canonical task is created and may be dispatched when lifecycle gates permit;
- `DISPATCHED` — the downstream subsystem mission was accepted/recovered;
- `BLOCKED` — a malformed downstream protocol result caused fail-closed blocking.

Dispatch attempts are recorded independently in `mission_task_dispatch_attempts`, including retryable transport failures and response-loss recovery provenance.

### Canonical mission-state gates

Task creation is allowed only while the canonical Stage-3.1.2 mission state is:

- `PLANNING`,
- `RUNNING`, or
- `REPLANNING`.

Actual subsystem dispatch is allowed only in:

- `RUNNING`, or
- `REPLANNING`.

Stage 3.1.5 never silently changes the canonical mission state.

## Create a governed routing task

`POST /api/missions/{mission_id}/routing-tasks`

Representative body:

```json
{
  "idempotency_key": "route-cti-001",
  "capability_id": "orchestrator.route.cti",
  "task_input": {
    "auto_acquire_cti": false,
    "mission_objective": {
      "type": "PENTEST_INTELLIGENCE_ENRICHMENT"
    }
  },
  "requested_by": "mission-controller",
  "reason": "Route the canonical mission to CTI",
  "metadata": {
    "environment": "LAB"
  }
}
```

The immutable task contract captures:

- canonical mission id;
- canonical scope contract id, snapshot id, version, and SHA-256;
- Governance binding id, version, snapshot id, and SHA-256;
- complete bound capability;
- derived routing destination;
- original task input;
- caller/reason/metadata;
- explicit authority and no-target-actuation semantics;
- task-contract SHA-256.

The task identifier uses the `mtask-*` namespace.

## Dispatch a governed routing task

`POST /api/missions/{mission_id}/routing-tasks/{task_id}/dispatch`

There is no caller-provided body for routing or authorization substitution.

Before dispatch the service verifies, fail-closed:

1. task-contract integrity;
2. canonical mission state is `RUNNING` or `REPLANNING`;
3. the current Scope/RoE snapshot is still the task-bound snapshot;
4. the current Governance binding is still current and exactly task-bound;
5. the capability is still non-actuating (`NOT_REQUIRED_INTERNAL`);
6. the task destination is supported;
7. no unrelated downstream CTI mission already occupies the same canonical mission id.

The CTI payload reserves and overwrites lineage fields from the immutable contract:

```json
{
  "mission_id": "mission-gmo-...",
  "global_task_id": "mtask-...",
  "mission_orchestrator_routing": {
    "schema_version": "apts-governed-task-routing-v1",
    "task_id": "mtask-...",
    "task_contract_sha256": "...",
    "scope_snapshot_id": "...",
    "scope_sha256": "...",
    "governance_binding_version": 1,
    "capability_id": "orchestrator.route.cti",
    "source_component": "APTS-MO01"
  }
}
```

Caller-supplied values for these reserved fields cannot override canonical lineage.

## Distributed idempotency and response-loss handling

The routing-task creation API is idempotent by `(mission_id, idempotency_key)` and rejects a conflicting replay.

Only one high-level CTI subsystem mission route is allowed for a canonical mission in Stage 3.1.5.

A dispatch-attempt record is persisted **before** the cross-service POST. If the CTI POST may have committed but the response is lost, Mission Orchestrator immediately reads:

`GET /api/cti/missions/{mission_id}`

If the exact canonical mission now exists, the attempt is recorded as recovered and the task becomes `DISPATCHED`, preventing a duplicate POST in the same operation.

If CTI is unavailable and no committed mission can be confirmed, the attempt is marked `RETRYABLE`, the task remains `READY`, and the request fails closed.

A malformed downstream response marks the attempt `FAILED_CLOSED` and the task `BLOCKED`.

## Read-only routing projection

`GET /api/missions/{mission_id}/routing-projection`

This endpoint reconstructs the global routing view from local immutable routing tasks plus downstream subsystem status. It returns a recommendation but never mutates the Stage-3.1.2 canonical state.

Current projections:

| Projection | Recommended canonical state |
|---|---|
| `UNROUTED` | `PLANNING` |
| `ROUTING_PENDING` | `PLANNING` |
| `SUBSYSTEMS_RUNNING` | `RUNNING` |
| `SUBSYSTEMS_COMPLETED` | `CLEANING_UP` |
| `FAILED` | `FAILED` |

Every response includes `canonical_state_mutated=false`.

## API additions

- `POST /api/missions/{mission_id}/routing-tasks`
- `GET /api/missions/{mission_id}/routing-tasks`
- `GET /api/missions/{mission_id}/routing-tasks/{task_id}`
- `POST /api/missions/{mission_id}/routing-tasks/{task_id}/dispatch`
- `GET /api/missions/{mission_id}/routing-projection`

Important fail-closed HTTP mappings:

- `403 MISSION_TASK_ROUTING_FAIL_CLOSED`
- `404 MISSION_TASK_NOT_FOUND`
- `409 MISSION_TASK_CONFLICT`
- `502 MISSION_SUBSYSTEM_PROTOCOL_ERROR`
- `503 MISSION_SUBSYSTEM_UNAVAILABLE`

Existing Stage-3.1.1 through Stage-3.1.4 APIs remain available.

## Data model

Stage 3.1.5 adds two tables:

- `mission_routed_tasks`
- `mission_task_dispatch_attempts`

Key database guarantees include:

- globally unique `task_id`;
- unique `(mission_id, idempotency_key)`;
- one routed task per `(mission_id, destination_subsystem)` in this stage;
- ordered unique dispatch attempt numbers per task;
- foreign-key lineage back to the canonical mission and routed task.

SQLite creates the tables automatically at repository startup. MariaDB/MySQL uses:

`migrations/005_stage3_1_5_governed_task_routing.sql`

## Runtime configuration

Existing Governance configuration remains:

```text
MISSION_GOVERNANCE_BASE_URL=http://127.0.0.1:8770
MISSION_GOVERNANCE_TIMEOUT_SECONDS=3.0
```

Stage 3.1.5 adds:

```text
MISSION_CTI_BASE_URL=http://127.0.0.1:8765
MISSION_CTI_TIMEOUT_SECONDS=5.0
```

## Health contract

`GET /health` now reports:

- `control_version=stage3.1.5-governed-task-routing`
- `governed_task_routing_schema_version=apts-governed-task-routing-v1`
- `governed_task_routing_mode=BOUND_INTERNAL_CAPABILITY_DERIVED_DESTINATION_FAIL_CLOSED`
- `subsystem_routing_dispatch_enabled=true`
- `supported_routing_subsystems=["CTI"]`
- `routing_projection_mode=READ_ONLY_CROSS_SUBSYSTEM_ROUTING_STATE`
- configured `cti_base_url`

The target-action safety boundary remains explicit:

- `dispatch_enabled=false`
- `target_action_dispatch_enabled=false`
- `target_actuation=false`
- `pre_dispatch_revalidation_required=true`

`subsystem_routing_dispatch_enabled=true` therefore means only that a high-level subsystem mission can be started; it does **not** mean target actions can be dispatched by APTS-MO01.

## Regression coverage

Stage-3.1.5 unit/regression coverage includes:

- route derivation from bound `subject_component`;
- immutable task hashing;
- task idempotency and conflicting replay rejection;
- single CTI subsystem route per global mission;
- rejection of `REQUIRED` target capabilities;
- immutable `required_subsystems` enforcement;
- lifecycle gates for task creation and dispatch;
- stale-scope/Governance-binding rejection;
- exact downstream lineage payload;
- dispatch replay without duplicate CTI mission start;
- response-loss recovery;
- fail-closed CTI outage handling;
- read-only cross-subsystem routing projection;
- preservation of target-action dispatch/actuation boundary.

Current full regression baseline:

```text
61 passed
```

Run:

```powershell
cd D:\mission_orchestrator
python -m pytest -q
```

Then run the real-service acceptance gate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_1_5_ACCEPTANCE.ps1
```
