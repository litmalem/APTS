param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.5 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        idempotency_key = "stage325-mission-$Token"
        source_system = "STAGE325_ACCEPTANCE"
        created_by = "stage3.2.5-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage325-lab" }
        success_criteria = @(@{ metric = "stage325_waiting_dependency_control"; expected = $true })
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-$Token"
        pip_version = "10"
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.5" }
    }
}

function New-LifecycleCommand(
    [string]$MissionId,
    [string]$Command,
    [string]$Token,
    $Metadata = $null,
    $EvidenceRefs = $null
) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    if ($null -eq $Metadata) { $Metadata = @{ acceptance = "stage3.2.5"; token = $Token } }
    if ($null -eq $EvidenceRefs) { $EvidenceRefs = @("evidence:stage3.2.5:acceptance") }
    return @{
        command_id = "lc-$Command-$Token"
        idempotency_key = "idem-lc-$Command-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.2.5-acceptance"
        reason_code = "STAGE325_$Command"
        reason = "Stage 3.2.5 lifecycle command $Command"
        evidence_refs = $EvidenceRefs
        metadata = $Metadata
    }
}

function Activate-Running([string]$MissionId, [string]$Token) {
    $bind = New-LifecycleCommand $MissionId "BIND_PIP" "bind-$Token"
    $null = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $bind
    $plan = New-LifecycleCommand $MissionId "START_PLANNING" "plan-$Token"
    $null = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $plan
    $start = New-LifecycleCommand $MissionId "START" "run-$Token"
    $run = Post-Json "$MissionBaseUrl/api/missions/$MissionId/lifecycle/commands" $start
    if ($run.mission_state.state -ne "RUNNING") { Fail "Activation helper did not reach RUNNING" }
}

function New-DirectTransition([string]$MissionId, [string]$ToState, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    return @{
        expected_state_version = [int]$state.mission_state.state_version
        to_state = $ToState
        actor = "stage3.2.5-legacy-acceptance"
        reason_code = "LEGACY_$Token"
        reason = "Exercise preserved Stage-3.1 direct transition API"
        evidence_refs = @()
        metadata = @{ legacy_acceptance = $true; stage = "3.2.5" }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.5 - Waiting States: Evidence & Approval Dependency Control Acceptance"
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
    if (($pytestOutput -join "`n") -notmatch "182 passed") { Fail "Expected Stage-3.2.5 baseline '182 passed'" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.5 regression baseline: 182 passed"

Write-Host "`n[2] Health / waiting-dependency contract / authority boundary"
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)" }
if ($health.status -ne "ok" -or $health.component_id -ne "APTS-MO01") { Fail "Unexpected Mission health identity" }
if ($health.control_version -ne "stage3.2.5-waiting-dependency-control") { Fail "Unexpected control_version: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Stage 3.2.5 must not add a database migration" }
if ($health.mission_waiting_dependency_schema_version -ne "apts-mission-waiting-dependency-control-v1") { Fail "Waiting dependency schema mismatch" }
if ($health.mission_waiting_dependency_mode -ne "EXPLICIT_WAIT_DECLARATION_AND_LOCAL_RESOLUTION_EVIDENCE_FAIL_CLOSED") { Fail "Waiting dependency mode mismatch" }
if ($health.mission_waiting_dependency_return_command -ne "START") { Fail "Unexpected waiting return command" }
if ($health.mission_waiting_dependency_resolution_status_required -ne "SATISFIED") { Fail "Unexpected dependency resolution status contract" }
if ($health.mission_waiting_dependency_evidence_refs_required_for_return -ne $true) { Fail "Resolution evidence requirement is not active" }
if ($health.mission_waiting_approval_is_governance_authorization -ne $false) { Fail "Approval dependency was conflated with Governance authorization" }
if ($health.mission_waiting_dependency_external_queries -ne $false) { Fail "Stage 3.2.5 must remain local-only" }
if ($health.mission_lifecycle_stage3_2_5_dependency_resolution_enabled -ne $true) { Fail "Stage-3.2.5 dependency control flag is not active" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.2.5 contract active; migration, Governance, and target-execution boundaries preserved"

$token = [Guid]::NewGuid().ToString("N").Substring(0, 10)

Write-Host "`n[3] WAIT_FOR_EVIDENCE requires an explicit typed dependency declaration"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "evidence-$token")
$missionId = $mission.canonical_identity.mission_id
Activate-Running $missionId "evidence-$token"
$missingWait = New-LifecycleCommand $missionId "WAIT_FOR_EVIDENCE" "missing-wait-$token"
$missingWaitFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $missingWait
if ($missingWaitFailure.status -ne 409 -or $missingWaitFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "WAIT_FOR_EVIDENCE without dependency declaration did not fail closed" }
if ($missingWaitFailure.body.message -notmatch "WAITING_DEPENDENCY_DECLARATION_FOR_WAIT") { Fail "Expected wait dependency declaration guard rejection" }
$stateAfterMissing = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($stateAfterMissing.mission_state.state -ne "RUNNING") { Fail "Rejected wait declaration mutated mission state" }
Pass "Missing wait dependency declaration is rejected with zero lifecycle mutation"

Write-Host "`n[4] Valid evidence dependency enters WAITING_EVIDENCE with durable local evidence"
$depId = "dep-evidence-$token"
$waitMetadata = @{
    acceptance = "stage3.2.5"
    dependency = @{ dependency_id = $depId; kind = "EVIDENCE"; description = "Await evidence artifact" }
}
$waitCommand = New-LifecycleCommand $missionId "WAIT_FOR_EVIDENCE" "wait-$token" $waitMetadata @("evidence:request:$token")
$wait = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $waitCommand
if ($wait.mission_state.state -ne "WAITING_EVIDENCE") { Fail "WAIT_FOR_EVIDENCE did not reach WAITING_EVIDENCE" }
if ($wait.waiting_dependency.schema_version -ne "apts-mission-waiting-dependency-control-v1") { Fail "Waiting dependency evidence schema mismatch" }
if ($wait.waiting_dependency.dependency_id -ne $depId -or $wait.waiting_dependency.kind -ne "EVIDENCE") { Fail "Waiting evidence dependency identity/kind mismatch" }
if ($wait.waiting_dependency.dependency_declared -ne $true) { Fail "Waiting dependency was not marked declared" }
if ($wait.waiting_dependency.authorization_granted -ne $false -or $wait.waiting_dependency.governance_authorization_query_performed -ne $false) { Fail "Evidence wait unexpectedly synthesized authorization" }
$waitView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/waiting-dependency-contract"
if ($waitView.waiting_dependency.active_dependency.valid -ne $true -or $waitView.waiting_dependency.active_dependency.dependency_id -ne $depId) { Fail "Waiting dependency projection did not reconstruct durable evidence" }
Pass "WAITING_EVIDENCE is backed by typed durable dependency lineage without external queries"

Write-Host "`n[5] START from WAITING_EVIDENCE fails closed until matching resolution evidence is supplied"
$noResolution = New-LifecycleCommand $missionId "START" "no-resolution-$token"
$noResolutionFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $noResolution
if ($noResolutionFailure.status -ne 409 -or $noResolutionFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "START without dependency resolution did not fail closed" }
if ($noResolutionFailure.body.message -notmatch "WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN") { Fail "Expected dependency resolution match guard rejection" }
$wrongMetadata = @{
    acceptance = "stage3.2.5"
    dependency_resolution = @{ dependency_id = "dep-wrong-$token"; status = "SATISFIED"; resolved_by = "stage3.2.5-acceptance" }
}
$wrongResolution = New-LifecycleCommand $missionId "START" "wrong-resolution-$token" $wrongMetadata @("evidence:artifact:$token")
$wrongFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $wrongResolution
if ($wrongFailure.status -ne 409 -or $wrongFailure.body.message -notmatch "WAITING_DEPENDENCY_RESOLUTION_MATCH_FOR_RETURN") { Fail "Mismatched dependency resolution did not fail closed" }
$stateStillWaiting = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($stateStillWaiting.mission_state.state -ne "WAITING_EVIDENCE") { Fail "Rejected dependency resolution mutated state" }
Pass "WAITING_EVIDENCE cannot return to RUNNING without matching SATISFIED resolution"

Write-Host "`n[6] Matching evidence resolution returns to RUNNING and is idempotent"
$resolutionMetadata = @{
    acceptance = "stage3.2.5"
    dependency_resolution = @{ dependency_id = $depId; status = "SATISFIED"; resolved_by = "stage3.2.5-acceptance" }
}
$returnCommand = New-LifecycleCommand $missionId "START" "return-$token" $resolutionMetadata @("evidence:artifact:$token")
$historyBeforeReturn = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$eventsBeforeReturn = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$return = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $returnCommand
if ($return.mission_state.state -ne "RUNNING") { Fail "Resolved dependency did not return mission to RUNNING" }
if ($return.waiting_dependency_resolution.resolution_ready -ne $true) { Fail "Resolution evidence is not ready" }
if ($return.waiting_dependency_resolution.dependency_id -ne $depId -or $return.waiting_dependency_resolution.kind -ne "EVIDENCE") { Fail "Resolution evidence identity/kind mismatch" }
if ($return.waiting_dependency_resolution.resolution_status -ne "SATISFIED") { Fail "Resolution status was not SATISFIED" }
if ($return.waiting_dependency_resolution.authorization_granted -ne $false -or $return.waiting_dependency_resolution.execution_authorized -ne $false) { Fail "Dependency resolution was conflated with execution authorization" }
$historyAfterReturn = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$eventsAfterReturn = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ([int]$historyAfterReturn.transition_count -ne ([int]$historyBeforeReturn.transition_count + 1)) { Fail "Valid dependency resolution did not append exactly one transition" }
if ([int]$eventsAfterReturn.event_count -le [int]$eventsBeforeReturn.event_count) { Fail "Valid dependency resolution did not append mission lineage events" }
$returnReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $returnCommand
if ($returnReplay.idempotent_replay -ne $true) { Fail "Exact resolution replay was not idempotent" }
$historyAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ([int]$historyAfterReplay.transition_count -ne [int]$historyAfterReturn.transition_count) { Fail "Resolution replay duplicated transition lineage" }
if ([int]$eventsAfterReplay.event_count -ne [int]$eventsAfterReturn.event_count) { Fail "Resolution replay duplicated event lineage" }
Pass "Matching resolution is durable, returns to RUNNING, and exact replay has zero duplicate side effects"

Write-Host "`n[7] WAIT_FOR_APPROVAL is workflow dependency control, not Governance authorization"
$approvalMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "approval-$token")
$approvalId = $approvalMission.canonical_identity.mission_id
Activate-Running $approvalId "approval-$token"
$approvalDepId = "dep-approval-$token"
$approvalWaitMetadata = @{
    acceptance = "stage3.2.5"
    dependency = @{ dependency_id = $approvalDepId; kind = "APPROVAL"; description = "Await operator workflow approval" }
}
$approvalWaitCommand = New-LifecycleCommand $approvalId "WAIT_FOR_APPROVAL" "approval-wait-$token" $approvalWaitMetadata @("approval:request:$token")
$approvalWait = Post-Json "$MissionBaseUrl/api/missions/$approvalId/lifecycle/commands" $approvalWaitCommand
if ($approvalWait.mission_state.state -ne "WAITING_APPROVAL" -or $approvalWait.waiting_dependency.kind -ne "APPROVAL") { Fail "WAIT_FOR_APPROVAL did not create typed approval dependency" }
if ($approvalWait.waiting_dependency.approval_dependency_is_governance_authorization -ne $false) { Fail "Approval dependency was mislabeled as Governance authorization" }
$approvalResolutionMetadata = @{
    acceptance = "stage3.2.5"
    dependency_resolution = @{ dependency_id = $approvalDepId; status = "SATISFIED"; resolved_by = "operator-$token" }
}
$approvalReturnCommand = New-LifecycleCommand $approvalId "START" "approval-return-$token" $approvalResolutionMetadata @("approval:ticket:$token")
$approvalReturn = Post-Json "$MissionBaseUrl/api/missions/$approvalId/lifecycle/commands" $approvalReturnCommand
if ($approvalReturn.mission_state.state -ne "RUNNING") { Fail "Satisfied approval dependency did not return to RUNNING" }
if ($approvalReturn.waiting_dependency_resolution.approval_dependency_is_governance_authorization -ne $false) { Fail "Approval resolution was conflated with Governance authorization" }
if ($approvalReturn.waiting_dependency_resolution.governance_authorization_query_performed -ne $false -or $approvalReturn.waiting_dependency_resolution.authorization_granted -ne $false) { Fail "Approval resolution synthesized Governance authority" }
Pass "WAITING_APPROVAL is resolved as local workflow evidence while aptsGSS remains the sole authorization authority"

Write-Host "`n[8] Legacy direct waiting state cannot bypass Stage-3.2.5 dependency lineage"
$legacyMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "legacy-$token")
$legacyId = $legacyMission.canonical_identity.mission_id
Activate-Running $legacyId "legacy-$token"
$directWait = New-DirectTransition $legacyId "WAITING_EVIDENCE" "WAITING_EVIDENCE_$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$legacyId/state/transitions" $directWait
$legacyResolutionMetadata = @{
    acceptance = "stage3.2.5"
    dependency_resolution = @{ dependency_id = "dep-legacy-$token"; status = "SATISFIED"; resolved_by = "legacy-acceptance" }
}
$legacyReturn = New-LifecycleCommand $legacyId "START" "legacy-return-$token" $legacyResolutionMetadata @("evidence:legacy:$token")
$legacyFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$legacyId/lifecycle/commands" $legacyReturn
if ($legacyFailure.status -ne 409 -or $legacyFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "Legacy WAITING_EVIDENCE bypass did not fail closed" }
if ($legacyFailure.body.message -notmatch "WAITING_DEPENDENCY_LINEAGE_FOR_RETURN") { Fail "Expected waiting dependency lineage guard rejection" }
$legacyState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$legacyId/state"
if ($legacyState.mission_state.state -ne "WAITING_EVIDENCE") { Fail "Rejected legacy return mutated state" }
Pass "Topology-valid waiting state is insufficient without canonical Stage-3.2.5 dependency lineage"

Write-Host "`n[9] Final boundary / deferred-stage check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.5-waiting-dependency-control") { Fail "Control version changed during acceptance" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Migration level changed during acceptance" }
if ($finalHealth.mission_lifecycle_stage3_2_6_pause_resume_replan_enabled -ne $false) { Fail "Stage 3.2.5 must not claim Stage 3.2.6 pause/resume/replan control" }
if ($finalHealth.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $false) { Fail "Stage 3.2.5 must not claim Stage 3.2.8 completion gate" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority changed" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary changed" }
Pass "Stage 3.2.5 preserved later lifecycle, Governance, migration, and target-execution boundaries"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.5 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
