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
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        throw
    }
}

function New-TransitionPayload([int]$ExpectedVersion, [string]$ToState, [string]$ReasonCode) {
    return @{
        expected_state_version = $ExpectedVersion
        to_state = $ToState
        actor = "stage3.1.6-acceptance"
        reason_code = $ReasonCode
        reason = "Stage 3.1.6 guarded transition"
        evidence_refs = @()
        metadata = @{ acceptance = "stage3.1.6" }
    }
}

function New-CommandJson(
    [string]$CommandId,
    [string]$IdempotencyKey,
    [string]$Operation,
    [string]$ExpectedVersionSha256,
    [hashtable]$Payload
) {
    return (@{
        command_id = $CommandId
        idempotency_key = $IdempotencyKey
        operation = $Operation
        expected_version_sha256 = $ExpectedVersionSha256
        payload = $Payload
        submitted_by = "stage3.1.6-acceptance"
        metadata = @{ acceptance = "stage3.1.6" }
    } | ConvertTo-Json -Depth 40)
}

function Get-Version([string]$MissionId) {
    return Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.6 - Mission Versioning & Concurrency Mode Acceptance"
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
Pass "Stage 3.1.1 through 3.1.6 regression"

Write-Host "`n[2] Stage-3.1.6 health / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.component_id -ne "APTS-MO01") { Fail "Unexpected component_id" }
if ($health.control_version -ne "stage3.1.6-mission-versioning-concurrency") { Fail "Unexpected control_version" }
if ($health.mission_concurrency_mode -ne "OPTIMISTIC_VERSION_VECTOR_IDEMPOTENT_COMMAND_GATE") { Fail "Unexpected concurrency mode" }
if ($health.mission_command_gate_enabled -ne $true) { Fail "Mission command gate is not enabled" }
if ($health.mission_mutation_serialization_mode -ne "PROCESS_WIDE_REENTRANT_GUARD_PLUS_REPOSITORY_CAS") { Fail "Unexpected mutation serialization mode" }
if (@($health.observed_version_domains) -notcontains "state_version") { Fail "state_version not observed" }
if (@($health.observed_version_domains) -notcontains "policy_version") { Fail "policy_version not observed" }
if (@($health.observed_version_domains) -notcontains "cti_plan_version") { Fail "cti_plan_version not observed" }
if ($health.dispatch_enabled -ne $false -or $health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) {
    Fail "Stage 3.1.6 changed the target-action authority boundary"
}
Pass "Versioning/concurrency control enabled without target-action authority"

Write-Host "`n[3] Governance and CTI preflight"
$govHealth = Invoke-RestMethod "$GovernanceBaseUrl/health"
if ($govHealth.component_id -ne "GOV-PLANE") { Fail "Unexpected Governance component_id" }
if ($govHealth.readiness_status -eq "NOT_READY") { Fail "Governance is NOT_READY" }
$emergency = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/emergency-stop"
if ([bool]$emergency.emergency_state.active) { Fail "Governance emergency stop is ACTIVE; acceptance will not release it" }
$ctiHealth = Invoke-RestMethod "$CtiBaseUrl/health"
if ($ctiHealth.component_id -ne "CTI-INF01") { Fail "Unexpected CTI component_id" }
if ($ctiHealth.readiness_status -eq "NOT_READY") { Fail "CTI is NOT_READY" }
Pass "GOV-PLANE and CTI-INF01 are reachable"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
$now = [DateTimeOffset]::UtcNow
$startAt = $now.AddMinutes(-5).ToString("o")
$endAt = $now.AddHours(2).ToString("o")

$missionBody = @{
    idempotency_key = "stage316-mission-$token"
    source_system = "POWERSHELL_ACCEPTANCE"
    created_by = "stage3.1.6-acceptance"
    client_request_id = "client-$token"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage316-lab" }
    success_criteria = @(@{ metric = "concurrency_guard"; expected = $true })
    budgets = @{ time_seconds = 1800; max_actions = 20; risk_ceiling = "MODERATE" }
    required_subsystems = @("CTI")
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.6" }
} | ConvertTo-Json -Depth 20

Write-Host "`n[4] Create mission and read initial version vector"
$created = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions" -ContentType "application/json" -Body $missionBody
$missionId = [string]$created.canonical_identity.mission_id
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Invalid mission id" }
$v0 = Get-Version $missionId
if ($v0.version_vector_complete -ne $true) { Fail "Initial version vector is incomplete" }
if ([int]$v0.version_vector.versions.envelope_version -ne 1) { Fail "Expected envelope_version=1" }
if ([int]$v0.version_vector.versions.state_version -ne 1) { Fail "Expected state_version=1" }
if ([int]$v0.version_vector.versions.scope_contract_version -ne 0) { Fail "Expected scope_contract_version=0" }
if ([int]$v0.version_vector.versions.governance_binding_version -ne 0) { Fail "Expected governance_binding_version=0" }
if ([string]$v0.version_sha256 -notmatch '^[0-9a-f]{64}$') { Fail "Invalid version SHA-256" }
$initialVersionHash = [string]$v0.version_sha256
Pass "Initial multi-domain version vector established: $initialVersionHash"

Write-Host "`n[5] Guarded transition + deterministic duplicate-command replay"
$cmdState1 = New-CommandJson "cmd-stage316-state1-$token" "idem-stage316-state1-$token" "STATE_TRANSITION" $initialVersionHash (New-TransitionPayload 1 "PIP_BOUND" "PIP_BOUND_CONCURRENCY_ACCEPTANCE")
$first = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $cmdState1
if ($first.command_status -ne "COMPLETED" -or $first.idempotent_replay -ne $false) { Fail "First guarded transition did not complete" }
$replay = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $cmdState1
if ($replay.idempotent_replay -ne $true) { Fail "Duplicate command was not replayed idempotently" }
if ($replay.result.transition.transition_id -ne $first.result.transition.transition_id) { Fail "Duplicate replay changed transition identity" }
$state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($state.mission_state.state -ne "PIP_BOUND" -or [int]$state.mission_state.state_version -ne 2) { Fail "Expected PIP_BOUND/v2" }
Pass "Duplicate command produced exactly one canonical transition"

Write-Host "`n[6] Stale version write is rejected without mutation"
$staleCmd = New-CommandJson "cmd-stage316-stale-$token" "idem-stage316-stale-$token" "STATE_TRANSITION" $initialVersionHash (New-TransitionPayload 2 "PLANNING" "STALE_WRITE_NEGATIVE")
$staleStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/commands" $staleCmd
if ($staleStatus -ne 409) { Fail "Stale command must fail HTTP 409 (actual=$staleStatus)" }
$stateAfterStale = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($stateAfterStale.mission_state.state -ne "PIP_BOUND" -or [int]$stateAfterStale.mission_state.state_version -ne 2) { Fail "Stale command mutated canonical state" }
$staleRecord = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands/cmd-stage316-stale-$token"
if ($staleRecord.command_status -ne "REJECTED_STALE") { Fail "Stale command was not journaled as REJECTED_STALE" }
Pass "Stale write rejected and auditable"

Write-Host "`n[7] Guarded Scope/RoE/Constraint contract"
$v1 = Get-Version $missionId
$scopePayload = @{
    expected_contract_version = 0
    idempotency_key = "stage316-scope-$token"
    actor = "stage3.1.6-acceptance"
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
    reason = "Stage 3.1.6 guarded scope"
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.6" }
}
$scopeCmd = New-CommandJson "cmd-stage316-scope-$token" "idem-stage316-scope-$token" "SCOPE_CONTRACT_PUT" ([string]$v1.version_sha256) $scopePayload
$scopeResult = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $scopeCmd
if ([int]$scopeResult.result.contract_version -ne 1) { Fail "Guarded scope did not create v1" }
$scopeHash = [string]$scopeResult.result.canonical_sha256
Pass "Scope/RoE/Constraint v1 committed through version-vector guard"

Write-Host "`n[8] Guarded Governance binding and policy-version observation"
$v2 = Get-Version $missionId
$bindingPayload = @{
    expected_binding_version = 0
    idempotency_key = "stage316-binding-$token"
    actor = "stage3.1.6-acceptance"
    policy_set_id = "default-policy"
    name = "Stage 3.1.6 concurrency binding"
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
    reason = "Stage 3.1.6 guarded Governance binding"
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.6" }
}
$bindingCmd = New-CommandJson "cmd-stage316-binding-$token" "idem-stage316-binding-$token" "GOVERNANCE_BINDING_PUT" ([string]$v2.version_sha256) $bindingPayload
$bindingResult = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $bindingCmd
if ([int]$bindingResult.result.binding_version -ne 1 -or $bindingResult.result.binding_status -ne "CURRENT") { Fail "Guarded Governance binding v1 failed" }

$v3 = Get-Version $missionId
$authPayload = @{
    idempotency_key = "stage316-auth-$token"
    capability_id = "pentest.recon"
    resource_type = "IP"
    resource_value = "127.0.0.1"
    context = @{ environment = "LAB"; acceptance = "stage3.1.6" }
    evidence_refs = @()
    requested_by = "stage3.1.6-acceptance"
}
$authCmd = New-CommandJson "cmd-stage316-auth-$token" "idem-stage316-auth-$token" "AUTHORIZATION_BINDING_CREATE" ([string]$v3.version_sha256) $authPayload
$authResult = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $authCmd
$v4 = Get-Version $missionId
if ($null -eq $v4.version_vector.versions.policy_version) { Fail "Authoritative policy_version was not incorporated into mission version vector" }
if ([int]$v4.version_vector.versions.governance_scope_version -lt 1) { Fail "Governance scope version missing" }
Pass "Governance binding/scope version and authoritative policy version are observed"

Write-Host "`n[9] Guarded PIP_BOUND -> PLANNING and routing-task creation"
$planCmd = New-CommandJson "cmd-stage316-planning-$token" "idem-stage316-planning-$token" "STATE_TRANSITION" ([string]$v4.version_sha256) (New-TransitionPayload 2 "PLANNING" "PLANNING_CONCURRENCY_ACCEPTANCE")
$planResult = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $planCmd
if ($planResult.result.mission_state.state -ne "PLANNING" -or [int]$planResult.result.mission_state.state_version -ne 3) { Fail "Guarded PLANNING transition failed" }

$v5 = Get-Version $missionId
$taskPayload = @{
    idempotency_key = "stage316-task-$token"
    capability_id = "orchestrator.route.cti"
    task_input = @{
        auto_acquire_cti = $false
        mission_objective = @{ type = "PENTEST_INTELLIGENCE_ENRICHMENT"; acceptance = "stage3.1.6" }
        intelligence_requirements = @()
        metadata = @{ acceptance = "stage3.1.6" }
    }
    requested_by = "stage3.1.6-acceptance"
    reason = "Guarded CTI route"
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.6" }
}
$taskCmd = New-CommandJson "cmd-stage316-task-$token" "idem-stage316-task-$token" "ROUTING_TASK_CREATE" ([string]$v5.version_sha256) $taskPayload
$taskResult = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $taskCmd
$taskId = [string]$taskResult.result.task_id
if (-not $taskId.StartsWith("mtask-") -or $taskResult.result.task_status -ne "READY") { Fail "Guarded routing task creation failed" }
Pass "Routing-task set revision is now part of the version vector"

Write-Host "`n[10] Guarded RUNNING transition and CTI dispatch"
$v6 = Get-Version $missionId
$runCmd = New-CommandJson "cmd-stage316-running-$token" "idem-stage316-running-$token" "STATE_TRANSITION" ([string]$v6.version_sha256) (New-TransitionPayload 3 "RUNNING" "RUNNING_CONCURRENCY_ACCEPTANCE")
$runResult = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $runCmd
if ($runResult.result.mission_state.state -ne "RUNNING" -or [int]$runResult.result.mission_state.state_version -ne 4) { Fail "Guarded RUNNING transition failed" }

$v7 = Get-Version $missionId
$dispatchPayload = @{ task_id = $taskId }
$dispatchCmd = New-CommandJson "cmd-stage316-dispatch-$token" "idem-stage316-dispatch-$token" "ROUTING_TASK_DISPATCH" ([string]$v7.version_sha256) $dispatchPayload
$dispatchResult = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/commands" -ContentType "application/json" -Body $dispatchCmd
if ($dispatchResult.result.task_status -ne "DISPATCHED") { Fail "Guarded CTI dispatch failed" }
$v8 = Get-Version $missionId
if ($v8.version_vector_complete -ne $true) { Fail "Post-dispatch version vector is incomplete" }
if ($v8.version_vector.subsystem_observations.cti_observation_status -ne "OBSERVED") { Fail "CTI version observation is not OBSERVED" }
if ([int]$v8.version_vector.versions.cti_state_version -lt 1) { Fail "CTI state_version missing" }
if ([int]$v8.version_vector.versions.cti_plan_version -lt 1) { Fail "CTI plan_version missing" }
Pass "Live CTI state_version/plan_version incorporated after dispatch"

Write-Host "`n[11] Real concurrent guarded transition race: exactly one winner"
# Use a dedicated race mission whose version vector is locally stable.  The primary
# acceptance mission has already dispatched CTI; its observed CTI state/plan versions
# may legitimately advance while Start-Job workers are being created.  Racing against
# that live external observation can make BOTH commands stale before either reaches the
# Mission Orchestrator, which tests external-version drift rather than local write
# serialization.  This isolated mission keeps the concurrency assertion deterministic
# while Stage [10] still verifies live CTI version observation on the primary mission.
$raceMissionBody = @{
    idempotency_key = "stage316-race-mission-$token"
    source_system = "POWERSHELL_ACCEPTANCE"
    created_by = "stage3.1.6-acceptance"
    client_request_id = "race-client-$token"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage316-race-lab" }
    success_criteria = @(@{ metric = "single_concurrent_winner"; expected = $true })
    budgets = @{ time_seconds = 300; max_actions = 2; risk_ceiling = "LOW" }
    required_subsystems = @("CTI")
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.6"; purpose = "concurrency-race" }
} | ConvertTo-Json -Depth 20

$raceMissionCreated = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions" -ContentType "application/json" -Body $raceMissionBody
$raceMissionId = [string]$raceMissionCreated.canonical_identity.mission_id
if (-not $raceMissionId.StartsWith("mission-gmo-")) { Fail "Invalid race mission id" }

$raceVersion = Get-Version $raceMissionId
if ($raceVersion.version_vector_complete -ne $true) { Fail "Race mission version vector is incomplete" }
$raceHash = [string]$raceVersion.version_sha256
$raceStateVersion = [int]$raceVersion.version_vector.versions.state_version
if ($raceStateVersion -ne 1) { Fail "Race mission must start at state_version=1" }

$raceBodyA = New-CommandJson "cmd-stage316-race-a-$token" "idem-stage316-race-a-$token" "STATE_TRANSITION" $raceHash (New-TransitionPayload $raceStateVersion "PIP_BOUND" "RACE_A")
$raceBodyB = New-CommandJson "cmd-stage316-race-b-$token" "idem-stage316-race-b-$token" "STATE_TRANSITION" $raceHash (New-TransitionPayload $raceStateVersion "PAUSED" "RACE_B")
$commandUri = "$MissionBaseUrl/api/missions/$raceMissionId/commands"
$jobScript = {
    param($Uri, $Body)
    try {
        $r = Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $Body -UseBasicParsing
        [pscustomobject]@{ status = [int]$r.StatusCode; body = $r.Content }
    } catch {
        if ($_.Exception.Response) {
            $errorBody = ""
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                if ($stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $errorBody = $reader.ReadToEnd()
                    $reader.Dispose()
                }
            } catch { }
            [pscustomobject]@{ status = [int]$_.Exception.Response.StatusCode; body = $errorBody }
        } else { throw }
    }
}
$jobA = Start-Job -ScriptBlock $jobScript -ArgumentList $commandUri, $raceBodyA
$jobB = Start-Job -ScriptBlock $jobScript -ArgumentList $commandUri, $raceBodyB
Wait-Job $jobA, $jobB | Out-Null
$raceResults = @((Receive-Job $jobA), (Receive-Job $jobB))
Remove-Job $jobA, $jobB -Force
$successCount = @($raceResults | Where-Object { $_.status -eq 201 }).Count
$conflictCount = @($raceResults | Where-Object { $_.status -eq 409 }).Count
if ($successCount -ne 1 -or $conflictCount -ne 1) {
    $raceDiag = ($raceResults | ForEach-Object { "status=$($_.status) body=$($_.body)" }) -join " | "
    Fail "Expected one concurrent 201 winner and one 409 stale loser; got $raceDiag"
}
$raceStateAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$raceMissionId/state"
if ([int]$raceStateAfter.mission_state.state_version -ne ($raceStateVersion + 1)) { Fail "Concurrent race produced more than one state-version increment" }
if (@("PIP_BOUND", "PAUSED") -notcontains $raceStateAfter.mission_state.state) { Fail "Unexpected race winner state" }
$raceHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$raceMissionId/commands"
if ([int]$raceHistory.command_count -ne 2) { Fail "Race mission command journal must contain exactly two commands" }
if (@($raceHistory.commands | Where-Object { $_.command_status -eq "COMPLETED" }).Count -ne 1) { Fail "Race mission must contain exactly one completed command" }
if (@($raceHistory.commands | Where-Object { $_.command_status -eq "REJECTED_STALE" }).Count -ne 1) { Fail "Race mission must contain exactly one stale command" }
Pass "Concurrent transition race produced exactly one winner and one stale loser"

Write-Host "`n[12] Command journal, immutable lineage, and final authority checks"
$history = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands"
if ([int]$history.command_count -lt 9) { Fail "Primary mission command journal is missing acceptance operations" }
if (@($history.commands | Where-Object { $_.command_status -eq "REJECTED_STALE" }).Count -lt 1) { Fail "Primary mission stale-write evidence is missing" }
if (@($raceHistory.commands | Where-Object { $_.command_status -eq "REJECTED_STALE" }).Count -ne 1) { Fail "Race stale-write evidence is missing" }
$finalScope = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/scope-contract"
$finalBinding = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/governance-binding"
$finalTask = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/routing-tasks/$taskId"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalScope.canonical_sha256 -ne $scopeHash) { Fail "Concurrency control mutated immutable scope snapshot" }
if ($finalBinding.binding_status -ne "CURRENT") { Fail "Governance binding is no longer current" }
if ($finalTask.task_contract.semantics.target_action_dispatch -ne $false -or $finalTask.task_contract.semantics.target_actuation -ne $false) { Fail "Routing task gained target authority" }
if ($finalHealth.dispatch_enabled -ne $false -or $finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Final target-action authority boundary changed" }
Pass "Command journal is auditable and all authority boundaries remain intact"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.6 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "MissionId             : $missionId"
Write-Host "RoutingTask           : $taskId"
$primaryFinalState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
Write-Host "Final canonical state : $($primaryFinalState.mission_state.state)/v$($primaryFinalState.mission_state.state_version)"
Write-Host "Race MissionId        : $raceMissionId"
Write-Host "Race final state      : $($raceStateAfter.mission_state.state)/v$($raceStateAfter.mission_state.state_version)"
Write-Host "Policy version        : $($v8.version_vector.versions.policy_version)"
Write-Host "CTI state/plan        : v$($v8.version_vector.versions.cti_state_version)/v$($v8.version_vector.versions.cti_plan_version)"
Write-Host "Command count         : $($history.command_count)"
Write-Host "Target dispatch       : $($finalHealth.target_action_dispatch_enabled)"
Write-Host "=============================================================================="
