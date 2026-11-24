param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780'
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Reason) {
    Write-Host "STAGE 3.9.1 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red
    exit 1
}

function Pass([string]$Reason) {
    Write-Host "[PASS] $Reason" -ForegroundColor Green
}

Set-Location $PSScriptRoot

$ExpectedControl = 'stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract'
$PredecessorControl = 'stage3.8.10-observe-reconstruct-acceptance-regression-gate'
$ExpectedSchema = 'apts-stage3.9-e2e-mission-acceptance-contract-v1'
$ExpectedScenarioSchema = 'apts-stage3.9-canonical-e2e-mission-scenario-v1'
$ExpectedScenarioId = 'stage3.9-canonical-e2e-control-plane-mission-v1'
$ExpectedMigration = 53
$ExpectedInventory = 1443
$ExpectedFocused = 12
$ExpectedPredecessorFocused = 4

Write-Host "=============================================================================="
Write-Host "Stage 3.9.1 - Canonical E2E Mission Scenario & Acceptance Contract"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

# -----------------------------------------------------------------------------
# [0] Runtime activation and boundary preflight
# -----------------------------------------------------------------------------
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "runtime unavailable: $($_.Exception.Message)"
}

if ($health.status -ne 'ok') {
    Fail "runtime health status is not ok"
}
if ($health.control_version -ne $ExpectedControl) {
    Fail "runtime control not active; expected $ExpectedControl but observed $($health.control_version)"
}
if ($health.mission_repository_migration_level -ne $ExpectedMigration -or
    $health.stage3_9_e2e_mission_acceptance_expected_migration_level -ne $ExpectedMigration) {
    Fail "migration level mismatch; Stage 3.9.1 must remain at repository migration 53"
}
if ($health.stage3_9_e2e_mission_acceptance_schema_version -ne $ExpectedSchema -or
    $health.stage3_9_e2e_mission_scenario_schema_version -ne $ExpectedScenarioSchema -or
    $health.stage3_9_e2e_mission_scenario_id -ne $ExpectedScenarioId) {
    Fail "Stage 3.9.1 schema/scenario identity mismatch"
}
if ($health.stage3_9_e2e_mission_acceptance_declared_only -ne $true -or
    $health.stage3_9_e2e_mission_acceptance_runtime_self_certification -ne $false -or
    $health.stage3_9_e2e_mission_acceptance_external_execution_required -ne $true -or
    $health.stage3_9_e2e_mission_acceptance_runtime_side_effects -ne $false) {
    Fail "Stage 3.9.1 declaration-only acceptance boundary mismatch"
}

foreach ($field in @(
    'stage3_9_e2e_mission_acceptance_new_execution_authority_added',
    'stage3_9_e2e_mission_acceptance_new_governance_authority_added',
    'stage3_9_e2e_mission_acceptance_new_routing_authority_added',
    'stage3_9_e2e_mission_acceptance_new_delegation_authority_added',
    'stage3_9_e2e_mission_acceptance_new_dispatch_authority_added',
    'stage3_9_e2e_mission_acceptance_new_target_actuation_authority_added',
    'stage3_9_e2e_mission_acceptance_new_external_network_io_added',
    'stage3_9_e2e_mission_acceptance_new_telemetry_export_added',
    'stage3_9_e2e_mission_acceptance_new_database_migration_added',
    'stage3_9_e2e_mission_acceptance_new_durable_store_added'
)) {
    if ($health.$field -ne $false) {
        Fail "authority/boundary field must remain false: $field"
    }
}

if ($health.supported_controls.Count -lt 2 -or
    $health.supported_controls[-2] -ne $PredecessorControl -or
    $health.supported_controls[-1] -ne $ExpectedControl) {
    Fail "supported control chain must end with Stage 3.8.10 -> Stage 3.9.1"
}

$requiredClosures = @(
    'stage3.1.10-acceptance-regression-gate',
    'stage3.2.10-lifecycle-acceptance-regression-gate',
    'stage3.3.10-planning-acceptance-regression-gate',
    'stage3.4.10-routing-delegation-acceptance-regression-gate',
    'stage3.5.10-execution-dispatch-acceptance-regression-gate',
    'stage3.6.10-outcome-acceptance-regression-gate',
    'stage3.7.10-adapt-replan-acceptance-regression-gate',
    $PredecessorControl
)
if ($health.stage3_9_e2e_mission_acceptance_required_stage_closure_controls.Count -ne $requiredClosures.Count) {
    Fail "required Stage 3.1-3.8 closure-control count mismatch"
}
for ($i = 0; $i -lt $requiredClosures.Count; $i++) {
    if ($health.stage3_9_e2e_mission_acceptance_required_stage_closure_controls[$i] -ne $requiredClosures[$i]) {
        Fail "required closure control mismatch at index $i"
    }
}

if ($health.stage3_9_e2e_mission_acceptance_phases.Count -ne 10 -or
    $health.stage3_9_e2e_mission_acceptance_phases[0].stage -ne '3.9.1' -or
    $health.stage3_9_e2e_mission_acceptance_phases[9].stage -ne '3.9.10') {
    Fail "Stage 3.9 acceptance phase map is incomplete"
}
if ($health.stage3_9_e2e_mission_acceptance_required_identity_families.Count -lt 20) {
    Fail "cross-stage identity-family contract is incomplete"
}
if ($health.stage3_9_e2e_mission_acceptance_invariants.Count -lt 10 -or
    $health.stage3_9_e2e_mission_acceptance_success_criteria.Count -lt 5 -or
    $health.stage3_9_e2e_mission_acceptance_failure_criteria.Count -lt 5) {
    Fail "acceptance invariant/success/failure contract is incomplete"
}
Pass "runtime Stage 3.9.1 contract active with predecessor and no authority expansion"

# -----------------------------------------------------------------------------
# [1] Canonical contract route and deterministic read-only projection
# -----------------------------------------------------------------------------
try {
    $contract1 = Invoke-RestMethod "$MissionBaseUrl/api/e2e/mission-scenario-acceptance-contract"
    $contract2 = Invoke-RestMethod "$MissionBaseUrl/api/e2e/mission-scenario-acceptance-contract"
} catch {
    Fail "Stage 3.9.1 contract route unavailable: $($_.Exception.Message)"
}

if ($contract1.status -ne 'completed' -or
    $contract1.control_version -ne $ExpectedControl -or
    $contract1.definition.schema_version -ne $ExpectedSchema -or
    $contract1.definition.scenario_schema_version -ne $ExpectedScenarioSchema -or
    $contract1.definition.scenario_id -ne $ExpectedScenarioId -or
    $contract1.definition.expected_repository_migration_level -ne $ExpectedMigration -or
    $contract1.definition.runtime_side_effects -ne $false -or
    $contract1.definition.new_durable_store_added -ne $false -or
    $contract1.definition.new_database_migration_added -ne $false -or
    $contract1.definition.new_execution_authority_added -ne $false -or
    $contract1.definition.next_stage -ne '3.9.2') {
    Fail "Stage 3.9.1 contract definition mismatch"
}

if ($contract1.contract.schema_version -ne $ExpectedSchema -or
    $contract1.contract.scenario.schema_version -ne $ExpectedScenarioSchema -or
    $contract1.contract.scenario.scenario_id -ne $ExpectedScenarioId -or
    $contract1.contract.stage391_boundary.declared_only -ne $true -or
    $contract1.contract.stage391_boundary.runtime_side_effects -ne $false -or
    $contract1.contract.stage391_boundary.new_execution_authority_added -ne $false -or
    $contract1.contract.scenario.mission_request.metadata.external_target_actuation_allowed -ne $false -or
    $contract1.contract.acceptance_phases.Count -ne 10 -or
    $contract1.contract.required_stage_closure_controls.Count -ne 8) {
    Fail "canonical E2E Mission scenario/acceptance contract mismatch"
}

$hash1 = $contract1.contract.integrity.canonical_sha256
$hash2 = $contract2.contract.integrity.canonical_sha256
if ([string]::IsNullOrWhiteSpace($hash1) -or $hash1.Length -ne 64 -or $hash1 -ne $hash2) {
    Fail "canonical contract digest is missing or non-deterministic"
}
if ($contract1.definition.contract_sha256 -ne $hash1 -or
    $contract2.definition.contract_sha256 -ne $hash2) {
    Fail "definition/contract digest binding mismatch"
}
Pass "canonical E2E scenario contract route is deterministic and read-only"

# -----------------------------------------------------------------------------
# [2] Static compilation and canonical test inventory
# -----------------------------------------------------------------------------
& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) {
    Fail "Python compilation failed"
}
Pass "Python compilation"

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch "(?m)^$ExpectedInventory tests collected") {
    Write-Host $collect.TrimEnd()
    Fail "canonical inventory must contain exactly $ExpectedInventory tests"
}
Pass "$ExpectedInventory tests collected"

# -----------------------------------------------------------------------------
# [3] Full historical regression
# -----------------------------------------------------------------------------
$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch "(?m)^$ExpectedInventory passed") {
    Fail "full Stage 3.1-3.9.1 regression failed"
}
Pass "$ExpectedInventory-test full regression"

# -----------------------------------------------------------------------------
# [4] Focused Stage 3.9.1 and predecessor closure regressions
# -----------------------------------------------------------------------------
$focused = (& python -m pytest -q tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch "(?m)^$ExpectedFocused passed") {
    Fail "focused Stage 3.9.1 regression failed"
}
Pass "$ExpectedFocused focused Stage 3.9.1 tests"

$predecessor = (& python -m pytest -q tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py 2>&1 | Out-String)
Write-Host $predecessor.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $predecessor -notmatch "(?m)^$ExpectedPredecessorFocused passed") {
    Fail "Stage 3.8.10 predecessor closure regression failed"
}
Pass "$ExpectedPredecessorFocused focused Stage 3.8.10 predecessor tests"

Write-Host "=============================================================================="
Write-Host 'STAGE 3.9.1 ACCEPTANCE: PASS' -ForegroundColor Green
Write-Host 'Canonical E2E Mission scenario and acceptance contract are frozen and active.'
Write-Host 'Stage 3.1-3.8 closure gates are explicit prerequisites; Stage 3.9 phases 3.9.1-3.9.10 are frozen.'
Write-Host 'Repository migration level: 53 (unchanged); new durable store: NONE; new migration: NONE.'
Write-Host 'Stage 3.9.1 is declaration-only and adds no Governance, routing, delegation, dispatch, execution, external-I/O, telemetry, or target-actuation authority.'
Write-Host 'Next stage: 3.9.2 - Intake -> Lifecycle E2E segment qualification.'
Write-Host "=============================================================================="
