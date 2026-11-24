param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.3.3 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Post-Json([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 100 -Compress
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
}

function Get-PostFailure([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 100 -Compress
    try {
        $result = Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
        return @{ status = 200; body = $result }
    } catch {
        $status = $null
        $body = $null
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            try { $body = $_.ErrorDetails.Message | ConvertFrom-Json } catch { $body = $null }
        }
        return @{ status = $status; body = $body }
    }
}

function New-MissionPayload([string]$Token) {
    return @{
        idempotency_key = "stage333-mission-$Token"
        source_system = "STAGE333_ACCEPTANCE"
        created_by = "stage3.3.3-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage333-lab" }
        success_criteria = @(
            @{ metric = "structured_tasks_materialized"; expected = $true },
            @{ metric = "authority_boundary_preserved"; expected = $true }
        )
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-stage333-$Token"
        pip_version = "17"
        metadata = @{ environment = "LAB"; acceptance = "stage3.3.3" }
    }
}

function New-LifecycleCommand([string]$MissionId, [string]$Command, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-stage333-$Token"
        idempotency_key = "idem-lc-stage333-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.3.3-acceptance"
        reason_code = "STAGE333_$Command"
        reason = "Stage 3.3.3 prerequisite command $Command"
        evidence_refs = @("evidence:stage333:$Token")
        metadata = @{ acceptance = "stage3.3.3"; token = $Token }
    }
}

function Invoke-Lifecycle([string]$MissionId, [string]$Command, [string]$Token) {
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId $Command $Token)
}

function New-PlanRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        idempotency_key = "stage333-plan-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.3-acceptance"
        reason = "Register Stage-3.3.1 canonical Plan prerequisite"
        metadata = @{ acceptance = "stage3.3.3"; prerequisite = "3.3.1"; key = $Key }
    }
}

function New-SnapshotRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    return @{
        idempotency_key = "stage333-snapshot-$Key"
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.3-acceptance"
        reason = "Freeze Stage-3.3.2 canonical planner input prerequisite"
        metadata = @{ acceptance = "stage3.3.3"; prerequisite = "3.3.2"; key = $Key }
    }
}

function New-DecompositionRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    $snapshot = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/planner-input-snapshot"
    return @{
        idempotency_key = "stage333-decomposition-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_snapshot_id = $snapshot.snapshot_id
        expected_snapshot_version = [int]$snapshot.snapshot_version
        expected_snapshot_sha256 = $snapshot.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.3-acceptance"
        reason = "Materialize canonical structured planned tasks without graph or dispatch"
        tasks = @(
            @{
                task_key = "collect-cti"
                task_type = "CTI_COLLECTION"
                objective = @{ goal = "Collect relevant canonical CTI context" }
                required_capability = "cti.read.context"
                required_subsystem = "CTI"
                preconditions = @(@{ kind = "PIP_BOUND"; required = $true })
                expected_outputs = @(@{ artifact = "cti_context"; format = "STRUCTURED" })
                success_criteria = @(@{ metric = "cti_context_available"; expected = $true })
                evidence_requirements = @(@{ type = "SOURCE_PROVENANCE" })
                priority = 10
                metadata = @{ acceptance = "stage3.3.3"; sequence_hint = 1 }
            },
            @{
                task_key = "analyze-cti"
                task_type = "CTI_ANALYSIS"
                objective = @{ goal = "Analyze CTI context for mission planning" }
                required_capability = "cti.analyze.context"
                required_subsystem = "CTI"
                preconditions = @()
                expected_outputs = @(@{ artifact = "cti_analysis"; format = "STRUCTURED" })
                success_criteria = @(@{ metric = "analysis_complete"; expected = $true })
                evidence_requirements = @(@{ type = "ANALYSIS_PROVENANCE" })
                priority = 20
                metadata = @{ acceptance = "stage3.3.3"; sequence_hint = 2 }
            }
        )
        metadata = @{ acceptance = "stage3.3.3"; key = $Key }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.3.3 - Canonical Task Decomposition Contract Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[1] Python compile + full regression"
Push-Location $PSScriptRoot
try {
    & python -m compileall -q mission_orchestrator tests
    if ($LASTEXITCODE -ne 0) { Fail "Python compile gate failed" }
    $pytestOutput = & python -m pytest -q 2>&1
    $pytestExit = $LASTEXITCODE
    $pytestOutput | ForEach-Object { Write-Host $_ }
    if ($pytestExit -ne 0) { Fail "Full Stage-3 regression failed" }
    $joined = ($pytestOutput -join "`n")
    if ($joined -notmatch "315 passed") { Fail "Expected Stage-3.3.3 regression baseline of 315 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.3.3 regression baseline: 315 passed"

Write-Host "`n[2] Health / task-decomposition contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.3.3-canonical-task-decomposition-contract") { Fail "Stage 3.3.3 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 11) { Fail "Repository migration level is not 11" }
if ($health.task_decomposition_schema_version -ne "apts-canonical-task-decomposition-v1") { Fail "Task-decomposition schema mismatch" }
if ($health.planned_task_schema_version -ne "apts-canonical-planned-task-v1") { Fail "Planned-task schema mismatch" }
if ($health.task_decomposition_creation_state_required -ne "PLANNING") { Fail "Task decomposition creation state is not PLANNING" }
if ($health.task_decomposition_requires_stage3_3_1_plan_contract -ne $true) { Fail "Stage-3.3.1 Plan prerequisite is not enforced" }
if ($health.task_decomposition_requires_stage3_3_2_planner_input_snapshot -ne $true) { Fail "Stage-3.3.2 snapshot prerequisite is not enforced" }
if ($health.task_decomposition_planner_invocation_performed -ne $false) { Fail "Planner invocation was unexpectedly enabled" }
if ($health.task_decomposition_dependency_graph_materialized -ne $false) { Fail "Stage-3.3.4 dependency graph was prematurely materialized" }
if ($health.task_decomposition_governance_query_performed -ne $false) { Fail "Governance query was unexpectedly performed" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.3.3 contract active; migration=11; planner/graph/Governance/execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Contract discovery + Stage-3.3.1/3.3.2 prerequisites"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload $token)
$missionId = $mission.canonical_identity.mission_id
$definition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-decomposition-definition"
if ($definition.task_decomposition_definition.schema_version -ne "apts-canonical-task-decomposition-v1") { Fail "Task-decomposition definition is not discoverable" }
if ($definition.task_decomposition_definition.dependency_fields_allowed -ne $false) { Fail "Dependency fields were prematurely enabled" }
if ($definition.plan_registered -ne $false -or $definition.snapshot_registered -ne $false -or $definition.decomposition_registered -ne $false) { Fail "New Mission unexpectedly contains Stage-3.3 artifacts" }

$bind = Invoke-Lifecycle $missionId "BIND_PIP" "bind-$token"
$planning = Invoke-Lifecycle $missionId "START_PLANNING" "planning-$token"
if ($bind.mission_state.state -ne "PIP_BOUND" -or $planning.mission_state.state -ne "PLANNING") { Fail "Mission did not reach PLANNING" }
$plan = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-contract" (New-PlanRequest $missionId $token)
$snapshot = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot" (New-SnapshotRequest $missionId $token)
if ($plan.plan_id -notlike "mplan-*") { Fail "Canonical Plan identity is invalid" }
if ($snapshot.snapshot_id -notlike "mpis-*") { Fail "Planner-input snapshot identity is invalid" }
if ($snapshot.planner_input_snapshot.semantics.planner_input_ready -ne $true) { Fail "Snapshot is not planner-input ready" }
Pass "Stage-3.3.1 Plan and Stage-3.3.2 exact planner-input snapshot prerequisites PASS"

Write-Host "`n[4] Canonical task materialization + immutable bindings"
$planBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract"
$snapshotBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot"
$decompRequest = New-DecompositionRequest $missionId $token
$decomp = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-decomposition" $decompRequest
if ($decomp.decomposition_id -notlike "mdecomp-*") { Fail "Canonical decomposition identity is invalid" }
if ([int]$decomp.decomposition_version -ne 1) { Fail "Initial decomposition version is not 1" }
if ([int]$decomp.task_count -ne 2) { Fail "Expected exactly two canonical planned tasks" }
if ($decomp.task_decomposition.task_set.materialization_status -ne "TASKS_MATERIALIZED") { Fail "Task set was not materialized" }
if ($decomp.task_decomposition.task_set.dependency_graph_status -ne "NOT_MATERIALIZED") { Fail "Dependency graph was prematurely materialized" }
if ([int]$decomp.task_decomposition.task_set.dependency_edge_count -ne 0) { Fail "Stage 3.3.3 created dependency edges" }
if ($decomp.task_decomposition.semantics.planner_invocation_performed -ne $false) { Fail "Task decomposition invoked a planner" }
if ($decomp.task_decomposition.semantics.task_is_dispatch -ne $false) { Fail "Planned task was treated as dispatch" }
if ($decomp.task_decomposition.semantics.decomposition_is_authorization -ne $false) { Fail "Decomposition was treated as authorization" }
foreach ($task in @($decomp.task_decomposition.task_set.tasks)) {
    if ($task.identity.planned_task_id -notlike "ptask-*") { Fail "Planned-task identity is invalid" }
    if ($task.dependency_binding.status -ne "NOT_MATERIALIZED") { Fail "Planned task contains a materialized dependency graph" }
    if (@($task.dependency_binding.dependencies).Count -ne 0) { Fail "Planned task contains dependency edges" }
    if ($task.semantics.task_status -ne "DEFINED") { Fail "Planned task initial status is not DEFINED" }
    if ($task.semantics.task_is_dispatch -ne $false -or $task.semantics.task_is_authorization -ne $false) { Fail "Planned task crossed authority/dispatch boundary" }
}
$planAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract"
$snapshotAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot"
if ($planAfter.canonical_sha256 -ne $planBefore.canonical_sha256) { Fail "Stage 3.3.3 mutated the immutable canonical Plan" }
if ($snapshotAfter.canonical_sha256 -ne $snapshotBefore.canonical_sha256) { Fail "Stage 3.3.3 mutated the immutable planner-input snapshot" }
if ($planAfter.plan_contract.task_graph.status -ne "NOT_MATERIALIZED" -or [int]$planAfter.plan_contract.task_graph.task_count -ne 0) { Fail "Stage 3.3.3 mutated Stage-3.3.1 Plan task graph" }
Pass "Canonical mdecomp/ptask contracts materialized while Plan/snapshot and Stage-3.3.4 graph boundary remain immutable"

Write-Host "`n[5] Planned-task read model + version vector"
$tasks = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planned-tasks"
if ([int]$tasks.task_count -ne 2) { Fail "Planned-task read model count mismatch" }
$taskIds = @($tasks.planned_tasks | ForEach-Object { $_.planned_task_id })
if ($taskIds.Count -ne 2 -or $taskIds[0] -notlike "ptask-*" -or $taskIds[1] -notlike "ptask-*") { Fail "Planned-task read model identity mismatch" }
$oneTask = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planned-tasks/$($taskIds[0])"
if ($oneTask.decomposition_id -ne $decomp.decomposition_id -or $oneTask.task_status -ne "DEFINED") { Fail "Single planned-task read model binding mismatch" }
$vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$vector.version_vector.versions.mission_plan_version -ne 1 -or [int]$vector.version_vector.versions.planner_input_snapshot_version -ne 1 -or [int]$vector.version_vector.versions.task_decomposition_version -ne 1) { Fail "Planning version vector domains are not 1/1/1" }
if ([int]$vector.version_vector.local_revisions.routing_task_count -ne 0) { Fail "Stage 3.3.3 created routed/dispatch tasks" }
Pass "Planned-task read model and task_decomposition_version=1 PASS; routed task count remains zero"

Write-Host "`n[6] Exact idempotent replay + event cardinality"
$eventsBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-decomposition" $decompRequest
$eventsAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($replay.idempotent_replay -ne $true) { Fail "Exact decomposition replay was not idempotent" }
if ($replay.decomposition_id -ne $decomp.decomposition_id -or $replay.canonical_sha256 -ne $decomp.canonical_sha256) { Fail "Exact replay changed decomposition identity/hash" }
if ([int]$eventsAfter.event_count -ne [int]$eventsBefore.event_count) { Fail "Exact replay created a duplicate Mission event" }
$registeredEvents = @($eventsAfter.events | Where-Object { $_.event_type -eq "MISSION_TASK_DECOMPOSITION_REGISTERED" })
if ($registeredEvents.Count -ne 1) { Fail "Expected exactly one MISSION_TASK_DECOMPOSITION_REGISTERED event" }
Pass "Exact replay is side-effect free and canonical registration event cardinality is one"

Write-Host "`n[7] Stage-3.3.4-or-later fields fail closed"
$invalid = New-DecompositionRequest $missionId "invalid-$token"
$invalid.tasks[1]["dependencies"] = @("collect-cti")
$invalid.idempotency_key = "stage333-invalid-dependency-$token"
$invalidFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/task-decomposition" $invalid
if ([int]$invalidFailure.status -ne 400 -or $invalidFailure.body.code -ne "MISSION_CONTRACT_INVALID") { Fail "Dependency-bearing Stage-3.3.3 task did not fail closed as canonical contract validation error" }
Pass "Dependency/tool/authorization/dispatch boundary remains closed until later stages"

Write-Host "`n[8] Event lineage + durable repository integrity"
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repository.integrity_status -ne "PASS") { Fail "Repository integrity did not PASS" }
if ([int]$repository.repository.migration_level -ne 11) { Fail "Repository projection migration level is not 11" }
if ([int]$repository.record_counts.mission_task_decompositions -ne 1) { Fail "Task-decomposition store count mismatch" }
if ([int]$repository.record_counts.mission_planned_tasks -ne 2) { Fail "Planned-task store count mismatch" }
if ($repository.persistence_manifest.task_decomposition_store.decomposition_id -ne $decomp.decomposition_id) { Fail "Persistence manifest decomposition binding mismatch" }
if (@($repository.persistence_manifest.planned_task_store).Count -ne 2) { Fail "Persistence manifest planned-task cardinality mismatch" }
if ($repository.persistence_manifest.integrity.canonical_sha256.Length -ne 64) { Fail "Persistence manifest canonical hash missing" }
Pass "Canonical event lineage, task stores, persistence manifest, and repository integrity PASS"

Write-Host "`n[9] Final Stage-3.3.3 invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.3.3-canonical-task-decomposition-contract") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 11) { Fail "Final migration level drifted" }
if ($finalHealth.task_decomposition_planner_invocation_performed -ne $false) { Fail "Final planner-invocation boundary drifted" }
if ($finalHealth.task_decomposition_dependency_graph_materialized -ne $false) { Fail "Final dependency-graph boundary drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Final Governance authority drifted" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Final target execution boundary drifted" }
Pass "TASK != DISPATCH, DECOMPOSITION != AUTHORIZATION, PLANNER != GOVERNANCE; Stage 3.3.4 remains unopened"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.3.3 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Mission             : $missionId"
Write-Host "Plan                : $($plan.plan_id)"
Write-Host "Planner Snapshot    : $($snapshot.snapshot_id)"
Write-Host "Task Decomposition  : $($decomp.decomposition_id)"
Write-Host "Planned Tasks       : $($tasks.task_count)"
Write-Host "Regression Baseline : 315 passed"
Write-Host "Repository SHA256   : $($repository.repository_sha256)"
Write-Host "Target Dispatch     : $($finalHealth.target_action_dispatch_enabled)"
Write-Host "=============================================================================="
exit 0
