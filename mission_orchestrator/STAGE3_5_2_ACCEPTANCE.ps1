param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.2 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.2-dispatch-eligibility-execution-preconditions"
$expectedPredecessor = "stage3.5.1-canonical-execution-dispatch-contract-identity"
$expectedMigrationLevel = 28
$expectedTestCount = 817
$expectedSchema = "apts-dispatch-eligibility-execution-preconditions-v1"
$expectedIdentityPrefix = "xelig-"
$expectedGateResult = "PASSED"
$expectedEligibilityStatus = "ELIGIBLE_FOR_PRE_DISPATCH_GOVERNANCE_REVALIDATION"
$expectedPreconditionStatus = "SATISFIED_PENDING_PRE_DISPATCH_AUTHORIZATION"
$expectedStore = "mission_execution_dispatch_eligibility_gates"

Write-Host "=============================================================================="
Write-Host "Stage 3.5.2 - Dispatch Eligibility & Execution Preconditions"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.2 source is not active on port 8780" }
Pass "Stage 3.5.2 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.5.2 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.2 proof"
Push-Location $PSScriptRoot
try {
    python -m pytest -q tests\test_stage3_5_2_dispatch_eligibility_execution_preconditions.py
    if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.5.2 proof failed" }
} finally {
    Pop-Location
}
Pass "Focused Stage-3.5.2 dispatch eligibility/execution-precondition proof passed"

Write-Host "`n[5] Runtime identity, migration, and predecessor ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 28" }
if ([int]$health.dispatch_eligibility_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.2 migration declaration is not 28" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2) { Fail "Supported-control tail cardinality is not 2" }
if ($tail[0] -ne $expectedPredecessor -or $tail[1] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expectedPredecessor, $expectedControl]"
}
Pass "Stage 3.5.1 -> Stage 3.5.2 control ordering and migration level are correct"

Write-Host "`n[6] Canonical dispatch-eligibility/precondition declaration"
if ($health.dispatch_eligibility_schema_version -ne $expectedSchema) { Fail "Unexpected Stage-3.5.2 schema version" }
if ($health.dispatch_eligibility_identity_prefix -ne $expectedIdentityPrefix) { Fail "Unexpected Stage-3.5.2 identity prefix" }
if ($health.dispatch_eligibility_gate_result -ne $expectedGateResult) { Fail "Unexpected gate result declaration" }
if ($health.dispatch_eligibility_status -ne $expectedEligibilityStatus) { Fail "Unexpected eligibility status" }
if ($health.dispatch_eligibility_execution_precondition_status -ne $expectedPreconditionStatus) { Fail "Unexpected execution-precondition status" }
if ($health.dispatch_eligibility_persistence_store -ne $expectedStore) { Fail "Unexpected Stage-3.5.2 persistence store" }
if (@($health.dispatch_eligibility_allowed_states).Count -ne 1 -or $health.dispatch_eligibility_allowed_states[0] -ne "RUNNING") { Fail "Stage-3.5.2 source-state boundary drifted" }
if ($health.dispatch_eligibility_requires_stage351_execution_dispatch_contract -ne $true) { Fail "Stage-3.5.1 predecessor requirement missing" }
if ($health.dispatch_eligibility_requires_current_readiness_projection -ne $true) { Fail "Current readiness projection prerequisite missing" }
if ($health.dispatch_eligibility_requires_structurally_ready_task -ne $true) { Fail "Structurally-ready task prerequisite missing" }
Pass "Canonical xelig contract and execution-precondition declaration are active"

Write-Host "`n[7] Eligibility versus execution-authority separation"
if ($health.dispatch_eligibility_eligible_for_pre_dispatch_governance_revalidation -ne $true) { Fail "Positive eligibility does not lead to Governance revalidation" }
if ($health.dispatch_eligibility_pre_dispatch_governance_revalidation_required -ne $true) { Fail "Pre-dispatch Governance revalidation requirement missing" }
if ($health.dispatch_eligibility_is_execution_authorization -ne $false) { Fail "Eligibility was elevated into execution authorization" }
if ($health.dispatch_eligibility_preconditions_are_execution_authorization -ne $false) { Fail "Execution preconditions were elevated into authorization" }
if ($health.dispatch_eligibility_eligible_for_execution -ne $false) { Fail "PASSED eligibility was elevated into executable authority" }
Pass "Eligibility/preconditions remain separate from execution authority"

Write-Host "`n[8] No Governance query / runtime resolution / dispatch / target actuation"
$forbiddenTrueFields = @(
    "dispatch_eligibility_governance_query_performed",
    "dispatch_eligibility_runtime_endpoint_resolution_performed",
    "dispatch_eligibility_runtime_health_probe_performed",
    "dispatch_eligibility_resource_assignment_performed",
    "dispatch_eligibility_execution_authorization_performed",
    "dispatch_eligibility_dispatch_attempt_started",
    "dispatch_eligibility_dispatch_performed",
    "dispatch_eligibility_external_network_io_performed",
    "dispatch_eligibility_target_action_dispatch_enabled",
    "dispatch_eligibility_target_actuation",
    "dispatch_eligibility_version_vector_extension_performed"
)
foreach ($field in $forbiddenTrueFields) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.2 execution boundary drifted: $field" }
}
Pass "Stage 3.5.2 performs static/durable eligibility evaluation only"

Write-Host "`n[9] Stage-3.5.1 predecessor boundary remains closed"
$stage351Forbidden = @(
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
foreach ($field in $stage351Forbidden) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.1 predecessor execution boundary drifted: $field" }
}
Pass "Stage-3.5.1 dispatch identity remains non-executing after Stage-3.5.2 activation"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.2 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version        : $($finalHealth.control_version)"
Write-Host "Repository Migration   : $($finalHealth.mission_repository_migration_level)"
Write-Host "Eligibility Schema     : $($finalHealth.dispatch_eligibility_schema_version)"
Write-Host "Identity Prefix        : $($finalHealth.dispatch_eligibility_identity_prefix)"
Write-Host "Gate Result            : $($finalHealth.dispatch_eligibility_gate_result)"
Write-Host "Eligibility Status     : $($finalHealth.dispatch_eligibility_status)"
Write-Host "Precondition Status    : $($finalHealth.dispatch_eligibility_execution_precondition_status)"
Write-Host "Governance Revalidate  : $($finalHealth.dispatch_eligibility_eligible_for_pre_dispatch_governance_revalidation)"
Write-Host "Eligible For Execution : $($finalHealth.dispatch_eligibility_eligible_for_execution)"
Write-Host "Dispatch Performed     : $($finalHealth.dispatch_eligibility_dispatch_performed)"
Write-Host "Target Actuation       : $($finalHealth.dispatch_eligibility_target_actuation)"
Write-Host "=============================================================================="
exit 0
