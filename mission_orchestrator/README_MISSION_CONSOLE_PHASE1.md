# Phase 1 — Read-only Mission Console

This patch adds a same-origin, read-only Web console to the existing Global Mission Orchestrator without changing the authoritative lifecycle/control semantics.

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
.\START_MISSION_CONSOLE_PHASE1.ps1
```

## Phase-1 screens

- Dashboard: mission state KPIs, recent missions, attention queue, source distribution.
- Missions: searchable/filterable canonical mission registry.
- Mission Workspace: Overview, lifecycle state, mission contract/budget/bindings, Plan & Tasks DAG, immutable plan lineage, deterministic timeline, observability diagnostics, raw read-model.
- Subsystems: canonical subsystem registry and capability contracts.
- Diagnostics: operator attention queue.
- System Health: raw orchestrator health contract.

## Added read-only API

```text
GET /api/missions
GET /api/dashboard/summary
GET /api/operator/attention
```

`GET /api/missions` supports:

```text
state=<STATE>
source_system=<SOURCE>
q=<TEXT>
terminal=true|false
limit=1..200
offset>=0
```

## Safety / authority boundary

The Phase-1 console intentionally contains no POST/PUT/PATCH/DELETE controls. It does not create lifecycle commands, authorize actions, call Governance, dispatch work, or write directly to the Mission database. Existing Mission Orchestrator APIs and persisted read models remain authoritative.

Static Web files are served from `/ui/` by the same Mission Orchestrator HTTP service, so no separate Web backend and no CORS configuration are required.
