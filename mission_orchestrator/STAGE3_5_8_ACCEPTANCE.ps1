param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.8 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.5.8-timeout-cancellation-abort-failure-propagation"
$expected357 = "stage3.5.7-execution-result-evidence-artifact-capture"
$expectedMigrationLevel = 34
$expectedTestCount = 931
$expectedFocusedCount = 20
$expectedStageSchema = "apts-execution-timeout-cancellation-abort-failure-propagation-v1"
$expectedTerminationSchema = "apts-execution-termination-control-v1"
$expectedTerminationPrefix = "xterm-"
$expectedTerminationMode = "FAIL_CLOSED_RUNTIME_TIMEOUT_CANCELLATION_ABORT_CONTROL_PENDING_TERMINAL_RESULT"
$expectedTerminationAuthority = "MISSION_ORCHESTRATOR_EXECUTION_CONTROL_INTENT"
$expectedTerminationStore = "mission_execution_termination_controls"
$expectedOutcomeSchema = "apts-execution-terminal-outcome-propagation-v1"
$expectedOutcomePrefix = "xprop-"
$expectedOutcomeMode = "VERIFIED_TERMINAL_OUTCOME_WITH_FAIL_FAST_MISSION_FAILURE_PROPAGATION"
$expectedOutcomeAuthority = "MISSION_ORCHESTRATOR_VERIFIED_EXECUTION_OUTCOME_PROPAGATION"
$expectedOutcomeStore = "mission_execution_outcome_propagations"
$expectedActions = @("ABORT", "CANCEL", "TIMEOUT")

Write-Host "=============================================================================="
Write-Host "Stage 3.5.8 - Timeout, Cancellation, Abort & Failure Propagation"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.8 source is not active on port 8780" }
Pass "Stage 3.5.8 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.5.8 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally { Pop-Location }
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.8 proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_5_8_timeout_cancellation_abort_failure_propagation.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
    if ($focusedExit -ne 0) { Fail "Focused Stage-3.5.8 proof failed" }
} finally { Pop-Location }
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") {
    Fail "Expected exactly $expectedFocusedCount focused Stage-3.5.8 tests to pass"
}
Pass "Focused Stage-3.5.8 timeout/cancellation/abort/failure propagation proof passed"

Write-Host "`n[5] Runtime identity, migration, and execution-control ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 34" }
if ([int]$health.stage358_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.8 migration declaration is not 34" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2 -or $tail[0] -ne $expected357 -or $tail[1] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expected357, $expectedControl]"
}
Pass "Stage 3.5.7 -> Stage 3.5.8 ordering and migration level are correct"

Write-Host "`n[6] Canonical Stage-3.5.8 termination-control declaration"
if ($health.stage358_schema_version -ne $expectedStageSchema) { Fail "Unexpected Stage-3.5.8 stage schema" }
if ($health.execution_termination_control_schema_version -ne $expectedTerminationSchema) { Fail "Unexpected termination-control schema" }
if ($health.execution_termination_control_identity_prefix -ne $expectedTerminationPrefix) { Fail "Unexpected termination-control identity prefix" }
if ($health.execution_termination_control_mode -ne $expectedTerminationMode) { Fail "Unexpected termination-control mode" }
if ($health.execution_termination_control_authority -ne $expectedTerminationAuthority) { Fail "Unexpected termination-control authority" }
if ($health.execution_termination_control_persistence_store -ne $expectedTerminationStore) { Fail "Unexpected termination-control persistence store" }
$observedActions = @($health.execution_termination_control_actions | Sort-Object)
if (($observedActions -join ",") -ne ($expectedActions -join ",")) {
    Fail "Unexpected termination-control action set: $($observedActions -join ',')"
}
if ($health.execution_termination_expected_terminal_state_by_action.TIMEOUT -ne "TIMED_OUT") { Fail "TIMEOUT must expect TIMED_OUT" }
if ($health.execution_termination_expected_terminal_state_by_action.CANCEL -ne "CANCELLED") { Fail "CANCEL must expect CANCELLED" }
if ($health.execution_termination_expected_terminal_state_by_action.ABORT -ne "CANCELLED") { Fail "ABORT must expect CANCELLED" }
Pass "Canonical xterm runtime termination-control contract is active"

Write-Host "`n[7] Termination-control source binding and fail-closed boundaries"
$requiredTerminationTrue = @(
    "execution_termination_control_requires_latest_stage356_running_projection",
    "execution_termination_control_requires_no_stage357_terminal_result",
    "execution_termination_control_one_per_execution_attempt",
    "execution_termination_control_runtime_endpoint_reused_from_stage355",
    "execution_termination_control_runtime_health_probe_performed",
    "execution_termination_control_runtime_control_io_performed"
)
foreach ($field in $requiredTerminationTrue) {
    if ($health.$field -ne $true) { Fail "Stage-3.5.8 termination declaration missing: $field" }
}
$requiredTerminationFalse = @(
    "execution_termination_control_runtime_endpoint_resolution_performed",
    "execution_termination_control_governance_query_performed",
    "execution_termination_control_dispatch_redelivery_performed",
    "execution_termination_control_new_target_action_dispatch_performed",
    "execution_termination_control_mission_state_transition_performed"
)
foreach ($field in $requiredTerminationFalse) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.8 termination boundary drifted: $field" }
}
Pass "Termination control is bound to the current RUNNING attempt without re-authorization, re-resolution, redelivery, or Mission transition"

Write-Host "`n[8] Canonical terminal-outcome verification and propagation declaration"
if ($health.execution_outcome_propagation_schema_version -ne $expectedOutcomeSchema) { Fail "Unexpected outcome-propagation schema" }
if ($health.execution_outcome_propagation_identity_prefix -ne $expectedOutcomePrefix) { Fail "Unexpected outcome-propagation identity prefix" }
if ($health.execution_outcome_propagation_mode -ne $expectedOutcomeMode) { Fail "Unexpected outcome-propagation mode" }
if ($health.execution_outcome_propagation_authority -ne $expectedOutcomeAuthority) { Fail "Unexpected outcome-propagation authority" }
if ($health.execution_outcome_persistence_store -ne $expectedOutcomeStore) { Fail "Unexpected outcome-propagation persistence store" }
if ($health.execution_outcome_stage357_result_authoritative -ne $true) { Fail "Stage-3.5.7 result must remain authoritative" }
if ($health.execution_outcome_success_does_not_imply_mission_completion -ne $true) { Fail "Success must not imply Mission completion" }
if ($health.execution_outcome_failure_propagates_via_canonical_stage327_lifecycle -ne $true) { Fail "Non-success propagation must reuse canonical lifecycle control" }
if ($health.execution_outcome_failed_target_mission_state -ne "FAILED") { Fail "FAILED result target must be FAILED" }
if ($health.execution_outcome_timed_out_target_mission_state -ne "FAILED") { Fail "TIMED_OUT result target must be FAILED" }
if ($health.execution_outcome_cancelled_target_mission_state -ne "ABORTED") { Fail "CANCELLED result target must be ABORTED" }
Pass "Canonical xprop terminal-outcome verification and fail-fast propagation contract is active"

Write-Host "`n[9] Outcome propagation performs no new runtime/Governance/dispatch authority"
$requiredOutcomeFalse = @(
    "execution_outcome_runtime_result_query_performed",
    "execution_outcome_runtime_control_io_performed",
    "execution_outcome_governance_query_performed",
    "execution_outcome_dispatch_redelivery_performed",
    "execution_outcome_new_target_action_dispatch_performed"
)
foreach ($field in $requiredOutcomeFalse) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.8 outcome boundary drifted: $field" }
}
Pass "Outcome verification consumes durable Stage-3.5.7 evidence and does not create new runtime/Governance/dispatch authority"

$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.8 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Stage Schema             : $($finalHealth.stage358_schema_version)"
Write-Host "Termination Prefix       : $($finalHealth.execution_termination_control_identity_prefix)"
Write-Host "Outcome Prefix           : $($finalHealth.execution_outcome_propagation_identity_prefix)"
Write-Host "Termination Store        : $($finalHealth.execution_termination_control_persistence_store)"
Write-Host "Outcome Store            : $($finalHealth.execution_outcome_persistence_store)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.5.8      : $expectedFocusedCount"
Write-Host "Next Boundary            : Stage 3.5.9"
