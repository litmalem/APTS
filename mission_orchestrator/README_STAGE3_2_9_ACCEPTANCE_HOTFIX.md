# Stage 3.2.9 Acceptance Hotfix — RUN Activation Evidence Field

## Scope

Acceptance-artifact-only hotfix. No Mission Orchestrator runtime code, database schema, lifecycle semantics, or test baseline changes.

## Root cause

`STAGE3_2_9_ACCEPTANCE.ps1` gate [6] checked:

```powershell
$run.lifecycle_command_result.planning_run_activation.activation_kind -eq "RUN"
```

The canonical Stage-3.2.4 evidence schema never defines `activation_kind`. Its established fields are:

- `phase = "RUNNING"`
- `activation_command = "START"`
- `activation_ready = true`
- `planning_activation_proof.valid = true`

The runtime response was correct; the acceptance assertion referenced a non-existent field.

## Correction

Gate [6] now validates the canonical Stage-3.2.4 evidence contract and also rechecks planner/Governance/target-execution boundaries.

## Validation

- Python compile: PASS
- Full regression: `255 passed`
- Direct Stage-3.2.9 event-path check confirms all corrected RUN activation evidence assertions evaluate true.

## Install

Replace only:

`D:\mission_orchestrator\STAGE3_2_9_ACCEPTANCE.ps1`

No service restart is required because runtime code is unchanged.

Then run:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE3_2_9_ACCEPTANCE.ps1
```
