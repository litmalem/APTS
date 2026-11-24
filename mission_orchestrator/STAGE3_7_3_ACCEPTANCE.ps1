param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.7.3 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.3-replan-eligibility-governance-gate"
$expectedPrior372="stage3.7.2-adaptation-trigger-detection-classification"
$expectedPrior371="stage3.7.1-canonical-adaptation-replan-contract-identity"
$expectedStage3610="stage3.6.10-outcome-acceptance-regression-gate"
$expectedMigrationLevel=47
$expectedTestCount=1216
$expectedFocusedCount=19
$expectedStageSchema="apts-replan-eligibility-governance-gate-v1"
$expectedContractSchema="apts-replan-eligibility-governance-contract-v1"
$expectedPrefix="rpelig-"
$expectedMode="STATIC_REPLAN_ELIGIBILITY_PLUS_AUTHORITATIVE_GOVERNANCE_FAIL_CLOSED_NO_REPLAN_COMMAND_NO_PLANNER_NO_SUPERSESSION_NO_ACTUATION"
$expectedAuthority="MISSION_ORCHESTRATOR_WITH_EXTERNAL_APTS_GSS"
$expectedEvent="MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_EVALUATED"
$expectedStore="mission_replan_eligibility_governance_gates"
$expectedActionClass="INTERNAL_REASONING"
$expectedActionName="AUTHORIZE_REPLAN"
$expectedResourceType="MISSION"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.3 - Replan Eligibility & Governance Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.3 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if([int]$health.adaptation_replan_database_migration_level -ne 45){ Fail "Stage-3.7.1 migration metadata must remain 45" }
if([int]$health.adaptation_trigger_classification_database_migration_level -ne 46){ Fail "Stage-3.7.2 migration metadata must remain 46" }
if([int]$health.replan_eligibility_database_migration_level -ne 47){ Fail "Stage-3.7.3 migration metadata must be 47" }
if($health.replan_eligibility_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.3 stage schema" }
if($health.replan_eligibility_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.3 contract schema" }
if($health.replan_eligibility_identity_prefix -ne $expectedPrefix){ Fail "Stage-3.7.3 identity prefix must be rpelig-" }
if($health.replan_eligibility_mode -ne $expectedMode){ Fail "unexpected Stage-3.7.3 mode" }
if($health.replan_eligibility_authority -ne $expectedAuthority){ Fail "unexpected Stage-3.7.3 authority" }
if($health.replan_eligibility_event_type -ne $expectedEvent){ Fail "unexpected Stage-3.7.3 event type" }
if($health.replan_eligibility_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.7.3 persistence store" }
if($health.replan_eligibility_governance_action_class -ne $expectedActionClass){ Fail "Governance action_class must be INTERNAL_REASONING" }
if($health.replan_eligibility_governance_action_name -ne $expectedActionName){ Fail "Governance action_name must be AUTHORIZE_REPLAN" }
if($health.replan_eligibility_governance_resource_type -ne $expectedResourceType){ Fail "Governance resource_type must be MISSION" }

$supported=@($health.supported_controls)
if($supported.Count -lt 4 -or $supported[-4] -ne $expectedStage3610 -or $supported[-3] -ne $expectedPrior371 -or $supported[-2] -ne $expectedPrior372 -or $supported[-1] -ne $expectedControl){
    Fail "supported control tail must end with Stage 3.6.10 -> Stage 3.7.1 -> Stage 3.7.2 -> Stage 3.7.3"
}
Pass "Stage 3.7.3 runtime, migration, predecessor lineage, and Governance action identity are active"

Write-Host "`n[1] Fail-closed eligibility / Governance boundary proof"
Assert-TrueField $health "replan_eligibility_static_fail_closed_before_governance_query"
foreach($field in @(
    "replan_eligibility_lifecycle_replan_requested",
    "replan_eligibility_replan_snapshot_bound",
    "replan_eligibility_planner_invocation_performed",
    "replan_eligibility_replan_decision_committed",
    "replan_eligibility_plan_supersession_performed",
    "replan_eligibility_dispatch_performed",
    "replan_eligibility_target_actuation"
)){ Assert-FalseField $health $field }
Pass "Stage 3.7.3 eligibility is fail-closed and introduces no lifecycle REPLAN, planner, supersession, dispatch, or actuation authority"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.3 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.3 regression failed" }
Pass "Full Stage 3.1-3.7.3 regression passed"

Write-Host "`n[5] Focused Stage 3.7.3 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_3_replan_eligibility_governance_gate.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.3 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.3 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.3 proof passed"

Write-Host "`n[6] Historical current-head tail probes"
$tails=(& python -m pytest -q `
 tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed `
 tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered 2>&1 | Out-String)
Write-Host $tails.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "historical current-head tail probes failed" }
if($tails -notmatch "(?m)^2 passed"){ Fail "historical tail probe suite must report exactly 2 passed" }
Pass "Historical current-head tail probes passed"

Write-Host "`n[7] Migration / source presence"
if(-not(Test-Path "migrations/047_stage3_7_3_replan_eligibility_governance_gate.sql")){ Fail "Stage-3.7.3 migration 047 is missing" }
if(-not(Test-Path "mission_orchestrator/replan_eligibility.py")){ Fail "Stage-3.7.3 replan-eligibility module is missing" }
if(-not(Test-Path "tests/test_stage3_7_3_replan_eligibility_governance_gate.py")){ Fail "Stage-3.7.3 focused proof is missing" }
$migration=Get-Content "migrations/047_stage3_7_3_replan_eligibility_governance_gate.sql" -Raw
if($migration -notmatch "mission_replan_eligibility_governance_gates"){ Fail "migration 047 does not create the Stage-3.7.3 durable store" }
$source=Get-Content "mission_orchestrator/replan_eligibility.py" -Raw
if($source -notmatch 'REPLAN_ELIGIBILITY_ID_PREFIX = "rpelig-"'){ Fail "canonical Stage-3.7.3 identity definition missing" }
if($source -notmatch 'REPLAN_GOVERNANCE_ACTION_NAME = "AUTHORIZE_REPLAN"'){ Fail "authoritative Governance action definition missing" }
if($source -notmatch 'REPLAN_ELIGIBLE_STATUS = "ELIGIBLE"'){ Fail "ELIGIBLE status definition missing" }
if($source -notmatch 'REPLAN_NOT_ELIGIBLE_STATUS = "NOT_ELIGIBLE"'){ Fail "NOT_ELIGIBLE status definition missing" }
if($source -notmatch 'REPLAN_REVIEW_REQUIRED_STATUS = "REVIEW_REQUIRED"'){ Fail "REVIEW_REQUIRED status definition missing" }
Pass "Migration 047, durable store, Stage-3.7.3 module, and focused tests are present"

Write-Host "`n[8] Regression metadata / current-head rebase proof"
$repoModel=Get-Content "mission_orchestrator/repository_model.py" -Raw
if($repoModel -notmatch 'REPOSITORY_MIGRATION_LEVEL = 47'){ Fail "repository_model.py must declare migration level 47" }
$serviceSource=Get-Content "mission_orchestrator/service.py" -Raw
if($serviceSource -notmatch 'CONTROL_VERSION = "stage3.7.3-replan-eligibility-governance-gate"'){ Fail "service.py Stage-3.7.3 control identity missing" }
$apiSource=Get-Content "mission_orchestrator/api_service.py" -Raw
if($apiSource -notmatch 'server_version = "APTSMissionOrchestrator/3.7.3"'){ Fail "HTTP server version must be 3.7.3" }
Pass "Repository head metadata is rebased to Stage 3.7.3"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.3 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version                  : $expectedControl"
Write-Host "repository migration             : $expectedMigrationLevel"
Write-Host "canonical regression inventory   : $expectedTestCount"
Write-Host "focused Stage 3.7.3              : $expectedFocusedCount passed"
Write-Host "eligibility/governance store     : $expectedStore"
Write-Host "Governance action                : $expectedActionName"
Write-Host "static fail-closed gate          : ACTIVE"
Write-Host "lifecycle REPLAN                 : NOT REQUESTED"
Write-Host "ReplanSnapshot                   : NOT BOUND"
Write-Host "planner invocation               : NOT PERFORMED"
Write-Host "replan decision/commit           : NOT PERFORMED"
Write-Host "plan supersession                : NOT PERFORMED"
Write-Host "dispatch / execution             : NOT PERFORMED"
Write-Host "target actuation                 : NOT PERFORMED"
