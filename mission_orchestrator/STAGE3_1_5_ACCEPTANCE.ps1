param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780",
    [string]$GovernanceBaseUrl = "http://127.0.0.1:8770",
    [string]$CtiBaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }
function Fail([string]$Message) { Write-Host "[FAIL] $Message" -ForegroundColor Red; exit 1 }

function Get-HttpStatusForPost([string]$Uri, [string]$JsonBody) {
    try {
        $response = Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $JsonBody -UseBasicParsing
        return [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        throw
    }
}

function New-TransitionBody([int]$ExpectedVersion, [string]$ToState, [string]$ReasonCode) {
    return (@{
        expected_state_version = $ExpectedVersion
        to_state = $ToState
        actor = "stage3.1.5-acceptance"
        reason_code = $ReasonCode
        reason = "Stage 3.1.5 governed routing acceptance transition"
        evidence_refs = @()
        metadata = @{ acceptance = "stage3.1.5" }
    } | ConvertTo-Json -Depth 20)
}

function New-ScopeBody([string]$IdempotencyKey, [string]$StartAt, [string]$EndAt) {
    return (@{
        expected_contract_version = 0
        idempotency_key = $IdempotencyKey
        actor = "stage3.1.5-acceptance"
        scope = @{
            targets = @(
                @{
                    target_type = "CIDR"
                    target_value = "127.0.0.0/8"
                    environment = "LAB"
                }
            )
            excluded_targets = @()
            network_ranges = @("127.0.0.0/8")
            domains = @()
            services = @()
        }
        roe = @{
            allowed_action_classes = @("INTERNAL_REASONING", "TARGET_RECON")
            prohibited_action_classes = @("DESTRUCTIVE_ACTION")
            allowed_time_window = @{
                start_at = $StartAt
                end_at = $EndAt
            }
            maximum_concurrency = 2
            destructive_actions_allowed = $false
            credential_usage_allowed = $false
            persistence_allowed = $false
            human_approval_required_for = @()
        }
        constraints = @{
            max_actions = 20
            max_duration = 1800
            risk_threshold = "MODERATE"
            resource_budget = @{
                max_network_requests = 100
                max_parallel_targets = 1
            }
            data_handling_policy = @{
                classification = "INTERNAL"
                retention_days = 7
                export_allowed = $false
            }
        }
        reason = "Stage 3.1.5 canonical routing boundary"
        metadata = @{
            environment = "LAB"
            acceptance = "stage3.1.5"
        }
    } | ConvertTo-Json -Depth 30)
}

function New-BindingBody([string]$IdempotencyKey) {
    return (@{
        expected_binding_version = 0
        idempotency_key = $IdempotencyKey
        actor = "stage3.1.5-acceptance"
        policy_set_id = "default-policy"
        name = "Stage 3.1.5 governed CTI routing binding"
        capabilities = @(
            @{
                capability_id = "orchestrator.route.cti"
                subject_component = "CTI-A01"
                action_class = "INTERNAL_REASONING"
                action_name = "START_CTI_MISSION"
                authorization_mode = "NOT_REQUIRED_INTERNAL"
                resource_types = @()
                max_risk_level = "LOW"
                requires_human_approval = $false
            },
            @{
                capability_id = "pentest.recon"
                subject_component = "CTI-A02"
                action_class = "TARGET_RECON"
                action_name = "recon"
                authorization_mode = "REQUIRED"
                resource_types = @("IP")
                max_risk_level = "MODERATE"
                requires_human_approval = $false
            }
        )
        reason = "Bind non-actuating CTI route while preserving target-action authority"
        metadata = @{
            environment = "LAB"
            acceptance = "stage3.1.5"
        }
    } | ConvertTo-Json -Depth 30)
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.5 - Governed Task Routing Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"
Write-Host "Governance           : $GovernanceBaseUrl"
Write-Host "VulnDesk CTI         : $CtiBaseUrl"

Write-Host "`n[1] Full regression"
Push-Location $PSScriptRoot
try {
    & python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Python regression failed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.1.5 regression"

Write-Host "`n[2] Mission Orchestrator Stage-3.1.5 health / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health status is not ok" }
if ($health.component_id -ne "APTS-MO01") { Fail "Unexpected Mission Orchestrator component_id" }
if ($health.control_version -ne "stage3.1.5-governed-task-routing") { Fail "Unexpected Stage-3.1.5 control_version" }
if ($health.governed_task_routing_mode -ne "BOUND_INTERNAL_CAPABILITY_DERIVED_DESTINATION_FAIL_CLOSED") { Fail "Unexpected governed task routing mode" }
if ($health.subsystem_routing_dispatch_enabled -ne $true) { Fail "Subsystem routing dispatch is not enabled" }
if (@($health.supported_routing_subsystems) -notcontains "CTI") { Fail "CTI is not listed as a supported routing subsystem" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Mission Orchestrator incorrectly owns policy authorization" }
if ($health.dispatch_enabled -ne $false) { Fail "Target-action dispatch_enabled must remain false" }
if ($health.target_action_dispatch_enabled -ne $false) { Fail "target_action_dispatch_enabled must remain false" }
if ($health.target_actuation -ne $false) { Fail "target_actuation must remain false" }
if ($health.pre_dispatch_revalidation_required -ne $true) { Fail "Downstream target pre-dispatch revalidation must remain required" }
Pass "Subsystem mission routing is enabled without enabling target-action dispatch"

Write-Host "`n[3] Authoritative Governance preflight"
$govHealth = Invoke-RestMethod "$GovernanceBaseUrl/health"
if ($govHealth.component_id -ne "GOV-PLANE") { Fail "Unexpected Governance component_id" }
if ($govHealth.readiness_status -eq "NOT_READY") { Fail "Governance readiness_status=NOT_READY" }
$emergency = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/emergency-stop"
if ($emergency.status -ne "completed" -or $null -eq $emergency.emergency_state) { Fail "Cannot read Governance emergency-stop state" }
if ([bool]$emergency.emergency_state.active) {
    Fail "Governance emergency stop is ACTIVE. Acceptance will not release a safety control."
}
Pass "GOV-PLANE is reachable and emergency stop is not active"

Write-Host "`n[4] VulnDesk CTI preflight"
$ctiHealth = Invoke-RestMethod "$CtiBaseUrl/health"
if ($ctiHealth.component_id -ne "CTI-INF01") { Fail "Unexpected CTI component_id" }
if ($ctiHealth.readiness_status -eq "NOT_READY") { Fail "CTI readiness_status=NOT_READY" }
Pass "CTI subsystem is reachable: component_id=CTI-INF01"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
$now = [DateTimeOffset]::UtcNow
$startAt = $now.AddMinutes(-5).ToString("o")
$endAt = $now.AddHours(2).ToString("o")

$missionBody = @{
    idempotency_key = "stage315-mission-$token"
    source_system = "POWERSHELL_ACCEPTANCE"
    created_by = "stage3.1.5-acceptance"
    client_request_id = "client-$token"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{
        type = "SECURITY_VALIDATION"
        target_ref = "stage315-lab"
    }
    success_criteria = @(
        @{ metric = "cti_subsystem_routed"; expected = $true }
    )
    budgets = @{
        time_seconds = 1800
        max_actions = 20
        risk_ceiling = "MODERATE"
    }
    required_subsystems = @("CTI")
    metadata = @{
        environment = "LAB"
        acceptance = "stage3.1.5"
    }
} | ConvertTo-Json -Depth 20

Write-Host "`n[5] Create canonical mission"
$created = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions" -ContentType "application/json" -Body $missionBody
$missionId = [string]$created.canonical_identity.mission_id
$envelopeHash = [string]$created.envelope.integrity.canonical_sha256
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Invalid canonical mission id" }
$initialState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($initialState.mission_state.state -ne "CREATED" -or [int]$initialState.mission_state.state_version -ne 1) { Fail "Mission did not start in CREATED/v1" }
Pass "Canonical mission created: $missionId"

Write-Host "`n[6] Create canonical Scope/RoE/Constraint snapshot"
$scopeBody = New-ScopeBody "stage315-scope-$token" $startAt $endAt
$scope = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/scope-contract" -ContentType "application/json" -Body $scopeBody
if ([int]$scope.contract_version -ne 1) { Fail "Expected scope contract v1" }
if ([string]$scope.canonical_sha256 -notmatch '^[0-9a-f]{64}$') { Fail "Invalid canonical scope hash" }
$scopeSnapshot = [string]$scope.snapshot_id
$scopeHash = [string]$scope.canonical_sha256
Pass "Canonical scope created: $scopeSnapshot"

Write-Host "`n[7] Bind governed CTI routing capability through authoritative Governance"
$bindingBody = New-BindingBody "stage315-binding-$token"
$binding = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/governance-binding" -ContentType "application/json" -Body $bindingBody
if ($binding.binding_status -ne "CURRENT" -or $binding.binding_current_for_scope -ne $true) { Fail "Governance binding is not current" }
if ([int]$binding.binding_version -ne 1) { Fail "Expected Governance binding v1" }
$routeCapabilities = @($binding.binding.capabilities | Where-Object { $_.capability_id -eq "orchestrator.route.cti" })
if ($routeCapabilities.Count -ne 1) { Fail "CTI routing capability was not persisted exactly once" }
$routeCapability = $routeCapabilities[0]
if ($routeCapability.subject_component -ne "CTI-A01" -or $routeCapability.action_class -ne "INTERNAL_REASONING" -or $routeCapability.authorization_mode -ne "NOT_REQUIRED_INTERNAL") {
    Fail "Persisted CTI routing capability does not preserve non-actuating semantics"
}
if ($binding.binding.governance_authority.authorization_authority -ne "aptsGSS" -or $binding.binding.governance_authority.authorization_authority_component -ne "GOV-PLANE") {
    Fail "Governance authority provenance mismatch"
}
Pass "Current canonical scope is bound to aptsGSS with a non-actuating CTI route capability"

Write-Host "`n[8] Advance canonical state CREATED -> PIP_BOUND -> PLANNING"
$t1 = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/state/transitions" -ContentType "application/json" -Body (New-TransitionBody 1 "PIP_BOUND" "PIP_BOUND_FOR_ROUTING")
if ($t1.mission_state.state -ne "PIP_BOUND" -or [int]$t1.mission_state.state_version -ne 2) { Fail "CREATED -> PIP_BOUND transition failed" }
$t2 = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/state/transitions" -ContentType "application/json" -Body (New-TransitionBody 2 "PLANNING" "PLANNING_FOR_ROUTING")
if ($t2.mission_state.state -ne "PLANNING" -or [int]$t2.mission_state.state_version -ne 3) { Fail "PIP_BOUND -> PLANNING transition failed" }
Pass "Canonical mission is PLANNING/v3"

Write-Host "`n[9] Create immutable governed CTI routing task"
$taskBody = @{
    idempotency_key = "stage315-task-$token"
    capability_id = "orchestrator.route.cti"
    task_input = @{
        auto_acquire_cti = $false
        mission_objective = @{
            type = "PENTEST_INTELLIGENCE_ENRICHMENT"
            acceptance = "stage3.1.5"
        }
        intelligence_requirements = @()
        metadata = @{
            acceptance = "stage3.1.5"
        }
    }
    requested_by = "stage3.1.5-acceptance"
    reason = "Start the required CTI subsystem mission"
    metadata = @{
        environment = "LAB"
        acceptance = "stage3.1.5"
    }
} | ConvertTo-Json -Depth 30

$task = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/routing-tasks" -ContentType "application/json" -Body $taskBody
$taskId = [string]$task.task_id
if (-not $taskId.StartsWith("mtask-")) { Fail "Invalid governed task id" }
if ($task.task_status -ne "READY") { Fail "New governed task must be READY" }
if ($task.destination_subsystem -ne "CTI" -or $task.destination_component -ne "CTI-A01") { Fail "CTI route was not derived from bound subject_component" }
if ($task.task_contract.routing.dispatch_path -ne "/api/cti/missions/start") { Fail "Unexpected CTI dispatch path" }
if ($task.task_contract.canonical_scope_binding.mission_scope_snapshot_id -ne $scopeSnapshot -or $task.task_contract.canonical_scope_binding.mission_scope_sha256 -ne $scopeHash) { Fail "Task lost canonical scope snapshot lineage" }
if ([int]$task.task_contract.governance_binding.governance_binding_version -ne 1) { Fail "Task lost Governance binding version" }
if ($task.task_contract.semantics.target_action_dispatch -ne $false -or $task.task_contract.semantics.target_actuation -ne $false) { Fail "Task unexpectedly enables target action/actuation" }
if ($task.task_contract.semantics.downstream_governance_revalidation_required_for_target_actions -ne $true) { Fail "Downstream target governance revalidation marker missing" }
if ([string]$task.canonical_sha256 -notmatch '^[0-9a-f]{64}$') { Fail "Invalid routed task SHA-256" }
Pass "Immutable routed task created: $taskId"

Write-Host "`n[10] Routing task idempotency and target-action fail-closed gate"
$taskReplay = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/routing-tasks" -ContentType "application/json" -Body $taskBody
if ($taskReplay.idempotent_replay -ne $true -or $taskReplay.task_id -ne $taskId) { Fail "Identical task replay was not idempotent" }
$targetTaskBody = @{
    idempotency_key = "stage315-target-task-$token"
    capability_id = "pentest.recon"
    task_input = @{ target = "127.0.0.1" }
    requested_by = "stage3.1.5-acceptance"
    reason = "Negative acceptance: target capability must not use subsystem routing"
    metadata = @{ acceptance = "stage3.1.5-negative" }
} | ConvertTo-Json -Depth 20
$targetStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/routing-tasks" $targetTaskBody
if ($targetStatus -ne 403) { Fail "REQUIRED target capability must fail closed with HTTP 403 (actual=$targetStatus)" }
Pass "Task replay is idempotent and REQUIRED target capability cannot use subsystem mission routing"

Write-Host "`n[11] Dispatch is blocked before RUNNING"
$preRunningStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/routing-tasks/$taskId/dispatch" "{}"
if ($preRunningStatus -ne 403) { Fail "Dispatch in PLANNING must fail closed with HTTP 403 (actual=$preRunningStatus)" }
Pass "Canonical lifecycle gate blocks dispatch while PLANNING"

Write-Host "`n[12] Advance PLANNING -> RUNNING and dispatch CTI subsystem mission"
$t3 = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/state/transitions" -ContentType "application/json" -Body (New-TransitionBody 3 "RUNNING" "START_GOVERNED_SUBSYSTEM_ROUTING")
if ($t3.mission_state.state -ne "RUNNING" -or [int]$t3.mission_state.state_version -ne 4) { Fail "PLANNING -> RUNNING transition failed" }
$dispatch = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/routing-tasks/$taskId/dispatch" -ContentType "application/json" -Body "{}"
if ($dispatch.task_status -ne "DISPATCHED") { Fail "Governed task was not DISPATCHED" }
if ($dispatch.dispatch_response.mission_id -ne $missionId) { Fail "CTI dispatch did not preserve canonical mission id" }
if (@($dispatch.dispatch_attempts).Count -ne 1) { Fail "Expected exactly one first dispatch attempt" }
if ($dispatch.dispatch_attempts[0].status -ne "COMPLETED") { Fail "First dispatch attempt was not COMPLETED" }
Pass "CTI subsystem mission accepted under canonical mission id"

Write-Host "`n[13] Verify exact CTI mission readback and dispatch replay"
$encodedMissionId = [uri]::EscapeDataString($missionId)
$ctiMissionEnvelope = Invoke-RestMethod "$CtiBaseUrl/api/cti/missions/$encodedMissionId"
if ($ctiMissionEnvelope.status -ne "completed" -or $null -eq $ctiMissionEnvelope.mission) { Fail "Malformed CTI mission-status envelope" }
if ($ctiMissionEnvelope.mission.mission_id -ne $missionId) { Fail "CTI mission identity differs from global canonical mission id" }
if ([string]$ctiMissionEnvelope.mission.status -eq "NOT_FOUND") { Fail "Dispatched CTI mission was not durably/readably created" }
$dispatchReplay = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/routing-tasks/$taskId/dispatch" -ContentType "application/json" -Body "{}"
if ($dispatchReplay.idempotent_replay -ne $true) { Fail "Dispatch replay must be idempotent" }
if (@($dispatchReplay.dispatch_attempts).Count -ne 1) { Fail "Dispatch replay created a duplicate CTI dispatch attempt" }
Pass "CTI readback preserves mission identity and dispatch replay creates no duplicate POST attempt"

Write-Host "`n[14] Read-only cross-subsystem routing projection"
$stateBeforeProjection = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
$projection = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/routing-projection"
$stateAfterProjection = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($projection.canonical_state_mutated -ne $false) { Fail "Routing projection claims to mutate canonical state" }
if ($projection.canonical_state -ne "RUNNING" -or [int]$projection.canonical_state_version -ne 4) { Fail "Projection lost canonical RUNNING/v4 state" }
if ([int]$projection.task_count -ne 1) { Fail "Routing projection must contain exactly one routed task" }
if ($projection.tasks[0].task_id -ne $taskId -or $projection.tasks[0].destination_subsystem -ne "CTI") { Fail "Projection lost routed task identity" }
if ($stateBeforeProjection.mission_state.state -ne $stateAfterProjection.mission_state.state -or [int]$stateBeforeProjection.mission_state.state_version -ne [int]$stateAfterProjection.mission_state.state_version) {
    Fail "Read-only routing projection mutated canonical mission state"
}
Pass "Routing projection is cross-subsystem/read-only; canonical state remains RUNNING/v4"

Write-Host "`n[15] Final immutable lineage and authority-boundary checks"
$finalTask = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/routing-tasks/$taskId"
$finalEnvelope = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/envelope"
$finalBinding = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/governance-binding"
if ($finalTask.canonical_sha256 -ne $task.canonical_sha256) { Fail "Routed task canonical hash changed after dispatch" }
if ($finalTask.task_contract.integrity.canonical_sha256 -ne $task.canonical_sha256) { Fail "Task-contract integrity hash mismatch" }
if ($finalEnvelope.envelope.integrity.canonical_sha256 -ne $envelopeHash) { Fail "Routing mutated immutable mission envelope" }
if ($finalBinding.binding_status -ne "CURRENT" -or $finalBinding.binding_current_for_scope -ne $true) { Fail "Routing changed/staled Governance binding" }
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.dispatch_enabled -ne $false -or $finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) {
    Fail "Target-action authority boundary changed during acceptance"
}
Pass "Immutable task/envelope/binding lineage preserved and target-action dispatch remains disabled"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.5 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "MissionId          : $missionId"
Write-Host "RoutingTask        : $taskId"
Write-Host "ScopeSnapshot      : $scopeSnapshot"
Write-Host "GovernanceBinding  : v$($binding.binding_version)"
Write-Host "CTI status         : $($ctiMissionEnvelope.mission.status)"
Write-Host "Routing projection : $($projection.routing_projection)"
Write-Host "Canonical state    : $($stateAfterProjection.mission_state.state)/v$($stateAfterProjection.mission_state.state_version)"
Write-Host "Target dispatch    : $($finalHealth.target_action_dispatch_enabled)"
Write-Host "=============================================================================="
