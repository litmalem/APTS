param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.3 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.3-authoritative-pre-dispatch-governance-revalidation"
$expectedPredecessor351 = "stage3.5.1-canonical-execution-dispatch-contract-identity"
$expectedPredecessor352 = "stage3.5.2-dispatch-eligibility-execution-preconditions"
$expectedMigrationLevel = 29
$expectedTestCount = 836
$expectedSchema = "apts-authoritative-pre-dispatch-governance-revalidation-v1"
$expectedIdentityPrefix = "xreval-"
$expectedMode = "AUTHORITATIVE_PRE_DISPATCH_FAIL_CLOSED"
$expectedAuthority = "EXTERNAL_APTS_GSS"
$expectedActionClass = "TASK_EXECUTION"
$expectedActionName = "AUTHORIZE_EXECUTION_DISPATCH"
$expectedResourceType = "SUBSYSTEM_CAPABILITY"
$expectedStore = "mission_pre_dispatch_governance_revalidations"

Write-Host "=============================================================================="
Write-Host "Stage 3.5.3 - Authoritative Pre-Dispatch Governance Revalidation"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.3 source is not active on port 8780" }
Pass "Stage 3.5.3 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.5.3 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.3 proof"
Push-Location $PSScriptRoot
try {
    python -m pytest -q tests\test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation.py
    if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.5.3 proof failed" }
} finally {
    Pop-Location
}
Pass "Focused Stage-3.5.3 authoritative Governance revalidation proof passed"

Write-Host "`n[5] Runtime identity, migration, and predecessor ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 29" }
if ([int]$health.pre_dispatch_governance_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.3 migration declaration is not 29" }
$tail = @($health.supported_controls | Select-Object -Last 3)
if ($tail.Count -ne 3) { Fail "Supported-control tail cardinality is not 3" }
if ($tail[0] -ne $expectedPredecessor351 -or $tail[1] -ne $expectedPredecessor352 -or $tail[2] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expectedPredecessor351, $expectedPredecessor352, $expectedControl]"
}
Pass "Stage 3.5.1 -> 3.5.2 -> 3.5.3 ordering and migration level are correct"

Write-Host "`n[6] Canonical authoritative revalidation declaration"
if ($health.pre_dispatch_governance_revalidation_schema_version -ne $expectedSchema) { Fail "Unexpected Stage-3.5.3 schema version" }
if ($health.pre_dispatch_governance_revalidation_identity_prefix -ne $expectedIdentityPrefix) { Fail "Unexpected Stage-3.5.3 identity prefix" }
if ($health.pre_dispatch_governance_revalidation_mode -ne $expectedMode) { Fail "Unexpected Stage-3.5.3 mode" }
if ($health.pre_dispatch_governance_revalidation_authority -ne $expectedAuthority) { Fail "Unexpected Governance authority" }
if ($health.pre_dispatch_governance_action_class -ne $expectedActionClass) { Fail "Unexpected Governance action class" }
if ($health.pre_dispatch_governance_action_name -ne $expectedActionName) { Fail "Unexpected Governance action name" }
if ($health.pre_dispatch_governance_resource_type -ne $expectedResourceType) { Fail "Unexpected Governance resource type" }
if ($health.pre_dispatch_governance_persistence_store -ne $expectedStore) { Fail "Unexpected Stage-3.5.3 persistence store" }
if (@($health.pre_dispatch_governance_revalidation_allowed_states).Count -ne 1 -or $health.pre_dispatch_governance_revalidation_allowed_states[0] -ne "RUNNING") { Fail "Stage-3.5.3 source-state boundary drifted" }
if ($health.pre_dispatch_governance_requires_stage351_execution_dispatch_contract -ne $true) { Fail "Stage-3.5.1 predecessor requirement missing" }
if ($health.pre_dispatch_governance_requires_stage352_dispatch_eligibility -ne $true) { Fail "Stage-3.5.2 predecessor requirement missing" }
Pass "Canonical xreval contract and predecessor bindings are active"

Write-Host "`n[7] Authoritative Governance / fail-closed semantics"
if ($health.pre_dispatch_governance_static_preconditions_revalidated -ne $true) { Fail "Static prerequisite revalidation is not enabled" }
if ($health.pre_dispatch_governance_authoritative_query_performed -ne $true) { Fail "Authoritative Governance query declaration is not enabled" }
if ($health.pre_dispatch_governance_fresh_policy_decision_required -ne $true) { Fail "Fresh PolicyDecision requirement is missing" }
if ($health.pre_dispatch_governance_fail_closed -ne $true) { Fail "Fail-closed semantics are missing" }
if ($health.pre_dispatch_governance_append_only_revalidation_history -ne $true) { Fail "Append-only revalidation history is missing" }
if ($health.pre_dispatch_governance_response_loss_recovery_supported -ne $true) { Fail "Response-loss recovery declaration is missing" }
if ($health.pre_dispatch_governance_allow_grants_execution_authorization -ne $true) { Fail "ALLOW execution-authorization semantic is missing" }
if ($health.pre_dispatch_governance_authorization_is_dispatch -ne $false) { Fail "Execution authorization was incorrectly equated with dispatch" }
Pass "Authoritative Governance decision is fresh, fail-closed, recoverable, and distinct from dispatch"

Write-Host "`n[8] No runtime resolution / dispatch / target actuation"
$forbiddenTrueFields = @(
    "pre_dispatch_governance_runtime_endpoint_resolution_performed",
    "pre_dispatch_governance_runtime_health_probe_performed",
    "pre_dispatch_governance_resource_assignment_performed",
    "pre_dispatch_governance_dispatch_attempt_started",
    "pre_dispatch_governance_dispatch_performed",
    "pre_dispatch_governance_external_target_network_io_performed",
    "pre_dispatch_governance_target_action_dispatch_enabled",
    "pre_dispatch_governance_target_actuation"
)
foreach ($field in $forbiddenTrueFields) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.3 runtime/dispatch boundary drifted: $field" }
}
Pass "Stage 3.5.3 grants authority evidence only; runtime dispatch remains closed"

Write-Host "`n[9] Stage-3.5.2 predecessor remains eligibility-only"
if ($health.dispatch_eligibility_eligible_for_pre_dispatch_governance_revalidation -ne $true) { Fail "Stage-3.5.2 no longer feeds Stage-3.5.3" }
if ($health.dispatch_eligibility_is_execution_authorization -ne $false) { Fail "Stage-3.5.2 eligibility was elevated into execution authority" }
if ($health.dispatch_eligibility_eligible_for_execution -ne $false) { Fail "Stage-3.5.2 eligibility incorrectly became executable" }
if ($health.dispatch_eligibility_governance_query_performed -ne $false) { Fail "Governance query leaked backward into Stage-3.5.2" }
if ($health.dispatch_eligibility_dispatch_performed -ne $false) { Fail "Dispatch leaked backward into Stage-3.5.2" }
if ($health.dispatch_eligibility_target_actuation -ne $false) { Fail "Target actuation leaked backward into Stage-3.5.2" }
Pass "Stage 3.5.2 remains static/durable eligibility only"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.3 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Revalidation Schema      : $($finalHealth.pre_dispatch_governance_revalidation_schema_version)"
Write-Host "Identity Prefix          : $($finalHealth.pre_dispatch_governance_revalidation_identity_prefix)"
Write-Host "Governance Authority     : $($finalHealth.pre_dispatch_governance_revalidation_authority)"
Write-Host "Governance Action        : $($finalHealth.pre_dispatch_governance_action_name)"
Write-Host "Fresh Policy Required    : $($finalHealth.pre_dispatch_governance_fresh_policy_decision_required)"
Write-Host "ALLOW Grants Exec Auth   : $($finalHealth.pre_dispatch_governance_allow_grants_execution_authorization)"
Write-Host "Authorization Is Dispatch: $($finalHealth.pre_dispatch_governance_authorization_is_dispatch)"
Write-Host "Dispatch Performed       : $($finalHealth.pre_dispatch_governance_dispatch_performed)"
Write-Host "Target Actuation         : $($finalHealth.pre_dispatch_governance_target_actuation)"
Write-Host "=============================================================================="
exit 0
