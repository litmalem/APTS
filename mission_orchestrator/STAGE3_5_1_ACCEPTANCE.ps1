param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.1 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.1-canonical-execution-dispatch-contract-identity"
$expectedPredecessor = "stage3.4.10-routing-delegation-acceptance-regression-gate"
$expectedMigrationLevel = 27
$expectedTestCount = 798
$expectedSchema = "apts-canonical-execution-dispatch-contract-v1"
$expectedIdentityPrefix = "xdispatch-"
$expectedStatus = "MATERIALIZED_PENDING_PRE_DISPATCH_AUTHORIZATION"
$expectedAuthorizationStatus = "NOT_EVALUATED"
$expectedStore = "mission_execution_dispatch_contracts"

Write-Host "=============================================================================="
Write-Host "Stage 3.5.1 - Canonical Execution Dispatch Contract & Identity"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator is not reachable at $MissionBaseUrl"
}
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.1 source is not active on port 8780" }
Pass "Stage 3.5.1 runtime control is active"

Write-Host "`n[1] Python compile"
Push-Location $PSScriptRoot
try {
    python -m compileall -q mission_orchestrator tests
    if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
} finally {
    Pop-Location
}
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
Push-Location $PSScriptRoot
try {
    $collectOutput = (& python -m pytest --collect-only -q 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { Fail "Pytest collection failed" }
} finally {
    Pop-Location
}
if ($collectOutput -notmatch "(?m)$expectedTestCount tests collected") {
    Write-Host $collectOutput
    Fail "Expected exactly $expectedTestCount collected tests"
}
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.5.1 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.1 proof"
Push-Location $PSScriptRoot
try {
    python -m pytest -q tests\test_stage3_5_1_canonical_execution_dispatch_contract_identity.py
    if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.5.1 proof failed" }
} finally {
    Pop-Location
}
Pass "Focused Stage-3.5.1 canonical dispatch identity proof passed"

Write-Host "`n[5] Runtime identity, migration, and predecessor ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 27" }
if ([int]$health.execution_dispatch_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.1 migration declaration is not 27" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2) { Fail "Supported-control tail cardinality is not 2" }
if ($tail[0] -ne $expectedPredecessor -or $tail[1] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expectedPredecessor, $expectedControl]"
}
Pass "Stage 3.4.10 -> Stage 3.5.1 control ordering and migration level are correct"

Write-Host "`n[6] Canonical execution-dispatch contract declaration"
if ($health.execution_dispatch_contract_schema_version -ne $expectedSchema) { Fail "Unexpected execution-dispatch schema version" }
if ($health.execution_dispatch_contract_identity_prefix -ne $expectedIdentityPrefix) { Fail "Unexpected execution-dispatch identity prefix" }
if ($health.execution_dispatch_contract_status -ne $expectedStatus) { Fail "Unexpected execution-dispatch status" }
if ($health.execution_dispatch_authorization_status -ne $expectedAuthorizationStatus) { Fail "Unexpected execution-authorization status" }
if ($health.execution_dispatch_persistence_store -ne $expectedStore) { Fail "Unexpected execution-dispatch persistence store" }
if (@($health.execution_dispatch_contract_allowed_states).Count -ne 1 -or $health.execution_dispatch_contract_allowed_states[0] -ne "RUNNING") { Fail "Execution-dispatch source-state boundary drifted" }
if ($health.execution_dispatch_requires_stage347_delivery_acknowledgement_ownership -ne $true) { Fail "Stage-3.4.7 ownership prerequisite missing" }
if ($health.execution_dispatch_requires_current_active_plan_version -ne $true) { Fail "Active Plan prerequisite missing" }
if ($health.execution_dispatch_requires_exact_running_state_version_vector -ne $true) { Fail "Exact Mission version-vector prerequisite missing" }
Pass "Canonical xdispatch contract declaration and exact provenance prerequisites are active"

Write-Host "`n[7] Execution-authority separation"
if ($health.execution_dispatch_pre_dispatch_governance_revalidation_required -ne $true) { Fail "Pre-dispatch Governance revalidation requirement missing" }
if ($health.execution_dispatch_ownership_is_execution_authority -ne $false) { Fail "Ownership was elevated into execution authority" }
if ($health.execution_dispatch_contract_is_dispatch -ne $false) { Fail "Dispatch contract was elevated into actual dispatch" }
if ($health.execution_dispatch_identity_is_execution_authorization -ne $false) { Fail "Dispatch identity was elevated into execution authorization" }
if ($health.task_delegation_authorization_reused_as_execution_grant -ne $false) { Fail "Delegation authorization was reused as execution grant" }
Pass "Ownership, delegation authorization, dispatch identity, and execution authority remain separated"

Write-Host "`n[8] No runtime dispatch / no target actuation boundary"
$forbiddenTrueFields = @(
    "execution_dispatch_runtime_endpoint_resolution_performed",
    "execution_dispatch_runtime_health_probe_performed",
    "execution_dispatch_resource_assignment_performed",
    "execution_dispatch_governance_query_performed",
    "execution_dispatch_execution_authorization_performed",
    "execution_dispatch_dispatch_attempt_started",
    "execution_dispatch_dispatch_performed",
    "execution_dispatch_external_network_io_performed",
    "execution_dispatch_target_action_dispatch_enabled",
    "execution_dispatch_target_actuation"
)
foreach ($field in $forbiddenTrueFields) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.1 execution boundary drifted: $field" }
}
Pass "Stage 3.5.1 materializes identity only: no runtime resolution, authorization, network dispatch, or actuation"

Write-Host "`n[9] Stage-3.4 predecessor execution boundary remains closed"
$stage34Forbidden = @(
    "task_routing_dispatch_performed",
    "task_routing_target_action_dispatch_enabled",
    "task_routing_target_actuation",
    "task_delegation_dispatch_performed",
    "task_delegation_execution_authorized",
    "delegation_delivery_dispatch_performed",
    "delegation_delivery_execution_authorized",
    "delegation_recovery_control_dispatch_performed",
    "delegation_recovery_control_execution_authorized",
    "routing_delegation_recovery_dispatch_performed",
    "routing_delegation_recovery_execution_authorized",
    "routing_delegation_recovery_target_action_dispatch_enabled",
    "routing_delegation_recovery_target_actuation"
)
foreach ($field in $stage34Forbidden) {
    if ($health.$field -ne $false) { Fail "Predecessor execution boundary drifted: $field" }
}
Pass "Stage-3.4 routing/delegation remains non-executing after Stage-3.5.1 activation"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version      : $($finalHealth.control_version)"
Write-Host "Repository Migration : $($finalHealth.mission_repository_migration_level)"
Write-Host "Dispatch Schema      : $($finalHealth.execution_dispatch_contract_schema_version)"
Write-Host "Identity Prefix      : $($finalHealth.execution_dispatch_contract_identity_prefix)"
Write-Host "Dispatch Status      : $($finalHealth.execution_dispatch_contract_status)"
Write-Host "Authorization Status : $($finalHealth.execution_dispatch_authorization_status)"
Write-Host "Governance Revalidate: $($finalHealth.execution_dispatch_pre_dispatch_governance_revalidation_required)"
Write-Host "Dispatch Performed   : $($finalHealth.execution_dispatch_dispatch_performed)"
Write-Host "Target Actuation     : $($finalHealth.execution_dispatch_target_actuation)"
Write-Host "=============================================================================="
exit 0
