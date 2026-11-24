param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.6 ACCEPTANCE: FAIL" -ForegroundColor Red
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

function New-MissionPayload([string]$Token) {
    return @{
        idempotency_key = "stage326-mission-$Token"
        source_system = "STAGE326_ACCEPTANCE"
        created_by = "stage3.2.6-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage326-lab" }
        success_criteria = @(@{ metric = "stage326_pause_resume_replan_control"; expected = $true })
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-$Token"
        pip_version = "11"
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.6" }
    }
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
    if ($null -eq $Metadata) { $Metadata = @{ acceptance = "stage3.2.6"; token = $Token } }
    if ($null -eq $EvidenceRefs) { $EvidenceRefs = @("evidence:stage3.2.6:acceptance") }
    $body = @{
        command_id = "lc-$Command-$Token"
        idempotency_key = "idem-lc-$Command-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.2.6-acceptance"
        reason_code = "STAGE326_$Command"
        reason = "Stage 3.2.6 lifecycle command $Command"
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
        acceptance = "stage3.2.6"
        dependency = @{ dependency_id = $DependencyId; kind = $kind; description = "Stage 3.2.6 waiting dependency" }
    }
    return New-LifecycleCommand $MissionId $Command $Token $null $metadata @("dependency:request:$Token")
}

function New-DirectTransition([string]$MissionId, [string]$ToState, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    return @{
        expected_state_version = [int]$state.mission_state.state_version
        to_state = $ToState
        actor = "stage3.2.6-legacy-acceptance"
        reason_code = "LEGACY_$Token"
        reason = "Exercise preserved Stage-3.1 direct transition API"
        evidence_refs = @()
        metadata = @{ legacy_acceptance = $true; stage = "3.2.6" }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.6 - Pause, Resume & Replanning Control Acceptance"
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
    if ($joined -notmatch "199 passed") { Fail "Expected Stage-3.2.6 regression baseline of 199 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.6 regression baseline: 199 passed"

Write-Host "`n[2] Health / pause-resume-replan contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.2.6-pause-resume-replanning-control") { Fail "Stage 3.2.6 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Repository migration level changed from 8" }
if ($health.mission_pause_resume_replan_schema_version -ne "apts-mission-pause-resume-replan-control-v1") { Fail "Stage 3.2.6 schema mismatch" }
if ($health.mission_lifecycle_stage3_2_6_pause_resume_replan_enabled -ne $true) { Fail "Stage 3.2.6 control not enabled" }
if ($health.mission_pause_resume_replan_planner_invocation_performed -ne $false) { Fail "Stage 3.2.6 must not invoke planner" }
if ($health.mission_pause_resume_replan_governance_query_performed -ne $false) { Fail "Stage 3.2.6 must not query Governance" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.2.6 contract active; migration, planner, Governance, and target-execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] PAUSE from RUNNING records durable exact-source context"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "pause-$token")
$missionId = $mission.canonical_identity.mission_id
Activate-Running $missionId "pause-$token"
$pauseCommand = New-LifecycleCommand $missionId "PAUSE" "pause-$token"
$pause = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $pauseCommand
if ($pause.mission_state.state -ne "PAUSED") { Fail "PAUSE did not reach PAUSED" }
if ($pause.pause_control.schema_version -ne "apts-mission-pause-resume-replan-control-v1") { Fail "Pause evidence schema mismatch" }
if ($pause.pause_control.from_state -ne "RUNNING" -or $pause.pause_control.to_state -ne "PAUSED") { Fail "Pause evidence source/target mismatch" }
if ($pause.pause_control.authorization_granted -ne $false -or $pause.pause_control.planner_invocation_performed -ne $false) { Fail "PAUSE expanded authority" }
$pauseView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/pause-resume-replan-contract"
if ($pauseView.pause_resume_replan.pause.active_pause.valid -ne $true) { Fail "Pause projection did not reconstruct durable pause lineage" }
if (($pauseView.pause_resume_replan.resume.allowed_targets_for_active_pause -join ",") -ne "RUNNING") { Fail "Paused RUNNING resume target policy mismatch" }
Pass "PAUSED preserves exact RUNNING source context and exposes deterministic resume policy"

Write-Host "`n[4] Legacy direct PAUSED cannot bypass Stage-3.2.6 pause lineage"
$legacyPauseMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "legacy-pause-$token")
$legacyPauseId = $legacyPauseMission.canonical_identity.mission_id
Activate-Running $legacyPauseId "legacy-pause-$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$legacyPauseId/state/transitions" (New-DirectTransition $legacyPauseId "PAUSED" "PAUSE_$token")
$legacyResume = New-LifecycleCommand $legacyPauseId "RESUME" "legacy-resume-$token" "RUNNING"
$legacyPauseFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$legacyPauseId/lifecycle/commands" $legacyResume
if ($legacyPauseFailure.status -ne 409 -or $legacyPauseFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "Legacy PAUSED bypass did not fail closed" }
if ($legacyPauseFailure.body.message -notmatch "PAUSE_LINEAGE_FOR_RESUME") { Fail "Expected PAUSE_LINEAGE_FOR_RESUME guard rejection" }
Pass "Topology-valid PAUSED is insufficient without canonical Stage-3.2.6 pause lineage"

Write-Host "`n[5] RESUME restores the permitted paused source and exact replay is idempotent"
$historyBeforeResume = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$eventsBeforeResume = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$resumeCommand = New-LifecycleCommand $missionId "RESUME" "resume-$token" "RUNNING"
$resume = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $resumeCommand
if ($resume.mission_state.state -ne "RUNNING") { Fail "RESUME did not restore RUNNING" }
if ($resume.resume_control.pause_id -ne $pause.pause_control.pause_id) { Fail "RESUME did not bind to active pause id" }
if ($resume.resume_control.resume_prerequisite.valid -ne $true) { Fail "RESUME prerequisite lineage is not valid" }
$historyAfterResume = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$eventsAfterResume = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ([int]$historyAfterResume.transition_count -ne ([int]$historyBeforeResume.transition_count + 1)) { Fail "RESUME did not append exactly one transition" }
if ([int]$eventsAfterResume.event_count -le [int]$eventsBeforeResume.event_count) { Fail "RESUME did not append lineage events" }
$resumeReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $resumeCommand
if ($resumeReplay.idempotent_replay -ne $true) { Fail "Exact RESUME replay was not idempotent" }
$historyAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
if ([int]$historyAfterReplay.transition_count -ne [int]$historyAfterResume.transition_count) { Fail "RESUME replay duplicated transition lineage" }
Pass "RESUME is pause-lineage bound, restores only the permitted state, and is idempotent"

Write-Host "`n[6] Paused waiting dependency cannot bypass satisfaction; safe continuation is REPLANNING"
$waitMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "wait-$token")
$waitId = $waitMission.canonical_identity.mission_id
Activate-Running $waitId "wait-$token"
$depId = "dep-stage326-$token"
$wait = Post-Json "$MissionBaseUrl/api/missions/$waitId/lifecycle/commands" (New-WaitCommand $waitId "WAIT_FOR_APPROVAL" "wait-$token" $depId)
if ($wait.mission_state.state -ne "WAITING_APPROVAL") { Fail "WAIT_FOR_APPROVAL did not reach waiting state" }
$waitPause = Post-Json "$MissionBaseUrl/api/missions/$waitId/lifecycle/commands" (New-LifecycleCommand $waitId "PAUSE" "wait-pause-$token")
if ($waitPause.pause_control.active_waiting_dependency.dependency_id -ne $depId) { Fail "Pause did not preserve active waiting dependency" }
$badWaitResume = New-LifecycleCommand $waitId "RESUME" "wait-running-$token" "RUNNING"
$badWaitResumeFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$waitId/lifecycle/commands" $badWaitResume
if ($badWaitResumeFailure.status -ne 409 -or $badWaitResumeFailure.body.message -notmatch "RESUME_TARGET_POLICY_FOR_PAUSED_SOURCE") { Fail "Paused waiting dependency resumed directly to RUNNING" }
$safeResume = Post-Json "$MissionBaseUrl/api/missions/$waitId/lifecycle/commands" (New-LifecycleCommand $waitId "RESUME" "wait-replan-$token" "REPLANNING")
if ($safeResume.mission_state.state -ne "REPLANNING") { Fail "Safe waiting resume did not reach REPLANNING" }
if ($safeResume.resume_control.waiting_dependency_abandoned -ne $true) { Fail "Safe waiting continuation did not mark dependency abandoned" }
if ($safeResume.replan_control.abandoned_waiting_dependency.dependency_id -ne $depId) { Fail "Replan evidence lost abandoned dependency identity" }
if ($safeResume.replan_control.authorization_granted -ne $false -or $safeResume.replan_control.planner_invocation_performed -ne $false) { Fail "Safe continuation expanded planner/Governance authority" }
Pass "Paused waiting state cannot claim dependency satisfaction; it can only continue safely through REPLANNING"

Write-Host "`n[7] REPLAN creates durable local episode; legacy direct REPLANNING cannot progress"
$replanMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "replan-$token")
$replanId = $replanMission.canonical_identity.mission_id
Activate-Running $replanId "replan-$token"
$replan = Post-Json "$MissionBaseUrl/api/missions/$replanId/lifecycle/commands" (New-LifecycleCommand $replanId "REPLAN" "replan-$token")
if ($replan.mission_state.state -ne "REPLANNING") { Fail "REPLAN did not reach REPLANNING" }
if ($replan.replan_control.origin -ne "REPLAN_COMMAND") { Fail "Replan origin mismatch" }
if ($replan.replan_control.planner_invocation_performed -ne $false -or $replan.replan_control.plan_artifact_created -ne $false) { Fail "REPLAN unexpectedly invoked planner or created plan artifact" }
$legacyReplanMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "legacy-replan-$token")
$legacyReplanId = $legacyReplanMission.canonical_identity.mission_id
Activate-Running $legacyReplanId "legacy-replan-$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$legacyReplanId/state/transitions" (New-DirectTransition $legacyReplanId "REPLANNING" "REPLAN_$token")
$legacyStart = New-LifecycleCommand $legacyReplanId "START" "legacy-start-$token" $null $null @("replan:ready:legacy")
$legacyReplanFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$legacyReplanId/lifecycle/commands" $legacyStart
if ($legacyReplanFailure.status -ne 409 -or $legacyReplanFailure.body.message -notmatch "REPLAN_LINEAGE_FOR_REPLANNING_PROGRESS") { Fail "Legacy REPLANNING bypass did not fail closed" }
Pass "REPLANNING progress requires durable Stage-3.2.6 replan lineage without invoking a planner"

Write-Host "`n[8] START from REPLANNING requires readiness evidence and returns RUNNING idempotently"
$noEvidenceStart = New-LifecycleCommand $replanId "START" "no-evidence-$token" $null $null @()
$noEvidenceFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$replanId/lifecycle/commands" $noEvidenceStart
if ($noEvidenceFailure.status -ne 409 -or $noEvidenceFailure.body.message -notmatch "REPLAN_READINESS_EVIDENCE_FOR_RETURN") { Fail "REPLANNING START without readiness evidence did not fail closed" }
$readyStart = New-LifecycleCommand $replanId "START" "ready-$token" $null $null @("plan-readiness:revision:$token")
$ready = Post-Json "$MissionBaseUrl/api/missions/$replanId/lifecycle/commands" $readyStart
if ($ready.mission_state.state -ne "RUNNING") { Fail "Ready replanning episode did not return to RUNNING" }
if ($ready.replan_resolution.readiness_status -ne "READY" -or $ready.replan_resolution.readiness_ready -ne $true) { Fail "Replan readiness evidence mismatch" }
if ($ready.replan_resolution.replan_id -ne $replan.replan_control.replan_id) { Fail "Replan readiness did not bind to active replan id" }
if ($ready.replan_resolution.authorization_granted -ne $false -or $ready.replan_resolution.execution_authorized -ne $false) { Fail "Replan readiness was conflated with execution authorization" }
$readyHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$replanId/state/transitions"
$readyReplay = Post-Json "$MissionBaseUrl/api/missions/$replanId/lifecycle/commands" $readyStart
if ($readyReplay.idempotent_replay -ne $true) { Fail "Exact replan readiness replay was not idempotent" }
$readyHistoryReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$replanId/state/transitions"
if ([int]$readyHistoryReplay.transition_count -ne [int]$readyHistory.transition_count) { Fail "Replan readiness replay duplicated transition lineage" }
Pass "REPLANNING returns to RUNNING only with active replan lineage plus explicit readiness evidence"

Write-Host "`n[9] Final boundary / deferred-stage check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.6-pause-resume-replanning-control") { Fail "Control version changed during acceptance" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Migration level changed during acceptance" }
if ($finalHealth.mission_lifecycle_stage3_2_7_terminal_semantics_enabled -ne $false) { Fail "Stage 3.2.6 must not claim Stage 3.2.7 terminal semantics" }
if ($finalHealth.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $false) { Fail "Stage 3.2.6 must not claim Stage 3.2.8 completion gate" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority changed" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary changed" }
Pass "Stage 3.2.6 preserved later lifecycle, Governance, migration, planner, and target-execution boundaries"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.6 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
