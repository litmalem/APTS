param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.1 ACCEPTANCE: FAIL" -ForegroundColor Red
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

function Get-PostFailure([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 60 -Compress
    try {
        $null = Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
        return @{ status = 200; body = $null }
    } catch {
        $status = $null
        $body = $null
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
        }
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            try { $body = $_.ErrorDetails.Message | ConvertFrom-Json } catch { $body = $null }
        }
        return @{ status = $status; body = $body }
    }
}

function New-LifecycleCommand(
    [string]$MissionId,
    [string]$Command,
    [string]$CommandId,
    [string]$IdempotencyKey,
    [int]$ExpectedStateVersion,
    [string]$ExpectedVersionSha256,
    [string]$TargetState = ""
) {
    $body = @{
        command_id = $CommandId
        idempotency_key = $IdempotencyKey
        command = $Command
        expected_version_sha256 = $ExpectedVersionSha256
        expected_state_version = $ExpectedStateVersion
        actor = "stage3.2.1-acceptance"
        reason_code = "LC_$Command"
        reason = "Stage 3.2.1 lifecycle acceptance command $Command"
        evidence_refs = @("evidence:stage3.2.1:acceptance")
        metadata = @{ acceptance = "stage3.2.1"; mission_id = $MissionId }
    }
    if ($TargetState) { $body.target_state = $TargetState }
    return $body
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.1 - Mission Lifecycle Command Contract Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[1] Python compile + full regression"
Push-Location $PSScriptRoot
try {
    & python -m compileall -q mission_orchestrator tests
    if ($LASTEXITCODE -ne 0) { Fail "Python compile gate failed" }
    $pytestOutput = & python -m pytest -q 2>&1
    $pytestOutput | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Fail "Full regression suite failed" }
    if (($pytestOutput -join "`n") -notmatch "125 passed") { Fail "Expected Stage-3.2.1 baseline '125 passed'" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.1 regression baseline: 125 passed"

Write-Host "`n[2] Health / lifecycle contract / authority boundary"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)"
}
if ($health.status -ne "ok" -or $health.component_id -ne "APTS-MO01") { Fail "Unexpected Mission health identity" }
if ($health.control_version -ne "stage3.2.1-mission-lifecycle-command-contract") { Fail "Unexpected control_version: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Stage 3.2.1 must not add a database migration" }
if ($health.mission_lifecycle_command_schema_version -ne "apts-mission-lifecycle-command-v1") { Fail "Lifecycle command schema mismatch" }
if ($health.mission_lifecycle_command_mode -ne "EXPLICIT_COMMAND_TO_CANONICAL_STATE_VIA_GUARDED_COMMAND_JOURNAL") { Fail "Lifecycle command mode mismatch" }
if ($health.mission_lifecycle_command_operation -ne "LIFECYCLE_COMMAND") { Fail "Lifecycle guarded operation mismatch" }
if ($health.mission_lifecycle_command_uses_existing_command_journal -ne $true) { Fail "Lifecycle command must reuse the existing command journal" }
if ($health.mission_lifecycle_command_stage3_2_2_guard_matrix_enabled -ne $false) { Fail "Stage 3.2.2 guard matrix must not be claimed active" }
if (@($health.supported_controls) -notcontains "stage3.1.10-acceptance-regression-gate") { Fail "Stage 3.1.10 closure control disappeared" }
if (@($health.supported_controls) -notcontains "stage3.2.1-mission-lifecycle-command-contract") { Fail "Stage 3.2.1 control missing" }
if (@($health.supported_mission_command_operations) -notcontains "LIFECYCLE_COMMAND") { Fail "Generic command gate does not advertise LIFECYCLE_COMMAND" }
$requiredLifecycleCommands = @(
    "BIND_PIP", "START_PLANNING", "START", "WAIT_FOR_EVIDENCE", "WAIT_FOR_APPROVAL",
    "PAUSE", "RESUME", "REPLAN", "BEGIN_CLEANUP", "COMPLETE", "ABORT", "FAIL", "EXPIRE"
)
foreach ($command in $requiredLifecycleCommands) {
    if (@($health.supported_mission_lifecycle_commands) -notcontains $command) { Fail "Missing lifecycle command: $command" }
}
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.dispatch_enabled -ne $false -or $health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) {
    Fail "Target execution authority must remain disabled"
}
Pass "Stage 3.2.1 contract active; migration and authority boundaries preserved"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))
$missionPayload = @{
    idempotency_key = "stage321-mission-$token"
    source_system = "STAGE321_ACCEPTANCE"
    created_by = "stage3.2.1-acceptance"
    client_request_id = "client-$token"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage321-lab" }
    success_criteria = @(@{ metric = "stage321_lifecycle_contract"; expected = $true })
    budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
    required_subsystems = @("CTI")
    metadata = @{ environment = "LAB"; acceptance = "stage3.2.1" }
}

Write-Host "`n[3] Create canonical mission + discover lifecycle contract"
try {
    $created = Post-Json "$MissionBaseUrl/api/missions" $missionPayload
} catch {
    Fail "Mission create failed: $($_.Exception.Message)"
}
$missionId = [string]$created.canonical_identity.mission_id
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Unexpected canonical mission id: $missionId" }
try {
    $contractView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/lifecycle-command-contract"
} catch {
    Fail "Lifecycle contract discovery failed: $($_.Exception.Message)"
}
if ($contractView.lifecycle_command_contract.schema_version -ne "apts-mission-lifecycle-command-v1") { Fail "Lifecycle contract schema mismatch" }
if ($contractView.lifecycle_command_contract.stage3_2_2_guard_matrix_not_implemented -ne $true) { Fail "Contract must explicitly defer richer guard matrix to Stage 3.2.2" }
if (@($contractView.topology_eligible_commands) -notcontains "BIND_PIP") { Fail "CREATED must expose BIND_PIP as topology-eligible" }
if (@($contractView.topology_eligible_commands) -contains "START") { Fail "CREATED must not expose START as topology-eligible" }
if ($contractView.eligibility_semantics -notmatch "NOT_AUTHORIZATION") { Fail "Topology eligibility must not be presented as authorization" }
Pass "Lifecycle command contract discovery is explicit and topology-only"

Write-Host "`n[4] BIND_PIP through versioned lifecycle command gate"
$vector0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
if ($vector0.version_vector_complete -ne $true) { Fail "Initial version vector is incomplete" }
$bind = New-LifecycleCommand $missionId "BIND_PIP" "lc-bind-$token" "idem-lc-bind-$token" 1 $vector0.version_sha256
try {
    $bindResult = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $bind
} catch {
    Fail "BIND_PIP lifecycle command failed: $($_.Exception.Message)"
}
if ($bindResult.lifecycle_command -ne "BIND_PIP" -or $bindResult.resolved_target_state -ne "PIP_BOUND") { Fail "BIND_PIP semantic mapping failed" }
if ($bindResult.command_status -ne "COMPLETED" -or $bindResult.idempotent_replay -ne $false) { Fail "BIND_PIP command journal result invalid" }
if ($bindResult.mission_state.state -ne "PIP_BOUND" -or [int]$bindResult.mission_state.state_version -ne 2) { Fail "BIND_PIP did not transition to PIP_BOUND/v2" }
if ($bindResult.guarded_command.operation -ne "LIFECYCLE_COMMAND") { Fail "Lifecycle command did not use guarded LIFECYCLE_COMMAND operation" }
Pass "BIND_PIP mapped to canonical PIP_BOUND through the existing versioned command journal"

Write-Host "`n[5] Exact replay is idempotent and does not duplicate lineage"
$eventsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$historyBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
try {
    $bindReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $bind
} catch {
    Fail "Exact lifecycle command replay failed: $($_.Exception.Message)"
}
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$historyAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
if ($bindReplay.idempotent_replay -ne $true) { Fail "Exact lifecycle command replay was not marked idempotent" }
if ([int]$eventsAfterReplay.event_count -ne [int]$eventsBeforeReplay.event_count) { Fail "Replay duplicated mission events" }
if ([int]$historyAfterReplay.transition_count -ne [int]$historyBeforeReplay.transition_count) { Fail "Replay duplicated state transition" }
Pass "Exact replay returns stored result with zero duplicate transition/event side effects"

Write-Host "`n[6] Stale version-vector command fails closed before mutation"
$staleStart = New-LifecycleCommand $missionId "START_PLANNING" "lc-stale-$token" "idem-lc-stale-$token" 2 $vector0.version_sha256
$staleFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $staleStart
if ([int]$staleFailure.status -ne 409) { Fail "Expected stale lifecycle command HTTP 409, got $($staleFailure.status)" }
if ($null -ne $staleFailure.body -and $staleFailure.body.code -ne "MISSION_VERSION_CONFLICT") { Fail "Unexpected stale lifecycle error code: $($staleFailure.body.code)" }
$stateAfterStale = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($stateAfterStale.mission_state.state -ne "PIP_BOUND" -or [int]$stateAfterStale.mission_state.state_version -ne 2) { Fail "Stale command mutated mission state" }
Pass "Stale lifecycle mutation rejected fail-closed with state unchanged"

Write-Host "`n[7] Valid START_PLANNING + illegal COMPLETE topology rejection"
$vector1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
$planning = New-LifecycleCommand $missionId "START_PLANNING" "lc-plan-$token" "idem-lc-plan-$token" 2 $vector1.version_sha256
try {
    $planningResult = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $planning
} catch {
    Fail "START_PLANNING lifecycle command failed: $($_.Exception.Message)"
}
if ($planningResult.mission_state.state -ne "PLANNING" -or [int]$planningResult.mission_state.state_version -ne 3) { Fail "START_PLANNING did not reach PLANNING/v3" }
$vector2 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/version-vector"
$illegalComplete = New-LifecycleCommand $missionId "COMPLETE" "lc-illegal-complete-$token" "idem-lc-illegal-complete-$token" 3 $vector2.version_sha256
$illegalFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $illegalComplete
if ([int]$illegalFailure.status -ne 409) { Fail "Expected illegal COMPLETE HTTP 409, got $($illegalFailure.status)" }
if ($null -ne $illegalFailure.body -and $illegalFailure.body.code -ne "MISSION_STATE_TRANSITION_ILLEGAL") { Fail "Unexpected illegal transition error code: $($illegalFailure.body.code)" }
$stateAfterIllegal = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($stateAfterIllegal.mission_state.state -ne "PLANNING" -or [int]$stateAfterIllegal.mission_state.state_version -ne 3) { Fail "Illegal lifecycle command mutated mission state" }
Pass "Lifecycle vocabulary does not bypass the existing canonical state topology"

Write-Host "`n[8] Command journal + event lineage expose lifecycle semantics"
$commands = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands"
if ([int]$commands.command_count -lt 4) { Fail "Expected lifecycle command journal entries were not recorded" }
$bindJournal = @($commands.commands | Where-Object { $_.command_id -eq "lc-bind-$token" })
if ($bindJournal.Count -ne 1 -or $bindJournal[0].operation -ne "LIFECYCLE_COMMAND") { Fail "BIND_PIP journal operation not preserved" }
if ($bindJournal[0].metadata.lifecycle_command -ne "BIND_PIP" -or $bindJournal[0].metadata.resolved_target_state -ne "PIP_BOUND") { Fail "Lifecycle journal metadata missing semantic intent" }
$events = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$eventTypes = @($events.events | ForEach-Object { $_.event_type })
if ($eventTypes -notcontains "MISSION_STATE_TRANSITIONED" -or $eventTypes -notcontains "MISSION_COMMAND_COMPLETED") { Fail "Lifecycle transition/command lineage events missing" }
Pass "Lifecycle intent is durable in command metadata and linked to existing mission lineage"

Write-Host "`n[9] Final boundary check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.1-mission-lifecycle-command-contract") { Fail "Final control_version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Repository migration level drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority drifted" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary drifted" }
Pass "Stage 3.2.1 preserved Governance and target-execution boundaries"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
