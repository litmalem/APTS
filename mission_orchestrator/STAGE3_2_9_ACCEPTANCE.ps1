param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.9 ACCEPTANCE: FAIL" -ForegroundColor Red
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

function Assert-HttpError($Failure, [int]$Status, [string]$Code, [string]$Context) {
    if ([int]$Failure.status -ne $Status) { Fail "$Context did not fail with HTTP $Status" }
    if ($null -eq $Failure.body -or $Failure.body.code -ne $Code) {
        Fail "$Context did not fail with $Code"
    }
}

function New-MissionPayload([string]$Token, [int]$CriteriaCount = 2) {
    $criteria = @()
    for ($i = 0; $i -lt $CriteriaCount; $i++) {
        $criteria += @{ metric = "stage329_criterion_$i"; expected = $true }
    }
    return @{
        idempotency_key = "stage329-mission-$Token"
        source_system = "STAGE329_ACCEPTANCE"
        created_by = "stage3.2.9-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage329-lab" }
        success_criteria = $criteria
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-$Token"
        pip_version = "13"
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.9" }
    }
}

function New-LifecycleEvent(
    [string]$MissionId,
    [string]$EventType,
    [string]$Token,
    $Metadata = $null,
    $EvidenceRefs = $null,
    $TargetState = $null,
    [string]$EventId = $null
) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    if ($null -eq $Metadata) { $Metadata = @{} }
    if ($null -eq $EvidenceRefs) { $EvidenceRefs = @() }
    if ([string]::IsNullOrWhiteSpace($EventId)) { $EventId = "source-event-$Token" }
    $body = @{
        event_id = $EventId
        event_type = $EventType
        source_component = "STAGE329-ACCEPTANCE-SOURCE"
        occurred_at = [DateTimeOffset]::UtcNow.ToString("o")
        observed_state = $state.mission_state.state
        observed_state_version = [int]$state.mission_state.state_version
        observed_version_sha256 = $vector.version_sha256
        actor = "stage3.2.9-event-adapter"
        reason = "Stage 3.2.9 acceptance event $EventType"
        evidence_refs = $EvidenceRefs
        metadata = $Metadata
    }
    if ($null -ne $TargetState) { $body.target_state = $TargetState }
    return $body
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

function Activate-Running-ByEvents([string]$MissionId, [string]$Token) {
    $bind = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/events" (New-LifecycleEvent $MissionId "PIP_BIND_REQUESTED" "bind-$Token")
    if ($bind.mission_state.state -ne "PIP_BOUND") { Fail "Event activation helper failed at PIP_BOUND" }
    $plan = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/events" (New-LifecycleEvent $MissionId "PLANNING_START_REQUESTED" "plan-$Token")
    if ($plan.mission_state.state -ne "PLANNING") { Fail "Event activation helper failed at PLANNING" }
    $run = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/events" (New-LifecycleEvent $MissionId "RUN_START_REQUESTED" "run-$Token")
    if ($run.mission_state.state -ne "RUNNING") { Fail "Event activation helper failed at RUNNING" }
    return $run
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.9 - Event-Driven Lifecycle Automation & Reliability Acceptance"
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
    if ($joined -notmatch "255 passed") { Fail "Expected Stage-3.2.9 regression baseline of 255 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.9 regression baseline: 255 passed"

Write-Host "`n[2] Health / automation contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.2.9-event-driven-lifecycle-automation-reliability") { Fail "Stage 3.2.9 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Repository migration level changed from 8" }
if ($health.mission_lifecycle_automation_schema_version -ne "apts-mission-lifecycle-automation-v1") { Fail "Lifecycle automation schema mismatch" }
if ($health.mission_lifecycle_automation_mode -ne "TYPED_EVENT_TO_GUARDED_IDEMPOTENT_LIFECYCLE_COMMAND_FAIL_CLOSED") { Fail "Lifecycle automation mode mismatch" }
if ($health.mission_lifecycle_automation_uses_existing_command_journal -ne $true) { Fail "Existing command journal is not declared as automation gate" }
if ($health.mission_lifecycle_automation_uses_existing_event_ledger -ne $true) { Fail "Existing Mission event ledger is not declared as automation audit substrate" }
if ($health.mission_lifecycle_automation_direct_state_mutation_allowed -ne $false) { Fail "Blind/direct state mutation was enabled" }
if ($health.mission_lifecycle_automation_exact_state_version_binding_required -ne $true) { Fail "Exact state/version binding is not required" }
if ($health.mission_lifecycle_automation_source_event_fingerprint_conflict_rejected -ne $true) { Fail "Source-event fingerprint conflict protection is not enabled" }
if ($health.mission_lifecycle_automation_external_event_delivery_enabled -ne $false) { Fail "Stage 3.2.9 unexpectedly enabled an external event-delivery worker" }
if ($health.mission_lifecycle_automation_governance_query_performed -ne $false) { Fail "Lifecycle automation unexpectedly claims Governance query" }
if ($health.mission_lifecycle_automation_planner_invocation_performed -ne $false) { Fail "Lifecycle automation unexpectedly claims planner invocation" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.2.9 contract active; migration=8, guard/journal reuse, no authority or execution expansion"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] Contract discovery + typed PIP event uses guarded command path"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "main-$token" 2)
$missionId = $mission.canonical_identity.mission_id
$contract = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/lifecycle-automation-contract"
if ($contract.lifecycle_automation.schema_version -ne "apts-mission-lifecycle-automation-v1") { Fail "Automation discovery schema mismatch" }
if ($contract.lifecycle_automation.event_to_command.PIP_BIND_REQUESTED -ne "BIND_PIP") { Fail "PIP event mapping mismatch" }
if ($contract.lifecycle_automation.blind_state_mutation_allowed -ne $false -or $contract.lifecycle_automation.direct_state_transition_api_used_by_automation -ne $false) { Fail "Automation discovery permits direct mutation bypass" }
if (@($contract.lifecycle_automation.eligible_event_types_for_current_state) -notcontains "PIP_BIND_REQUESTED") { Fail "PIP_BIND_REQUESTED not eligible in CREATED" }

$beforeEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$beforeTransitions = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$beforeCommands = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands"
$bindRequest = New-LifecycleEvent $missionId "PIP_BIND_REQUESTED" "main-bind-$token" @{} @("evidence:pip-ready:$token") $null "upstream-stage329-bind-$token"
$bind = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" $bindRequest
if ($bind.automation_status -ne "APPLIED" -or $bind.idempotent_replay -ne $false) { Fail "PIP event was not applied as first delivery" }
if ($bind.proposed_lifecycle_command -ne "BIND_PIP" -or $bind.lifecycle_command_result.lifecycle_command -ne "BIND_PIP") { Fail "PIP event was not translated to BIND_PIP" }
if ($bind.mission_state.state -ne "PIP_BOUND") { Fail "PIP event did not reach PIP_BOUND" }
if ($bind.transition.metadata.lifecycle_automation.source_event_id -ne $bindRequest.event_id) { Fail "Source-event provenance was not persisted on transition" }
if ($bind.transition.metadata.lifecycle_automation.governance_authorization_query_performed -ne $false) { Fail "Transition provenance falsely claims Governance authorization" }
if ($bind.outcome_event.payload.existing_command_journal_used -ne $true -or $bind.outcome_event.payload.direct_state_transition_bypass_used -ne $false) { Fail "Automation did not preserve command-journal/guarded mutation path" }
$afterEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$afterTransitions = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$afterCommands = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands"
if ([int]$afterEvents.event_count -ne ([int]$beforeEvents.event_count + 4)) { Fail "Applied lifecycle event did not append exactly RECEIVED + TRANSITIONED + COMMAND_COMPLETED + APPLIED" }
if ([int]$afterTransitions.transition_count -ne ([int]$beforeTransitions.transition_count + 1)) { Fail "Applied lifecycle event did not append exactly one transition" }
if ([int]$afterCommands.command_count -ne ([int]$beforeCommands.command_count + 1)) { Fail "Applied lifecycle event did not append exactly one generated command" }
$delta = @($afterEvents.events | Select-Object -Skip ([int]$beforeEvents.event_count))
$expectedTypes = @("MISSION_LIFECYCLE_EVENT_RECEIVED", "MISSION_STATE_TRANSITIONED", "MISSION_COMMAND_COMPLETED", "MISSION_LIFECYCLE_EVENT_APPLIED")
for ($i = 0; $i -lt $expectedTypes.Count; $i++) {
    if ($delta[$i].event_type -ne $expectedTypes[$i]) { Fail "Unexpected applied-event ledger order at index $i" }
}
Pass "Typed source event is translated to deterministic BIND_PIP and committed only through existing guarded lifecycle command path"

Write-Host "`n[4] Exact applied-event replay is side-effect free; conflicting event-ID reuse fails"
$eventsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$transitionsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$commandsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands"
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" $bindRequest
if ($replay.idempotent_replay -ne $true -or $replay.automation_status -ne "APPLIED") { Fail "Exact applied-event replay was not recognized" }
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$transitionsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$commandsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/commands"
if ([int]$eventsAfterReplay.event_count -ne [int]$eventsBeforeReplay.event_count) { Fail "Applied-event replay duplicated Mission events" }
if ([int]$transitionsAfterReplay.transition_count -ne [int]$transitionsBeforeReplay.transition_count) { Fail "Applied-event replay duplicated transition" }
if ([int]$commandsAfterReplay.command_count -ne [int]$commandsBeforeReplay.command_count) { Fail "Applied-event replay duplicated generated command" }
$conflictRequest = $bindRequest.Clone()
$conflictRequest.reason = "Different canonical meaning using the same source event identity"
$conflict = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" $conflictRequest
Assert-HttpError $conflict 409 "MISSION_COMMAND_CONFLICT" "Conflicting source-event identity reuse"
Pass "Exact delivery is replay-safe and same source identity cannot be rebound to different canonical content"

Write-Host "`n[5] Stale event is durably rejected before state mutation and rejection replay is stable"
$staleMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "stale-$token" 1)
$staleId = $staleMission.canonical_identity.mission_id
$stale = New-LifecycleEvent $staleId "PIP_BIND_REQUESTED" "stale-$token"
$stale.observed_state_version = [int]$stale.observed_state_version + 1
$staleEvents0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleId/events"
$staleTransitions0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleId/state/transitions"
$staleFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$staleId/lifecycle/events" $stale
Assert-HttpError $staleFailure 409 "MISSION_VERSION_CONFLICT" "Stale lifecycle event"
$staleState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleId/state"
$staleEvents1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleId/events"
$staleTransitions1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleId/state/transitions"
if ($staleState.mission_state.state -ne "CREATED") { Fail "Stale event mutated Mission state" }
if ([int]$staleTransitions1.transition_count -ne [int]$staleTransitions0.transition_count) { Fail "Stale event appended a state transition" }
if ([int]$staleEvents1.event_count -ne ([int]$staleEvents0.event_count + 2)) { Fail "Stale event did not append exactly RECEIVED + REJECTED" }
$staleTail = @($staleEvents1.events | Select-Object -Last 2)
if ($staleTail[0].event_type -ne "MISSION_LIFECYCLE_EVENT_RECEIVED" -or $staleTail[1].event_type -ne "MISSION_LIFECYCLE_EVENT_REJECTED") { Fail "Stale event outcome ledger is not RECEIVED -> REJECTED" }
$staleReplay = Get-PostFailure "$MissionBaseUrl/api/missions/$staleId/lifecycle/events" $stale
Assert-HttpError $staleReplay 409 "MISSION_VERSION_CONFLICT" "Rejected lifecycle event replay"
$staleEvents2 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$staleId/events"
if ([int]$staleEvents2.event_count -ne [int]$staleEvents1.event_count) { Fail "Rejected-event replay appended duplicate audit events" }
Pass "Late/out-of-order delivery is fail-closed, durable, and cannot be reinterpreted on exact replay"

Write-Host "`n[6] Planning and RUNNING activation continue through event automation"
$plan = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "PLANNING_START_REQUESTED" "main-plan-$token")
if ($plan.mission_state.state -ne "PLANNING" -or $plan.lifecycle_command_result.lifecycle_command -ne "START_PLANNING") { Fail "PLANNING_START_REQUESTED failed" }
$run = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "RUN_START_REQUESTED" "main-run-$token")
if ($run.mission_state.state -ne "RUNNING" -or $run.lifecycle_command_result.lifecycle_command -ne "START") { Fail "RUN_START_REQUESTED failed" }
$runActivation = $run.lifecycle_command_result.planning_run_activation
if ($null -eq $runActivation) { Fail "Stage-3.2.4 RUN activation evidence was not preserved" }
if ($runActivation.schema_version -ne "apts-mission-planning-run-activation-v1" -or $runActivation.phase -ne "RUNNING") { Fail "Stage-3.2.4 RUN activation evidence was missing or malformed" }
if ($runActivation.activation_command -ne "START" -or $runActivation.activation_ready -ne $true) { Fail "Stage-3.2.4 RUN activation evidence was not ready" }
if ($runActivation.planning_activation_proof.valid -ne $true) { Fail "Stage-3.2.4 planning activation lineage proof was not preserved" }
if ($runActivation.planner_invocation_performed -ne $false -or $runActivation.governance_authorization_query_performed -ne $false -or $runActivation.execution_authorized -ne $false) { Fail "RUNNING activation expanded planner/Governance/execution authority" }
if ($runActivation.target_action_dispatch_enabled -ne $false -or $runActivation.target_actuation -ne $false) { Fail "RUNNING activation unexpectedly enabled target execution" }
Pass "PIP_BOUND -> PLANNING -> RUNNING event automation preserves Stage-3.2.4 activation semantics"

Write-Host "`n[7] Evidence waiting + resolution automation preserves dependency lineage"
$depId = "dep-stage329-evidence-$token"
$waitMeta = @{ dependency = @{ dependency_id = $depId; kind = "EVIDENCE" } }
$wait = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "EVIDENCE_REQUIRED" "evidence-required-$token" $waitMeta @("evidence:dependency-request:$token"))
if ($wait.mission_state.state -ne "WAITING_EVIDENCE") { Fail "EVIDENCE_REQUIRED did not enter WAITING_EVIDENCE" }
if ($wait.lifecycle_command_result.waiting_dependency.dependency_id -ne $depId) { Fail "Waiting dependency id was not preserved" }
$readyMeta = @{ dependency_resolution = @{ dependency_id = $depId; status = "SATISFIED"; resolved_by = "stage329-acceptance" } }
$ready = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "EVIDENCE_READY" "evidence-ready-$token" $readyMeta @("evidence:dependency-resolved:$token"))
if ($ready.mission_state.state -ne "RUNNING") { Fail "EVIDENCE_READY did not return to RUNNING" }
if ($ready.lifecycle_command_result.waiting_dependency_resolution.dependency_id -ne $depId -or $ready.lifecycle_command_result.waiting_dependency_resolution.resolution_status -ne "SATISFIED") { Fail "Dependency resolution lineage mismatch" }
Pass "Event automation reuses Stage-3.2.5 waiting/resolution control instead of bypassing it"

Write-Host "`n[8] Approval events remain workflow dependency, never Governance authorization"
$approvalId = "dep-stage329-approval-$token"
$approvalWaitMeta = @{ dependency = @{ dependency_id = $approvalId; kind = "APPROVAL" } }
$approvalWait = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "APPROVAL_REQUIRED" "approval-required-$token" $approvalWaitMeta)
if ($approvalWait.mission_state.state -ne "WAITING_APPROVAL") { Fail "APPROVAL_REQUIRED did not enter WAITING_APPROVAL" }
$approvalReadyMeta = @{ dependency_resolution = @{ dependency_id = $approvalId; status = "SATISFIED"; resolved_by = "human-review" } }
$approvalReady = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "APPROVAL_GRANTED" "approval-granted-$token" $approvalReadyMeta @("evidence:approval:$token"))
if ($approvalReady.mission_state.state -ne "RUNNING") { Fail "APPROVAL_GRANTED did not return to RUNNING" }
$resolution = $approvalReady.lifecycle_command_result.waiting_dependency_resolution
if ($resolution.approval_dependency_is_governance_authorization -ne $false) { Fail "Workflow approval was confused with Governance authorization" }
if ($resolution.governance_authorization_query_performed -ne $false -or $resolution.authorization_granted -ne $false) { Fail "Approval automation fabricated a Governance decision" }
Pass "Workflow approval dependency is resolved without changing EXTERNAL_APTS_GSS authorization authority"

Write-Host "`n[9] Pause/resume and replanning events preserve Stage-3.2.6 guards and lineage"
$paused = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "PAUSE_REQUESTED" "pause-$token")
if ($paused.mission_state.state -ne "PAUSED") { Fail "PAUSE_REQUESTED did not enter PAUSED" }
$pauseId = $paused.lifecycle_command_result.pause_control.pause_id
$resumed = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "RESUME_REQUESTED" "resume-$token" @{} @() "RUNNING")
if ($resumed.mission_state.state -ne "RUNNING") { Fail "RESUME_REQUESTED did not return to RUNNING" }
if ($resumed.lifecycle_command_result.resume_control.pause_id -ne $pauseId) { Fail "RESUME lost exact pause lineage" }
$replan = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "REPLAN_REQUESTED" "replan-$token" @{} @("evidence:replan-trigger:$token"))
if ($replan.mission_state.state -ne "REPLANNING") { Fail "REPLAN_REQUESTED did not enter REPLANNING" }
$replanId = $replan.lifecycle_command_result.replan_control.replan_id
$replanReady = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "REPLAN_READY" "replan-ready-$token" @{} @("evidence:replan-ready:$token"))
if ($replanReady.mission_state.state -ne "RUNNING") { Fail "REPLAN_READY did not return to RUNNING" }
if ($replanReady.lifecycle_command_result.replan_resolution.replan_id -ne $replanId -or $replanReady.lifecycle_command_result.replan_resolution.readiness_status -ne "READY") { Fail "Replanning readiness lineage mismatch" }
Pass "Pause/resume/replanning events remain subject to existing Stage-3.2.6 control semantics"

Write-Host "`n[10] Cleanup + verified completion events preserve Stage-3.2.8 completion gate"
$cleanup = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "CLEANUP_REQUESTED" "cleanup-$token" @{} @("evidence:cleanup-start:$token"))
if ($cleanup.mission_state.state -ne "CLEANING_UP") { Fail "CLEANUP_REQUESTED did not enter CLEANING_UP" }
if ($cleanup.lifecycle_command_result.cleanup_control.cleanup_started -ne $true -or $cleanup.lifecycle_command_result.cleanup_control.verified_completion_claimed -ne $false) { Fail "Cleanup event did not preserve Stage-3.2.8 cleanup evidence semantics" }
$completion = New-CompletionBundle "stage329-$token" 2
$completed = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/events" (New-LifecycleEvent $missionId "COMPLETION_VERIFIED" "complete-$token" $completion.metadata $completion.refs)
if ($completed.mission_state.state -ne "COMPLETED") { Fail "COMPLETION_VERIFIED did not reach COMPLETED" }
if ($completed.lifecycle_command_result.completion_verification.verified_completion_claimed -ne $true -or $completed.lifecycle_command_result.completion_verification.cleanup_completion_gate_applied -ne $true) { Fail "Stage-3.2.8 verified completion evidence was not preserved" }
$terminal = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/terminal-semantics-contract"
if ($terminal.terminal_semantics.current_terminal_lineage.status -ne "VALID_VERIFIED_COMPLETION") { Fail "Completed event did not reconstruct as VALID_VERIFIED_COMPLETION" }
Pass "Event automation cannot bypass the existing cleanup/verified-completion gate"

Write-Host "`n[11] Typed terminal event preserves Stage-3.2.7 abort semantics"
$abortMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "abort-$token" 1)
$abortId = $abortMission.canonical_identity.mission_id
$aborted = Post-Json "$MissionBaseUrl/api/missions/$abortId/lifecycle/events" (New-LifecycleEvent $abortId "ABORT_REQUESTED" "abort-$token" @{} @("evidence:abort:$token"))
if ($aborted.mission_state.state -ne "ABORTED") { Fail "ABORT_REQUESTED did not reach ABORTED" }
if ($aborted.lifecycle_command_result.terminal_control.terminal_command -ne "ABORT" -or $aborted.lifecycle_command_result.terminal_control.terminal_state -ne "ABORTED") { Fail "Typed abort terminal evidence mismatch" }
if ($aborted.lifecycle_command_result.terminal_control.verified_completion_claimed -ne $false) { Fail "ABORT falsely claimed verified completion" }
Pass "ABORT_REQUESTED delegates to existing typed terminal semantics rather than inventing new finality"

Write-Host "`n[12] Upstream lineage + repository integrity + final boundary"
$lineage = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/lineage"
$upstream = @($lineage.upstream_edges | Where-Object { $_.upstream_event_id -eq $bindRequest.event_id })
if ($upstream.Count -ne 2) { Fail "Expected exactly two upstream edges for the first lifecycle source event" }
if ($lineage.integrity_status -ne "PASS") { Fail "Mission event lineage integrity failed" }
$repo = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repo.integrity_status -ne "PASS") { Fail "Mission repository integrity reconstruction failed" }
if ([int]$repo.repository.migration_level -ne 8) { Fail "Repository integrity view reports migration other than 8" }
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.9-event-driven-lifecycle-automation-reliability") { Fail "Control version changed during acceptance" }
if ($finalHealth.mission_lifecycle_stage3_2_9_event_automation_enabled -ne $true) { Fail "Stage 3.2.9 automation disabled during acceptance" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority changed during acceptance" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary changed during acceptance" }
Pass "Event lineage and repository integrity remain PASS; migration, Governance, planner, and target-execution boundaries are preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.9 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
