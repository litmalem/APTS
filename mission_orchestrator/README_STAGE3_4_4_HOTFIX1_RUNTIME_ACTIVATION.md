# Stage 3.4.4 Hotfix-1 — Runtime Activation / Acceptance Preflight

## Why this hotfix exists
The Stage-3.4.4 source regression can pass while port 8780 is still served by an older Mission Orchestrator process that was started before the Stage-3.4.4 files were installed. In that case `/health.control_version` remains at the old control and live acceptance correctly fails.

## Changes
- `STAGE3_4_4_ACCEPTANCE.ps1` now performs a **runtime activation preflight before the 6+ minute full regression**.
- The preflight prints the observed and expected `control_version` and gives an explicit stale-listener restart instruction.
- `mission_orchestrator/api_service.py` startup banner now correctly identifies **Stage 3.4.4 — Deterministic Route Selection & Decision Record** instead of the stale Stage-3.4.3 banner.
- No route-selection semantics, persistence schema, authority boundary, or API contract is changed.

## Required operational step
After applying Stage 3.4.4, stop the process currently listening on port 8780 and start Mission Orchestrator from the updated repository:

```powershell
cd D:\mission_orchestrator
$listener = Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue
if ($listener) { Stop-Process -Id $listener.OwningProcess -Force }
python .\run\run_mission_orchestrator.py --host 127.0.0.1 --port 8780
```

Run acceptance from a second PowerShell window. Before doing so, verify:

```powershell
(Invoke-RestMethod http://127.0.0.1:8780/health).control_version
```

Expected:

```text
stage3.4.4-deterministic-route-selection-decision-record
```
