param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.7 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.7-execution-result-evidence-artifact-capture"
$expected356 = "stage3.5.6-running-execution-state-heartbeat-projection"
$expectedMigrationLevel = 33
$expectedTestCount = 911
$expectedFocusedCount = 18
$expectedSchema = "apts-execution-result-evidence-artifact-capture-v1"
$expectedPrefix = "xresult-"
$expectedMode = "AUTHORITATIVE_RUNTIME_TERMINAL_RESULT_WITH_IMMUTABLE_EVIDENCE_ARTIFACT_MANIFEST"
$expectedAuthority = "DOWNSTREAM_SUBSYSTEM_RUNTIME_EXECUTION_RESULT"
$expectedAttemptStatus = "TERMINAL_RESULT_CAPTURED"
$expectedChannel = "RUNTIME_EXECUTION_TERMINAL_RESULT_READ"
$expectedStore = "mission_execution_result_captures"
$expectedTerminalStates = @("CANCELLED", "FAILED", "SUCCEEDED", "TIMED_OUT")

Write-Host "=============================================================================="
Write-Host "Stage 3.5.7 - Execution Result / Evidence / Artifact Capture"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.7 source is not active on port 8780" }
Pass "Stage 3.5.7 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.5.7 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally { Pop-Location }
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.7 proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_5_7_execution_result_evidence_artifact_capture.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
    if ($focusedExit -ne 0) { Fail "Focused Stage-3.5.7 proof failed" }
} finally { Pop-Location }
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") {
    Fail "Expected exactly $expectedFocusedCount focused Stage-3.5.7 tests to pass"
}
Pass "Focused Stage-3.5.7 terminal-result/evidence/artifact capture proof passed"

Write-Host "`n[5] Runtime identity, migration, and execution-control ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 33" }
if ([int]$health.execution_result_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.7 migration declaration is not 33" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2 -or $tail[0] -ne $expected356 -or $tail[1] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expected356, $expectedControl]"
}
Pass "Stage 3.5.6 -> Stage 3.5.7 ordering and migration level are correct"

Write-Host "`n[6] Canonical Stage-3.5.7 declaration"
if ($health.execution_result_schema_version -ne $expectedSchema) { Fail "Unexpected Stage-3.5.7 schema version" }
if ($health.execution_result_identity_prefix -ne $expectedPrefix) { Fail "Unexpected Stage-3.5.7 identity prefix" }
if ($health.execution_result_mode -ne $expectedMode) { Fail "Unexpected Stage-3.5.7 mode" }
if ($health.execution_result_authority -ne $expectedAuthority) { Fail "Unexpected Stage-3.5.7 authority" }
if ($health.execution_result_attempt_status -ne $expectedAttemptStatus) { Fail "Unexpected Stage-3.5.7 attempt status" }
if ($health.execution_result_runtime_result_channel -ne $expectedChannel) { Fail "Unexpected Stage-3.5.7 runtime result channel" }
if ($health.execution_result_persistence_store -ne $expectedStore) { Fail "Unexpected Stage-3.5.7 persistence store" }
$observedTerminalStates = @($health.execution_result_terminal_execution_states | Sort-Object)
if (($observedTerminalStates -join ",") -ne ($expectedTerminalStates -join ",")) {
    Fail "Unexpected terminal execution-state set: $($observedTerminalStates -join ',')"
}
Pass "Canonical xresult terminal-result contract is active"

Write-Host "`n[7] Source binding, evidence, artifact, and cardinality invariants"
$requiredTrueFields = @(
    "execution_result_requires_latest_stage356_running_projection",
    "execution_result_one_terminal_result_per_execution_attempt",
    "execution_result_runtime_endpoint_reused_from_stage355",
    "execution_result_runtime_health_probe_performed",
    "execution_result_runtime_terminal_result_query_performed",
    "execution_result_evidence_required",
    "execution_result_artifact_optional",
    "execution_result_is_not_task_completion_authority"
)
foreach ($field in $requiredTrueFields) {
    if ($health.$field -ne $true) { Fail "Stage-3.5.7 declaration missing: $field" }
}
Pass "Stage 3.5.7 binds latest xrun and captures authoritative terminal evidence without taking completion authority"

Write-Host "`n[8] No re-authorization, no redelivery, no inline artifact persistence, no mission transition"
$requiredFalseFields = @(
    "execution_result_runtime_endpoint_resolution_performed",
    "execution_result_governance_query_performed",
    "execution_result_dispatch_redelivery_performed",
    "execution_result_target_action_dispatch_performed",
    "execution_result_inline_artifact_payload_persisted",
    "execution_result_mission_state_transition_performed"
)
foreach ($field in $requiredFalseFields) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.7 boundary drifted: $field" }
}
if ($health.running_execution_state -ne "RUNNING") { Fail "Stage-3.5.6 RUNNING source declaration drifted" }
if ($health.running_execution_projection_is_observation_not_execution_authority -ne $true) { Fail "Stage-3.5.6 observation boundary drifted" }
Pass "Result capture is separated from Governance, endpoint resolution, redelivery, target dispatch, payload storage, and completion transition"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.7 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Result Schema            : $($finalHealth.execution_result_schema_version)"
Write-Host "Result Prefix            : $($finalHealth.execution_result_identity_prefix)"
Write-Host "Attempt Status           : $($finalHealth.execution_result_attempt_status)"
Write-Host "Persistence Store        : $($finalHealth.execution_result_persistence_store)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.5.7      : $expectedFocusedCount"
Write-Host "Next Boundary            : Stage 3.5.8"
