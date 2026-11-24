param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage4.8-governance-scope-roe-enforcement"
$ExpectedPentestMigration = 6
$ExpectedInventory = 1748

Write-Host "=============================================================================="
Write-Host "Stage 4.8 - Governance, Scope & Rules-of-Engagement Enforcement"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains authoritative"

Write-Host "`n[1] Stage 4.8 runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if (-not $health.stage4_8_scope_validator_enabled -or -not $health.stage4_8_roe_enforcement_enabled) { throw "Stage 4.8 enforcement is not active" }
if ($health.stage4_8_authorization_minting_enabled -or $health.stage4_8_execution_intake_enabled -or $health.stage4_8_tool_invocation_enabled -or $health.stage4_8_target_actuation) { throw "Stage 4.8 crossed authority/execution boundary" }
if ($health.stage4_8_next_stage -ne "4.9") { throw "Stage 4.8 next stage mismatch" }
Write-Host "[PASS] Stage 4.8 active, migration 6, execution remains disabled"

Write-Host "`n[2] Canonical Stage 4.8 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/governance-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "governance contract route mismatch" }
$dims = @($contract.definition.machine_enforced_dimensions)
$expectedDims = @("target_allowlist","target_denylist","network_range","credential_boundary","technique_restrictions","time_window","impact_limit","rate_limit","stop_conditions")
if (($dims -join ",") -ne ($expectedDims -join ",")) { throw "machine-enforced dimension mismatch" }
if ($contract.decision_is_authorization -or $contract.authorization_minting_enabled -or $contract.execution_intake_enabled -or $contract.tool_invocation_enabled -or $contract.target_actuation) { throw "contract crossed execution authority boundary" }
Write-Host "[PASS] canonical fail-closed scope/RoE contract"

Write-Host "`n[3] Execution-intake negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 4.8 execution intake was not rejected" }
Write-Host "[PASS] execution intake remains fail-closed"

Write-Host "`n[4] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[5] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[6] Focused Stage 4.8 regression"
python -m pytest -q tests/test_stage4_8_governance_scope_roe_enforcement.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.8 focused regression failed" }

Write-Host "`n[7] Stage 4.1 -> 4.8 regression"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1-4.8 regression failed" }

Write-Host "`n[8] Critical Stage 3 + Stage 4 governance regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py
if ($LASTEXITCODE -ne 0) { throw "critical predecessor regression failed" }

Write-Host "`n[9] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.8 Governance, Scope & Rules-of-Engagement Enforcement"
Write-Host "control_version : $ExpectedControl"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "semantics       : machine-enforced eligibility; no local PolicyDecision; no target execution"
Write-Host "next            : Stage 4.9 - Evidence, Finding & Lineage Foundation"
Write-Host "=============================================================================="
