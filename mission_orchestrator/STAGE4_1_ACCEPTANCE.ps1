param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage4.1-pentest-boundary-canonical-contract"
$ExpectedSchema = "apts-stage4.1-pentest-boundary-canonical-contract-v1"
$ExpectedHandoffSchema = "apts-pentest-boundary-handoff-envelope-v1"
$ExpectedMissionMigration = 53
$ExpectedPentestMigration = 0
$ExpectedInventory = 1590

Write-Host "=============================================================================="
Write-Host "Stage 4.1 - Pentest Boundary & Canonical Contract"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 handoff preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
if ([int]$mo.mission_repository_migration_level -ne $ExpectedMissionMigration) { throw "Mission Orchestrator migration mismatch" }
if ($mo.stage3_9_10_next_stage -ne "4.1") { throw "Mission Orchestrator does not hand off to Stage 4.1" }
if ($mo.stage3_9_10_stage_output -ne "GLOBAL_MISSION_ORCHESTRATOR") { throw "Stage 3 output mismatch" }
Write-Host "[PASS] Stage 3.9.10 predecessor closed and hands to Stage 4.1"

Write-Host "`n[1] Pentest runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.status -ne "ok") { throw "Pentest subsystem health is not ok" }
if ($health.subsystem_id -ne "PENTEST") { throw "Pentest subsystem identity mismatch" }
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest repository migration must remain 0" }
if ($health.stage4_1_schema_version -ne $ExpectedSchema) { throw "Stage 4.1 schema mismatch" }
if ($health.stage4_1_handoff_schema_version -ne $ExpectedHandoffSchema) { throw "Stage 4.1 handoff schema mismatch" }
if ($health.stage4_1_predecessor_control -ne $ExpectedMissionControl) { throw "Stage 4.1 predecessor mismatch" }
if ($health.stage4_1_execution_intake_enabled) { throw "Stage 4.1 must not enable execution intake" }
if ($health.stage4_1_workflow_runtime_enabled) { throw "Stage 4.1 must not enable workflow runtime" }
if ($health.stage4_1_local_task_repository_enabled) { throw "Stage 4.1 must not enable local task repository" }
if ($health.stage4_1_durable_persistence_enabled) { throw "Stage 4.1 must not add durable persistence" }
if ($health.stage4_1_tool_invocation_enabled) { throw "Stage 4.1 must not invoke pentest tools" }
if ($health.stage4_1_target_actuation) { throw "Stage 4.1 must not actuate targets" }
if ($health.stage4_1_next_stage -ne "4.2") { throw "Stage 4.1 next-stage mismatch" }
Write-Host "[PASS] Pentest boundary runtime active"

Write-Host "`n[2] Canonical boundary contract API"
$contract = Invoke-RestMethod "$PentestUrl/api/pentest/boundary-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($contract.definition.schema_version -ne $ExpectedSchema) { throw "contract definition schema mismatch" }
if ($contract.definition.handoff_schema_version -ne $ExpectedHandoffSchema) { throw "handoff schema mismatch" }
if ($contract.definition.predecessor_control -ne $ExpectedMissionControl) { throw "contract predecessor mismatch" }
if ($contract.definition.subsystem_id -ne "PENTEST") { throw "contract subsystem mismatch" }
if (@($contract.definition.required_fields).Count -ne 8) { throw "required handoff field count mismatch" }
if (-not $contract.read_only) { throw "contract API must be read-only" }
if ($contract.execution_intake_enabled) { throw "contract API incorrectly enables execution intake" }
if ($contract.target_actuation) { throw "contract API incorrectly enables target actuation" }
Write-Host "[PASS] canonical Pentest boundary contract"

Write-Host "`n[3] Validation-only handoff envelope"
$payload = @{
    pentest_id = "pentest-$([guid]::NewGuid())"
    mission_id = "mission-gmo-$([guid]::NewGuid())"
    task_id = "ptask-$([guid]::NewGuid())"
    scope = @{
        targets = @(@{ target_type = "HOST"; target_value = "lab-target.invalid" })
        excluded_targets = @()
    }
    objective = @{
        type = "SECURITY_VALIDATION"
        description = "Stage 4.1 boundary acceptance validation only"
    }
    constraints = @{
        max_actions = 10
        risk_threshold = "MODERATE"
        data_handling_policy = @{ retain_sensitive_output = $false }
    }
    roe = @{
        allowed_action_classes = @("TARGET_RECON", "VULNERABILITY_VALIDATION")
        prohibited_action_classes = @("DESTRUCTIVE_ACTION")
        destructive_actions_allowed = $false
    }
    authorization_reference = @{
        policy_decision_id = "decision-stage4-1-acceptance"
        policy_decision_hash = ("a" * 64)
        policy_version = 1
        execution_authorized = $true
        pre_dispatch_revalidation_id = "xreval-stage4-1-acceptance"
    }
}
$body = $payload | ConvertTo-Json -Depth 20 -Compress
$validation = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/boundary/validate" -ContentType "application/json" -Body $body
if ($validation.status -ne "valid") { throw "boundary validation did not return valid" }
if (-not $validation.validated_only) { throw "validation route is not validation-only" }
if ($validation.accepted_for_execution) { throw "validation route accepted execution" }
if ($validation.persisted) { throw "validation route persisted state" }
if ($validation.target_actuation) { throw "validation route actuated target" }
if ($validation.envelope.schema_version -ne $ExpectedHandoffSchema) { throw "validation envelope schema mismatch" }
Write-Host "[PASS] handoff envelope validated without execution/persistence"

Write-Host "`n[4] Execution-intake negative boundary"
$dispatchRejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{"probe":true}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        $dispatchRejected = $true
    } else {
        throw
    }
}
if (-not $dispatchRejected) { throw "Stage 4.1 execution dispatch was not rejected with HTTP 409" }
Write-Host "[PASS] execution dispatch remains disabled"

Write-Host "`n[5] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[6] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[7] Focused Stage 4.1 regression"
python -m pytest -q tests/test_stage4_1_pentest_boundary_canonical_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1 focused regression failed" }

Write-Host "`n[8] Boundary predecessor / registry / governance critical regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage3_1_4_governance_authorization_binding.py `
  tests/test_stage3_5_5_dispatch_delivery_execution_acknowledgement.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py
if ($LASTEXITCODE -ne 0) { throw "boundary critical regression failed" }

Write-Host "`n[9] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.1 Pentest Boundary & Canonical Contract"
Write-Host "control_version : $ExpectedControl"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "predecessor     : Stage 3.9.10 / GLOBAL MISSION ORCHESTRATOR"
Write-Host "boundary        : MO -> PENTEST -> Pentest Workflow"
Write-Host "authority       : no local authorization minting; no execution; no actuation"
Write-Host "next            : Stage 4.2 - PIP Ingestion, Validation & Binding"
Write-Host "=============================================================================="
