param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.3.4 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        idempotency_key = "stage334-mission-$Token"
        source_system = "STAGE334_ACCEPTANCE"
        created_by = "stage3.3.4-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage334-lab" }
        success_criteria = @(
            @{ metric = "dependency_graph_validated"; expected = $true },
            @{ metric = "authority_boundary_preserved"; expected = $true }
        )
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-stage334-$Token"
        pip_version = "18"
        metadata = @{ environment = "LAB"; acceptance = "stage3.3.4" }
    }
}

function New-LifecycleCommand([string]$MissionId, [string]$Command, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-stage334-$Token"
        idempotency_key = "idem-lc-stage334-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.3.4-acceptance"
        reason_code = "STAGE334_$Command"
        reason = "Stage 3.3.4 prerequisite command $Command"
        evidence_refs = @("evidence:stage334:$Token")
        metadata = @{ acceptance = "stage3.3.4"; token = $Token }
    }
}

function Invoke-Lifecycle([string]$MissionId, [string]$Command, [string]$Token) {
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId $Command $Token)
}

function New-PlanRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        idempotency_key = "stage334-plan-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.4-acceptance"
        reason = "Register Stage-3.3.1 canonical Plan prerequisite"
        metadata = @{ acceptance = "stage3.3.4"; prerequisite = "3.3.1"; key = $Key }
    }
}

function New-SnapshotRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    return @{
        idempotency_key = "stage334-snapshot-$Key"
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.4-acceptance"
        reason = "Freeze Stage-3.3.2 planner input prerequisite"
        metadata = @{ acceptance = "stage3.3.4"; prerequisite = "3.3.2"; key = $Key }
    }
}

function New-DecompositionRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    $snapshot = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/planner-input-snapshot"
    return @{
        idempotency_key = "stage334-decomposition-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_snapshot_id = $snapshot.snapshot_id
        expected_snapshot_version = [int]$snapshot.snapshot_version
        expected_snapshot_sha256 = $snapshot.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.4-acceptance"
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
                metadata = @{ acceptance = "stage3.3.4"; sequence_hint = 1 }
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
                metadata = @{ acceptance = "stage3.3.4"; sequence_hint = 2 }
            }
        )
        metadata = @{ acceptance = "stage3.3.4"; key = $Key }
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
        idempotency_key = "stage334-graph-$Key"
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
        created_by = "stage3.3.4-acceptance"
        reason = "Materialize deterministic task dependency DAG only"
        edges = $Edges
        metadata = @{ acceptance = "stage3.3.4"; key = $Key }
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

Write-Host "=============================================================================="
Write-Host "Stage 3.3.4 - Task Dependency Graph & Structural Validation Acceptance"
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
    if ($joined -notmatch "344 passed") { Fail "Expected Stage-3.3.4 regression baseline of 344 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.3.4 regression baseline: 344 passed"

Write-Host "`n[2] Health / graph contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.3.4-task-dependency-graph-structural-validation") { Fail "Stage 3.3.4 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 12) { Fail "Repository migration level is not 12" }
if ($health.task_dependency_graph_schema_version -ne "apts-canonical-task-dependency-graph-v1") { Fail "Dependency-graph schema mismatch" }
if ($health.task_dependency_edge_schema_version -ne "apts-canonical-task-dependency-edge-v1") { Fail "Dependency-edge schema mismatch" }
if ($health.task_dependency_graph_creation_state_required -ne "PLANNING") { Fail "Graph registration state is not PLANNING" }
if ($health.task_dependency_graph_requires_stage3_3_3_task_decomposition -ne $true) { Fail "Stage-3.3.3 decomposition prerequisite is not enforced" }
if ($health.task_dependency_graph_materialized -ne $true -or $health.task_dependency_graph_dependency_validation_performed -ne $true) { Fail "Stage-3.3.4 graph/validation capability is not active" }
if ($health.task_dependency_graph_planner_invocation_performed -ne $false) { Fail "Planner invocation was unexpectedly enabled" }
if ($health.task_dependency_graph_readiness_projection_performed -ne $false -or $health.task_dependency_graph_scheduling_performed -ne $false) { Fail "Readiness/scheduling was prematurely enabled" }
if ($health.task_dependency_graph_governance_query_performed -ne $false) { Fail "Governance query was unexpectedly performed" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.3.4 active; migration=12; planner/readiness/Governance/execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Stage-3.3.1/3.3.2/3.3.3 prerequisites + graph discovery"
$prepared = New-PreparedMission "main-$token"
$missionId = $prepared.mission_id
$definition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph-definition"
if ($definition.task_dependency_graph_definition.schema_version -ne "apts-canonical-task-dependency-graph-v1") { Fail "Graph-definition discovery schema mismatch" }
if ($definition.task_dependency_graph_definition.structural_validation_mode -ne "DETERMINISTIC_COMPLETE_DAG_FAIL_CLOSED") { Fail "Graph structural-validation mode mismatch" }
if ($definition.graph_registered -ne $false) { Fail "Graph was unexpectedly registered before Stage-3.3.4 request" }
if ([int]$prepared.decomposition.task_count -ne 2) { Fail "Expected two Stage-3.3.3 canonical planned tasks" }
Pass "Canonical Plan, snapshot, decomposition, and graph-definition prerequisites PASS"

Write-Host "`n[4] Canonical DAG materialization + structural validation"
$planBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract"
$snapshotBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot"
$decompBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-decomposition"
$graphRequest = New-GraphRequest $missionId $token
$graph = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph" $graphRequest
if ($graph.graph_id -notlike "mgraph-*") { Fail "Canonical dependency-graph identity is invalid" }
if ([int]$graph.graph_version -ne 1 -or [int]$graph.node_count -ne 2 -or [int]$graph.edge_count -ne 1) { Fail "Graph version/node/edge cardinality mismatch" }
if ($graph.validation_status -ne "PASS") { Fail "Graph structural validation did not PASS" }
if ($graph.task_dependency_graph.graph.status -ne "STRUCTURALLY_VALIDATED") { Fail "Graph status is not STRUCTURALLY_VALIDATED" }
$topo = @($graph.task_dependency_graph.graph.topological_task_keys)
if ($topo.Count -ne 2 -or $topo[0] -ne "collect-cti" -or $topo[1] -ne "analyze-cti") { Fail "Deterministic topological order mismatch" }
if ($graph.task_dependency_graph.structural_validation.cycle_detected -ne $false) { Fail "Valid graph reports a cycle" }
if ($graph.task_dependency_graph.semantics.readiness_projection_performed -ne $false -or $graph.task_dependency_graph.semantics.scheduling_performed -ne $false) { Fail "Graph registration performed readiness/scheduling" }
if ($graph.task_dependency_graph.semantics.target_action_dispatch_enabled -ne $false) { Fail "Graph registration performed dispatch" }
$planAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract"
$snapshotAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot"
$decompAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-decomposition"
if ($planAfter.canonical_sha256 -ne $planBefore.canonical_sha256) { Fail "Graph registration mutated canonical Plan" }
if ($snapshotAfter.canonical_sha256 -ne $snapshotBefore.canonical_sha256) { Fail "Graph registration mutated planner-input snapshot" }
if ($decompAfter.canonical_sha256 -ne $decompBefore.canonical_sha256) { Fail "Graph registration mutated task decomposition" }
Pass "Complete immutable DAG materialized with deterministic topological validation; prior artifacts unchanged"

Write-Host "`n[5] Edge read model + version vector + idempotent replay"
$edges = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-dependency-edges"
if ([int]$edges.edge_count -ne 1) { Fail "Dependency-edge read model count mismatch" }
if ($edges.dependency_edges[0].dependency_edge_id -notlike "medge-*") { Fail "Dependency-edge identity is invalid" }
if ($edges.dependency_edges[0].from_task_key -ne "collect-cti" -or $edges.dependency_edges[0].to_task_key -ne "analyze-cti") { Fail "Dependency-edge semantics mismatch" }
$vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$vector.version_vector.versions.mission_plan_version -ne 1 -or [int]$vector.version_vector.versions.planner_input_snapshot_version -ne 1 -or [int]$vector.version_vector.versions.task_decomposition_version -ne 1 -or [int]$vector.version_vector.versions.task_dependency_graph_version -ne 1) { Fail "Planning version domains are not 1/1/1/1" }
$eventsBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph" $graphRequest
$eventsAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($replay.idempotent_replay -ne $true -or $replay.graph_id -ne $graph.graph_id -or $replay.canonical_sha256 -ne $graph.canonical_sha256) { Fail "Exact graph replay was not canonical/idempotent" }
if ([int]$eventsAfter.event_count -ne [int]$eventsBefore.event_count) { Fail "Exact graph replay created duplicate Mission event" }
$graphEvents = @($eventsAfter.events | Where-Object { $_.event_type -eq "MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED" })
if ($graphEvents.Count -ne 1) { Fail "Expected exactly one MISSION_TASK_DEPENDENCY_GRAPH_REGISTERED event" }
Pass "Edge read model, task_dependency_graph_version=1, and side-effect-free replay PASS"

Write-Host "`n[6] Directed cycle fails closed before persistence"
$cyclePrepared = New-PreparedMission "cycle-$token"
$cycleMissionId = $cyclePrepared.mission_id
$cycleEdges = @(
    @{ from_task_key = "collect-cti"; to_task_key = "analyze-cti" },
    @{ from_task_key = "analyze-cti"; to_task_key = "collect-cti" }
)
$cycleRequest = New-GraphRequest $cycleMissionId "cycle-$token" $cycleEdges
$cycleFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$cycleMissionId/task-dependency-graph" $cycleRequest
if ([int]$cycleFailure.status -ne 409 -or $cycleFailure.body.code -ne "MISSION_TASK_DEPENDENCY_GRAPH_GUARD_REJECTED") { Fail "Directed cycle did not fail closed with graph guard rejection" }
$cycleDefinition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$cycleMissionId/task-dependency-graph-definition"
if ($cycleDefinition.graph_registered -ne $false) { Fail "Rejected cyclic graph was persisted" }
Pass "Directed-cycle structural validation fails closed with zero graph persistence"

Write-Host "`n[7] Durable repository / event lineage / migration projection"
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repository.integrity_status -ne "PASS") { Fail "Repository integrity did not PASS" }
if ([int]$repository.repository.migration_level -ne 12) { Fail "Repository projection migration level is not 12" }
if ([int]$repository.record_counts.mission_task_dependency_graphs -ne 1) { Fail "Dependency-graph store count mismatch" }
if ([int]$repository.record_counts.mission_task_dependency_edges -ne 1) { Fail "Dependency-edge store count mismatch" }
if ($repository.persistence_manifest.task_dependency_graph_store.graph_id -ne $graph.graph_id) { Fail "Persistence manifest graph binding mismatch" }
if (@($repository.persistence_manifest.task_dependency_edge_store).Count -ne 1) { Fail "Persistence manifest edge cardinality mismatch" }
if ($repository.persistence_manifest.integrity.canonical_sha256.Length -ne 64) { Fail "Persistence manifest canonical hash missing" }
Pass "Graph/edge stores, canonical event lineage, persistence manifest, and repository integrity PASS"

Write-Host "`n[8] Final Stage-3.3.4 invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.3.4-task-dependency-graph-structural-validation") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 12) { Fail "Final migration level drifted" }
if ($finalHealth.task_dependency_graph_planner_invocation_performed -ne $false) { Fail "Final planner boundary drifted" }
if ($finalHealth.task_dependency_graph_readiness_projection_performed -ne $false -or $finalHealth.task_dependency_graph_scheduling_performed -ne $false) { Fail "Final readiness/scheduling boundary drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Final Governance authority drifted" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Final target execution boundary drifted" }
Pass "GRAPH != SCHEDULING, TASK != DISPATCH, READINESS != PERMISSION, PLANNER != GOVERNANCE"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.3.4 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Mission             : $missionId"
Write-Host "Plan                : $($prepared.plan.plan_id)"
Write-Host "Planner Snapshot    : $($prepared.snapshot.snapshot_id)"
Write-Host "Task Decomposition  : $($prepared.decomposition.decomposition_id)"
Write-Host "Dependency Graph    : $($graph.graph_id)"
Write-Host "Graph Nodes / Edges : $($graph.node_count) / $($graph.edge_count)"
Write-Host "Regression Baseline : 344 passed"
Write-Host "Repository SHA256   : $($repository.repository_sha256)"
Write-Host "Target Dispatch     : $($finalHealth.target_action_dispatch_enabled)"
Write-Host "=============================================================================="
exit 0
