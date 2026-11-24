param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage5.4-vulnerability-hypothesis-agent"
$ExpectedPredecessor = "stage5.3-enumeration-agent"
$ExpectedPentestMigration = 11
$ExpectedInventory = 1901
$ExpectedSchema = "apts-stage5.4-vulnerability-hypothesis-agent-v1"
$ExpectedRequestSchema = "apts-stage5.4-vulnerability-hypothesis-run-request-v1"
$ExpectedOutputSchema = "apts-stage5.4-vulnerability-hypothesis-output-v1"
$ExpectedHypothesisSchema = "apts-stage5.4-vulnerability-hypothesis-model-v1"
$ExpectedEvidenceSchema = "apts-stage5.4-vulnerability-hypothesis-evidence-contract-v1"
$ExpectedAgent = "PENTEST_VULNERABILITY_HYPOTHESIS_AGENT"
$ExpectedCapability = "vulnerability_analysis"
$ExpectedNextStage = "5.5"

Write-Host "=============================================================================="
Write-Host "Stage 5.4 - Vulnerability Hypothesis Agent"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains global mission authority"

Write-Host "`n[1] Stage 5.4 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/5\.4") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage5_4_schema_version -ne $ExpectedSchema) { throw "Stage 5.4 schema inactive" }
if ([int]$health.stage5_4_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.4 migration declaration mismatch" }
if ($health.stage5_4_vulnerability_hypothesis_agent_id -ne $ExpectedAgent) { throw "Vulnerability Hypothesis agent identity mismatch" }
if (-not $health.stage5_4_vulnerability_hypothesis_agent_enabled) { throw "Vulnerability Hypothesis Agent not enabled" }
if (-not $health.stage5_4_knowledge_cti_correlation_enabled) { throw "Knowledge/CTI correlation not enabled" }
if (-not $health.stage5_4_hypothesis_model_enabled) { throw "Hypothesis model not enabled" }
if (-not $health.stage5_4_confidence_model_enabled) { throw "Confidence model not enabled" }
if (-not $health.stage5_4_required_validation_model_enabled) { throw "Required-validation model not enabled" }
if (-not $health.stage5_4_predecessor_enumeration_binding_enabled) { throw "Stage 5.3 predecessor binding not enabled" }
if (-not $health.stage5_4_evidence_to_hypothesis_lineage_enabled) { throw "Evidence-to-hypothesis lineage not enabled" }
if (-not $health.stage5_4_orchestrator_progress_handoff_enabled) { throw "Orchestrator progress handoff not enabled" }
if ($health.stage5_4_finding_creation_enabled) { throw "Unvalidated finding creation must remain disabled" }
if ($health.stage5_4_validation_execution_enabled) { throw "Validation execution must remain disabled" }
if ($health.stage5_4_execution_intake_enabled) { throw "Execution intake must remain disabled" }
if ($health.stage5_4_tool_invocation_enabled) { throw "Direct tool invocation must remain disabled" }
if ($health.stage5_4_external_network_io_performed) { throw "Stage 5.4 unexpectedly performed external network I/O" }
if ($health.stage5_4_target_actuation) { throw "Target actuation unexpectedly enabled" }
if ($health.stage5_4_authorization_minting_enabled) { throw "Authorization minting unexpectedly enabled" }
if ($health.stage5_4_next_stage -ne $ExpectedNextStage) { throw "Stage 5.4 next-stage mismatch" }
Write-Host "[PASS] Stage 5.4 active; migration 11; read-only hypothesis authority preserved"

Write-Host "`n[2] Canonical Stage 5.4 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/vulnerability-hypothesis-agent-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "Stage 5.4 contract route mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "Stage 5.4 schema mismatch" }
if ($contract.definition.run_request_schema_version -ne $ExpectedRequestSchema) { throw "Stage 5.4 request schema mismatch" }
if ($contract.definition.output_schema_version -ne $ExpectedOutputSchema) { throw "Stage 5.4 output schema mismatch" }
if ($contract.definition.hypothesis_model_schema_version -ne $ExpectedHypothesisSchema) { throw "Hypothesis model schema mismatch" }
if ($contract.definition.evidence_schema_version -ne $ExpectedEvidenceSchema) { throw "Hypothesis evidence schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedPredecessor) { throw "Stage 5.4 predecessor mismatch" }
if ([int]$contract.definition.repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.4 repository migration mismatch" }
if ($contract.definition.agent_id -ne $ExpectedAgent) { throw "Stage 5.4 agent identity mismatch" }
if ($contract.definition.capability_id -ne $ExpectedCapability) { throw "Stage 5.4 capability mismatch" }
if (-not $contract.definition.implementation_available) { throw "Vulnerability Hypothesis specialist implementation unavailable" }
if (-not $contract.definition.knowledge_cti_correlation_enabled) { throw "Knowledge/CTI correlation disabled" }
if (-not $contract.definition.predecessor_enumeration_binding_enabled) { throw "Stage 5.3 binding disabled" }
if (-not $contract.definition.evidence_to_hypothesis_lineage_enabled) { throw "Stage 4.9 Evidence-to-Hypothesis lineage disabled" }
if ($contract.definition.finding_creation_enabled) { throw "Stage 5.4 may not create confirmed findings" }
if ($contract.definition.validation_execution_enabled) { throw "Stage 5.4 may not execute validation" }
if ($contract.execution_authority) { throw "Hypothesis contract grants execution authority unexpectedly" }
if ($contract.validation_execution_enabled) { throw "Contract enables validation execution unexpectedly" }
if ($contract.finding_creation_enabled) { throw "Contract enables unvalidated finding creation unexpectedly" }
if ($contract.tool_invocation_enabled) { throw "Hypothesis contract grants raw tool invocation unexpectedly" }
if ($contract.target_actuation) { throw "Hypothesis contract grants target actuation unexpectedly" }
if ($contract.controlled_execution_stage -ne "6") { throw "Controlled execution authority moved away from Stage 6" }
if ($contract.definition.next_stage -ne $ExpectedNextStage) { throw "Stage 5.4 definition next-stage mismatch" }
Write-Host "[PASS] SHA-bound Observation -> Knowledge/CTI -> Hypothesis -> Confidence -> Required Validation contract"

Write-Host "`n[3] Controlled-execution negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 5.4 execution intake was not rejected" }
Write-Host "[PASS] Hypothesis analysis cannot execute validation; Stage 6 retains controlled execution authority"

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

Write-Host "`n[6] Focused Stage 5.4 regression"
python -m pytest -q tests/test_stage5_4_vulnerability_hypothesis_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.4 focused regression failed" }

Write-Host "`n[7] Stage 4.1 -> Stage 5.4 Pentest qualification chain"
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
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1 -> 5.4 qualification chain failed" }

Write-Host "`n[8] Critical global-mission -> Vulnerability Hypothesis Stage 5.4 regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py
if ($LASTEXITCODE -ne 0) { throw "critical Stage 3 -> Stage 5.4 regression failed" }

Write-Host "`n[9] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 5.4 Vulnerability Hypothesis Agent"
Write-Host "control_version   : $ExpectedControl"
Write-Host "pentest migration : $ExpectedPentestMigration"
Write-Host "inventory         : $ExpectedInventory"
Write-Host "enabled           : Stage-5.3 predecessor binding / Knowledge+CTI correlation / deterministic OPEN+UNVALIDATED Hypothesis Model / confidence / required validation / Stage-4.9 Evidence-to-Hypothesis lineage / Stage-5.1 progress handoff"
Write-Host "disabled          : validation execution / confirmed-finding creation / direct tool access / raw network execution / target actuation / PolicyDecision minting"
Write-Host "execution authority: Stage 6 preserved"
Write-Host "next              : Stage 5.5 - Attack-Path Planning Agent"
Write-Host "=============================================================================="
