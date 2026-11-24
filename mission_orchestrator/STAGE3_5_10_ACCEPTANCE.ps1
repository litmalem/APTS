param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.5.10 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Assert-FalseFields($Object, [string[]]$Fields, [string]$Context) {
    foreach ($field in $Fields) {
        if ($Object.$field -ne $false) {
            Fail "$Context boundary drifted: $field must be false"
        }
    }
}

$expectedControl = "stage3.5.10-execution-dispatch-acceptance-regression-gate"
$expectedGateSchema = "apts-mission-stage3.5-execution-dispatch-acceptance-gate-v1"
$expectedGateMode = "FULL_REGRESSION_PLUS_CANONICAL_EXECUTION_INTEGRATION_AND_LIVE_RUNTIME_BOUNDARY_PROBES"
$expectedGateBaseline = "STAGE_3_5_1_THROUGH_3_5_9"
$expectedRuntimeChangeMode = "NO_NEW_EXECUTION_AUTHORITY_RUNTIME_IO_OR_TARGET_ACTUATION"
$expectedMigrationLevel = 35
$expectedTestCount = 963
$expectedFocusedCount = 12

$requiredStage35Controls = @(
    "stage3.5.1-canonical-execution-dispatch-contract-identity",
    "stage3.5.2-dispatch-eligibility-execution-preconditions",
    "stage3.5.3-authoritative-pre-dispatch-governance-revalidation",
    "stage3.5.4-idempotent-dispatch-execution-attempt-identity",
    "stage3.5.5-dispatch-delivery-execution-acknowledgement",
    "stage3.5.6-running-execution-state-heartbeat-projection",
    "stage3.5.7-execution-result-evidence-artifact-capture",
    "stage3.5.8-timeout-cancellation-abort-failure-propagation",
    "stage3.5.9-execution-event-lineage-replay-recovery"
)

$requiredGates = @(
    "PYTHON_COMPILE",
    "CANONICAL_PYTEST_INVENTORY",
    "FULL_PYTEST_REGRESSION",
    "MISSION_HEALTH_AND_AUTHORITY_BOUNDARY",
    "CANONICAL_EXECUTION_DISPATCH_CONTRACT_AND_IDENTITY",
    "DISPATCH_ELIGIBILITY_AND_EXECUTION_PRECONDITIONS",
    "AUTHORITATIVE_PRE_DISPATCH_GOVERNANCE_REVALIDATION",
    "IDEMPOTENT_DISPATCH_AND_EXECUTION_ATTEMPT_IDENTITY",
    "DISPATCH_DELIVERY_AND_EXECUTION_ACKNOWLEDGEMENT",
    "RUNNING_EXECUTION_STATE_AND_HEARTBEAT_PROJECTION",
    "EXECUTION_RESULT_EVIDENCE_AND_ARTIFACT_CAPTURE",
    "TIMEOUT_CANCELLATION_ABORT_AND_FAILURE_PROPAGATION",
    "EXECUTION_EVENT_LINEAGE_REPLAY_AND_RECOVERY",
    "SUCCESS_AND_NON_SUCCESS_TERMINAL_TRAJECTORY_INTEGRATION",
    "RESTART_RECONSTRUCTION_WITHOUT_RUNTIME_QUERY_REDISPATCH_OR_RESUMPTION",
    "REPOSITORY_AND_EVENT_INTEGRITY",
    "FINAL_EXECUTION_AUTHORITY_RUNTIME_IO_AND_ACTUATION_BOUNDARY"
)

Write-Host "=============================================================================="
Write-Host "Stage 3.5.10 - Execution Dispatch Acceptance / Regression Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator is not reachable at $MissionBaseUrl"
}
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.5.10 source is not active on port 8780" }
Pass "Stage 3.5.10 runtime control is active"

Write-Host "`n[1] Python compile"
Push-Location $PSScriptRoot
try {
    python -m compileall -q mission_orchestrator tests
    if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
} finally {
    Pop-Location
}
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
Push-Location $PSScriptRoot
try {
    $collectOutput = (& python -m pytest --collect-only -q 2>&1 | Out-String)
    $collectExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($collectExit -ne 0) {
    Write-Host $collectOutput
    Fail "Pytest collection failed"
}
if ($collectOutput -notmatch "(?m)$expectedTestCount tests collected") {
    Write-Host $collectOutput
    Fail "Expected exactly $expectedTestCount collected tests"
}
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[3] Full Stage 3.1-3.5.10 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full $expectedTestCount-test regression passed"

Write-Host "`n[4] Focused Stage-3.5.10 closure proof"
Push-Location $PSScriptRoot
try {
    $focusedOutput = (& python -m pytest -q tests\test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py 2>&1 | Out-String)
    $focusedExit = $LASTEXITCODE
    Write-Host $focusedOutput
} finally {
    Pop-Location
}
if ($focusedExit -ne 0) { Fail "Focused Stage-3.5.10 proof failed" }
if ($focusedOutput -notmatch "(?m)$expectedFocusedCount passed") { Fail "Expected exactly $expectedFocusedCount focused Stage-3.5.10 tests to pass" }
Pass "Focused Stage-3.5.10 end-to-end, restart, integrity, and authority-boundary proof passed"

Write-Host "`n[5] Runtime closure metadata and declared acceptance gates"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not $expectedMigrationLevel" }
if ($health.stage3_5_execution_acceptance_gate_schema_version -ne $expectedGateSchema) { Fail "Unexpected Stage-3.5 acceptance gate schema" }
if ($health.stage3_5_execution_acceptance_gate_mode -ne $expectedGateMode) { Fail "Unexpected Stage-3.5 acceptance gate mode" }
if ($health.stage3_5_execution_acceptance_gate_baseline -ne $expectedGateBaseline) { Fail "Unexpected Stage-3.5 acceptance gate baseline" }
if ($health.stage3_5_execution_acceptance_gate_runtime_change_mode -ne $expectedRuntimeChangeMode) { Fail "Stage-3.5 runtime-change boundary drifted" }
if ($health.stage3_5_execution_acceptance_gate_database_change_mode -ne "NO_NEW_DATABASE_MIGRATION") { Fail "Stage-3.5 database-change boundary drifted" }
if ([int]$health.stage3_5_execution_acceptance_gate_expected_migration_level -ne $expectedMigrationLevel) { Fail "Stage-3.5 expected migration level drifted" }
if ($health.stage3_5_execution_acceptance_gate_declared_only -ne $true) { Fail "Closure gate must remain declarative" }
if ($health.stage3_5_execution_acceptance_gate_runtime_self_certification -ne $false) { Fail "Runtime must not self-certify Stage-3.5 PASS" }
if ($health.stage3_5_execution_acceptance_gate_external_execution_required -ne $true) { Fail "External acceptance execution requirement missing" }

$observedPriorControls = @($health.stage3_5_execution_acceptance_gate_required_prior_controls)
if ($observedPriorControls.Count -ne $requiredStage35Controls.Count) { Fail "Required Stage-3.5 prior-control cardinality drifted" }
for ($i = 0; $i -lt $requiredStage35Controls.Count; $i++) {
    if ($observedPriorControls[$i] -ne $requiredStage35Controls[$i]) {
        Fail "Required Stage-3.5 prior-control mismatch at index $i"
    }
}

$observedGates = @($health.stage3_5_execution_acceptance_gate_required_gates)
if ($observedGates.Count -ne $requiredGates.Count) { Fail "Required Stage-3.5 acceptance-gate cardinality drifted" }
for ($i = 0; $i -lt $requiredGates.Count; $i++) {
    if ($observedGates[$i] -ne $requiredGates[$i]) {
        Fail "Required Stage-3.5 acceptance-gate mismatch at index $i : expected $($requiredGates[$i]), observed $($observedGates[$i])"
    }
}
Pass "Stage-3.5.10 closure metadata and all 17 required external gates are active"

Write-Host "`n[6] Stage-3.5.1 through Stage-3.5.10 supported-control ordering"
$tail = @($health.supported_controls | Select-Object -Last 10)
$expectedTail = @($requiredStage35Controls + $expectedControl)
if ($tail.Count -ne 10) { Fail "Stage-3.5 supported-control tail cardinality is not 10" }
for ($i = 0; $i -lt $expectedTail.Count; $i++) {
    if ($tail[$i] -ne $expectedTail[$i]) {
        Fail "Stage-3.5 supported-control ordering mismatch at index $i : expected $($expectedTail[$i]), observed $($tail[$i])"
    }
}
Pass "Stage 3.5.1 through 3.5.10 control lineage is complete and ordered"

Write-Host "`n[7] Stage-3.5.1-3.5.4 pre-dispatch authority boundary"
if ($health.execution_dispatch_contract_is_dispatch -ne $false) { Fail "Stage-3.5.1 contract was elevated into dispatch" }
if ($health.execution_dispatch_dispatch_performed -ne $false -or $health.execution_dispatch_external_network_io_performed -ne $false) { Fail "Stage-3.5.1 performed forbidden dispatch/network I/O" }
if ($health.execution_dispatch_target_actuation -ne $false) { Fail "Stage-3.5.1 actuated target" }

if ($health.dispatch_eligibility_is_execution_authorization -ne $false) { Fail "Stage-3.5.2 eligibility was elevated into execution authorization" }
if ($health.dispatch_eligibility_governance_query_performed -ne $false -or $health.dispatch_eligibility_dispatch_performed -ne $false) { Fail "Stage-3.5.2 performed forbidden Governance query/dispatch" }
if ($health.dispatch_eligibility_target_actuation -ne $false) { Fail "Stage-3.5.2 actuated target" }

if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority drifted from EXTERNAL_APTS_GSS" }
if ($health.pre_dispatch_governance_revalidation_authority -ne "EXTERNAL_APTS_GSS") { Fail "Stage-3.5.3 pre-dispatch authority drifted" }
if ($health.pre_dispatch_governance_authoritative_query_performed -ne $true) { Fail "Stage-3.5.3 authoritative Governance query is not enabled" }
if ($health.pre_dispatch_governance_allow_grants_execution_authorization -ne $true) { Fail "Stage-3.5.3 ALLOW no longer grants execution authorization" }
if ($health.pre_dispatch_governance_authorization_is_dispatch -ne $false) { Fail "Stage-3.5.3 authorization was elevated into dispatch" }
if ($health.pre_dispatch_governance_dispatch_performed -ne $false -or $health.pre_dispatch_governance_target_actuation -ne $false) { Fail "Stage-3.5.3 performed forbidden dispatch/actuation" }

if ($health.execution_attempt_durable_dispatch_commit_performed -ne $true) { Fail "Stage-3.5.4 durable dispatch commit is missing" }
if ($health.execution_attempt_immutable_dispatch_envelope_materialized -ne $true) { Fail "Stage-3.5.4 immutable dispatch envelope is missing" }
if ($health.execution_attempt_target_delivery_performed -ne $false) { Fail "Stage-3.5.4 dispatch commit was elevated into target delivery" }
if ($health.execution_attempt_external_target_network_io_performed -ne $false -or $health.execution_attempt_target_action_dispatch_performed -ne $false -or $health.execution_attempt_target_actuation -ne $false) { Fail "Stage-3.5.4 crossed the target-dispatch/actuation boundary" }
Pass "Contract -> eligibility -> external Governance ALLOW -> idempotent commit boundaries are intact"

Write-Host "`n[8] Stage-3.5.5-3.5.7 runtime delivery / observation / result boundary"
if ($health.execution_delivery_runtime_endpoint_resolution_performed -ne $true) { Fail "Stage-3.5.5 runtime endpoint resolution is not active" }
if ($health.execution_delivery_runtime_health_probe_performed -ne $true) { Fail "Stage-3.5.5 runtime health probe is not active" }
if ($health.execution_delivery_target_delivery_performed -ne $true -or $health.execution_delivery_acknowledgement_performed -ne $true) { Fail "Stage-3.5.5 delivery/ACK contract drifted" }
if ($health.execution_delivery_external_target_network_io_performed -ne $true -or $health.execution_delivery_target_action_dispatch_performed -ne $true) { Fail "Stage-3.5.5 is no longer the target-dispatch/network-I/O boundary" }
if ($health.execution_delivery_target_actuation -ne $false) { Fail "Stage-3.5.5 incorrectly claims target actuation" }
if ($health.execution_delivery_execution_started -ne $false -or $health.execution_delivery_running_state_recorded -ne $false) { Fail "Stage-3.5.5 delivery ACK was elevated into RUNNING state" }

if ($health.running_execution_runtime_health_probe_performed -ne $true -or $health.running_execution_runtime_execution_state_query_performed -ne $true) { Fail "Stage-3.5.6 runtime observation contract drifted" }
if ($health.running_execution_execution_started -ne $true -or $health.running_execution_running_state_recorded -ne $true -or $health.running_execution_heartbeat_recorded -ne $true) { Fail "Stage-3.5.6 RUNNING/heartbeat projection is incomplete" }
if ($health.running_execution_projection_is_observation_not_execution_authority -ne $true) { Fail "Stage-3.5.6 observation was elevated into execution authority" }
if ($health.running_execution_dispatch_redelivery_performed -ne $false -or $health.running_execution_target_action_dispatch_performed -ne $false -or $health.running_execution_target_actuation -ne $false) { Fail "Stage-3.5.6 performed redispatch/target action/actuation" }

if ($health.execution_result_runtime_terminal_result_query_performed -ne $true) { Fail "Stage-3.5.7 terminal result query is not active" }
if ($health.execution_result_evidence_required -ne $true) { Fail "Stage-3.5.7 evidence requirement drifted" }
if ($health.execution_result_is_not_task_completion_authority -ne $true) { Fail "Stage-3.5.7 result capture was elevated into task completion authority" }
if ($health.execution_result_mission_state_transition_performed -ne $false) { Fail "Stage-3.5.7 performed Mission state transition" }
if ($health.execution_result_dispatch_redelivery_performed -ne $false -or $health.execution_result_target_action_dispatch_performed -ne $false) { Fail "Stage-3.5.7 performed redispatch/new target-action dispatch" }
Pass "Stage 3.5.5 target dispatch is followed by non-authorizing runtime observation and result capture"

Write-Host "`n[9] Stage-3.5.8 termination / failure-propagation boundary"
if ($health.execution_termination_control_runtime_health_probe_performed -ne $true -or $health.execution_termination_control_runtime_control_io_performed -ne $true) { Fail "Stage-3.5.8 termination runtime-control boundary drifted" }
if ($health.execution_termination_control_governance_query_performed -ne $false) { Fail "Stage-3.5.8 termination unexpectedly queried Governance" }
if ($health.execution_termination_control_dispatch_redelivery_performed -ne $false -or $health.execution_termination_control_new_target_action_dispatch_performed -ne $false) { Fail "Stage-3.5.8 termination created redispatch/new target action" }
if ($health.execution_termination_control_mission_state_transition_performed -ne $false) { Fail "Termination-control request itself transitioned Mission state" }
if ($health.execution_outcome_runtime_result_query_performed -ne $false -or $health.execution_outcome_runtime_control_io_performed -ne $false) { Fail "Outcome propagation repeated runtime I/O" }
if ($health.execution_outcome_new_target_action_dispatch_performed -ne $false) { Fail "Outcome propagation created a new target action" }
if ($health.execution_outcome_success_does_not_imply_mission_completion -ne $true) { Fail "Successful execution was elevated into Mission completion authority" }
if ($health.execution_outcome_failure_propagates_via_canonical_stage327_lifecycle -ne $true) { Fail "Failure propagation no longer uses canonical lifecycle" }
Pass "Termination control is bounded; outcome propagation uses canonical lifecycle and does not invent a second dispatch"

Write-Host "`n[10] Stage-3.5.9 lineage / replay / recovery boundary"
if ([int]$health.execution_recovery_database_migration_level -ne 35) { Fail "Stage-3.5.9 migration declaration drifted" }
if ($health.execution_recovery_persistence_store -ne "mission_execution_recovery_checkpoints") { Fail "Stage-3.5.9 persistence store drifted" }
if ($health.execution_replay_read_only -ne $true -or $health.execution_replay_side_effects_performed -ne $false) { Fail "Stage-3.5.9 replay read-only invariant drifted" }
if ($health.execution_recovery_reconstructs_from_durable_repository -ne $true) { Fail "Stage-3.5.9 recovery no longer reconstructs from durable repository" }
Assert-FalseFields $health @(
    "execution_recovery_runtime_health_probe_performed",
    "execution_recovery_runtime_result_query_performed",
    "execution_recovery_runtime_control_io_performed",
    "execution_recovery_external_network_io_performed",
    "execution_recovery_governance_query_performed",
    "execution_recovery_dispatch_redelivery_performed",
    "execution_recovery_new_execution_attempt_created",
    "execution_recovery_new_target_action_dispatch_performed",
    "execution_recovery_mission_state_transition_performed",
    "execution_recovery_failure_propagation_performed",
    "execution_recovery_mission_success_completion_authority_exercised",
    "execution_replay_is_execution",
    "execution_recovery_is_authorization",
    "execution_recovery_is_dispatch",
    "execution_recovery_is_runtime_resumption",
    "execution_recovery_is_lifecycle_transition",
    "execution_recovery_target_actuation"
) "Stage-3.5.9 replay/recovery"
Pass "Replay remains read-only and recovery remains durable reconstruction without runtime/Governance/redispatch/resumption"

Write-Host "`n[11] Stage-3.5.10 no-new-authority / no-new-I/O / no-new-persistence proof"
Assert-FalseFields $health @(
    "stage3_5_execution_acceptance_gate_new_execution_authorization_authority_added",
    "stage3_5_execution_acceptance_gate_new_governance_query_added",
    "stage3_5_execution_acceptance_gate_new_execution_dispatch_contract_added",
    "stage3_5_execution_acceptance_gate_new_dispatch_eligibility_gate_added",
    "stage3_5_execution_acceptance_gate_new_execution_attempt_added",
    "stage3_5_execution_acceptance_gate_new_runtime_endpoint_resolution_added",
    "stage3_5_execution_acceptance_gate_new_runtime_health_probe_added",
    "stage3_5_execution_acceptance_gate_new_runtime_delivery_added",
    "stage3_5_execution_acceptance_gate_new_runtime_execution_state_query_added",
    "stage3_5_execution_acceptance_gate_new_runtime_result_query_added",
    "stage3_5_execution_acceptance_gate_new_runtime_control_io_added",
    "stage3_5_execution_acceptance_gate_new_external_network_io_added",
    "stage3_5_execution_acceptance_gate_new_dispatch_redelivery_added",
    "stage3_5_execution_acceptance_gate_new_runtime_resumption_added",
    "stage3_5_execution_acceptance_gate_new_target_action_dispatch_added",
    "stage3_5_execution_acceptance_gate_new_target_actuation_added",
    "stage3_5_execution_acceptance_gate_new_mission_state_transition_added",
    "stage3_5_execution_acceptance_gate_new_failure_propagation_added",
    "stage3_5_execution_acceptance_gate_new_mission_success_completion_authority_added",
    "stage3_5_execution_acceptance_gate_new_durable_store_added",
    "stage3_5_execution_acceptance_gate_new_database_migration_added",
    "stage3_5_execution_acceptance_gate_closure_gate_is_execution"
) "Stage-3.5.10 closure"
Pass "Stage 3.5.10 is a pure external acceptance/regression closure declaration"

Write-Host "`n[12] Final Stage-3.5 authority matrix"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.execution_dispatch_contract_is_dispatch -ne $false) { Fail "Final matrix: Stage-3.5.1 contract became dispatch" }
if ($finalHealth.dispatch_eligibility_is_execution_authorization -ne $false) { Fail "Final matrix: Stage-3.5.2 eligibility became authorization" }
if ($finalHealth.pre_dispatch_governance_allow_grants_execution_authorization -ne $true -or $finalHealth.pre_dispatch_governance_authorization_is_dispatch -ne $false) { Fail "Final matrix: Stage-3.5.3 authorization boundary drifted" }
if ($finalHealth.execution_attempt_target_delivery_performed -ne $false) { Fail "Final matrix: Stage-3.5.4 commit became target delivery" }
if ($finalHealth.execution_delivery_target_action_dispatch_performed -ne $true -or $finalHealth.execution_delivery_target_actuation -ne $false) { Fail "Final matrix: Stage-3.5.5 target-dispatch boundary drifted" }
if ($finalHealth.running_execution_projection_is_observation_not_execution_authority -ne $true) { Fail "Final matrix: Stage-3.5.6 observation became authority" }
if ($finalHealth.execution_result_is_not_task_completion_authority -ne $true) { Fail "Final matrix: Stage-3.5.7 result became completion authority" }
if ($finalHealth.execution_outcome_success_does_not_imply_mission_completion -ne $true) { Fail "Final matrix: successful execution became Mission completion" }
if ($finalHealth.execution_replay_is_execution -ne $false -or $finalHealth.execution_recovery_is_dispatch -ne $false -or $finalHealth.execution_recovery_is_runtime_resumption -ne $false) { Fail "Final matrix: Stage-3.5.9 replay/recovery became execution/dispatch/resumption" }
if ($finalHealth.stage3_5_execution_acceptance_gate_closure_gate_is_execution -ne $false) { Fail "Final matrix: Stage-3.5.10 closure gate became execution" }
Pass "Stage 3.5 closes with one explicit authorization source, one target-dispatch boundary, bounded runtime I/O, and non-actuating recovery"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.5.10 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version          : $($finalHealth.control_version)"
Write-Host "Repository Migration     : $($finalHealth.mission_repository_migration_level)"
Write-Host "Stage-3.5 Baseline       : $($finalHealth.stage3_5_execution_acceptance_gate_baseline)"
Write-Host "Governance Authority     : $($finalHealth.governance_authorization_authority)"
Write-Host "Target Dispatch Boundary : Stage 3.5.5 ($($finalHealth.execution_delivery_target_action_dispatch_performed))"
Write-Host "Target Actuation Claim   : $($finalHealth.execution_delivery_target_actuation)"
Write-Host "Replay Read Only         : $($finalHealth.execution_replay_read_only)"
Write-Host "Recovery Resumption      : $($finalHealth.execution_recovery_is_runtime_resumption)"
Write-Host "Canonical Test Inventory : $expectedTestCount"
Write-Host "Focused Stage-3.5.10     : $expectedFocusedCount"
Write-Host "=============================================================================="
exit 0
