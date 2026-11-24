param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.7.1 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.1-canonical-adaptation-replan-contract-identity"
$expectedPredecessor="stage3.6.10-outcome-acceptance-regression-gate"
$expectedMigrationLevel=45
$expectedTestCount=1175
$expectedFocusedCount=19
$expectedStageSchema="apts-adaptation-replan-contract-identity-v1"
$expectedContractSchema="apts-canonical-adaptation-replan-contract-v1"
$expectedMode="IMMUTABLE_ADAPTATION_EPISODE_AND_REPLAN_TRIGGER_IDENTITY_BOUND_TO_CURRENT_NONTERMINAL_MISSION_AND_ACTIVE_PLAN_PENDING_CLASSIFICATION"
$expectedAuthority="MISSION_ORCHESTRATOR_ADAPTATION_REPLAN_MATERIALIZATION"
$expectedStore="mission_adaptation_replan_contracts"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.1 - Canonical Adaptation / Replan Contract & Identity"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.1 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be $expectedMigrationLevel" }
if($health.adaptation_replan_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.1 stage schema" }
if($health.adaptation_replan_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.1 contract schema" }
if($health.adaptation_replan_mode -ne $expectedMode){ Fail "unexpected Stage-3.7.1 mode" }
if($health.adaptation_replan_authority -ne $expectedAuthority){ Fail "unexpected Stage-3.7.1 authority" }
if($health.adaptation_episode_identity_prefix -ne "adpt-"){ Fail "AdaptationEpisode prefix must be adpt-" }
if($health.replan_trigger_identity_prefix -ne "rpln-"){ Fail "ReplanTrigger prefix must be rpln-" }
if($health.replan_snapshot_reserved_identity_prefix -ne "rpsnap-"){ Fail "ReplanSnapshot reserved prefix mismatch" }
if($health.replan_candidate_reserved_identity_prefix -ne "rpcand-"){ Fail "ReplanCandidate reserved prefix mismatch" }
if($health.replan_decision_reserved_identity_prefix -ne "rpdec-"){ Fail "ReplanDecision reserved prefix mismatch" }
if($health.replan_commit_reserved_identity_prefix -ne "rpcom-"){ Fail "ReplanCommit reserved prefix mismatch" }
if($health.adaptation_replan_episode_initial_state -ne "DETECTED"){ Fail "initial adaptation episode state must be DETECTED" }
if($health.adaptation_replan_persistence_store -ne $expectedStore){ Fail "unexpected Stage-3.7.1 persistence store" }
if([int]$health.adaptation_replan_database_migration_level -ne 45){ Fail "Stage-3.7.1 migration metadata must be 45" }

$supported=@($health.supported_controls)
if($supported.Count -lt 3 -or $supported[-3] -ne "stage3.6.9-outcome-lineage-replay-recovery" -or $supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl){
    Fail "supported control tail must end with Stage 3.6.9 -> Stage 3.6.10 -> Stage 3.7.1"
}

$allowed=@($health.adaptation_replan_allowed_mission_states)
$expectedAllowed=@("RUNNING","WAITING_APPROVAL","WAITING_EVIDENCE")
if($allowed.Count -ne $expectedAllowed.Count){ Fail "allowed Mission-state cardinality mismatch" }
for($i=0; $i -lt $expectedAllowed.Count; $i++){ if($allowed[$i] -ne $expectedAllowed[$i]){ Fail "allowed Mission-state ordering/value mismatch at index $i" } }

$states=@($health.adaptation_replan_episode_state_model)
$expectedStates=@("DETECTED","CLASSIFIED","ELIGIBILITY_PENDING","ELIGIBLE","SNAPSHOT_BOUND","REPLAN_REQUESTED","CANDIDATE_READY","VALIDATED","COMMITTED","HANDOFF_READY")
if($states.Count -ne $expectedStates.Count){ Fail "episode-state model cardinality mismatch" }
for($i=0; $i -lt $expectedStates.Count; $i++){ if($states[$i] -ne $expectedStates[$i]){ Fail "episode-state model mismatch at index $i" } }

Assert-TrueField $health "adaptation_replan_current_plan_generation_bound"
Assert-TrueField $health "adaptation_replan_historical_plans_immutable"
if($health.adaptation_replan_target_plan_generation_rule -ne "SOURCE_PLAN_GENERATION_PLUS_ONE"){ Fail "target Plan generation rule must be SOURCE_PLAN_GENERATION_PLUS_ONE" }
Pass "Stage 3.7.1 canonical identity/materialization control is active"

Write-Host "`n[1] Authority-boundary proof"
foreach($field in @(
    "adaptation_replan_terminal_reopening_allowed",
    "adaptation_replan_classification_performed",
    "adaptation_replan_eligibility_evaluation_performed",
    "adaptation_replan_snapshot_bound",
    "adaptation_replan_lifecycle_replan_requested",
    "adaptation_replan_planner_invocation_performed",
    "adaptation_replan_candidate_created",
    "adaptation_replan_plan_delta_computed",
    "adaptation_replan_plan_validation_performed",
    "adaptation_replan_commit_performed",
    "adaptation_replan_plan_supersession_performed",
    "adaptation_replan_mission_state_transition_performed",
    "adaptation_replan_governance_query_performed",
    "adaptation_replan_runtime_query_performed",
    "adaptation_replan_runtime_control_io_performed",
    "adaptation_replan_dispatch_performed",
    "adaptation_replan_new_execution_attempt_created",
    "adaptation_replan_external_network_io_performed",
    "adaptation_replan_target_action_dispatch_performed",
    "adaptation_replan_target_actuation"
)){ Assert-FalseField $health $field }
Pass "Stage 3.7.1 remains detection/identity-only and non-actuating"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.1 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.1 regression failed" }
Pass "Full Stage 3.1-3.7.1 regression passed"

Write-Host "`n[5] Focused Stage 3.7.1 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.1 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.1 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.1 proof passed"

Write-Host "`n[6] Historical current-head tail probes"
$tails=(& python -m pytest -q `
 tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed `
 tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered 2>&1 | Out-String)
Write-Host $tails.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "historical current-head tail probes failed" }
if($tails -notmatch "(?m)^2 passed"){ Fail "historical tail probe suite must report exactly 2 passed" }
Pass "Historical current-head tail probes passed"

Write-Host "`n[7] Migration / source presence"
if(-not(Test-Path "migrations/045_stage3_7_1_canonical_adaptation_replan_contract_identity.sql")){ Fail "Stage-3.7.1 migration 045 is missing" }
if(-not(Test-Path "mission_orchestrator/adaptation_replan.py")){ Fail "Stage-3.7.1 adaptation/replan module is missing" }
if(-not(Test-Path "tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py")){ Fail "Stage-3.7.1 focused proof is missing" }
$migration=Get-Content "migrations/045_stage3_7_1_canonical_adaptation_replan_contract_identity.sql" -Raw
if($migration -notmatch "mission_adaptation_replan_contracts"){ Fail "migration 045 does not create the canonical Stage-3.7.1 store" }
$source=Get-Content "mission_orchestrator/adaptation_replan.py" -Raw
if($source -notmatch 'ADAPTATION_EPISODE_ID_PREFIX = "adpt-"'){ Fail "canonical AdaptationEpisode identity definition missing" }
if($source -notmatch 'REPLAN_TRIGGER_ID_PREFIX = "rpln-"'){ Fail "canonical ReplanTrigger identity definition missing" }
Pass "Migration 045, canonical store, domain module, and focused tests are present"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version             : $expectedControl"
Write-Host "repository migration        : $expectedMigrationLevel"
Write-Host "canonical test inventory    : $expectedTestCount"
Write-Host "focused Stage-3.7.1 tests   : $expectedFocusedCount"
Write-Host "persistence store           : $expectedStore"
Write-Host "episode initial state       : DETECTED"
Write-Host "successor generation rule   : source N -> target N+1 (binding only)"
Write-Host "planner/dispatch/actuation  : NOT PERFORMED"
