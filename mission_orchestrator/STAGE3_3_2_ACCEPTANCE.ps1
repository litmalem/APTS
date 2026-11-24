param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.3.2 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        idempotency_key = "stage332-mission-$Token"
        source_system = "STAGE332_ACCEPTANCE"
        created_by = "stage3.3.2-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage332-lab" }
        success_criteria = @(
            @{ metric = "planner_context_bound"; expected = $true },
            @{ metric = "no_authority_expansion"; expected = $true }
        )
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-stage332-$Token"
        pip_version = "16"
        metadata = @{ environment = "LAB"; acceptance = "stage3.3.2" }
    }
}

function New-ScopePayload([string]$Token) {
    return @{
        expected_contract_version = 0
        idempotency_key = "stage332-scope-$Token"
        actor = "stage3.3.2-acceptance"
        scope = @{
            targets = @(@{ target_type = "CIDR"; target_value = "127.0.0.0/8"; environment = "LAB" })
            excluded_targets = @()
            network_ranges = @("127.0.0.0/8")
            domains = @("lab.example.test")
            services = @(@{ name = "https"; protocol = "TCP"; port = 443; target_ref = "lab.example.test" })
        }
        roe = @{
            allowed_action_classes = @("TARGET_RECON", "VULNERABILITY_VALIDATION")
            prohibited_action_classes = @("DESTRUCTIVE_ACTION")
            maximum_concurrency = 2
            destructive_actions_allowed = $false
            credential_usage_allowed = $false
            persistence_allowed = $false
            human_approval_required_for = @("VULNERABILITY_VALIDATION")
        }
        constraints = @{
            max_actions = 10
            max_duration = 1200
            risk_threshold = "LOW"
            resource_budget = @{ max_network_requests = 100 }
            data_handling_policy = @{ classification = "INTERNAL" }
        }
        reason = "Stage 3.3.2 planner input context Scope"
        metadata = @{ acceptance = "stage3.3.2" }
    }
}

function New-LifecycleCommand([string]$MissionId, [string]$Command, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-stage332-$Token"
        idempotency_key = "idem-lc-stage332-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.3.2-acceptance"
        reason_code = "STAGE332_$Command"
        reason = "Stage 3.3.2 prerequisite command $Command"
        evidence_refs = @("evidence:stage332:$Token")
        metadata = @{ acceptance = "stage3.3.2"; token = $Token }
    }
}

function Invoke-Lifecycle([string]$MissionId, [string]$Command, [string]$Token) {
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId $Command $Token)
}

function New-PlanRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        idempotency_key = "stage332-plan-$Key"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.2-acceptance"
        reason = "Register Stage-3.3.1 canonical Plan prerequisite"
        metadata = @{ acceptance = "stage3.3.2"; prerequisite = "3.3.1"; key = $Key }
    }
}

function New-SnapshotRequest([string]$MissionId, [string]$Key) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $plan = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/plan-contract"
    return @{
        idempotency_key = "stage332-snapshot-$Key"
        expected_plan_id = $plan.plan_id
        expected_plan_version = [int]$plan.plan_version
        expected_plan_sha256 = $plan.canonical_sha256
        expected_state_version = [int]$state.mission_state.state_version
        created_by = "stage3.3.2-acceptance"
        reason = "Freeze deterministic planner input from canonical local context"
        metadata = @{ acceptance = "stage3.3.2"; key = $Key }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.3.2 - Planner Input Snapshot & Context Binding Acceptance"
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
    if ($joined -notmatch "296 passed") { Fail "Expected Stage-3.3.2 regression baseline of 296 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.3.2 regression baseline: 296 passed"

Write-Host "`n[2] Health / snapshot contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.3.2-planner-input-snapshot-context-binding") { Fail "Stage 3.3.2 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 10) { Fail "Repository migration level is not 10" }
if ($health.planner_input_snapshot_schema_version -ne "apts-planner-input-snapshot-v1") { Fail "Planner-input snapshot schema mismatch" }
if ($health.planner_input_snapshot_mode -ne "IMMUTABLE_LOCAL_CONTEXT_BOUND_TO_CANONICAL_PLAN_AND_EXACT_PLANNING_STATE") { Fail "Planner-input snapshot mode mismatch" }
if ($health.planner_input_snapshot_context_mode -ne "CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH") { Fail "Planner-input context mode mismatch" }
if ($health.planner_input_snapshot_creation_state_required -ne "PLANNING") { Fail "Snapshot creation state is not PLANNING" }
if ([int]$health.planner_input_snapshot_initial_version -ne 1) { Fail "Initial snapshot version is not 1" }
if ($health.planner_input_snapshot_requires_stage3_3_1_plan_contract -ne $true) { Fail "Stage-3.3.1 Plan prerequisite is not enforced" }
if ($health.planner_input_snapshot_local_durable_context_only -ne $true) { Fail "Snapshot is not constrained to durable local context" }
if ($health.planner_input_snapshot_external_context_refresh_performed -ne $false) { Fail "External context refresh was unexpectedly enabled" }
if ($health.planner_input_snapshot_planner_input_ready -ne $true) { Fail "Planner-input readiness is not declared" }
if ($health.planner_input_snapshot_planner_invocation_performed -ne $false) { Fail "Planner invocation was unexpectedly enabled" }
if ($health.planner_input_snapshot_plan_synthesis_performed -ne $false) { Fail "Plan synthesis was unexpectedly enabled" }
if ($health.planner_input_snapshot_task_decomposition_performed -ne $false) { Fail "Task decomposition was unexpectedly enabled" }
if ($health.planner_input_snapshot_snapshot_is_authorization -ne $false) { Fail "SNAPSHOT was confused with AUTHORIZATION" }
if ($health.planner_input_snapshot_context_is_permission -ne $false) { Fail "CONTEXT was confused with PERMISSION" }
if ($health.planner_input_snapshot_plan_is_authorization -ne $false) { Fail "PLAN was confused with AUTHORIZATION" }
if ($health.planner_input_snapshot_task_is_dispatch -ne $false) { Fail "TASK was confused with DISPATCH" }
if ($health.planner_input_snapshot_readiness_is_permission -ne $false) { Fail "READINESS was confused with PERMISSION" }
if ($health.planner_input_snapshot_planner_is_governance -ne $false) { Fail "PLANNER was confused with GOVERNANCE" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
if (@($health.supported_controls) -notcontains "stage3.3.1-canonical-plan-contract-identity") { Fail "Stage 3.3.1 prerequisite control is missing" }
if (@($health.supported_controls) -notcontains "stage3.3.2-planner-input-snapshot-context-binding") { Fail "Stage 3.3.2 control is missing" }
Pass "Stage 3.3.2 contract active; migration=10; planner/authority/execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Contract discovery + Stage-3.3.1 prerequisite guard"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload $token)
$missionId = [string]$mission.canonical_identity.mission_id
$definition = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot-definition"
if ($definition.plan_registered -ne $false -or $definition.snapshot_registered -ne $false) { Fail "Fresh mission unexpectedly has Plan/snapshot artifacts" }
if ($definition.planner_input_snapshot_definition.schema_version -ne "apts-planner-input-snapshot-v1") { Fail "Snapshot definition schema mismatch" }
if ($definition.planner_input_snapshot_definition.creation_state_required -ne "PLANNING") { Fail "Snapshot definition does not require PLANNING" }
if ($definition.planner_input_snapshot_definition.requires_stage3_3_1_plan_contract -ne $true) { Fail "Snapshot definition does not require Stage 3.3.1 Plan" }
if ($definition.planner_input_snapshot_definition.caller_supplied_planner_content_allowed -ne $false) { Fail "Snapshot definition allows caller-supplied planner content" }
if ($definition.planner_input_snapshot_definition.planner_invocation_performed -ne $false) { Fail "Snapshot definition invokes planner" }
$missingPlanRequest = @{
    idempotency_key = "stage332-no-plan-$token"
    expected_plan_id = "mplan-missing"
    expected_plan_version = 1
    expected_plan_sha256 = ("0".PadRight(64, [char]"0"))
    expected_state_version = 1
    created_by = "stage3.3.2-acceptance"
}
$missingPlan = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot" $missingPlanRequest
if ([int]$missingPlan.status -ne 409 -or $missingPlan.body.code -ne "MISSION_PLANNER_INPUT_SNAPSHOT_GUARD_REJECTED") { Fail "Snapshot without Stage-3.3.1 Plan did not fail closed" }
Pass "Snapshot contract is discoverable and requires a canonical Stage-3.3.1 Plan"

Write-Host "`n[4] Bind Scope + guarded PLANNING + canonical Plan prerequisite"
$scope = Post-Json "$MissionBaseUrl/api/missions/$missionId/scope-contract" (New-ScopePayload $token)
if ([int]$scope.contract_version -ne 1) { Fail "Canonical Scope v1 was not created" }
$bound = Invoke-Lifecycle $missionId "BIND_PIP" "bind-$token"
if ($bound.mission_state.state -ne "PIP_BOUND") { Fail "BIND_PIP did not enter PIP_BOUND" }
$planning = Invoke-Lifecycle $missionId "START_PLANNING" "planning-$token"
if ($planning.mission_state.state -ne "PLANNING") { Fail "START_PLANNING did not enter PLANNING" }
if ($planning.planning_run_activation.planner_invocation_performed -ne $false) { Fail "Stage-3.2.4 activation unexpectedly invoked planner" }
$plan = Post-Json "$MissionBaseUrl/api/missions/$missionId/plan-contract" (New-PlanRequest $missionId "canonical-$token")
if (-not $plan.plan_id.StartsWith("mplan-")) { Fail "Stage-3.3.1 canonical plan_id prefix mismatch" }
if ([int]$plan.plan_version -ne 1) { Fail "Stage-3.3.1 Plan version is not 1" }
if ($plan.plan_contract.task_graph.status -ne "NOT_MATERIALIZED") { Fail "Plan unexpectedly materialized a task graph" }
if ($plan.plan_contract.mission_binding.scope.binding_status -ne "BOUND") { Fail "Plan did not bind canonical Scope" }
if ($plan.plan_contract.mission_binding.scope.scope_sha256 -ne $scope.canonical_sha256) { Fail "Plan Scope hash does not match canonical Scope" }
Pass "Exact Scope + Stage-3.2.4 PLANNING lineage + Stage-3.3.1 Plan prerequisite established"

Write-Host "`n[5] Canonical planner-input snapshot + exact context binding"
$beforeVector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$beforeVector.version_vector.versions.planner_input_snapshot_version -ne 0) { Fail "planner_input_snapshot_version is not 0 before snapshot" }
$snapshotRequest = New-SnapshotRequest $missionId "canonical-$token"
$snapshot = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot" $snapshotRequest
if ($snapshot.idempotent_replay -ne $false) { Fail "First snapshot registration was reported as replay" }
if (-not $snapshot.snapshot_id.StartsWith("mpis-")) { Fail "Canonical snapshot_id prefix mismatch" }
if ([int]$snapshot.snapshot_version -ne 1) { Fail "Canonical snapshot_version is not 1" }
if ($snapshot.plan_id -ne $plan.plan_id -or [int]$snapshot.plan_version -ne 1) { Fail "Snapshot is not bound to exact Plan identity/version" }
if ($snapshot.source_plan_sha256 -ne $plan.canonical_sha256) { Fail "Snapshot source Plan hash mismatch" }
$s = $snapshot.planner_input_snapshot
if ($s.mission_context.mission_id -ne $missionId) { Fail "Snapshot Mission binding mismatch" }
if ($s.plan_binding.plan_id -ne $plan.plan_id -or $s.plan_binding.plan_sha256 -ne $plan.canonical_sha256) { Fail "Snapshot Plan binding mismatch" }
if ($s.plan_binding.task_graph_status -ne "NOT_MATERIALIZED" -or [int]$s.plan_binding.task_count -ne 0 -or [int]$s.plan_binding.dependency_edge_count -ne 0) { Fail "Stage 3.3.2 unexpectedly materialized tasks/dependencies" }
if ($s.lifecycle_context.state -ne "PLANNING" -or [int]$s.lifecycle_context.state_version -ne [int]$snapshotRequest.expected_state_version) { Fail "Snapshot lifecycle context is not exact PLANNING state/version" }
if ($s.lifecycle_context.planning_transition_to_state -ne "PLANNING") { Fail "Snapshot planning lineage mismatch" }
if ($s.scope_context.binding_status -ne "BOUND" -or [int]$s.scope_context.scope_version -ne 1) { Fail "Snapshot did not embed exact canonical Scope" }
if ($s.scope_context.scope_sha256 -ne $scope.canonical_sha256) { Fail "Snapshot Scope hash mismatch" }
if ($s.governance_context.binding_status -ne "UNBOUND") { Fail "Acceptance mission unexpectedly has local Governance binding" }
if ($s.knowledge_context.pip_id -ne "pip-stage332-$token" -or [string]$s.knowledge_context.pip_version -ne "16") { Fail "Snapshot PIP binding mismatch" }
if ($s.context_binding.mode -ne "CANONICAL_DURABLE_LOCAL_FACTS_NO_EXTERNAL_REFRESH") { Fail "Snapshot context mode mismatch" }
if ([string]$s.context_binding.source_context_sha256 -notmatch "^[0-9a-f]{64}$") { Fail "Source-context SHA-256 missing/invalid" }
if ($s.semantics.planner_input_ready -ne $true) { Fail "Snapshot is not marked planner-input ready" }
if ($s.semantics.planner_invocation_performed -ne $false -or $s.semantics.plan_synthesis_performed -ne $false -or $s.semantics.task_decomposition_performed -ne $false) { Fail "Snapshot crossed planner synthesis/decomposition boundary" }
if ($s.semantics.governance_authorization_query_performed -ne $false -or $s.semantics.external_context_refresh_performed -ne $false) { Fail "Snapshot performed forbidden external refresh/authorization query" }
if ($s.semantics.snapshot_is_authorization -ne $false -or $s.semantics.context_is_permission -ne $false) { Fail "Snapshot/context semantics expanded into authorization/permission" }
if ($s.semantics.target_action_dispatch_enabled -ne $false -or $s.semantics.target_actuation -ne $false) { Fail "Snapshot enabled target execution" }
if ([string]$snapshot.canonical_sha256 -notmatch "^[0-9a-f]{64}$" -or $s.integrity.canonical_sha256 -ne $snapshot.canonical_sha256) { Fail "Snapshot canonical SHA-256 integrity mismatch" }
Pass "Immutable snapshot binds exact Mission/Plan/PLANNING/Scope/PIP context without planner invocation or external refresh"

Write-Host "`n[6] Idempotency + immutable request surface"
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot" $snapshotRequest
if ($replay.idempotent_replay -ne $true) { Fail "Exact snapshot retry was not idempotent" }
if ($replay.snapshot_id -ne $snapshot.snapshot_id -or $replay.canonical_sha256 -ne $snapshot.canonical_sha256) { Fail "Snapshot replay changed identity/hash" }
$secondRequest = @{}
$snapshotRequest.GetEnumerator() | ForEach-Object { $secondRequest[$_.Key] = $_.Value }
$secondRequest.idempotency_key = "stage332-snapshot-second-$token"
$second = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot" $secondRequest
if ([int]$second.status -ne 409 -or $second.body.code -ne "MISSION_PLANNER_INPUT_SNAPSHOT_CONFLICT") { Fail "Second immutable snapshot was not rejected" }
$invalidRequest = @{}
$snapshotRequest.GetEnumerator() | ForEach-Object { $invalidRequest[$_.Key] = $_.Value }
$invalidRequest.idempotency_key = "stage332-snapshot-invalid-$token"
$invalidRequest.tasks = @(@{ task_id = "not-allowed" })
$invalid = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot" $invalidRequest
if ([int]$invalid.status -ne 400 -or $invalid.body.code -ne "MISSION_CONTRACT_INVALID") { Fail "Caller-supplied planner/task content was not rejected" }
Pass "Exact replay is stable; second snapshot and caller-supplied planner content fail closed"

Write-Host "`n[7] Version vector + event lineage + repository integrity"
$afterVector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ([int]$afterVector.version_vector.versions.planner_input_snapshot_version -ne 1) { Fail "planner_input_snapshot_version did not advance to 1" }
if ($afterVector.version_sha256 -eq $beforeVector.version_sha256) { Fail "Version-vector SHA-256 did not change after snapshot" }
$stored = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planner-input-snapshot"
if ($stored.snapshot_id -ne $snapshot.snapshot_id -or $stored.canonical_sha256 -ne $snapshot.canonical_sha256) { Fail "Stored snapshot reconstruction mismatch" }
$events = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$snapshotEvents = @($events.events | Where-Object { $_.event_type -eq "MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED" })
if ($snapshotEvents.Count -ne 1) { Fail "Expected exactly one MISSION_PLANNER_INPUT_SNAPSHOT_REGISTERED event" }
if ($snapshotEvents[0].causation_id -ne $snapshot.snapshot_id -or [int]$snapshotEvents[0].plan_version -ne 1) { Fail "Snapshot event causation/Plan version mismatch" }
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repository.integrity_status -ne "PASS") { Fail "Mission repository integrity is not PASS" }
if ([int]$repository.repository.migration_level -ne 10) { Fail "Repository projection migration level is not 10" }
if (@($repository.repository.stores) -notcontains "mission_planner_input_snapshots") { Fail "mission_planner_input_snapshots store is missing" }
if ([int]$repository.record_counts.mission_planner_input_snapshots -ne 1) { Fail "planner-input snapshot record count is not 1" }
if ($repository.persistence_manifest.planner_input_snapshot_store.snapshot_id -ne $snapshot.snapshot_id) { Fail "Persistence manifest snapshot binding mismatch" }
Pass "Snapshot version, event causality, persistence, reconstruction, and repository integrity PASS"

Write-Host "`n[8] Final architecture invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority drifted during acceptance" }
if ($finalHealth.planner_input_snapshot_planner_invocation_performed -ne $false) { Fail "Planner invocation became enabled" }
if ($finalHealth.planner_input_snapshot_task_decomposition_performed -ne $false) { Fail "Task decomposition became enabled" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution became enabled" }
Pass "SNAPSHOT != AUTHORIZATION; CONTEXT != PERMISSION; PLAN != AUTHORIZATION; TASK != DISPATCH; READINESS != PERMISSION; PLANNER != GOVERNANCE"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.3.2 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
