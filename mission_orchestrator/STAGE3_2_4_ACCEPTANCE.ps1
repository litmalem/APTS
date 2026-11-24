param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.4 ACCEPTANCE: FAIL" -ForegroundColor Red
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
        idempotency_key = "stage324-mission-$Token"
        source_system = "STAGE324_ACCEPTANCE"
        created_by = "stage3.2.4-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage324-lab" }
        success_criteria = @(@{ metric = "stage324_planning_run_activation"; expected = $true })
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        pip_id = "pip-$Token"
        pip_version = "9"
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.4" }
    }
}

function New-LifecycleCommand([string]$MissionId, [string]$Command, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-$Command-$Token"
        idempotency_key = "idem-lc-$Command-$Token"
        command = $Command
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.2.4-acceptance"
        reason_code = "STAGE324_$Command"
        reason = "Stage 3.2.4 lifecycle command $Command"
        evidence_refs = @("evidence:stage3.2.4:acceptance")
        metadata = @{ acceptance = "stage3.2.4"; mission_id = $MissionId; token = $Token }
    }
}

function New-DirectTransition([string]$MissionId, [string]$ToState, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    return @{
        expected_state_version = [int]$state.mission_state.state_version
        to_state = $ToState
        actor = "stage3.2.4-legacy-acceptance"
        reason_code = "LEGACY_$Token"
        reason = "Exercise preserved Stage-3.1 direct transition API"
        evidence_refs = @()
        metadata = @{ legacy_acceptance = $true; stage = "3.2.4" }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.4 - Planning and Run Activation Acceptance"
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
    if (($pytestOutput -join "`n") -notmatch "166 passed") { Fail "Expected Stage-3.2.4 baseline '166 passed'" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.4 regression baseline: 166 passed"

Write-Host "`n[2] Health / planning-run activation contract / authority boundary"
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)" }
if ($health.status -ne "ok" -or $health.component_id -ne "APTS-MO01") { Fail "Unexpected Mission health identity" }
if ($health.control_version -ne "stage3.2.4-planning-run-activation") { Fail "Unexpected control_version: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Stage 3.2.4 must not add a database migration" }
if ($health.mission_planning_run_activation_schema_version -ne "apts-mission-planning-run-activation-v1") { Fail "Planning/run activation schema mismatch" }
if ($health.mission_planning_run_activation_mode -ne "PIP_BOUND_TO_PLANNING_TO_RUNNING_WITH_LOCAL_LINEAGE_PROOFS") { Fail "Planning/run activation mode mismatch" }
if ($health.mission_planning_activation_command -ne "START_PLANNING" -or $health.mission_planning_activation_transition -ne "PIP_BOUND->PLANNING") { Fail "Planning activation contract mismatch" }
if ($health.mission_run_activation_command -ne "START" -or $health.mission_run_activation_transition -ne "PLANNING->RUNNING") { Fail "Run activation contract mismatch" }
if ($health.mission_planning_run_requires_pip_activation_lineage -ne $true -or $health.mission_run_requires_planning_activation_lineage -ne $true) { Fail "Activation-lineage requirements are not active" }
if ($health.mission_lifecycle_stage3_2_4_planning_run_activation_enabled -ne $true) { Fail "Stage-3.2.4 activation flag is not active" }
if ($health.mission_planning_run_planner_invocation_performed -ne $false -or $health.mission_planning_run_plan_artifact_created -ne $false) { Fail "Stage 3.2.4 must not implement planner execution" }
if ($health.mission_planning_run_governance_query_performed -ne $false -or $health.mission_planning_run_authorization_granted -ne $false -or $health.mission_planning_run_execution_authorized -ne $false) { Fail "Stage 3.2.4 must not synthesize authorization" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution boundary expanded" }
Pass "Stage 3.2.4 contract active; migration, planner, Governance, and target-execution boundaries preserved"

$token = [Guid]::NewGuid().ToString("N").Substring(0, 10)

Write-Host "`n[3] Stage-3.2.3 BIND_PIP lineage makes planning activation locally ready"
$mission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "valid-$token")
$missionId = $mission.canonical_identity.mission_id
$bindCommand = New-LifecycleCommand $missionId "BIND_PIP" "bind-$token"
$bind = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $bindCommand
if ($bind.mission_state.state -ne "PIP_BOUND") { Fail "BIND_PIP did not reach PIP_BOUND" }
$activationView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planning-run-activation-contract"
if ($activationView.planning_run_activation.planning_activation.activation_ready -ne $true) { Fail "Planning activation should be ready after canonical Stage-3.2.3 BIND_PIP" }
if ($activationView.planning_run_activation.activation_chain.pip_activation.valid -ne $true) { Fail "Stage-3.2.3 PIP activation lineage was not recognized" }
if ($activationView.planning_run_activation.run_activation.activation_ready -ne $false) { Fail "Run activation must not be ready before PLANNING" }
Pass "PIP_BOUND planning readiness is derived from immutable PIP binding plus durable Stage-3.2.3 lineage"

Write-Host "`n[4] Legacy direct PIP_BOUND cannot bypass Stage-3.2.3 activation lineage"
$legacy = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "legacy-$token")
$legacyId = $legacy.canonical_identity.mission_id
$directPip = New-DirectTransition $legacyId "PIP_BOUND" "PIP_BOUND_$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$legacyId/state/transitions" $directPip
$legacyPlan = New-LifecycleCommand $legacyId "START_PLANNING" "legacy-plan-$token"
$legacyFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$legacyId/lifecycle/commands" $legacyPlan
if ($legacyFailure.status -ne 409) { Fail "Expected HTTP 409 for START_PLANNING without Stage-3.2.3 activation lineage; got $($legacyFailure.status)" }
if ($null -eq $legacyFailure.body -or $legacyFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "Unexpected legacy START_PLANNING failure contract" }
if ($legacyFailure.body.message -notmatch "PIP_ACTIVATION_EVIDENCE_FOR_PLANNING") { Fail "Expected PIP activation lineage guard rejection" }
$legacyState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$legacyId/state"
if ($legacyState.mission_state.state -ne "PIP_BOUND") { Fail "Rejected planning activation mutated state" }
Pass "Topology-valid PIP_BOUND is insufficient without canonical Stage-3.2.3 activation lineage"

Write-Host "`n[5] START_PLANNING activates PLANNING with durable evidence and no planner invocation"
$beforeEnvelope = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/envelope"
$planCommand = New-LifecycleCommand $missionId "START_PLANNING" "plan-$token"
$plan = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $planCommand
if ($plan.mission_state.state -ne "PLANNING") { Fail "START_PLANNING did not reach PLANNING" }
if ($plan.planning_run_activation.schema_version -ne "apts-mission-planning-run-activation-v1" -or $plan.planning_run_activation.phase -ne "PLANNING") { Fail "Planning activation evidence missing or malformed" }
if ($plan.planning_run_activation.activation_ready -ne $true) { Fail "Planning activation evidence was not ready" }
if ($plan.planning_run_activation.pip_activation_proof.valid -ne $true) { Fail "Planning activation did not bind Stage-3.2.3 proof" }
if ($plan.planning_run_activation.planner_invocation_performed -ne $false -or $plan.planning_run_activation.plan_artifact_created -ne $false) { Fail "START_PLANNING unexpectedly invoked planner/created plan" }
if ($plan.planning_run_activation.execution_authorized -ne $false) { Fail "PLANNING activation must not grant execution authorization" }
$afterEnvelope = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/envelope"
if ($beforeEnvelope.envelope.integrity.canonical_sha256 -ne $afterEnvelope.envelope.integrity.canonical_sha256) { Fail "START_PLANNING mutated immutable Mission envelope" }
Pass "PIP_BOUND -> PLANNING records activation evidence while preserving immutable envelope and planner boundary"

Write-Host "`n[6] Exact START_PLANNING replay is idempotent with zero duplicate lineage"
$historyBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$eventsBeforeReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
$planReplay = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $planCommand
if ($planReplay.idempotent_replay -ne $true) { Fail "Exact START_PLANNING replay was not marked idempotent" }
if ($planReplay.planning_run_activation.phase -ne "PLANNING") { Fail "Planning activation evidence was not preserved on replay" }
$historyAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state/transitions"
$eventsAfterReplay = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/events"
if ([int]$historyAfterReplay.transition_count -ne [int]$historyBeforeReplay.transition_count) { Fail "Exact START_PLANNING replay duplicated state transition" }
if ([int]$eventsAfterReplay.event_count -ne [int]$eventsBeforeReplay.event_count) { Fail "Exact START_PLANNING replay duplicated mission events" }
Pass "Planning activation is one-shot, idempotent, and durable through existing command/transition/event lineage"

Write-Host "`n[7] Initial START requires durable planning activation lineage"
$legacyRunMission = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "legacy-run-$token")
$legacyRunId = $legacyRunMission.canonical_identity.mission_id
$legacyBind = New-LifecycleCommand $legacyRunId "BIND_PIP" "legacy-run-bind-$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$legacyRunId/lifecycle/commands" $legacyBind
$directPlanning = New-DirectTransition $legacyRunId "PLANNING" "PLANNING_$token"
$null = Post-Json "$MissionBaseUrl/api/missions/$legacyRunId/state/transitions" $directPlanning
$legacyStart = New-LifecycleCommand $legacyRunId "START" "legacy-start-$token"
$startFailure = Get-PostFailure "$MissionBaseUrl/api/missions/$legacyRunId/lifecycle/commands" $legacyStart
if ($startFailure.status -ne 409 -or $startFailure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "Initial START without planning activation lineage did not fail closed" }
if ($startFailure.body.message -notmatch "PLANNING_ACTIVATION_EVIDENCE_FOR_INITIAL_RUN") { Fail "Expected planning activation lineage guard rejection" }
$legacyRunState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$legacyRunId/state"
if ($legacyRunState.mission_state.state -ne "PLANNING") { Fail "Rejected initial START mutated state" }
Pass "PLANNING topology alone cannot activate RUNNING without Stage-3.2.4 planning lineage"

Write-Host "`n[8] Valid START activates RUNNING without authorizing or dispatching target execution"
$runReady = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planning-run-activation-contract"
if ($runReady.planning_run_activation.run_activation.activation_ready -ne $true) { Fail "Run activation should be ready after canonical START_PLANNING" }
$startCommand = New-LifecycleCommand $missionId "START" "run-$token"
$run = Post-Json "$MissionBaseUrl/api/missions/$missionId/lifecycle/commands" $startCommand
if ($run.mission_state.state -ne "RUNNING") { Fail "START did not reach RUNNING" }
if ($run.planning_run_activation.phase -ne "RUNNING" -or $run.planning_run_activation.activation_ready -ne $true) { Fail "Run activation evidence missing or invalid" }
if ($run.planning_run_activation.planning_activation_proof.valid -ne $true) { Fail "RUNNING activation did not bind planning activation lineage" }
if ($run.planning_run_activation.planner_invocation_performed -ne $false -or $run.planning_run_activation.plan_artifact_created -ne $false) { Fail "RUNNING activation unexpectedly invoked planner" }
if ($run.planning_run_activation.governance_authorization_query_performed -ne $false -or $run.planning_run_activation.execution_authorized -ne $false) { Fail "RUNNING lifecycle state was conflated with execution authorization" }
if ($run.planning_run_activation.target_action_dispatch_enabled -ne $false -or $run.planning_run_activation.target_actuation -ne $false) { Fail "START unexpectedly enabled target execution" }
$completeView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/planning-run-activation-contract"
if ($completeView.planning_run_activation.activation_chain.chain_complete -ne $true) { Fail "PIP -> PLANNING -> RUNNING activation chain is not complete" }
Pass "PLANNING -> RUNNING completes local lifecycle activation chain without planner, Governance, or target-execution authority expansion"

Write-Host "`n[9] Final boundary / deferred-stage check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.4-planning-run-activation") { Fail "Control version changed during acceptance" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Migration level changed during acceptance" }
if ($finalHealth.mission_lifecycle_stage3_2_5_dependency_resolution_enabled -ne $false) { Fail "Stage 3.2.4 must not claim Stage 3.2.5 dependency resolution" }
if ($finalHealth.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $false) { Fail "Stage 3.2.4 must not claim Stage 3.2.8 completion gate" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority changed" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary changed" }
Pass "Stage 3.2.4 preserved deferred lifecycle, Governance, migration, and target-execution boundaries"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.4 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
