param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage4.9-evidence-finding-lineage-foundation"
$ExpectedPentestMigration = 7
$ExpectedInventory = 1784

Write-Host "=============================================================================="
Write-Host "Stage 4.9 - Evidence, Finding & Lineage Foundation"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains authoritative"

Write-Host "`n[1] Stage 4.9 runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if (-not $health.stage4_9_evidence_model_enabled -or -not $health.stage4_9_finding_model_enabled -or -not $health.stage4_9_lineage_projection_enabled) { throw "Stage 4.9 lineage foundation is not active" }
if (-not $health.stage4_9_append_only_persistence_enabled -or -not $health.stage4_9_idempotent_replay_enabled) { throw "Stage 4.9 persistence/replay controls are not active" }
if ($health.stage4_9_authorization_minting_enabled -or $health.stage4_9_execution_intake_enabled -or $health.stage4_9_tool_invocation_enabled -or $health.stage4_9_target_actuation) { throw "Stage 4.9 crossed authority/execution boundary" }
if ($health.stage4_9_next_stage -ne "4.10") { throw "Stage 4.9 next stage mismatch" }
Write-Host "[PASS] Stage 4.9 active, migration 7, controlled execution remains disabled"

Write-Host "`n[2] Canonical Stage 4.9 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/lineage-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "lineage contract route mismatch" }
$types = @($contract.definition.object_types)
$expectedTypes = @("OBSERVATION","EVIDENCE","FINDING","HYPOTHESIS","ACTION_PROPOSAL","ACTION_RESULT","ARTIFACT")
if (($types -join ",") -ne ($expectedTypes -join ",")) { throw "lineage object type mismatch" }
$metadata = @($contract.definition.required_metadata)
$expectedMetadata = @("identity","provenance","timestamp","parent_reference","integrity")
if (($metadata -join ",") -ne ($expectedMetadata -join ",")) { throw "required metadata mismatch" }
if (-not $contract.evidence_model_enabled -or -not $contract.finding_model_enabled -or -not $contract.lineage_projection_enabled) { throw "Stage 4.9 deliverables not active" }
if ($contract.authorization_minting_enabled -or $contract.execution_intake_enabled -or $contract.tool_invocation_enabled -or $contract.target_actuation) { throw "contract crossed execution authority boundary" }
Write-Host "[PASS] canonical evidence/finding/lineage contract"

Write-Host "`n[3] Execution-intake negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 4.9 execution intake was not rejected" }
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

Write-Host "`n[6] Focused Stage 4.9 regression"
python -m pytest -q tests/test_stage4_9_evidence_finding_lineage_foundation.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.9 focused regression failed" }

Write-Host "`n[7] Stage 4.1 -> 4.9 regression"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1-4.9 regression failed" }

Write-Host "`n[8] Critical Stage 3 + Stage 4 lineage/governance regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py
if ($LASTEXITCODE -ne 0) { throw "critical predecessor regression failed" }

Write-Host "`n[9] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.9 Evidence, Finding & Lineage Foundation"
Write-Host "control_version : $ExpectedControl"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "semantics       : append-only canonical evidence/finding/lineage; no authorization minting; no target execution"
Write-Host "next            : Stage 4.10 - Pentest Foundation Acceptance Gate"
Write-Host "=============================================================================="
