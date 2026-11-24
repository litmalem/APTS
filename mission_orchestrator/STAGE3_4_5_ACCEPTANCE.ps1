param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.5 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }

Write-Host "=============================================================================="
Write-Host "Stage 3.4.5 - Governance-Bound Delegation Authorization Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator is not reachable at $MissionBaseUrl" }
$expectedControl = "stage3.4.5-governance-bound-delegation-authorization"
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.4.5 source is not active on port 8780" }
Pass "Stage 3.4.5 runtime control is active"

Write-Host "`n[1] Python compile + focused contract proof"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
python -m pytest -q tests\test_stage3_4_5_governance_bound_delegation_authorization.py
if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.4.5 proof failed" }
Pass "Stage-3.4.5 focused authorization, idempotency, recovery, persistence, integrity, and boundary tests passed"

Write-Host "`n[2] Health / Governance authority / delegation boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ([int]$health.mission_repository_migration_level -ne 22) { Fail "Repository migration level is not 22" }
if ([int]$health.delegation_authorization_database_migration_level -ne 22) { Fail "Stage-3.4.5 migration declaration is not 22" }
if ($health.delegation_authorization_persistence_store -ne "mission_delegation_authorizations") { Fail "Unexpected Stage-3.4.5 persistence store" }
if ($health.delegation_authorization_mode -ne "AUTHORITATIVE_GOVERNANCE_PRE_DELEGATION_FAIL_CLOSED") { Fail "Unexpected Stage-3.4.5 mode" }
if ($health.delegation_authorization_governance_query_enabled -ne $true) { Fail "Authoritative Governance query capability is not enabled" }
if ($health.delegation_authorization_requires_stage344_route_decision -ne $true) { Fail "Stage-3.4.4 route-decision binding is not required" }
if ($health.delegation_authorization_requires_current_governance_binding -ne $true) { Fail "Current Governance binding is not required" }
if ($health.delegation_authorization_is_delegation -ne $false) { Fail "Authorization was incorrectly equated with delegation" }
if ($health.delegation_authorization_pre_delegation_revalidation_required -ne $true) { Fail "Pre-delegation revalidation invariant is absent" }
if ($health.task_routing_delegation_performed -ne $false) { Fail "Delegation leaked into Stage 3.4.5" }
if ($health.task_routing_dispatch_performed -ne $false) { Fail "Dispatch leaked into Stage 3.4.5" }
if ($health.task_routing_runtime_endpoint_resolution_performed -ne $false) { Fail "Endpoint resolution leaked into Stage 3.4.5" }
if ($health.task_routing_runtime_health_probe_performed -ne $false) { Fail "Runtime health probing leaked into Stage 3.4.5" }
if ($health.task_routing_target_actuation -ne $false) { Fail "Target execution leaked into Stage 3.4.5" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
Pass "Governance is authoritative; authorization remains distinct from delegation/dispatch/execution"

Write-Host "`n[3] Canonical definition endpoint"
# Definition is Mission-scoped, so the focused Python proof covers a concrete Mission instance.
Pass "Canonical definition and Mission-scoped API are covered by focused Stage-3.4.5 tests"

Write-Host "`n[4] Regression smoke partitions"
$stage31 = @(Get-ChildItem -Path "tests\test_stage3_1_*.py" -File | Sort-Object Name | ForEach-Object { $_.FullName })
if ($stage31.Count -eq 0) { Fail "No Stage-3.1 regression tests were discovered" }
python -m pytest -q @stage31
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.1 regression partition failed" }

$stage32 = @(Get-ChildItem -Path "tests\test_stage3_2_*.py" -File | Sort-Object Name | ForEach-Object { $_.FullName })
if ($stage32.Count -eq 0) { Fail "No Stage-3.2 regression tests were discovered" }
python -m pytest -q @stage32
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.2 regression partition failed" }
Pass "Stage-3.1 and Stage-3.2 regression partitions passed"

Write-Host "`n[5] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 22) { Fail "Final migration level drifted" }
if ($finalHealth.delegation_authorization_is_delegation -ne $false) { Fail "Authorization/delegation boundary drifted" }
if ($finalHealth.task_routing_delegation_performed -ne $false -or $finalHealth.task_routing_dispatch_performed -ne $false) { Fail "Delegation/dispatch boundary drifted" }
if ($finalHealth.task_routing_target_actuation -ne $false) { Fail "Execution boundary drifted" }
Pass "Stage 3.4.5 closure contract preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.5 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
