# Phase 2 — Guarded Human Interaction Mission Console

Phase 2 extends the existing Phase-1 read-only Mission Console with bounded human interaction over the canonical Mission lifecycle API. The Web UI remains a client of the Mission Orchestrator control plane; it does not become a second authority and it does not write the Mission database directly.

## Run

```powershell
cd D:\mission_orchestrator
.\.venv\Scripts\python.exe .\run\run_mission_orchestrator.py --host 127.0.0.1 --port 8780
```

Open:

```text
http://127.0.0.1:8780/ui/
```

Or use:

```powershell
.\START_MISSION_CONSOLE_PHASE2.ps1
```

## Human-interaction controls

The Mission Workspace now contains a **Controls** tab. The Web console exposes only this bounded operator set:

```text
START
PAUSE
RESUME
REPLAN
BEGIN_CLEANUP
ABORT
```

A command is enabled only when it is present in the backend `guard_eligible_commands` contract for the mission's current state. The browser does not invent a transition matrix.

Commands such as `FAIL`, `EXPIRE`, `COMPLETE`, `WAIT_FOR_EVIDENCE`, `WAIT_FOR_APPROVAL`, `BIND_PIP`, and `START_PLANNING` remain outside the Phase-2 operator surface even though they may exist in the canonical backend contract.

## Guarded command submission

Before every lifecycle mutation, the browser performs a fresh preflight:

1. re-read the canonical mission state;
2. re-read `/version-vector`;
3. re-read `/lifecycle-command-contract`;
4. verify that the state version and version-vector SHA have not changed;
5. verify that the requested command is still guard-eligible;
6. verify an eligible resume target for `RESUME`;
7. submit one canonical lifecycle command using the fresh expected versions.

No mutation is automatically retried. A backend concurrency/lifecycle conflict is surfaced to the operator and requires an explicit refresh/review.

Every Web command supplies:

```text
command_id
idempotency_key
expected_version_sha256
expected_state_version
actor
reason_code
reason
evidence_refs
metadata
```

`RESUME` additionally supplies `target_state`.

For a `START` transition out of `WAITING_EVIDENCE` or `WAITING_APPROVAL`, the console requires evidence and sends a canonical `dependency_resolution` for the currently active dependency. A `START` transition out of `REPLANNING` also requires evidence of replan readiness.

`ABORT` uses a danger-zone confirmation and requires the operator to type `ABORT` before submission.

## Operator attribution

The UI stores an **Actor ID** locally in the browser for audit attribution and includes it in lifecycle commands. This value is **not authentication**, **not authorization**, and cannot grant a Governance approval.

Production deployment should place the console behind the APTS authenticated operator boundary and derive actor identity from authenticated session/context rather than trusting free-form browser input.

## Governance visibility

Phase 2 adds a read-only Mission governance projection:

```text
GET /api/missions/{mission_id}/governance-visibility
```

It shows, on a best-effort basis:

- current local Mission governance binding;
- Mission authorization bindings;
- authoritative aptsGSS mission correlation snapshot;
- policy-decision references;
- human approval requests and pending-approval count.

The Mission console deliberately provides **no** Governance `ALLOW`/`DENY`, human `APPROVE`/`DENY`, target dispatch, or target-actuation control. Governance remains external authority.

If aptsGSS is unavailable or returns a protocol error, Mission state remains readable and the Governance tab reports the visibility failure without manufacturing an authorization result.

## Phase-1 compatibility

The Phase-1 read models remain available:

```text
GET /api/missions
GET /api/dashboard/summary
GET /api/operator/attention
```

Existing Dashboard, Missions, Plan & Tasks, Timeline, Diagnostics, Subsystems, and System Health screens remain available.

## Validation performed

Focused console tests cover:

- preservation of Phase-1 read models;
- bounded Phase-2 command surface;
- canonical `RUNNING -> PAUSED` lifecycle execution;
- fail-closed stale version-vector conflict;
- read-only Governance visibility and pending human approval projection.

A broader lifecycle/console regression group was also run against the archive baseline.
