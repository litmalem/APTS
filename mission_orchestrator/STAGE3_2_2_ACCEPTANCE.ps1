param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.2 ACCEPTANCE: FAIL" -ForegroundColor Red
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

function New-MissionPayload([string]$Token, [bool]$WithPip) {
    $body = @{
        idempotency_key = "stage322-mission-$Token"
        source_system = "STAGE322_ACCEPTANCE"
        created_by = "stage3.2.2-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage322-lab" }
        success_criteria = @(@{ metric = "stage322_guard_matrix"; expected = $true })
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.2" }
    }
    if ($WithPip) {
        $body.pip_id = "pip-$Token"
        $body.pip_version = "1"
    }
    return $body
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
        actor = "stage3.2.2-acceptance"
        reason_code = "LC_$Command"
        reason = "Stage 3.2.2 lifecycle acceptance command $Command"
        evidence_refs = @("evidence:stage3.2.2:acceptance")
        metadata = @{ acceptance = "stage3.2.2"; mission_id = $MissionId }
    }
    if ($TargetState) { $body.target_state = $TargetState }
    return $body
}

function Invoke-Lifecycle([string]$MissionId, [string]$Command, [string]$Token, [string]$TargetState = "") {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    $commandId = "lc-$($Command.ToLower())-$Token"
    $body = New-LifecycleCommand $MissionId $Command $commandId "idem-$commandId" ([int]$state.mission_state.state_version) $vector.version_sha256 $TargetState
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $body
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.2 - Lifecycle Transition Guard Matrix Acceptance"
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
    if (($pytestOutput -join "`n") -notmatch "140 passed") { Fail "Expected Stage-3.2.2 baseline '140 passed'" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.2 regression baseline: 140 passed"

Write-Host "`n[2] Health / guard-matrix contract / authority boundary"
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)" }
if ($health.status -ne "ok" -or $health.component_id -ne "APTS-MO01") { Fail "Unexpected Mission health identity" }
if ($health.control_version -ne "stage3.2.2-lifecycle-transition-guard-matrix") { Fail "Unexpected control_version: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Stage 3.2.2 must not add a database migration" }
if ($health.mission_lifecycle_command_stage3_2_2_guard_matrix_enabled -ne $true) { Fail "Stage 3.2.2 guard matrix is not active" }
if ($health.mission_lifecycle_guard_matrix_schema_version -ne "apts-mission-lifecycle-guard-matrix-v1") { Fail "Guard matrix schema mismatch" }
if ($health.mission_lifecycle_guard_matrix_mode -ne "DETERMINISTIC_LOCAL_PRECONDITION_FAIL_CLOSED") { Fail "Guard matrix mode mismatch" }
if ($health.mission_lifecycle_guard_matrix_applies_to -ne "LIFECYCLE_COMMAND") { Fail "Guard matrix applies_to mismatch" }
if ($health.mission_lifecycle_guard_matrix_local_only -ne $true -or $health.mission_lifecycle_guard_matrix_external_authority_queries -ne $false) { Fail "Guard matrix must be local-only" }
if ($health.mission_lifecycle_legacy_state_transition_api_preserved -ne $true) { Fail "Stage-3.1 legacy state API compatibility disappeared" }
if ($health.mission_lifecycle_stage3_2_5_dependency_resolution_enabled -ne $false) { Fail "Stage 3.2.5 dependency resolution must not be claimed active" }
if ($health.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $false) { Fail "Stage 3.2.8 completion gate must not be claimed active" }
if (@($health.supported_controls) -notcontains "stage3.2.1-mission-lifecycle-command-contract") { Fail "Stage 3.2.1 control disappeared" }
if (@($health.supported_controls) -notcontains "stage3.2.2-lifecycle-transition-guard-matrix") { Fail "Stage 3.2.2 control missing" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.dispatch_enabled -ne $false -or $health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution authority must remain disabled" }
Pass "Guard matrix active; migration, Governance, and target-execution boundaries preserved"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))

Write-Host "`n[3] Missing-PIP mission: topology eligibility vs Stage-3.2.2 guard eligibility"
$missingCreated = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "missing-$token" $false)
$missingMissionId = [string]$missingCreated.canonical_identity.mission_id
$missingContract = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/lifecycle-command-contract"
if ($missingContract.lifecycle_guard_matrix.schema_version -ne "apts-mission-lifecycle-guard-matrix-v1") { Fail "Guard matrix discovery missing" }
if (@($missingContract.topology_eligible_commands) -notcontains "BIND_PIP") { Fail "CREATED must remain topology-eligible for BIND_PIP" }
if (@($missingContract.guard_eligible_commands) -contains "BIND_PIP") { Fail "BIND_PIP must fail local guard when immutable PIP binding is missing" }
foreach ($safe in @("PAUSE","ABORT","FAIL","EXPIRE")) {
    if (@($missingContract.guard_eligible_commands) -notcontains $safe) { Fail "Fail-safe control $safe unexpectedly unavailable" }
}
if ($missingContract.eligibility_semantics -notmatch "NOT_GOVERNANCE_AUTHORIZATION") { Fail "Local guard eligibility was presented as Governance authorization" }
Pass "Discovery separates canonical topology from local lifecycle prerequisites"

Write-Host "`n[4] BIND_PIP fails closed before mutation when immutable PIP binding is absent"
$missingState0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/state"
$missingVector0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/version-vector"
$missingBind = New-LifecycleCommand $missingMissionId "BIND_PIP" "lc-missing-bind-$token" "idem-lc-missing-bind-$token" ([int]$missingState0.mission_state.state_version) $missingVector0.version_sha256
$missingFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missingMissionId/lifecycle/commands" $missingBind
if ([int]$missingFailure.status -ne 409) { Fail "Expected missing-PIP guard rejection HTTP 409, got $($missingFailure.status)" }
if ($null -eq $missingFailure.body -or $missingFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "Unexpected missing-PIP error code: $($missingFailure.body.code)" }
if ($missingFailure.body.message -notmatch "PIP_BINDING_COMPLETE_WHEN_REQUIRED") { Fail "Missing-PIP guard id not exposed" }
$missingStateAfter = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/state"
$missingHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/state/transitions"
$missingEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/events"
$missingCommands = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/commands"
if ($missingStateAfter.mission_state.state -ne "CREATED" -or [int]$missingHistory.transition_count -ne 0) { Fail "Rejected guard mutated mission state" }
if (@($missingEvents.events | Where-Object { $_.event_type -eq "MISSION_COMMAND_COMPLETED" }).Count -ne 0) { Fail "Rejected guard emitted command-completed event" }
$failedJournal = @($missingCommands.commands | Where-Object { $_.command_id -eq "lc-missing-bind-$token" })
if ($failedJournal.Count -ne 1 -or $failedJournal[0].command_status -ne "FAILED") { Fail "Rejected guard command was not durably journaled as FAILED" }
Pass "Missing operational prerequisite rejected fail-closed with zero state/event side effects"

Write-Host "`n[5] Complete-PIP mission: BIND_PIP -> START_PLANNING -> START passes guard matrix"
$readyCreated = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "ready-$token" $true)
$readyMissionId = [string]$readyCreated.canonical_identity.mission_id
$bindResult = Invoke-Lifecycle $readyMissionId "BIND_PIP" "bind-$token"
if ($bindResult.mission_state.state -ne "PIP_BOUND" -or $bindResult.lifecycle_guard.allowed -ne $true) { Fail "BIND_PIP did not pass guard matrix" }
$planResult = Invoke-Lifecycle $readyMissionId "START_PLANNING" "plan-$token"
if ($planResult.mission_state.state -ne "PLANNING" -or $planResult.lifecycle_guard.allowed -ne $true) { Fail "START_PLANNING did not pass guard matrix" }
$startResult = Invoke-Lifecycle $readyMissionId "START" "start-$token"
if ($startResult.mission_state.state -ne "RUNNING" -or $startResult.lifecycle_guard.allowed -ne $true) { Fail "START did not pass guard matrix" }
if ($startResult.lifecycle_guard.authority_query_performed -ne $false) { Fail "Lifecycle guard unexpectedly queried authority" }
Pass "Operational lifecycle progress requires and validates complete immutable PIP binding"

Write-Host "`n[6] PAUSED semantic guard requires RESUME instead of START"
$pauseResult = Invoke-Lifecycle $readyMissionId "PAUSE" "pause-$token"
if ($pauseResult.mission_state.state -ne "PAUSED") { Fail "PAUSE failed" }
$pausedContract = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/lifecycle-command-contract"
if (@($pausedContract.topology_eligible_commands) -notcontains "START") { Fail "PAUSED -> RUNNING should remain topologically legal" }
if (@($pausedContract.guard_eligible_commands) -contains "START") { Fail "START must be semantically rejected from PAUSED" }
if (@($pausedContract.guard_eligible_commands) -notcontains "RESUME") { Fail "RESUME must be guard-eligible from PAUSED" }
if (@($pausedContract.guard_eligible_resume_targets) -notcontains "RUNNING") { Fail "RUNNING resume target missing" }
$pausedState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/state"
$pausedVector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/version-vector"
$badStart = New-LifecycleCommand $readyMissionId "START" "lc-bad-start-$token" "idem-lc-bad-start-$token" ([int]$pausedState.mission_state.state_version) $pausedVector.version_sha256
$badStartFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$readyMissionId/lifecycle/commands" $badStart
if ([int]$badStartFailure.status -ne 409 -or $badStartFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "START-from-PAUSED was not rejected by lifecycle guard" }
if ($badStartFailure.body.message -notmatch "SOURCE_STATE_ALLOWED_FOR_COMMAND") { Fail "Semantic source-state guard id missing" }
$resumeResult = Invoke-Lifecycle $readyMissionId "RESUME" "resume-$token" "RUNNING"
if ($resumeResult.mission_state.state -ne "RUNNING" -or $resumeResult.lifecycle_guard.allowed -ne $true) { Fail "RESUME -> RUNNING failed" }
Pass "Semantic command/source-state matrix prevents topology-valid but lifecycle-wrong intent"

Write-Host "`n[7] Fail-safe terminal control is never blocked by missing PIP"
try { $abortResult = Invoke-Lifecycle $missingMissionId "ABORT" "abort-$token" } catch { Fail "ABORT on missing-PIP mission failed: $($_.Exception.Message)" }
if ($abortResult.mission_state.state -ne "ABORTED" -or $abortResult.lifecycle_guard.allowed -ne $true) { Fail "ABORT did not remain fail-safe" }
$pipGuard = @($abortResult.lifecycle_guard.checks | Where-Object { $_.guard_id -eq "PIP_BINDING_COMPLETE_WHEN_REQUIRED" })
if ($pipGuard.Count -ne 1 -or $pipGuard[0].required -ne "NOT_REQUIRED" -or $pipGuard[0].status -ne "PASS") { Fail "Fail-safe terminal command was incorrectly PIP-gated" }
Pass "Abort/fail/expire control path remains available even when operational prerequisites are invalid"

Write-Host "`n[8] Guard outcomes are durable/auditable without synthesizing authorization"
$readyCommands = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/commands"
$readyEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/events"
$successfulLifecycle = @($readyCommands.commands | Where-Object { $_.operation -eq "LIFECYCLE_COMMAND" -and $_.command_status -eq "COMPLETED" })
if ($successfulLifecycle.Count -lt 5) { Fail "Expected successful lifecycle commands not present in journal" }
if (@($readyEvents.events | Where-Object { $_.event_type -eq "MISSION_STATE_TRANSITIONED" }).Count -lt 5) { Fail "Successful lifecycle transitions are missing lineage events" }
if ($pausedContract.lifecycle_guard_matrix.external_authority_queries -ne $false -or $pausedContract.lifecycle_guard_matrix.governance_decision_synthesized -ne $false) { Fail "Guard matrix crossed Governance authority boundary" }
$deferred = @($pausedContract.lifecycle_guard_matrix.deferred_guards)
if ($deferred -notcontains "WAITING_EVIDENCE_DEPENDENCY_SATISFACTION_STAGE_3_2_5") { Fail "Stage 3.2.5 dependency guard was not explicitly deferred" }
if ($deferred -notcontains "CLEANUP_VERIFICATION_AND_COMPLETION_CRITERIA_STAGE_3_2_8") { Fail "Stage 3.2.8 completion gate was not explicitly deferred" }
Pass "Guarded lifecycle semantics are traceable while future dependency/completion stages remain unclaimed"

Write-Host "`n[9] Final boundary check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.2-lifecycle-transition-guard-matrix") { Fail "Final control_version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Repository migration level drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority drifted" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary drifted" }
Pass "Stage 3.2.2 preserved Governance and target-execution boundaries"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.2 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
