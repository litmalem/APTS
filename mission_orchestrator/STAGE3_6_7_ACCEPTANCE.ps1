param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"
function Fail([string]$Message){ Write-Host "[FAIL] $Message" -ForegroundColor Red; Write-Host "`n=============================================================================="; Write-Host "STAGE 3.6.7 ACCEPTANCE: FAIL" -ForegroundColor Red; Write-Host "=============================================================================="; exit 1 }
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $false){ Fail "$Context boundary drifted: $Field must be false" } }
function Assert-TrueField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $true){ Fail "$Context contract drifted: $Field must be true" } }

$expectedControl="stage3.6.7-completion-readiness-blockers"
$expectedPredecessor="stage3.6.6-mission-success-criteria-evaluation"
$expectedMigrationLevel=42
$expectedTestCount=1102
$expectedFocusedCount=20
$expectedStage6Count=139
$expectedStageSchema="apts-mission-completion-readiness-blockers-v1"
$expectedContractSchema="apts-mission-completion-readiness-blockers-contract-v1"
$expectedPrefix="mready-"
$expectedStore="mission_completion_readiness_decisions"
$expectedStatus="MISSION_COMPLETION_READINESS_EVALUATED"

Write-Host "=============================================================================="
Write-Host "Stage 3.6.7 - Completion Readiness & Blockers"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.6.7 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if($health.completion_readiness_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.6.7 stage schema" }
if($health.completion_readiness_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.6.7 contract schema" }
if($health.completion_readiness_identity_prefix -ne $expectedPrefix){ Fail "unexpected Stage-3.6.7 identity prefix" }
if($health.completion_readiness_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.6.7 persistence store" }
if($health.completion_readiness_status -ne $expectedStatus){ Fail "unexpected Stage-3.6.7 readiness status" }
if([int]$health.completion_readiness_database_migration_level -ne $expectedMigrationLevel){ Fail "Stage-3.6.7 migration metadata must be $expectedMigrationLevel" }
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl){ Fail "supported control tail must end with Stage 3.6.6 then Stage 3.6.7" }
Assert-TrueField $health "completion_readiness_consumes_stage366_evaluation" "health"
Assert-TrueField $health "completion_readiness_decision_performed" "health"
foreach($field in @("completion_readiness_mission_success_completion_authority_exercised","completion_readiness_mission_state_transition_performed")){ Assert-FalseField $health $field "health" }
Pass "Stage 3.6.7 runtime control and authority boundary are active"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.6.7 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.6.7 regression failed" }
Pass "Full Stage 3.1-3.6.7 regression passed"

Write-Host "`n[4] Stage 3.6 chain regression"
$stage6=(& python -m pytest -q `
 tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py `
 tests/test_stage3_6_2_task_terminality_completion_eligibility.py `
 tests/test_stage3_6_3_evidence_binding_verification.py `
 tests/test_stage3_6_4_dependency_aware_task_completion.py `
 tests/test_stage3_6_5_mission_outcome_aggregation.py `
 tests/test_stage3_6_6_mission_success_criteria_evaluation.py `
 tests/test_stage3_6_7_completion_readiness_blockers.py 2>&1 | Out-String)
Write-Host $stage6.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage-3.6 chain regression failed" }
if($stage6 -notmatch "(?m)^$expectedStage6Count passed"){ Fail "Stage-3.6 chain suite must report exactly $expectedStage6Count passed" }
Pass "Stage-3.6.1 through Stage-3.6.7 chain passed"

Write-Host "`n[5] Focused Stage 3.6.7 proof"
$focused=(& python -m pytest -q tests/test_stage3_6_7_completion_readiness_blockers.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.6.7 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.6.7 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.6.7 proof passed"

Write-Host "`n[6] Migration / source / API registration"
if(-not(Test-Path "migrations/042_stage3_6_7_completion_readiness_blockers.sql")){ Fail "migration 042 is missing" }
if(-not(Test-Path "mission_orchestrator/completion_readiness.py")){ Fail "Stage-3.6.7 contract module is missing" }
$apiSource=Get-Content "mission_orchestrator/api_service.py" -Raw
if($apiSource -notmatch "completion-readiness-decisions" -or $apiSource -notmatch "completion-readiness-definition"){ Fail "Stage-3.6.7 API routes are missing" }
$migrationSource=Get-Content "migrations/042_stage3_6_7_completion_readiness_blockers.sql" -Raw
if($migrationSource -notmatch "mission_completion_readiness_decisions"){ Fail "Stage-3.6.7 durable store is missing from migration 042" }
$eventSource=Get-Content "mission_orchestrator/mission_events.py" -Raw
if($eventSource -notmatch "MISSION_COMPLETION_READINESS_EVALUATED"){ Fail "Stage-3.6.7 canonical event type is missing" }
Pass "Stage-3.6.7 migration, contract module, durable store, API, and event are registered"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.7 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version            : $expectedControl"
Write-Host "repository migration       : $expectedMigrationLevel"
Write-Host "canonical test inventory   : $expectedTestCount"
Write-Host "Stage-3.6 chain tests       : $expectedStage6Count"
Write-Host "focused Stage-3.6.7 tests  : $expectedFocusedCount"
Write-Host "persistence store          : $expectedStore"
Write-Host "readiness status           : $expectedStatus"
Write-Host "next stage                 : 3.6.8"
