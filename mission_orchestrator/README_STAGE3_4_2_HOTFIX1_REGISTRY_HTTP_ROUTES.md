# Stage 3.4.2 Hotfix 1 — Canonical Registry HTTP Routes

## Symptom

`STAGE3_4_2_ACCEPTANCE.ps1` passes the full regression and health checks, then fails at step `[3] Canonical Stage-3.4.1 registry source` with:

`{"status":"error","code":"ROUTE_NOT_FOUND"}`

for `GET /api/subsystem-registry`.

## Root cause

The Stage-3.4.1 service layer already implemented and tested the canonical registry read models (`get_subsystem_registry`, `get_subsystem_registry_definition`, subsystem/capability lookups), and the Stage-3.4.1 README documented their public HTTP paths. However, the corresponding GET route registrations were omitted from `MissionOrchestratorHandler.do_GET`. Service-level tests therefore passed while the real HTTP acceptance probe returned the generic 404 `ROUTE_NOT_FOUND` response.

## Fix

`mission_orchestrator/api_service.py` now registers the documented Stage-3.4.1 read-model endpoints:

- `GET /api/subsystem-registry-definition`
- `GET /api/subsystem-registry`
- `GET /api/subsystems`
- `GET /api/subsystems/{subsystem_id}`
- `GET /api/subsystems/{subsystem_id}/capabilities`
- `GET /api/subsystems/{subsystem_id}/capabilities/{capability_id}`

The change is read-only. It does **not** add runtime endpoint resolution, subsystem health probing, candidate eligibility, route selection, Governance authorization, delegation, dispatch, or target actuation.

A new HTTP regression test exercises all six paths through a real ephemeral `ThreadingHTTPServer`, preventing a future service/API registration drift.

The server startup banner was also corrected from the stale Stage-3.3.10 label to Stage 3.4.2. This banner change is cosmetic only.

## Verification performed

- `python -m compileall -q mission_orchestrator tests` — PASS
- Stage 3.4.1 + 3.4.2 focused tests — `45 passed`
- HTTP registry route regression — PASS for all six documented endpoints

A monolithic full-suite run in the packaging environment exceeded its execution window after substantial progress; no failure was observed before timeout. The user's pre-hotfix source already demonstrated `550 passed`; after applying this hotfix the expected test count is `551` because one regression test was added.

## Deployment

Overlay the hotfix ZIP at `D:\mission_orchestrator`, restart Mission Orchestrator, then run:

```powershell
cd D:\mission_orchestrator
python -m compileall -q mission_orchestrator tests
python -m pytest -q
```

Expected count after this hotfix: `551 passed`.

Then restart Mission Orchestrator if the test command was run while the old process remained active, and execute:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_4_2_ACCEPTANCE.ps1
```

Acceptance step `[3]` should now resolve the persisted canonical registry and proceed to the focused contract proof.
