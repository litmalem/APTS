param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.6 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.6-running-execution-state-heartbeat-projection"
$expected355 = "stage3.5.5-dispatch-delivery-execution-acknowledgement"
$expectedMigrationLevel = 32
$expectedTestCount = 893
$expectedFocusedCount = 18
$expectedSchema = "apts-running-execution-state-heartbeat-projection-v1"
$expectedPrefix = "xrun-"
$expectedMode = "AUTHORITATIVE_RUNTIME_RUNNING_STATE_WITH_APPEND_ONLY_HEARTBEAT_PROJECTION"
$expectedAuthority = "DOWNSTREAM_SUBSYSTEM_RUNTIME_EXECUTION_STATE"
$expectedState = "RUNNING"
$expectedAttemptStatus = "RUNNING_HEARTBEAT_CONFIRMED"
$expectedHeartbeatStatus = "ALIVE"
$expectedStore = "mission_execution_running_projections"

Write-Host "=============================================================================="
Write-Host "Stage 3.5.6 - Running Execution State & Heartbeat Projection"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.6 source is not active on port 8780" }
Pass "Stage 3.5.6 runtime control is active"

Write-Host "`n[1] Python compile"
Push-Location $PSScriptRoot
try {
    python -m compileall -q mission_orchestrator tests
    if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
} finally { Pop-Location }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
Push-Location $PSScriptRoot
try {
    $collectOutput = (& python -m pytest --collect-only -q 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { Fail "Pytest collection failed" }
} finally { Pop-Location }
if ($collectOutput -notmatch "(?m)$expectedTestCount tests collected") {
    Write-Host $collectOutput
    Fail "Expected exactly $expectedTestCount collected tests"
}
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.5.6 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally { Pop-Location }
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.6 proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_5_6_running_execution_state_heartbeat_projection.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
    if ($focusedExit -ne 0) { Fail "Focused Stage-3.5.6 proof failed" }
} finally { Pop-Location }
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") {
    Fail "Expected exactly $expectedFocusedCount focused Stage-3.5.6 tests to pass"
}
Pass "Focused Stage-3.5.6 RUNNING/heartbeat projection proof passed"

Write-Host "`n[5] Runtime identity, migration, and execution-control ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 32" }
if ([int]$health.running_execution_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.6 migration declaration is not 32" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2 -or $tail[0] -ne $expected355 -or $tail[1] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expected355, $expectedControl]"
}
Pass "Stage 3.5.5 -> Stage 3.5.6 ordering and migration level are correct"

Write-Host "`n[6] Canonical Stage-3.5.6 declaration"
if ($health.running_execution_schema_version -ne $expectedSchema) { Fail "Unexpected Stage-3.5.6 schema version" }
if ($health.running_execution_identity_prefix -ne $expectedPrefix) { Fail "Unexpected Stage-3.5.6 identity prefix" }
if ($health.running_execution_mode -ne $expectedMode) { Fail "Unexpected Stage-3.5.6 mode" }
if ($health.running_execution_authority -ne $expectedAuthority) { Fail "Unexpected Stage-3.5.6 authority" }
if ($health.running_execution_state -ne $expectedState) { Fail "Unexpected Stage-3.5.6 execution state" }
if ($health.running_execution_attempt_status -ne $expectedAttemptStatus) { Fail "Unexpected Stage-3.5.6 attempt status" }
if ($health.running_execution_heartbeat_status -ne $expectedHeartbeatStatus) { Fail "Unexpected Stage-3.5.6 heartbeat status" }
if ($health.running_execution_persistence_store -ne $expectedStore) { Fail "Unexpected Stage-3.5.6 persistence store" }
Pass "Canonical xrun RUNNING/heartbeat projection contract is active"

Write-Host "`n[7] Stage-3.5.5 source binding and append-only heartbeat invariants"
$requiredTrueFields = @(
    "running_execution_requires_stage355_delivery_acknowledgement",
    "running_execution_append_only_heartbeat_projection",
    "running_execution_heartbeat_sequence_monotonic_per_attempt",
    "running_execution_runtime_endpoint_reused_from_stage355",
    "running_execution_runtime_health_probe_performed",
    "running_execution_runtime_execution_state_query_performed",
    "running_execution_execution_start_observed",
    "running_execution_execution_started",
    "running_execution_running_state_recorded",
    "running_execution_heartbeat_recorded",
    "running_execution_projection_is_observation_not_execution_authority"
)
foreach ($field in $requiredTrueFields) {
    if ($health.$field -ne $true) { Fail "Stage-3.5.6 declaration missing: $field" }
}
Pass "Stage 3.5.6 requires Stage-3.5.5 and persists append-only RUNNING/heartbeat evidence"

Write-Host "`n[8] No new authority, no redelivery, no actuation"
$requiredFalseFields = @(
    "running_execution_runtime_endpoint_resolution_performed",
    "running_execution_governance_query_performed",
    "running_execution_dispatch_redelivery_performed",
    "running_execution_target_action_dispatch_performed",
    "running_execution_target_actuation"
)
foreach ($field in $requiredFalseFields) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.6 boundary drifted: $field" }
}
if ($health.execution_delivery_execution_started -ne $false) { Fail "Stage-3.5.5 immutable acknowledgement boundary drifted" }
if ($health.execution_delivery_heartbeat_recorded -ne $false) { Fail "Stage-3.5.5 incorrectly claims heartbeat ownership" }
Pass "Observation is separated from authorization, redelivery, target dispatch, and target actuation"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.6 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Projection Schema        : $($finalHealth.running_execution_schema_version)"
Write-Host "Projection Prefix        : $($finalHealth.running_execution_identity_prefix)"
Write-Host "Execution State          : $($finalHealth.running_execution_state)"
Write-Host "Heartbeat Status         : $($finalHealth.running_execution_heartbeat_status)"
Write-Host "Persistence Store        : $($finalHealth.running_execution_persistence_store)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.5.6      : $expectedFocusedCount"
Write-Host "Next Boundary            : Stage 3.5.7"
