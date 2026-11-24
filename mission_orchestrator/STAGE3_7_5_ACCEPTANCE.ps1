param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.7.5 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.5-deterministic-replan-candidate-generation"
$expectedPrior374="stage3.7.4-canonical-replan-snapshot-context-binding"
$expectedPrior373="stage3.7.3-replan-eligibility-governance-gate"
$expectedPrior372="stage3.7.2-adaptation-trigger-detection-classification"
$expectedPrior371="stage3.7.1-canonical-adaptation-replan-contract-identity"
$expectedStage3610="stage3.6.10-outcome-acceptance-regression-gate"
$expectedMigrationLevel=49
$expectedTestCount=1257
$expectedFocusedCount=21
$expectedProbeCount=22
$expectedStageSchema="apts-deterministic-replan-candidate-generation-v1"
$expectedContractSchema="apts-replan-candidate-generation-contract-v1"
$expectedCandidatePrefix="rpcand-"
$expectedInvocationPrefix="rpinv-"
$expectedStatus="CANDIDATE_GENERATED"
$expectedEvent="MISSION_REPLAN_CANDIDATE_GENERATED"
$expectedAuthority="MISSION_ORCHESTRATOR_DETERMINISTIC_REPLAN_CANDIDATE_GENERATION"
$expectedPlannerProfile="CANONICAL_REPLAN_REMAINDER_DAG_V1"
$expectedStore="mission_replan_candidates"
$expectedMode="DETERMINISTIC_LOCAL_PURE_FUNCTION_OVER_IMMUTABLE_REPLAN_SNAPSHOT_CANDIDATE_ONLY_NO_VALIDATION_NO_COMMIT_NO_SUPERSESSION_NO_ACTUATION"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.5 - Deterministic Replan Candidate Generation"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.5 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if([int]$health.adaptation_replan_database_migration_level -ne 45){ Fail "Stage-3.7.1 migration metadata must remain 45" }
if([int]$health.adaptation_trigger_classification_database_migration_level -ne 46){ Fail "Stage-3.7.2 migration metadata must remain 46" }
if([int]$health.replan_eligibility_database_migration_level -ne 47){ Fail "Stage-3.7.3 migration metadata must remain 47" }
if([int]$health.replan_snapshot_database_migration_level -ne 48){ Fail "Stage-3.7.4 migration metadata must remain 48" }
if([int]$health.replan_candidate_database_migration_level -ne 49){ Fail "Stage-3.7.5 migration metadata must be 49" }
if($health.replan_candidate_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.5 stage schema" }
if($health.replan_candidate_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.5 contract schema" }
if($health.replan_candidate_identity_prefix -ne $expectedCandidatePrefix){ Fail "Stage-3.7.5 candidate identity prefix must be rpcand-" }
if($health.replan_candidate_planner_invocation_identity_prefix -ne $expectedInvocationPrefix){ Fail "Stage-3.7.5 planner invocation prefix must be rpinv-" }
if($health.replan_candidate_status -ne $expectedStatus){ Fail "Stage-3.7.5 candidate status must be CANDIDATE_GENERATED" }
if($health.replan_candidate_event_type -ne $expectedEvent){ Fail "unexpected Stage-3.7.5 event type" }
if($health.replan_candidate_authority -ne $expectedAuthority){ Fail "unexpected Stage-3.7.5 authority" }
if($health.replan_candidate_planner_profile -ne $expectedPlannerProfile){ Fail "unexpected Stage-3.7.5 planner profile" }
if($health.replan_candidate_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.7.5 persistence store" }
if($health.replan_candidate_mode -ne $expectedMode){ Fail "unexpected Stage-3.7.5 mode" }

$supported=@($health.supported_controls)
if($supported.Count -lt 6 -or $supported[-6] -ne $expectedStage3610 -or $supported[-5] -ne $expectedPrior371 -or $supported[-4] -ne $expectedPrior372 -or $supported[-3] -ne $expectedPrior373 -or $supported[-2] -ne $expectedPrior374 -or $supported[-1] -ne $expectedControl){
    Fail "supported control tail must end with Stage 3.6.10 -> 3.7.1 -> 3.7.2 -> 3.7.3 -> 3.7.4 -> 3.7.5"
}
Pass "Stage 3.7.5 runtime, migration, predecessor lineage, candidate identity, and persistence identity are active"

Write-Host "`n[1] Deterministic candidate authority-boundary proof"
foreach($field in @(
    "replan_candidate_requires_stage374_snapshot",
    "replan_candidate_snapshot_is_sole_authoritative_planning_input",
    "replan_candidate_deterministic_local_planner",
    "replan_candidate_planner_invocation_performed",
    "replan_candidate_plan_delta_computed"
)){ Assert-TrueField $health $field }
foreach($field in @(
    "replan_candidate_successor_plan_created",
    "replan_candidate_plan_validation_performed",
    "replan_candidate_replan_decision_committed",
    "replan_candidate_plan_supersession_performed",
    "replan_candidate_mission_state_transition_performed",
    "replan_candidate_governance_query_performed",
    "replan_candidate_external_context_refresh_performed",
    "replan_candidate_dispatch_performed",
    "replan_candidate_target_actuation"
)){ Assert-FalseField $health $field }
Pass "Stage 3.7.5 invokes only the deterministic local candidate planner and introduces no successor-Plan activation, validation, commit, supersession, state transition, Governance refresh, dispatch, or actuation authority"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.5 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.5 regression failed" }
Pass "Full Stage 3.1-3.7.5 regression passed"

Write-Host "`n[5] Focused Stage 3.7.5 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_5_deterministic_replan_candidate_generation.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.5 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.5 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.5 proof passed"

Write-Host "`n[6] Predecessor and historical current-head probes"
$probes=(& python -m pytest -q `
 tests/test_stage3_7_4_canonical_replan_snapshot_context_binding.py `
 tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed `
 tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered 2>&1 | Out-String)
Write-Host $probes.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage-3.7.4 predecessor/current-head probe suite failed" }
if($probes -notmatch "(?m)^$expectedProbeCount passed"){ Fail "predecessor/current-head probe suite must report exactly $expectedProbeCount passed" }
Pass "Stage-3.7.4 predecessor and historical current-head probes passed"

Write-Host "`n[7] Migration / source presence"
if(-not(Test-Path "migrations/049_stage3_7_5_deterministic_replan_candidate_generation.sql")){ Fail "Stage-3.7.5 migration 049 is missing" }
if(-not(Test-Path "mission_orchestrator/replan_candidate.py")){ Fail "Stage-3.7.5 ReplanCandidate module is missing" }
if(-not(Test-Path "tests/test_stage3_7_5_deterministic_replan_candidate_generation.py")){ Fail "Stage-3.7.5 focused proof is missing" }
$migration=Get-Content "migrations/049_stage3_7_5_deterministic_replan_candidate_generation.sql" -Raw
if($migration -notmatch "mission_replan_candidates"){ Fail "migration 049 does not create mission_replan_candidates" }
$source=Get-Content "mission_orchestrator/replan_candidate.py" -Raw
if($source -notmatch 'REPLAN_CANDIDATE_STATUS = "CANDIDATE_GENERATED"'){ Fail "canonical CANDIDATE_GENERATED definition missing" }
if($source -notmatch 'REPLAN_CANDIDATE_EVENT_TYPE = "MISSION_REPLAN_CANDIDATE_GENERATED"'){ Fail "canonical Stage-3.7.5 event definition missing" }
if($source -notmatch 'REPLAN_PLANNER_PROFILE = "CANONICAL_REPLAN_REMAINDER_DAG_V1"'){ Fail "canonical deterministic planner profile missing" }
if($source -notmatch 'REPLAN_CANDIDATE_ID_PREFIX = "rpcand-"'){ Fail "canonical rpcand- identity definition missing" }
if($source -notmatch 'REPLAN_PLANNER_INVOCATION_ID_PREFIX = "rpinv-"'){ Fail "canonical rpinv- identity definition missing" }
if($source -notmatch '"next_stage": "3.7.6"'){ Fail "Stage-3.7.5 definition must reserve Stage 3.7.6 as next stage" }
Pass "Migration 049, durable candidate store, deterministic ReplanCandidate module, identities, and focused proof are present"

Write-Host "`n[8] Repository-head metadata / server activation proof"
$repoModel=Get-Content "mission_orchestrator/repository_model.py" -Raw
if($repoModel -notmatch 'REPOSITORY_MIGRATION_LEVEL = 49'){ Fail "repository_model.py must declare migration level 49" }
$serviceSource=Get-Content "mission_orchestrator/service.py" -Raw
if($serviceSource -notmatch 'CONTROL_VERSION = "stage3.7.5-deterministic-replan-candidate-generation"'){ Fail "service.py Stage-3.7.5 control identity missing" }
$apiSource=Get-Content "mission_orchestrator/api_service.py" -Raw
if($apiSource -notmatch 'server_version = "APTSMissionOrchestrator/3.7.5"'){ Fail "HTTP server version must be 3.7.5" }
if($apiSource -match 'replan-commit'){ Fail "Stage-3.7.5 API must not expose replan-commit" }
if($apiSource -match 'replan-supersession'){ Fail "Stage-3.7.5 API must not expose replan-supersession" }
Pass "Repository head metadata and Stage-3.7.5 server identity are active"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.5 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version                  : $expectedControl"
Write-Host "repository migration             : $expectedMigrationLevel"
Write-Host "canonical regression inventory   : $expectedTestCount"
Write-Host "focused Stage 3.7.5              : $expectedFocusedCount passed"
Write-Host "replan candidate store           : $expectedStore"
Write-Host "candidate status                 : $expectedStatus"
Write-Host "planner profile                  : $expectedPlannerProfile"
Write-Host "source input                     : immutable Stage-3.7.4 ReplanSnapshot"
Write-Host "planner invocation               : DETERMINISTIC LOCAL ONLY"
Write-Host "ReplanCandidate                  : CREATED"
Write-Host "Plan delta                       : COMPUTED AS CANDIDATE PROJECTION"
Write-Host "successor Plan                   : NOT CREATED / NOT ACTIVATED"
Write-Host "Plan validation                  : NOT PERFORMED"
Write-Host "replan decision / commit         : NOT PERFORMED"
Write-Host "Plan supersession                : NOT PERFORMED"
Write-Host "Mission state transition         : NOT PERFORMED"
Write-Host "Governance query                 : NOT PERFORMED"
Write-Host "external context refresh         : NOT PERFORMED"
Write-Host "dispatch / execution             : NOT PERFORMED"
Write-Host "target actuation                 : NOT PERFORMED"
Write-Host "next stage                       : 3.7.6"
