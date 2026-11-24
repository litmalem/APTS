# Patch Notes — Governance Operations Console UI Patch 2

Date: 2026-08-14
Target: aptsGSS / Governance & Safety Plane — Phase GUI-1
Scope: Visual/UX refinement only. No database migration and no Governance API contract change.

## Problem addressed

The first GUI build could inherit the Windows/Qt dark system palette while also applying a light QSS background. On dark-theme Windows this produced mixed rendering such as white text on light surfaces, low-contrast tab labels, and buttons that looked disabled even when enabled.

## Changes

1. Added an explicit application light palette in `governance_ui/main_window.py`.
   - Uses Qt `Fusion` style.
   - Explicit Window, Base, Text, ButtonText, Highlight, PlaceholderText, and Disabled roles.
   - Makes rendering deterministic regardless of Windows light/dark theme.

2. Replaced the partial stylesheet with a complete Operations Console stylesheet.
   - High-contrast application title and subtitles.
   - Clear active/inactive tab states with blue accent for selected tabs.
   - Explicit enabled, hover, pressed, and disabled button states.
   - White/light panels instead of host-theme dark panels.
   - High-contrast table cells and headers.
   - Light text editors/input fields with dark text.
   - Improved scrollbar and tooltip rendering.

3. Added semantic button styling.
   - `Start API`, `Refresh`, and `Retry Pending/Failed` use primary accent styling.
   - `ACTIVATE EMERGENCY STOP` uses explicit danger styling.
   - `RELEASE EMERGENCY STOP` uses explicit safe/success styling.
   - Disabled actions remain clearly distinguishable from enabled actions.

4. Added UI object names for maintainable styling.
   - Header, subtitle, footer, panels, info boxes, section titles, and semantic buttons are styled via object names rather than one-off inline styles.

## Architecture impact

None. The following remain unchanged:

- Governance API: `127.0.0.1:8770`
- MariaDB: configured via `.env`
- VulnDesk Event API integration
- GOV-S01..GOV-S06 logical component model
- Emergency Stop semantics
- Outbox semantics
- Process supervision semantics

No SQL migration is required.

## Files changed

- `governance_ui/main_window.py`
- `PATCH_NOTES_GOVERNANCE_GUI_PHASE1_UI2.md`

## Validation performed

- Python compile check: PASS
- Existing pytest regression suite: 12 passed
- No live visual rendering was executed in the build container because PySide6 is not installed there; the patch is intended for the existing local `.venv` where Phase GUI-1 already runs successfully.

## Install on local PC

1. Close `run_gui.py`.
2. Extract the patch ZIP to `D:\aptsGS` and preserve folders.
3. Existing `.env` does not need to be changed.
4. Start again:

```powershell
cd D:\aptsGS
.\.venv\Scripts\activate
python run_gui.py
```

Expected result: the title, tabs, buttons, panels, tables, and text areas remain readable even if Windows is using Dark Mode.
