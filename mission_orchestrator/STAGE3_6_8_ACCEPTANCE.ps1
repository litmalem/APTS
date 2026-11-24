param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"
function Fail([string]$Message){ Write-Host "[FAIL] $Message" -ForegroundColor Red; Write-Host "`n=============================================================================="; Write-Host "STAGE 3.6.8 ACCEPTANCE: FAIL" -ForegroundColor Red; Write-Host "=============================================================================="; exit 1 }
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $false){ Fail "$Context boundary drifted: $Field must be false" } }
function Assert-TrueField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $true){ Fail "$Context contract drifted: $Field must be true" } }

$expectedControl="stage3.6.8-verified-completion-declaration-lifecycle-handoff"
$expectedPredecessor="stage3.6.7-completion-readiness-blockers"
$expectedMigrationLevel=43
$expectedTestCount=1122
$expectedFocusedCount=20
$expectedStage6Count=159
$expectedStageSchema="apts-mission-verified-completion-declaration-lifecycle-handoff-v1"
$expectedContractSchema="apts-mission-verified-completion-declaration-lifecycle-handoff-contract-v1"
$expectedPrefix="mdecl-"
$expectedStore="mission_verified_completion_declarations"
$expectedStatus="MISSION_VERIFIED_COMPLETION_DECLARED"

Write-Host "=============================================================================="
Write-Host "Stage 3.6.8 - Verified Completion Declaration & Lifecycle Handoff"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.6.8 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if($health.verified_completion_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.6.8 stage schema" }
if($health.verified_completion_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.6.8 contract schema" }
if($health.verified_completion_identity_prefix -ne $expectedPrefix){ Fail "unexpected Stage-3.6.8 identity prefix" }
if($health.verified_completion_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.6.8 persistence store" }
if($health.verified_completion_status -ne $expectedStatus){ Fail "unexpected Stage-3.6.8 declaration status" }
if([int]$health.verified_completion_database_migration_level -ne $expectedMigrationLevel){ Fail "Stage-3.6.8 migration metadata must be $expectedMigrationLevel" }
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl){ Fail "supported control tail must end with Stage 3.6.7 then Stage 3.6.8" }
Assert-TrueField $health "verified_completion_consumes_stage367_readiness" "health"
Assert-TrueField $health "verified_completion_revalidates_stage366_evaluation" "health"
Assert-TrueField $health "verified_completion_declaration_performed" "health"
Assert-TrueField $health "verified_completion_persists_before_lifecycle_handoff" "health"
Assert-TrueField $health "verified_completion_uses_canonical_stage32_lifecycle_command_path" "health"
Assert-TrueField $health "verified_completion_restart_safe_partial_handoff_resume" "health"
Assert-TrueField $health "verified_completion_mission_success_completion_authority_exercised" "health"
foreach($field in @("verified_completion_direct_state_transition_bypass_used","verified_completion_governance_query_performed","verified_completion_runtime_query_performed","verified_completion_runtime_control_io_performed","verified_completion_dispatch_performed","verified_completion_external_network_io_performed","verified_completion_target_actuation")){ Assert-FalseField $health $field "health" }
if(@($health.verified_completion_lifecycle_handoff_commands) -join "," -ne "BEGIN_CLEANUP,COMPLETE"){ Fail "Stage-3.6.8 lifecycle handoff commands must be BEGIN_CLEANUP then COMPLETE" }
if($health.verified_completion_final_state -ne "COMPLETED"){ Fail "Stage-3.6.8 final state must be COMPLETED" }
Pass "Stage 3.6.8 runtime control, durable declaration, and lifecycle handoff boundary are active"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.6.8 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.6.8 regression failed" }
Pass "Full Stage 3.1-3.6.8 regression passed"

Write-Host "`n[4] Stage 3.6 chain regression"
$stage6=(& python -m pytest -q `
 tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py `
 tests/test_stage3_6_2_task_terminality_completion_eligibility.py `
 tests/test_stage3_6_3_evidence_binding_verification.py `
 tests/test_stage3_6_4_dependency_aware_task_completion.py `
 tests/test_stage3_6_5_mission_outcome_aggregation.py `
 tests/test_stage3_6_6_mission_success_criteria_evaluation.py `
 tests/test_stage3_6_7_completion_readiness_blockers.py `
 tests/test_stage3_6_8_verified_completion_declaration_lifecycle_handoff.py 2>&1 | Out-String)
Write-Host $stage6.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage-3.6 chain regression failed" }
if($stage6 -notmatch "(?m)^$expectedStage6Count passed"){ Fail "Stage-3.6 chain suite must report exactly $expectedStage6Count passed" }
Pass "Stage-3.6.1 through Stage-3.6.8 chain passed"

Write-Host "`n[5] Focused Stage 3.6.8 proof"
$focused=(& python -m pytest -q tests/test_stage3_6_8_verified_completion_declaration_lifecycle_handoff.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.6.8 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.6.8 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.6.8 proof passed"

Write-Host "`n[6] Migration / source / API / event registration"
if(-not(Test-Path "migrations/043_stage3_6_8_verified_completion_declaration_lifecycle_handoff.sql")){ Fail "migration 043 is missing" }
if(-not(Test-Path "mission_orchestrator/verified_completion.py")){ Fail "Stage-3.6.8 contract module is missing" }
$apiSource=Get-Content "mission_orchestrator/api_service.py" -Raw
if($apiSource -notmatch "verified-completion-declarations" -or $apiSource -notmatch "verified-completion-definition"){ Fail "Stage-3.6.8 API routes are missing" }
$migrationSource=Get-Content "migrations/043_stage3_6_8_verified_completion_declaration_lifecycle_handoff.sql" -Raw
if($migrationSource -notmatch "mission_verified_completion_declarations"){ Fail "Stage-3.6.8 durable store is missing from migration 043" }
$eventSource=Get-Content "mission_orchestrator/mission_events.py" -Raw
if($eventSource -notmatch "MISSION_VERIFIED_COMPLETION_DECLARED" -or $eventSource -notmatch "MISSION_COMPLETION_LIFECYCLE_HANDOFF_COMPLETED"){ Fail "Stage-3.6.8 canonical event types are missing" }
Pass "Stage-3.6.8 migration, contract module, durable store, API, and events are registered"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.8 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version            : $expectedControl"
Write-Host "repository migration       : $expectedMigrationLevel"
Write-Host "canonical test inventory   : $expectedTestCount"
Write-Host "Stage-3.6 chain tests       : $expectedStage6Count"
Write-Host "focused Stage-3.6.8 tests  : $expectedFocusedCount"
Write-Host "persistence store          : $expectedStore"
Write-Host "declaration status         : $expectedStatus"
Write-Host "lifecycle handoff          : BEGIN_CLEANUP -> COMPLETE"
Write-Host "final Mission state        : COMPLETED"
Write-Host "next stage                 : 3.6.9"
