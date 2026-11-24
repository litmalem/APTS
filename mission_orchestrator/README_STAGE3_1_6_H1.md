# Stage 3.1.6-H1 — Acceptance Race Isolation Hotfix

## Scope

This hotfix changes only `STAGE3_1_6_ACCEPTANCE.ps1`.
No Mission Orchestrator Python source, database schema, Governance source, or VulnDesk/CTI source is changed.

## Why H1 is required

The original Step [11] reused the primary acceptance mission after CTI dispatch. At that point the mission version hash includes live CTI `state_version` and `plan_version` observations. PowerShell `Start-Job` starts separate worker processes and can introduce enough delay for CTI to advance before either POST reaches the Mission Orchestrator. In that case both commands correctly fail closed as stale (`409,409`). That outcome demonstrates external version drift, but it does not test the intended local concurrent-write race.

## H1 behavior

- Step [10] remains unchanged and continues to verify live CTI `state_version` / `plan_version` incorporation.
- Step [11] creates a dedicated race mission that has not dispatched a subsystem task, so its version vector is stable during worker startup.
- Two legal state transitions from the same version are issued concurrently.
- Acceptance requires exactly one HTTP `201` winner and exactly one HTTP `409` stale loser.
- The race command journal must contain exactly one `COMPLETED` and one `REJECTED_STALE` record.
- Step [12] validates the primary mission and race mission journals independently.

## Installation

Replace only:

`D:\mission_orchestrator\STAGE3_1_6_ACCEPTANCE.ps1`

Then run:

```powershell
cd D:\mission_orchestrator
python -m pytest -q

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_1_6_ACCEPTANCE.ps1
```

Expected final line:

`STAGE 3.1.6 ACCEPTANCE: PASS`
