param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.9 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }

$expectedControl = "stage3.5.9-execution-event-lineage-replay-recovery"
$expected358 = "stage3.5.8-timeout-cancellation-abort-failure-propagation"
$expectedMigrationLevel = 35
$expectedTestCount = 951
$expectedFocusedCount = 20
$expectedLineageSchema = "apts-execution-event-lineage-v1"
$expectedReplaySchema = "apts-execution-event-replay-v1"
$expectedRecoverySchema = "apts-execution-recovery-checkpoint-v1"
$expectedRecoveryPrefix = "xrecover-"
$expectedRecoveryStore = "mission_execution_recovery_checkpoints"

Write-Host "=============================================================================="
Write-Host "Stage 3.5.9 - Execution Event Lineage, Replay & Recovery"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator is not reachable at $MissionBaseUrl" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.9 source is not active on port 8780" }
Pass "Stage 3.5.9 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.5.9 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally { Pop-Location }
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.9 proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_5_9_execution_event_lineage_replay_recovery.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
    if ($focusedExit -ne 0) { Fail "Focused Stage-3.5.9 proof failed" }
} finally { Pop-Location }
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") { Fail "Expected exactly $expectedFocusedCount focused Stage-3.5.9 tests to pass" }
Pass "Focused Stage-3.5.9 lineage/replay/recovery proof passed"

Write-Host "`n[5] Runtime identity, ordering, and migration"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 35" }
if ([int]$health.execution_recovery_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5.9 migration declaration is not 35" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2 -or $tail[0] -ne $expected358 -or $tail[1] -ne $expectedControl) { Fail "Expected supported-control tail [$expected358, $expectedControl]" }
Pass "Stage 3.5.8 -> Stage 3.5.9 ordering and migration level are correct"

Write-Host "`n[6] Canonical execution lineage/replay/recovery declaration"
if ($health.execution_event_lineage_schema_version -ne $expectedLineageSchema) { Fail "Unexpected execution-lineage schema" }
if ($health.execution_event_replay_schema_version -ne $expectedReplaySchema) { Fail "Unexpected execution-replay schema" }
if ($health.execution_recovery_checkpoint_schema_version -ne $expectedRecoverySchema) { Fail "Unexpected execution-recovery schema" }
if ($health.execution_recovery_checkpoint_identity_prefix -ne $expectedRecoveryPrefix) { Fail "Unexpected recovery checkpoint identity prefix" }
if ($health.execution_recovery_persistence_store -ne $expectedRecoveryStore) { Fail "Unexpected recovery persistence store" }
if ($health.execution_recovery_requires_stage358_terminal_outcome_propagation -ne $true) { Fail "Recovery must require Stage-3.5.8 terminal outcome propagation" }
if ($health.execution_recovery_termination_control_optional -ne $true) { Fail "Stage-3.5.8 termination control must remain optional" }
if ($health.execution_replay_read_only -ne $true) { Fail "Execution replay must be read-only" }
Pass "Canonical xrecover execution recovery contract is active"

Write-Host "`n[7] Non-actuating replay/recovery authority boundaries"
$requiredFalse = @(
    "execution_replay_side_effects_performed",
    "execution_recovery_runtime_health_probe_performed",
    "execution_recovery_runtime_result_query_performed",
    "execution_recovery_runtime_control_io_performed",
    "execution_recovery_external_network_io_performed",
    "execution_recovery_governance_query_performed",
    "execution_recovery_dispatch_redelivery_performed",
    "execution_recovery_new_execution_attempt_created",
    "execution_recovery_new_target_action_dispatch_performed",
    "execution_recovery_mission_state_transition_performed",
    "execution_recovery_failure_propagation_performed",
    "execution_recovery_mission_success_completion_authority_exercised",
    "execution_replay_is_execution",
    "execution_recovery_is_authorization",
    "execution_recovery_is_dispatch",
    "execution_recovery_is_runtime_resumption",
    "execution_recovery_is_lifecycle_transition",
    "execution_recovery_target_actuation"
)
foreach ($field in $requiredFalse) {
    if ($health.$field -ne $false) { Fail "Stage-3.5.9 authority boundary drifted: $field" }
}
if ($health.execution_recovery_reconstructs_from_durable_repository -ne $true) { Fail "Recovery must reconstruct from durable repository" }
Pass "Replay/recovery cannot query runtime/Governance, redispatch, resume, actuate, or transition Mission state"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.9 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($health.control_version)"
Write-Host "Repository Migration     : $($health.mission_repository_migration_level)"
Write-Host "Lineage Schema           : $($health.execution_event_lineage_schema_version)"
Write-Host "Replay Schema            : $($health.execution_event_replay_schema_version)"
Write-Host "Recovery Prefix          : $($health.execution_recovery_checkpoint_identity_prefix)"
Write-Host "Recovery Store           : $($health.execution_recovery_persistence_store)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.5.9      : $expectedFocusedCount"
Write-Host "Next Boundary            : Stage 3.5.10"
