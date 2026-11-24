param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage5.1-full-agentic-pentest-workflow-orchestrator"
$ExpectedPredecessor = "stage4.10-pentest-foundation-acceptance-gate"
$ExpectedPentestMigration = 8
$ExpectedInventory = 1823
$ExpectedSchema = "apts-stage5.1-full-agentic-pentest-workflow-orchestrator-v1"
$ExpectedNextStage = "5.2"

Write-Host "=============================================================================="
Write-Host "Stage 5.1 - Full Agentic Pentest Workflow Orchestrator"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains global mission authority"

Write-Host "`n[1] Stage 5.1 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/5\.1") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage5_1_schema_version -ne $ExpectedSchema) { throw "Stage 5.1 schema inactive" }
if ([int]$health.stage5_1_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.1 migration declaration mismatch" }
if (-not $health.stage5_1_full_local_orchestrator_enabled) { throw "full local orchestrator not enabled" }
if (-not $health.stage5_1_task_decomposition_enabled) { throw "task decomposition not enabled" }
if (-not $health.stage5_1_agent_task_graph_enabled) { throw "agent task graph not enabled" }
if (-not $health.stage5_1_specialist_assignment_enabled) { throw "specialist assignment not enabled" }
if (-not $health.stage5_1_progress_aggregation_enabled) { throw "progress aggregation not enabled" }
if (-not $health.stage5_1_replanning_enabled) { throw "replanning not enabled" }
if (-not $health.stage5_1_terminate_escalate_enabled) { throw "terminate/escalate not enabled" }
if ($health.stage5_1_specialist_execution_enabled) { throw "specialist execution must remain disabled at Stage 5.1" }
if ($health.stage5_1_execution_intake_enabled) { throw "execution intake must remain disabled" }
if ($health.stage5_1_tool_invocation_enabled) { throw "tool invocation must remain disabled" }
if ($health.stage5_1_external_network_io_performed) { throw "external network I/O unexpectedly enabled" }
if ($health.stage5_1_target_actuation) { throw "target actuation unexpectedly enabled" }
if ($health.stage5_1_authorization_minting_enabled) { throw "authorization minting unexpectedly enabled" }
if ($health.stage5_1_next_stage -ne $ExpectedNextStage) { throw "Stage 5.1 next-stage mismatch" }
if (-not $health.stage4_10_declared_only) { throw "Stage 4.10 foundation contract not preserved" }
if (-not $health.stage4_9_lineage_projection_enabled) { throw "Stage 4.9 lineage foundation not preserved" }
Write-Host "[PASS] Stage 5.1 active; migration 8; Stage 4 foundation preserved"

Write-Host "`n[2] Canonical Stage 5.1 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/agentic-orchestrator-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "Stage 5.1 contract route mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "Stage 5.1 schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedPredecessor) { throw "Stage 5.1 predecessor mismatch" }
if ([int]$contract.definition.repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.1 repository migration mismatch" }
if (-not $contract.definition.full_local_orchestrator_enabled) { throw "orchestrator contract disabled" }
if (-not $contract.definition.task_decomposition_enabled) { throw "task decomposition contract disabled" }
if (-not $contract.definition.specialist_assignment_enabled) { throw "specialist assignment contract disabled" }
if (-not $contract.definition.progress_aggregation_enabled) { throw "progress aggregation contract disabled" }
if (-not $contract.definition.replanning_enabled) { throw "replanning contract disabled" }
if ($contract.specialist_execution_enabled) { throw "contract grants specialist execution unexpectedly" }
if ($contract.execution_intake_enabled) { throw "contract grants execution intake unexpectedly" }
if ($contract.tool_invocation_enabled) { throw "contract grants tool invocation unexpectedly" }
if ($contract.target_actuation) { throw "contract grants target actuation unexpectedly" }
Write-Host "[PASS] SHA-bound Stage 5.1 orchestration contract"

Write-Host "`n[3] Controlled-execution negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 5.1 execution intake was not rejected" }
Write-Host "[PASS] Stage 5.1 remains control-plane only; Stage 6 retains execution authority"

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

Write-Host "`n[6] Focused Stage 5.1 regression"
python -m pytest -q tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.1 focused regression failed" }

Write-Host "`n[7] Stage 4.1 -> Stage 5.1 Pentest qualification chain"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1 -> 5.1 qualification chain failed" }

Write-Host "`n[8] Critical global-mission -> Pentest Stage 5.1 regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py
if ($LASTEXITCODE -ne 0) { throw "critical Stage 3 -> Stage 5.1 regression failed" }

Write-Host "`n[9] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 5.1 Full Agentic Pentest Workflow Orchestrator"
Write-Host "control_version   : $ExpectedControl"
Write-Host "pentest migration : $ExpectedPentestMigration"
Write-Host "inventory         : $ExpectedInventory"
Write-Host "enabled           : task understanding / deterministic decomposition / agent task graph / specialist role assignment / progress aggregation / versioned replanning / terminate-escalate"
Write-Host "disabled          : specialist execution / raw tool access / external network I/O / target actuation / PolicyDecision minting"
Write-Host "global authority  : Stage 3.9.10 Global Mission Orchestrator preserved"
Write-Host "execution authority: Stage 6 preserved"
Write-Host "next              : Stage 5.2 - Reconnaissance Agent"
Write-Host "=============================================================================="
