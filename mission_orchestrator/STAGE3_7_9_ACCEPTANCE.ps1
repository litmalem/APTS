param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"
function Fail([string]$Message){ Write-Host "[FAIL] $Message" -ForegroundColor Red; Write-Host "`n=============================================================================="; Write-Host "STAGE 3.7.9 ACCEPTANCE: FAIL" -ForegroundColor Red; Write-Host "=============================================================================="; exit 1 }
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.9-adapt-replan-lineage-replay-recovery"
$expectedPrior="stage3.7.8-atomic-replan-commit-supersession-handoff"
$expectedMigrationLevel=53
$expectedTestCount=1344
$expectedFocusedCount=22
$expectedPredecessorFocusedCount=18
$expectedLineageSchema="apts-replan-event-lineage-v1"
$expectedReplaySchema="apts-replan-event-replay-v1"
$expectedRecoverySchema="apts-replan-recovery-checkpoint-v1"
$expectedPrefix="rplin-"
$expectedEvent="MISSION_REPLAN_RECOVERY_CHECKPOINTED"
$expectedStore="mission_replan_recovery_checkpoints"
$expectedStatus="ACTIVE"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.9 - Adapt/Replan Lineage, Replay & Recovery"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.9 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be 53" }
if([int]$health.replan_handoff_database_migration_level -ne 52){ Fail "Stage-3.7.8 migration metadata must remain 52" }
if([int]$health.replan_recovery_database_migration_level -ne 53){ Fail "Stage-3.7.9 migration metadata must be 53" }
if($health.replan_event_lineage_schema_version -ne $expectedLineageSchema){ Fail "unexpected replan lineage schema" }
if($health.replan_event_replay_schema_version -ne $expectedReplaySchema){ Fail "unexpected replan replay schema" }
if($health.replan_recovery_checkpoint_schema_version -ne $expectedRecoverySchema){ Fail "unexpected replan recovery checkpoint schema" }
if($health.replan_recovery_checkpoint_identity_prefix -ne $expectedPrefix){ Fail "recovery checkpoint identity prefix must be rplin-" }
if($health.replan_recovery_event_type -ne $expectedEvent){ Fail "unexpected recovery checkpoint event" }
if($health.replan_recovery_persistence_store -ne $expectedStore){ Fail "unexpected recovery checkpoint store" }
if($health.replan_lineage_status -ne $expectedStatus){ Fail "replan lineage status must be ACTIVE" }
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPrior -or $supported[-1] -ne $expectedControl){ Fail "supported-control tail must end with Stage 3.7.8 -> Stage 3.7.9" }
Pass "Stage 3.7.9 runtime, migration, predecessor lineage, schemas, identity, and store are active"

Write-Host "`n[1] Read-only replay / durable recovery authority proof"
foreach($field in @(
    "replan_recovery_binds_stage371_through_stage378_chain",
    "replan_recovery_requires_stage378_handoff_ready",
    "replan_recovery_requires_successor_active_plan_head",
    "replan_replay_read_only",
    "replan_recovery_reconstructs_from_durable_repository"
)){ Assert-TrueField $health $field }
foreach($field in @(
    "replan_replay_side_effects_performed",
    "replan_recovery_planner_rerun_performed",
    "replan_recovery_llm_reinterpretation_performed",
    "replan_recovery_governance_query_performed",
    "replan_recovery_runtime_query_performed",
    "replan_recovery_runtime_control_io_performed",
    "replan_recovery_external_network_io_performed",
    "replan_recovery_cancellation_io_performed",
    "replan_recovery_routing_performed",
    "replan_recovery_delegation_performed",
    "replan_recovery_dispatch_performed",
    "replan_recovery_execution_attempt_created",
    "replan_recovery_mission_state_transition_performed",
    "replan_recovery_historical_plan_mutation_performed",
    "replan_recovery_active_plan_head_cas_performed",
    "replan_recovery_target_action_dispatch_performed",
    "replan_recovery_target_actuation"
)){ Assert-FalseField $health $field }
Pass "Stage 3.7.9 replay is read-only and recovery reconstructs durable evidence without re-execution or control-plane side effects"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.9 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.9 regression failed" }
Pass "Full Stage 3.1-3.7.9 regression passed"

Write-Host "`n[5] Focused Stage 3.7.9 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.9 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.9 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.9 proof passed"

Write-Host "`n[6] Stage 3.7.8 predecessor non-regression proof"
$prior=(& python -m pytest -q tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py 2>&1 | Out-String)
Write-Host $prior.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.8 predecessor tests failed" }
if($prior -notmatch "(?m)^$expectedPredecessorFocusedCount passed"){ Fail "focused Stage-3.7.8 suite must report exactly $expectedPredecessorFocusedCount passed" }
Pass "Stage-3.7.8 predecessor proof passed"

Write-Host "`n[7] Source/migration/API boundary proof"
foreach($path in @(
    "mission_orchestrator/replan_lineage.py",
    "migrations/053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql",
    "tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py"
)){ if(-not(Test-Path $path)){ Fail "missing $path" } }
$migration=Get-Content "migrations/053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql" -Raw
if($migration -notmatch "mission_replan_recovery_checkpoints"){ Fail "migration 053 must create mission_replan_recovery_checkpoints" }
$source=Get-Content "mission_orchestrator/replan_lineage.py" -Raw
if($source -notmatch 'REPLAN_EVENT_LINEAGE_SCHEMA_VERSION = "apts-replan-event-lineage-v1"'){ Fail "lineage schema definition missing" }
if($source -notmatch 'REPLAN_EVENT_REPLAY_SCHEMA_VERSION = "apts-replan-event-replay-v1"'){ Fail "replay schema definition missing" }
if($source -notmatch 'REPLAN_RECOVERY_CHECKPOINT_SCHEMA_VERSION = "apts-replan-recovery-checkpoint-v1"'){ Fail "recovery schema definition missing" }
if($source -notmatch 'REPLAN_RECOVERY_CHECKPOINT_ID_PREFIX = "rplin-"'){ Fail "rplin identity definition missing" }
if($source -notmatch 'REPLAN_RECOVERY_EVENT_TYPE = "MISSION_REPLAN_RECOVERY_CHECKPOINTED"'){ Fail "recovery event definition missing" }
if($source -notmatch '"next_stage": "3.7.10"'){ Fail "Stage 3.7.10 boundary missing" }
$api=Get-Content "mission_orchestrator/api_service.py" -Raw
foreach($route in @("replan-lineage","replan-replay","replan-recovery","replan-recovery-checkpoints","replan-lineage-definition")){
    if($api -notmatch [regex]::Escape($route)){ Fail "API route token missing: $route" }
}
Pass "Stage-3.7.9 source, migration, API, and Stage-3.7.10 boundary proof passed"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.9 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
