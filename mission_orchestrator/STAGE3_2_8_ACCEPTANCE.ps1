param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.8 ACCEPTANCE: FAIL" -ForegroundColor Red
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

function Assert-GuardRejected($Failure, [string]$ExpectedGuard, [string]$Context) {
    if ([int]$Failure.status -ne 409) { Fail "$Context did not fail with HTTP 409" }
    if ($null -eq $Failure.body -or $Failure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") {
        Fail "$Context did not fail with MISSION_LIFECYCLE_GUARD_REJECTED"
    }
    if ($Failure.body.message -notmatch [regex]::Escape($ExpectedGuard)) {
        Fail "$Context did not identify guard $ExpectedGuard"
    }
}

function New-MissionPayload([string]$Token, [int]$CriteriaCount = 2) {
    $criteria = @()
    for ($i = 0; $i -lt $CriteriaCount; $i++) {
        $criteria += @{ metric = "stage328_criterion_$i"; expected = $true }
    }
    return @{
        idempotency_key = "stage328-mission-$Token"
        source_system = "STAGE328_ACCEPTANCE"
        created_by = "stage3.2.8-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage328-lab" }
        success_criteria = $criteria
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-$Token"
        pip_version = "13"
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.8" }
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
    if ($null -eq $Metadata) { $Metadata = @{ acceptance = "stage3.2.8"; token = $Token } }
    if ($null -eq $EvidenceRefs) { $EvidenceRefs = @("evidence:stage3.2.8:acceptance:$Token") }
    $body = @{
        command_id = "lc-$Command-$Token"
        idempotency_key = "idem-lc-$Command-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.2.8-acceptance"
        reason_code = "STAGE328_$Command"
        reason = "Stage 3.2.8 lifecycle command $Command"
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

function New-WaitCommand([string]$MissionId, [string]$Token, [string]$DependencyId) {
    $metadata = @{
        acceptance = "stage3.2.8"
        dependency = @{
            dependency_id = $DependencyId
            kind = "EVIDENCE"
            description = "Stage 3.2.8 unresolved completion dependency"
        }
    }
    return New-LifecycleCommand $MissionId "WAIT_FOR_EVIDENCE" $Token $null $metadata @("dependency:request:$Token")
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
        acceptance = "stage3.2.8"
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

function New-DirectTransition([string]$MissionId, [string]$ToState, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    return @{
        expected_state_version = [int]$state.mission_state.state_version
        to_state = $ToState
        actor = "stage3.2.8-legacy-acceptance"
        reason_code = "LEGACY_$Token"
        reason = "Exercise preserved Stage-3.1 direct transition API"
        evidence_refs = @()
        metadata = @{ legacy_acceptance = $true; stage = "3.2.8" }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.8 - Cleanup & Verified Completion Gate Acceptance"
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
    if ($joined -notmatch "234 passed") { Fail "Expected Stage-3.2.8 regression baseline of 234 passed" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.8 regression baseline: 234 passed"

Write-Host "`n[2] Health / cleanup-completion contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne "stage3.2.8-cleanup-verified-completion-gate") { Fail "Stage 3.2.8 control version is not active" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Repository migration level changed from 8" }
if ($health.mission_cleanup_completion_schema_version -ne "apts-mission-cleanup-completion-gate-v1") { Fail "Cleanup/completion schema mismatch" }
if ($health.mission_cleanup_completion_mode -ne "DURABLE_CLEANUP_LINEAGE_AND_EVIDENCE_GATED_VERIFIED_COMPLETION_FAIL_CLOSED") { Fail "Cleanup/completion mode mismatch" }
if ($health.mission_cleanup_command -ne "BEGIN_CLEANUP" -or $health.mission_cleanup_state -ne "CLEANING_UP") { Fail "Cleanup command/state contract mismatch" }
if ($health.mission_completion_command -ne "COMPLETE" -or $health.mission_completion_state -ne "COMPLETED") { Fail "Completion command/state contract mismatch" }
if ($health.mission_completion_verification_status -ne "VERIFIED") { Fail "Completion verification status mismatch" }
if ($health.mission_completion_exact_success_criteria_coverage_required -ne $true) { Fail "Exact success-criteria coverage is not required" }
if ($health.mission_completion_cleanup_checks_required -ne $true) { Fail "Cleanup checks are not required" }
if ($health.mission_completion_evidence_refs_required -ne $true -or $health.mission_completion_nested_evidence_binding_required -ne $true) { Fail "Completion evidence binding contract is not active" }
if ([int]$health.mission_completion_outstanding_critical_dependencies_required -ne 0) { Fail "Completion does not require zero critical dependencies" }
if ($health.mission_completion_requires_stage3_2_4_run_lineage -ne $true -or $health.mission_completion_requires_stage3_2_8_cleanup_lineage -ne $true) { Fail "Required run/cleanup lineage gates are not active" }
if ($health.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $true) { Fail "Stage 3.2.8 completion gate is not enabled" }
if ($health.mission_cleanup_action_performed_by_orchestrator -ne $false) { Fail "Orchestrator unexpectedly claims target cleanup execution" }
if ($health.mission_completion_governance_query_performed -ne $false -or $health.mission_completion_authorization_granted -ne $false -or $health.mission_completion_execution_authorized -ne $false) { Fail "Completion gate expanded Governance/execution authority" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.2.8 contract active; migration=8 and Governance/target-execution boundaries preserved"

$token = [guid]::NewGuid().ToString("N")

Write-Host "`n[3] BEGIN_CLEANUP from RUNNING records durable Stage-3.2.8 lineage"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "happy-$token" 2)
$missionId = $mission.canonical_identity.mission_id
Activate-Running $missionId "happy-$token"
$cleanupMeta = @{ acceptance = "stage3.2.8"; cleanup = @{ scope = "LOCAL_FINALIZATION" } }
$cleanupRequest = New-LifecycleCommand $missionId "BEGIN_CLEANUP" "cleanup-$token" $null $cleanupMeta @("evidence:cleanup-start:$token")
$cleanup = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $cleanupRequest
if ($cleanup.mission_state.state -ne "CLEANING_UP") { Fail "BEGIN_CLEANUP did not reach CLEANING_UP" }
if ($cleanup.cleanup_control.schema_version -ne "apts-mission-cleanup-completion-gate-v1") { Fail "Cleanup evidence schema mismatch" }
if ($cleanup.cleanup_control.from_state -ne "RUNNING") { Fail "Cleanup evidence lost exact RUNNING source state" }
if ($cleanup.cleanup_control.run_activation_proof.valid -ne $true) { Fail "Cleanup evidence did not bind valid Stage-3.2.4 RUNNING lineage" }
if ($cleanup.cleanup_control.completion_prerequisites_ready -ne $true) { Fail "Clean RUNNING source did not become completion-ready" }
if ($cleanup.cleanup_control.cleanup_verified -ne $false -or $cleanup.cleanup_control.verified_completion_claimed -ne $false) { Fail "BEGIN_CLEANUP prematurely claimed verified cleanup/completion" }
if ($cleanup.cleanup_control.cleanup_context.scope -ne "LOCAL_FINALIZATION") { Fail "Cleanup context was not persisted" }
$cleanupView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/cleanup-completion-contract"
if ($cleanupView.cleanup_completion.current_state -ne "CLEANING_UP") { Fail "Cleanup read model is not in CLEANING_UP" }
if ($cleanupView.cleanup_completion.cleanup_lineage.valid -ne $true) { Fail "Cleanup lineage did not reconstruct as valid" }
if ($cleanupView.cleanup_completion.completion_prerequisites_ready -ne $true) { Fail "Cleanup read model did not report completion prerequisites ready" }
Pass "CLEANING_UP preserves run lineage and creates durable cleanup control without fabricating cleanup execution"

Write-Host "`n[4] COMPLETE without completion declaration fails closed with zero state/event side effects"
$history0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$events0 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$missingRequest = New-LifecycleCommand $missionId "COMPLETE" "missing-$token" $null @{ acceptance = "stage3.2.8" } @("evidence:missing:$token")
$missingFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $missingRequest
Assert-GuardRejected $missingFailure "COMPLETION_DECLARATION_VERIFIED" "Missing completion declaration"
$stateAfterMissing = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
$history1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$events1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ($stateAfterMissing.mission_state.state -ne "CLEANING_UP") { Fail "Rejected COMPLETE changed mission state" }
if ([int]$history1.transition_count -ne [int]$history0.transition_count -or [int]$events1.event_count -ne [int]$events0.event_count) { Fail "Rejected COMPLETE persisted transition/event side effects" }
Pass "Missing completion evidence is rejected before transition/event persistence"

Write-Host "`n[5] Exact success-criteria coverage is mandatory"
$partial = New-CompletionBundle "partial-$token" 2
$partial.metadata.completion.criteria_results = @($partial.metadata.completion.criteria_results[0])
$partialRequest = New-LifecycleCommand $missionId "COMPLETE" "partial-$token" $null $partial.metadata $partial.refs
$partialFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $partialRequest
Assert-GuardRejected $partialFailure "COMPLETION_SUCCESS_CRITERIA_COVERAGE" "Partial success-criteria coverage"
$stateAfterPartial = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($stateAfterPartial.mission_state.state -ne "CLEANING_UP") { Fail "Partial completion request changed state" }
Pass "COMPLETE requires every canonical success criterion exactly once with SATISFIED evidence"

Write-Host "`n[6] Cleanup verification and critical-dependency gates fail closed"
$badCleanup = New-CompletionBundle "badcleanup-$token" 2
$badCleanup.metadata.completion.cleanup_checks[0].status = "FAIL"
$badCleanupRequest = New-LifecycleCommand $missionId "COMPLETE" "badcleanup-$token" $null $badCleanup.metadata $badCleanup.refs
$badCleanupFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $badCleanupRequest
Assert-GuardRejected $badCleanupFailure "COMPLETION_CLEANUP_VERIFIED" "Failed cleanup check"

$badDeps = New-CompletionBundle "baddeps-$token" 2
$badDeps.metadata.completion.outstanding_critical_dependencies = 1
$badDepsRequest = New-LifecycleCommand $missionId "COMPLETE" "baddeps-$token" $null $badDeps.metadata $badDeps.refs
$badDepsFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $badDepsRequest
Assert-GuardRejected $badDepsFailure "COMPLETION_CRITICAL_DEPENDENCIES_CLEAR" "Outstanding critical dependency"
Pass "Cleanup checks must PASS and outstanding critical dependencies must be zero"

Write-Host "`n[7] Nested evidence must be bound to command-level evidence_refs"
$unbound = New-CompletionBundle "unbound-$token" 2
$unbound.refs = @($unbound.refs | Where-Object { $_ -notmatch "criterion:1:" })
$unboundRequest = New-LifecycleCommand $missionId "COMPLETE" "unbound-$token" $null $unbound.metadata $unbound.refs
$unboundFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $unboundRequest
Assert-GuardRejected $unboundFailure "COMPLETION_EVIDENCE_REFS_BOUND" "Unbound nested evidence"
Pass "Objective/criterion/cleanup evidence cannot escape the command evidence envelope"

Write-Host "`n[8] Valid COMPLETE persists verified completion and terminal projection"
$valid = New-CompletionBundle "verified-$token" 2
$completeRequest = New-LifecycleCommand $missionId "COMPLETE" "verified-$token" $null $valid.metadata $valid.refs
$beforeCompleteTransitions = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$beforeCompleteEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$completed = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $completeRequest
if ($completed.mission_state.state -ne "COMPLETED") { Fail "Verified COMPLETE did not reach COMPLETED" }
if ($completed.completion_verification.schema_version -ne "apts-mission-cleanup-completion-gate-v1") { Fail "Completion verification schema mismatch" }
if ($completed.completion_verification.verification_status -ne "VERIFIED" -or $completed.completion_verification.objective_status -ne "SATISFIED") { Fail "Completion verification status/objective mismatch" }
if ([int]$completed.completion_verification.success_criteria_count -ne 2 -or [int]$completed.completion_verification.criteria_results.Count -ne 2) { Fail "Completion verification did not preserve exact criteria coverage" }
if ($completed.completion_verification.cleanup_status -ne "VERIFIED") { Fail "Completion verification cleanup status mismatch" }
if ([int]$completed.completion_verification.outstanding_critical_dependencies -ne 0) { Fail "Completion verification persisted critical dependencies" }
if ($completed.completion_verification.verified_completion_claimed -ne $true -or $completed.completion_verification.cleanup_completion_gate_applied -ne $true) { Fail "Verified completion flags are not set" }
if ($completed.completion_verification.cleanup_id -ne $cleanup.cleanup_control.cleanup_id) { Fail "Completion did not bind the exact cleanup lineage" }
$terminal = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/terminal-semantics-contract"
if ($terminal.terminal_semantics.current_terminal_lineage.valid -ne $true) { Fail "Verified completion terminal lineage is invalid" }
if ($terminal.terminal_semantics.current_terminal_lineage.status -ne "VALID_VERIFIED_COMPLETION") { Fail "Terminal projection did not report VALID_VERIFIED_COMPLETION" }
if ($terminal.terminal_semantics.verified_completion_claimed -ne $true -or $terminal.terminal_semantics.cleanup_completion_gate_applied -ne $true) { Fail "Terminal projection lost verified completion flags" }
$completedView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/cleanup-completion-contract"
if ($completedView.cleanup_completion.verified_completion_claimed -ne $true) { Fail "Cleanup-completion read model lost verified completion" }
Pass "COMPLETED is now evidence-gated and reconstructs as VALID_VERIFIED_COMPLETION"

Write-Host "`n[9] Exact COMPLETE replay is idempotent and exactly-once"
$afterCompleteTransitions = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$afterCompleteEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ([int]$afterCompleteTransitions.transition_count -ne ([int]$beforeCompleteTransitions.transition_count + 1)) { Fail "COMPLETE did not append exactly one transition" }
# A guarded lifecycle command intentionally emits two canonical Mission events:
#   1) MISSION_STATE_TRANSITIONED from transition_mission_state(), and
#   2) MISSION_COMMAND_COMPLETED from the Stage-3.1.6 command journal.
# Stage 3.2.8 must preserve both Stage-3.1.9 event lineage and command-journal lineage.
if ([int]$afterCompleteEvents.event_count -ne ([int]$beforeCompleteEvents.event_count + 2)) { Fail "COMPLETE did not append exactly the expected transition + command-completed Mission events" }
$newCompleteEvents = @($afterCompleteEvents.events | Select-Object -Skip ([int]$beforeCompleteEvents.event_count))
if ($newCompleteEvents.Count -ne 2) { Fail "COMPLETE event delta is not exactly two canonical events" }
$stateEvents = @($newCompleteEvents | Where-Object { $_.event_type -eq "MISSION_STATE_TRANSITIONED" })
$commandEvents = @($newCompleteEvents | Where-Object { $_.event_type -eq "MISSION_COMMAND_COMPLETED" })
if ($stateEvents.Count -ne 1 -or $commandEvents.Count -ne 1) { Fail "COMPLETE event delta does not contain exactly one state-transition event and one command-completed event" }
$stateEvent = $stateEvents[0]
$commandEvent = $commandEvents[0]
if ($stateEvent.causation_id -ne $completed.transition.transition_id -or $stateEvent.payload.to_state -ne "COMPLETED") { Fail "COMPLETE state-transition event is not bound to the committed COMPLETED transition" }
if ($commandEvent.causation_id -ne $completeRequest.command_id -or $commandEvent.payload.command_id -ne $completeRequest.command_id) { Fail "COMPLETE command-completed event is not bound to the exact lifecycle command" }
if ($commandEvent.parent_event_id -ne $stateEvent.event_id) { Fail "COMPLETE event lineage does not chain command completion directly after state transition" }
$replay = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $completeRequest
if ($replay.idempotent_replay -ne $true) { Fail "Exact COMPLETE replay was not recognized as idempotent" }
$replayTransitions = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$replayEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ([int]$replayTransitions.transition_count -ne [int]$afterCompleteTransitions.transition_count -or [int]$replayEvents.event_count -ne [int]$afterCompleteEvents.event_count) { Fail "COMPLETE replay duplicated transition/event" }
Pass "Verified COMPLETE uses the existing command journal for replay-safe exactly-once persistence"

Write-Host "`n[10] Paused unresolved waiting dependency can enter cleanup but cannot complete"
$blockedMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "blocked-$token" 2)
$blockedId = $blockedMission.canonical_identity.mission_id
Activate-Running $blockedId "blocked-$token"
$dependencyId = "dep-stage328-$token"
$wait = Post-Json "$MissionBaseUrl/api/missions/$blockedId/lifecycle/commands" (New-WaitCommand $blockedId "wait-$token" $dependencyId)
if ($wait.mission_state.state -ne "WAITING_EVIDENCE") { Fail "Blocked scenario did not enter WAITING_EVIDENCE" }
$pause = Post-Json "$MissionBaseUrl/api/missions/$blockedId/lifecycle/commands" (New-LifecycleCommand $blockedId "PAUSE" "pause-$token")
if ($pause.mission_state.state -ne "PAUSED") { Fail "Blocked scenario did not enter PAUSED" }
$blockedCleanup = Post-Json "$MissionBaseUrl/api/missions/$blockedId/lifecycle/commands" (New-LifecycleCommand $blockedId "BEGIN_CLEANUP" "blocked-cleanup-$token")
if ($blockedCleanup.mission_state.state -ne "CLEANING_UP") { Fail "Blocked scenario did not enter CLEANING_UP" }
$blockers = @($blockedCleanup.cleanup_control.completion_blockers)
if ($blockers -notcontains "UNRESOLVED_WAITING_DEPENDENCY") { Fail "Unresolved waiting dependency was not preserved as a completion blocker" }
$blockedBundle = New-CompletionBundle "blocked-$token" 2
$blockedRequest = New-LifecycleCommand $blockedId "COMPLETE" "blocked-complete-$token" $null $blockedBundle.metadata $blockedBundle.refs
$blockedFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$blockedId/lifecycle/commands" $blockedRequest
Assert-GuardRejected $blockedFailure "CLEANUP_COMPLETION_BLOCKERS_CLEAR" "Completion with unresolved waiting dependency"
$blockedState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$blockedId/state"
if ($blockedState.mission_state.state -ne "CLEANING_UP") { Fail "Blocked completion changed state" }
Pass "Unresolved dependency context is durable and prevents false successful completion"

Write-Host "`n[11] Legacy direct COMPLETED remains distinguishable from verified completion"
$legacyMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "legacy-$token" 1)
$legacyId = $legacyMission.canonical_identity.mission_id
Activate-Running $legacyId "legacy-$token"
$legacyCleanup = Post-Json "$MissionBaseUrl/api/missions/$legacyId/state/transitions" (New-DirectTransition $legacyId "CLEANING_UP" "cleanup-$token")
if ($legacyCleanup.mission_state.state -ne "CLEANING_UP") { Fail "Legacy direct transition did not reach CLEANING_UP" }
$legacyComplete = Post-Json "$MissionBaseUrl/api/missions/$legacyId/state/transitions" (New-DirectTransition $legacyId "COMPLETED" "complete-$token")
if ($legacyComplete.mission_state.state -ne "COMPLETED") { Fail "Legacy direct transition did not reach COMPLETED" }
$legacyTerminal = Invoke-RestMethod "$MissionBaseUrl/api/missions/$legacyId/terminal-semantics-contract"
if ($legacyTerminal.terminal_semantics.current_terminal_lineage.status -ne "LEGACY_DIRECT_COMPLETED_NO_STAGE_3_2_8_EVIDENCE") { Fail "Legacy COMPLETED was not explicitly marked unverified" }
if ($legacyTerminal.terminal_semantics.verified_completion_claimed -ne $false -or $legacyTerminal.terminal_semantics.cleanup_completion_gate_applied -ne $false) { Fail "Legacy COMPLETED incorrectly claimed verified completion" }
Pass "Compatibility API is preserved without fabricating Stage-3.2.8 completion provenance"

Write-Host "`n[12] Failure during cleanup remains FAILED, not successful completion"
$failMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "fail-$token" 1)
$failId = $failMission.canonical_identity.mission_id
Activate-Running $failId "fail-$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$failId/lifecycle/commands" (New-LifecycleCommand $failId "BEGIN_CLEANUP" "fail-cleanup-$token")
$failed = Post-Json "$MissionBaseUrl/api/missions/$failId/lifecycle/commands" (New-LifecycleCommand $failId "FAIL" "cleanup-fail-$token")
if ($failed.mission_state.state -ne "FAILED") { Fail "FAIL during CLEANING_UP did not reach FAILED" }
if ($failed.terminal_control.from_state -ne "CLEANING_UP") { Fail "FAIL during cleanup lost exact source state" }
if ($failed.terminal_control.verified_completion_claimed -ne $false -or $failed.terminal_control.cleanup_completion_gate_applied -ne $false) { Fail "FAIL during cleanup incorrectly claimed successful completion" }
Pass "Stage-3.2.7 failure semantics remain distinct from Stage-3.2.8 verified completion"

Write-Host "`n[13] Final boundary / current-control check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.8-cleanup-verified-completion-gate") { Fail "Control version changed during acceptance" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Migration level changed during acceptance" }
if ($finalHealth.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $true) { Fail "Stage 3.2.8 completion gate disabled during acceptance" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority changed" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary changed" }
Pass "Stage 3.2.8 closes verified completion semantics without migration, Governance, or target-execution expansion"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.8 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
