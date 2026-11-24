param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage5.8-cross-agent-feedback-shared-state-replanning"
$ExpectedPredecessor = "stage5.7-post-exploitation-impact-agent"
$ExpectedPentestMigration = 15
$ExpectedInventory = 2009
$ExpectedSchema = "apts-stage5.8-cross-agent-feedback-shared-state-replanning-v1"
$ExpectedSharedStateSchema = "apts-stage5.8-shared-state-v1"
$ExpectedHandoffSchema = "apts-stage5.8-agent-handoff-v1"
$ExpectedFeedbackSchema = "apts-stage5.8-cross-agent-feedback-record-v1"
$ExpectedReplanSchema = "apts-stage5.8-local-replan-decision-v1"
$ExpectedNextStage = "5.9"

Write-Host "=============================================================================="
Write-Host "Stage 5.8 - Cross-Agent Feedback, Shared State & Replanning"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains global mission authority"

Write-Host "`n[1] Stage 5.8 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/5\.8") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage5_8_schema_version -ne $ExpectedSchema) { throw "Stage 5.8 schema inactive" }
if ([int]$health.stage5_8_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.8 migration declaration mismatch" }
if (-not $health.stage5_8_shared_state_enabled) { throw "Shared state disabled" }
if (-not $health.stage5_8_agent_handoff_enabled) { throw "Agent handoff disabled" }
if (-not $health.stage5_8_cross_agent_feedback_enabled) { throw "Cross-agent feedback disabled" }
if (-not $health.stage5_8_local_replanning_enabled) { throw "Local replanning disabled" }
if (-not $health.stage5_8_replan_projection_only) { throw "Local replan must remain projection-only" }
if ($health.stage5_8_execution_request_creation_enabled) { throw "Execution request creation must remain disabled" }
if ($health.stage5_8_action_result_creation_enabled) { throw "Action result creation must remain disabled" }
if ($health.stage5_8_confirmed_finding_creation_enabled) { throw "Confirmed finding creation must remain disabled" }
if ($health.stage5_8_new_target_evidence_creation_enabled) { throw "New target evidence creation must remain disabled" }
if ($health.stage5_8_tool_invocation_enabled) { throw "Tool invocation must remain disabled" }
if ($health.stage5_8_external_network_io_performed) { throw "Unexpected external network I/O" }
if ($health.stage5_8_target_actuation) { throw "Unexpected target actuation" }
if ($health.stage5_8_authorization_minting_enabled) { throw "Authorization minting must remain disabled" }
if ($health.stage5_8_next_stage -ne $ExpectedNextStage) { throw "Stage 5.8 next-stage mismatch" }
Write-Host "[PASS] Stage 5.8 active; migration 15; coordination-only authority preserved"

Write-Host "`n[2] Canonical Stage 5.8 contract"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/cross-agent-feedback-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "Stage 5.8 contract route mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "Stage 5.8 schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedPredecessor) { throw "Stage 5.8 predecessor mismatch" }
if ([int]$contract.definition.repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.8 repository migration mismatch" }
if (-not $contract.shared_state_enabled) { throw "Shared-state contract not active" }
if (-not $contract.agent_handoff_enabled) { throw "Handoff contract not active" }
if (-not $contract.cross_agent_feedback_enabled) { throw "Feedback contract not active" }
if (-not $contract.local_replanning_enabled) { throw "Local replanning contract not active" }
if (-not $contract.replan_projection_only) { throw "Replan projection boundary not active" }
if ($contract.execution_authority) { throw "Stage 5.8 unexpectedly has execution authority" }
if ($contract.execution_request_creation_enabled) { throw "Stage 5.8 may not create execution requests" }
if ($contract.action_result_creation_enabled) { throw "Stage 5.8 may not create action results" }
if ($contract.new_target_evidence_creation_enabled) { throw "Stage 5.8 may not create target evidence" }
if ($contract.tool_invocation_enabled) { throw "Stage 5.8 may not invoke tools" }
if ($contract.target_actuation) { throw "Stage 5.8 may not actuate targets" }
if ($contract.controlled_execution_stage -ne "6") { throw "Controlled execution authority moved away from Stage 6" }
if ($contract.definition.next_stage -ne $ExpectedNextStage) { throw "Stage 5.8 next-stage mismatch" }
Write-Host "[PASS] SHA-bound shared-state / handoff / feedback / local-replan contracts"

Write-Host "`n[3] Controlled-execution negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 5.8 execution intake was not rejected" }
Write-Host "[PASS] Stage 6 retains controlled execution/evidence authority"

Write-Host "`n[4] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[5] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "Expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[6] Focused Stage 5.8 regression"
python -m pytest -q tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.8 focused regression failed" }

Write-Host "`n[7] Immediate predecessor continuity"
python -m pytest -q `
  tests/test_stage5_7_post_exploitation_impact_agent.py `
  tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.7 -> 5.8 continuity failed" }

Write-Host "`n[8] Stage 5.1 -> Stage 5.8 specialist chain"
python -m pytest -q `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py `
  tests/test_stage5_7_post_exploitation_impact_agent.py `
  tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.1 -> 5.8 chain failed" }

Write-Host "`n[9] Critical governance/evidence/global acceptance regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_7_post_exploitation_impact_agent.py `
  tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py
if ($LASTEXITCODE -ne 0) { throw "Critical Stage 3.9.10 -> Stage 5.8 regression failed" }

Write-Host "`n[10] Full historical regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "STAGE 5.8 ACCEPTANCE: PASS"
Write-Host "Control: $ExpectedControl"
Write-Host "Migration: $ExpectedPentestMigration"
Write-Host "Inventory: $ExpectedInventory"
Write-Host "Boundary: shared state/feedback/replan projection only; Stage 6 remains controlled execution authority"
Write-Host "Next: Stage $ExpectedNextStage"
Write-Host "=============================================================================="
