param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.1.8 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Post-Json([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 40 -Compress
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
}

function Expect-ValidationFailure([string]$Uri, $Body, [string]$ExpectedPhase, [string]$Label) {
    $json = $Body | ConvertTo-Json -Depth 40 -Compress
    try {
        $null = Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
        Fail "$Label unexpectedly passed validation"
    } catch {
        $statusCode = $null
        try { $statusCode = [int]$_.Exception.Response.StatusCode.value__ } catch {}
        if ($statusCode -ne 400) {
            Fail "$Label returned unexpected HTTP status $statusCode : $($_.Exception.Message)"
        }
        $raw = $_.ErrorDetails.Message
        if (-not $raw) { Fail "$Label did not return a structured validation body" }
        try { $body = $raw | ConvertFrom-Json } catch { Fail "$Label validation body is not JSON: $raw" }
        if ($body.code -ne "MISSION_VALIDATION_FAILED") { Fail "$Label returned unexpected code: $($body.code)" }
        if ($body.validation_phase -ne $ExpectedPhase) {
            Fail "$Label expected phase $ExpectedPhase but received $($body.validation_phase)"
        }
        if ($body.persistence_performed -ne $false -or $body.authority_query_performed -ne $false -or $body.planning_performed -ne $false -or $body.target_action_performed -ne $false) {
            Fail "$Label failure response indicates a forbidden side effect"
        }
    }
    Pass "$Label rejected fail-closed at phase $ExpectedPhase"
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.8 - Canonical Mission API & Validation Layer Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[1] Full regression"
$pytestOutput = & python -m pytest -q 2>&1
$pytestOutput | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { Fail "Regression suite failed" }
if (($pytestOutput -join "`n") -notmatch "91 passed") { Fail "Expected current regression result '91 passed'" }
Pass "Stage 3.1.1 through 3.1.8 regression"

Write-Host "`n[2] Stage-3.1.8 health / authority boundary"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)"
}
if ($health.control_version -ne "stage3.1.8-canonical-mission-api-validation-layer") { Fail "Unexpected control_version: $($health.control_version)" }
if ($health.canonical_mission_api_schema_version -ne "apts-canonical-mission-api-v1") { Fail "Canonical Mission API schema mismatch" }
if ($health.canonical_mission_api_stabilized -ne $true) { Fail "Canonical Mission API is not declared stabilized" }
if ($health.canonical_mission_validation_schema_version -ne "apts-canonical-mission-validation-v1") { Fail "Validation schema mismatch" }
if ($health.canonical_mission_validation_mode -ne "PREFLIGHT_NO_PERSISTENCE_FAIL_CLOSED") { Fail "Validation mode mismatch" }
$pipeline = @($health.canonical_mission_validation_pipeline)
if (($pipeline -join ",") -ne "SCHEMA,SEMANTIC,SCOPE,CONSTRAINTS") { Fail "Unexpected validation pipeline: $($pipeline -join ',')" }
if ($health.canonical_mission_preflight_enabled -ne $true) { Fail "Canonical mission preflight is not enabled" }
if ($health.validation_external_authority_queries -ne $false) { Fail "Validation must not query external authorities" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($health.dispatch_enabled -ne $false -or $health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) {
    Fail "Stage 3.1.8 must not enable target execution authority"
}
Pass "Canonical API/validation contract active; Governance and target execution boundaries preserved"

$token = (Get-Date -Format "yyyyMMddHHmmss") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))
$startAt = (Get-Date).ToUniversalTime().AddMinutes(-5).ToString("yyyy-MM-ddTHH:mm:ssZ")
$endAt = (Get-Date).ToUniversalTime().AddHours(4).ToString("yyyy-MM-ddTHH:mm:ssZ")

$missionPayload = @{
    idempotency_key = "stage318-mission-$token"
    source_system = "STAGE318_ACCEPTANCE"
    created_by = "stage3.1.8-acceptance"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{ type = "SECURITY_VALIDATION"; target_ref = "canonical-api-lab" }
    success_criteria = @(@{ metric = "canonical_contract_valid"; expected = $true })
    budgets = @{ time_seconds = 1800 }
    required_subsystems = @("CTI", "PENTEST")
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.8" }
}
$scopePayload = @{
    expected_contract_version = 0
    idempotency_key = "stage318-scope-$token"
    actor = "stage3.1.8-acceptance"
    scope = @{
        targets = @(@{ target_type = "CIDR"; target_value = "127.0.0.0/8"; environment = "LAB" })
        excluded_targets = @()
        network_ranges = @("127.0.0.0/8")
        domains = @()
        services = @()
    }
    roe = @{
        allowed_action_classes = @("INTERNAL_REASONING", "TARGET_RECON")
        prohibited_action_classes = @("DESTRUCTIVE_ACTION")
        allowed_time_window = @{ start_at = $startAt; end_at = $endAt }
        maximum_concurrency = 2
        destructive_actions_allowed = $false
        credential_usage_allowed = $false
        persistence_allowed = $false
        human_approval_required_for = @()
    }
    constraints = @{
        max_actions = 20
        max_duration = 1800
        risk_threshold = "MODERATE"
        resource_budget = @{ max_network_requests = 100; max_parallel_targets = 1 }
        data_handling_policy = @{ classification = "INTERNAL"; retention_days = 7; export_allowed = $false }
    }
    reason = "Stage 3.1.8 canonical mission validation"
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.8" }
}
$draft = @{ mission = $missionPayload; scope_contract = $scopePayload }

Write-Host "`n[3] Canonical preflight validation - all four layers"
try {
    $validation = Post-Json "$MissionBaseUrl/api/missions/validate" $draft
} catch {
    Fail "Valid canonical mission draft failed preflight: $($_.Exception.Message)"
}
if ($validation.status -ne "valid" -or $validation.valid -ne $true) { Fail "Valid draft did not return valid=true" }
if ($validation.validation_schema_version -ne "apts-canonical-mission-validation-v1") { Fail "Validation response schema mismatch" }
$checkPhases = @($validation.checks | ForEach-Object { $_.phase })
if (($checkPhases -join ",") -ne "SCHEMA,SEMANTIC,SCOPE,CONSTRAINTS") { Fail "Validation checks did not cover all phases" }
$failedChecks = @($validation.checks | Where-Object { $_.status -ne "PASS" })
if ($failedChecks.Count -ne 0) { Fail "One or more valid-draft checks did not PASS" }
if ([string]$validation.mission_request_sha256 -notmatch '^[0-9a-f]{64}$') { Fail "Mission validation fingerprint is not SHA-256" }
if ([string]$validation.scope_contract_request_sha256 -notmatch '^[0-9a-f]{64}$') { Fail "Scope validation fingerprint is not SHA-256" }
if ($validation.persistence_performed -ne $false -or $validation.authority_query_performed -ne $false -or $validation.planning_performed -ne $false -or $validation.target_action_performed -ne $false) {
    Fail "Preflight validation performed a forbidden side effect"
}
Pass "Schema -> semantic -> scope -> constraints preflight completed with zero side effects"

Write-Host "`n[4] Preflight did not persist: first create remains non-replay"
try {
    $created = Post-Json "$MissionBaseUrl/api/missions" $missionPayload
} catch {
    Fail "Mission creation after preflight failed: $($_.Exception.Message)"
}
if ($created.idempotent_replay -ne $false) { Fail "Mission create replayed; preflight appears to have persisted state" }
$missionId = [string]$created.canonical_identity.mission_id
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Unexpected mission identity: $missionId" }
Pass "Mission persisted only when the existing canonical create API was called: $missionId"

Write-Host "`n[5] Stabilized create/read/state API"
try {
    $missionRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId"
    $envelopeRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/envelope"
    $stateRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
} catch {
    Fail "Canonical mission read API failed: $($_.Exception.Message)"
}
if ($missionRead.mission.mission_id -ne $missionId) { Fail "Mission read identity mismatch" }
if ($envelopeRead.envelope.mission.mission_kind -ne "AUTONOMOUS_PENTEST") { Fail "Envelope read mismatch" }
if ($stateRead.mission_state.state -ne "CREATED" -or [int]$stateRead.mission_state.state_version -ne 1) { Fail "Initial state must be CREATED/v1" }
Pass "Mission identity, immutable envelope, and canonical state are readable through stable APIs"

Write-Host "`n[6] Stabilized Scope/RoE/Constraint API"
try {
    $scopeResult = Post-Json "$MissionBaseUrl/api/missions/$missionId/scope-contract" $scopePayload
    $scopeRead = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/scope-contract"
} catch {
    Fail "Canonical Scope/RoE/Constraint API failed: $($_.Exception.Message)"
}
if ([int]$scopeResult.contract_version -ne 1 -or [int]$scopeRead.contract_version -ne 1) { Fail "Scope contract did not stabilize at v1" }
if ($scopeRead.snapshot_id -ne $scopeResult.snapshot_id) { Fail "Scope read does not return the persisted canonical snapshot" }
Pass "Canonical Scope/RoE/Constraint contract persisted and read as immutable v1 snapshot"

Write-Host "`n[7] Canonical contract projection"
try {
    $contract = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/canonical-contract"
} catch {
    Fail "Canonical contract projection failed: $($_.Exception.Message)"
}
if ($contract.schema_version -ne "apts-canonical-mission-api-v1") { Fail "Canonical contract projection schema mismatch" }
if ($contract.contract_status -ne "SCOPE_BOUND" -or $contract.contract_complete -ne $true) { Fail "Canonical contract projection is not scope-bound/complete" }
if ($contract.canonical_identity.mission_id -ne $missionId) { Fail "Canonical contract identity mismatch" }
if ($contract.mission_state.state -ne "CREATED") { Fail "Canonical contract state projection mismatch" }
if ($contract.scope_snapshot_id -ne $scopeResult.snapshot_id) { Fail "Canonical contract scope snapshot mismatch" }
if ($contract.external_authority_query_performed -ne $false) { Fail "Canonical contract read unexpectedly claims an external authority query" }
if ($contract.target_action_dispatch_enabled -ne $false -or $contract.target_actuation -ne $false) { Fail "Canonical contract projection changed execution boundary" }
Pass "One local read projection binds identity + envelope + state + current Scope contract"

Write-Host "`n[8] Fail-closed validation phase attribution"
$schemaBadMission = $missionPayload.Clone()
$schemaBadMission["idempotency_key"] = "stage318-bad-schema-$token"
$schemaBadMission["unsupported_field"] = "reject"
Expect-ValidationFailure "$MissionBaseUrl/api/missions/validate" @{ mission = $schemaBadMission; scope_contract = $scopePayload } "SCHEMA" "Schema violation"

$semanticBadMission = $missionPayload.Clone()
$semanticBadMission["idempotency_key"] = "stage318-bad-semantic-$token"
$semanticBadMission["required_subsystems"] = @("CTI", "UNKNOWN-SUBSYSTEM")
Expect-ValidationFailure "$MissionBaseUrl/api/missions/validate" @{ mission = $semanticBadMission; scope_contract = $scopePayload } "SEMANTIC" "Semantic violation"

$scopeBad = $scopePayload.Clone()
$scopeBad["idempotency_key"] = "stage318-bad-scope-$token"
$scopeBad["scope"] = @{
    targets = @(@{ target_type = "IP"; target_value = "127.0.0.1"; environment = "LAB" })
    excluded_targets = @(@{ target_type = "IP"; target_value = "127.0.0.1"; environment = "LAB" })
    network_ranges = @()
    domains = @()
    services = @()
}
Expect-ValidationFailure "$MissionBaseUrl/api/missions/validate" @{ mission = $missionPayload; scope_contract = $scopeBad } "SCOPE" "Scope violation"

$constraintBad = $scopePayload.Clone()
$constraintBad["idempotency_key"] = "stage318-bad-constraint-$token"
$constraintBad["constraints"] = @{
    max_actions = 20
    max_duration = 1801
    risk_threshold = "MODERATE"
    resource_budget = @{ max_network_requests = 100 }
    data_handling_policy = @{ classification = "INTERNAL"; retention_days = 7; export_allowed = $false }
}
$constraintMission = $missionPayload.Clone()
$constraintMission["idempotency_key"] = "stage318-budget-mission-$token"
Expect-ValidationFailure "$MissionBaseUrl/api/missions/validate" @{ mission = $constraintMission; scope_contract = $constraintBad } "CONSTRAINTS" "Constraint violation"

Write-Host "`n[9] Deterministic validation + final safety boundary"
$validation2 = Post-Json "$MissionBaseUrl/api/missions/validate" $draft
if ($validation2.mission_request_sha256 -ne $validation.mission_request_sha256) { Fail "Mission validation fingerprint is not deterministic" }
if ($validation2.scope_contract_request_sha256 -ne $validation.scope_contract_request_sha256) { Fail "Scope validation fingerprint is not deterministic" }
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($finalHealth.dispatch_enabled -ne $false -or $finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution authority changed" }
Pass "Validation is deterministic; Governance/target authority boundary remains unchanged"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.8 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "MissionId          : $missionId"
Write-Host "Mission Draft SHA256: $($validation.mission_request_sha256)"
Write-Host "Scope Draft SHA256  : $($validation.scope_contract_request_sha256)"
Write-Host "=============================================================================="
exit 0
