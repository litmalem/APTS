param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.3.6 ACCEPTANCE: FAIL" -ForegroundColor Red
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

Write-Host "=============================================================================="
Write-Host "Stage 3.3.6 - Plan Validation & Feasibility Gate Acceptance"
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
    if ($joined -notmatch "401 passed") { Fail "Expected Stage-3.3.6 regression baseline of 401 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.3.6 regression baseline: 401 passed"

Write-Host "`n[2] Health / validation-feasibility contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.3.6-plan-validation-feasibility-gate") { Fail "Stage 3.3.6 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 14) { Fail "Repository migration level is not 14" }
if ($health.plan_validation_schema_version -ne "apts-plan-validation-feasibility-v1") { Fail "Plan-validation schema mismatch" }
if ($health.plan_validation_status_after_success -ne "VALIDATED_FEASIBLE") { Fail "Validated feasibility status mismatch" }
if ($health.plan_validation_requires_stage3_3_5_generated_candidate_plan -ne $true) { Fail "Stage 3.3.5 generated-plan prerequisite is not enforced" }
if ($health.plan_validation_deterministic_local_gate -ne $true -or $health.plan_validation_feasibility_validation_performed -ne $true) { Fail "Stage 3.3.6 deterministic validation gate is not active" }
if ($health.plan_validation_plan_activation_performed -ne $false) { Fail "Stage 3.3.6 prematurely activated a Plan" }
if ($health.plan_validation_readiness_projection_performed -ne $false -or $health.plan_validation_scheduling_performed -ne $false) { Fail "Stage 3.3.8 readiness/scheduling was prematurely enabled" }
if ($health.plan_validation_governance_query_performed -ne $false -or $health.plan_validation_feasibility_is_authorization -ne $false) { Fail "Feasibility was confused with Governance authorization" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.plan_validation_target_action_dispatch_enabled -ne $false -or $health.plan_validation_target_actuation -ne $false) { Fail "Target execution authority expanded" }
Pass "Stage 3.3.6 active; migration=14; feasibility enabled while activation/readiness/Governance/execution boundaries remain preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Stage-3.3.1 through 3.3.5 prerequisites + validation discovery"
$prepared = New-PreparedMission "main-$token"
$missionId = $prepared.mission_id
$graph = Post-Json "$MissionBaseUrl/api/missions/$missionId/task-dependency-graph" (New-GraphRequest $missionId "main-$token")
if ($graph.validation_status -ne "PASS") { Fail "Stage-3.3.4 DAG prerequisite did not validate" }
$plannerRequest = New-PlannerRequest $missionId "main-$token"
$generated = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-invocation" $plannerRequest
if ($generated.generated_plan_status -ne "GENERATED_UNVALIDATED") { Fail "Stage-3.3.5 candidate status is not GENERATED_UNVALIDATED" }
$definition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-validation-definition"
if ($definition.generated_plan_registered -ne $true -or $definition.generated_plan_status -ne "GENERATED_UNVALIDATED") { Fail "Generated candidate is not visible to Stage 3.3.6" }
if ($definition.plan_validation_registered -ne $false) { Fail "Plan-validation artifact existed before validation" }
if ($definition.plan_validation_definition.schema_version -ne "apts-plan-validation-feasibility-v1") { Fail "Plan-validation definition discovery failed" }
Pass "Canonical Plan, snapshot, decomposition, validated DAG, and GENERATED_UNVALIDATED candidate are bound; Stage-3.3.6 definition is discoverable"

Write-Host "`n[4] Deterministic Plan validation + feasibility gate"
$validationRequest = New-ValidationRequest $missionId "main-$token"
$validated = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-validation" $validationRequest
if ($validated.plan_validation_id -notlike "pvalidate-*") { Fail "Plan-validation identity is invalid" }
if ([int]$validated.validation_version -ne 1) { Fail "Plan-validation version is not 1" }
if ($validated.validation_status -ne "VALIDATED_FEASIBLE" -or $validated.feasible -ne $true) { Fail "Candidate Plan was not materialized as VALIDATED_FEASIBLE" }
if ($validated.feasibility_is_authorization -ne $false) { Fail "Feasibility was incorrectly treated as authorization" }
if ($validated.plan_activation_performed -ne $false -or $validated.readiness_projection_performed -ne $false) { Fail "Validation prematurely activated Plan/readiness" }
if ($validated.scheduling_performed -ne $false -or $validated.governance_authorization_query_performed -ne $false) { Fail "Validation prematurely scheduled work or queried Governance" }
if ($validated.target_action_dispatch_enabled -ne $false -or $validated.target_actuation -ne $false) { Fail "Validation expanded execution authority" }
$failedChecks = @($validated.plan_validation.validation.checks | Where-Object { $_.status -ne "PASS" })
if ($failedChecks.Count -ne 0) { Fail "One or more deterministic feasibility checks did not PASS" }
Pass "Immutable VALIDATED_FEASIBLE artifact created; all local checks PASS; feasibility remains non-authorizing"

Write-Host "`n[5] Validation replay + version vector + exactly-once event lineage"
$eventsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-validation" $validationRequest
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($replay.idempotent_replay -ne $true -or $replay.plan_validation_id -ne $validated.plan_validation_id) { Fail "Exact validation replay was not idempotent" }
if ([int]$eventsAfterReplay.event_count -ne [int]$eventsBeforeReplay.event_count) { Fail "Exact validation replay created duplicate Mission events" }
$vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$vector.version_vector.versions.mission_plan_version -ne 1 -or [int]$vector.version_vector.versions.planner_input_snapshot_version -ne 1 -or [int]$vector.version_vector.versions.task_decomposition_version -ne 1 -or [int]$vector.version_vector.versions.task_dependency_graph_version -ne 1 -or [int]$vector.version_vector.versions.planner_generation_version -ne 1 -or [int]$vector.version_vector.versions.plan_validation_version -ne 1) { Fail "Stage-3.3 planning version domains are not 1/1/1/1/1/1" }
$validationEvents = @($eventsAfterReplay.events | Where-Object { $_.event_type -eq "MISSION_PLAN_VALIDATED_FEASIBLE" })
if ($validationEvents.Count -ne 1) { Fail "Expected exactly one MISSION_PLAN_VALIDATED_FEASIBLE event" }
if ($validationEvents[0].causation_id -ne $validated.plan_validation_id) { Fail "Plan-validation event causation_id mismatch" }
Pass "Validation replay is side-effect-free; plan_validation_version=1; exactly-once validation event PASS"

Write-Host "`n[6] Validation read model + durable repository integrity"
$validationRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-validation"
if ($validationRead.canonical_sha256 -ne $validated.canonical_sha256) { Fail "Plan-validation read model hash mismatch" }
if ($validationRead.validation_status -ne "VALIDATED_FEASIBLE" -or $validationRead.feasible -ne $true) { Fail "Plan-validation read model status mismatch" }
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repository.integrity_status -ne "PASS") { Fail "Repository integrity did not PASS" }
if ([int]$repository.repository.migration_level -ne 14) { Fail "Repository projection migration level is not 14" }
if ([int]$repository.record_counts.mission_plan_validations -ne 1) { Fail "Plan-validation store count mismatch" }
if ($repository.persistence_manifest.plan_validation_store.plan_validation_id -ne $validated.plan_validation_id) { Fail "Persistence manifest plan-validation identity mismatch" }
Pass "Plan-validation read model, durable store, manifest, and repository integrity PASS"

Write-Host "`n[7] Stale binding + caller-supplied authority/feasibility surfaces fail closed"
$stalePrepared = New-PreparedMission "stale-$token"
$staleMissionId = $stalePrepared.mission_id
$null = Post-Json "$MissionBaseUrl/api/missions/$staleMissionId/task-dependency-graph" (New-GraphRequest $staleMissionId "stale-$token")
$null = Post-Json "$MissionBaseUrl/api/missions/$staleMissionId/planner-invocation" (New-PlannerRequest $staleMissionId "stale-$token")
$staleRequest = New-ValidationRequest $staleMissionId "stale-$token"
$staleRequest.expected_generated_plan_sha256 = ("0" * 64)
$staleFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$staleMissionId/plan-validation" $staleRequest
if ([int]$staleFailure.status -ne 409 -or $staleFailure.body.code -ne "MISSION_PLAN_VALIDATION_GUARD_REJECTED") { Fail "Stale generated-plan binding did not fail closed" }
$injectedRequest = New-ValidationRequest $staleMissionId "injected-$token"
$injectedRequest.authorization = @{ decision = "ALLOW" }
$injectedFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$staleMissionId/plan-validation" $injectedRequest
if ([int]$injectedFailure.status -ne 400 -or $injectedFailure.body.code -ne "MISSION_CONTRACT_INVALID") { Fail "Caller-supplied authorization surface was not rejected" }
$staleDefinition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleMissionId/plan-validation-definition"
if ($staleDefinition.plan_validation_registered -ne $false) { Fail "Rejected validation requests created a persistent artifact" }
Pass "Stale candidate binding and caller-supplied authority surface fail closed with zero validation persistence"

Write-Host "`n[8] Final Stage-3.3.6 invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.3.6-plan-validation-feasibility-gate") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 14) { Fail "Final migration level drifted" }
if ($finalHealth.plan_validation_feasibility_validation_performed -ne $true) { Fail "Final feasibility capability drifted" }
if ($finalHealth.plan_validation_plan_activation_performed -ne $false -or $finalHealth.plan_validation_readiness_projection_performed -ne $false -or $finalHealth.plan_validation_scheduling_performed -ne $false) { Fail "Final later-stage planning boundary drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS" -or $finalHealth.plan_validation_governance_query_performed -ne $false -or $finalHealth.plan_validation_feasibility_is_authorization -ne $false) { Fail "Final Governance authority boundary drifted" }
if ($finalHealth.plan_validation_target_action_dispatch_enabled -ne $false -or $finalHealth.plan_validation_target_actuation -ne $false) { Fail "Final target execution boundary drifted" }
Pass "Stage 3.3.6 closes with local deterministic feasibility, external Governance authority, no activation/readiness/scheduling, and migration level 14"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.3.6 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Mission              : $missionId"
Write-Host "Generated Plan        : $($generated.generated_plan_id)"
Write-Host "Plan Validation       : $($validated.plan_validation_id)"
Write-Host "Validation Status     : $($validated.validation_status)"
Write-Host "Feasible              : $($validated.feasible)"
Write-Host "Regression Baseline   : 401 passed"
Write-Host "Repository SHA256     : $($repository.repository_sha256)"
Write-Host "Governance Authority  : $($finalHealth.governance_authorization_authority)"
Write-Host "Target Dispatch       : $($finalHealth.plan_validation_target_action_dispatch_enabled)"
Write-Host "=============================================================================="
exit 0
