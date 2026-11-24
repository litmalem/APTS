param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.7.2 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }
function Assert-ExactArray($Actual,[string[]]$Expected,[string]$Label){
    $a=@($Actual)
    if($a.Count -ne $Expected.Count){ Fail "$Label cardinality mismatch: observed=$($a.Count) expected=$($Expected.Count)" }
    for($i=0; $i -lt $Expected.Count; $i++){
        if($a[$i] -ne $Expected[$i]){ Fail "$Label mismatch at index ${i}: observed=$($a[$i]) expected=$($Expected[$i])" }
    }
}

$expectedControl="stage3.7.2-adaptation-trigger-detection-classification"
$expectedPrior="stage3.7.1-canonical-adaptation-replan-contract-identity"
$expectedStage3610="stage3.6.10-outcome-acceptance-regression-gate"
$expectedMigrationLevel=46
$expectedTestCount=1197
$expectedFocusedCount=22
$expectedStageSchema="apts-adaptation-trigger-detection-classification-v1"
$expectedContractSchema="apts-adaptation-trigger-classification-contract-v1"
$expectedPrefix="rcls-"
$expectedMode="EVIDENCE_BOUND_DETERMINISTIC_ADAPTATION_TRIGGER_CLASSIFICATION_NO_ELIGIBILITY_NO_REPLAN_NO_PLANNER_NO_ACTUATION"
$expectedAuthority="MISSION_ORCHESTRATOR_ADAPTATION_TRIGGER_CLASSIFICATION"
$expectedStatus="CLASSIFIED"
$expectedEvent="MISSION_ADAPTATION_TRIGGER_CLASSIFIED"
$expectedStore="mission_adaptation_trigger_classifications"

$expectedReasons=@(
    "EXECUTION_FAILURE",
    "EXECUTION_TIMEOUT_EXHAUSTED",
    "TASK_OUTCOME_REJECTED",
    "DEPENDENCY_INVALIDATED",
    "RESOURCE_UNAVAILABLE",
    "AGENT_CAPABILITY_CHANGED",
    "ENVIRONMENT_STATE_CHANGED",
    "MISSION_CONSTRAINT_CHANGED",
    "BUDGET_PRESSURE",
    "DEADLINE_RISK",
    "POLICY_CHANGED",
    "EVIDENCE_CONTRADICTION",
    "PLAN_STALE"
)
$expectedSeverities=@("LOW","MEDIUM","HIGH","CRITICAL")
$expectedSourceStages=@(
    "STAGE3_3_PLANNING",
    "STAGE3_4_ROUTING_DELEGATION",
    "STAGE3_5_EXECUTION",
    "STAGE3_6_OUTCOME_COMPLETION",
    "MISSION_LIFECYCLE",
    "GOVERNANCE",
    "ENVIRONMENT",
    "OPERATOR",
    "OTHER"
)
$expectedScopes=@("LEVEL_3_PARTIAL_PLAN","LEVEL_4_MISSION")

Write-Host "=============================================================================="
Write-Host "Stage 3.7.2 - Adaptation Trigger Detection & Classification"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.2 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if([int]$health.adaptation_replan_database_migration_level -ne 45){ Fail "Stage-3.7.1 migration metadata must remain 45" }
if($health.adaptation_replan_persistence_store -ne "mission_adaptation_replan_contracts"){ Fail "Stage-3.7.1 persistence store changed unexpectedly" }
if($health.adaptation_replan_episode_initial_state -ne "DETECTED"){ Fail "Stage-3.7.1 immutable source episode state must remain DETECTED" }

if($health.adaptation_trigger_classification_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.2 stage schema" }
if($health.adaptation_trigger_classification_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.2 contract schema" }
if($health.adaptation_trigger_classification_identity_prefix -ne $expectedPrefix){ Fail "Stage-3.7.2 classification identity prefix must be rcls-" }
if($health.adaptation_trigger_classification_mode -ne $expectedMode){ Fail "unexpected Stage-3.7.2 mode" }
if($health.adaptation_trigger_classification_authority -ne $expectedAuthority){ Fail "unexpected Stage-3.7.2 authority" }
if($health.adaptation_trigger_classification_status -ne $expectedStatus){ Fail "classification status must be CLASSIFIED" }
if($health.adaptation_trigger_classification_event_type -ne $expectedEvent){ Fail "unexpected Stage-3.7.2 event type" }
if([int]$health.adaptation_trigger_classification_database_migration_level -ne 46){ Fail "Stage-3.7.2 migration metadata must be 46" }
if($health.adaptation_trigger_classification_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.7.2 persistence store" }
if($health.adaptation_trigger_effective_episode_state -ne "CLASSIFIED"){ Fail "effective Stage-3.7.2 episode projection must be CLASSIFIED" }

Assert-ExactArray $health.adaptation_trigger_reason_codes $expectedReasons "adaptation-trigger reason taxonomy"
Assert-ExactArray $health.adaptation_trigger_severities $expectedSeverities "adaptation-trigger severity taxonomy"
Assert-ExactArray $health.adaptation_trigger_source_stages $expectedSourceStages "adaptation-trigger source-stage taxonomy"
Assert-ExactArray $health.adaptation_trigger_replan_scope_levels $expectedScopes "adaptation-trigger replan-scope taxonomy"

$supported=@($health.supported_controls)
if($supported.Count -lt 3 -or $supported[-3] -ne $expectedStage3610 -or $supported[-2] -ne $expectedPrior -or $supported[-1] -ne $expectedControl){
    Fail "supported control tail must end with Stage 3.6.10 -> Stage 3.7.1 -> Stage 3.7.2"
}
Pass "Stage 3.7.2 classification control, migration, taxonomy, and Stage-3.7.1 compatibility are active"

Write-Host "`n[1] Evidence/concurrency guard proof"
foreach($field in @(
    "adaptation_trigger_requires_stage371_detected_episode",
    "adaptation_trigger_requires_stage371_contract_hash_binding",
    "adaptation_trigger_requires_detection_event_hash_binding",
    "adaptation_trigger_requires_current_mission_version_binding",
    "adaptation_trigger_requires_current_active_plan_head",
    "adaptation_trigger_evidence_backed_only"
)){ Assert-TrueField $health $field }
if($health.adaptation_replan_classification_performed -ne $false){ Fail "immutable Stage-3.7.1 source contract must still declare classification_performed=false" }
if($health.adaptation_trigger_historical_stage371_contract_mutated -ne $false){ Fail "Stage-3.7.1 persisted contract must not be mutated by Stage 3.7.2" }
Pass "Stage 3.7.2 is evidence-bound and concurrency-bound without mutating Stage 3.7.1"

Write-Host "`n[2] Authority-boundary proof"
foreach($field in @(
    "adaptation_trigger_unauthoritative_ai_thinks_replan_allowed",
    "adaptation_trigger_eligibility_evaluation_performed",
    "adaptation_trigger_lifecycle_replan_requested",
    "adaptation_trigger_planner_invocation_performed",
    "adaptation_trigger_replan_candidate_created",
    "adaptation_trigger_plan_delta_computed",
    "adaptation_trigger_plan_validation_performed",
    "adaptation_trigger_replan_decision_committed",
    "adaptation_trigger_plan_supersession_performed",
    "adaptation_trigger_historical_plan_mutation_performed",
    "adaptation_trigger_terminal_state_reopening_performed",
    "adaptation_trigger_mission_state_transition_performed",
    "adaptation_trigger_governance_query_performed",
    "adaptation_trigger_runtime_query_performed",
    "adaptation_trigger_runtime_control_io_performed",
    "adaptation_trigger_dispatch_performed",
    "adaptation_trigger_new_execution_attempt_created",
    "adaptation_trigger_external_network_io_performed",
    "adaptation_trigger_target_action_dispatch_performed",
    "adaptation_trigger_target_actuation"
)){ Assert-FalseField $health $field }
Pass "Stage 3.7.2 performs classification only; no eligibility, REPLAN, planner, supersession, dispatch, or actuation authority is introduced"

Write-Host "`n[3] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[4] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[5] Full Stage 3.1-3.7.2 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.2 regression failed" }
Pass "Full Stage 3.1-3.7.2 regression passed"

Write-Host "`n[6] Focused Stage 3.7.2 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_2_adaptation_trigger_detection_classification.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.2 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.2 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.2 proof passed"

Write-Host "`n[7] Historical current-head tail probes"
$tails=(& python -m pytest -q `
 tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed `
 tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered 2>&1 | Out-String)
Write-Host $tails.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "historical current-head tail probes failed" }
if($tails -notmatch "(?m)^2 passed"){ Fail "historical tail probe suite must report exactly 2 passed" }
Pass "Historical current-head tail probes passed"

Write-Host "`n[8] Migration / source presence"
if(-not(Test-Path "migrations/046_stage3_7_2_adaptation_trigger_detection_classification.sql")){ Fail "Stage-3.7.2 migration 046 is missing" }
if(-not(Test-Path "mission_orchestrator/adaptation_trigger.py")){ Fail "Stage-3.7.2 adaptation-trigger classification module is missing" }
if(-not(Test-Path "tests/test_stage3_7_2_adaptation_trigger_detection_classification.py")){ Fail "Stage-3.7.2 focused proof is missing" }
$migration=Get-Content "migrations/046_stage3_7_2_adaptation_trigger_detection_classification.sql" -Raw
if($migration -notmatch "mission_adaptation_trigger_classifications"){ Fail "migration 046 does not create the Stage-3.7.2 classification store" }
$source=Get-Content "mission_orchestrator/adaptation_trigger.py" -Raw
if($source -notmatch 'ADAPTATION_TRIGGER_CLASSIFICATION_ID_PREFIX = "rcls-"'){ Fail "canonical classification identity definition missing" }
if($source -notmatch 'ADAPTATION_TRIGGER_CLASSIFICATION_STATUS = "CLASSIFIED"'){ Fail "canonical CLASSIFIED state definition missing" }
if($source -notmatch 'REPLAN_SCOPE_LEVEL_3 = "LEVEL_3_PARTIAL_PLAN"'){ Fail "Level-3 partial-plan scope definition missing" }
if($source -notmatch 'REPLAN_SCOPE_LEVEL_4 = "LEVEL_4_MISSION"'){ Fail "Level-4 mission scope definition missing" }
Pass "Migration 046, durable store, classification module, and focused tests are present"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.2 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version                  : $expectedControl"
Write-Host "repository migration             : $expectedMigrationLevel"
Write-Host "canonical regression inventory   : $expectedTestCount"
Write-Host "focused Stage 3.7.2              : $expectedFocusedCount passed"
Write-Host "classification store             : $expectedStore"
Write-Host "classification status            : $expectedStatus"
Write-Host "Stage 3.7.1 persisted state      : DETECTED / IMMUTABLE"
Write-Host "eligibility evaluation           : NOT PERFORMED"
Write-Host "lifecycle REPLAN                 : NOT REQUESTED"
Write-Host "planner invocation               : NOT PERFORMED"
Write-Host "plan supersession                : NOT PERFORMED"
Write-Host "dispatch / execution             : NOT PERFORMED"
Write-Host "target actuation                 : NOT PERFORMED"

