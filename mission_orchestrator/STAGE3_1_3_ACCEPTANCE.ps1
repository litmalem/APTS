param(
    [string]$BaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }
function Fail([string]$Message) { Write-Host "[FAIL] $Message" -ForegroundColor Red; exit 1 }

function Get-HttpStatusForPost([string]$Uri, [string]$JsonBody) {
    try {
        $response = Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $JsonBody -UseBasicParsing
        return [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        throw
    }
}

function Get-HttpStatusForGet([string]$Uri) {
    try {
        $response = Invoke-WebRequest -Method Get -Uri $Uri -UseBasicParsing
        return [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        throw
    }
}

function New-ContractBody(
    [string]$IdempotencyKey,
    [int]$ExpectedVersion,
    [int]$MaxActions = 20,
    [int]$MaximumConcurrency = 2
) {
    $obj = @{
        expected_contract_version = $ExpectedVersion
        idempotency_key = $IdempotencyKey
        actor = "stage3.1.3-acceptance"
        scope = @{
            targets = @(
                @{
                    target_type = "CIDR"
                    target_value = "127.0.0.0/8"
                    environment = "LAB"
                }
            )
            excluded_targets = @(
                @{
                    target_type = "IP"
                    target_value = "127.0.0.254"
                    environment = "LAB"
                }
            )
            network_ranges = @("127.0.0.0/8")
            domains = @("lab.example.test")
            services = @(
                @{
                    name = "https"
                    protocol = "TCP"
                    port = 443
                    target_ref = "lab.example.test"
                }
            )
        }
        roe = @{
            allowed_action_classes = @("TARGET_RECON", "VULNERABILITY_VALIDATION")
            prohibited_action_classes = @("DESTRUCTIVE_ACTION", "CREDENTIAL_USE")
            allowed_time_window = @{
                start_at = "2026-09-02T00:00:00Z"
                end_at = "2026-09-03T00:00:00Z"
            }
            maximum_concurrency = $MaximumConcurrency
            destructive_actions_allowed = $false
            credential_usage_allowed = $false
            persistence_allowed = $false
            human_approval_required_for = @("VULNERABILITY_VALIDATION")
        }
        constraints = @{
            max_actions = $MaxActions
            max_duration = 1800
            risk_threshold = "MODERATE"
            resource_budget = @{
                max_network_requests = 500
                max_parallel_targets = 2
            }
            data_handling_policy = @{
                classification = "INTERNAL"
                retention_days = 7
                export_allowed = $false
            }
        }
        reason = "Stage 3.1.3 acceptance mission boundary"
        metadata = @{
            environment = "LAB"
            acceptance = "stage3.1.3"
        }
    }
    return ($obj | ConvertTo-Json -Depth 30)
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.3 - Mission Scope, RoE & Constraint Contract Acceptance"
Write-Host "=============================================================================="

Write-Host "`n[1] Full regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Regression failed" }
Pass "Stage 3.1.1 + 3.1.2 + 3.1.3 regression"

Write-Host "`n[2] Health / authority boundary"
$health = Invoke-RestMethod "$BaseUrl/health"
if ($health.status -ne "ok") { Fail "Health is not ok" }
if ($health.component_id -ne "APTS-MO01") { Fail "Unexpected component_id" }
if ($health.control_version -ne "stage3.1.3-mission-scope-roe-constraint-contract") { Fail "Unexpected control_version" }
if ($health.mission_scope_contract_mode -ne "IMMUTABLE_VERSIONED_HASHED_APPEND_ONLY") { Fail "Unexpected contract mode" }
if ($health.scope_contract_authority -ne "GLOBAL_MISSION_ORCHESTRATOR_CANONICAL_DEFINITION") { Fail "Unexpected scope authority" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.governance_binding_enabled -ne $false) { Fail "3.1.3 must not bind/evaluate Governance yet" }
if ($health.dispatch_enabled -ne $false) { Fail "3.1.3 must not enable dispatch" }
if ($health.target_actuation -ne $false) { Fail "3.1.3 must not enable target actuation" }
Pass "Canonical definition authority separated from Governance/execution authority"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
$missionBody = @{
    idempotency_key = "stage313-mission-$token"
    source_system = "POWERSHELL_ACCEPTANCE"
    created_by = "stage3.1.3-acceptance"
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
    metadata = @{ environment = "LAB" }
} | ConvertTo-Json -Depth 20

Write-Host "`n[3] Create canonical mission"
$created = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/missions" -ContentType "application/json" -Body $missionBody
$missionId = $created.canonical_identity.mission_id
$envelopeHash = $created.envelope.integrity.canonical_sha256
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Invalid canonical mission id" }
$stateBefore = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/state"
if ($stateBefore.mission_state.state -ne "CREATED" -or $stateBefore.mission_state.state_version -ne 1) {
    Fail "Mission did not start in CREATED/v1"
}
Pass "Mission created: $missionId"

Write-Host "`n[4] No implicit contract before explicit creation"
$missingStatus = Get-HttpStatusForGet "$BaseUrl/api/missions/$missionId/scope-contract"
if ($missingStatus -ne 404) { Fail "Missing scope contract must return HTTP 404 (actual=$missingStatus)" }
$emptyHistory = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/scope-contract/history"
if ($emptyHistory.current_contract_version -ne 0 -or $emptyHistory.version_count -ne 0) {
    Fail "Empty scope history projection is invalid"
}
Pass "Scope contract requires explicit canonical creation"

Write-Host "`n[5] Create canonical Scope/RoE/Constraint v1"
$v1Body = New-ContractBody "stage313-scope-v1-$token" 0 20 2
$v1 = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/missions/$missionId/scope-contract" -ContentType "application/json" -Body $v1Body
if ($v1.idempotent_replay -ne $false) { Fail "Initial contract must not be replay" }
if ($v1.contract_version -ne 1) { Fail "Initial contract_version must be 1" }
if (-not $v1.mission_scope_contract_id.StartsWith("mscope-")) { Fail "Invalid mission_scope_contract_id" }
if (-not $v1.snapshot_id.StartsWith("mscope-snap-")) { Fail "Invalid snapshot_id" }
if ($v1.canonical_sha256.Length -ne 64) { Fail "Contract hash must contain 64 hex chars" }
if ($v1.contract.integrity.canonical_sha256 -ne $v1.canonical_sha256) { Fail "Contract hash/read model mismatch" }
if ($v1.contract.roe.destructive_actions_allowed -ne $false) { Fail "Destructive-action flag must remain false" }
if ($v1.contract.roe.credential_usage_allowed -ne $false) { Fail "Credential-use flag must remain false" }
if ($v1.contract.constraints.risk_threshold -ne "MODERATE") { Fail "Risk threshold canonicalization mismatch" }
$contractId = $v1.mission_scope_contract_id
$v1Snapshot = $v1.snapshot_id
$v1Hash = $v1.canonical_sha256
Pass "Canonical mission boundary created: $contractId/v1"

Write-Host "`n[6] Idempotent contract replay"
$replay = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/missions/$missionId/scope-contract" -ContentType "application/json" -Body $v1Body
if ($replay.idempotent_replay -ne $true) { Fail "Identical retry must be idempotent replay" }
if ($replay.snapshot_id -ne $v1Snapshot -or $replay.canonical_sha256 -ne $v1Hash) {
    Fail "Replay changed immutable v1 snapshot"
}
Pass "Contract retry preserves canonical snapshot"

Write-Host "`n[7] Idempotency and optimistic version conflict gates"
$idempotencyConflict = ($v1Body | ConvertFrom-Json)
$idempotencyConflict.constraints.max_actions = 99
$idempotencyConflictJson = $idempotencyConflict | ConvertTo-Json -Depth 30
$idempotencyStatus = Get-HttpStatusForPost "$BaseUrl/api/missions/$missionId/scope-contract" $idempotencyConflictJson
if ($idempotencyStatus -ne 409) { Fail "Changed request with same scope idempotency key must return HTTP 409" }

$staleBody = New-ContractBody "stage313-stale-$token" 0 10 1
$staleStatus = Get-HttpStatusForPost "$BaseUrl/api/missions/$missionId/scope-contract" $staleBody
if ($staleStatus -ne 409) { Fail "Stale expected_contract_version must return HTTP 409" }
$currentAfterConflict = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/scope-contract"
if ($currentAfterConflict.contract_version -ne 1 -or $currentAfterConflict.canonical_sha256 -ne $v1Hash) {
    Fail "Conflict path mutated current contract"
}
Pass "Idempotency and stale-writer conflicts rejected without mutation"

Write-Host "`n[8] Semantic fail-closed validation"
$bad = (New-ContractBody "stage313-bad-$token" 1 20 2 | ConvertFrom-Json)
$bad.roe.allowed_action_classes += "DESTRUCTIVE_ACTION"
$bad.roe.prohibited_action_classes = @("CREDENTIAL_USE")
$badJson = $bad | ConvertTo-Json -Depth 30
$badStatus = Get-HttpStatusForPost "$BaseUrl/api/missions/$missionId/scope-contract" $badJson
if ($badStatus -ne 400) { Fail "Contradictory destructive-action contract must return HTTP 400 (actual=$badStatus)" }
$historyAfterBad = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/scope-contract/history"
if ($historyAfterBad.version_count -ne 1) { Fail "Invalid contract was persisted" }
Pass "Invalid RoE rejected before persistence"

Write-Host "`n[9] Append immutable revision v2"
$v2Body = New-ContractBody "stage313-scope-v2-$token" 1 10 1
$v2 = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/missions/$missionId/scope-contract" -ContentType "application/json" -Body $v2Body
if ($v2.contract_version -ne 2) { Fail "Revision must create contract_version=2" }
if ($v2.mission_scope_contract_id -ne $contractId) { Fail "Revision changed stable contract identity" }
if ($v2.snapshot_id -eq $v1Snapshot) { Fail "Revision reused v1 snapshot id" }
if ($v2.canonical_sha256 -eq $v1Hash) { Fail "Revision reused v1 canonical hash" }
if ($v2.contract.constraints.max_actions -ne 10) { Fail "Revision max_actions mismatch" }
if ($v2.contract.roe.maximum_concurrency -ne 1) { Fail "Revision concurrency mismatch" }
Pass "v2 created with stable contract identity and new immutable snapshot"

Write-Host "`n[10] Append-only history"
$history = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/scope-contract/history"
if ($history.version_count -ne 2) { Fail "Expected exactly 2 scope contract versions" }
if ($history.current_contract_version -ne 2) { Fail "Current contract version must be 2" }
if ($history.versions[0].contract_version -ne 1 -or $history.versions[1].contract_version -ne 2) {
    Fail "Contract history version sequence is invalid"
}
if ($history.versions[0].snapshot_id -ne $v1Snapshot -or $history.versions[0].canonical_sha256 -ne $v1Hash) {
    Fail "Historical v1 snapshot changed after revision"
}
Pass "Historical snapshots are append-only and immutable"

Write-Host "`n[11] State and envelope independence"
$stateAfter = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/state"
if ($stateAfter.mission_state.state -ne "CREATED" -or $stateAfter.mission_state.state_version -ne 1) {
    Fail "Scope contract mutation implicitly changed mission lifecycle state"
}
$envelopeAfter = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/envelope"
if ($envelopeAfter.envelope.integrity.canonical_sha256 -ne $envelopeHash) {
    Fail "Scope contract mutation changed immutable Stage-3.1.1 envelope"
}
Pass "Contract versions are independent from lifecycle state and immutable envelope"

Write-Host "`n[12] Current contract readback"
$current = Invoke-RestMethod "$BaseUrl/api/missions/$missionId/scope-contract"
if ($current.contract_version -ne 2) { Fail "Current contract readback is not v2" }
if ($current.contract.constraints.max_actions -ne 10) { Fail "Current v2 content mismatch" }
if ($current.contract.integrity.canonical_sha256 -ne $v2.canonical_sha256) { Fail "Current v2 hash mismatch" }
Pass "Current canonical Scope/RoE/Constraint readback verified"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.3 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "mission_id              : $missionId"
Write-Host "mission_scope_contract  : $contractId"
Write-Host "current_contract_version: 2"
Write-Host "contract_versions       : 2"
Write-Host "mission_state            : CREATED/v1"
Write-Host "governance_binding       : DISABLED (boundary preserved)"
Write-Host "=============================================================================="
