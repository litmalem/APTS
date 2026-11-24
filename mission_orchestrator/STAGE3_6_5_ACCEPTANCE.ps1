param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.6.5 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object, [string]$Field, [string]$Context) {
    if ($Object.$Field -ne $false) { Fail "$Context boundary drifted: $Field must be false" }
}
function Assert-TrueField($Object, [string]$Field, [string]$Context) {
    if ($Object.$Field -ne $true) { Fail "$Context contract drifted: $Field must be true" }
}

$expectedControl = "stage3.6.5-mission-outcome-aggregation"
$expectedPredecessor = "stage3.6.4-dependency-aware-task-completion"
$expectedMigrationLevel = 40
$expectedTestCount = 1062
$expectedFocusedCount = 20
$expectedStage6Count = 99
$expectedStageSchema = "apts-mission-outcome-aggregation-v1"
$expectedContractSchema = "apts-mission-outcome-aggregation-contract-v1"
$expectedPrefix = "moutcome-"
$expectedStore = "mission_outcome_aggregations"
$expectedStatus = "MISSION_EXECUTION_OUTCOME_AGGREGATED"

Write-Host "=============================================================================="
Write-Host "Stage 3.6.5 - Mission Outcome Aggregation"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health = Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" }
catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }

Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if ($health.status -ne "ok") { Fail "health.status must be ok" }
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.6.5 runtime control is not active" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "repository migration level must be $expectedMigrationLevel" }
if ($health.mission_outcome_aggregation_stage_schema_version -ne $expectedStageSchema) { Fail "unexpected Stage-3.6.5 stage schema" }
if ($health.mission_outcome_aggregation_contract_schema_version -ne $expectedContractSchema) { Fail "unexpected Stage-3.6.5 contract schema" }
if ($health.mission_outcome_aggregation_identity_prefix -ne $expectedPrefix) { Fail "unexpected Stage-3.6.5 identity prefix" }
if ($health.mission_outcome_aggregation_persistence_store -ne $expectedStore) { Fail "unexpected Stage-3.6.5 persistence store" }
if ($health.mission_outcome_aggregation_status -ne $expectedStatus) { Fail "unexpected Stage-3.6.5 aggregation status" }
if ([int]$health.mission_outcome_aggregation_database_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.6.5 migration metadata must be $expectedMigrationLevel" }
$supported = @($health.supported_controls)
if ($supported.Count -lt 2 -or $supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl) {
    Fail "supported control tail must end with Stage 3.6.4 then Stage 3.6.5"
}
foreach ($field in @(
    "mission_outcome_aggregation_requires_active_plan_version",
    "mission_outcome_aggregation_consumes_task_outcomes",
    "mission_outcome_aggregation_consumes_task_completions",
    "mission_outcome_aggregation_observes_running_projections"
)) { Assert-TrueField $health $field "health" }
foreach ($field in @(
    "mission_outcome_aggregation_success_criteria_evaluation_performed",
    "mission_outcome_aggregation_mission_completion_readiness_decision_performed",
    "mission_outcome_aggregation_plan_progression_performed",
    "mission_outcome_aggregation_mission_success_completion_authority_exercised",
    "mission_outcome_aggregation_external_network_io_performed",
    "mission_outcome_aggregation_target_actuation",
    "mission_outcome_aggregation_mission_state_transition_performed"
)) { Assert-FalseField $health $field "health" }
Pass "Stage 3.6.5 runtime control and authority boundary are active"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { Write-Host $collect; Fail "pytest collection failed" }
if ($collect -notmatch "(?m)^$expectedTestCount tests collected") { Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.6.5 regression"
& python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "full Stage 3.1-3.6.5 regression failed" }
Pass "Full Stage 3.1-3.6.5 regression passed"

Write-Host "`n[4] Stage 3.6 chain regression"
$stage6 = (& python -m pytest -q `
    tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py `
    tests/test_stage3_6_2_task_terminality_completion_eligibility.py `
    tests/test_stage3_6_3_evidence_binding_verification.py `
    tests/test_stage3_6_4_dependency_aware_task_completion.py `
    tests/test_stage3_6_5_mission_outcome_aggregation.py 2>&1 | Out-String)
Write-Host $stage6.TrimEnd()
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.6 chain regression failed" }
if ($stage6 -notmatch "(?m)^$expectedStage6Count passed") { Fail "Stage-3.6 chain suite must report exactly $expectedStage6Count passed" }
Pass "Stage-3.6.1 through Stage-3.6.5 chain passed"

Write-Host "`n[5] Focused Stage 3.6.5 proof"
$focused = (& python -m pytest -q tests/test_stage3_6_5_mission_outcome_aggregation.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0) { Fail "focused Stage-3.6.5 tests failed" }
if ($focused -notmatch "(?m)^$expectedFocusedCount passed") { Fail "focused Stage-3.6.5 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.6.5 proof passed"

Write-Host "`n[6] Migration / source / API registration"
if (-not (Test-Path "migrations/040_stage3_6_5_mission_outcome_aggregation.sql")) { Fail "migration 040 is missing" }
if (-not (Test-Path "mission_orchestrator/mission_outcome_aggregation.py")) { Fail "Stage-3.6.5 contract module is missing" }
$apiSource = Get-Content "mission_orchestrator/api_service.py" -Raw
if ($apiSource -notmatch "mission-outcome-aggregations" -or $apiSource -notmatch "mission-outcome-aggregation-definition") { Fail "Stage-3.6.5 API routes are missing" }
$migrationSource = Get-Content "migrations/040_stage3_6_5_mission_outcome_aggregation.sql" -Raw
if ($migrationSource -notmatch "mission_outcome_aggregations") { Fail "Stage-3.6.5 durable store is missing from migration 040" }
$eventSource = Get-Content "mission_orchestrator/mission_events.py" -Raw
if ($eventSource -notmatch "MISSION_OUTCOME_AGGREGATED") { Fail "Stage-3.6.5 canonical event type is missing" }
Pass "Stage-3.6.5 migration, contract module, durable store, API, and event are registered"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.5 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version            : $expectedControl"
Write-Host "repository migration       : $expectedMigrationLevel"
Write-Host "canonical test inventory   : $expectedTestCount"
Write-Host "Stage-3.6 chain tests       : $expectedStage6Count"
Write-Host "focused Stage-3.6.5 tests  : $expectedFocusedCount"
Write-Host "persistence store          : $expectedStore"
Write-Host "aggregation status         : $expectedStatus"
Write-Host "next stage                 : 3.6.6"
