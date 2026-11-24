param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780'
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Reason) {
    Write-Host "STAGE 3.9.2 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red
    exit 1
}

function Pass([string]$Reason) {
    Write-Host "[PASS] $Reason" -ForegroundColor Green
}

function Post-Json([string]$Uri, $Body) {
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 32 -Compress)
}

Set-Location $PSScriptRoot

$ExpectedControl = 'stage3.9.2-intake-lifecycle-e2e-segment-qualification'
$PredecessorControl = 'stage3.9.1-canonical-e2e-mission-scenario-acceptance-contract'
$ExpectedSchema = 'apts-stage3.9-intake-lifecycle-segment-qualification-v1'
$ExpectedScenarioId = 'stage3.9-canonical-e2e-control-plane-mission-v1'
$ExpectedMigration = 53
$ExpectedInventory = 1458
$ExpectedFocused = 15
$ExpectedPredecessorFocused = 12
$RunId = 'host-' + (Get-Date -Format 'yyyyMMddHHmmss')

Write-Host "=============================================================================="
Write-Host "Stage 3.9.2 - Intake -> Lifecycle E2E Segment Qualification"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"
Write-Host "Qualification Run ID : $RunId"

# -----------------------------------------------------------------------------
# [0] Runtime activation, predecessor, migration and authority boundary
# -----------------------------------------------------------------------------
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "runtime unavailable: $($_.Exception.Message)"
}

if ($health.status -ne 'ok') { Fail 'runtime health status is not ok' }
if ($health.control_version -ne $ExpectedControl) {
    Fail "runtime control not active; expected $ExpectedControl but observed $($health.control_version)"
}
if ($health.mission_repository_migration_level -ne $ExpectedMigration -or
    $health.stage3_9_2_intake_lifecycle_qualification_expected_migration_level -ne $ExpectedMigration) {
    Fail 'Stage 3.9.2 must remain at repository migration level 53'
}
if ($health.stage3_9_2_intake_lifecycle_qualification_schema_version -ne $ExpectedSchema -or
    $health.stage3_9_2_intake_lifecycle_qualification_predecessor_control -ne $PredecessorControl -or
    $health.stage3_9_2_intake_lifecycle_qualification_terminal_state -ne 'PLANNING' -or
    $health.stage3_9_2_intake_lifecycle_qualification_terminal_state_version -ne 3) {
    Fail 'Stage 3.9.2 qualification identity/head mismatch'
}
if ($health.stage3_9_2_intake_lifecycle_qualification_runtime_verifier_read_only -ne $true -or
    $health.stage3_9_2_intake_lifecycle_qualification_external_execution_required -ne $true -or
    $health.stage3_9_2_intake_lifecycle_qualification_existing_public_routes_only -ne $true) {
    Fail 'Stage 3.9.2 execution/verifier boundary mismatch'
}
foreach ($field in @(
    'stage3_9_2_intake_lifecycle_qualification_new_governance_authority_added',
    'stage3_9_2_intake_lifecycle_qualification_new_routing_authority_added',
    'stage3_9_2_intake_lifecycle_qualification_new_delegation_authority_added',
    'stage3_9_2_intake_lifecycle_qualification_new_dispatch_authority_added',
    'stage3_9_2_intake_lifecycle_qualification_new_execution_authority_added',
    'stage3_9_2_intake_lifecycle_qualification_new_target_actuation_authority_added',
    'stage3_9_2_intake_lifecycle_qualification_new_external_network_io_added',
    'stage3_9_2_intake_lifecycle_qualification_new_telemetry_export_added',
    'stage3_9_2_intake_lifecycle_qualification_new_planner_authority_added',
    'stage3_9_2_intake_lifecycle_qualification_new_database_migration_added',
    'stage3_9_2_intake_lifecycle_qualification_new_durable_store_added'
)) {
    if ($health.$field -ne $false) { Fail "authority/boundary field must remain false: $field" }
}
if ($health.supported_controls.Count -lt 2 -or
    $health.supported_controls[-2] -ne $PredecessorControl -or
    $health.supported_controls[-1] -ne $ExpectedControl) {
    Fail 'supported control chain must end with Stage 3.9.1 -> Stage 3.9.2'
}
Pass 'runtime Stage 3.9.2 active with Stage 3.9.1 predecessor and no authority expansion'

# -----------------------------------------------------------------------------
# [1] Frozen qualification contract is deterministic and source-bound to 3.9.1
# -----------------------------------------------------------------------------
try {
    $contract1 = Invoke-RestMethod "$MissionBaseUrl/api/e2e/intake-lifecycle-qualification-contract"
    $contract2 = Invoke-RestMethod "$MissionBaseUrl/api/e2e/intake-lifecycle-qualification-contract"
    $stage391 = Invoke-RestMethod "$MissionBaseUrl/api/e2e/mission-scenario-acceptance-contract"
} catch {
    Fail "E2E qualification contract route unavailable: $($_.Exception.Message)"
}
if ($contract1.status -ne 'completed' -or
    $contract1.control_version -ne $ExpectedControl -or
    $contract1.definition.schema_version -ne $ExpectedSchema -or
    $contract1.definition.predecessor_control -ne $PredecessorControl -or
    $contract1.definition.source_scenario_id -ne $ExpectedScenarioId -or
    $contract1.definition.qualified_segment_head_state -ne 'PLANNING' -or
    $contract1.definition.qualified_segment_head_state_version -ne 3 -or
    $contract1.definition.runtime_verifier_read_only -ne $true -or
    $contract1.definition.next_stage -ne '3.9.3') {
    Fail 'Stage 3.9.2 contract definition mismatch'
}
if ($contract1.contract.source_acceptance_contract_sha256 -ne $stage391.contract.integrity.canonical_sha256) {
    Fail 'Stage 3.9.2 contract is not bound to the frozen Stage 3.9.1 source contract'
}
if ($contract1.contract.integrity.canonical_sha256 -ne $contract2.contract.integrity.canonical_sha256 -or
    $contract1.definition.contract_sha256 -ne $contract1.contract.integrity.canonical_sha256) {
    Fail 'Stage 3.9.2 contract digest is missing or non-deterministic'
}
Pass 'Stage 3.9.2 qualification contract is deterministic and bound to Stage 3.9.1'

# -----------------------------------------------------------------------------
# [2] Execute the frozen Stage 3.9.1 Mission intake via existing public route
# -----------------------------------------------------------------------------
$runToken = $stage391.contract.scenario.run_binding.token
if ([string]::IsNullOrWhiteSpace($runToken)) {
    Fail 'Stage 3.9.1 contract does not expose the canonical run-binding token'
}
$missionRequest = $stage391.contract.scenario.mission_request |
    ConvertTo-Json -Depth 32 |
    ConvertFrom-Json
$missionRequest.idempotency_key = $missionRequest.idempotency_key.Replace($runToken, $RunId)
$missionRequest.metadata.run_id = $RunId


try {
    $created = Post-Json "$MissionBaseUrl/api/missions" $missionRequest
} catch {
    Fail "canonical Mission intake failed: $($_.Exception.Message)"
}
$MissionId = $created.canonical_identity.mission_id
if ($created.status -ne 'registered' -or $created.idempotent_replay -ne $false -or
    [string]::IsNullOrWhiteSpace($MissionId) -or -not $MissionId.StartsWith('mission-gmo-') -or
    -not $created.canonical_identity.envelope_id.StartsWith('menv-')) {
    Fail 'canonical Mission intake identity/registration mismatch'
}
$state0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
if ($state0.mission_state.state -ne 'CREATED' -or $state0.mission_state.state_version -ne 1) {
    Fail 'canonical Mission intake must establish CREATED state version 1'
}
Pass "canonical Mission intake materialized CREATED head ($MissionId)"

# -----------------------------------------------------------------------------
# [3] Existing lifecycle surface: CREATED -> PIP_BOUND -> PLANNING
# -----------------------------------------------------------------------------
$vv0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
$bindRequest = [ordered]@{
    command_id = "stage392-$RunId-bind-pip"
    idempotency_key = "stage392-$RunId-bind-pip"
    command = 'BIND_PIP'
    expected_version_sha256 = $vv0.version_sha256
    expected_state_version = 1
    actor = 'stage3.9.2-acceptance-runner'
    reason_code = 'STAGE392_BIND_PIP'
    reason = 'Stage 3.9.2 canonical E2E segment command BIND_PIP'
    evidence_refs = @("evidence:stage3.9.2:$RunId:bind-pip")
    metadata = [ordered]@{ stage = '3.9.2'; scenario_id = $ExpectedScenarioId; run_id = $RunId; segment = 'INTAKE_TO_LIFECYCLE' }
}
try { $bind = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $bindRequest } catch {
    Fail "BIND_PIP failed: $($_.Exception.Message)"
}
if ($bind.idempotent_replay -ne $false -or
    $bind.lifecycle_command -ne 'BIND_PIP' -or
    $bind.mission_state.state -ne 'PIP_BOUND' -or
    $bind.mission_state.state_version -ne 2 -or
    $bind.mission_activation.activation_ready -ne $true -or
    $bind.mission_activation.execution_authorized -ne $false) {
    Fail 'BIND_PIP qualification result mismatch'
}

$vv1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
$planningRequest = [ordered]@{
    command_id = "stage392-$RunId-start-planning"
    idempotency_key = "stage392-$RunId-start-planning"
    command = 'START_PLANNING'
    expected_version_sha256 = $vv1.version_sha256
    expected_state_version = 2
    actor = 'stage3.9.2-acceptance-runner'
    reason_code = 'STAGE392_START_PLANNING'
    reason = 'Stage 3.9.2 canonical E2E segment command START_PLANNING'
    evidence_refs = @("evidence:stage3.9.2:$RunId:start-planning")
    metadata = [ordered]@{ stage = '3.9.2'; scenario_id = $ExpectedScenarioId; run_id = $RunId; segment = 'INTAKE_TO_LIFECYCLE' }
}
try { $planning = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $planningRequest } catch {
    Fail "START_PLANNING failed: $($_.Exception.Message)"
}
if ($planning.idempotent_replay -ne $false -or
    $planning.lifecycle_command -ne 'START_PLANNING' -or
    $planning.mission_state.state -ne 'PLANNING' -or
    $planning.mission_state.state_version -ne 3 -or
    $planning.planning_run_activation.activation_ready -ne $true -or
    $planning.planning_run_activation.pip_activation_proof.valid -ne $true -or
    $planning.planning_run_activation.planner_invocation_performed -ne $false -or
    $planning.planning_run_activation.plan_artifact_created -ne $false -or
    $planning.planning_run_activation.execution_authorized -ne $false) {
    Fail 'START_PLANNING qualification result mismatch'
}
Pass 'canonical lifecycle segment reached PLANNING state version 3 without planner/execution authority'

# -----------------------------------------------------------------------------
# [4] Read-only runtime verifier: exact lineage, events and repository footprint
# -----------------------------------------------------------------------------
try {
    $proof1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/e2e-intake-lifecycle-qualification"
    $proof2 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/e2e-intake-lifecycle-qualification"
} catch {
    Fail "Stage 3.9.2 qualification proof route unavailable: $($_.Exception.Message)"
}
if ($proof1.read_only -ne $true -or
    $proof1.qualification.status -ne 'QUALIFIED' -or
    $proof1.qualification.qualified -ne $true -or
    $proof1.qualification.failed_check_ids.Count -ne 0 -or
    $proof1.qualification.segment_head.state -ne 'PLANNING' -or
    $proof1.qualification.segment_head.state_version -ne 3 -or
    $proof1.qualification.segment_head.transition_count -ne 2 -or
    $proof1.qualification.segment_head.command_count -ne 2 -or
    $proof1.qualification.segment_head.event_count -ne 5) {
    Fail 'read-only Stage 3.9.2 qualification proof is not QUALIFIED'
}
if (($proof1.qualification | ConvertTo-Json -Depth 32 -Compress) -ne ($proof2.qualification | ConvertTo-Json -Depth 32 -Compress)) {
    Fail 'qualification proof is not deterministic under repeated read'
}
Pass 'runtime verifier proves exact intake/lifecycle lineage and remains read-only'

# -----------------------------------------------------------------------------
# [5] Exact replay idempotency: no duplicate Mission, transition, command or event
# -----------------------------------------------------------------------------
try {
    $createdReplay = Post-Json "$MissionBaseUrl/api/missions" $missionRequest
    $bindReplay = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $bindRequest
    $planningReplay = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $planningRequest
    $proofReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/e2e-intake-lifecycle-qualification"
} catch {
    Fail "exact replay qualification failed: $($_.Exception.Message)"
}
if ($createdReplay.idempotent_replay -ne $true -or
    $createdReplay.canonical_identity.mission_id -ne $MissionId -or
    $bindReplay.idempotent_replay -ne $true -or
    $planningReplay.idempotent_replay -ne $true -or
    $proofReplay.qualification.status -ne 'QUALIFIED' -or
    $proofReplay.qualification.segment_head.transition_count -ne 2 -or
    $proofReplay.qualification.segment_head.command_count -ne 2 -or
    $proofReplay.qualification.segment_head.event_count -ne 5) {
    Fail 'exact replay created duplicate or changed the qualified segment head'
}
Pass 'Mission/lifecycle exact replays are idempotent with no duplicate segment side effects'

# -----------------------------------------------------------------------------
# [6] Static compilation and canonical regression inventory
# -----------------------------------------------------------------------------
& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch "(?m)^$ExpectedInventory tests collected") {
    Write-Host $collect.TrimEnd()
    Fail "canonical inventory must contain exactly $ExpectedInventory tests"
}
Pass "$ExpectedInventory tests collected"

# -----------------------------------------------------------------------------
# [7] Full historical regression
# -----------------------------------------------------------------------------
$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch "(?m)^$ExpectedInventory passed") {
    Fail 'full Stage 3.1-3.9.2 regression failed'
}
Pass "$ExpectedInventory-test full regression"

# -----------------------------------------------------------------------------
# [8] Focused Stage 3.9.2 and predecessor Stage 3.9.1 regressions
# -----------------------------------------------------------------------------
$focused = (& python -m pytest -q tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch "(?m)^$ExpectedFocused passed") {
    Fail 'focused Stage 3.9.2 regression failed'
}
Pass "$ExpectedFocused focused Stage 3.9.2 tests"

$predecessor = (& python -m pytest -q tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py 2>&1 | Out-String)
Write-Host $predecessor.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $predecessor -notmatch "(?m)^$ExpectedPredecessorFocused passed") {
    Fail 'Stage 3.9.1 predecessor regression failed'
}
Pass "$ExpectedPredecessorFocused focused Stage 3.9.1 predecessor tests"

Write-Host "=============================================================================="
Write-Host 'STAGE 3.9.2 ACCEPTANCE: PASS' -ForegroundColor Green
Write-Host 'Canonical Stage 3.9.1 Mission intake has been qualified through CREATED -> PIP_BOUND -> PLANNING.'
Write-Host 'The qualified segment head is PLANNING state version 3; no plan/task artifact has been materialized yet.'
Write-Host 'Exact replay is idempotent: 1 Mission, 2 transitions, 2 commands, 5 Mission events.'
Write-Host 'Repository migration level: 53 (unchanged); new durable store: NONE; new migration: NONE.'
Write-Host 'No new Governance, routing, delegation, dispatch, execution, planner, external-I/O, telemetry, or target-actuation authority was added.'
Write-Host 'Next stage: 3.9.3 - Planning -> Task Graph E2E segment qualification.'
Write-Host "=============================================================================="
