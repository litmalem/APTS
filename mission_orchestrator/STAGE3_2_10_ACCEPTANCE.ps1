param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.10 ACCEPTANCE: FAIL" -ForegroundColor Red
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

function New-MissionPayload([string]$Token, [int]$CriteriaCount = 2) {
    $criteria = @()
    for ($i = 0; $i -lt $CriteriaCount; $i++) {
        $criteria += @{ metric = "stage3210_criterion_$i"; expected = $true }
    }
    return @{
        idempotency_key = "stage3210-mission-$Token"
        source_system = "STAGE3210_ACCEPTANCE"
        created_by = "stage3.2.10-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage3210-lab" }
        success_criteria = $criteria
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-$Token"
        pip_version = "14"
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.10" }
    }
}

function New-LifecycleCommand(
    [string]$MissionId,
    [string]$Command,
    [string]$Token,
    $Metadata = $null,
    $EvidenceRefs = $null,
    $TargetState = $null
) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    if ($null -eq $Metadata) { $Metadata = @{ acceptance = "stage3.2.10" } }
    if ($null -eq $EvidenceRefs) { $EvidenceRefs = @("evidence:stage3210:$Token") }
    $body = @{
        command_id = "lc-stage3210-$Token"
        idempotency_key = "idem-lc-stage3210-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.2.10-acceptance"
        reason_code = "STAGE3210_$Command"
        reason = "Stage 3.2.10 acceptance command $Command"
        evidence_refs = $EvidenceRefs
        metadata = $Metadata
    }
    if ($null -ne $TargetState) { $body.target_state = $TargetState }
    return $body
}

function New-LifecycleEvent([string]$MissionId, [string]$EventType, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        event_id = "stage3210-event-$Token"
        event_type = $EventType
        source_component = "STAGE3210-ACCEPTANCE-SOURCE"
        occurred_at = [DateTimeOffset]::UtcNow.ToString("o")
        observed_state = $state.mission_state.state
        observed_state_version = [int]$state.mission_state.state_version
        observed_version_sha256 = $vector.version_sha256
        actor = "stage3.2.10-event-adapter"
        reason_code = "STAGE3210_$EventType"
        reason = "Stage 3.2.10 acceptance event $EventType"
        evidence_refs = @()
        metadata = @{ acceptance = "stage3.2.10" }
    }
}

function New-CompletionBundle([string]$Prefix, [int]$CriteriaCount = 2) {
    $objectiveRef = "evidence:objective:$Prefix"
    $criteriaResults = @()
    $refs = @($objectiveRef)
    for ($i = 0; $i -lt $CriteriaCount; $i++) {
        $ref = "evidence:criterion:$i`:$Prefix"
        $refs += $ref
        $criteriaResults += @{
            criterion_index = $i
            status = "SATISFIED"
            evidence_refs = @($ref)
        }
    }
    $cleanupRef = "evidence:cleanup:$Prefix"
    $refs += $cleanupRef
    $metadata = @{
        acceptance = "stage3.2.10"
        completion = @{
            verification_status = "VERIFIED"
            objective_status = "SATISFIED"
            objective_evidence_refs = @($objectiveRef)
            success_criteria_status = "SATISFIED"
            criteria_results = $criteriaResults
            cleanup_status = "VERIFIED"
            cleanup_checks = @(
                @{
                    check_id = "CONTROLLED_CLEANUP_VERIFIED"
                    status = "PASS"
                    evidence_refs = @($cleanupRef)
                }
            )
            outstanding_critical_dependencies = 0
        }
    }
    return @{ refs = $refs; metadata = $metadata }
}

function Invoke-Lifecycle([string]$MissionId, [string]$Command, [string]$Token, $Metadata = $null, $EvidenceRefs = $null, $TargetState = $null) {
    $request = New-LifecycleCommand $MissionId $Command $Token $Metadata $EvidenceRefs $TargetState
    return Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $request
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.10 - Lifecycle Acceptance & Regression Gate"
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
    if ($joined -notmatch "267 passed") { Fail "Expected Stage-3.2.10 regression baseline of 267 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.10 regression baseline: 267 passed"

Write-Host "`n[2] Health / closure contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.2.10-lifecycle-acceptance-regression-gate") { Fail "Stage 3.2.10 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Repository migration level changed from 8" }
if ($health.stage3_2_lifecycle_acceptance_gate_schema_version -ne "apts-mission-stage3.2-lifecycle-acceptance-gate-v1") { Fail "Stage-3.2 closure schema mismatch" }
if ($health.stage3_2_lifecycle_acceptance_gate_mode -ne "FULL_REGRESSION_PLUS_LIVE_LIFECYCLE_CONTRACT_PROBES") { Fail "Stage-3.2 closure mode mismatch" }
if ($health.stage3_2_lifecycle_acceptance_gate_baseline -ne "STAGE_3_2_1_THROUGH_3_2_9") { Fail "Stage-3.2 closure baseline mismatch" }
if ($health.stage3_2_lifecycle_acceptance_gate_declared_only -ne $true -or $health.stage3_2_lifecycle_acceptance_gate_runtime_self_certification -ne $false) { Fail "Runtime incorrectly self-certifies acceptance" }
if ($health.stage3_2_lifecycle_acceptance_gate_external_execution_required -ne $true) { Fail "External acceptance execution is not required" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.mission_lifecycle_automation_external_event_delivery_enabled -ne $false) { Fail "External event delivery was unexpectedly enabled" }
if ($health.mission_lifecycle_automation_planner_invocation_performed -ne $false) { Fail "Planner invocation was unexpectedly enabled" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
$requiredControls = @(
    "stage3.2.1-mission-lifecycle-command-contract",
    "stage3.2.2-lifecycle-transition-guard-matrix",
    "stage3.2.3-mission-pip-activation",
    "stage3.2.4-planning-run-activation",
    "stage3.2.5-waiting-dependency-control",
    "stage3.2.6-pause-resume-replanning-control",
    "stage3.2.7-abort-failure-expiration-semantics",
    "stage3.2.8-cleanup-verified-completion-gate",
    "stage3.2.9-event-driven-lifecycle-automation-reliability",
    "stage3.2.10-lifecycle-acceptance-regression-gate"
)
foreach ($control in $requiredControls) {
    if (@($health.supported_controls) -notcontains $control) { Fail "Missing supported control: $control" }
}
Pass "Stage 3.2 closure contract active; migration=8 and authority/execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Lifecycle command discovery + PIP/planning/run activation + replay"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "main-$token" 2)
$missionId = $mission.canonical_identity.mission_id
$contract = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/lifecycle-command-contract"
if ($contract.lifecycle_command_contract.schema_version -ne "apts-mission-lifecycle-command-v1") { Fail "Lifecycle command contract schema mismatch" }
if ($contract.lifecycle_guard_matrix.schema_version -ne "apts-mission-lifecycle-guard-matrix-v1") { Fail "Lifecycle guard matrix schema mismatch" }
$bindRequest = New-LifecycleCommand $missionId "BIND_PIP" "bind-$token"
$bind = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $bindRequest
$bindReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $bindRequest
if ($bind.mission_state.state -ne "PIP_BOUND" -or $bindReplay.idempotent_replay -ne $true) { Fail "BIND_PIP activation/replay failed" }
$planning = Invoke-Lifecycle $missionId "START_PLANNING" "planning-$token"
$running = Invoke-Lifecycle $missionId "START" "running-$token"
if ($planning.mission_state.state -ne "PLANNING" -or $running.mission_state.state -ne "RUNNING") { Fail "PIP_BOUND -> PLANNING -> RUNNING activation failed" }
if ($running.planning_run_activation.planning_activation_proof.valid -ne $true) { Fail "Planning activation lineage proof is invalid" }
if ($running.planning_run_activation.planner_invocation_performed -ne $false -or $running.planning_run_activation.execution_authorized -ne $false) { Fail "Activation expanded planner/execution authority" }
Pass "Stages 3.2.1-3.2.4 command, guard, activation, and idempotency semantics PASS"

Write-Host "`n[4] Waiting evidence + approval resolution"
$evidenceDep = "dep-stage3210-evidence-$token"
$waitEvidenceMeta = @{ acceptance = "stage3.2.10"; dependency = @{ dependency_id = $evidenceDep; kind = "EVIDENCE"; description = "Acceptance evidence dependency" } }
$waitEvidence = Invoke-Lifecycle $missionId "WAIT_FOR_EVIDENCE" "wait-evidence-$token" $waitEvidenceMeta @("evidence:dependency:requested:$token")
if ($waitEvidence.mission_state.state -ne "WAITING_EVIDENCE") { Fail "WAIT_FOR_EVIDENCE did not enter WAITING_EVIDENCE" }
$resolveEvidenceMeta = @{ acceptance = "stage3.2.10"; dependency_resolution = @{ dependency_id = $evidenceDep; status = "SATISFIED"; resolved_by = "stage3.2.10-acceptance" } }
$resolvedEvidence = Invoke-Lifecycle $missionId "START" "resolve-evidence-$token" $resolveEvidenceMeta @("evidence:dependency:resolved:$token")
if ($resolvedEvidence.mission_state.state -ne "RUNNING") { Fail "Evidence dependency did not return to RUNNING" }

$approvalDep = "dep-stage3210-approval-$token"
$waitApprovalMeta = @{ acceptance = "stage3.2.10"; dependency = @{ dependency_id = $approvalDep; kind = "APPROVAL"; description = "Acceptance workflow approval" } }
$waitApproval = Invoke-Lifecycle $missionId "WAIT_FOR_APPROVAL" "wait-approval-$token" $waitApprovalMeta @()
if ($waitApproval.mission_state.state -ne "WAITING_APPROVAL") { Fail "WAIT_FOR_APPROVAL did not enter WAITING_APPROVAL" }
$resolveApprovalMeta = @{ acceptance = "stage3.2.10"; dependency_resolution = @{ dependency_id = $approvalDep; status = "SATISFIED"; resolved_by = "human-review" } }
$resolvedApproval = Invoke-Lifecycle $missionId "START" "resolve-approval-$token" $resolveApprovalMeta @("evidence:approval:$token")
if ($resolvedApproval.mission_state.state -ne "RUNNING") { Fail "Approval dependency did not return to RUNNING" }
if ($resolvedApproval.waiting_dependency_resolution.approval_dependency_is_governance_authorization -ne $false) { Fail "Workflow approval was confused with Governance authorization" }
Pass "Stage 3.2.5 evidence/approval waiting and resolution semantics PASS"

Write-Host "`n[5] Pause / resume / replanning control"
$paused = Invoke-Lifecycle $missionId "PAUSE" "pause-$token"
if ($paused.mission_state.state -ne "PAUSED") { Fail "PAUSE did not enter PAUSED" }
$pauseId = $paused.pause_control.pause_id
$resumed = Invoke-Lifecycle $missionId "RESUME" "resume-$token" @{} @() "RUNNING"
if ($resumed.mission_state.state -ne "RUNNING" -or $resumed.resume_control.pause_id -ne $pauseId) { Fail "RESUME did not preserve pause lineage" }
$replan = Invoke-Lifecycle $missionId "REPLAN" "replan-$token" @{} @("evidence:replan:trigger:$token")
if ($replan.mission_state.state -ne "REPLANNING") { Fail "REPLAN did not enter REPLANNING" }
$notReadyRequest = New-LifecycleCommand $missionId "START" "replan-not-ready-$token" @{} @()
$notReady = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $notReadyRequest
if ([int]$notReady.status -ne 409 -or $notReady.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "REPLANNING without readiness evidence did not fail closed" }
$ready = Invoke-Lifecycle $missionId "START" "replan-ready-$token" @{} @("evidence:replan:ready:$token")
if ($ready.mission_state.state -ne "RUNNING" -or $ready.replan_resolution.readiness_status -ne "READY") { Fail "Replanning readiness did not return to RUNNING" }
Pass "Stage 3.2.6 pause/resume/replanning lineage and readiness gates PASS"

Write-Host "`n[6] Cleanup + verified completion gate"
$cleanup = Invoke-Lifecycle $missionId "BEGIN_CLEANUP" "cleanup-$token" @{} @("evidence:cleanup:start:$token")
if ($cleanup.mission_state.state -ne "CLEANING_UP") { Fail "BEGIN_CLEANUP did not enter CLEANING_UP" }
$badCompleteRequest = New-LifecycleCommand $missionId "COMPLETE" "complete-missing-$token" @{} @("evidence:insufficient:$token")
$badComplete = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $badCompleteRequest
if ([int]$badComplete.status -ne 409 -or $badComplete.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "Incomplete completion evidence did not fail closed" }
$completion = New-CompletionBundle "stage3210-$token" 2
$completed = Invoke-Lifecycle $missionId "COMPLETE" "complete-$token" $completion.metadata $completion.refs
if ($completed.mission_state.state -ne "COMPLETED") { Fail "Verified COMPLETE did not reach COMPLETED" }
if ($completed.completion_verification.verified_completion_claimed -ne $true -or $completed.completion_verification.cleanup_completion_gate_applied -ne $true) { Fail "Verified completion evidence is incomplete" }
Pass "Stage 3.2.8 cleanup and evidence-gated verified completion PASS"

Write-Host "`n[7] Abort / failure / expiration are distinct immutable terminal semantics"
$terminalCases = @(
    @{ event = "ABORT"; state = "ABORTED" },
    @{ event = "FAIL"; state = "FAILED" },
    @{ event = "EXPIRE"; state = "EXPIRED" }
)
foreach ($case in $terminalCases) {
    $terminalMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "$($case.event.ToLower())-$token" 1)
    $terminalId = $terminalMission.canonical_identity.mission_id
    $terminalResult = Invoke-Lifecycle $terminalId $case.event "$($case.event.ToLower())-$token" @{} @("evidence:terminal:$($case.event):$token")
    if ($terminalResult.mission_state.state -ne $case.state) { Fail "$($case.event) did not reach $($case.state)" }
    if ($terminalResult.terminal_control.terminal_state -ne $case.state) { Fail "$($case.event) terminal evidence mismatch" }
    $afterTerminal = New-LifecycleCommand $terminalId "PAUSE" "after-$($case.event.ToLower())-$token"
    $terminalFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$terminalId/lifecycle/commands" $afterTerminal
    if ([int]$terminalFailure.status -ne 409 -or $terminalFailure.body.code -ne "MISSION_STATE_TRANSITION_ILLEGAL") { Fail "$($case.state) allowed an outgoing lifecycle transition" }
}
Pass "Stage 3.2.7 ABORTED/FAILED/EXPIRED semantics are distinct and immutable"

Write-Host "`n[8] Event automation replay + stale/out-of-order rejection"
$eventMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "event-$token" 1)
$eventMissionId = $eventMission.canonical_identity.mission_id
$event = New-LifecycleEvent $eventMissionId "PIP_BIND_REQUESTED" "bind-$token"
$eventFirst = Post-Json "$MissionBaseUrl/api/missions/$eventMissionId/lifecycle/events" $event
$historyBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$eventMissionId/state/transitions"
$eventsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$eventMissionId/events"
$eventReplay = Post-Json "$MissionBaseUrl/api/missions/$eventMissionId/lifecycle/events" $event
$historyAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$eventMissionId/state/transitions"
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$eventMissionId/events"
if ($eventFirst.automation_status -ne "APPLIED" -or $eventReplay.idempotent_replay -ne $true) { Fail "Exact event replay did not return idempotent success" }
if ([int]$historyAfterReplay.transition_count -ne [int]$historyBeforeReplay.transition_count -or [int]$eventsAfterReplay.event_count -ne [int]$eventsBeforeReplay.event_count) { Fail "Exact event replay created duplicate side effects" }
$stale = New-LifecycleEvent $eventMissionId "PLANNING_START_REQUESTED" "stale-$token"
$stale.observed_state_version = [int]$stale.observed_state_version - 1
$staleFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$eventMissionId/lifecycle/events" $stale
if ([int]$staleFailure.status -ne 409 -or $staleFailure.body.code -ne "MISSION_VERSION_CONFLICT") { Fail "Stale lifecycle event did not fail closed with version conflict" }
Pass "Stage 3.2.9 event automation is idempotent and stale/out-of-order events fail closed"

Write-Host "`n[9] Event lineage + repository integrity"
$lineage = Invoke-RestMethod "$MissionBaseUrl/api/missions/$eventMissionId/lineage"
$repository = Invoke-RestMethod "$MissionBaseUrl/api/missions/$eventMissionId/repository"
if ($lineage.integrity_status -ne "PASS" -or $repository.integrity_status -ne "PASS") { Fail "Lineage or repository integrity did not PASS" }
if ([int]$repository.repository.migration_level -ne 8) { Fail "Repository projection migration level is not 8" }
if ($lineage.external_authority_query_performed -ne $false -or $lineage.target_action_dispatch_enabled -ne $false -or $lineage.target_actuation -ne $false) { Fail "Lineage read changed authority/execution boundary" }
Pass "Append-only event lineage and durable repository integrity PASS"

Write-Host "`n[10] Final Stage-3.2 closure invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.10-lifecycle-acceptance-regression-gate") { Fail "Final control version drifted" }
if ($finalHealth.stage3_2_lifecycle_acceptance_gate_declared_only -ne $true -or $finalHealth.stage3_2_lifecycle_acceptance_gate_runtime_self_certification -ne $false) { Fail "Final acceptance declaration semantics drifted" }
if ($finalHealth.mission_lifecycle_stage3_2_9_event_automation_enabled -ne $true) { Fail "Stage 3.2.9 automation was disabled by closure" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Final Governance authority boundary drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Final repository migration level drifted" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Final target execution boundary drifted" }
Pass "Stage 3.2 closes with external Governance authority, no planner/execution expansion, and migration level 8"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.10 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Main Mission        : $missionId"
Write-Host "Completed State     : $($completed.mission_state.state)"
Write-Host "Event Mission       : $eventMissionId"
Write-Host "Regression Baseline : 267 passed"
Write-Host "Repository SHA256   : $($repository.repository_sha256)"
Write-Host "Target Dispatch     : $($finalHealth.target_action_dispatch_enabled)"
Write-Host "=============================================================================="
exit 0
