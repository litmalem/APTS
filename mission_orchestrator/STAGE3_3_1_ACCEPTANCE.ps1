param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.3.1 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        idempotency_key = "stage331-mission-$Token"
        source_system = "STAGE331_ACCEPTANCE"
        created_by = "stage3.3.1-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage331-lab" }
        success_criteria = @(
            @{ metric = "canonical_plan_identity"; expected = $true },
            @{ metric = "no_authority_expansion"; expected = $true }
        )
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-stage331-$Token"
        pip_version = "15"
        metadata = @{ environment = "LAB"; acceptance = "stage3.3.1" }
    }
}

function New-LifecycleCommand([string]$MissionId, [string]$Command, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-stage331-$Token"
        idempotency_key = "idem-lc-stage331-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.3.1-acceptance"
        reason_code = "STAGE331_$Command"
        reason = "Stage 3.3.1 prerequisite command $Command"
        evidence_refs = @("evidence:stage331:$Token")
        metadata = @{ acceptance = "stage3.3.1"; token = $Token }
    }
}

function Invoke-Lifecycle([string]$MissionId, [string]$Command, [string]$Token) {
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId $Command $Token)
}

function New-PlanRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        idempotency_key = "stage331-plan-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.1-acceptance"
        reason = "Register immutable canonical plan identity"
        metadata = @{ acceptance = "stage3.3.1"; key = $Key }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.3.1 - Canonical Plan Contract & Identity Acceptance"
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
    if ($joined -notmatch "280 passed") { Fail "Expected Stage-3.3.1 regression baseline of 280 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.3.1 regression baseline: 280 passed"

Write-Host "`n[2] Health / Plan contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.3.1-canonical-plan-contract-identity") { Fail "Stage 3.3.1 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 9) { Fail "Repository migration level is not 9" }
if ($health.mission_plan_contract_schema_version -ne "apts-mission-plan-contract-v1") { Fail "Plan contract schema mismatch" }
if ($health.mission_plan_contract_mode -ne "IMMUTABLE_CANONICAL_PLAN_IDENTITY_BOUND_TO_MISSION_AND_PLANNING_ACTIVATION") { Fail "Plan contract mode mismatch" }
if ($health.mission_plan_contract_creation_state_required -ne "PLANNING") { Fail "Plan creation state is not PLANNING" }
if ([int]$health.mission_plan_contract_initial_version -ne 1) { Fail "Initial plan version is not 1" }
if ($health.mission_plan_contract_task_graph_initial_status -ne "NOT_MATERIALIZED") { Fail "Task graph was unexpectedly materialized" }
if ($health.mission_plan_contract_requires_stage3_2_4_planning_activation_lineage -ne $true) { Fail "Stage-3.2.4 activation lineage is not mandatory" }
if ($health.mission_plan_contract_planner_invocation_performed -ne $false) { Fail "Planner invocation was unexpectedly enabled" }
if ($health.mission_plan_contract_task_decomposition_performed -ne $false) { Fail "Task decomposition was unexpectedly enabled" }
if ($health.mission_plan_contract_plan_revision_performed -ne $false) { Fail "Plan revision was unexpectedly enabled" }
if ($health.mission_plan_contract_plan_is_authorization -ne $false) { Fail "PLAN was confused with AUTHORIZATION" }
if ($health.mission_plan_contract_task_is_dispatch -ne $false) { Fail "TASK was confused with DISPATCH" }
if ($health.mission_plan_contract_readiness_is_permission -ne $false) { Fail "READINESS was confused with PERMISSION" }
if ($health.mission_plan_contract_planner_is_governance -ne $false) { Fail "PLANNER was confused with GOVERNANCE" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
if (@($health.supported_controls) -notcontains "stage3.2.10-lifecycle-acceptance-regression-gate") { Fail "Stage 3.2.10 closure baseline is missing" }
if (@($health.supported_controls) -notcontains "stage3.3.1-canonical-plan-contract-identity") { Fail "Stage 3.3.1 control is missing" }
Pass "Plan identity contract active; migration=9; authority/execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Contract discovery + fail-closed before PLANNING"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload $token)
$missionId = $mission.canonical_identity.mission_id
$definition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract-definition"
if ($definition.plan_registered -ne $false) { Fail "Fresh mission unexpectedly has a registered Plan" }
if ($definition.plan_contract_definition.schema_version -ne "apts-mission-plan-contract-v1") { Fail "Plan definition schema mismatch" }
if ($definition.plan_contract_definition.creation_state_required -ne "PLANNING") { Fail "Plan definition does not require PLANNING" }
if ($definition.plan_contract_definition.task_graph_status_at_stage3_3_1 -ne "NOT_MATERIALIZED") { Fail "Plan definition materializes a task graph" }
if ($definition.plan_contract_definition.plan_is_authorization -ne $false -or $definition.plan_contract_definition.planner_is_governance -ne $false) { Fail "Plan definition expands authority" }
$tooEarlyRequest = New-PlanRequest $missionId "too-early-$token"
$tooEarly = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/plan-contract" $tooEarlyRequest
if ([int]$tooEarly.status -ne 409 -or $tooEarly.body.code -ne "MISSION_PLAN_CONTRACT_GUARD_REJECTED") { Fail "Plan registration before PLANNING did not fail closed" }
Pass "Plan contract is discoverable and cannot be registered before guarded PLANNING"

Write-Host "`n[4] Stage-3.2.4 activation lineage + canonical Plan registration"
$bound = Invoke-Lifecycle $missionId "BIND_PIP" "bind-$token"
if ($bound.mission_state.state -ne "PIP_BOUND") { Fail "BIND_PIP did not enter PIP_BOUND" }
$planning = Invoke-Lifecycle $missionId "START_PLANNING" "planning-$token"
if ($planning.mission_state.state -ne "PLANNING") { Fail "START_PLANNING did not enter PLANNING" }
if ($planning.planning_run_activation.planner_invocation_performed -ne $false) { Fail "Stage-3.2.4 activation unexpectedly invoked planner" }
if ($planning.planning_run_activation.execution_authorized -ne $false) { Fail "Stage-3.2.4 activation unexpectedly authorized execution" }
$beforeVector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$beforeVector.version_vector.versions.mission_plan_version -ne 0) { Fail "mission_plan_version is not 0 before registration" }
$planRequest = New-PlanRequest $missionId "canonical-$token"
$plan = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-contract" $planRequest
if ($plan.idempotent_replay -ne $false) { Fail "First Plan registration was reported as replay" }
if (-not $plan.plan_id.StartsWith("mplan-")) { Fail "Canonical plan_id prefix mismatch" }
if ([int]$plan.plan_version -ne 1) { Fail "Canonical plan_version is not 1" }
if ($plan.plan_contract.identity.mission_id -ne $missionId) { Fail "Plan identity is not bound to Mission" }
if ($plan.plan_contract.mission_binding.mission_id -ne $missionId) { Fail "Mission binding mismatch" }
if ($plan.plan_contract.planning_activation_binding.state -ne "PLANNING") { Fail "Plan is not bound to PLANNING" }
if ($plan.plan_contract.planning_activation_binding.planning_transition_to_state -ne "PLANNING") { Fail "Plan activation lineage mismatch" }
if ($plan.plan_contract.task_graph.status -ne "NOT_MATERIALIZED" -or [int]$plan.plan_contract.task_graph.task_count -ne 0 -or [int]$plan.plan_contract.task_graph.dependency_edge_count -ne 0) { Fail "Stage 3.3.1 unexpectedly materialized tasks/dependencies" }
if ($plan.plan_contract.semantics.planner_invocation_performed -ne $false -or $plan.plan_contract.semantics.task_decomposition_performed -ne $false) { Fail "Planner/task decomposition boundary expanded" }
if ($plan.plan_contract.semantics.plan_is_authorization -ne $false -or $plan.plan_contract.semantics.task_is_dispatch -ne $false) { Fail "Plan/task semantics expanded into authority/dispatch" }
if ($plan.canonical_sha256.Length -ne 64 -or $plan.plan_contract.integrity.canonical_sha256 -ne $plan.canonical_sha256) { Fail "Canonical Plan SHA-256 integrity mismatch" }
Pass "Immutable Plan identity/version/hash are bound to exact Mission and Stage-3.2.4 PLANNING lineage"

Write-Host "`n[5] Idempotent replay + immutable single identity + request surface"
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-contract" $planRequest
if ($replay.idempotent_replay -ne $true) { Fail "Exact Plan retry was not idempotent" }
if ($replay.plan_id -ne $plan.plan_id -or $replay.canonical_sha256 -ne $plan.canonical_sha256) { Fail "Idempotent replay changed Plan identity/hash" }
$secondRequest = New-PlanRequest $missionId "second-$token"
$second = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/plan-contract" $secondRequest
if ([int]$second.status -ne 409 -or $second.body.code -ne "MISSION_PLAN_CONTRACT_CONFLICT") { Fail "Second Plan identity was not rejected" }
$invalidRequest = @{}
$planRequest.GetEnumerator() | ForEach-Object { $invalidRequest[$_.Key] = $_.Value }
$invalidRequest.idempotency_key = "stage331-plan-invalid-$token"
$invalidRequest.tasks = @(@{ task_id = "task-not-allowed" })
$invalid = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/plan-contract" $invalidRequest
if ([int]$invalid.status -ne 400 -or $invalid.body.code -ne "MISSION_CONTRACT_INVALID") { Fail "Task materialization field was not rejected at Stage 3.3.1" }
Pass "Replay is stable; second identity and task/planner surface expansion fail closed"

Write-Host "`n[6] Version vector + event lineage + repository integrity"
$afterVector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$afterVector.version_vector.versions.mission_plan_version -ne 1) { Fail "mission_plan_version did not advance to 1" }
if ($afterVector.version_sha256 -eq $beforeVector.version_sha256) { Fail "Version-vector SHA-256 did not change after Plan registration" }
$stored = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/plan-contract"
if ($stored.plan_id -ne $plan.plan_id -or $stored.canonical_sha256 -ne $plan.canonical_sha256) { Fail "Stored Plan reconstruction mismatch" }
$events = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$planEvents = @($events.events | Where-Object { $_.event_type -eq "MISSION_PLAN_CONTRACT_REGISTERED" })
if ($planEvents.Count -ne 1) { Fail "Expected exactly one MISSION_PLAN_CONTRACT_REGISTERED event" }
if ($planEvents[0].causation_id -ne $plan.plan_id -or [int]$planEvents[0].plan_version -ne 1) { Fail "Plan event causation/version mismatch" }
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repository.integrity_status -ne "PASS") { Fail "Mission repository integrity is not PASS" }
if ([int]$repository.repository.migration_level -ne 9) { Fail "Repository projection migration level is not 9" }
if (@($repository.repository.stores) -notcontains "mission_plans") { Fail "mission_plans store is missing from repository projection" }
if ([int]$repository.record_counts.mission_plans -ne 1) { Fail "mission_plans record count is not 1" }
if ($repository.persistence_manifest.mission_plan_store.plan_id -ne $plan.plan_id) { Fail "Persistence manifest Plan binding mismatch" }
Pass "Plan version, event causality, persistence, reconstruction, and integrity PASS"

Write-Host "`n[7] Final authority/execution invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority drifted during acceptance" }
if ($finalHealth.mission_plan_contract_planner_invocation_performed -ne $false) { Fail "Planner invocation became enabled" }
if ($finalHealth.mission_plan_contract_task_decomposition_performed -ne $false) { Fail "Task decomposition became enabled" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution became enabled" }
Pass "PLAN != AUTHORIZATION; TASK != DISPATCH; READINESS != PERMISSION; PLANNER != GOVERNANCE"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.3.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
