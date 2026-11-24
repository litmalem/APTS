param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage5.6-exploitation-agent"
$ExpectedPredecessor = "stage5.5-attack-path-planning-agent"
$ExpectedPentestMigration = 13
$ExpectedInventory = 1957
$ExpectedSchema = "apts-stage5.6-exploitation-agent-v1"
$ExpectedRequestSchema = "apts-stage5.6-exploitation-run-request-v1"
$ExpectedOutputSchema = "apts-stage5.6-exploitation-output-v1"
$ExpectedProposalSchema = "apts-stage5.6-exploit-action-proposal-v1"
$ExpectedValidationTaskSchema = "apts-stage5.6-validation-task-v1"
$ExpectedEvidenceSchema = "apts-stage5.6-exploitation-evidence-contract-v1"
$ExpectedAgent = "PENTEST_EXPLOITATION_AGENT"
$ExpectedNextStage = "5.7"

Write-Host "=============================================================================="
Write-Host "Stage 5.6 - Exploitation Agent"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains global mission authority"

Write-Host "`n[1] Stage 5.6 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/5\.6") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage5_6_schema_version -ne $ExpectedSchema) { throw "Stage 5.6 schema inactive" }
if ([int]$health.stage5_6_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.6 migration declaration mismatch" }
if ($health.stage5_6_exploitation_agent_id -ne $ExpectedAgent) { throw "Exploitation Agent identity mismatch" }
if (-not $health.stage5_6_exploitation_agent_enabled) { throw "Exploitation Agent not enabled" }
if (-not $health.stage5_6_exploit_action_proposal_enabled) { throw "Exploit Action Proposal disabled" }
if (-not $health.stage5_6_validation_task_enabled) { throw "Validation Task disabled" }
if (-not $health.stage5_6_scope_roe_evaluation_enabled) { throw "Stage 4.8 scope/RoE evaluation disabled" }
if (-not $health.stage5_6_action_proposal_lineage_enabled) { throw "Stage 4.9 action-proposal lineage disabled" }
if (-not $health.stage5_6_orchestrator_validation_handoff_enabled) { throw "Validation handoff disabled" }
if (-not $health.stage5_6_orchestrator_exploitation_handoff_enabled) { throw "Exploitation handoff disabled" }
if ($health.stage5_6_caller_supplied_executable_content_enabled) { throw "Caller-supplied executable content must remain disabled" }
if ($health.stage5_6_validation_execution_enabled) { throw "Validation execution must remain disabled" }
if ($health.stage5_6_exploitation_execution_enabled) { throw "Exploitation execution must remain disabled" }
if ($health.stage5_6_execution_request_creation_enabled) { throw "Execution-request creation must remain disabled" }
if ($health.stage5_6_action_result_creation_enabled) { throw "Action-result creation must remain disabled" }
if ($health.stage5_6_new_target_evidence_creation_enabled) { throw "New target execution evidence must remain disabled" }
if ($health.stage5_6_finding_creation_enabled) { throw "Confirmed-finding creation must remain disabled" }
if ($health.stage5_6_tool_invocation_enabled) { throw "Direct tool invocation must remain disabled" }
if ($health.stage5_6_external_network_io_performed) { throw "Stage 5.6 unexpectedly performed external network I/O" }
if ($health.stage5_6_target_actuation) { throw "Target actuation unexpectedly enabled" }
if ($health.stage5_6_authorization_minting_enabled) { throw "Authorization minting unexpectedly enabled" }
if ($health.stage5_6_next_stage -ne $ExpectedNextStage) { throw "Stage 5.6 next-stage mismatch" }
Write-Host "[PASS] Stage 5.6 active; migration 13; proposal-only authority preserved"

Write-Host "`n[2] Canonical Stage 5.6 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/exploitation-agent-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "Stage 5.6 contract route mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "Stage 5.6 schema mismatch" }
if ($contract.definition.run_request_schema_version -ne $ExpectedRequestSchema) { throw "Stage 5.6 request schema mismatch" }
if ($contract.definition.output_schema_version -ne $ExpectedOutputSchema) { throw "Stage 5.6 output schema mismatch" }
if ($contract.definition.exploit_action_proposal_schema_version -ne $ExpectedProposalSchema) { throw "Exploit Action Proposal schema mismatch" }
if ($contract.definition.validation_task_schema_version -ne $ExpectedValidationTaskSchema) { throw "Validation Task schema mismatch" }
if ($contract.definition.evidence_schema_version -ne $ExpectedEvidenceSchema) { throw "Stage 5.6 evidence schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedPredecessor) { throw "Stage 5.6 predecessor mismatch" }
if ([int]$contract.definition.repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.6 repository migration mismatch" }
if ($contract.definition.agent_id -ne $ExpectedAgent) { throw "Stage 5.6 agent identity mismatch" }
if (-not $contract.definition.implementation_available) { throw "Exploitation Agent implementation unavailable" }
if (-not $contract.definition.exploit_action_proposal_enabled) { throw "Exploit Action Proposal disabled" }
if (-not $contract.definition.validation_task_enabled) { throw "Validation Task disabled" }
if ($contract.definition.caller_supplied_executable_content_enabled) { throw "Executable content injection unexpectedly enabled" }
if ($contract.definition.validation_execution_enabled) { throw "Stage 5.6 may not execute validation" }
if ($contract.definition.exploitation_execution_enabled) { throw "Stage 5.6 may not execute exploitation" }
if ($contract.definition.execution_request_creation_enabled) { throw "Stage 5.6 may not create execution requests" }
if ($contract.definition.action_result_creation_enabled) { throw "Stage 5.6 may not create action results" }
if ($contract.definition.new_target_evidence_creation_enabled) { throw "Stage 5.6 may not create target execution evidence" }
if ($contract.definition.finding_creation_enabled) { throw "Stage 5.6 may not create confirmed findings" }
if ($contract.execution_authority) { throw "Stage 5.6 contract grants execution authority unexpectedly" }
if ($contract.validation_execution_enabled) { throw "Contract enables validation execution unexpectedly" }
if ($contract.exploitation_execution_enabled) { throw "Contract enables exploitation execution unexpectedly" }
if ($contract.execution_request_creation_enabled) { throw "Contract enables execution-request creation unexpectedly" }
if ($contract.action_result_creation_enabled) { throw "Contract enables action-result creation unexpectedly" }
if ($contract.new_target_evidence_creation_enabled) { throw "Contract enables new target evidence unexpectedly" }
if ($contract.finding_creation_enabled) { throw "Contract enables finding creation unexpectedly" }
if ($contract.tool_invocation_enabled) { throw "Contract grants raw tool invocation unexpectedly" }
if ($contract.target_actuation) { throw "Contract grants target actuation unexpectedly" }
if ($contract.controlled_execution_stage -ne "6") { throw "Controlled execution authority moved away from Stage 6" }
if ($contract.definition.next_stage -ne $ExpectedNextStage) { throw "Stage 5.6 definition next-stage mismatch" }
Write-Host "[PASS] SHA-bound Exploit Action Proposal / Validation Task contract"

Write-Host "`n[3] Controlled-execution negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 5.6 execution intake was not rejected" }
Write-Host "[PASS] Stage 5.6 cannot execute; Stage 6 retains controlled execution authority"

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

Write-Host "`n[6] Focused Stage 5.6 regression"
python -m pytest -q tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.6 focused regression failed" }

Write-Host "`n[7] Stage 5.1 -> Stage 5.6 specialist predecessor chain"
python -m pytest -q `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.1 -> 5.6 predecessor-chain regression failed" }

Write-Host "`n[8] Governance/evidence + Stage 5.1 -> Stage 5.6 qualification"
python -m pytest -q `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.7 -> 5.6 qualification failed" }

Write-Host "`n[9] Critical global/Pentest acceptance regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Critical Stage 3.9.10 -> Stage 5.6 regression failed" }

Write-Host "`n[10] Full historical regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "STAGE 5.6 ACCEPTANCE: PASS"
Write-Host "Control: $ExpectedControl"
Write-Host "Migration: $ExpectedPentestMigration"
Write-Host "Inventory: $ExpectedInventory"
Write-Host "Boundary: proposal/validation-task only; Stage 6 remains controlled execution authority"
Write-Host "Next: Stage $ExpectedNextStage"
Write-Host "=============================================================================="
