param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.7.4 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.4-canonical-replan-snapshot-context-binding"
$expectedPrior373="stage3.7.3-replan-eligibility-governance-gate"
$expectedPrior372="stage3.7.2-adaptation-trigger-detection-classification"
$expectedPrior371="stage3.7.1-canonical-adaptation-replan-contract-identity"
$expectedStage3610="stage3.6.10-outcome-acceptance-regression-gate"
$expectedMigrationLevel=48
$expectedTestCount=1236
$expectedFocusedCount=20
$expectedStageSchema="apts-canonical-replan-snapshot-context-binding-v1"
$expectedContractSchema="apts-replan-snapshot-context-binding-contract-v1"
$expectedPrefix="rpsnap-"
$expectedStatus="SNAPSHOT_BOUND"
$expectedEvent="MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND"
$expectedContextMode="CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH"
$expectedAuthority="MISSION_ORCHESTRATOR_REPLAN_CONTEXT_BINDING"
$expectedStore="mission_replan_snapshots"
$expectedMode="IMMUTABLE_CANONICAL_REPLAN_SNAPSHOT_BOUND_TO_ELIGIBLE_EPISODE_CURRENT_PLAN_LOCAL_DURABLE_CONTEXT_NO_EXTERNAL_REFRESH_NO_REPLAN_COMMAND_NO_PLANNER_NO_ACTUATION"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.4 - Canonical Replan Snapshot & Context Binding"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.4 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if([int]$health.adaptation_replan_database_migration_level -ne 45){ Fail "Stage-3.7.1 migration metadata must remain 45" }
if([int]$health.adaptation_trigger_classification_database_migration_level -ne 46){ Fail "Stage-3.7.2 migration metadata must remain 46" }
if([int]$health.replan_eligibility_database_migration_level -ne 47){ Fail "Stage-3.7.3 migration metadata must remain 47" }
if([int]$health.replan_snapshot_database_migration_level -ne 48){ Fail "Stage-3.7.4 migration metadata must be 48" }
if($health.replan_snapshot_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.4 stage schema" }
if($health.replan_snapshot_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.4 contract schema" }
if($health.replan_snapshot_identity_prefix -ne $expectedPrefix){ Fail "Stage-3.7.4 identity prefix must be rpsnap-" }
if($health.replan_snapshot_status -ne $expectedStatus){ Fail "Stage-3.7.4 snapshot status must be SNAPSHOT_BOUND" }
if($health.replan_snapshot_event_type -ne $expectedEvent){ Fail "unexpected Stage-3.7.4 event type" }
if($health.replan_snapshot_context_mode -ne $expectedContextMode){ Fail "unexpected Stage-3.7.4 context mode" }
if($health.replan_snapshot_authority -ne $expectedAuthority){ Fail "unexpected Stage-3.7.4 authority" }
if($health.replan_snapshot_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.7.4 persistence store" }
if($health.replan_snapshot_mode -ne $expectedMode){ Fail "unexpected Stage-3.7.4 mode" }

$supported=@($health.supported_controls)
if($supported.Count -lt 5 -or $supported[-5] -ne $expectedStage3610 -or $supported[-4] -ne $expectedPrior371 -or $supported[-3] -ne $expectedPrior372 -or $supported[-2] -ne $expectedPrior373 -or $supported[-1] -ne $expectedControl){
    Fail "supported control tail must end with Stage 3.6.10 -> Stage 3.7.1 -> Stage 3.7.2 -> Stage 3.7.3 -> Stage 3.7.4"
}
Pass "Stage 3.7.4 runtime, migration, predecessor lineage, snapshot identity, and persistence identity are active"

Write-Host "`n[1] Canonical snapshot authority-boundary proof"
Assert-TrueField $health "replan_snapshot_requires_stage373_eligible_gate"
Assert-TrueField $health "replan_snapshot_local_durable_context_only"
foreach($field in @(
    "replan_snapshot_external_context_refresh_performed",
    "replan_snapshot_governance_query_performed",
    "replan_snapshot_lifecycle_replan_requested",
    "replan_snapshot_planner_invocation_performed",
    "replan_snapshot_replan_candidate_created",
    "replan_snapshot_successor_plan_created",
    "replan_snapshot_plan_delta_computed",
    "replan_snapshot_plan_validation_performed",
    "replan_snapshot_replan_decision_committed",
    "replan_snapshot_plan_supersession_performed",
    "replan_snapshot_mission_state_transition_performed",
    "replan_snapshot_dispatch_performed",
    "replan_snapshot_target_actuation"
)){ Assert-FalseField $health $field }
Pass "Stage 3.7.4 is local-durable-context-only and introduces no Governance refresh, lifecycle REPLAN, planner, successor Plan, commit, dispatch, or actuation authority"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.4 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.4 regression failed" }
Pass "Full Stage 3.1-3.7.4 regression passed"

Write-Host "`n[5] Focused Stage 3.7.4 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_4_canonical_replan_snapshot_context_binding.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.4 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.4 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.4 proof passed"

Write-Host "`n[6] Predecessor and historical current-head probes"
$probes=(& python -m pytest -q `
 tests/test_stage3_7_3_replan_eligibility_governance_gate.py `
 tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed `
 tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered 2>&1 | Out-String)
Write-Host $probes.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage-3.7.3 predecessor/current-head probe suite failed" }
if($probes -notmatch "(?m)^21 passed"){ Fail "predecessor/current-head probe suite must report exactly 21 passed" }
Pass "Stage-3.7.3 predecessor and historical current-head probes passed"

Write-Host "`n[7] Migration / source presence"
if(-not(Test-Path "migrations/048_stage3_7_4_canonical_replan_snapshot_context_binding.sql")){ Fail "Stage-3.7.4 migration 048 is missing" }
if(-not(Test-Path "mission_orchestrator/replan_snapshot.py")){ Fail "Stage-3.7.4 ReplanSnapshot module is missing" }
if(-not(Test-Path "tests/test_stage3_7_4_canonical_replan_snapshot_context_binding.py")){ Fail "Stage-3.7.4 focused proof is missing" }
$migration=Get-Content "migrations/048_stage3_7_4_canonical_replan_snapshot_context_binding.sql" -Raw
if($migration -notmatch "mission_replan_snapshots"){ Fail "migration 048 does not create mission_replan_snapshots" }
$source=Get-Content "mission_orchestrator/replan_snapshot.py" -Raw
if($source -notmatch 'REPLAN_SNAPSHOT_STATUS = "SNAPSHOT_BOUND"'){ Fail "canonical SNAPSHOT_BOUND definition missing" }
if($source -notmatch 'REPLAN_SNAPSHOT_EVENT_TYPE = "MISSION_REPLAN_SNAPSHOT_CONTEXT_BOUND"'){ Fail "canonical Stage-3.7.4 event definition missing" }
if($source -notmatch 'REPLAN_SNAPSHOT_CONTEXT_MODE = "CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH"'){ Fail "canonical local-durable context-mode definition missing" }
if($source -notmatch '"next_stage": "3.7.5"'){ Fail "Stage-3.7.4 definition must reserve Stage 3.7.5 as next stage" }
$adaptationSource=Get-Content "mission_orchestrator/adaptation_replan.py" -Raw
if($adaptationSource -notmatch 'REPLAN_SNAPSHOT_ID_PREFIX = "rpsnap-"'){ Fail "canonical rpsnap- identity definition missing" }
Pass "Migration 048, durable store, ReplanSnapshot module, identity, and focused proof are present"

Write-Host "`n[8] Repository-head metadata / server activation proof"
$repoModel=Get-Content "mission_orchestrator/repository_model.py" -Raw
if($repoModel -notmatch 'REPOSITORY_MIGRATION_LEVEL = 48'){ Fail "repository_model.py must declare migration level 48" }
$serviceSource=Get-Content "mission_orchestrator/service.py" -Raw
if($serviceSource -notmatch 'CONTROL_VERSION = "stage3.7.4-canonical-replan-snapshot-context-binding"'){ Fail "service.py Stage-3.7.4 control identity missing" }
$apiSource=Get-Content "mission_orchestrator/api_service.py" -Raw
if($apiSource -notmatch 'server_version = "APTSMissionOrchestrator/3.7.4"'){ Fail "HTTP server version must be 3.7.4" }
if($apiSource -match 'replan-commit'){ Fail "Stage-3.7.4 API must not expose replan-commit" }
if($apiSource -match 'replan-supersession'){ Fail "Stage-3.7.4 API must not expose replan-supersession" }
Pass "Repository head metadata and Stage-3.7.4 server identity are active"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.4 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version                  : $expectedControl"
Write-Host "repository migration             : $expectedMigrationLevel"
Write-Host "canonical regression inventory   : $expectedTestCount"
Write-Host "focused Stage 3.7.4              : $expectedFocusedCount passed"
Write-Host "replan snapshot store            : $expectedStore"
Write-Host "snapshot status                  : $expectedStatus"
Write-Host "context mode                     : $expectedContextMode"
Write-Host "external context refresh         : NOT PERFORMED"
Write-Host "Governance query                 : NOT PERFORMED"
Write-Host "lifecycle REPLAN                 : NOT REQUESTED"
Write-Host "planner invocation               : NOT PERFORMED"
Write-Host "candidate / successor Plan       : NOT CREATED"
Write-Host "Plan delta / validation          : NOT PERFORMED"
Write-Host "replan decision / commit         : NOT PERFORMED"
Write-Host "Plan supersession                : NOT PERFORMED"
Write-Host "Mission state transition         : NOT PERFORMED"
Write-Host "dispatch / execution             : NOT PERFORMED"
Write-Host "target actuation                 : NOT PERFORMED"
Write-Host "next stage                       : 3.7.5"
