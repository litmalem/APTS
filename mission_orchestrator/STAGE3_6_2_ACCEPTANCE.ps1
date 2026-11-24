param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.6.2 ACCEPTANCE: FAIL" -ForegroundColor Red
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

$expectedControl = "stage3.6.2-task-terminality-completion-eligibility"
$expectedPredecessor = "stage3.6.1-canonical-task-outcome-contract-identity"
$expectedMigrationLevel = 37
$expectedTestCount = 1002
$expectedFocusedCount = 20
$expectedStageSchema = "apts-task-terminality-completion-eligibility-v1"
$expectedContractSchema = "apts-task-terminality-completion-eligibility-contract-v1"
$expectedPrefix = "telig-"
$expectedMode = "DETERMINISTIC_LOCAL_TERMINALITY_AND_COMPLETION_ELIGIBILITY_NO_COMPLETION_COMMIT"
$expectedAuthority = "MISSION_ORCHESTRATOR_TASK_TERMINALITY_COMPLETION_ELIGIBILITY"
$expectedGateStatus = "EVALUATED"
$expectedStore = "mission_task_terminality_eligibility_gates"
$expectedSourceStatuses = @(
    "VERIFIED_CANCELLED",
    "VERIFIED_COMPLETED",
    "VERIFIED_FAILED",
    "VERIFIED_TIMED_OUT"
)
$expectedAllowedStates = @("ABORTED", "FAILED", "RUNNING")

Write-Host "=============================================================================="
Write-Host "Stage 3.6.2 - Task Terminality & Completion Eligibility"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.6.2 source is not active on port 8780" }
Pass "Stage 3.6.2 runtime control is active"

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

Write-Host "`n[3] Full Stage 3.1-3.6.2 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.6.2 proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_6_2_task_terminality_completion_eligibility.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
} finally {
    Pop-Location
}
if ($focusedExit -ne 0) { Fail "Focused Stage-3.6.2 proof failed" }
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") {
    Fail "Expected exactly $expectedFocusedCount focused Stage-3.6.2 tests to pass"
}
Pass "Focused Stage-3.6.2 terminality, eligibility, idempotency, restart, lineage, integrity, and authority-boundary proof passed"

Write-Host "`n[5] Runtime identity, migration, and control ordering"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not $expectedMigrationLevel" }
if ([int]$health.task_terminality_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.6.2 migration declaration is not $expectedMigrationLevel" }
if ($health.task_terminality_persistence_store -ne $expectedStore) { Fail "Stage-3.6.2 persistence store drifted" }
$tail = @($health.supported_controls | Select-Object -Last 2)
if ($tail.Count -ne 2 -or $tail[0] -ne $expectedPredecessor -or $tail[1] -ne $expectedControl) {
    Fail "Expected supported-control tail [$expectedPredecessor, $expectedControl]"
}
Pass "Stage 3.6.1 -> Stage 3.6.2 ordering and migration level are correct"

Write-Host "`n[6] Canonical terminality / completion-eligibility contract declaration"
if ($health.task_terminality_stage_schema_version -ne $expectedStageSchema) { Fail "Unexpected Stage-3.6.2 stage schema" }
if ($health.task_terminality_contract_schema_version -ne $expectedContractSchema) { Fail "Unexpected Stage-3.6.2 contract schema" }
if ($health.task_terminality_identity_prefix -ne $expectedPrefix) { Fail "Unexpected Stage-3.6.2 identity prefix" }
if ($health.task_terminality_mode -ne $expectedMode) { Fail "Unexpected Stage-3.6.2 mode" }
if ($health.task_terminality_authority -ne $expectedAuthority) { Fail "Unexpected Stage-3.6.2 authority" }
if ($health.task_terminality_gate_status -ne $expectedGateStatus) { Fail "Unexpected Stage-3.6.2 gate status" }
if ($health.task_terminality_requires_stage361_task_outcome_identity -ne $true) { Fail "Stage-3.6.1 source-outcome prerequisite is not active" }
if ($health.task_terminality_requires_active_plan_version -ne $true) { Fail "Active-Plan prerequisite is not active" }
if ($health.task_terminality_one_gate_per_task_outcome -ne $true) { Fail "One immutable gate per task outcome invariant is not active" }
if ($health.task_terminality_deterministic_local_classification -ne $true) { Fail "Deterministic local classification declaration is not active" }
if ($health.task_terminality_completion_eligible_only_for_verified_completed -ne $true) { Fail "VERIFIED_COMPLETED-only eligibility declaration is not active" }
Pass "Canonical immutable telig-* terminality/completion-eligibility gate is active"

Write-Host "`n[7] Source statuses and deterministic terminal classification boundary"
$observedStatuses = @($health.task_terminality_source_statuses)
if ($observedStatuses.Count -ne $expectedSourceStatuses.Count) { Fail "Task terminality source-status cardinality drifted" }
for ($i = 0; $i -lt $expectedSourceStatuses.Count; $i++) {
    if ($observedStatuses[$i] -ne $expectedSourceStatuses[$i]) {
        Fail "Task terminality source-status mismatch at index $i"
    }
}
$observedStates = @($health.task_terminality_allowed_mission_states)
if ($observedStates.Count -ne $expectedAllowedStates.Count) { Fail "Allowed Mission-state cardinality drifted" }
for ($i = 0; $i -lt $expectedAllowedStates.Count; $i++) {
    if ($observedStates[$i] -ne $expectedAllowedStates[$i]) {
        Fail "Allowed Mission-state mismatch at index $i"
    }
}
Push-Location $PSScriptRoot
try {
    python -c "from mission_orchestrator.task_terminality import classify_task_terminality_and_completion_eligibility as c; assert c('VERIFIED_COMPLETED')['completion_eligible'] is True; assert c('VERIFIED_FAILED')['completion_eligible'] is False; assert c('VERIFIED_CANCELLED')['completion_eligible'] is False; assert c('VERIFIED_TIMED_OUT')['completion_eligible'] is False"
    if ($LASTEXITCODE -ne 0) { Fail "Deterministic terminal classification proof failed" }
} finally {
    Pop-Location
}
Pass "All four Stage-3.6.1 terminal outcomes classify deterministically; only VERIFIED_COMPLETED is completion-eligible"

Write-Host "`n[8] No acceptance / completion / dependency / progression authority"
Assert-FalseFields $health @(
    "task_terminality_acceptance_performed",
    "task_terminality_acceptance_criteria_evaluation_performed",
    "task_terminality_completion_commit_performed",
    "task_terminality_state_transition_performed",
    "task_terminality_dependency_release_performed",
    "task_terminality_readiness_recalculation_performed",
    "task_terminality_plan_progression_performed",
    "task_terminality_mission_success_completion_authority_exercised"
) "Stage-3.6.2 task semantics"
Pass "Completion eligibility is not elevated into acceptance, completion commit, dependency release, Plan progression, or Mission completion"

Write-Host "`n[9] No Governance / runtime / redispatch / actuation authority"
Assert-FalseFields $health @(
    "task_terminality_governance_query_performed",
    "task_terminality_runtime_query_performed",
    "task_terminality_runtime_control_io_performed",
    "task_terminality_dispatch_redelivery_performed",
    "task_terminality_new_execution_attempt_created",
    "task_terminality_new_target_action_dispatch_performed",
    "task_terminality_external_network_io_performed",
    "task_terminality_target_actuation",
    "task_terminality_mission_state_transition_performed"
) "Stage-3.6.2 external-authority"
Pass "Stage 3.6.2 is a local read/derive/persist gate and cannot contact Governance/runtime, redispatch, actuate, or transition Mission state"

Write-Host "`n[10] Migration 037 and canonical durable-store source check"
$migrationPath = Join-Path $PSScriptRoot "migrations\037_stage3_6_2_task_terminality_completion_eligibility.sql"
if (-not (Test-Path $migrationPath)) { Fail "Migration 037 file is missing" }
$migrationText = Get-Content -Raw $migrationPath
if ($migrationText -notmatch "mission_task_terminality_eligibility_gates") { Fail "Migration 037 does not define mission_task_terminality_eligibility_gates" }
if ($migrationText -notmatch "uq_task_terminality_eligibility_outcome") { Fail "Migration 037 lacks one-gate-per-task-outcome uniqueness" }
if ($migrationText -notmatch "uq_task_terminality_eligibility_idempotency") { Fail "Migration 037 lacks canonical idempotency uniqueness" }
Pass "Migration 037 defines the durable eligibility-gate store and uniqueness guards"

Write-Host "`n[11] Final runtime revalidation"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.status -ne "ok") { Fail "Final Mission Orchestrator health is not ok" }
if ($finalHealth.control_version -ne $expectedControl) { Fail "Runtime control drifted during acceptance" }
if ([int]$finalHealth.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Migration level drifted during acceptance" }
Pass "Final Stage-3.6.2 runtime identity is stable"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.2 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Terminality Schema       : $($finalHealth.task_terminality_contract_schema_version)"
Write-Host "Eligibility Prefix       : $($finalHealth.task_terminality_identity_prefix)"
Write-Host "Eligibility Store        : $($finalHealth.task_terminality_persistence_store)"
Write-Host "Completion Commit        : $($finalHealth.task_terminality_completion_commit_performed)"
Write-Host "Dependency Release       : $($finalHealth.task_terminality_dependency_release_performed)"
Write-Host "Target Actuation         : $($finalHealth.task_terminality_target_actuation)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.6.2      : $expectedFocusedCount"
Write-Host "Next Boundary            : Stage 3.6.3"
Write-Host "=============================================================================="
exit 0
