# Phase 3 — Advanced Operations Mission Console

Phase 3 extends the existing Phase-1 read-only console and Phase-2 guarded lifecycle interaction with advanced **read-side operational tooling**. The Mission Orchestrator remains the control-plane authority for canonical mission state, while aptsGSS remains the external Governance/approval authority.

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
.\START_MISSION_CONSOLE_PHASE3.ps1
```

## Phase-3 capabilities

### 1. Live Mission Event Stream (SSE)

```text
GET /api/missions/{mission_id}/events/stream
```

Features:

- Server-Sent Events over the canonical persisted mission-event log;
- `Last-Event-ID` / `after` cursor support;
- bounded polling and stream rotation for reconnect safety;
- heartbeat comments;
- no database mutation, Governance decision, dispatch, or target actuation;
- `once=1` mode for deterministic smoke tests.

### 2. Immutable Plan Version Diff

```text
GET /api/missions/{mission_id}/plan-diff?from=1&to=2
```

The diff compares candidate-plan material inside immutable plan-version artifacts and reports:

- added/removed/modified tasks;
- per-field task changes;
- added/removed dependency edges;
- content-equivalence by candidate-plan SHA-256.

### 3. Interactive Causal Graph

The UI renders the existing Stage-3.8 canonical causal-lineage graph as a dependency-free interactive SVG. Clicking a node exposes its event identity, parent/causation links, and integrity material.

Authoritative source remains:

```text
GET /api/missions/{mission_id}/observability-causal-graph
```

### 4. Evidence Browser

```text
GET /api/missions/{mission_id}/evidence-browser
```

The evidence index is projected from the deterministic forensic evidence bundle and groups:

- execution result captures;
- evidence-binding verifications;
- task outcomes;
- mission outcome aggregations;
- completion declarations;
- execution attempts.

The UI provides category filtering and a canonical-record inspector. It never edits or re-attests evidence.

### 5. Forensic Reconstruction Workspace

Uses the existing read-only Stage-3.8 APIs:

```text
GET /api/missions/{mission_id}/forensic-reconstruction
GET /api/missions/{mission_id}/forensic-evidence-bundle
```

The UI surfaces reconstruction verification, rebuilt event count, mission state, active plan, execution/task-outcome/replan material, diagnostics, bundle identity, and record counts.

### 6. Mission Comparison

```text
GET /api/mission-comparison?left={mission_id}&right={mission_id}
```

Compares two canonical mission projections side-by-side across:

- mission state/state version;
- active and total plan versions;
- planned/completed tasks;
- mission event count;
- execution attempts;
- replan commits;
- observability health;
- blocking diagnostics findings.

Numeric deltas are reported as **right minus left**.

### 7. Prioritized Operator Attention Queue

```text
GET /api/operator/attention/advanced?limit=100
```

The Phase-1 attention-state projection is enriched with read-only observability diagnostics and severity ranking. Typical priorities:

- `CRITICAL`: failed mission or blocking integrity finding;
- `HIGH`: waiting for Governance approval/evidence or degraded observability;
- `MEDIUM`: paused or replanning mission.

The queue returns recommendations for operator inspection only. It does not grant authorization or execute lifecycle actions automatically.

## Authority invariants preserved

Phase 3 does **not** introduce a new authority plane.

- no direct Mission database writes from Web UI;
- no Governance `ALLOW`/`DENY`/`REVIEW` mutation;
- no human approval decision from Mission Web;
- no target dispatch or target actuation from advanced-operation read models;
- Phase-2 lifecycle commands remain bounded to `START`, `PAUSE`, `RESUME`, `REPLAN`, `BEGIN_CLEANUP`, and `ABORT` and still use canonical lifecycle/version guards;
- no automatic retry of stale lifecycle mutations.

## Validation

Performed on the packaged baseline:

```text
python compile (api_service.py, service.py, governance_binding.py): PASS
node --check mission_web/app.js: PASS

Phase 1 + Phase 2 + Phase 3 console tests:
10 passed

Lifecycle + console regression group:
39 passed

Stage-3.8 observability/forensic regression group (3.8.1 through 3.8.9):
71 passed

HTTP SSE smoke:
200 text/event-stream
stream_ready -> stream_end (once=1)
```
