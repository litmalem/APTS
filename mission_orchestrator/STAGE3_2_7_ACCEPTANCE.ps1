param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.7 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        $null = Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
        return @{ status = 200; body = $null }
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

function New-MissionPayload([string]$Token, [bool]$WithPip = $true) {
    $payload = @{
        idempotency_key = "stage327-mission-$Token"
        source_system = "STAGE327_ACCEPTANCE"
        created_by = "stage3.2.7-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage327-lab" }
        success_criteria = @(@{ metric = "stage327_terminal_semantics"; expected = $true })
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.7" }
    }
    if ($WithPip) {
        $payload.pip_id = "pip-$Token"
        $payload.pip_version = "12"
    }
    return $payload
}

function New-LifecycleCommand(
    [string]$MissionId,
    [string]$Command,
    [string]$Token,
    $TargetState = $null,
    $Metadata = $null,
    $EvidenceRefs = $null
) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    if ($null -eq $Metadata) { $Metadata = @{ acceptance = "stage3.2.7"; token = $Token } }
    if ($null -eq $EvidenceRefs) { $EvidenceRefs = @("evidence:stage3.2.7:acceptance") }
    $body = @{
        command_id = "lc-$Command-$Token"
        idempotency_key = "idem-lc-$Command-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.2.7-acceptance"
        reason_code = "STAGE327_$Command"
        reason = "Stage 3.2.7 lifecycle command $Command"
        evidence_refs = $EvidenceRefs
        metadata = $Metadata
    }
    if ($Command -eq "RESUME") { $body.target_state = $TargetState }
    return $body
}

function Activate-Running([string]$MissionId, [string]$Token) {
    $null = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId "BIND_PIP" "bind-$Token")
    $null = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId "START_PLANNING" "plan-$Token")
    $run = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" (New-LifecycleCommand $MissionId "START" "run-$Token")
    if ($run.mission_state.state -ne "RUNNING") { Fail "Activation helper did not reach RUNNING" }
}

function New-WaitCommand([string]$MissionId, [string]$Command, [string]$Token, [string]$DependencyId) {
    $kind = if ($Command -eq "WAIT_FOR_EVIDENCE") { "EVIDENCE" } else { "APPROVAL" }
    $metadata = @{
        acceptance = "stage3.2.7"
        dependency = @{
            dependency_id = $DependencyId
            kind = $kind
            description = "Stage 3.2.7 terminal-context dependency"
        }
    }
    return New-LifecycleCommand $MissionId $Command $Token $null $metadata @("dependency:request:$Token")
}

function New-DirectTransition([string]$MissionId, [string]$ToState, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    return @{
        expected_state_version = [int]$state.mission_state.state_version
        to_state = $ToState
        actor = "stage3.2.7-legacy-acceptance"
        reason_code = "LEGACY_$Token"
        reason = "Exercise preserved Stage-3.1 direct transition API"
        evidence_refs = @()
        metadata = @{ legacy_acceptance = $true; stage = "3.2.7" }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.7 - Abort, Failure & Expiration Semantics Acceptance"
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
    if ($joined -notmatch "216 passed") { Fail "Expected Stage-3.2.7 regression baseline of 216 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.7 regression baseline: 216 passed"

Write-Host "`n[2] Health / typed terminal semantics / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.2.7-abort-failure-expiration-semantics") { Fail "Stage 3.2.7 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Repository migration level changed from 8" }
if ($health.mission_terminal_semantics_schema_version -ne "apts-mission-terminal-semantics-v1") { Fail "Stage 3.2.7 terminal schema mismatch" }
if ($health.mission_terminal_semantics_mode -ne "DURABLE_TYPED_TERMINATION_CAUSE_WITH_IMMUTABLE_FINALITY_FAIL_CLOSED") { Fail "Stage 3.2.7 terminal mode mismatch" }
if ($health.mission_terminal_commands.ABORT -ne "ABORTED" -or $health.mission_terminal_commands.FAIL -ne "FAILED" -or $health.mission_terminal_commands.EXPIRE -ne "EXPIRED") { Fail "Typed terminal command mapping mismatch" }
if ($health.mission_terminal_state_immutability_enforced -ne $true) { Fail "Terminal state immutability is not enabled" }
if ($health.mission_terminal_evidence_refs_required -ne $false -or $health.mission_terminal_pip_binding_required -ne $false) { Fail "Fail-safe terminal exits unexpectedly require evidence or PIP" }
if ($health.mission_lifecycle_stage3_2_7_terminal_semantics_enabled -ne $true) { Fail "Stage 3.2.7 terminal semantics not enabled" }
if ($health.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $false) { Fail "Stage 3.2.7 must not claim Stage 3.2.8 completion gate" }
if ($health.mission_terminal_governance_query_performed -ne $false -or $health.mission_terminal_authorization_granted -ne $false -or $health.mission_terminal_execution_authorized -ne $false) { Fail "Terminal semantics expanded Governance/execution authority" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.2.7 active; migration=8 and Governance/target-execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] ABORT from RUNNING records durable controlled-stop semantics"
$abortMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "abort-$token")
$abortId = $abortMission.canonical_identity.mission_id
Activate-Running $abortId "abort-$token"
$abortMetadata = @{ acceptance = "stage3.2.7"; terminal = @{ abort_source = "OPERATOR" } }
$abortRequest = New-LifecycleCommand $abortId "ABORT" "abort-$token" $null $abortMetadata @("operator:abort:$token")
$historyBeforeAbort = Invoke-RestMethod "$MissionBaseUrl/api/missions/$abortId/state/transitions"
$eventsBeforeAbort = Invoke-RestMethod "$MissionBaseUrl/api/missions/$abortId/events"
$abort = Post-Json "$MissionBaseUrl/api/missions/$abortId/lifecycle/commands" $abortRequest
if ($abort.mission_state.state -ne "ABORTED") { Fail "ABORT did not reach ABORTED" }
if ($abort.terminal_control.schema_version -ne "apts-mission-terminal-semantics-v1") { Fail "ABORT terminal evidence schema mismatch" }
if ($abort.terminal_control.terminal_command -ne "ABORT" -or $abort.terminal_control.terminal_state -ne "ABORTED") { Fail "ABORT typed intent/target mismatch" }
if ($abort.terminal_control.from_state -ne "RUNNING") { Fail "ABORT did not preserve exact source state" }
if ($abort.terminal_control.cause_family -ne "CONTROLLED_STOP" -or $abort.terminal_control.disposition -ne "INTENTIONAL_ABORT") { Fail "ABORT semantic profile mismatch" }
if ($abort.terminal_control.terminal_context.abort_source -ne "OPERATOR") { Fail "ABORT terminal context was not preserved" }
if ($abort.terminal_control.verified_completion_claimed -ne $false) { Fail "ABORT incorrectly claimed verified completion" }
$abortView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$abortId/terminal-semantics-contract"
if ($abortView.terminal_semantics.current_terminal_lineage.valid -ne $true) { Fail "ABORT terminal lineage did not reconstruct as valid" }
if ($abortView.terminal_semantics.current_terminal_lineage.terminal_id -ne $abort.terminal_control.terminal_id) { Fail "ABORT projection terminal id mismatch" }
Pass "ABORT is a durable typed controlled stop, not success/failure conflation"

Write-Host "`n[4] Exact terminal replay is idempotent and appends no duplicate transition/event"
$historyAfterAbort = Invoke-RestMethod "$MissionBaseUrl/api/missions/$abortId/state/transitions"
$eventsAfterAbort = Invoke-RestMethod "$MissionBaseUrl/api/missions/$abortId/events"
if ([int]$historyAfterAbort.transition_count -ne ([int]$historyBeforeAbort.transition_count + 1)) { Fail "ABORT did not append exactly one transition" }
if ([int]$eventsAfterAbort.event_count -le [int]$eventsBeforeAbort.event_count) { Fail "ABORT did not append lifecycle event lineage" }
$abortReplay = Post-Json "$MissionBaseUrl/api/missions/$abortId/lifecycle/commands" $abortRequest
if ($abortReplay.idempotent_replay -ne $true) { Fail "Exact ABORT replay was not idempotent" }
if ($abortReplay.terminal_control.terminal_id -ne $abort.terminal_control.terminal_id) { Fail "ABORT replay changed terminal evidence identity" }
$historyAfterAbortReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$abortId/state/transitions"
$eventsAfterAbortReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$abortId/events"
if ([int]$historyAfterAbortReplay.transition_count -ne [int]$historyAfterAbort.transition_count) { Fail "ABORT replay duplicated transition lineage" }
if ([int]$eventsAfterAbortReplay.event_count -ne [int]$eventsAfterAbort.event_count) { Fail "ABORT replay duplicated event lineage" }
Pass "Terminal command replay is exactly-once with stable typed evidence"

Write-Host "`n[5] FAIL from WAITING_EVIDENCE preserves abandoned dependency context"
$failMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "fail-$token")
$failId = $failMission.canonical_identity.mission_id
Activate-Running $failId "fail-$token"
$dependencyId = "dep-terminal-fail-$token"
$wait = Post-Json "$MissionBaseUrl/api/missions/$failId/lifecycle/commands" (New-WaitCommand $failId "WAIT_FOR_EVIDENCE" "wait-$token" $dependencyId)
if ($wait.mission_state.state -ne "WAITING_EVIDENCE") { Fail "WAIT_FOR_EVIDENCE did not reach waiting state" }
$failMetadata = @{ acceptance = "stage3.2.7"; terminal = @{ failure_class = "UNRECOVERABLE_DEPENDENCY" } }
$failed = Post-Json "$MissionBaseUrl/api/missions/$failId/lifecycle/commands" (New-LifecycleCommand $failId "FAIL" "fail-$token" $null $failMetadata @("failure:evidence:$token"))
if ($failed.mission_state.state -ne "FAILED") { Fail "FAIL did not reach FAILED" }
if ($failed.terminal_control.cause_family -ne "FAILURE" -or $failed.terminal_control.disposition -ne "UNRECOVERABLE_FAILURE") { Fail "FAIL semantic profile mismatch" }
if ($failed.terminal_control.active_waiting_dependency.dependency_id -ne $dependencyId) { Fail "FAIL lost active waiting dependency identity" }
if (-not ($failed.terminal_control.abandoned_control_contexts -contains "WAITING_DEPENDENCY")) { Fail "FAIL did not mark waiting dependency abandoned" }
if ($failed.terminal_control.automatic_retry_allowed_after_terminal -ne $false) { Fail "FAILED terminal state unexpectedly allows automatic retry" }
Pass "FAIL preserves the exact blocked dependency and records unrecoverable failure semantics"

Write-Host "`n[6] EXPIRE from PAUSED preserves exact pause context"
$expireMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "expire-$token")
$expireId = $expireMission.canonical_identity.mission_id
Activate-Running $expireId "expire-$token"
$paused = Post-Json "$MissionBaseUrl/api/missions/$expireId/lifecycle/commands" (New-LifecycleCommand $expireId "PAUSE" "pause-$token")
if ($paused.mission_state.state -ne "PAUSED") { Fail "PAUSE did not reach PAUSED" }
$expireMetadata = @{ acceptance = "stage3.2.7"; terminal = @{ deadline_ref = "acceptance-deadline:$token" } }
$expired = Post-Json "$MissionBaseUrl/api/missions/$expireId/lifecycle/commands" (New-LifecycleCommand $expireId "EXPIRE" "expire-$token" $null $expireMetadata @("deadline:expired:$token"))
if ($expired.mission_state.state -ne "EXPIRED") { Fail "EXPIRE did not reach EXPIRED" }
if ($expired.terminal_control.cause_family -ne "EXPIRATION" -or $expired.terminal_control.disposition -ne "VALIDITY_EXPIRED") { Fail "EXPIRE semantic profile mismatch" }
if ($expired.terminal_control.active_pause.pause_id -ne $paused.pause_control.pause_id) { Fail "EXPIRE lost active pause identity" }
if ($expired.terminal_control.active_pause.paused_from_state -ne "RUNNING") { Fail "EXPIRE lost PAUSE source context" }
if (-not ($expired.terminal_control.abandoned_control_contexts -contains "PAUSE")) { Fail "EXPIRE did not mark PAUSE context abandoned" }
Pass "EXPIRE is distinguished from failure/abort and preserves the active pause lineage"

Write-Host "`n[7] Fail-safe terminal exits do not require PIP binding or evidence refs"
foreach ($pair in @(@("ABORT", "ABORTED"), @("FAIL", "FAILED"), @("EXPIRE", "EXPIRED"))) {
    $command = [string]$pair[0]
    $target = [string]$pair[1]
    $safeMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "safe-$command-$token" $false)
    $safeId = $safeMission.canonical_identity.mission_id
    $safeRequest = New-LifecycleCommand $safeId $command "safe-$command-$token" $null @{ acceptance = "stage3.2.7" } @()
    $safeResult = Post-Json "$MissionBaseUrl/api/missions/$safeId/lifecycle/commands" $safeRequest
    if ($safeResult.mission_state.state -ne $target) { Fail "$command without PIP/evidence did not reach $target" }
    if ([int]$safeResult.terminal_control.terminal_evidence_refs.Count -ne 0) { Fail "$command unexpectedly fabricated evidence refs" }
    $pipGuard = @($safeResult.lifecycle_guard.checks | Where-Object { $_.guard_id -eq "PIP_BINDING_COMPLETE_WHEN_REQUIRED" })[0]
    if ($null -eq $pipGuard -or $pipGuard.status -ne "PASS" -or $pipGuard.required -ne "NOT_REQUIRED") { Fail "$command fail-safe PIP guard semantics mismatch" }
}
Pass "ABORT/FAIL/EXPIRE remain available as fail-safe exits even without PIP or evidence refs"

Write-Host "`n[8] Terminal state finality blocks subsequent lifecycle and legacy-direct transitions"
$afterTerminal = New-LifecycleCommand $failId "ABORT" "after-failed-$token"
$terminalFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$failId/lifecycle/commands" $afterTerminal
if ($terminalFailure.status -ne 409 -or $terminalFailure.body.code -ne "MISSION_STATE_TRANSITION_ILLEGAL") { Fail "Lifecycle command escaped terminal-state immutability" }
if ($terminalFailure.body.message -notmatch "terminal mission state FAILED is immutable") { Fail "Terminal immutability failure did not identify FAILED finality" }
$directAfterTerminal = Get-PostFailure "$MissionBaseUrl/api/missions/$failId/state/transitions" (New-DirectTransition $failId "ABORTED" "after-failed-$token")
if ($directAfterTerminal.status -ne 409 -or $directAfterTerminal.body.code -ne "MISSION_STATE_TRANSITION_ILLEGAL") { Fail "Legacy direct transition escaped terminal-state immutability" }
Pass "Terminal finality is enforced consistently across lifecycle and preserved direct-transition APIs"

Write-Host "`n[9] Legacy direct terminal transition is visible but cannot fabricate Stage-3.2.7 evidence"
$legacyMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "legacy-terminal-$token" $false)
$legacyId = $legacyMission.canonical_identity.mission_id
$legacy = Post-Json "$MissionBaseUrl/api/missions/$legacyId/state/transitions" (New-DirectTransition $legacyId "ABORTED" "ABORT_$token")
if ($legacy.mission_state.state -ne "ABORTED") { Fail "Legacy direct transition did not reach ABORTED" }
$legacyView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$legacyId/terminal-semantics-contract"
if ($legacyView.terminal_semantics.current_terminal_lineage.valid -ne $false) { Fail "Legacy direct terminal transition was incorrectly accepted as typed Stage-3.2.7 lineage" }
if ($legacyView.terminal_semantics.current_terminal_lineage.status -ne "LEGACY_DIRECT_TERMINAL_TRANSITION_NO_STAGE_3_2_7_EVIDENCE") { Fail "Legacy direct terminal lineage status mismatch" }
Pass "Legacy terminal state remains observable but is explicitly distinguished from canonical typed termination"

Write-Host "`n[10] CLEANING_UP failure does not claim verified completion"
$cleanupMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "cleanup-$token")
$cleanupId = $cleanupMission.canonical_identity.mission_id
Activate-Running $cleanupId "cleanup-$token"
$cleanup = Post-Json "$MissionBaseUrl/api/missions/$cleanupId/lifecycle/commands" (New-LifecycleCommand $cleanupId "BEGIN_CLEANUP" "cleanup-$token")
if ($cleanup.mission_state.state -ne "CLEANING_UP") { Fail "BEGIN_CLEANUP did not reach CLEANING_UP" }
$cleanupFail = Post-Json "$MissionBaseUrl/api/missions/$cleanupId/lifecycle/commands" (New-LifecycleCommand $cleanupId "FAIL" "cleanup-fail-$token")
if ($cleanupFail.mission_state.state -ne "FAILED") { Fail "FAIL from CLEANING_UP did not reach FAILED" }
if ($cleanupFail.terminal_control.from_state -ne "CLEANING_UP") { Fail "Cleanup FAIL lost exact source state" }
if ($cleanupFail.terminal_control.verified_completion_claimed -ne $false -or $cleanupFail.terminal_control.cleanup_completion_gate_applied -ne $false) { Fail "Stage 3.2.7 incorrectly claimed Stage 3.2.8 verified completion semantics" }
Pass "Failure during cleanup remains failure; verified completion is still deferred to Stage 3.2.8"

Write-Host "`n[11] COMPLETED remains terminal but its verified completion semantics are deferred to Stage 3.2.8"
$completeMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "complete-$token")
$completeId = $completeMission.canonical_identity.mission_id
Activate-Running $completeId "complete-$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$completeId/lifecycle/commands" (New-LifecycleCommand $completeId "BEGIN_CLEANUP" "complete-cleanup-$token")
$completed = Post-Json "$MissionBaseUrl/api/missions/$completeId/lifecycle/commands" (New-LifecycleCommand $completeId "COMPLETE" "complete-$token")
if ($completed.mission_state.state -ne "COMPLETED") { Fail "COMPLETE did not reach COMPLETED" }
$completedView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$completeId/terminal-semantics-contract"
if ($completedView.terminal_semantics.current_terminal_lineage.status -ne "COMPLETED_TERMINAL_DEFERRED_TO_STAGE_3_2_8") { Fail "COMPLETED was not explicitly marked as Stage-3.2.8 deferred" }
if ($completedView.terminal_semantics.current_terminal_lineage.terminal_command -ne "COMPLETE") { Fail "COMPLETED projection lost COMPLETE intent" }
Pass "COMPLETED finality is preserved without prematurely claiming the Stage-3.2.8 completion gate"

Write-Host "`n[12] Final boundary / deferred-stage check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.7-abort-failure-expiration-semantics") { Fail "Control version changed during acceptance" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Migration level changed during acceptance" }
if ($finalHealth.mission_lifecycle_stage3_2_7_terminal_semantics_enabled -ne $true) { Fail "Stage 3.2.7 terminal semantics disabled during acceptance" }
if ($finalHealth.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $false) { Fail "Stage 3.2.8 completion gate unexpectedly enabled" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority changed" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary changed" }
Pass "Stage 3.2.7 preserves migration, Governance authority, target-execution boundary, and Stage-3.2.8 deferral"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.7 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
