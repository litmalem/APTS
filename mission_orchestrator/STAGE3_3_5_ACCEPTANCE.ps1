param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.3.5 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        idempotency_key = "stage335-mission-$Token"
        source_system = "STAGE335_ACCEPTANCE"
        created_by = "stage3.3.5-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage335-lab" }
        success_criteria = @(
            @{ metric = "dependency_graph_validated"; expected = $true },
            @{ metric = "authority_boundary_preserved"; expected = $true }
        )
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-stage335-$Token"
        pip_version = "18"
        metadata = @{ environment = "LAB"; acceptance = "stage3.3.5" }
    }
}

function New-LifecycleCommand([string]$MissionId, [string]$Command, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-stage335-$Token"
        idempotency_key = "idem-lc-stage335-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.3.5-acceptance"
        reason_code = "STAGE335_$Command"
        reason = "Stage 3.3.5 prerequisite command $Command"
        evidence_refs = @("evidence:stage335:$Token")
        metadata = @{ acceptance = "stage3.3.5"; token = $Token }
    }
}

function Invoke-Lifecycle([string]$MissionId, [string]$Command, [string]$Token) {
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId $Command $Token)
}

function New-PlanRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        idempotency_key = "stage335-plan-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.5-acceptance"
        reason = "Register Stage-3.3.1 canonical Plan prerequisite"
        metadata = @{ acceptance = "stage3.3.5"; prerequisite = "3.3.1"; key = $Key }
    }
}

function New-SnapshotRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    return @{
        idempotency_key = "stage335-snapshot-$Key"
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.5-acceptance"
        reason = "Freeze Stage-3.3.2 planner input prerequisite"
        metadata = @{ acceptance = "stage3.3.5"; prerequisite = "3.3.2"; key = $Key }
    }
}

function New-DecompositionRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    $snapshot = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/planner-input-snapshot"
    return @{
        idempotency_key = "stage335-decomposition-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_snapshot_id = $snapshot.snapshot_id
        expected_snapshot_version = [int]$snapshot.snapshot_version
        expected_snapshot_sha256 = $snapshot.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.5-acceptance"
        reason = "Materialize Stage-3.3.3 canonical planned tasks before dependency graph"
        tasks = @(
            @{
                task_key = "collect-cti"
                task_type = "CTI_COLLECTION"
                objective = @{ goal = "Collect canonical CTI context" }
                required_capability = "cti.read.context"
                required_subsystem = "CTI"
                preconditions = @()
                expected_outputs = @(@{ artifact = "cti_context"; format = "STRUCTURED" })
                success_criteria = @(@{ metric = "cti_context_available"; expected = $true })
                evidence_requirements = @(@{ type = "SOURCE_PROVENANCE" })
                priority = 10
                metadata = @{ acceptance = "stage3.3.5"; sequence_hint = 1 }
            },
            @{
                task_key = "analyze-cti"
                task_type = "CTI_ANALYSIS"
                objective = @{ goal = "Analyze canonical CTI context" }
                required_capability = "cti.analyze.context"
                required_subsystem = "CTI"
                preconditions = @()
                expected_outputs = @(@{ artifact = "cti_analysis"; format = "STRUCTURED" })
                success_criteria = @(@{ metric = "analysis_complete"; expected = $true })
                evidence_requirements = @(@{ type = "ANALYSIS_PROVENANCE" })
                priority = 20
                metadata = @{ acceptance = "stage3.3.5"; sequence_hint = 2 }
            }
        )
        metadata = @{ acceptance = "stage3.3.5"; key = $Key }
    }
}

function New-GraphRequest([string]$MissionId, [string]$Key, $Edges = $null) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    $snapshot = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/planner-input-snapshot"
    $decomp = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/task-decomposition"
    if ($null -eq $Edges) {
        $Edges = @(@{ from_task_key = "collect-cti"; to_task_key = "analyze-cti" })
    }
    return @{
        idempotency_key = "stage335-graph-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_snapshot_id = $snapshot.snapshot_id
        expected_snapshot_version = [int]$snapshot.snapshot_version
        expected_snapshot_sha256 = $snapshot.canonical_sha256
        expected_decomposition_id = $decomp.decomposition_id
        expected_decomposition_version = [int]$decomp.decomposition_version
        expected_decomposition_sha256 = $decomp.canonical_sha256
        expected_task_set_sha256 = $decomp.task_set_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.5-acceptance"
        reason = "Materialize deterministic task dependency DAG only"
        edges = $Edges
        metadata = @{ acceptance = "stage3.3.5"; key = $Key }
    }
}

function New-PreparedMission([string]$Key) {
    $mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload $Key)
    $missionId = $mission.canonical_identity.mission_id
    $null = Invoke-Lifecycle $missionId "BIND_PIP" "bind-$Key"
    $planning = Invoke-Lifecycle $missionId "START_PLANNING" "planning-$Key"
    if ($planning.mission_state.state -ne "PLANNING") { Fail "Prepared Mission did not reach PLANNING" }
    $plan = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-contract" (New-PlanRequest $missionId $Key)
    $snapshot = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot" (New-SnapshotRequest $missionId $Key)
    $decomp = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-decomposition" (New-DecompositionRequest $missionId $Key)
    return @{ mission_id = $missionId; plan = $plan; snapshot = $snapshot; decomposition = $decomp }
}


function New-PlannerRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    $snapshot = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/planner-input-snapshot"
    $decomp = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/task-decomposition"
    $graph = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/task-dependency-graph"
    return @{
        idempotency_key = "stage335-planner-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_snapshot_id = $snapshot.snapshot_id
        expected_snapshot_version = [int]$snapshot.snapshot_version
        expected_snapshot_sha256 = $snapshot.canonical_sha256
        expected_decomposition_id = $decomp.decomposition_id
        expected_decomposition_version = [int]$decomp.decomposition_version
        expected_decomposition_sha256 = $decomp.canonical_sha256
        expected_task_set_sha256 = $decomp.task_set_sha256
        expected_graph_id = $graph.graph_id
        expected_graph_version = [int]$graph.graph_version
        expected_graph_sha256 = $graph.canonical_sha256
        expected_node_set_sha256 = $graph.node_set_sha256
        expected_edge_set_sha256 = $graph.edge_set_sha256
        expected_state_version = [int]$state.mission_state.state_version
        planner_profile = "CANONICAL_DAG_STRUCTURAL_PLANNER_V1"
        created_by = "stage3.3.5-acceptance"
        reason = "Invoke Stage-3.3.5 local deterministic graph planner"
        metadata = @{ acceptance = "stage3.3.5"; key = $Key }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.3.5 - Planner Invocation & Plan Generation Acceptance"
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
    if ($joined -notmatch "381 passed") { Fail "Expected Stage-3.3.5 regression baseline of 381 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.3.5 regression baseline: 381 passed"

Write-Host "`n[2] Health / planner-generation contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.3.5-planner-invocation-plan-generation") { Fail "Stage 3.3.5 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 13) { Fail "Repository migration level is not 13" }
if ($health.planner_generation_invocation_schema_version -ne "apts-planner-invocation-v1") { Fail "Planner invocation schema mismatch" }
if ($health.planner_generation_generated_plan_schema_version -ne "apts-generated-mission-plan-v1") { Fail "Generated-plan schema mismatch" }
if ($health.planner_generation_planner_engine -ne "APTS_MO_LOCAL_DETERMINISTIC_GRAPH_PLANNER") { Fail "Planner engine mismatch" }
if ($health.planner_generation_planner_invocation_performed -ne $true -or $health.planner_generation_plan_generation_performed -ne $true) { Fail "Stage 3.3.5 planner/generation capability is not active" }
if ($health.planner_generation_external_model_invocation_performed -ne $false -or $health.planner_generation_external_network_io_performed -ne $false) { Fail "Stage 3.3.5 unexpectedly invokes an external model/network planner" }
if ($health.planner_generation_feasibility_validation_performed -ne $false) { Fail "Stage 3.3.6 feasibility validation was prematurely enabled" }
if ($health.planner_generation_readiness_projection_performed -ne $false -or $health.planner_generation_scheduling_performed -ne $false) { Fail "Stage 3.3.8 readiness/scheduling was prematurely enabled" }
if ($health.planner_generation_governance_query_performed -ne $false) { Fail "Planner unexpectedly queried Governance authorization" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.planner_generation_target_action_dispatch_enabled -ne $false -or $health.planner_generation_target_actuation -ne $false) { Fail "Planner expanded target execution authority" }
Pass "Stage 3.3.5 active; migration=13; planner enabled while feasibility/readiness/Governance/execution boundaries remain preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Stage-3.3.1 through 3.3.4 prerequisites + planner discovery"
$prepared = New-PreparedMission "main-$token"
$missionId = $prepared.mission_id
$graphRequest = New-GraphRequest $missionId "main-$token"
$graph = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph" $graphRequest
if ($graph.validation_status -ne "PASS") { Fail "Stage-3.3.4 dependency graph prerequisite did not PASS" }
$definition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-generation-definition"
if ($definition.planner_generation_definition.planner_invocation_schema_version -ne "apts-planner-invocation-v1") { Fail "Planner-generation definition discovery failed" }
if ($definition.planner_invoked -ne $false -or $definition.generated_plan_registered -ne $false) { Fail "Planner artifacts existed before invocation" }
if ($definition.graph_validation_status -ne "PASS") { Fail "Planner discovery did not observe validated graph" }
Pass "Canonical Plan + snapshot + decomposition + validated DAG are bound and planner-generation definition is discoverable"

Write-Host "`n[4] Real planner invocation + immutable GENERATED_UNVALIDATED candidate plan"
$planBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract"
$snapshotBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot"
$decompBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-decomposition"
$graphBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph"
$plannerRequest = New-PlannerRequest $missionId "main-$token"
$generated = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-invocation" $plannerRequest
if ($generated.planner_invocation_id -notlike "pinvoke-*") { Fail "Planner invocation identity is invalid" }
if ($generated.generated_plan_id -notlike "pgen-*") { Fail "Generated-plan identity is invalid" }
if ([int]$generated.generation_version -ne 1) { Fail "Planner generation version is not 1" }
if ($generated.planner_profile -ne "CANONICAL_DAG_STRUCTURAL_PLANNER_V1") { Fail "Planner profile mismatch" }
if ($generated.planner_engine -ne "APTS_MO_LOCAL_DETERMINISTIC_GRAPH_PLANNER") { Fail "Planner engine mismatch" }
if ($generated.generated_plan_status -ne "GENERATED_UNVALIDATED") { Fail "Generated candidate status mismatch" }
if ([int]$generated.task_count -ne 2 -or [int]$generated.dependency_edge_count -ne 1 -or [int]$generated.planning_layer_count -ne 2) { Fail "Generated candidate cardinality/layering mismatch" }
$ordered = @($generated.generated_plan.generated_plan.ordered_task_keys)
if ($ordered.Count -ne 2 -or $ordered[0] -ne "collect-cti" -or $ordered[1] -ne "analyze-cti") { Fail "Generated topological task order mismatch" }
if ($generated.feasibility_validation_performed -ne $false -or $generated.readiness_projection_performed -ne $false -or $generated.scheduling_performed -ne $false) { Fail "Planner crossed a later-stage planning boundary" }
if ($generated.governance_authorization_query_performed -ne $false -or $generated.target_action_dispatch_enabled -ne $false -or $generated.target_actuation -ne $false) { Fail "Planner crossed Governance/execution authority boundary" }
$planAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract"
$snapshotAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot"
$decompAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-decomposition"
$graphAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph"
if ($planAfter.canonical_sha256 -ne $planBefore.canonical_sha256 -or $snapshotAfter.canonical_sha256 -ne $snapshotBefore.canonical_sha256 -or $decompAfter.canonical_sha256 -ne $decompBefore.canonical_sha256 -or $graphAfter.canonical_sha256 -ne $graphBefore.canonical_sha256) { Fail "Planner invocation mutated a prior canonical planning artifact" }
Pass "Local deterministic planner invoked; immutable candidate plan generated; prior canonical artifacts unchanged"

Write-Host "`n[5] Planner replay + version vector + event lineage"
$eventsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-invocation" $plannerRequest
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($replay.idempotent_replay -ne $true -or $replay.planner_invocation_id -ne $generated.planner_invocation_id -or $replay.generated_plan_id -ne $generated.generated_plan_id) { Fail "Exact planner replay was not idempotent" }
if ([int]$eventsAfterReplay.event_count -ne [int]$eventsBeforeReplay.event_count) { Fail "Exact planner replay created duplicate Mission events" }
$invokedEvents = @($eventsAfterReplay.events | Where-Object { $_.event_type -eq "MISSION_PLANNER_INVOKED" })
$generatedEvents = @($eventsAfterReplay.events | Where-Object { $_.event_type -eq "MISSION_PLAN_GENERATED" })
if ($invokedEvents.Count -ne 1 -or $generatedEvents.Count -ne 1) { Fail "Planner event lineage is not exactly-once" }
$vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$vector.version_vector.versions.mission_plan_version -ne 1 -or [int]$vector.version_vector.versions.planner_input_snapshot_version -ne 1 -or [int]$vector.version_vector.versions.task_decomposition_version -ne 1 -or [int]$vector.version_vector.versions.task_dependency_graph_version -ne 1 -or [int]$vector.version_vector.versions.planner_generation_version -ne 1) { Fail "Stage-3.3 planning version domains are not 1/1/1/1/1" }
Pass "Planner replay is side-effect-free; planner_generation_version=1; exactly-once planning events PASS"

Write-Host "`n[6] Generated-plan read model + durable repository integrity"
$invocationRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-invocation"
$generatedRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/generated-plan"
if ($invocationRead.planner_invocation_sha256 -ne $generated.planner_invocation_sha256) { Fail "Planner-invocation read model hash mismatch" }
if ($generatedRead.canonical_sha256 -ne $generated.generated_plan_sha256) { Fail "Generated-plan read model hash mismatch" }
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repository.integrity_status -ne "PASS") { Fail "Repository integrity did not PASS" }
if ([int]$repository.repository.migration_level -ne 13) { Fail "Repository projection migration level is not 13" }
if ([int]$repository.record_counts.mission_planner_invocations -ne 1 -or [int]$repository.record_counts.mission_generated_plans -ne 1) { Fail "Planner-generation store counts mismatch" }
if ($repository.persistence_manifest.planner_invocation_store.planner_invocation_id -ne $generated.planner_invocation_id) { Fail "Persistence manifest planner invocation mismatch" }
if ($repository.persistence_manifest.generated_plan_store.generated_plan_id -ne $generated.generated_plan_id) { Fail "Persistence manifest generated plan mismatch" }
Pass "Planner invocation/generated-plan read models, durable stores, manifest, and repository integrity PASS"

Write-Host "`n[7] Stale binding and caller-supplied planner output fail closed"
$stalePrepared = New-PreparedMission "stale-$token"
$staleMissionId = $stalePrepared.mission_id
$staleGraph = Post-Json "$MissionBaseUrl/api/missions/$staleMissionId/task-dependency-graph" (New-GraphRequest $staleMissionId "stale-$token")
$staleRequest = New-PlannerRequest $staleMissionId "stale-$token"
$staleRequest.expected_graph_sha256 = "0" * 64
$staleFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$staleMissionId/planner-invocation" $staleRequest
if ([int]$staleFailure.status -ne 409 -or $staleFailure.body.code -ne "MISSION_VERSION_CONFLICT") { Fail "Stale graph binding did not fail closed with version conflict" }
$injectedRequest = New-PlannerRequest $staleMissionId "injected-$token"
$injectedRequest.planner_output = @{ status = "caller-supplied" }
$injectedFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$staleMissionId/planner-invocation" $injectedRequest
if ([int]$injectedFailure.status -ne 400 -or $injectedFailure.body.code -ne "MISSION_CONTRACT_INVALID") { Fail "Caller-supplied planner output was not rejected" }
$staleDefinition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleMissionId/planner-generation-definition"
if ($staleDefinition.planner_invoked -ne $false -or $staleDefinition.generated_plan_registered -ne $false) { Fail "Rejected planner requests created persistent artifacts" }
Pass "Stale canonical bindings and caller-supplied planner output fail closed with zero planner persistence"

Write-Host "`n[8] Final Stage-3.3.5 invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.3.5-planner-invocation-plan-generation") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 13) { Fail "Final migration level drifted" }
if ($finalHealth.planner_generation_planner_invocation_performed -ne $true -or $finalHealth.planner_generation_plan_generation_performed -ne $true) { Fail "Final planner capability drifted" }
if ($finalHealth.planner_generation_feasibility_validation_performed -ne $false -or $finalHealth.planner_generation_readiness_projection_performed -ne $false -or $finalHealth.planner_generation_scheduling_performed -ne $false) { Fail "Final later-stage planning boundary drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS" -or $finalHealth.planner_generation_governance_query_performed -ne $false) { Fail "Final Governance authority boundary drifted" }
if ($finalHealth.planner_generation_target_action_dispatch_enabled -ne $false -or $finalHealth.planner_generation_target_actuation -ne $false) { Fail "Final target execution boundary drifted" }
Pass "PLAN != AUTHORIZATION, TASK != DISPATCH, READINESS != PERMISSION, PLANNER != GOVERNANCE"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.3.5 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Mission             : $missionId"
Write-Host "Plan                : $($prepared.plan.plan_id)"
Write-Host "Planner Snapshot    : $($prepared.snapshot.snapshot_id)"
Write-Host "Task Decomposition  : $($prepared.decomposition.decomposition_id)"
Write-Host "Dependency Graph    : $($graph.graph_id)"
Write-Host "Planner Invocation  : $($generated.planner_invocation_id)"
Write-Host "Generated Plan      : $($generated.generated_plan_id)"
Write-Host "Generated Status    : $($generated.generated_plan_status)"
Write-Host "Regression Baseline : 381 passed"
Write-Host "Repository SHA256   : $($repository.repository_sha256)"
Write-Host "Target Dispatch     : $($finalHealth.planner_generation_target_action_dispatch_enabled)"
Write-Host "=============================================================================="
exit 0
