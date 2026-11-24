param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"
function Fail([string]$Message){ Write-Host "[FAIL] $Message" -ForegroundColor Red; Write-Host "`n=============================================================================="; Write-Host "STAGE 3.7.6 ACCEPTANCE: FAIL" -ForegroundColor Red; Write-Host "=============================================================================="; exit 1 }
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.6-replan-candidate-validation-delta-feasibility-gate"
$expectedPrior="stage3.7.5-deterministic-replan-candidate-generation"
$expectedMigrationLevel=50
$expectedTestCount=1282
$expectedFocusedCount=25
$expectedStageSchema="apts-replan-candidate-validation-delta-feasibility-gate-v1"
$expectedContractSchema="apts-replan-candidate-validation-decision-contract-v1"
$expectedPrefix="rpdec-"
$expectedEvent="MISSION_REPLAN_DECISION_RECORDED"
$expectedValidated="VALIDATED_FOR_COMMIT"
$expectedRejected="REJECTED_INFEASIBLE"
$expectedStore="mission_replan_decisions"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.6 - Replan Candidate Validation & Delta Feasibility Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.6 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be 50" }
if([int]$health.replan_candidate_database_migration_level -ne 49){ Fail "Stage-3.7.5 migration metadata must remain 49" }
if([int]$health.replan_validation_database_migration_level -ne 50){ Fail "Stage-3.7.6 migration metadata must be 50" }
if($health.replan_validation_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.6 stage schema" }
if($health.replan_validation_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.6 contract schema" }
if($health.replan_validation_identity_prefix -ne $expectedPrefix){ Fail "validation identity prefix must be rpdec-" }
if($health.replan_validation_event_type -ne $expectedEvent){ Fail "unexpected validation event" }
if($health.replan_validation_validated_status -ne $expectedValidated){ Fail "unexpected validated status" }
if($health.replan_validation_rejected_status -ne $expectedRejected){ Fail "unexpected rejected status" }
if($health.replan_validation_persistence_store -ne $expectedStore){ Fail "unexpected validation store" }
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPrior -or $supported[-1] -ne $expectedControl){ Fail "supported-control tail must end with Stage 3.7.5 -> Stage 3.7.6" }
Pass "Stage 3.7.6 runtime, migration, predecessor lineage, and persistence identity are active"

Write-Host "`n[1] Validation authority-boundary proof"
foreach($field in @("replan_validation_requires_stage375_candidate","replan_validation_deterministic_reproduction_required","replan_validation_active_plan_head_drift_rejected","replan_validation_mission_version_drift_rejected","replan_validation_plan_validation_performed","replan_validation_delta_feasibility_evaluated")){ Assert-TrueField $health $field }
foreach($field in @("replan_validation_successor_plan_created","replan_validation_replan_decision_committed","replan_validation_plan_supersession_performed","replan_validation_mission_state_transition_performed","replan_validation_dispatch_performed","replan_validation_target_actuation")){ Assert-FalseField $health $field }
Pass "Stage 3.7.6 is validation-only and has no commit/supersession/dispatch/actuation authority"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.6 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.6 regression failed" }
Pass "Full Stage 3.1-3.7.6 regression passed"

Write-Host "`n[5] Focused Stage 3.7.6 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.6 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.6 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.6 proof passed"

Write-Host "`n[6] Source/migration presence"
foreach($path in @("mission_orchestrator/replan_validation.py","migrations/050_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.sql","tests/test_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.py")){ if(-not(Test-Path $path)){ Fail "missing $path" } }
$migration=Get-Content "migrations/050_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.sql" -Raw
if($migration -notmatch "mission_replan_decisions"){ Fail "migration 050 must create mission_replan_decisions" }
$source=Get-Content "mission_orchestrator/replan_validation.py" -Raw
if($source -notmatch 'REPLAN_VALIDATION_STATUS_VALIDATED = "VALIDATED_FOR_COMMIT"'){ Fail "VALIDATED_FOR_COMMIT definition missing" }
if($source -notmatch 'REPLAN_VALIDATION_STATUS_REJECTED = "REJECTED_INFEASIBLE"'){ Fail "REJECTED_INFEASIBLE definition missing" }
if($source -notmatch '"next_stage": "3.7.7"'){ Fail "Stage 3.7.7 boundary missing" }
Pass "Stage-3.7.6 source and migration proof passed"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.6 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
