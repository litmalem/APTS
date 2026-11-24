param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.5 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.5-dispatch-delivery-execution-acknowledgement"
$expected351 = "stage3.5.1-canonical-execution-dispatch-contract-identity"
$expected352 = "stage3.5.2-dispatch-eligibility-execution-preconditions"
$expected353 = "stage3.5.3-authoritative-pre-dispatch-governance-revalidation"
$expected354 = "stage3.5.4-idempotent-dispatch-execution-attempt-identity"
$expectedMigrationLevel = 31
$expectedTestCount = 875
$expectedFocusedCount = 19
$expectedSchema = "apts-dispatch-delivery-execution-acknowledgement-v1"
$expectedPrefix = "xack-"
$expectedMode = "RUNTIME_DISPATCH_ENVELOPE_DELIVERY_WITH_EXECUTION_ACKNOWLEDGEMENT_PENDING_RUNNING"
$expectedAuthority = "DOWNSTREAM_SUBSYSTEM_EXECUTION_INTAKE_ACKNOWLEDGEMENT"
$expectedChannel = "RUNTIME_SUBSYSTEM_EXECUTION_INTAKE"
$expectedDeliveryStatus = "DELIVERED_TO_RUNTIME"
$expectedAckStatus = "ACKNOWLEDGED_ACCEPTED_FOR_EXECUTION"
$expectedAttemptStatus = "DELIVERED_ACKNOWLEDGED_PENDING_RUNNING"
$expectedStore = "mission_execution_deliveries"

Write-Host "=============================================================================="
Write-Host "Stage 3.5.5 - Dispatch Delivery & Execution Acknowledgement"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.5 source is not active on port 8780" }
Pass "Stage 3.5.5 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.5.5 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.5 proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_5_5_dispatch_delivery_execution_acknowledgement.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
    if ($focusedExit -ne 0) { Fail "Focused Stage-3.5.5 proof failed" }
} finally {
    Pop-Location
}
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") {
    Fail "Expected exactly $expectedFocusedCount focused Stage-3.5.5 tests to pass"
}
Pass "Focused Stage-3.5.5 dispatch delivery/acknowledgement proof passed"

Write-Host "`n[5] Runtime identity, migration, and execution-control ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 31" }
if ([int]$health.execution_delivery_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.5 migration declaration is not 31" }
$tail = @($health.supported_controls | Select-Object -Last 5)
if ($tail.Count -ne 5) { Fail "Supported-control tail cardinality is not 5" }
if ($tail[0] -ne $expected351 -or $tail[1] -ne $expected352 -or $tail[2] -ne $expected353 -or $tail[3] -ne $expected354 -or $tail[4] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expected351, $expected352, $expected353, $expected354, $expectedControl]"
}
Pass "Stage 3.5.1 -> 3.5.2 -> 3.5.3 -> 3.5.4 -> 3.5.5 ordering and migration level are correct"

Write-Host "`n[6] Canonical Stage-3.5.5 declaration"
if ($health.execution_delivery_schema_version -ne $expectedSchema) { Fail "Unexpected Stage-3.5.5 schema version" }
if ($health.execution_delivery_identity_prefix -ne $expectedPrefix) { Fail "Unexpected Stage-3.5.5 identity prefix" }
if ($health.execution_delivery_mode -ne $expectedMode) { Fail "Unexpected Stage-3.5.5 mode" }
if ($health.execution_delivery_authority -ne $expectedAuthority) { Fail "Unexpected Stage-3.5.5 authority" }
if ($health.execution_delivery_channel -ne $expectedChannel) { Fail "Unexpected Stage-3.5.5 delivery channel" }
if ($health.execution_delivery_status -ne $expectedDeliveryStatus) { Fail "Unexpected Stage-3.5.5 delivery status" }
if ($health.execution_delivery_acknowledgement_status -ne $expectedAckStatus) { Fail "Unexpected Stage-3.5.5 acknowledgement status" }
if ($health.execution_delivery_attempt_status -ne $expectedAttemptStatus) { Fail "Unexpected Stage-3.5.5 attempt status" }
if ($health.execution_delivery_persistence_store -ne $expectedStore) { Fail "Unexpected Stage-3.5.5 persistence store" }
if (@($health.execution_delivery_allowed_states).Count -ne 1 -or $health.execution_delivery_allowed_states[0] -ne "RUNNING") { Fail "Stage-3.5.5 source-state boundary drifted" }
Pass "Canonical xack delivery/acknowledgement contract is active"

Write-Host "`n[7] Predecessor, authorization, and idempotency invariants"
if ($health.execution_delivery_requires_stage354_committed_execution_attempt -ne $true) { Fail "Stage-3.5.4 committed-attempt requirement missing" }
if ($health.execution_delivery_requires_current_latest_stage353_allow -ne $true) { Fail "Latest Stage-3.5.3 ALLOW requirement missing" }
if ($health.execution_delivery_one_ack_per_attempt -ne $true) { Fail "One-ack-per-attempt invariant missing" }
if ($health.execution_delivery_remote_replay_key_is_dispatch_envelope_identity -ne $true) { Fail "xenv downstream replay-key invariant missing" }
if ($health.execution_delivery_governance_query_performed -ne $false) { Fail "Stage 3.5.5 unexpectedly declares a new Governance query" }
Pass "Stage 3.5.5 preserves Stage-3.5.3 authority and Stage-3.5.4 immutable attempt/envelope identity"

Write-Host "`n[8] Runtime delivery and acknowledgement boundary is open"
$requiredTrueFields = @(
    "execution_delivery_runtime_endpoint_resolution_performed",
    "execution_delivery_runtime_health_probe_performed",
    "execution_delivery_target_delivery_performed",
    "execution_delivery_acknowledgement_performed",
    "execution_delivery_execution_start_acknowledged",
    "execution_delivery_external_target_network_io_performed",
    "execution_delivery_target_action_dispatch_performed"
)
foreach ($field in $requiredTrueFields) {
    if ($health.$field -ne $true) { Fail "Stage-3.5.5 runtime-delivery declaration missing: $field" }
}
Pass "Runtime endpoint resolution, health probe, delivery, and execution acknowledgement are Stage-3.5.5 capabilities"

Write-Host "`n[9] Stage-3.5.6 RUNNING/heartbeat and target actuation remain closed"
$requiredFalseFields = @(
    "execution_delivery_execution_started",
    "execution_delivery_running_state_recorded",
    "execution_delivery_heartbeat_recorded",
    "execution_delivery_target_actuation"
)
foreach ($field in $requiredFalseFields) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.5 boundary drifted: $field" }
}
if ($health.execution_attempt_target_delivery_performed -ne $false) { Fail "Stage-3.5.4 was incorrectly changed into the delivery stage" }
if ($health.execution_attempt_execution_started -ne $false) { Fail "Stage-3.5.4 execution-start boundary drifted" }
Pass "Stage 3.5.5 stops at accepted execution intake; Stage 3.5.6 owns RUNNING/heartbeat and actuation remains false"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.5 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Delivery Schema          : $($finalHealth.execution_delivery_schema_version)"
Write-Host "Delivery Prefix          : $($finalHealth.execution_delivery_identity_prefix)"
Write-Host "Delivery Status          : $($finalHealth.execution_delivery_status)"
Write-Host "Acknowledgement Status   : $($finalHealth.execution_delivery_acknowledgement_status)"
Write-Host "Attempt Status           : $($finalHealth.execution_delivery_attempt_status)"
Write-Host "Persistence Store        : $($finalHealth.execution_delivery_persistence_store)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.5.5      : $expectedFocusedCount"
Write-Host "Next Boundary            : Stage 3.5.6 Running State & Heartbeat"
