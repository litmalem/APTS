# Patch Notes — Governance Operations Console Phase GUI-1

## Scope

Adds a separate PySide6 desktop console to `aptsGSS` without converting the Governance & Safety Plane into an agent and without changing governance authority semantics.

## New GUI functions

1. Dashboard
   - Governance API process/listener state
   - MariaDB connectivity
   - VulnDesk Event API reachability
   - Outbox worker state and backlog
   - Emergency Stop state
2. Components
   - GOV-S01..GOV-S06 and GOV-D01..GOV-D03
   - Shared-process/runtime status
3. Interfaces & Ports
   - Governance-provided HTTP interfaces on GOV_PORT
   - MariaDB consumed interface
   - VulnDesk CTI Event API consumed interface
4. Runtime API control
   - Start API
   - Stop API
   - Restart API
   - External-listener PID discovery with safe ownership check
5. Emergency Control
   - Activate / Release
   - Actor ID + mandatory reason + typed confirmation
6. Transactional Outbox
   - total/pending/failed/delivered counts
   - recent delivery records
   - retry pending/failed

## New files

- `governance_ui/__init__.py`
- `governance_ui/api_client.py`
- `governance_ui/service_supervisor.py`
- `governance_ui/main_window.py`
- `app/interface_catalog.py`
- `run_gui.py`
- `run_gui_windows.bat`
- `run_gui_linux.sh`
- `tests/test_interface_catalog.py`

## Modified files

- `app/main.py`
- `app/repositories.py`
- `requirements.txt`
- `.gitignore`
- `README.md`

## New operational APIs

- `GET /api/governance/runtime/status`
- `GET /api/governance/interfaces`
- `GET /api/governance/outbox/status`

## Database

No SQL migration is required. The GUI reads existing `gov_event_outbox` and `gov_emergency_state` tables through Governance API/repository boundaries.

## Safety decisions

- GOV-S01..GOV-S06 cannot be individually disabled.
- Emergency Stop remains distinct from stopping Governance API.
- Approval actions are intentionally not exposed in Phase GUI-1.
- Secrets such as `GOV_DB_PASSWORD` are not surfaced.
