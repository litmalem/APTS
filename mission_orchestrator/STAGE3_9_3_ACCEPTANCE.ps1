param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780'
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Reason) {
    Write-Host "STAGE 3.9.3 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red
    exit 1
}
function Pass([string]$Reason) {
    Write-Host "[PASS] $Reason" -ForegroundColor Green
}

Set-Location $PSScriptRoot

$ExpectedControl = 'stage3.9.3-planning-task-graph-dependency-verification'
$PredecessorControl = 'stage3.9.2-intake-lifecycle-e2e-segment-qualification'
$ExpectedSchema = 'apts-stage3.9-planning-task-graph-dependency-qualification-v1'
$ExpectedMigration = 53
$ExpectedInventory = 1473
$ExpectedFocused = 15
$RunId = 'host-' + (Get-Date -Format 'yyyyMMddHHmmss')

Write-Host "=============================================================================="
Write-Host "Stage 3.9.3 - Planning -> Task Graph -> Dependency Verification"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"
Write-Host "Qualification Run ID : $RunId"

# [0] Runtime activation / migration / authority boundary
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.status -ne 'ok') { Fail 'runtime health status is not ok' }
if ($health.control_version -ne $ExpectedControl) { Fail "expected $ExpectedControl but observed $($health.control_version)" }
if ($health.mission_repository_migration_level -ne $ExpectedMigration) { Fail 'repository migration must remain 53' }
if ($health.stage3_9_3_planning_task_graph_qualification_schema_version -ne $ExpectedSchema -or
    $health.stage3_9_3_planning_task_graph_qualification_predecessor_control -ne $PredecessorControl -or
    $health.stage3_9_3_planning_task_graph_qualification_task_count -ne 3 -or
    $health.stage3_9_3_planning_task_graph_qualification_edge_count -ne 2 -or
    $health.stage3_9_3_planning_task_graph_qualification_graph_status -ne 'PASS') {
    Fail 'Stage 3.9.3 health contract mismatch'
}
if ($health.stage3_9_3_planning_task_graph_qualification_runtime_verifier_read_only -ne $true) {
    Fail 'Stage 3.9.3 verifier must remain read-only'
}
foreach ($field in @(
    'stage3_9_3_planning_task_graph_qualification_new_planner_authority_added',
    'stage3_9_3_planning_task_graph_qualification_new_governance_authority_added',
    'stage3_9_3_planning_task_graph_qualification_new_routing_authority_added',
    'stage3_9_3_planning_task_graph_qualification_new_delegation_authority_added',
    'stage3_9_3_planning_task_graph_qualification_new_dispatch_authority_added',
    'stage3_9_3_planning_task_graph_qualification_new_execution_authority_added',
    'stage3_9_3_planning_task_graph_qualification_new_target_actuation_authority_added',
    'stage3_9_3_planning_task_graph_qualification_new_external_network_io_added',
    'stage3_9_3_planning_task_graph_qualification_new_telemetry_export_added',
    'stage3_9_3_planning_task_graph_qualification_new_database_migration_added',
    'stage3_9_3_planning_task_graph_qualification_new_durable_store_added'
)) {
    if ($health.$field -ne $false) { Fail "boundary field must remain false: $field" }
}
if ($health.supported_controls.Count -lt 3 -or
    $health.supported_controls[-2] -ne $PredecessorControl -or
    $health.supported_controls[-1] -ne $ExpectedControl) {
    Fail 'supported control chain must end with Stage 3.9.2 -> Stage 3.9.3'
}
Pass 'runtime Stage 3.9.3 active with migration 53 and no authority expansion'

# [1] Live canonical E2E segment qualification over public HTTP routes
& python .\run\stage3_9_3_acceptance_client.py --base-url $MissionBaseUrl --run-id $RunId
if ($LASTEXITCODE -ne 0) { Fail 'live Planning -> Task Graph -> Dependency qualification failed' }
Pass 'live Stage 3.9.3 canonical segment QUALIFIED, including exact replay idempotency'

# [2] Python compilation
& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'

# [3] Canonical regression inventory
$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch "(?m)^$ExpectedInventory tests collected") {
    Write-Host $collect.TrimEnd()
    Fail "canonical inventory must contain exactly $ExpectedInventory tests"
}
Pass "$ExpectedInventory tests collected"

# [4] Focused Stage 3.9.3
$focused = (& python -m pytest -q tests/test_stage3_9_3_planning_task_graph_dependency_verification.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch "(?m)^$ExpectedFocused passed") {
    Fail 'focused Stage 3.9.3 regression failed'
}
Pass "$ExpectedFocused/$ExpectedFocused focused Stage 3.9.3 tests"

# [5] Immediate predecessor compatibility
$pred = (& python -m pytest -q tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py 2>&1 | Out-String)
Write-Host $pred.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $pred -notmatch '(?m)^27 passed') { Fail 'Stage 3.9.1/3.9.2 predecessor regression failed' }
Pass '27/27 Stage 3.9.1 + 3.9.2 predecessor tests'

# [6] Planning dependency structural compatibility
$planning = (& python -m pytest -q tests/test_stage3_3_1_canonical_plan_contract_identity.py tests/test_stage3_3_2_planner_input_snapshot_context_binding.py tests/test_stage3_3_3_canonical_task_decomposition_contract.py tests/test_stage3_3_4_task_dependency_graph_structural_validation.py 2>&1 | Out-String)
Write-Host $planning.TrimEnd()
if ($LASTEXITCODE -ne 0) { Fail 'Stage 3.3.1-3.3.4 planning structural regression failed' }
Pass 'Stage 3.3.1-3.3.4 planning structural regression'

# [7] Full historical regression -- authoritative host acceptance
$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch "(?m)^$ExpectedInventory passed") {
    Fail 'full Stage 3.1-3.9.3 regression failed'
}
Pass "$ExpectedInventory-test full regression"

Write-Host "=============================================================================="
Write-Host "STAGE 3.9.3 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "qualified head  : PLANNING(v3), Plan v1, Snapshot v1, 3 tasks, DAG PASS, 2 edges"
Write-Host "next            : Stage 3.9.4 - Routing -> Delegation -> Governance"
Write-Host "=============================================================================="
