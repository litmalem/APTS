param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage5.3-enumeration-agent"
$ExpectedPredecessor = "stage5.2-reconnaissance-agent"
$ExpectedPentestMigration = 10
$ExpectedInventory = 1873
$ExpectedSchema = "apts-stage5.3-enumeration-agent-v1"
$ExpectedAssetSchema = "apts-stage5.3-enumerated-asset-model-v1"
$ExpectedEvidenceSchema = "apts-stage5.3-enumeration-evidence-contract-v1"
$ExpectedAgent = "PENTEST_ENUMERATION_AGENT"
$ExpectedNextStage = "5.4"

Write-Host "=============================================================================="
Write-Host "Stage 5.3 - Enumeration Agent"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains global mission authority"

Write-Host "`n[1] Stage 5.3 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/5\.3") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage5_3_schema_version -ne $ExpectedSchema) { throw "Stage 5.3 schema inactive" }
if ([int]$health.stage5_3_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.3 migration declaration mismatch" }
if ($health.stage5_3_enumeration_agent_id -ne $ExpectedAgent) { throw "Enumeration agent identity mismatch" }
if (-not $health.stage5_3_enumeration_agent_enabled) { throw "Enumeration Agent not enabled" }
if (-not $health.stage5_3_service_enumeration_enabled) { throw "Service enumeration not enabled" }
if (-not $health.stage5_3_technology_identification_enabled) { throw "Technology identification not enabled" }
if (-not $health.stage5_3_version_discovery_enabled) { throw "Version discovery not enabled" }
if (-not $health.stage5_3_endpoint_discovery_enabled) { throw "Endpoint discovery not enabled" }
if (-not $health.stage5_3_configuration_observation_enabled) { throw "Configuration observation not enabled" }
if (-not $health.stage5_3_enumerated_asset_model_enabled) { throw "Enumerated asset model not enabled" }
if (-not $health.stage5_3_predecessor_recon_binding_enabled) { throw "Stage 5.2 predecessor binding not enabled" }
if (-not $health.stage5_3_enumeration_evidence_contract_enabled) { throw "Enumeration evidence contract not enabled" }
if (-not $health.stage5_3_scope_roe_evaluation_enabled) { throw "Scope/RoE evaluation not enabled" }
if (-not $health.stage5_3_orchestrator_progress_handoff_enabled) { throw "Orchestrator progress handoff not enabled" }
if ($health.stage5_3_execution_intake_enabled) { throw "Execution intake must remain disabled" }
if ($health.stage5_3_tool_invocation_enabled) { throw "Direct tool invocation must remain disabled" }
if ($health.stage5_3_external_network_io_performed) { throw "Stage 5.3 unexpectedly performed external network I/O" }
if ($health.stage5_3_target_actuation) { throw "Target actuation unexpectedly enabled" }
if ($health.stage5_3_authorization_minting_enabled) { throw "Authorization minting unexpectedly enabled" }
if ($health.stage5_3_next_stage -ne $ExpectedNextStage) { throw "Stage 5.3 next-stage mismatch" }
Write-Host "[PASS] Stage 5.3 active; migration 10; bounded specialist authority preserved"

Write-Host "`n[2] Canonical Stage 5.3 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/enumeration-agent-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "Stage 5.3 contract route mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "Stage 5.3 schema mismatch" }
if ($contract.definition.asset_model_schema_version -ne $ExpectedAssetSchema) { throw "Enumerated asset schema mismatch" }
if ($contract.definition.evidence_schema_version -ne $ExpectedEvidenceSchema) { throw "Enumeration evidence schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedPredecessor) { throw "Stage 5.3 predecessor mismatch" }
if ([int]$contract.definition.repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.3 repository migration mismatch" }
if ($contract.definition.agent_id -ne $ExpectedAgent) { throw "Stage 5.3 agent identity mismatch" }
if (-not $contract.definition.implementation_available) { throw "Enumeration specialist implementation unavailable" }
if (-not $contract.definition.predecessor_recon_binding_enabled) { throw "Stage 5.2 binding disabled" }
if (-not $contract.definition.stage4_9_lineage_binding_enabled) { throw "Stage 4.9 evidence lineage binding disabled" }
if (-not $contract.definition.scope_roe_evaluation_enabled) { throw "Stage 4.8 governance binding disabled" }
if ($contract.execution_authority) { throw "Enumeration contract grants execution authority unexpectedly" }
if ($contract.tool_invocation_enabled) { throw "Enumeration contract grants raw tool invocation unexpectedly" }
if ($contract.target_actuation) { throw "Enumeration contract grants target actuation unexpectedly" }
if ($contract.controlled_execution_stage -ne "6") { throw "Controlled execution authority moved away from Stage 6" }
Write-Host "[PASS] SHA-bound Stage 5.3 Enumeration Agent + enumerated-asset/evidence contracts"

Write-Host "`n[3] Controlled-execution negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 5.3 execution intake was not rejected" }
Write-Host "[PASS] Enumeration may model/propose; Stage 6 retains controlled execution authority"

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

Write-Host "`n[6] Focused Stage 5.3 regression"
python -m pytest -q tests/test_stage5_3_enumeration_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.3 focused regression failed" }

Write-Host "`n[7] Stage 4.1 -> Stage 5.3 Pentest qualification chain"
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
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1 -> 5.3 qualification chain failed" }

Write-Host "`n[8] Critical global-mission -> Enumeration Stage 5.3 regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py
if ($LASTEXITCODE -ne 0) { throw "critical Stage 3 -> Stage 5.3 regression failed" }

Write-Host "`n[9] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 5.3 Enumeration Agent"
Write-Host "control_version   : $ExpectedControl"
Write-Host "pentest migration : $ExpectedPentestMigration"
Write-Host "inventory         : $ExpectedInventory"
Write-Host "enabled           : Stage-5.2 predecessor binding / service+technology+version+endpoint+configuration observation normalization / enumerated asset model / Stage-4.9 evidence lineage / Stage-4.8 governed enumeration proposals / Stage-5.1 progress handoff"
Write-Host "disabled          : direct tool access / raw network execution / target actuation / PolicyDecision minting"
Write-Host "execution authority: Stage 6 preserved"
Write-Host "next              : Stage 5.4 - Vulnerability Hypothesis Agent"
Write-Host "=============================================================================="
