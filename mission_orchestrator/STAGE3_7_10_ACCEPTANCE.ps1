param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.7.10 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $false){ Fail "$Context boundary drifted: $Field must be false" } }
function Assert-TrueField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $true){ Fail "$Context contract drifted: $Field must be true" } }

$expectedControl="stage3.7.10-adapt-replan-acceptance-regression-gate"
$expectedPredecessor="stage3.7.9-adapt-replan-lineage-replay-recovery"
$expectedMigrationLevel=53
$expectedTestCount=1356
$expectedFocusedCount=12
$expectedPredecessorFocusedCount=22
$expectedStage37Count=200
$expectedSchema="apts-mission-stage3.7-adapt-replan-acceptance-gate-v1"
$expectedMode="FULL_REGRESSION_PLUS_CANONICAL_ADAPT_REPLAN_INTEGRATION_AND_LIVE_BOUNDARY_PROBES"
$expectedBaseline="STAGE_3_7_1_THROUGH_3_7_9"
$expectedRuntimeChangeMode="NO_NEW_ADAPT_REPLAN_AUTHORITY_RUNTIME_IO_PLAN_MUTATION_OR_TARGET_ACTUATION"
$expectedDatabaseChangeMode="NO_NEW_DATABASE_MIGRATION"

$requiredPriorControls=@(
    "stage3.7.1-canonical-adaptation-replan-contract-identity",
    "stage3.7.2-adaptation-trigger-detection-classification",
    "stage3.7.3-replan-eligibility-governance-gate",
    "stage3.7.4-canonical-replan-snapshot-context-binding",
    "stage3.7.5-deterministic-replan-candidate-generation",
    "stage3.7.6-replan-candidate-validation-delta-feasibility-gate",
    "stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization",
    "stage3.7.8-atomic-replan-commit-supersession-handoff",
    "stage3.7.9-adapt-replan-lineage-replay-recovery"
)

$requiredGates=@(
    "PYTHON_COMPILE",
    "CANONICAL_PYTEST_INVENTORY",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_ADAPTATION_REPLAN_CONTRACT_AND_IDENTITY",
    "ADAPTATION_TRIGGER_DETECTION_AND_CLASSIFICATION",
    "REPLAN_ELIGIBILITY_AND_GOVERNANCE_GATE",
    "CANONICAL_REPLAN_SNAPSHOT_CONTEXT_BINDING",
    "DETERMINISTIC_REPLAN_CANDIDATE_GENERATION",
    "REPLAN_CANDIDATE_VALIDATION_AND_DELTA_FEASIBILITY",
    "AUTHORITATIVE_REPLAN_COMMIT_AND_SUCCESSOR_PLAN_MATERIALIZATION",
    "ATOMIC_REPLAN_SUPERSESSION_AND_HANDOFF",
    "ADAPT_REPLAN_LINEAGE_REPLAY_AND_RECOVERY",
    "END_TO_END_ADAPT_REPLAN_TRAJECTORY_INTEGRATION",
    "RESTART_RECONSTRUCTION_WITHOUT_PLANNER_GOVERNANCE_RUNTIME_REDISPATCH_OR_ACTUATION",
    "REPOSITORY_AND_EVENT_INTEGRITY",
    "FINAL_ADAPT_REPLAN_AUTHORITY_RUNTIME_IO_PLAN_MUTATION_AND_ACTUATION_BOUNDARY"
)

Write-Host "=============================================================================="
Write-Host "Stage 3.7.10 - Adapt/Replan Acceptance / Regression Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.10 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must remain $expectedMigrationLevel" }
if([int]$health.replan_recovery_database_migration_level -ne $expectedMigrationLevel){ Fail "Stage-3.7.9 migration metadata must remain $expectedMigrationLevel" }
if($health.stage3_7_adapt_replan_acceptance_gate_schema_version -ne $expectedSchema){ Fail "unexpected Stage-3.7.10 closure schema" }
if($health.stage3_7_adapt_replan_acceptance_gate_mode -ne $expectedMode){ Fail "unexpected Stage-3.7.10 closure mode" }
if($health.stage3_7_adapt_replan_acceptance_gate_baseline -ne $expectedBaseline){ Fail "unexpected Stage-3.7.10 baseline" }
if($health.stage3_7_adapt_replan_acceptance_gate_runtime_change_mode -ne $expectedRuntimeChangeMode){ Fail "unexpected Stage-3.7.10 runtime change mode" }
if($health.stage3_7_adapt_replan_acceptance_gate_database_change_mode -ne $expectedDatabaseChangeMode){ Fail "unexpected Stage-3.7.10 database change mode" }
if([int]$health.stage3_7_adapt_replan_acceptance_gate_expected_migration_level -ne $expectedMigrationLevel){ Fail "Stage-3.7.10 expected migration metadata must remain $expectedMigrationLevel" }
Assert-TrueField $health "stage3_7_adapt_replan_acceptance_gate_declared_only" "health"
Assert-FalseField $health "stage3_7_adapt_replan_acceptance_gate_runtime_self_certification" "health"
Assert-TrueField $health "stage3_7_adapt_replan_acceptance_gate_external_execution_required" "health"

$supported=@($health.supported_controls)
if($supported.Count -lt 10){ Fail "supported_controls does not contain complete Stage 3.7 chain" }
for($i=0; $i -lt $requiredPriorControls.Count; $i++){
    $offset=$supported.Count-10+$i
    if($supported[$offset] -ne $requiredPriorControls[$i]){ Fail "Stage-3.7 supported-control ordering mismatch at Stage-3.7 index $i" }
}
if($supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl){ Fail "supported control tail must end with Stage 3.7.9 then Stage 3.7.10" }

$prior=@($health.stage3_7_adapt_replan_acceptance_gate_required_prior_controls)
if($prior.Count -ne $requiredPriorControls.Count){ Fail "Stage-3.7.10 prior-control cardinality mismatch" }
for($i=0; $i -lt $requiredPriorControls.Count; $i++){
    if($prior[$i] -ne $requiredPriorControls[$i]){ Fail "Stage-3.7.10 required prior-control ordering mismatch at index $i" }
}
$gates=@($health.stage3_7_adapt_replan_acceptance_gate_required_gates)
if($gates.Count -ne $requiredGates.Count){ Fail "Stage-3.7.10 must declare exactly $($requiredGates.Count) mandatory acceptance gates" }
for($i=0; $i -lt $requiredGates.Count; $i++){
    if($gates[$i] -ne $requiredGates[$i]){ Fail "Stage-3.7.10 required gate ordering mismatch at index $i" }
}
Pass "Stage 3.7.10 runtime closure declaration is active and cannot self-certify PASS"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.7.10 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.10 regression failed" }
Pass "Full Stage 3.1-3.7.10 regression passed"

Write-Host "`n[4] Stage 3.7 chain regression"
$stage37=(& python -m pytest -q `
 tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py `
 tests/test_stage3_7_2_adaptation_trigger_detection_classification.py `
 tests/test_stage3_7_3_replan_eligibility_governance_gate.py `
 tests/test_stage3_7_4_canonical_replan_snapshot_context_binding.py `
 tests/test_stage3_7_5_deterministic_replan_candidate_generation.py `
 tests/test_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.py `
 tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py `
 tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py `
 tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py `
 tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py 2>&1 | Out-String)
Write-Host $stage37.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage-3.7 chain regression failed" }
if($stage37 -notmatch "(?m)^$expectedStage37Count passed"){ Fail "Stage-3.7 chain suite must report exactly $expectedStage37Count passed" }
Pass "Stage-3.7.1 through Stage-3.7.10 chain passed"

Write-Host "`n[5] Focused Stage 3.7.10 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.10 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.10 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.10 closure proof passed"

Write-Host "`n[6] Stage 3.7.9 predecessor non-regression proof"
$predecessor=(& python -m pytest -q tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py 2>&1 | Out-String)
Write-Host $predecessor.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.9 predecessor tests failed" }
if($predecessor -notmatch "(?m)^$expectedPredecessorFocusedCount passed"){ Fail "focused Stage-3.7.9 suite must report exactly $expectedPredecessorFocusedCount passed" }
Pass "Stage-3.7.9 predecessor proof passed"

Write-Host "`n[7] Migration / source / version closure"
foreach($path in @(
    "migrations/053_stage3_7_9_adapt_replan_lineage_replay_recovery.sql",
    "mission_orchestrator/adapt_replan_acceptance_gate.py",
    "tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py"
)){ if(-not(Test-Path $path)){ Fail "missing $path" } }
if(Test-Path "migrations/054_stage3_7_10_adapt_replan_acceptance_regression_gate.sql"){ Fail "Stage 3.7.10 must not add migration 054" }
if((Get-ChildItem "migrations/*.sql").Count -ne 53){ Fail "migration inventory must remain exactly 53 SQL migrations" }
$gateSource=Get-Content "mission_orchestrator/adapt_replan_acceptance_gate.py" -Raw
foreach($token in @(
    'ADAPT_REPLAN_ACCEPTANCE_GATE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"',
    'ADAPT_REPLAN_ACCEPTANCE_GATE_EXPECTED_MIGRATION_LEVEL = 53',
    '"runtime_self_certification": False',
    '"external_acceptance_execution_required": True',
    '"stage377_is_successor_plan_commit_authority": True',
    '"stage378_is_handoff_authority": True'
)){ if($gateSource -notmatch [regex]::Escape($token)){ Fail "Stage-3.7.10 closure source token missing: $token" } }
$serviceSource=Get-Content "mission_orchestrator/service.py" -Raw
if($serviceSource -notmatch 'CONTROL_VERSION = "stage3\.7\.10-adapt-replan-acceptance-regression-gate"'){ Fail "service control_version is not Stage 3.7.10" }
$apiSource=Get-Content "mission_orchestrator/api_service.py" -Raw
if($apiSource -notmatch 'server_version = "APTSMissionOrchestrator/3\.7\.10"'){ Fail "API server_version is not 3.7.10" }
Pass "Stage-3.7.10 adds no migration/store and activates only closure/version metadata"

Write-Host "`n[8] Stage 3.7 authority matrix"
Assert-FalseField $health "adaptation_replan_classification_performed" "Stage 3.7.1"
Assert-FalseField $health "adaptation_replan_planner_invocation_performed" "Stage 3.7.1"
Assert-FalseField $health "adaptation_replan_dispatch_performed" "Stage 3.7.1"
Assert-FalseField $health "adaptation_replan_target_actuation" "Stage 3.7.1"
Assert-FalseField $health "adaptation_trigger_eligibility_evaluation_performed" "Stage 3.7.2"
Assert-FalseField $health "adaptation_trigger_governance_query_performed" "Stage 3.7.2"
Assert-FalseField $health "adaptation_trigger_planner_invocation_performed" "Stage 3.7.2"
Assert-FalseField $health "adaptation_trigger_target_actuation" "Stage 3.7.2"
Assert-TrueField  $health "replan_eligibility_static_fail_closed_before_governance_query" "Stage 3.7.3"
Assert-FalseField $health "replan_eligibility_planner_invocation_performed" "Stage 3.7.3"
Assert-FalseField $health "replan_eligibility_plan_supersession_performed" "Stage 3.7.3"
Assert-FalseField $health "replan_eligibility_target_actuation" "Stage 3.7.3"
Assert-TrueField  $health "replan_snapshot_local_durable_context_only" "Stage 3.7.4"
Assert-FalseField $health "replan_snapshot_external_context_refresh_performed" "Stage 3.7.4"
Assert-FalseField $health "replan_snapshot_governance_query_performed" "Stage 3.7.4"
Assert-FalseField $health "replan_snapshot_plan_supersession_performed" "Stage 3.7.4"
Assert-TrueField  $health "replan_candidate_deterministic_local_planner" "Stage 3.7.5"
Assert-TrueField  $health "replan_candidate_planner_invocation_performed" "Stage 3.7.5"
Assert-FalseField $health "replan_candidate_successor_plan_created" "Stage 3.7.5"
Assert-FalseField $health "replan_candidate_plan_supersession_performed" "Stage 3.7.5"
Assert-TrueField  $health "replan_validation_plan_validation_performed" "Stage 3.7.6"
Assert-FalseField $health "replan_validation_successor_plan_created" "Stage 3.7.6"
Assert-FalseField $health "replan_validation_plan_supersession_performed" "Stage 3.7.6"
Assert-TrueField  $health "replan_commit_authoritative_governance_revalidation_performed" "Stage 3.7.7"
Assert-TrueField  $health "replan_commit_successor_plan_created" "Stage 3.7.7"
Assert-TrueField  $health "replan_commit_plan_supersession_performed" "Stage 3.7.7"
Assert-FalseField $health "replan_commit_historical_plan_mutation_performed" "Stage 3.7.7"
Assert-FalseField $health "replan_commit_dispatch_performed" "Stage 3.7.7"
Assert-FalseField $health "replan_commit_target_actuation" "Stage 3.7.7"
Assert-TrueField  $health "replan_handoff_atomic_commit_verified" "Stage 3.7.8"
Assert-TrueField  $health "replan_handoff_plan_supersession_verified" "Stage 3.7.8"
Assert-FalseField $health "replan_handoff_cancellation_io_performed" "Stage 3.7.8"
Assert-FalseField $health "replan_handoff_dispatch_performed" "Stage 3.7.8"
Assert-FalseField $health "replan_handoff_target_actuation" "Stage 3.7.8"
Assert-TrueField  $health "replan_replay_read_only" "Stage 3.7.9"
Assert-TrueField  $health "replan_recovery_reconstructs_from_durable_repository" "Stage 3.7.9"
Assert-FalseField $health "replan_replay_side_effects_performed" "Stage 3.7.9"
Assert-FalseField $health "replan_recovery_planner_rerun_performed" "Stage 3.7.9"
Assert-FalseField $health "replan_recovery_governance_query_performed" "Stage 3.7.9"
Assert-FalseField $health "replan_recovery_runtime_control_io_performed" "Stage 3.7.9"
Assert-FalseField $health "replan_recovery_dispatch_performed" "Stage 3.7.9"
Assert-FalseField $health "replan_recovery_historical_plan_mutation_performed" "Stage 3.7.9"
Assert-FalseField $health "replan_recovery_active_plan_head_cas_performed" "Stage 3.7.9"
Assert-FalseField $health "replan_recovery_target_actuation" "Stage 3.7.9"
Pass "Stage-3.7 authority remains separated across detect/classify/gate/snapshot/generate/validate/commit/handoff/recovery"

Write-Host "`n[9] Stage 3.7.10 no-new-authority / no-I/O / no-mutation closure"
foreach($field in @(
    "stage3_7_adapt_replan_acceptance_gate_new_adaptation_episode_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_trigger_classification_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_replan_eligibility_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_snapshot_binding_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_candidate_generation_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_validation_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_commit_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_plan_supersession_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_handoff_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_recovery_authority_added",
    "stage3_7_adapt_replan_acceptance_gate_new_governance_query_added",
    "stage3_7_adapt_replan_acceptance_gate_new_runtime_query_added",
    "stage3_7_adapt_replan_acceptance_gate_new_runtime_control_io_added",
    "stage3_7_adapt_replan_acceptance_gate_new_external_context_refresh_added",
    "stage3_7_adapt_replan_acceptance_gate_new_external_network_io_added",
    "stage3_7_adapt_replan_acceptance_gate_new_cancellation_io_added",
    "stage3_7_adapt_replan_acceptance_gate_new_routing_added",
    "stage3_7_adapt_replan_acceptance_gate_new_delegation_added",
    "stage3_7_adapt_replan_acceptance_gate_new_dispatch_added",
    "stage3_7_adapt_replan_acceptance_gate_new_execution_attempt_added",
    "stage3_7_adapt_replan_acceptance_gate_new_mission_state_transition_added",
    "stage3_7_adapt_replan_acceptance_gate_new_historical_plan_mutation_added",
    "stage3_7_adapt_replan_acceptance_gate_new_active_plan_head_cas_added",
    "stage3_7_adapt_replan_acceptance_gate_new_target_action_dispatch_added",
    "stage3_7_adapt_replan_acceptance_gate_new_target_actuation_added",
    "stage3_7_adapt_replan_acceptance_gate_new_llm_reinterpretation_added",
    "stage3_7_adapt_replan_acceptance_gate_new_durable_store_added",
    "stage3_7_adapt_replan_acceptance_gate_new_database_migration_added",
    "stage3_7_adapt_replan_acceptance_gate_stage379_replay_is_replan_processing",
    "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_replan_execution",
    "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_dispatch",
    "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_runtime_resumption",
    "stage3_7_adapt_replan_acceptance_gate_stage379_recovery_is_lifecycle_transition",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_adaptation_detection",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_trigger_classification",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_replan_eligibility_authority",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_snapshot_binding",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_candidate_generation",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_candidate_validation",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_plan_commit",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_plan_supersession",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_handoff",
    "stage3_7_adapt_replan_acceptance_gate_closure_gate_is_recovery"
)){ Assert-FalseField $health $field "Stage 3.7.10" }
Assert-TrueField $health "stage3_7_adapt_replan_acceptance_gate_stage377_is_successor_plan_commit_authority" "Stage 3.7.10"
Assert-TrueField $health "stage3_7_adapt_replan_acceptance_gate_stage378_is_handoff_authority" "Stage 3.7.10"
Pass "Stage-3.7.10 is a declaration-only closure gate with no new operational authority"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.10 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "Stage 3.7 closed: detect -> classify -> eligibility/governance -> snapshot -> candidate -> validate -> commit -> handoff -> lineage/replay/recovery -> acceptance."
Write-Host "Repository migration level: 53 (unchanged); new durable store: NONE; new migration: NONE."
Write-Host "Authoritative successor-plan commit remains Stage 3.7.7; handoff authority remains Stage 3.7.8; Stage 3.7.9 recovery remains read-only reconstruction."
Write-Host "=============================================================================="
