param(
    [string]$BaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }
function Fail([string]$Message) { Write-Host "[FAIL] $Message" -ForegroundColor Red; exit 1 }

function Get-HttpStatusForPost([string]$Uri, [string]$JsonBody) {
    try {
        Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $JsonBody -UseBasicParsing | Out-Null
        return 200
    } catch {
        if ($_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        throw
    }
}

function Transition-Mission(
    [string]$MissionId,
    [int]$ExpectedVersion,
    [string]$ToState,
    [string]$ReasonCode
) {
    $payload = @{
        expected_state_version = $ExpectedVersion
        to_state = $ToState
        actor = "stage3.1.2-acceptance"
        reason_code = $ReasonCode
        reason = "Acceptance transition to $ToState"
        evidence_refs = @("acceptance:$ReasonCode")
        metadata = @{ acceptance = "stage3.1.2" }
    } | ConvertTo-Json -Depth 20

    return Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/api/missions/$MissionId/state/transitions" `
        -ContentType "application/json" `
        -Body $payload
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.2 - Canonical Mission State Model Acceptance"
Write-Host "=============================================================================="

Write-Host "`n[1] Full regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Regression failed" }
Pass "Stage 3.1.1 + 3.1.2 regression"

Write-Host "`n[2] Health / boundary"
$health = Invoke-RestMethod "$BaseUrl/health"
if ($health.status -ne "ok") { Fail "Health is not ok" }
if ($health.component_id -ne "APTS-MO01") { Fail "Unexpected component_id" }
if ($health.control_version -ne "stage3.1.2-canonical-mission-state-model") { Fail "Unexpected control_version" }
if ($health.mission_state_mode -ne "CANONICAL_VERSIONED_OPTIMISTIC_CONCURRENCY") { Fail "Unexpected mission_state_mode" }
if ($health.dispatch_enabled -ne $false) { Fail "3.1.2 must not enable dispatch" }
if ($health.target_actuation -ne $false) { Fail "3.1.2 must not enable target actuation" }
Pass "Health, state authority, and execution boundary"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
$bodyObject = @{
    idempotency_key = "stage312-acceptance-$token"
    source_system = "POWERSHELL_ACCEPTANCE"
    created_by = "stage3.1.2-acceptance"
    client_request_id = "client-$token"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{
        type = "SECURITY_VALIDATION"
        target_ref = "lab-target-01"
    }
    success_criteria = @(
        @{ metric = "authorized_goal_complete"; expected = $true }
    )
    budgets = @{
        time_seconds = 1800
        max_actions = 20
        risk_ceiling = "MEDIUM"
    }
    required_subsystems = @("CTI", "PENTEST")
    scope_contract_id = "scope-stage312-acceptance"
    scope_version = 1
    roe_version = "1"
    pip_id = "pip-stage312-acceptance"
    pip_version = "1"
    policy_version = "1"
    metadata = @{ environment = "LAB" }
}
$body = $bodyObject | ConvertTo-Json -Depth 20

Write-Host "`n[3] Create mission and verify CREATED/v1"
$created = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/missions" -ContentType "application/json" -Body $body
$missionId = $created.canonical_identity.mission_id
$envelopeHash = $created.envelope.integrity.canonical_sha256
$initial = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/state"
if ($initial.mission_state.state -ne "CREATED") { Fail "Initial state must be CREATED" }
if ($initial.mission_state.state_version -ne 1) { Fail "Initial state_version must be 1" }
if ($initial.mission_state.terminal -ne $false) { Fail "CREATED must not be terminal" }
Pass "Canonical initial state: CREATED/v1"

Write-Host "`n[4] Illegal bypass gate"
$illegal = @{
    expected_state_version = 1
    to_state = "RUNNING"
    actor = "stage3.1.2-acceptance"
    reason_code = "BYPASS_ATTEMPT"
} | ConvertTo-Json -Depth 10
$illegalStatus = Get-HttpStatusForPost "$BaseUrl/api/missions/$missionId/state/transitions" $illegal
if ($illegalStatus -ne 409) { Fail "CREATED -> RUNNING must be rejected with HTTP 409 (actual=$illegalStatus)" }
$afterIllegal = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/state"
if ($afterIllegal.mission_state.state_version -ne 1) { Fail "Illegal transition mutated state_version" }
Pass "Illegal transition rejected without mutation"

Write-Host "`n[5] Legal path to RUNNING"
$t1 = Transition-Mission $missionId 1 "PIP_BOUND" "PIP_BOUND_CONFIRMED"
$t2 = Transition-Mission $missionId 2 "PLANNING" "PLANNING_STARTED"
$t3 = Transition-Mission $missionId 3 "RUNNING" "EXECUTION_STARTED"
if ($t3.mission_state.state -ne "RUNNING") { Fail "Expected RUNNING" }
if ($t3.mission_state.state_version -ne 4) { Fail "Expected state_version=4" }
Pass "CREATED -> PIP_BOUND -> PLANNING -> RUNNING"

Write-Host "`n[6] Optimistic concurrency gate"
$stale = @{
    expected_state_version = 3
    to_state = "WAITING_APPROVAL"
    actor = "stage3.1.2-acceptance"
    reason_code = "STALE_WRITER"
} | ConvertTo-Json -Depth 10
$staleStatus = Get-HttpStatusForPost "$BaseUrl/api/missions/$missionId/state/transitions" $stale
if ($staleStatus -ne 409) { Fail "Stale writer must return HTTP 409 (actual=$staleStatus)" }
$afterStale = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/state"
if ($afterStale.mission_state.state -ne "RUNNING" -or $afterStale.mission_state.state_version -ne 4) {
    Fail "Stale writer changed canonical state"
}
Pass "Stale state_version rejected"

Write-Host "`n[7] Waiting / resume / cleanup / completion"
$t4 = Transition-Mission $missionId 4 "WAITING_APPROVAL" "APPROVAL_REQUIRED"
$t5 = Transition-Mission $missionId 5 "RUNNING" "APPROVAL_RESOLVED"
$t6 = Transition-Mission $missionId 6 "CLEANING_UP" "FINALIZATION_STARTED"
$t7 = Transition-Mission $missionId 7 "COMPLETED" "MISSION_GOAL_COMPLETE"
if ($t7.mission_state.state -ne "COMPLETED") { Fail "Expected COMPLETED" }
if ($t7.mission_state.state_version -ne 8) { Fail "Expected state_version=8" }
if ($t7.mission_state.terminal -ne $true) { Fail "COMPLETED must be terminal" }
Pass "Canonical terminal completion reached through CLEANING_UP"

Write-Host "`n[8] Terminal immutability"
$resume = @{
    expected_state_version = 8
    to_state = "RUNNING"
    actor = "stage3.1.2-acceptance"
    reason_code = "ILLEGAL_RESUME"
} | ConvertTo-Json -Depth 10
$resumeStatus = Get-HttpStatusForPost "$BaseUrl/api/missions/$missionId/state/transitions" $resume
if ($resumeStatus -ne 409) { Fail "Terminal state must reject outgoing transition with HTTP 409" }
Pass "Terminal state is immutable"

Write-Host "`n[9] Transition ledger"
$history = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/state/transitions"
if ($history.transition_count -ne 7) { Fail "Expected exactly 7 committed transitions" }
for ($i = 0; $i -lt $history.transitions.Count; $i++) {
    $expectedToVersion = $i + 2
    if ($history.transitions[$i].to_state_version -ne $expectedToVersion) {
        Fail "Transition ledger version sequence is not contiguous"
    }
}
Pass "Append-only transition ledger is contiguous"

Write-Host "`n[10] Envelope immutability"
$envelope = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/envelope"
if ($envelope.envelope.integrity.canonical_sha256 -ne $envelopeHash) {
    Fail "Mission state changes mutated immutable envelope hash"
}
Pass "Stage 3.1.1 immutable envelope preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.2 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "mission_id    : $missionId"
Write-Host "final_state   : COMPLETED"
Write-Host "state_version : 8"
Write-Host "transitions   : 7"
Write-Host "=============================================================================="
