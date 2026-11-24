param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage5.7-post-exploitation-impact-agent"
$ExpectedPredecessor = "stage5.6-exploitation-agent"
$ExpectedPentestMigration = 14
$ExpectedInventory = 1985
$ExpectedSchema = "apts-stage5.7-post-exploitation-impact-agent-v1"
$ExpectedRequestSchema = "apts-stage5.7-post-exploitation-impact-run-request-v1"
$ExpectedOutputSchema = "apts-stage5.7-post-exploitation-impact-output-v1"
$ExpectedImpactSchema = "apts-stage5.7-impact-analysis-v1"
$ExpectedFindingSchema = "apts-stage5.7-post-validation-finding-v1"
$ExpectedEvidenceSchema = "apts-stage5.7-post-exploitation-impact-evidence-v1"
$ExpectedAgent = "PENTEST_POST_EXPLOITATION_IMPACT_AGENT"
$ExpectedCapability = "impact_analysis"
$ExpectedNextStage = "5.8"

Write-Host "=============================================================================="
Write-Host "Stage 5.7 - Post-Exploitation & Impact Agent"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains global mission authority"

Write-Host "`n[1] Stage 5.7 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/5\.7") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage5_7_schema_version -ne $ExpectedSchema) { throw "Stage 5.7 schema inactive" }
if ([int]$health.stage5_7_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.7 migration declaration mismatch" }
if ($health.stage5_7_agent_id -ne $ExpectedAgent) { throw "Post-Exploitation & Impact Agent identity mismatch" }
if ($health.stage5_7_capability_id -ne $ExpectedCapability) { throw "Stage 5.7 capability mismatch" }
if (-not $health.stage5_7_post_exploitation_impact_agent_enabled) { throw "Post-Exploitation & Impact Agent not enabled" }
if (-not $health.stage5_7_impact_analysis_enabled) { throw "Impact analysis disabled" }
if (-not $health.stage5_7_post_validation_findings_enabled) { throw "Post-validation findings disabled" }
if (-not $health.stage5_7_evidence_sufficiency_enabled) { throw "Evidence sufficiency assessment disabled" }
if (-not $health.stage5_7_stop_conditions_enabled) { throw "Stop-condition assessment disabled" }
if (-not $health.stage5_7_orchestrator_impact_handoff_enabled) { throw "Impact handoff disabled" }
if ($health.stage5_7_caller_supplied_post_exploitation_results_enabled) { throw "Caller-supplied post-exploitation results must remain disabled" }
if ($health.stage5_7_confirmed_finding_creation_enabled) { throw "Confirmed finding creation must remain disabled" }
if ($health.stage5_7_lateral_movement_execution_enabled) { throw "Lateral movement execution must remain disabled" }
if ($health.stage5_7_execution_request_creation_enabled) { throw "Execution-request creation must remain disabled" }
if ($health.stage5_7_action_result_creation_enabled) { throw "Action-result creation must remain disabled" }
if ($health.stage5_7_new_target_evidence_creation_enabled) { throw "New target evidence creation must remain disabled" }
if ($health.stage5_7_tool_invocation_enabled) { throw "Direct tool invocation must remain disabled" }
if ($health.stage5_7_external_network_io_performed) { throw "Stage 5.7 unexpectedly performed external network I/O" }
if ($health.stage5_7_target_actuation) { throw "Target actuation unexpectedly enabled" }
if ($health.stage5_7_authorization_minting_enabled) { throw "Authorization minting unexpectedly enabled" }
if ($health.stage5_7_next_stage -ne $ExpectedNextStage) { throw "Stage 5.7 next-stage mismatch" }
Write-Host "[PASS] Stage 5.7 active; migration 14; analysis-only authority preserved"

Write-Host "`n[2] Canonical Stage 5.7 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/post-exploitation-impact-agent-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "Stage 5.7 contract route mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "Stage 5.7 schema mismatch" }
if ($contract.definition.run_request_schema_version -ne $ExpectedRequestSchema) { throw "Stage 5.7 request schema mismatch" }
if ($contract.definition.output_schema_version -ne $ExpectedOutputSchema) { throw "Stage 5.7 output schema mismatch" }
if ($contract.definition.impact_analysis_schema_version -ne $ExpectedImpactSchema) { throw "ImpactAnalysis schema mismatch" }
if ($contract.definition.post_validation_finding_schema_version -ne $ExpectedFindingSchema) { throw "PostValidationFinding schema mismatch" }
if ($contract.definition.evidence_schema_version -ne $ExpectedEvidenceSchema) { throw "Stage 5.7 evidence schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedPredecessor) { throw "Stage 5.7 predecessor mismatch" }
if ([int]$contract.definition.repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.7 repository migration mismatch" }
if ($contract.definition.agent_id -ne $ExpectedAgent) { throw "Stage 5.7 agent identity mismatch" }
if ($contract.definition.capability_id -ne $ExpectedCapability) { throw "Stage 5.7 capability mismatch" }
if (-not $contract.definition.implementation_available) { throw "Post-Exploitation & Impact Agent implementation unavailable" }
if (-not $contract.definition.impact_analysis_enabled) { throw "Impact analysis disabled" }
if (-not $contract.definition.post_validation_findings_enabled) { throw "Post-validation findings disabled" }
if (-not $contract.definition.evidence_sufficiency_enabled) { throw "Evidence sufficiency disabled" }
if (-not $contract.definition.stop_conditions_enabled) { throw "Stop conditions disabled" }
if ($contract.definition.caller_supplied_post_exploitation_results_enabled) { throw "Post-exploitation result injection unexpectedly enabled" }
if ($contract.definition.confirmed_finding_creation_enabled) { throw "Stage 5.7 may not create confirmed findings" }
if ($contract.definition.lateral_movement_execution_enabled) { throw "Stage 5.7 may not execute lateral movement" }
if ($contract.definition.execution_request_creation_enabled) { throw "Stage 5.7 may not create execution requests" }
if ($contract.definition.action_result_creation_enabled) { throw "Stage 5.7 may not create action results" }
if ($contract.definition.new_target_evidence_creation_enabled) { throw "Stage 5.7 may not create target evidence" }
if ($contract.definition.tool_invocation_enabled) { throw "Stage 5.7 may not invoke tools" }
if ($contract.definition.external_network_io_enabled) { throw "Stage 5.7 may not open external network I/O" }
if ($contract.definition.target_actuation) { throw "Stage 5.7 may not actuate targets" }
if ($contract.definition.authorization_minting_enabled) { throw "Stage 5.7 may not mint authorization" }
if ($contract.execution_authority) { throw "Stage 5.7 contract grants execution authority unexpectedly" }
if ($contract.confirmed_finding_creation_enabled) { throw "Contract enables confirmed finding creation unexpectedly" }
if ($contract.caller_supplied_post_exploitation_results_enabled) { throw "Contract enables caller post-exploitation results unexpectedly" }
if ($contract.lateral_movement_execution_enabled) { throw "Contract enables lateral movement execution unexpectedly" }
if ($contract.execution_request_creation_enabled) { throw "Contract enables execution-request creation unexpectedly" }
if ($contract.action_result_creation_enabled) { throw "Contract enables action-result creation unexpectedly" }
if ($contract.new_target_evidence_creation_enabled) { throw "Contract enables new target evidence unexpectedly" }
if ($contract.tool_invocation_enabled) { throw "Contract grants raw tool invocation unexpectedly" }
if ($contract.external_network_io_performed) { throw "Contract reports external network I/O unexpectedly" }
if ($contract.target_actuation) { throw "Contract grants target actuation unexpectedly" }
if ($contract.controlled_execution_stage -ne "6") { throw "Controlled execution authority moved away from Stage 6" }
if ($contract.definition.next_stage -ne $ExpectedNextStage) { throw "Stage 5.7 definition next-stage mismatch" }
Write-Host "[PASS] SHA-bound ImpactAnalysis / provisional PostValidationFinding contract"

Write-Host "`n[3] Controlled-execution negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 5.7 execution intake was not rejected" }
Write-Host "[PASS] Stage 5.7 cannot execute; Stage 6 retains controlled execution/evidence authority"

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

Write-Host "`n[6] Focused Stage 5.7 regression"
python -m pytest -q tests/test_stage5_7_post_exploitation_impact_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.7 focused regression failed" }

Write-Host "`n[7] Stage 5.1 -> Stage 5.7 specialist predecessor chain"
python -m pytest -q `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py `
  tests/test_stage5_7_post_exploitation_impact_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.1 -> 5.7 predecessor-chain regression failed" }

Write-Host "`n[8] Governance/evidence + Stage 5.1 -> Stage 5.7 qualification"
python -m pytest -q `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py `
  tests/test_stage5_7_post_exploitation_impact_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.7 -> 5.7 qualification failed" }

Write-Host "`n[9] Critical global/Pentest acceptance regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py `
  tests/test_stage5_7_post_exploitation_impact_agent.py
if ($LASTEXITCODE -ne 0) { throw "Critical Stage 3.9.10 -> Stage 5.7 regression failed" }

Write-Host "`n[10] Full historical regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "STAGE 5.7 ACCEPTANCE: PASS"
Write-Host "Control: $ExpectedControl"
Write-Host "Migration: $ExpectedPentestMigration"
Write-Host "Inventory: $ExpectedInventory"
Write-Host "Boundary: impact/provisional-findings only; Stage 6 remains controlled execution/evidence authority"
Write-Host "Next: Stage $ExpectedNextStage"
Write-Host "=============================================================================="
