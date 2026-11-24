param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780",
    [string]$GovernanceBaseUrl = "http://127.0.0.1:8770",
    [string]$CtiBaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.1.10 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Post-Json([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 60 -Compress
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
}

function Get-HttpStatusForPost([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 60 -Compress
    try {
        $response = Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $json -UseBasicParsing
        return [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        throw
    }
}

function New-Transition([int]$ExpectedVersion, [string]$ToState, [string]$ReasonCode) {
    return @{
        expected_state_version = $ExpectedVersion
        to_state = $ToState
        actor = "stage3.1.10-acceptance"
        reason_code = $ReasonCode
        reason = "Stage 3.1.10 acceptance/regression transition"
        evidence_refs = @()
        metadata = @{ acceptance = "stage3.1.10" }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.10 - Acceptance & Regression Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"
Write-Host "Governance           : $GovernanceBaseUrl"
Write-Host "VulnDesk CTI         : $CtiBaseUrl"

Write-Host "`n[1] Python compile + full Stage-3.1 regression"
Push-Location $PSScriptRoot
try {
    & python -m compileall -q mission_orchestrator tests
    if ($LASTEXITCODE -ne 0) { Fail "Python compile gate failed" }
    $pytestOutput = & python -m pytest -q 2>&1
    $pytestOutput | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Fail "Full regression suite failed" }
    if (($pytestOutput -join "`n") -notmatch "111 passed") { Fail "Expected Stage-3.1.10 baseline '111 passed'" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.1.10 regression baseline: 111 passed"

Write-Host "`n[2] Mission health + Stage-3.1 closure contract + authority boundary"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)"
}
if ($health.status -ne "ok" -or $health.component_id -ne "APTS-MO01") { Fail "Mission Orchestrator identity/health mismatch" }
if ($health.control_version -ne "stage3.1.10-acceptance-regression-gate") { Fail "Unexpected control_version: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Repository migration level changed; Stage 3.1.10 expects 8" }
if ($health.stage3_1_acceptance_gate_schema_version -ne "apts-mission-stage3.1-acceptance-gate-v1") { Fail "Acceptance-gate schema mismatch" }
if ($health.stage3_1_acceptance_gate_mode -ne "FULL_REGRESSION_PLUS_LIVE_CONTRACT_PROBES") { Fail "Acceptance-gate mode mismatch" }
if ($health.stage3_1_acceptance_gate_baseline -ne "STAGE_3_1_1_THROUGH_3_1_9") { Fail "Acceptance-gate baseline mismatch" }
if ($health.stage3_1_acceptance_gate_database_change_mode -ne "NO_NEW_DATABASE_MIGRATION") { Fail "Stage 3.1.10 must not add a database migration" }
if ($health.stage3_1_acceptance_gate_runtime_change_mode -ne "NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY") { Fail "Stage 3.1.10 runtime-change mode mismatch" }
if ($health.stage3_1_acceptance_gate_declared_only -ne $true -or $health.stage3_1_acceptance_gate_runtime_self_certification -ne $false) {
    Fail "Runtime must declare the gate but must not self-certify PASS"
}
$requiredControls = @(
    "stage3.1.1-canonical-mission-identity-envelope",
    "stage3.1.2-canonical-mission-state-model",
    "stage3.1.3-mission-scope-roe-constraint-contract",
    "stage3.1.4-governance-authorization-binding-contract",
    "stage3.1.5-governed-task-routing",
    "stage3.1.6-mission-versioning-concurrency",
    "stage3.1.7-mission-persistence-repository-model",
    "stage3.1.8-canonical-mission-api-validation-layer",
    "stage3.1.9-mission-event-lineage-foundation",
    "stage3.1.10-acceptance-regression-gate"
)
foreach ($control in $requiredControls) {
    if (@($health.supported_controls) -notcontains $control) { Fail "Missing supported control: $control" }
}
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.dispatch_enabled -ne $false -or $health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) {
    Fail "Target execution authority must remain disabled"
}
Pass "Closure metadata is active; no migration, authority, or target-execution expansion"

Write-Host "`n[3] Governance + CTI readiness / safety preflight"
try {
    $govHealth = Invoke-RestMethod "$GovernanceBaseUrl/health"
    $emergency = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/emergency-stop"
    $ctiHealth = Invoke-RestMethod "$CtiBaseUrl/health"
} catch {
    Fail "Cross-subsystem readiness probe failed: $($_.Exception.Message)"
}
if ($govHealth.component_id -ne "GOV-PLANE") { Fail "Unexpected Governance component_id" }
if ($govHealth.readiness_status -eq "NOT_READY") { Fail "Governance readiness_status=NOT_READY" }
if ($null -eq $emergency.emergency_state) { Fail "Governance emergency-stop response malformed" }
if ([bool]$emergency.emergency_state.active) { Fail "Governance emergency stop is ACTIVE; acceptance will not release a safety control" }
if ($ctiHealth.component_id -ne "CTI-INF01") { Fail "Unexpected CTI component_id" }
if ($ctiHealth.readiness_status -eq "NOT_READY") { Fail "CTI readiness_status=NOT_READY" }
Pass "GOV-PLANE and CTI are reachable; emergency stop is inactive"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))
$now = [DateTimeOffset]::UtcNow
$startAt = $now.AddMinutes(-5).ToString("o")
$endAt = $now.AddHours(2).ToString("o")

$missionPayload = @{
    idempotency_key = "stage3110-mission-$token"
    source_system = "STAGE3110_ACCEPTANCE"
    created_by = "stage3.1.10-acceptance"
    client_request_id = "client-$token"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage3110-lab" }
    success_criteria = @(@{ metric = "stage31_acceptance_gate"; expected = $true })
    budgets = @{ time_seconds = 1800; max_actions = 20; risk_ceiling = "MODERATE" }
    required_subsystems = @("CTI")
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.10" }
}

$scopePayload = @{
    expected_contract_version = 0
    idempotency_key = "stage3110-scope-$token"
    actor = "stage3.1.10-acceptance"
    scope = @{
        targets = @(@{ target_type = "CIDR"; target_value = "127.0.0.0/8"; environment = "LAB" })
        excluded_targets = @()
        network_ranges = @("127.0.0.0/8")
        domains = @()
        services = @()
    }
    roe = @{
        allowed_action_classes = @("INTERNAL_REASONING", "TARGET_RECON")
        prohibited_action_classes = @("DESTRUCTIVE_ACTION")
        allowed_time_window = @{ start_at = $startAt; end_at = $endAt }
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
        resource_budget = @{ max_network_requests = 100; max_parallel_targets = 1 }
        data_handling_policy = @{ classification = "INTERNAL"; retention_days = 7; export_allowed = $false }
    }
    reason = "Stage 3.1.10 final Stage-3.1 canonical closure"
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.10" }
}

Write-Host "`n[4] Canonical preflight validation remains zero-side-effect"
try {
    $validation = Post-Json "$MissionBaseUrl/api/missions/validate" @{ mission = $missionPayload; scope_contract = $scopePayload }
} catch {
    Fail "Canonical preflight failed: $($_.Exception.Message)"
}
if ($validation.valid -ne $true -or $validation.status -ne "valid") { Fail "Canonical preflight did not return valid=true" }
if ((@($validation.checks | ForEach-Object { $_.phase }) -join ",") -ne "SCHEMA,SEMANTIC,SCOPE,CONSTRAINTS") { Fail "Preflight did not execute all four validation phases" }
if ($validation.persistence_performed -ne $false -or $validation.authority_query_performed -ne $false -or $validation.planning_performed -ne $false -or $validation.target_action_performed -ne $false) {
    Fail "Preflight performed a forbidden side effect"
}
Pass "Schema -> semantic -> scope -> constraints preflight PASS with zero side effects"

Write-Host "`n[5] Canonical identity + create replay + root event"
try {
    $created = Post-Json "$MissionBaseUrl/api/missions" $missionPayload
    $replay = Post-Json "$MissionBaseUrl/api/missions" $missionPayload
} catch {
    Fail "Mission create/replay failed: $($_.Exception.Message)"
}
if ($created.idempotent_replay -ne $false -or $replay.idempotent_replay -ne $true) { Fail "Mission create/replay idempotency failed" }
$missionId = [string]$created.canonical_identity.mission_id
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Unexpected canonical mission id: $missionId" }
$rootView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ([int]$rootView.event_count -ne 1 -or @($rootView.events)[0].event_type -ne "MISSION_REGISTERED") { Fail "Canonical root event was not created exactly once" }
Pass "Canonical identity and replay gate PASS: $missionId"

Write-Host "`n[6] Scope/RoE/Constraint commit + immutable replay + canonical projection"
try {
    $scope = Post-Json "$MissionBaseUrl/api/missions/$missionId/scope-contract" $scopePayload
    $scopeReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/scope-contract" $scopePayload
    $contract = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/canonical-contract"
} catch {
    Fail "Scope/canonical-contract probe failed: $($_.Exception.Message)"
}
if ([int]$scope.contract_version -ne 1 -or $scopeReplay.idempotent_replay -ne $true) { Fail "Scope v1/replay gate failed" }
if ($contract.contract_complete -ne $true -or $contract.contract_status -ne "SCOPE_BOUND") { Fail "Canonical contract is not complete/SCOPE_BOUND" }
if ($contract.external_authority_query_performed -ne $false -or $contract.target_action_dispatch_enabled -ne $false -or $contract.target_actuation -ne $false) {
    Fail "Canonical contract projection crossed an authority/execution boundary"
}
Pass "Immutable Scope/RoE/Constraint v1 and local canonical projection PASS"

Write-Host "`n[7] Governance binding + authoritative target authorization provenance"
$bindingPayload = @{
    expected_binding_version = 0
    idempotency_key = "stage3110-binding-$token"
    actor = "stage3.1.10-acceptance"
    policy_set_id = "default-policy"
    name = "Stage 3.1.10 closure binding"
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
    reason = "Bind safe internal CTI routing and externally-authorized target capability"
    metadata = @{ acceptance = "stage3.1.10" }
}
try {
    $binding = Post-Json "$MissionBaseUrl/api/missions/$missionId/governance-binding" $bindingPayload
    $bindingReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/governance-binding" $bindingPayload
} catch {
    Fail "Governance binding failed: $($_.Exception.Message)"
}
if ([int]$binding.binding_version -ne 1 -or $bindingReplay.idempotent_replay -ne $true) { Fail "Governance binding v1/replay failed" }
if ($binding.binding.governance_authority.authorization_authority -ne "aptsGSS" -or $binding.binding.governance_authority.authorization_authority_component -ne "GOV-PLANE") {
    Fail "Governance authority identity was not preserved"
}
$authPayload = @{
    idempotency_key = "stage3110-auth-$token"
    capability_id = "pentest.recon"
    resource_type = "IP"
    resource_value = "127.0.0.1"
    context = @{ environment = "LAB"; acceptance = "stage3.1.10" }
    evidence_refs = @("evidence://stage3.1.10/authorization")
    requested_by = "stage3.1.10-acceptance"
    metadata = @{ acceptance = "stage3.1.10" }
}
try {
    $auth = Post-Json "$MissionBaseUrl/api/missions/$missionId/authorization-bindings" $authPayload
} catch {
    Fail "Authoritative Governance authorization probe failed: $($_.Exception.Message)"
}
if ($auth.authorization_binding.decision_provenance.authorization_authority -ne "aptsGSS") { Fail "Authorization provenance lost aptsGSS authority" }
if ($auth.authorization_binding.decision_provenance.authorization_authority_component -ne "GOV-PLANE") { Fail "Authorization provenance lost GOV-PLANE authority" }
if ($auth.execution_authorized -ne $false -or $auth.authorization_binding.execution_authorized -ne $false) { Fail "Authorization binding must not become execution authorization" }
if ($auth.governance_status -ne "AUTHORIZED" -or $auth.authorization_granted -ne $true) { Fail "Expected authoritative ALLOW for in-scope lab recon capability" }
Pass "External PolicyDecision provenance is bound without granting target execution authority"

Write-Host "`n[8] Canonical lifecycle + governed internal CTI routing + target-route fail-closed"
try {
    $t1 = Post-Json "$MissionBaseUrl/api/missions/$missionId/state/transitions" (New-Transition 1 "PIP_BOUND" "STAGE3110_PIP_BOUND")
    $t2 = Post-Json "$MissionBaseUrl/api/missions/$missionId/state/transitions" (New-Transition 2 "PLANNING" "STAGE3110_PLANNING")
} catch {
    Fail "CREATED -> PIP_BOUND -> PLANNING failed: $($_.Exception.Message)"
}
if ($t2.mission_state.state -ne "PLANNING" -or [int]$t2.mission_state.state_version -ne 3) { Fail "Mission did not reach PLANNING/v3" }
$taskPayload = @{
    idempotency_key = "stage3110-task-$token"
    capability_id = "orchestrator.route.cti"
    task_input = @{
        auto_acquire_cti = $false
        mission_objective = @{ type = "PENTEST_INTELLIGENCE_ENRICHMENT"; acceptance = "stage3.1.10" }
        intelligence_requirements = @()
        metadata = @{ acceptance = "stage3.1.10" }
    }
    requested_by = "stage3.1.10-acceptance"
    reason = "Start required CTI subsystem mission without target actuation"
    metadata = @{ acceptance = "stage3.1.10" }
}
try {
    $task = Post-Json "$MissionBaseUrl/api/missions/$missionId/routing-tasks" $taskPayload
    $taskReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/routing-tasks" $taskPayload
} catch {
    Fail "Governed CTI routing task create/replay failed: $($_.Exception.Message)"
}
$taskId = [string]$task.task_id
if ($task.task_status -ne "READY" -or $taskReplay.idempotent_replay -ne $true) { Fail "Governed task READY/replay gate failed" }
if ($task.task_contract.semantics.target_action_dispatch -ne $false -or $task.task_contract.semantics.target_actuation -ne $false) { Fail "Internal CTI route claims target execution capability" }
$targetRouteStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/routing-tasks" @{
    idempotency_key = "stage3110-target-route-$token"
    capability_id = "pentest.recon"
    task_input = @{ target = "127.0.0.1" }
    requested_by = "stage3.1.10-acceptance"
    reason = "Negative gate: target capability must not use subsystem routing"
    metadata = @{ acceptance = "stage3.1.10-negative" }
}
if ($targetRouteStatus -ne 403) { Fail "Target capability routing must fail closed with HTTP 403 (actual=$targetRouteStatus)" }
try {
    $t3 = Post-Json "$MissionBaseUrl/api/missions/$missionId/state/transitions" (New-Transition 3 "RUNNING" "STAGE3110_RUNNING")
    $dispatch = Post-Json "$MissionBaseUrl/api/missions/$missionId/routing-tasks/$taskId/dispatch" @{}
    $dispatchReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/routing-tasks/$taskId/dispatch" @{}
} catch {
    Fail "RUNNING transition / CTI dispatch failed: $($_.Exception.Message)"
}
if ($t3.mission_state.state -ne "RUNNING" -or [int]$t3.mission_state.state_version -ne 4) { Fail "Mission did not reach RUNNING/v4" }
if ($dispatch.task_status -ne "DISPATCHED" -or $dispatchReplay.idempotent_replay -ne $true) { Fail "CTI dispatch/replay gate failed" }
if (@($dispatchReplay.dispatch_attempts).Count -ne 1) { Fail "Dispatch replay created a duplicate external attempt" }
$encodedMissionId = [uri]::EscapeDataString($missionId)
$ctiMissionEnvelope = Invoke-RestMethod "$CtiBaseUrl/api/cti/missions/$encodedMissionId"
if ($ctiMissionEnvelope.status -ne "completed" -or $ctiMissionEnvelope.mission.mission_id -ne $missionId) { Fail "CTI readback did not preserve global mission identity" }
Pass "Internal CTI route dispatched exactly once; target-capability route remains fail-closed"

Write-Host "`n[9] Version vector + guarded command success/replay + stale rejection"
try {
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
} catch {
    Fail "Version-vector read failed: $($_.Exception.Message)"
}
if ($vector.version_vector_complete -ne $true) { Fail "Version vector is incomplete after CTI dispatch" }
if ($null -eq $vector.version_vector.versions.policy_version) { Fail "Authoritative policy_version is absent from version vector" }
if ($null -eq $vector.version_vector.versions.cti_state_version -or $null -eq $vector.version_vector.versions.cti_plan_version) { Fail "CTI state/plan versions are absent from version vector" }
$versionToken = [string]$vector.version_sha256
$commandId = "cmd-stage3110-$token"
$command = @{
    command_id = $commandId
    idempotency_key = "idem-$commandId"
    operation = "STATE_TRANSITION"
    expected_version_sha256 = $versionToken
    payload = New-Transition 4 "REPLANNING" "STAGE3110_COMMAND_REPLANNING"
    submitted_by = "stage3.1.10-acceptance"
    metadata = @{ acceptance = "stage3.1.10" }
}
try {
    $commandResult = Post-Json "$MissionBaseUrl/api/missions/$missionId/commands" $command
    $commandReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/commands" $command
} catch {
    Fail "Guarded command success/replay failed: $($_.Exception.Message)"
}
if ($commandResult.idempotent_replay -ne $false -or $commandReplay.idempotent_replay -ne $true) { Fail "Command idempotency failed" }
if ($commandResult.result.mission_state.state -ne "REPLANNING" -or [int]$commandResult.result.mission_state.state_version -ne 5) { Fail "Guarded command did not produce REPLANNING/v5" }
$staleCommand = @{
    command_id = "cmd-stage3110-stale-$token"
    idempotency_key = "idem-stale-$token"
    operation = "STATE_TRANSITION"
    expected_version_sha256 = $versionToken
    payload = New-Transition 5 "RUNNING" "STAGE3110_STALE_REJECT"
    submitted_by = "stage3.1.10-acceptance"
    metadata = @{ acceptance = "stage3.1.10-stale" }
}
$staleStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/commands" $staleCommand
if ($staleStatus -ne 409) { Fail "Stale version-vector command must fail with HTTP 409 (actual=$staleStatus)" }
$staleRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands/$($staleCommand.command_id)"
if ($staleRead.command_status -ne "REJECTED_STALE") { Fail "Stale command was not journaled as REJECTED_STALE" }
Pass "Version vector includes policy/CTI domains; command replay is idempotent and stale writes fail closed"

Write-Host "`n[10] Event lineage + durable repository integrity closure"
try {
    $eventsView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
    $lineage = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/lineage"
    $repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
} catch {
    Fail "Event/lineage/repository closure read failed: $($_.Exception.Message)"
}
if ($eventsView.integrity_status -ne "PASS" -or $lineage.integrity_status -ne "PASS" -or $repository.integrity_status -ne "PASS") { Fail "One or more integrity projections did not PASS" }
$eventTypes = @($eventsView.events | ForEach-Object { $_.event_type })
foreach ($requiredEvent in @(
    "MISSION_REGISTERED",
    "MISSION_SCOPE_CONTRACT_COMMITTED",
    "MISSION_GOVERNANCE_BOUND",
    "MISSION_AUTHORIZATION_BOUND",
    "MISSION_STATE_TRANSITIONED",
    "MISSION_ROUTING_TASK_CREATED",
    "MISSION_ROUTING_TASK_DISPATCHED",
    "MISSION_COMMAND_COMPLETED"
)) {
    if ($eventTypes -notcontains $requiredEvent) { Fail "Final lineage missing event type: $requiredEvent" }
}
if ([int]$repository.record_counts.mission_events -ne [int]$eventsView.event_count) { Fail "Repository/event count mismatch" }
$eventIntegrityCheck = @($repository.integrity_checks | Where-Object { $_.check -eq "mission_event_append_only_hash_chain" })
if ($eventIntegrityCheck.Count -ne 1 -or $eventIntegrityCheck[0].status -ne "PASS") { Fail "Repository event hash-chain check did not PASS" }
if ($lineage.external_authority_query_performed -ne $false -or $lineage.target_action_dispatch_enabled -ne $false -or $lineage.target_actuation -ne $false) {
    Fail "Lineage read changed authority/execution boundary"
}
Pass "Canonical events, lineage, persistence manifest, and append-only hash chain all PASS"

Write-Host "`n[11] Final Stage-3.1 safety/authority invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.1.10-acceptance-regression-gate") { Fail "Final control_version drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Final Governance authority boundary drifted" }
if ($finalHealth.dispatch_enabled -ne $false -or $finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) {
    Fail "Final target execution boundary drifted"
}
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Final repository migration level drifted" }
Pass "Stage 3.1 closes with Governance external, target action disabled, and repository migration level 8"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.10 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "MissionId          : $missionId"
Write-Host "RoutingTask        : $taskId"
Write-Host "GovernanceBinding  : v$($binding.binding_version)"
Write-Host "PolicyDecision     : $($auth.authorization_binding.decision_provenance.policy_decision_id)"
Write-Host "CTI status         : $($ctiMissionEnvelope.mission.status)"
Write-Host "Canonical state    : REPLANNING/v5"
Write-Host "Mission events     : $($eventsView.event_count)"
Write-Host "Repository SHA256  : $($repository.repository_sha256)"
Write-Host "Target dispatch    : $($finalHealth.target_action_dispatch_enabled)"
Write-Host "=============================================================================="
exit 0
