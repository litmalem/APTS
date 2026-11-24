param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.4 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.4-idempotent-dispatch-execution-attempt-identity"
$expectedPredecessor351 = "stage3.5.1-canonical-execution-dispatch-contract-identity"
$expectedPredecessor352 = "stage3.5.2-dispatch-eligibility-execution-preconditions"
$expectedPredecessor353 = "stage3.5.3-authoritative-pre-dispatch-governance-revalidation"
$expectedMigrationLevel = 30
$expectedTestCount = 856
$expectedSchema = "apts-idempotent-dispatch-execution-attempt-v1"
$expectedAttemptPrefix = "xattempt-"
$expectedEnvelopePrefix = "xenv-"
$expectedMode = "IDEMPOTENT_DURABLE_DISPATCH_COMMIT_WITH_STABLE_EXECUTION_ATTEMPT_IDENTITY_PENDING_DELIVERY"
$expectedAuthority = "GLOBAL_MISSION_ORCHESTRATOR_IDEMPOTENT_DISPATCH_COMMIT"
$expectedDispatchCommitStatus = "COMMITTED_IDEMPOTENT_PENDING_DELIVERY"
$expectedAttemptStatus = "CREATED_NOT_DELIVERED"
$expectedStore = "mission_execution_attempts"

Write-Host "=============================================================================="
Write-Host "Stage 3.5.4 - Idempotent Dispatch & Execution Attempt Identity"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.4 source is not active on port 8780" }
Pass "Stage 3.5.4 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.5.4 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.4 proof"
Push-Location $PSScriptRoot
try {
    python -m pytest -q tests\test_stage3_5_4_idempotent_dispatch_execution_attempt_identity.py
    if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.5.4 proof failed" }
} finally {
    Pop-Location
}
Pass "Focused Stage-3.5.4 idempotent dispatch/execution-attempt proof passed"

Write-Host "`n[5] Runtime identity, migration, and predecessor ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 30" }
if ([int]$health.execution_attempt_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.4 migration declaration is not 30" }
$tail = @($health.supported_controls | Select-Object -Last 4)
if ($tail.Count -ne 4) { Fail "Supported-control tail cardinality is not 4" }
if ($tail[0] -ne $expectedPredecessor351 -or $tail[1] -ne $expectedPredecessor352 -or $tail[2] -ne $expectedPredecessor353 -or $tail[3] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expectedPredecessor351, $expectedPredecessor352, $expectedPredecessor353, $expectedControl]"
}
Pass "Stage 3.5.1 -> 3.5.2 -> 3.5.3 -> 3.5.4 ordering and migration level are correct"

Write-Host "`n[6] Canonical Stage-3.5.4 declaration"
if ($health.execution_attempt_schema_version -ne $expectedSchema) { Fail "Unexpected execution-attempt schema version" }
if ($health.execution_attempt_identity_prefix -ne $expectedAttemptPrefix) { Fail "Unexpected execution-attempt identity prefix" }
if ($health.dispatch_envelope_identity_prefix -ne $expectedEnvelopePrefix) { Fail "Unexpected dispatch-envelope identity prefix" }
if ($health.execution_attempt_mode -ne $expectedMode) { Fail "Unexpected Stage-3.5.4 mode" }
if ($health.execution_attempt_authority -ne $expectedAuthority) { Fail "Unexpected Stage-3.5.4 authority" }
if ($health.execution_attempt_dispatch_commit_status -ne $expectedDispatchCommitStatus) { Fail "Unexpected dispatch-commit status" }
if ($health.execution_attempt_status -ne $expectedAttemptStatus) { Fail "Unexpected execution-attempt status" }
if ($health.execution_attempt_persistence_store -ne $expectedStore) { Fail "Unexpected Stage-3.5.4 persistence store" }
if (@($health.execution_attempt_allowed_states).Count -ne 1 -or $health.execution_attempt_allowed_states[0] -ne "RUNNING") { Fail "Stage-3.5.4 source-state boundary drifted" }
Pass "Canonical xattempt/xenv contract is active"

Write-Host "`n[7] Predecessor and idempotency invariants"
if ($health.execution_attempt_requires_stage351_execution_dispatch_contract -ne $true) { Fail "Stage-3.5.1 predecessor requirement missing" }
if ($health.execution_attempt_requires_stage352_passed_dispatch_eligibility -ne $true) { Fail "Stage-3.5.2 predecessor requirement missing" }
if ($health.execution_attempt_requires_latest_stage353_allow -ne $true) { Fail "Latest Stage-3.5.3 ALLOW requirement missing" }
if ($health.execution_attempt_one_initial_attempt_per_dispatch -ne $true) { Fail "One-initial-attempt-per-dispatch invariant missing" }
if ($health.execution_attempt_idempotent_replay -ne $true) { Fail "Idempotent replay declaration missing" }
if ($health.execution_attempt_duplicate_dispatch_suppressed -ne $true) { Fail "Duplicate dispatch suppression missing" }
if ($health.execution_attempt_duplicate_execution_attempt_suppressed -ne $true) { Fail "Duplicate execution-attempt suppression missing" }
if ($health.execution_attempt_durable_dispatch_commit_performed -ne $true) { Fail "Durable dispatch commit declaration missing" }
if ($health.execution_attempt_immutable_dispatch_envelope_materialized -ne $true) { Fail "Immutable dispatch-envelope declaration missing" }
Pass "Stage 3.5.4 idempotency and durable identity invariants are active"

Write-Host "`n[8] No new Governance query / no delivery / no execution-start / no target actuation"
$forbiddenTrueFields = @(
    "execution_attempt_governance_query_performed",
    "execution_attempt_runtime_endpoint_resolution_performed",
    "execution_attempt_runtime_health_probe_performed",
    "execution_attempt_resource_assignment_performed",
    "execution_attempt_target_delivery_performed",
    "execution_attempt_delivery_acknowledgement_performed",
    "execution_attempt_execution_started",
    "execution_attempt_external_target_network_io_performed",
    "execution_attempt_target_action_dispatch_performed",
    "execution_attempt_target_actuation"
)
foreach ($field in $forbiddenTrueFields) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.4 side-effect boundary drifted: $field" }
}
Pass "Stage 3.5.4 commits identity/evidence only; Stage 3.5.5 delivery boundary remains closed"

Write-Host "`n[9] Stage-3.5.3 remains the authoritative Governance decision boundary"
if ($health.pre_dispatch_governance_authoritative_query_performed -ne $true) { Fail "Stage-3.5.3 authoritative Governance declaration missing" }
if ($health.pre_dispatch_governance_allow_grants_execution_authorization -ne $true) { Fail "Stage-3.5.3 ALLOW authorization semantic missing" }
if ($health.pre_dispatch_governance_authorization_is_dispatch -ne $false) { Fail "Stage-3.5.3 authorization was incorrectly equated with dispatch" }
Pass "Stage 3.5.3 remains authoritative authorization; Stage 3.5.4 consumes rather than reissues it"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.4 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Attempt Schema           : $($finalHealth.execution_attempt_schema_version)"
Write-Host "Attempt Prefix           : $($finalHealth.execution_attempt_identity_prefix)"
Write-Host "Envelope Prefix          : $($finalHealth.dispatch_envelope_identity_prefix)"
Write-Host "Dispatch Commit Status   : $($finalHealth.execution_attempt_dispatch_commit_status)"
Write-Host "Execution Attempt Status : $($finalHealth.execution_attempt_status)"
Write-Host "Persistence Store        : $($finalHealth.execution_attempt_persistence_store)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Next Boundary            : Stage 3.5.5 delivery/ack/execution-start"
