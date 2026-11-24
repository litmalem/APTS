param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.3.8 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        idempotency_key = "stage336-mission-$Token"
        source_system = "STAGE336_ACCEPTANCE"
        created_by = "stage3.3.6-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage336-lab" }
        success_criteria = @(
            @{ metric = "dependency_graph_validated"; expected = $true },
            @{ metric = "authority_boundary_preserved"; expected = $true }
        )
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-stage336-$Token"
        pip_version = "18"
        metadata = @{ environment = "LAB"; acceptance = "stage3.3.5" }
    }
}

function New-LifecycleCommand([string]$MissionId, [string]$Command, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-stage336-$Token"
        idempotency_key = "idem-lc-stage336-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.3.6-acceptance"
        reason_code = "STAGE336_$Command"
        reason = "Stage 3.3.5 prerequisite command $Command"
        evidence_refs = @("evidence:stage336:$Token")
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
        idempotency_key = "stage336-plan-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.6-acceptance"
        reason = "Register Stage-3.3.1 canonical Plan prerequisite"
        metadata = @{ acceptance = "stage3.3.5"; prerequisite = "3.3.1"; key = $Key }
    }
}

function New-SnapshotRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    return @{
        idempotency_key = "stage336-snapshot-$Key"
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.6-acceptance"
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
        idempotency_key = "stage336-decomposition-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_snapshot_id = $snapshot.snapshot_id
        expected_snapshot_version = [int]$snapshot.snapshot_version
        expected_snapshot_sha256 = $snapshot.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.6-acceptance"
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
        idempotency_key = "stage336-graph-$Key"
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
        created_by = "stage3.3.6-acceptance"
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
        idempotency_key = "stage336-planner-$Key"
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
        created_by = "stage3.3.6-acceptance"
        reason = "Invoke Stage-3.3.5 local deterministic graph planner"
        metadata = @{ acceptance = "stage3.3.5"; key = $Key }
    }
}


function New-ValidationRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $generated = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/generated-plan"
    return @{
        idempotency_key = "stage336-validation-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        expected_generated_plan_id = $generated.generated_plan_id
        expected_generated_plan_sha256 = $generated.canonical_sha256
        created_by = "stage3.3.6-acceptance"
        reason = "Validate Stage-3.3.5 generated candidate Plan feasibility"
        metadata = @{ acceptance = "stage3.3.6"; key = $Key }
    }
}


function New-LifecycleCommand337([string]$MissionId, [string]$Command, [string]$Token, $EvidenceRefs = $null) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    if ($null -eq $EvidenceRefs) { $EvidenceRefs = @("evidence:stage337:$Token") }
    return @{
        command_id = "lc-stage337-$Token"
        idempotency_key = "idem-lc-stage337-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.3.7-acceptance"
        reason_code = "STAGE337_$Command"
        reason = "Stage 3.3.7 lifecycle command $Command"
        evidence_refs = $EvidenceRefs
        metadata = @{ acceptance = "stage3.3.7"; token = $Token }
    }
}

function Invoke-Lifecycle337([string]$MissionId, [string]$Command, [string]$Token, $EvidenceRefs = $null) {
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand337 $MissionId $Command $Token $EvidenceRefs)
}

function New-PlanVersionActivationRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $validation = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-validation"
    return @{
        idempotency_key = "stage337-activate-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        expected_plan_validation_id = $validation.plan_validation_id
        expected_plan_validation_sha256 = $validation.canonical_sha256
        created_by = "stage3.3.7-acceptance"
        reason = "Activate immutable validated-feasible Plan version v1"
        metadata = @{ acceptance = "stage3.3.7"; key = $Key }
    }
}

function New-ReplanSuccessorRequest([string]$MissionId, [string]$ReplanId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $active = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-versions/active"
    return @{
        idempotency_key = "stage337-replan-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        expected_active_plan_version = [int]$active.plan_version
        expected_active_plan_sha256 = $active.canonical_sha256
        expected_replan_id = $ReplanId
        created_by = "stage3.3.7-acceptance"
        reason = "Create immutable successor Plan for canonical replanning episode"
        metadata = @{ acceptance = "stage3.3.7"; key = $Key }
    }
}

function New-TaskReadinessProjectionRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $active = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-versions/active"
    return @{
        idempotency_key = "stage338-projection-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        expected_active_plan_version_record_id = $active.plan_version_record_id
        expected_active_plan_version = [int]$active.plan_version
        expected_active_plan_sha256 = $active.canonical_sha256
        created_by = "stage3.3.8-acceptance"
        reason = "Project structural task readiness and deterministic dependency waves only"
        metadata = @{ acceptance = "stage3.3.8"; key = $Key }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.3.8 - Task Readiness & Scheduling Projection Acceptance"
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
    if ($joined -notmatch "456 passed") { Fail "Expected Stage-3.3.8 regression baseline of 456 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.3.8 regression baseline: 456 passed"

Write-Host "`n[2] Health / Plan-versioning contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.3.8-task-readiness-scheduling-projection") { Fail "Stage 3.3.8 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 16) { Fail "Repository migration level is not 16" }
if ($health.plan_versioning_schema_version -ne "apts-mission-plan-version-v1") { Fail "Plan-versioning schema mismatch" }
if ($health.plan_versioning_append_only_versions -ne $true -or $health.plan_versioning_single_active_head -ne $true) { Fail "Append-only version/head contract is not active" }
if ($health.plan_versioning_head_update_mode -ne "OPTIMISTIC_COMPARE_AND_SWAP") { Fail "Plan-version active-head CAS mode mismatch" }
if ($health.plan_versioning_successor_version_rule -ne "PREDECESSOR_PLUS_ONE") { Fail "Plan successor version rule mismatch" }
if ($health.plan_versioning_prior_versions_mutated -ne $false) { Fail "Prior Plan versions may be mutated" }
if ($health.plan_versioning_planner_reinvocation_on_replan -ne $true) { Fail "Replanning does not re-invoke the deterministic planner" }
if ($health.plan_versioning_governance_query_performed -ne $false -or $health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.plan_versioning_scheduling_performed -ne $false -or $health.plan_versioning_target_action_dispatch_enabled -ne $false -or $health.plan_versioning_target_actuation -ne $false) { Fail "Readiness/scheduling/execution authority expanded" }
if ($health.task_readiness_projection_schema_version -ne "apts-task-readiness-scheduling-projection-v1") { Fail "Task-readiness projection schema mismatch" }
if ($health.task_readiness_projection_scheduling_mode -ne "DEPENDENCY_LAYER_WAVES_NO_CLOCK_NO_RESOURCE_ASSIGNMENT") { Fail "Task-readiness scheduling mode mismatch" }
if ($health.task_readiness_projection_readiness_is_permission -ne $false -or $health.task_readiness_projection_ready_is_authorized -ne $false) { Fail "Readiness was conflated with permission/authorization" }
if ($health.task_readiness_projection_target_action_dispatch_enabled -ne $false -or $health.task_readiness_projection_target_actuation -ne $false) { Fail "Stage 3.3.8 expanded target execution authority" }
Pass "Stage 3.3.8 active; migration=16; structural readiness/waves enabled while Governance/execution boundaries remain preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Stage-3.3.1 through 3.3.6 prerequisites + versioning discovery"
$prepared = New-PreparedMission "main-$token"
$missionId = $prepared.mission_id
$graph = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph" (New-GraphRequest $missionId "main-$token")
if ($graph.validation_status -ne "PASS") { Fail "Stage-3.3.4 DAG prerequisite did not validate" }
$generated = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-invocation" (New-PlannerRequest $missionId "main-$token")
if ($generated.generated_plan_status -ne "GENERATED_UNVALIDATED") { Fail "Stage-3.3.5 candidate was not generated" }
$validated = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-validation" (New-ValidationRequest $missionId "main-$token")
if ($validated.validation_status -ne "VALIDATED_FEASIBLE" -or $validated.feasible -ne $true) { Fail "Stage-3.3.6 prerequisite is not VALIDATED_FEASIBLE" }
$definition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-versioning-definition"
if ($definition.plan_versioning_active -ne $false -or [int]$definition.registered_version_count -ne 0) { Fail "Plan version existed before initial activation" }
if ($definition.plan_versioning_definition.schema_version -ne "apts-mission-plan-version-v1") { Fail "Plan-versioning definition discovery failed" }
Pass "Stage-3.3.1 through 3.3.6 artifacts are bound and Stage-3.3.7 definition is discoverable"

Write-Host "`n[4] Initial v1 activation + exact replay"
$activateRequest = New-PlanVersionActivationRequest $missionId "main-$token"
$v1 = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-versions/activate" $activateRequest
if ([int]$v1.plan_version -ne 1 -or $v1.activation_type -ne "INITIAL_VALIDATED_PLAN" -or $v1.effective_status -ne "ACTIVE") { Fail "Initial Plan v1 activation failed" }
if ($v1.predecessor_plan_version_record_id -ne $null -or $v1.replan_id -ne $null) { Fail "Initial Plan v1 contains invalid predecessor/replan lineage" }
if ($v1.governance_authorization_query_performed -ne $false -or $v1.target_action_dispatch_enabled -ne $false) { Fail "Initial activation expanded authority" }
$eventsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$v1Replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-versions/activate" $activateRequest
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($v1Replay.idempotent_replay -ne $true -or $v1Replay.plan_version_record_id -ne $v1.plan_version_record_id) { Fail "Initial Plan exact replay was not idempotent" }
if ([int]$eventsAfterReplay.event_count -ne [int]$eventsBeforeReplay.event_count) { Fail "Initial Plan replay duplicated events" }
Pass "Validated-feasible Plan activated as immutable v1; exact replay is side-effect-free"

Write-Host "`n[5] Active Plan v1 readiness + dependency-wave projection + replay"
$projectionDefinition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-readiness-projection-definition"
if ($projectionDefinition.active_projection_registered -ne $false -or [int]$projectionDefinition.registered_projection_count -ne 0) { Fail "Readiness projection existed before Stage-3.3.8 materialization" }
$p1Request = New-TaskReadinessProjectionRequest $missionId "v1-$token"
$p1 = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-readiness-projection" $p1Request
if ([int]$p1.plan_version -ne 1 -or $p1.effective_status -ne "ACTIVE") { Fail "v1 readiness projection is not active/bound to Plan v1" }
if ([int]$p1.ready_task_count -ne 1 -or [int]$p1.blocked_task_count -ne 1 -or [int]$p1.task_count -ne 2) { Fail "v1 structural readiness counts are invalid" }
if ($p1.ready_task_keys[0] -ne "collect-cti" -or $p1.blocked_task_keys[0] -ne "analyze-cti") { Fail "v1 root/dependent readiness semantics are invalid" }
if ([int]$p1.wave_count -ne 2 -or $p1.scheduling_projection.wall_clock_schedule_created -ne $false -or $p1.scheduling_projection.resource_assignment_performed -ne $false -or $p1.scheduling_projection.dispatch_performed -ne $false) { Fail "v1 scheduling projection expanded beyond dependency waves" }
if ($p1.readiness_is_permission -ne $false -or $p1.ready_is_authorized -ne $false -or $p1.governance_authorization_query_performed -ne $false -or $p1.target_action_dispatch_enabled -ne $false) { Fail "v1 readiness projection expanded authority" }
$eventsBeforeP1Replay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$p1Replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-readiness-projection" $p1Request
$eventsAfterP1Replay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($p1Replay.idempotent_replay -ne $true -or $p1Replay.projection_id -ne $p1.projection_id) { Fail "v1 readiness exact replay was not idempotent" }
if ([int]$eventsAfterP1Replay.event_count -ne [int]$eventsBeforeP1Replay.event_count) { Fail "v1 readiness replay duplicated events" }
Pass "Plan v1 projects READY roots + BLOCKED dependencies into structural waves; replay is side-effect-free"

Write-Host "`n[6] RUNNING -> REPLANNING + premature return fail-closed"
$running = Invoke-Lifecycle337 $missionId "START" "run-$token"
if ($running.mission_state.state -ne "RUNNING") { Fail "Mission did not enter RUNNING" }
$replan = Invoke-Lifecycle337 $missionId "REPLAN" "replan-$token"
if ($replan.mission_state.state -ne "REPLANNING") { Fail "Mission did not enter REPLANNING" }
$replanId = $replan.replan_control.replan_id
if ([string]::IsNullOrWhiteSpace($replanId)) { Fail "Canonical replan_id is missing" }
$premature = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" (New-LifecycleCommand337 $missionId "START" "premature-$token" @("plan-readiness:premature"))
if ([int]$premature.status -ne 409 -or $premature.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "REPLANNING -> RUNNING was not blocked before successor Plan commit" }
Pass "Canonical replan lineage created; REPLANNING cannot return to RUNNING before successor Plan commit"

Write-Host "`n[7] Deterministic v2 successor + supersession + replay"
$replanRequest = New-ReplanSuccessorRequest $missionId $replanId "main-$token"
$v2 = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-versions/replan" $replanRequest
if ([int]$v2.plan_version -ne 2 -or $v2.activation_type -ne "REPLAN_SUCCESSOR" -or $v2.effective_status -ne "ACTIVE") { Fail "Replan successor v2 creation failed" }
if ($v2.predecessor_plan_version_record_id -ne $v1.plan_version_record_id -or [int]$v2.predecessor_plan_version -ne 1) { Fail "v2 predecessor lineage mismatch" }
if ($v2.replan_id -ne $replanId -or $v2.planner_reinvocation_performed -ne $true) { Fail "v2 is not bound to replan lineage / planner reinvocation" }
$history = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-versions"
if ([int]$history.version_count -ne 2) { Fail "Expected exactly two Plan versions after first replan" }
if ($history.plan_versions[0].effective_status -ne "SUPERSEDED" -or $history.plan_versions[1].effective_status -ne "ACTIVE") { Fail "Supersession projection is invalid" }
if ($history.plan_versions[0].plan_version_record_id -ne $v1.plan_version_record_id -or $history.plan_versions[1].plan_version_record_id -ne $v2.plan_version_record_id) { Fail "Version history identity mismatch" }
$eventsBeforeV2Replay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$v2Replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-versions/replan" $replanRequest
$eventsAfterV2Replay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($v2Replay.idempotent_replay -ne $true -or $v2Replay.plan_version_record_id -ne $v2.plan_version_record_id) { Fail "v2 exact replay was not idempotent" }
if ([int]$eventsAfterV2Replay.event_count -ne [int]$eventsBeforeV2Replay.event_count) { Fail "v2 replay duplicated events" }
Pass "Planner re-invocation appended v2; v1 projects SUPERSEDED without mutation; replay is side-effect-free"

Write-Host "`n[8] Successor Plan v2 receives separate readiness projection; v1 projection supersedes"
$p2Request = New-TaskReadinessProjectionRequest $missionId "v2-$token"
$p2 = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-readiness-projection" $p2Request
if ([int]$p2.plan_version -ne 2 -or $p2.plan_version_record_id -ne $v2.plan_version_record_id -or $p2.effective_status -ne "ACTIVE") { Fail "v2 readiness projection is not bound to active successor Plan" }
$projectionHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/task-readiness-projections"
if ([int]$projectionHistory.projection_count -ne 2) { Fail "Expected exactly two readiness projections after v2" }
if ($projectionHistory.projections[0].effective_status -ne "SUPERSEDED" -or $projectionHistory.projections[1].effective_status -ne "ACTIVE") { Fail "Readiness projection supersession semantics are invalid" }
if ($projectionHistory.projections[0].projection_id -ne $p1.projection_id -or $projectionHistory.projections[1].projection_id -ne $p2.projection_id) { Fail "Readiness projection history identity mismatch" }
Pass "Readiness projections are immutable per Plan version; v1 projects SUPERSEDED and v2 ACTIVE"

Write-Host "`n[9] Stale active-head CAS rejection"
$staleRequest = New-ReplanSuccessorRequest $missionId $replanId "stale-$token"
$staleRequest.expected_active_plan_version = 1
$staleRequest.expected_active_plan_sha256 = $v1.canonical_sha256
$staleFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/plan-versions/replan" $staleRequest
if ([int]$staleFailure.status -ne 409 -or $staleFailure.body.code -ne "MISSION_VERSION_CONFLICT") { Fail "Stale active Plan head did not fail closed with CAS/version conflict" }
Pass "Stale Plan-head version/hash is rejected fail-closed"

Write-Host "`n[10] Replanning return after successor + readiness evidence"
$returned = Invoke-Lifecycle337 $missionId "START" "return-$token" @("plan-readiness:v2")
if ($returned.mission_state.state -ne "RUNNING") { Fail "Mission did not return to RUNNING after successor + readiness" }
if ($returned.replan_resolution.replan_id -ne $replanId) { Fail "Replan resolution lineage mismatch" }
$active = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-versions/active"
if ([int]$active.plan_version -ne 2 -or $active.plan_version_record_id -ne $v2.plan_version_record_id) { Fail "Active Plan head is not v2" }
Pass "REPLANNING -> RUNNING succeeds only after v2 commit plus Stage-3.2.6 readiness evidence"

Write-Host "`n[11] Event lineage + durable repository integrity"
$events = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$activationEvents = @($events.events | Where-Object { $_.event_type -eq "MISSION_PLAN_VERSION_ACTIVATED" })
$replanEvents = @($events.events | Where-Object { $_.event_type -eq "MISSION_PLAN_VERSION_REPLANNED_SUPERSEDED" })
$readinessEvents = @($events.events | Where-Object { $_.event_type -eq "MISSION_TASK_READINESS_PROJECTED" })
if ($activationEvents.Count -ne 1 -or $replanEvents.Count -ne 1 -or $readinessEvents.Count -ne 2) { Fail "Expected one activation, one replan-supersession, and two readiness events" }
if ($activationEvents[0].causation_id -ne $v1.plan_version_record_id -or $replanEvents[0].causation_id -ne $v2.plan_version_record_id) { Fail "Plan-version event causation lineage mismatch" }
if ($readinessEvents[0].causation_id -ne $p1.projection_id -or $readinessEvents[1].causation_id -ne $p2.projection_id) { Fail "Readiness event causation lineage mismatch" }
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repository.integrity_status -ne "PASS") { Fail "Repository integrity did not PASS" }
if ([int]$repository.repository.migration_level -ne 16) { Fail "Repository projection migration level is not 16" }
if ([int]$repository.record_counts.mission_plan_version_heads -ne 1 -or [int]$repository.record_counts.mission_plan_versions -ne 2) { Fail "Plan-version store cardinality mismatch" }
if ([int]$repository.record_counts.mission_task_readiness_projections -ne 2) { Fail "Readiness projection store cardinality mismatch" }
if ($repository.persistence_manifest.plan_versioning_store.head.active_plan_version_record_id -ne $v2.plan_version_record_id) { Fail "Persistence manifest active head mismatch" }
if ($repository.persistence_manifest.task_readiness_projection_store.projections.Count -ne 2) { Fail "Persistence manifest readiness projection store mismatch" }
Pass "Plan/readiness events, append-only history, projection store, manifest, and repository integrity PASS"

Write-Host "`n[12] Version vector + no scheduling/Governance/target execution expansion"
$vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$vector.version_vector.versions.plan_versioning_version -ne 2) { Fail "plan_versioning_version did not advance to 2" }
if ([int]$vector.version_vector.versions.task_readiness_projection_version -ne 2) { Fail "task_readiness_projection_version did not advance to active Plan v2" }
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.plan_versioning_governance_query_performed -ne $false -or $finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Final Governance boundary drifted" }
if ($finalHealth.plan_versioning_scheduling_performed -ne $false -or $finalHealth.plan_versioning_target_action_dispatch_enabled -ne $false -or $finalHealth.plan_versioning_target_actuation -ne $false) { Fail "Final scheduling/execution boundary drifted" }
if ($finalHealth.plan_versioning_external_model_invocation_performed -ne $false -or $finalHealth.plan_versioning_external_network_io_performed -ne $false) { Fail "External model/network behavior was unexpectedly enabled" }
if ($finalHealth.task_readiness_projection_governance_query_performed -ne $false -or $finalHealth.task_readiness_projection_target_action_dispatch_enabled -ne $false -or $finalHealth.task_readiness_projection_target_actuation -ne $false) { Fail "Stage-3.3.8 authority/execution boundary drifted" }
Pass "plan_versioning_version=2 and readiness_projection_version=2; Governance and target execution boundaries preserved"

Write-Host "`n[13] Final Stage-3.3.8 invariant"
if ($finalHealth.control_version -ne "stage3.3.8-task-readiness-scheduling-projection") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 16) { Fail "Final repository migration level drifted" }
if ($finalHealth.plan_versioning_append_only_versions -ne $true -or $finalHealth.plan_versioning_single_active_head -ne $true -or $finalHealth.plan_versioning_prior_versions_mutated -ne $false) { Fail "Final version/supersession invariant drifted" }
if ($finalHealth.task_readiness_projection_readiness_is_permission -ne $false -or $finalHealth.task_readiness_projection_ready_is_authorized -ne $false) { Fail "Final readiness/permission invariant drifted" }
if ($finalHealth.task_readiness_projection_wall_clock_schedule_created -ne $false -or $finalHealth.task_readiness_projection_resource_assignment_performed -ne $false) { Fail "Final scheduling projection expanded into clock/resource scheduling" }
if ($finalHealth.task_readiness_projection_target_action_dispatch_enabled -ne $false -or $finalHealth.task_readiness_projection_target_actuation -ne $false) { Fail "Final target execution boundary drifted" }
Pass "Stage 3.3.8 closes with immutable Plan-bound readiness projections, dependency waves, and no authorization/dispatch expansion"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.3.8 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Mission              : $missionId"
Write-Host "Initial Plan Version : $($v1.plan_version_record_id) / v$($v1.plan_version)"
Write-Host "Active Plan Version  : $($v2.plan_version_record_id) / v$($v2.plan_version)"
Write-Host "Replan ID            : $replanId"
Write-Host "Regression Baseline  : 456 passed"
Write-Host "Repository SHA256    : $($repository.repository_sha256)"
Write-Host "Governance Authority : $($finalHealth.governance_authorization_authority)"
Write-Host "Readiness v1        : $($p1.projection_id)"
Write-Host "Readiness v2        : $($p2.projection_id)"
Write-Host "Ready / Blocked     : $($p2.ready_task_count) / $($p2.blocked_task_count)"
Write-Host "Schedule Waves      : $($p2.wave_count)"
Write-Host "Target Dispatch     : $($finalHealth.task_readiness_projection_target_action_dispatch_enabled)"
Write-Host "=============================================================================="
exit 0
