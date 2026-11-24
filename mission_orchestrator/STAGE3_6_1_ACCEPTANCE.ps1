param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.6.1 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Assert-FalseFields($Object, [string[]]$Fields, [string]$Context) {
    foreach ($field in $Fields) {
        if ($Object.$field -ne $false) {
            Fail "$Context boundary drifted: $field must be false"
        }
    }
}

$expectedControl = "stage3.6.1-canonical-task-outcome-contract-identity"
$expectedPredecessor = "stage3.5.10-execution-dispatch-acceptance-regression-gate"
$expectedMigrationLevel = 36
$expectedTestCount = 982
$expectedFocusedCount = 19
$expectedStageSchema = "apts-task-outcome-contract-identity-v1"
$expectedContractSchema = "apts-canonical-task-outcome-contract-v1"
$expectedPrefix = "toutcome-"
$expectedMode = "IMMUTABLE_TASK_OUTCOME_IDENTITY_BOUND_TO_VERIFIED_TERMINAL_EXECUTION_PENDING_ACCEPTANCE"
$expectedAuthority = "MISSION_ORCHESTRATOR_TASK_OUTCOME_MATERIALIZATION"
$expectedContractStatus = "MATERIALIZED_PENDING_TASK_OUTCOME_ACCEPTANCE"
$expectedStore = "mission_task_outcomes"
$expectedSourceStatuses = @(
    "VERIFIED_CANCELLED",
    "VERIFIED_COMPLETED",
    "VERIFIED_FAILED",
    "VERIFIED_TIMED_OUT"
)
$expectedAllowedStates = @("ABORTED", "FAILED", "RUNNING")

Write-Host "=============================================================================="
Write-Host "Stage 3.6.1 - Canonical Task Outcome Contract & Identity"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.6.1 source is not active on port 8780" }
Pass "Stage 3.6.1 runtime control is active"

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
    $collectExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($collectExit -ne 0) {
    Write-Host $collectOutput
    Fail "Pytest collection failed"
}
if ($collectOutput -notmatch "(?m)$expectedTestCount tests collected") {
    Write-Host $collectOutput
    Fail "Expected exactly $expectedTestCount collected tests"
}
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.6.1 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.6.1 proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_6_1_canonical_task_outcome_contract_identity.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
} finally {
    Pop-Location
}
if ($focusedExit -ne 0) { Fail "Focused Stage-3.6.1 proof failed" }
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") {
    Fail "Expected exactly $expectedFocusedCount focused Stage-3.6.1 tests to pass"
}
Pass "Focused Stage-3.6.1 identity, idempotency, restart, lineage, integrity, and authority-boundary proof passed"

Write-Host "`n[5] Runtime identity, migration, and control ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not $expectedMigrationLevel" }
if ([int]$health.task_outcome_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.6.1 migration declaration is not $expectedMigrationLevel" }
if ($health.task_outcome_persistence_store -ne $expectedStore) { Fail "Stage-3.6.1 persistence store drifted" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2 -or $tail[0] -ne $expectedPredecessor -or $tail[1] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expectedPredecessor, $expectedControl]"
}
Pass "Stage 3.5.10 -> Stage 3.6.1 ordering and migration level are correct"

Write-Host "`n[6] Canonical task-outcome contract declaration"
if ($health.task_outcome_stage_schema_version -ne $expectedStageSchema) { Fail "Unexpected Stage-3.6.1 stage schema" }
if ($health.task_outcome_contract_schema_version -ne $expectedContractSchema) { Fail "Unexpected canonical task-outcome schema" }
if ($health.task_outcome_identity_prefix -ne $expectedPrefix) { Fail "Unexpected task-outcome identity prefix" }
if ($health.task_outcome_mode -ne $expectedMode) { Fail "Unexpected task-outcome mode" }
if ($health.task_outcome_authority -ne $expectedAuthority) { Fail "Unexpected task-outcome authority" }
if ($health.task_outcome_contract_status -ne $expectedContractStatus) { Fail "Unexpected task-outcome contract status" }
if ($health.task_outcome_one_identity_per_plan_task -ne $true) { Fail "One immutable identity per Plan task invariant is not active" }
if ($health.task_outcome_identity_materialized -ne $true) { Fail "Task-outcome identity materialization declaration is not active" }
Pass "Canonical immutable toutcome-* contract declaration is active"

Write-Host "`n[7] Stage-3.5 source prerequisite declaration"
$requiredTrue = @(
    "task_outcome_requires_stage3510_closed_runtime_release",
    "task_outcome_requires_active_plan_version",
    "task_outcome_requires_stage354_execution_attempt",
    "task_outcome_requires_stage357_terminal_result_capture",
    "task_outcome_requires_stage358_verified_outcome_propagation",
    "task_outcome_requires_stage359_execution_recovery_checkpoint"
)
foreach ($field in $requiredTrue) {
    if ($health.$field -ne $true) { Fail "Stage-3.6.1 prerequisite drifted: $field" }
}

$observedStatuses = @($health.task_outcome_source_statuses)
if ($observedStatuses.Count -ne $expectedSourceStatuses.Count) { Fail "Task-outcome source-status cardinality drifted" }
for ($i = 0; $i -lt $expectedSourceStatuses.Count; $i++) {
    if ($observedStatuses[$i] -ne $expectedSourceStatuses[$i]) {
        Fail "Task-outcome source-status mismatch at index $i"
    }
}
$observedStates = @($health.task_outcome_allowed_mission_states)
if ($observedStates.Count -ne $expectedAllowedStates.Count) { Fail "Allowed Mission-state cardinality drifted" }
for ($i = 0; $i -lt $expectedAllowedStates.Count; $i++) {
    if ($observedStates[$i] -ne $expectedAllowedStates[$i]) {
        Fail "Allowed Mission-state mismatch at index $i"
    }
}
Pass "Stage-3.6.1 remains bound to the closed Stage-3.5 terminal execution trajectory"

Write-Host "`n[8] No acceptance / completion / dependency / progression authority"
Assert-FalseFields $health @(
    "task_outcome_acceptance_performed",
    "task_outcome_acceptance_criteria_evaluation_performed",
    "task_outcome_completion_commit_performed",
    "task_outcome_state_transition_performed",
    "task_outcome_dependency_release_performed",
    "task_outcome_readiness_recalculation_performed",
    "task_outcome_plan_progression_performed",
    "task_outcome_mission_success_completion_authority_exercised"
) "Stage-3.6.1 task semantics"
Pass "Task-outcome identity is not elevated into acceptance, completion, dependency release, Plan progression, or Mission completion"

Write-Host "`n[9] No Governance / runtime / redispatch / actuation authority"
Assert-FalseFields $health @(
    "task_outcome_governance_query_performed",
    "task_outcome_runtime_query_performed",
    "task_outcome_runtime_control_io_performed",
    "task_outcome_dispatch_redelivery_performed",
    "task_outcome_new_execution_attempt_created",
    "task_outcome_new_target_action_dispatch_performed",
    "task_outcome_external_network_io_performed",
    "task_outcome_target_actuation",
    "task_outcome_mission_state_transition_performed"
) "Stage-3.6.1 external-authority"
Pass "Stage 3.6.1 cannot contact Governance/runtime, redispatch, create another execution attempt, actuate, or transition Mission state"

Write-Host "`n[10] Migration 036 and canonical store source check"
$migrationPath = Join-Path $PSScriptRoot "migrations\036_stage3_6_1_canonical_task_outcome_contract_identity.sql"
if (-not (Test-Path $migrationPath)) { Fail "Migration 036 file is missing" }
$migrationText = Get-Content -Raw $migrationPath
if ($migrationText -notmatch "mission_task_outcomes") { Fail "Migration 036 does not define mission_task_outcomes" }
if ($migrationText -notmatch "uq_task_outcome_plan_task") { Fail "Migration 036 lacks one-outcome-per-Plan-task uniqueness" }
if ($migrationText -notmatch "uq_task_outcome_idempotency") { Fail "Migration 036 lacks canonical idempotency uniqueness" }
Pass "Migration 036 defines the canonical task-outcome durable store and uniqueness guards"

Write-Host "`n[11] Final runtime revalidation"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.status -ne "ok") { Fail "Final Mission Orchestrator health is not ok" }
if ($finalHealth.control_version -ne $expectedControl) { Fail "Runtime control drifted during acceptance" }
if ([int]$finalHealth.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Migration level drifted during acceptance" }
Pass "Final Stage-3.6.1 runtime identity is stable"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Task Outcome Schema      : $($finalHealth.task_outcome_contract_schema_version)"
Write-Host "Task Outcome Prefix      : $($finalHealth.task_outcome_identity_prefix)"
Write-Host "Task Outcome Store       : $($finalHealth.task_outcome_persistence_store)"
Write-Host "Acceptance Performed     : $($finalHealth.task_outcome_acceptance_performed)"
Write-Host "Completion Commit        : $($finalHealth.task_outcome_completion_commit_performed)"
Write-Host "Dependency Release       : $($finalHealth.task_outcome_dependency_release_performed)"
Write-Host "Target Actuation         : $($finalHealth.task_outcome_target_actuation)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.6.1      : $expectedFocusedCount"
Write-Host "Next Boundary            : Stage 3.6.2"
Write-Host "=============================================================================="
exit 0
