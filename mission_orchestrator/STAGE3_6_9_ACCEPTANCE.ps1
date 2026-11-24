param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"
function Fail([string]$Message){ Write-Host "[FAIL] $Message" -ForegroundColor Red; Write-Host "`n=============================================================================="; Write-Host "STAGE 3.6.9 ACCEPTANCE: FAIL" -ForegroundColor Red; Write-Host "=============================================================================="; exit 1 }
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $false){ Fail "$Context boundary drifted: $Field must be false" } }
function Assert-TrueField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $true){ Fail "$Context contract drifted: $Field must be true" } }

$expectedControl="stage3.6.9-outcome-lineage-replay-recovery"
$expectedPredecessor="stage3.6.8-verified-completion-declaration-lifecycle-handoff"
$expectedMigrationLevel=44
$expectedTestCount=1144
$expectedFocusedCount=22
$expectedStage6Count=181
$expectedLineageSchema="apts-outcome-event-lineage-v1"
$expectedReplaySchema="apts-outcome-event-replay-v1"
$expectedRecoverySchema="apts-outcome-recovery-checkpoint-v1"
$expectedPrefix="orecover-"
$expectedStore="mission_outcome_recovery_checkpoints"
$expectedEvent="MISSION_OUTCOME_RECOVERY_CHECKPOINTED"

Write-Host "=============================================================================="
Write-Host "Stage 3.6.9 - Outcome Lineage, Replay & Recovery"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.6.9 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if($health.outcome_event_lineage_schema_version -ne $expectedLineageSchema){ Fail "unexpected Stage-3.6.9 outcome lineage schema" }
if($health.outcome_event_replay_schema_version -ne $expectedReplaySchema){ Fail "unexpected Stage-3.6.9 outcome replay schema" }
if($health.outcome_recovery_checkpoint_schema_version -ne $expectedRecoverySchema){ Fail "unexpected Stage-3.6.9 recovery checkpoint schema" }
if($health.outcome_recovery_checkpoint_identity_prefix -ne $expectedPrefix){ Fail "unexpected Stage-3.6.9 recovery checkpoint identity prefix" }
if($health.outcome_recovery_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.6.9 persistence store" }
if($health.outcome_recovery_event_type -ne $expectedEvent){ Fail "unexpected Stage-3.6.9 recovery event type" }
if([int]$health.outcome_recovery_database_migration_level -ne $expectedMigrationLevel){ Fail "Stage-3.6.9 migration metadata must be $expectedMigrationLevel" }
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl){ Fail "supported control tail must end with Stage 3.6.8 then Stage 3.6.9" }
$allowed=@($health.outcome_recovery_allowed_states)
if($allowed.Count -ne 1 -or $allowed[0] -ne "COMPLETED"){ Fail "Stage-3.6.9 recovery must be restricted to COMPLETED Mission state" }
Assert-TrueField $health "outcome_recovery_binds_stage361_through_stage368_evidence_chain" "health"
Assert-TrueField $health "outcome_recovery_requires_stage368_verified_completion_declaration" "health"
Assert-TrueField $health "outcome_recovery_requires_completed_mission_state" "health"
Assert-TrueField $health "outcome_replay_read_only" "health"
Assert-TrueField $health "outcome_recovery_reconstructs_from_durable_repository" "health"
foreach($field in @(
    "outcome_replay_side_effects_performed",
    "outcome_recovery_llm_reinterpretation_performed",
    "outcome_recovery_runtime_query_performed",
    "outcome_recovery_runtime_control_io_performed",
    "outcome_recovery_governance_query_performed",
    "outcome_recovery_external_network_io_performed",
    "outcome_recovery_dispatch_redelivery_performed",
    "outcome_recovery_new_execution_attempt_created",
    "outcome_recovery_new_target_action_dispatch_performed",
    "outcome_recovery_mission_state_transition_performed",
    "outcome_recovery_mission_success_completion_authority_exercised",
    "outcome_recovery_target_actuation",
    "outcome_replay_is_execution",
    "outcome_recovery_is_execution",
    "outcome_recovery_is_dispatch",
    "outcome_recovery_is_runtime_resumption",
    "outcome_recovery_is_governance_authorization",
    "outcome_recovery_is_lifecycle_transition"
)){ Assert-FalseField $health $field "health" }
Pass "Stage 3.6.9 runtime control, lineage/replay/recovery schemas, durable store, and non-actuating authority boundary are active"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.6.9 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.6.9 regression failed" }
Pass "Full Stage 3.1-3.6.9 regression passed"

Write-Host "`n[4] Stage 3.6 chain regression"
$stage6=(& python -m pytest -q `
 tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py `
 tests/test_stage3_6_2_task_terminality_completion_eligibility.py `
 tests/test_stage3_6_3_evidence_binding_verification.py `
 tests/test_stage3_6_4_dependency_aware_task_completion.py `
 tests/test_stage3_6_5_mission_outcome_aggregation.py `
 tests/test_stage3_6_6_mission_success_criteria_evaluation.py `
 tests/test_stage3_6_7_completion_readiness_blockers.py `
 tests/test_stage3_6_8_verified_completion_declaration_lifecycle_handoff.py `
 tests/test_stage3_6_9_outcome_lineage_replay_recovery.py 2>&1 | Out-String)
Write-Host $stage6.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage-3.6 chain regression failed" }
if($stage6 -notmatch "(?m)^$expectedStage6Count passed"){ Fail "Stage-3.6 chain suite must report exactly $expectedStage6Count passed" }
Pass "Stage-3.6.1 through Stage-3.6.9 chain passed"

Write-Host "`n[5] Focused Stage 3.6.9 proof"
$focused=(& python -m pytest -q tests/test_stage3_6_9_outcome_lineage_replay_recovery.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.6.9 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.6.9 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.6.9 proof passed"

Write-Host "`n[6] Migration / source / API / event registration"
if(-not(Test-Path "migrations/044_stage3_6_9_outcome_lineage_replay_recovery.sql")){ Fail "migration 044 is missing" }
if(-not(Test-Path "mission_orchestrator/outcome_lineage.py")){ Fail "Stage-3.6.9 outcome lineage module is missing" }
$apiSource=Get-Content "mission_orchestrator/api_service.py" -Raw
foreach($route in @("outcome-lineage","outcome-replay","outcome-recovery","outcome-recovery-checkpoints","outcome-lineage-definition")){
    if($apiSource -notmatch [regex]::Escape($route)){ Fail "Stage-3.6.9 API route missing: $route" }
}
$migrationSource=Get-Content "migrations/044_stage3_6_9_outcome_lineage_replay_recovery.sql" -Raw
if($migrationSource -notmatch "mission_outcome_recovery_checkpoints"){ Fail "Stage-3.6.9 durable store is missing from migration 044" }
$eventSource=Get-Content "mission_orchestrator/mission_events.py" -Raw
if($eventSource -notmatch "MISSION_OUTCOME_RECOVERY_CHECKPOINTED"){ Fail "Stage-3.6.9 canonical recovery event type is missing" }
Pass "Stage-3.6.9 migration, contract module, durable store, API, and event are registered"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.9 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version            : $expectedControl"
Write-Host "repository migration       : $expectedMigrationLevel"
Write-Host "canonical test inventory   : $expectedTestCount"
Write-Host "Stage-3.6 chain tests       : $expectedStage6Count"
Write-Host "focused Stage-3.6.9 tests  : $expectedFocusedCount"
Write-Host "persistence store          : $expectedStore"
Write-Host "recovery event             : $expectedEvent"
Write-Host "recovery allowed state     : COMPLETED"
Write-Host "next stage                 : 3.6.10"
