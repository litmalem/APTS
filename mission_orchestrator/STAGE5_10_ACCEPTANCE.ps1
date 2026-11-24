param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage5.10-agentic-pentest-acceptance-regression-gate"
$ExpectedPredecessor = "stage5.9-governance-bound-multi-agent-pentest-e2e"
$ExpectedPentestMigration = 16
$ExpectedInventory = 2045
$ExpectedSchema = "apts-stage5.10-agentic-pentest-acceptance-regression-gate-v1"
$ExpectedStageOutput = "AGENTIC_MULTI_AGENT_PENTEST_WORKFLOW"
$ExpectedNextStage = "6.1"
$ExpectedDimensionCount = 12

Write-Host "=============================================================================="
Write-Host "Stage 5.10 - Agentic Pentest Acceptance & Regression Gate"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains global mission authority"

Write-Host "`n[1] Stage 5.10 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/5\.10") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage5_10_schema_version -ne $ExpectedSchema) { throw "Stage 5.10 schema inactive" }
if ([int]$health.stage5_10_expected_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 5.10 expected migration mismatch" }
if ($health.stage5_10_predecessor_control -ne $ExpectedPredecessor) { throw "Stage 5.10 predecessor mismatch" }
if (-not $health.stage5_10_declared_only) { throw "Stage 5.10 must remain declarative" }
if ($health.stage5_10_runtime_self_certification) { throw "Runtime self-certification must remain disabled" }
if (-not $health.stage5_10_external_acceptance_execution_required) { throw "External acceptance harness must remain authoritative" }
if (-not $health.stage5_10_full_historical_regression_required) { throw "Full historical regression must remain required" }
if ($health.stage5_10_new_database_migration_added) { throw "Stage 5.10 must not add a database migration" }
if ($health.stage5_10_new_durable_store_added) { throw "Stage 5.10 must not add a durable store" }
if ($health.stage5_10_new_authorization_authority_added) { throw "Stage 5.10 must not add authorization authority" }
if ($health.stage5_10_new_execution_authority_added) { throw "Stage 5.10 must not add execution authority" }
if ($health.stage5_10_new_tool_authority_added) { throw "Stage 5.10 must not add tool authority" }
if ($health.stage5_10_policydecision_minting_performed) { throw "PolicyDecision minting must remain disabled" }
if ($health.stage5_10_execution_request_creation_performed) { throw "ExecutionRequest creation must remain disabled" }
if ($health.stage5_10_action_result_creation_performed) { throw "ActionResult creation must remain disabled" }
if ($health.stage5_10_tool_invocation_performed) { throw "Tool invocation must remain disabled" }
if ($health.stage5_10_external_network_io_performed) { throw "Unexpected external network I/O" }
if ($health.stage5_10_target_actuation) { throw "Unexpected target actuation" }
if ($health.stage5_10_stage_output -ne $ExpectedStageOutput) { throw "Stage 5 output mismatch" }
if ($health.stage5_10_next_stage -ne $ExpectedNextStage) { throw "Stage 5.10 next-stage mismatch" }
Write-Host "[PASS] Stage 5.10 active; migration 16 unchanged; closure remains declarative"

Write-Host "`n[2] Canonical Stage 5.10 acceptance contract"
$gate = Invoke-RestMethod "$PentestUrl/api/pentest/agentic-pentest-acceptance-gate-contract"
if ($gate.control_version -ne $ExpectedControl) { throw "acceptance contract route mismatch" }
if ($gate.definition.schema_version -ne $ExpectedSchema) { throw "acceptance contract schema mismatch" }
if ($gate.definition.predecessor_control -ne $ExpectedPredecessor) { throw "acceptance predecessor mismatch" }
if ([int]$gate.definition.expected_repository_migration_level -ne $ExpectedPentestMigration) { throw "acceptance contract migration mismatch" }
if ([int]$gate.definition.required_stage5_control_count -ne 9) { throw "Stage 5 control count mismatch" }
if ([int]$gate.definition.required_acceptance_dimension_count -ne $ExpectedDimensionCount) { throw "acceptance dimension count mismatch" }
if ([int]$gate.definition.required_stage5_9_scenario_count -ne 7) { throw "Stage 5.9 scenario count mismatch" }
if ($gate.definition.stage_output -ne $ExpectedStageOutput) { throw "acceptance stage output mismatch" }
if ($gate.definition.next_stage -ne $ExpectedNextStage) { throw "acceptance next-stage mismatch" }
if (-not $gate.read_only) { throw "acceptance gate must be read-only" }
if ($gate.runtime_self_certification) { throw "acceptance gate may not self-certify" }
if (-not $gate.external_acceptance_execution_required) { throw "external acceptance execution must be required" }
if (-not $gate.full_historical_regression_required) { throw "full historical regression must be required" }
if ($gate.authorization_minted) { throw "acceptance read may not mint authorization" }
if ($gate.execution_request_created) { throw "acceptance read may not create ExecutionRequest" }
if ($gate.action_result_created) { throw "acceptance read may not create ActionResult" }
if ($gate.tool_invocation_performed) { throw "acceptance read may not invoke tools" }
if ($gate.external_network_io_performed) { throw "acceptance read may not perform external network I/O" }
if ($gate.target_actuation) { throw "acceptance read may not actuate targets" }
Write-Host "[PASS] SHA-bound Stage 5 closure contract binds controls, identities, scenarios, and 12 roadmap dimensions"

Write-Host "`n[3] Controlled-execution negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 5.10 execution intake was not rejected" }
Write-Host "[PASS] Stage 6 retains controlled execution and target-evidence authority"

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

Write-Host "`n[6] Focused Stage 5.10 regression"
python -m pytest -q tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.10 focused regression failed" }

Write-Host "`n[7] Stage 5.9 -> Stage 5.10 continuity"
python -m pytest -q `
  tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py `
  tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.9 -> 5.10 continuity failed" }

Write-Host "`n[8] Stage 5.1 -> Stage 5.10 specialist / shared-state / governance chain"
python -m pytest -q `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py `
  tests/test_stage5_7_post_exploitation_impact_agent.py `
  tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py `
  tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py `
  tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5.1 -> 5.10 chain failed" }

Write-Host "`n[9] Critical global-root / governance / evidence / closure regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py `
  tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py `
  tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Critical Stage 3.9.10 -> Stage 5.10 regression failed" }

Write-Host "`n[10] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "STAGE 5.10 ACCEPTANCE: PASS"
Write-Host "Control          : $ExpectedControl"
Write-Host "Pentest migration: $ExpectedPentestMigration (unchanged)"
Write-Host "Inventory        : $ExpectedInventory"
Write-Host "Acceptance dims  : specialist isolation / role ownership / handoff / agent identity / shared state / no direct tool bypass / governance preservation / deterministic contracts / recovery / replanning / lineage / regression"
Write-Host "Gate authority   : external acceptance harness; runtime self-certification disabled"
Write-Host "Boundary         : no new persistence / authorization / execution / tool / network / target authority"
Write-Host "STAGE 5 OUTPUT   : AGENTIC MULTI-AGENT PENTEST WORKFLOW"
Write-Host "Next             : Stage 6.1 - Canonical Execution Request Contract"
Write-Host "=============================================================================="
