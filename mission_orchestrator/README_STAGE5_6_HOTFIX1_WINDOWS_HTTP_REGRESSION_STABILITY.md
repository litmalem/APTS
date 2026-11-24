# Stage 5.6 HOTFIX1 — Windows HTTP Regression Stability

This hotfix addresses the Windows-only `WinError 10053` localhost transport abort observed
in the Stage-5.6 full historical regression.

It does **not** change Stage-5.6 production runtime or the Stage-5.6/Stage-6 authority boundary.

## Install

Overlay the hotfix tree at:

`D:\mission_orchestrator`

Allow overwrite of:

- `tests\test_stage4_10_pentest_foundation_acceptance_gate.py`
- `tests\test_stage5_6_exploitation_agent.py`
- `tests\_localhost_http.py` (same shared transport helper, included for self-contained install)

No database migration is added. No runtime restart is required solely for this hotfix.

## Verify

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE5_6_HOTFIX1_VERIFY.ps1
```

Then rerun the canonical acceptance:

```powershell
.\STAGE5_6_ACCEPTANCE.ps1
```

The final expected outcome remains:

```text
1957 passed
STAGE 5.6 ACCEPTANCE: PASS
```

The exact elapsed time is environment-dependent.
