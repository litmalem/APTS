param(
    [string]$BaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }
function Fail([string]$Message) { Write-Host "[FAIL] $Message" -ForegroundColor Red; exit 1 }

Write-Host "=============================================================================="
Write-Host "Stage 3.1.1 - Canonical Mission Identity & Envelope Acceptance"
Write-Host "=============================================================================="

Write-Host "`n[1] Focused regression"
python -m pytest -q .\tests\test_stage3_1_1_identity_envelope.py
if ($LASTEXITCODE -ne 0) { Fail "Focused regression failed" }
Pass "Focused regression"

Write-Host "`n[2] Health"
$health = Invoke-RestMethod "$BaseUrl/health"
if ($health.status -ne "ok") { Fail "Health is not ok" }
if ($health.component_id -ne "APTS-MO01") { Fail "Unexpected component_id" }
if ($health.control_version -ne "stage3.1.1-canonical-mission-identity-envelope") { Fail "Unexpected control_version" }
if ($health.dispatch_enabled -ne $false) { Fail "3.1.1 must not enable dispatch" }
if ($health.target_actuation -ne $false) { Fail "3.1.1 must not enable target actuation" }
Pass "Health and authority boundary"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
$idem = "stage311-acceptance-$token"
$bodyObject = @{
    idempotency_key = $idem
    source_system = "POWERSHELL_ACCEPTANCE"
    created_by = "stage3.1.1-acceptance"
    client_request_id = "client-$token"
    client_mission_ref = "pre-global-$token"
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
    scope_contract_id = "scope-stage311-acceptance"
    scope_version = 1
    roe_version = "1"
    policy_version = "1"
    metadata = @{ environment = "LAB" }
}
$body = $bodyObject | ConvertTo-Json -Depth 20

Write-Host "`n[3] Create canonical mission"
$created = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/missions" -ContentType "application/json" -Body $body
$missionId = $created.canonical_identity.mission_id
$envelopeId = $created.canonical_identity.envelope_id
$hash = $created.envelope.integrity.canonical_sha256
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Global mission id is not authoritative GMO identity" }
if (-not $envelopeId.StartsWith("menv-")) { Fail "Envelope id is invalid" }
if ($created.canonical_identity.envelope_version -ne 1) { Fail "Envelope version must start at 1" }
if ($hash.Length -ne 64) { Fail "Canonical SHA-256 must contain 64 hex chars" }
if ($created.idempotent_replay -ne $false) { Fail "First creation must not be replay" }
Pass "Canonical identity created: $missionId"

Write-Host "`n[4] Idempotent replay"
$replayed = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/missions" -ContentType "application/json" -Body $body
if ($replayed.idempotent_replay -ne $true) { Fail "Second identical request is not marked replay" }
if ($replayed.canonical_identity.mission_id -ne $missionId) { Fail "Replay changed mission_id" }
if ($replayed.canonical_identity.envelope_id -ne $envelopeId) { Fail "Replay changed envelope_id" }
if ($replayed.envelope.integrity.canonical_sha256 -ne $hash) { Fail "Replay changed canonical hash" }
Pass "Idempotent replay preserves canonical identity"

Write-Host "`n[5] Idempotency conflict gate"
$conflictObject = $bodyObject.Clone()
$conflictObject.objective = @{ type = "SECURITY_VALIDATION"; target_ref = "different-target" }
$conflictBody = $conflictObject | ConvertTo-Json -Depth 20
$conflictStatus = $null
try {
    Invoke-WebRequest -Method Post -Uri "$BaseUrl/api/missions" -ContentType "application/json" -Body $conflictBody -UseBasicParsing | Out-Null
    $conflictStatus = 200
} catch {
    if ($_.Exception.Response) {
        $conflictStatus = [int]$_.Exception.Response.StatusCode
    }
}
if ($conflictStatus -ne 409) { Fail "Changed payload with same idempotency key must return HTTP 409 (actual=$conflictStatus)" }
Pass "Idempotency conflict rejected"

Write-Host "`n[6] Readback"
$mission = Invoke-RestMethod "$BaseUrl/api/missions/$missionId"
$envelope = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/envelope"
if ($mission.mission.mission_id -ne $missionId) { Fail "Mission readback mismatch" }
if ($mission.mission.registration_status -ne "REGISTERED") { Fail "Mission registration status mismatch" }
if ($envelope.envelope.integrity.canonical_sha256 -ne $hash) { Fail "Envelope readback hash mismatch" }
if ($envelope.envelope.bindings.scope.scope_snapshot_id -ne "scope-stage311-acceptance@v1") { Fail "Scope snapshot canonicalization mismatch" }
Pass "Durable mission/envelope readback"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "mission_id  : $missionId"
Write-Host "envelope_id : $envelopeId"
Write-Host "sha256      : $hash"
Write-Host "=============================================================================="
