param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.2.3 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Post-Json([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 80 -Compress
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
}

function Get-PostFailure([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 80 -Compress
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

function New-MissionPayload([string]$Token, [bool]$WithPip) {
    $body = @{
        idempotency_key = "stage323-mission-$Token"
        source_system = "STAGE323_ACCEPTANCE"
        created_by = "stage3.2.3-acceptance"
        client_request_id = "client-$Token"
        mission_kind = "AUTONOMOUS_PENTEST"
        objective = @{ type = "SECURITY_VALIDATION"; target_ref = "stage323-lab" }
        success_criteria = @(@{ metric = "stage323_pip_activation"; expected = $true })
        budgets = @{ time_seconds = 1200; max_actions = 10; risk_ceiling = "LOW" }
        required_subsystems = @("CTI")
        metadata = @{ environment = "LAB"; acceptance = "stage3.2.3" }
    }
    if ($WithPip) {
        $body.pip_id = "pip-$Token"
        $body.pip_version = "7"
    }
    return $body
}

function New-BindCommand([string]$MissionId, [string]$Token) {
    $state = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/state"
    $vector = Invoke-RestMethod "$MissionBaseUrl/api/missions/$MissionId/version-vector"
    return @{
        command_id = "lc-bind-$Token"
        idempotency_key = "idem-lc-bind-$Token"
        command = "BIND_PIP"
        expected_version_sha256 = $vector.version_sha256
        expected_state_version = [int]$state.mission_state.state_version
        actor = "stage3.2.3-acceptance"
        reason_code = "ACTIVATE_PIP"
        reason = "Stage 3.2.3 immutable PIP activation"
        evidence_refs = @("evidence:stage3.2.3:acceptance")
        metadata = @{ acceptance = "stage3.2.3"; mission_id = $MissionId }
    }
}

Write-Host "=============================================================================="
Write-Host "Stage 3.2.3 - Mission PIP Activation Acceptance"
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
    if (($pytestOutput -join "`n") -notmatch "152 passed") { Fail "Expected Stage-3.2.3 baseline '152 passed'" }
} finally {
    Pop-Location
}
Pass "Stage 3.1.1 through 3.2.3 regression baseline: 152 passed"

Write-Host "`n[2] Health / activation contract / authority boundary"
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)" }
if ($health.status -ne "ok" -or $health.component_id -ne "APTS-MO01") { Fail "Unexpected Mission health identity" }
if ($health.control_version -ne "stage3.2.3-mission-pip-activation") { Fail "Unexpected control_version: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne 8) { Fail "Stage 3.2.3 must not add a database migration" }
if ($health.mission_activation_schema_version -ne "apts-mission-pip-activation-v1") { Fail "Activation schema mismatch" }
if ($health.mission_activation_mode -ne "CREATED_TO_PIP_BOUND_FROM_IMMUTABLE_CANONICAL_PIP_BINDING") { Fail "Activation mode mismatch" }
if ($health.mission_activation_command -ne "BIND_PIP" -or $health.mission_activation_transition -ne "CREATED->PIP_BOUND") { Fail "Activation command/transition mismatch" }
if ($health.mission_activation_binding_source -ne "IMMUTABLE_CANONICAL_MISSION_ENVELOPE") { Fail "Activation binding source mismatch" }
if ($health.mission_activation_pip_artifact_query_performed -ne $false -or $health.mission_activation_governance_query_performed -ne $false) { Fail "Activation must be local-only" }
if ($health.mission_activation_authorization_granted -ne $false -or $health.mission_activation_execution_authorized -ne $false) { Fail "Activation must not synthesize authorization/execution authority" }
if (@($health.supported_controls) -notcontains "stage3.2.2-lifecycle-transition-guard-matrix") { Fail "Stage 3.2.2 control disappeared" }
if (@($health.supported_controls) -notcontains "stage3.2.3-mission-pip-activation") { Fail "Stage 3.2.3 control missing" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) { Fail "Target execution authority must remain disabled" }
Pass "Stage 3.2.3 activation contract active; migration and authority boundaries preserved"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))

Write-Host "`n[3] Activation discovery: exact immutable PIP binding is locally ready"
$readyCreated = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "ready-$token" $true)
$readyMissionId = [string]$readyCreated.canonical_identity.mission_id
$activationView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/activation-contract"
if ($activationView.mission_activation.schema_version -ne "apts-mission-pip-activation-v1") { Fail "Activation discovery schema mismatch" }
if ($activationView.mission_activation.current_state -ne "CREATED" -or $activationView.mission_activation.activation_ready -ne $true) { Fail "Complete-PIP CREATED mission should be activation-ready" }
if ($activationView.mission_activation.pip_binding.pip_id -ne "pip-ready-$token" -or $activationView.mission_activation.pip_binding.pip_version -ne "7") { Fail "Activation discovery did not expose exact PIP binding" }
if ($activationView.mission_activation.canonical_envelope.integrity_verified -ne $true) { Fail "Canonical envelope integrity was not verified" }
if ($activationView.mission_activation.pip_artifact_query_performed -ne $false -or $activationView.mission_activation.governance_authorization_query_performed -ne $false) { Fail "Activation discovery crossed an external authority boundary" }
if ($activationView.mission_activation.execution_authorized -ne $false) { Fail "Activation discovery incorrectly authorized execution" }
Pass "Activation readiness binds CREATED to the exact immutable PIP identity/version without external queries"

Write-Host "`n[4] Missing PIP fails closed before activation mutation"
$missingCreated = Post-Json "$MissionBaseUrl/api/missions" (New-MissionPayload "missing-$token" $false)
$missingMissionId = [string]$missingCreated.canonical_identity.mission_id
$missingActivation = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/activation-contract"
if ($missingActivation.mission_activation.activation_ready -ne $false) { Fail "Missing-PIP mission must not be activation-ready" }
$missingBind = New-BindCommand $missingMissionId "missing-$token"
$failure = Get-PostFailure "$MissionBaseUrl/api/missions/$missingMissionId/lifecycle/commands" $missingBind
if ([int]$failure.status -ne 409 -or $failure.body.code -ne "MISSION_LIFECYCLE_GUARD_REJECTED") { Fail "Missing-PIP BIND_PIP did not fail closed with HTTP 409" }
if ($failure.body.message -notmatch "PIP_BINDING_COMPLETE_WHEN_REQUIRED") { Fail "Expected PIP prerequisite guard id was not exposed" }
$missingState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/state"
$missingHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/state/transitions"
if ($missingState.mission_state.state -ne "CREATED" -or [int]$missingHistory.transition_count -ne 0) { Fail "Rejected activation mutated canonical state" }
Pass "Incomplete canonical PIP binding is rejected with zero lifecycle mutation"

Write-Host "`n[5] BIND_PIP activates exact binding and preserves immutable envelope"
$beforeEnvelope = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/envelope"
$bindBody = New-BindCommand $readyMissionId "ready-$token"
$bindResult = Post-Json "$MissionBaseUrl/api/missions/$readyMissionId/lifecycle/commands" $bindBody
if ($bindResult.mission_state.state -ne "PIP_BOUND") { Fail "BIND_PIP did not produce PIP_BOUND" }
if ($null -eq $bindResult.mission_activation -or $bindResult.mission_activation.activation_ready -ne $true) { Fail "BIND_PIP response missing ready activation evidence" }
if ($bindResult.mission_activation.pip_binding.pip_id -ne "pip-ready-$token" -or $bindResult.mission_activation.pip_binding.pip_version -ne "7") { Fail "Activation evidence PIP identity/version mismatch" }
if ($bindResult.mission_activation.canonical_envelope.canonical_sha256 -ne $beforeEnvelope.envelope.integrity.canonical_sha256) { Fail "Activation evidence envelope hash mismatch" }
if ($bindResult.transition.metadata.mission_activation.schema_version -ne "apts-mission-pip-activation-v1") { Fail "Activation evidence was not persisted in transition metadata" }
$afterEnvelope = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/envelope"
if ($afterEnvelope.envelope.integrity.canonical_sha256 -ne $beforeEnvelope.envelope.integrity.canonical_sha256) { Fail "BIND_PIP mutated immutable envelope hash" }
if ($afterEnvelope.envelope.bindings.pip.pip_id -ne $beforeEnvelope.envelope.bindings.pip.pip_id -or $afterEnvelope.envelope.bindings.pip.pip_version -ne $beforeEnvelope.envelope.bindings.pip.pip_version) { Fail "BIND_PIP rewrote immutable PIP binding" }
Pass "CREATED -> PIP_BOUND activates rather than rewrites the immutable canonical PIP binding"

Write-Host "`n[6] Exact replay preserves activation evidence with no duplicate lineage"
$replay = Post-Json "$MissionBaseUrl/api/missions/$readyMissionId/lifecycle/commands" $bindBody
if ($replay.idempotent_replay -ne $true) { Fail "Exact BIND_PIP replay was not idempotent" }
if ($replay.mission_activation.canonical_envelope.canonical_sha256 -ne $bindResult.mission_activation.canonical_envelope.canonical_sha256) { Fail "Activation replay evidence changed" }
$readyHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/state/transitions"
$readyEvents = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/events"
if ([int]$readyHistory.transition_count -ne 1) { Fail "Exact replay duplicated activation transition" }
if (@($readyEvents.events | Where-Object { $_.event_type -eq "MISSION_STATE_TRANSITIONED" }).Count -ne 1) { Fail "Exact replay duplicated transition lineage" }
$postActivation = Invoke-RestMethod "$MissionBaseUrl/api/missions/$readyMissionId/activation-contract"
if ($postActivation.mission_activation.current_state -ne "PIP_BOUND" -or $postActivation.mission_activation.activation_ready -ne $false) { Fail "Activation contract should close after PIP_BOUND" }
Pass "Activation is one-shot, idempotent, and durable through existing transition/event lineage"

Write-Host "`n[7] Lifecycle discovery exposes Stage-3.2.3 activation semantics without authorization"
$lifecycleView = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missingMissionId/lifecycle-command-contract"
if ($lifecycleView.lifecycle_command_contract.stage3_2_3_activation_contract_schema_version -ne "apts-mission-pip-activation-v1") { Fail "Lifecycle contract missing Stage-3.2.3 activation schema" }
if ($lifecycleView.mission_activation.activation_ready -ne $false) { Fail "Lifecycle discovery activation projection disagrees with missing PIP" }
$bindEval = @($lifecycleView.guard_evaluations | Where-Object { $_.command -eq "BIND_PIP" })
if ($bindEval.Count -ne 1) { Fail "BIND_PIP guard evaluation missing" }
$integrityGuard = @($bindEval[0].checks | Where-Object { $_.guard_id -eq "CANONICAL_ENVELOPE_INTEGRITY_FOR_PIP_ACTIVATION" })
if ($integrityGuard.Count -ne 1 -or $integrityGuard[0].status -ne "PASS" -or $integrityGuard[0].required -ne "VERIFIED") { Fail "Stage-3.2.3 activation integrity guard missing or invalid" }
if ($lifecycleView.governance_authorization_authority -ne "EXTERNAL_APTS_GSS" -or $lifecycleView.target_action_dispatch_enabled -ne $false -or $lifecycleView.target_actuation -ne $false) { Fail "Lifecycle discovery expanded authority" }
Pass "Activation semantics are explicit in lifecycle discovery while authorization remains external"

Write-Host "`n[8] Final boundary check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.2.3-mission-pip-activation") { Fail "Final control_version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 8) { Fail "Repository migration level drifted" }
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority drifted" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution boundary drifted" }
if ($finalHealth.mission_lifecycle_stage3_2_5_dependency_resolution_enabled -ne $false -or $finalHealth.mission_lifecycle_stage3_2_8_completion_gate_enabled -ne $false) { Fail "Future lifecycle stages were claimed prematurely" }
Pass "Stage 3.2.3 preserved Governance, migration, and target-execution boundaries"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.2.3 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
