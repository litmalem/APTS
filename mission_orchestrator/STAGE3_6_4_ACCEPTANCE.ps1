param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.6.4 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Assert-FalseField($Object, [string]$Field, [string]$Context) {
    if ($Object.$Field -ne $false) {
        Fail "$Context boundary drifted: $Field must be false"
    }
}

function Assert-TrueField($Object, [string]$Field, [string]$Context) {
    if ($Object.$Field -ne $true) {
        Fail "$Context contract drifted: $Field must be true"
    }
}

$expectedControl = "stage3.6.4-dependency-aware-task-completion"
$expectedPredecessor = "stage3.6.3-evidence-binding-verification"
$expectedMigrationLevel = 39
$expectedTestCount = 1042
$expectedFocusedCount = 20
$expectedStage6Count = 79
$expectedStageSchema = "apts-dependency-aware-task-completion-v1"
$expectedContractSchema = "apts-dependency-aware-task-completion-contract-v1"
$expectedPrefix = "tcomp-"
$expectedStore = "mission_task_completion_commits"
$expectedStatus = "COMPLETED_DEPENDENCY_CONSISTENT"
$expectedDependencyStatus = "DEPENDENCIES_SATISFIED"
$expectedAcceptanceStatus = "ACCEPTED_FOR_TASK_COMPLETION"

Write-Host "=============================================================================="
Write-Host "Stage 3.6.4 - Dependency-Aware Task Completion"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try {
    $health = Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)"
}

Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if ($health.status -ne "ok") { Fail "health.status must be ok" }
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.6.4 runtime control is not active" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) {
    Fail "repository migration level must be $expectedMigrationLevel"
}
if ($health.task_completion_stage_schema_version -ne $expectedStageSchema) {
    Fail "unexpected Stage-3.6.4 stage schema"
}
if ($health.task_completion_contract_schema_version -ne $expectedContractSchema) {
    Fail "unexpected Stage-3.6.4 contract schema"
}
if ($health.task_completion_identity_prefix -ne $expectedPrefix) {
    Fail "unexpected Stage-3.6.4 identity prefix"
}
if ($health.task_completion_persistence_store -ne $expectedStore) {
    Fail "unexpected Stage-3.6.4 persistence store"
}
if ($health.task_completion_status -ne $expectedStatus) {
    Fail "unexpected Stage-3.6.4 completion status"
}
if ($health.task_completion_dependency_status -ne $expectedDependencyStatus) {
    Fail "unexpected Stage-3.6.4 dependency status"
}
if ($health.task_completion_acceptance_status -ne $expectedAcceptanceStatus) {
    Fail "unexpected Stage-3.6.4 acceptance status"
}
if ([int]$health.task_completion_database_migration_level -ne $expectedMigrationLevel) {
    Fail "Stage-3.6.4 database migration metadata must be $expectedMigrationLevel"
}
$supported = @($health.supported_controls)
if ($supported.Count -lt 2 -or $supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl) {
    Fail "supported control tail must end with Stage 3.6.3 then Stage 3.6.4"
}
foreach ($field in @(
    "task_completion_requires_stage363_verified_evidence_binding",
    "task_completion_requires_stage362_completion_eligible_gate",
    "task_completion_requires_stage361_completed_task_outcome",
    "task_completion_requires_active_plan_version",
    "task_completion_requires_all_prerequisite_task_completions",
    "task_completion_rejects_superseded_plan_dependency_completions",
    "task_completion_one_commit_per_active_plan_task",
    "task_completion_task_outcome_acceptance_performed",
    "task_completion_dependency_precondition_evaluation_performed",
    "task_completion_task_completion_commit_performed",
    "task_completion_canonical_completion_record_created"
)) {
    Assert-TrueField $health $field "health"
}
foreach ($field in @(
    "task_completion_task_state_transition_performed",
    "task_completion_dependency_release_performed",
    "task_completion_readiness_recalculation_performed",
    "task_completion_plan_progression_performed",
    "task_completion_mission_success_completion_authority_exercised",
    "task_completion_governance_query_performed",
    "task_completion_runtime_query_performed",
    "task_completion_runtime_control_io_performed",
    "task_completion_dispatch_redelivery_performed",
    "task_completion_new_execution_attempt_created",
    "task_completion_new_target_action_dispatch_performed",
    "task_completion_external_network_io_performed",
    "task_completion_target_actuation",
    "task_completion_mission_state_transition_performed"
)) {
    Assert-FalseField $health $field "health"
}
Pass "Stage 3.6.4 runtime control and authority boundary are active"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { Write-Host $collect; Fail "pytest collection failed" }
if ($collect -notmatch "(?m)^$expectedTestCount tests collected") {
    Write-Host $collect
    Fail "canonical regression inventory must contain exactly $expectedTestCount tests"
}
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.6.4 regression"
& python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "full Stage 3.1-3.6.4 regression failed" }
Pass "Full Stage 3.1-3.6.4 regression passed"

Write-Host "`n[4] Stage 3.6 chain regression"
$stage6 = (& python -m pytest -q `
    tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py `
    tests/test_stage3_6_2_task_terminality_completion_eligibility.py `
    tests/test_stage3_6_3_evidence_binding_verification.py `
    tests/test_stage3_6_4_dependency_aware_task_completion.py 2>&1 | Out-String)
Write-Host $stage6.TrimEnd()
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.6 chain regression failed" }
if ($stage6 -notmatch "(?m)^$expectedStage6Count passed") {
    Fail "Stage-3.6 chain suite must report exactly $expectedStage6Count passed"
}
Pass "Stage-3.6.1 through Stage-3.6.4 chain passed"

Write-Host "`n[5] Focused Stage 3.6.4 proof"
$focused = (& python -m pytest -q tests/test_stage3_6_4_dependency_aware_task_completion.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0) { Fail "focused Stage-3.6.4 tests failed" }
if ($focused -notmatch "(?m)^$expectedFocusedCount passed") {
    Fail "focused Stage-3.6.4 suite must report exactly $expectedFocusedCount passed"
}
Pass "Focused Stage-3.6.4 proof passed"

Write-Host "`n[6] Migration / source / API registration"
if (-not (Test-Path "migrations/039_stage3_6_4_dependency_aware_task_completion.sql")) {
    Fail "migration 039 is missing"
}
if (-not (Test-Path "mission_orchestrator/task_completion.py")) {
    Fail "Stage-3.6.4 contract module is missing"
}
$apiSource = Get-Content "mission_orchestrator/api_service.py" -Raw
if ($apiSource -notmatch "task-completions" -or $apiSource -notmatch "task-completion-definition") {
    Fail "Stage-3.6.4 API routes are missing"
}
$migrationSource = Get-Content "migrations/039_stage3_6_4_dependency_aware_task_completion.sql" -Raw
if ($migrationSource -notmatch "mission_task_completion_commits") {
    Fail "Stage-3.6.4 durable store is missing from migration 039"
}
Pass "Stage-3.6.4 migration, contract module, durable store, and APIs are registered"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.4 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version            : $expectedControl"
Write-Host "repository migration       : $expectedMigrationLevel"
Write-Host "canonical test inventory   : $expectedTestCount"
Write-Host "Stage-3.6 chain tests       : $expectedStage6Count"
Write-Host "focused Stage-3.6.4 tests  : $expectedFocusedCount"
Write-Host "persistence store          : $expectedStore"
Write-Host "completion status          : $expectedStatus"
Write-Host "next stage                 : 3.6.5"
