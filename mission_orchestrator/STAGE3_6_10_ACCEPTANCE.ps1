param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.6.10 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $false){ Fail "$Context boundary drifted: $Field must be false" } }
function Assert-TrueField($Object,[string]$Field,[string]$Context){ if($Object.$Field -ne $true){ Fail "$Context contract drifted: $Field must be true" } }

$expectedControl="stage3.6.10-outcome-acceptance-regression-gate"
$expectedPredecessor="stage3.6.9-outcome-lineage-replay-recovery"
$expectedMigrationLevel=44
$expectedTestCount=1156
$expectedFocusedCount=12
$expectedStage6Count=193
$expectedSchema="apts-mission-stage3.6-outcome-acceptance-gate-v1"
$expectedMode="FULL_REGRESSION_PLUS_CANONICAL_OUTCOME_INTEGRATION_AND_LIVE_COMPLETION_BOUNDARY_PROBES"
$expectedBaseline="STAGE_3_6_1_THROUGH_3_6_9"
$expectedRuntimeChangeMode="NO_NEW_OUTCOME_COMPLETION_AUTHORITY_RUNTIME_IO_OR_TARGET_ACTUATION"
$expectedDatabaseChangeMode="NO_NEW_DATABASE_MIGRATION"

$requiredPriorControls=@(
    "stage3.6.1-canonical-task-outcome-contract-identity",
    "stage3.6.2-task-terminality-completion-eligibility",
    "stage3.6.3-evidence-binding-verification",
    "stage3.6.4-dependency-aware-task-completion",
    "stage3.6.5-mission-outcome-aggregation",
    "stage3.6.6-mission-success-criteria-evaluation",
    "stage3.6.7-completion-readiness-blockers",
    "stage3.6.8-verified-completion-declaration-lifecycle-handoff",
    "stage3.6.9-outcome-lineage-replay-recovery"
)

Write-Host "=============================================================================="
Write-Host "Stage 3.6.10 - Outcome Acceptance / Regression Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.6.10 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must remain $expectedMigrationLevel" }
if($health.stage3_6_outcome_acceptance_gate_schema_version -ne $expectedSchema){ Fail "unexpected Stage-3.6.10 closure schema" }
if($health.stage3_6_outcome_acceptance_gate_mode -ne $expectedMode){ Fail "unexpected Stage-3.6.10 closure mode" }
if($health.stage3_6_outcome_acceptance_gate_baseline -ne $expectedBaseline){ Fail "unexpected Stage-3.6.10 baseline" }
if($health.stage3_6_outcome_acceptance_gate_runtime_change_mode -ne $expectedRuntimeChangeMode){ Fail "unexpected Stage-3.6.10 runtime change mode" }
if($health.stage3_6_outcome_acceptance_gate_database_change_mode -ne $expectedDatabaseChangeMode){ Fail "unexpected Stage-3.6.10 database change mode" }
if([int]$health.stage3_6_outcome_acceptance_gate_expected_migration_level -ne $expectedMigrationLevel){ Fail "Stage-3.6.10 expected migration metadata must remain $expectedMigrationLevel" }
Assert-TrueField $health "stage3_6_outcome_acceptance_gate_declared_only" "health"
Assert-FalseField $health "stage3_6_outcome_acceptance_gate_runtime_self_certification" "health"
Assert-TrueField $health "stage3_6_outcome_acceptance_gate_external_execution_required" "health"
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPredecessor -or $supported[-1] -ne $expectedControl){ Fail "supported control tail must end with Stage 3.6.9 then Stage 3.6.10" }
$prior=@($health.stage3_6_outcome_acceptance_gate_required_prior_controls)
if($prior.Count -ne $requiredPriorControls.Count){ Fail "Stage-3.6.10 prior-control cardinality mismatch" }
for($i=0; $i -lt $requiredPriorControls.Count; $i++){
    if($prior[$i] -ne $requiredPriorControls[$i]){ Fail "Stage-3.6.10 required prior-control ordering mismatch at index $i" }
}
$gates=@($health.stage3_6_outcome_acceptance_gate_required_gates)
if($gates.Count -ne 17){ Fail "Stage-3.6.10 must declare exactly 17 mandatory acceptance gates" }
Pass "Stage 3.6.10 runtime closure declaration is active and cannot self-certify PASS"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.6.10 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.6.10 regression failed" }
Pass "Full Stage 3.1-3.6.10 regression passed"

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
 tests/test_stage3_6_9_outcome_lineage_replay_recovery.py `
 tests/test_stage3_6_10_outcome_acceptance_regression_gate.py 2>&1 | Out-String)
Write-Host $stage6.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage-3.6 chain regression failed" }
if($stage6 -notmatch "(?m)^$expectedStage6Count passed"){ Fail "Stage-3.6 chain suite must report exactly $expectedStage6Count passed" }
Pass "Stage-3.6.1 through Stage-3.6.10 chain passed"

Write-Host "`n[5] Focused Stage 3.6.10 proof"
$focused=(& python -m pytest -q tests/test_stage3_6_10_outcome_acceptance_regression_gate.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.6.10 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.6.10 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.6.10 closure proof passed"

Write-Host "`n[6] Migration / source closure"
if(-not(Test-Path "migrations/044_stage3_6_9_outcome_lineage_replay_recovery.sql")){ Fail "migration 044 is missing" }
if(Test-Path "migrations/045_stage3_6_10_outcome_acceptance_regression_gate.sql"){ Fail "Stage 3.6.10 must not add migration 045" }
if(-not(Test-Path "mission_orchestrator/outcome_acceptance_gate.py")){ Fail "Stage-3.6.10 closure-contract module is missing" }
if(-not(Test-Path "tests/test_stage3_6_10_outcome_acceptance_regression_gate.py")){ Fail "Stage-3.6.10 focused proof is missing" }
$gateSource=Get-Content "mission_orchestrator/outcome_acceptance_gate.py" -Raw
if($gateSource -notmatch "NO_NEW_DATABASE_MIGRATION"){ Fail "Stage-3.6.10 no-migration declaration is missing" }
if($gateSource -notmatch "runtime_self_certification"){ Fail "Stage-3.6.10 external acceptance boundary declaration is missing" }
Pass "Stage-3.6.10 adds no migration/store and declares external acceptance only"

Write-Host "`n[7] Stage 3.6 completion-authority matrix"
Assert-FalseField $health "task_outcome_mission_success_completion_authority_exercised" "Stage 3.6.1"
Assert-FalseField $health "task_outcome_completion_commit_performed" "Stage 3.6.1"
Assert-FalseField $health "task_terminality_mission_success_completion_authority_exercised" "Stage 3.6.2"
Assert-FalseField $health "task_terminality_acceptance_performed" "Stage 3.6.2"
Assert-FalseField $health "task_evidence_binding_mission_success_completion_authority_exercised" "Stage 3.6.3"
Assert-FalseField $health "task_evidence_binding_task_completion_commit_performed" "Stage 3.6.3"
Assert-TrueField  $health "task_completion_task_completion_commit_performed" "Stage 3.6.4"
Assert-FalseField $health "task_completion_mission_success_completion_authority_exercised" "Stage 3.6.4"
Assert-FalseField $health "mission_outcome_aggregation_success_criteria_evaluation_performed" "Stage 3.6.5"
Assert-FalseField $health "mission_outcome_aggregation_mission_success_completion_authority_exercised" "Stage 3.6.5"
Assert-TrueField  $health "mission_success_evaluation_performed" "Stage 3.6.6"
Assert-FalseField $health "mission_success_evaluation_mission_completion_readiness_decision_performed" "Stage 3.6.6"
Assert-FalseField $health "mission_success_evaluation_mission_success_completion_authority_exercised" "Stage 3.6.6"
Assert-TrueField  $health "completion_readiness_decision_performed" "Stage 3.6.7"
Assert-FalseField $health "completion_readiness_mission_success_completion_authority_exercised" "Stage 3.6.7"
Assert-TrueField  $health "verified_completion_declaration_performed" "Stage 3.6.8"
Assert-TrueField  $health "verified_completion_mission_success_completion_authority_exercised" "Stage 3.6.8"
Assert-TrueField  $health "verified_completion_uses_canonical_stage32_lifecycle_command_path" "Stage 3.6.8"
Assert-FalseField $health "verified_completion_direct_state_transition_bypass_used" "Stage 3.6.8"
Assert-FalseField $health "verified_completion_runtime_control_io_performed" "Stage 3.6.8"
Assert-TrueField  $health "outcome_replay_read_only" "Stage 3.6.9"
Assert-TrueField  $health "outcome_recovery_reconstructs_from_durable_repository" "Stage 3.6.9"
Assert-FalseField $health "outcome_recovery_mission_success_completion_authority_exercised" "Stage 3.6.9"
Assert-FalseField $health "outcome_recovery_is_dispatch" "Stage 3.6.9"
Assert-FalseField $health "outcome_recovery_is_runtime_resumption" "Stage 3.6.9"
Assert-FalseField $health "outcome_recovery_is_lifecycle_transition" "Stage 3.6.9"
Pass "Single Mission-success completion authority remains Stage 3.6.8; Stage 3.6.9 remains read-only/non-actuating recovery"

Write-Host "`n[8] Stage 3.6.10 no-new-authority / no-I/O / no-actuation proof"
foreach($field in @(
    "stage3_6_outcome_acceptance_gate_new_task_outcome_authority_added",
    "stage3_6_outcome_acceptance_gate_new_terminality_classification_authority_added",
    "stage3_6_outcome_acceptance_gate_new_evidence_verification_authority_added",
    "stage3_6_outcome_acceptance_gate_new_task_completion_authority_added",
    "stage3_6_outcome_acceptance_gate_new_mission_outcome_aggregation_added",
    "stage3_6_outcome_acceptance_gate_new_success_criteria_evaluation_added",
    "stage3_6_outcome_acceptance_gate_new_completion_readiness_decision_added",
    "stage3_6_outcome_acceptance_gate_new_mission_success_completion_authority_added",
    "stage3_6_outcome_acceptance_gate_new_lifecycle_transition_path_added",
    "stage3_6_outcome_acceptance_gate_new_governance_query_added",
    "stage3_6_outcome_acceptance_gate_new_runtime_query_added",
    "stage3_6_outcome_acceptance_gate_new_runtime_control_io_added",
    "stage3_6_outcome_acceptance_gate_new_external_network_io_added",
    "stage3_6_outcome_acceptance_gate_new_dispatch_redelivery_added",
    "stage3_6_outcome_acceptance_gate_new_execution_attempt_added",
    "stage3_6_outcome_acceptance_gate_new_target_action_dispatch_added",
    "stage3_6_outcome_acceptance_gate_new_target_actuation_added",
    "stage3_6_outcome_acceptance_gate_new_llm_reinterpretation_added",
    "stage3_6_outcome_acceptance_gate_new_durable_store_added",
    "stage3_6_outcome_acceptance_gate_new_database_migration_added",
    "stage3_6_outcome_acceptance_gate_task_outcome_is_task_completion",
    "stage3_6_outcome_acceptance_gate_terminality_is_task_acceptance",
    "stage3_6_outcome_acceptance_gate_evidence_verification_is_task_completion",
    "stage3_6_outcome_acceptance_gate_task_completion_is_mission_completion",
    "stage3_6_outcome_acceptance_gate_aggregation_is_success_evaluation",
    "stage3_6_outcome_acceptance_gate_success_evaluation_is_completion_authority",
    "stage3_6_outcome_acceptance_gate_readiness_is_completion_authority",
    "stage3_6_outcome_acceptance_gate_verified_completion_direct_state_transition_bypass_used",
    "stage3_6_outcome_acceptance_gate_replay_is_outcome_processing",
    "stage3_6_outcome_acceptance_gate_recovery_is_completion_authority",
    "stage3_6_outcome_acceptance_gate_recovery_is_dispatch",
    "stage3_6_outcome_acceptance_gate_recovery_is_runtime_resumption",
    "stage3_6_outcome_acceptance_gate_recovery_is_lifecycle_transition",
    "stage3_6_outcome_acceptance_gate_closure_gate_is_outcome_processing",
    "stage3_6_outcome_acceptance_gate_closure_gate_is_completion_authority"
)){ Assert-FalseField $health $field "Stage 3.6.10" }
Assert-TrueField $health "stage3_6_outcome_acceptance_gate_verified_completion_is_mission_success_completion_authority" "Stage 3.6.10"
Pass "Stage-3.6.10 introduces no new outcome/completion authority, runtime I/O, lifecycle path, persistence, dispatch, or actuation"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.6.10 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "control_version             : $expectedControl"
Write-Host "repository migration        : $expectedMigrationLevel"
Write-Host "canonical test inventory    : $expectedTestCount"
Write-Host "Stage-3.6 chain tests        : $expectedStage6Count"
Write-Host "focused Stage-3.6.10 tests  : $expectedFocusedCount"
Write-Host "new durable store           : NONE"
Write-Host "new database migration      : NONE"
Write-Host "Mission-success authority   : Stage 3.6.8 verified completion declaration"
Write-Host "Stage 3.6 status            : CLOSED"
