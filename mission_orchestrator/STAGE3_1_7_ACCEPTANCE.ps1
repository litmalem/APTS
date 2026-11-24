param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.1.7 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Post-Json([string]$Uri, $Body) {
    $json = $Body | ConvertTo-Json -Depth 30 -Compress
    return Invoke-RestMethod -Method Post -Uri $Uri -ContentType "application/json" -Body $json
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.7 - Mission Persistence & Repository Model Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[1] Full regression"
$pytestOutput = & python -m pytest -q 2>&1
$pytestOutput | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { Fail "Regression suite failed" }
if (($pytestOutput -join "`n") -notmatch "82 passed") { Fail "Expected current regression result '82 passed'" }
Pass "Stage 3.1.1 through 3.1.7 regression"

Write-Host "`n[2] Stage-3.1.7 health / authority boundary"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator health unavailable: $($_.Exception.Message)"
}
if ($health.control_version -ne "stage3.1.7-mission-persistence-repository-model") { Fail "Unexpected control_version: $($health.control_version)" }
if ($health.mission_repository_schema_version -ne "apts-mission-repository-v1") { Fail "Repository schema version mismatch" }
if ($health.mission_persistence_manifest_schema_version -ne "apts-mission-persistence-manifest-v1") { Fail "Persistence manifest schema version mismatch" }
if ([int]$health.mission_repository_migration_level -ne 7) { Fail "Repository migration level must be 7" }
if ($health.mission_repository_model -ne "NORMALIZED_DURABLE_WITH_APPEND_ONLY_LEDGERS_AND_MUTABLE_HEADS") { Fail "Repository storage model mismatch" }
if ($health.mission_repository_source_of_truth -ne "MISSION_ORCHESTRATOR_DATABASE") { Fail "Repository source-of-truth contract mismatch" }
if ($health.mission_repository_recovery_mode -ne "DURABLE_RECONSTRUCTION_NO_IN_MEMORY_SOURCE_OF_TRUTH") { Fail "Repository recovery mode mismatch" }
if ($health.mission_repository_read_model_enabled -ne $true) { Fail "Repository read model is not enabled" }
if ($health.dispatch_enabled -ne $false -or $health.target_action_dispatch_enabled -ne $false -or $health.target_actuation -ne $false) {
    Fail "Stage 3.1.7 must not enable target execution authority"
}
Pass "Repository contract active; target execution boundary preserved"

$token = (Get-Date -Format "yyyyMMddHHmmss") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))

Write-Host "`n[3] Create canonical mission"
$missionPayload = @{
    idempotency_key = "stage317-mission-$token"
    source_system = "STAGE317_ACCEPTANCE"
    created_by = "stage3.1.7-acceptance"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{ type = "SECURITY_VALIDATION"; target_ref = "repository-acceptance-lab" }
    success_criteria = @(@{ metric = "repository_integrity"; expected = $true })
    budgets = @{ time_seconds = 1800 }
    required_subsystems = @("CTI")
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.7" }
}
try {
    $created = Post-Json "$MissionBaseUrl/api/missions" $missionPayload
} catch {
    Fail "Mission creation failed: $($_.Exception.Message)"
}
$missionId = [string]$created.canonical_identity.mission_id
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Unexpected mission identity: $missionId" }
Pass "Mission created: $missionId"

Write-Host "`n[4] Initial durable repository reconstruction"
$repo1 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ($repo1.integrity_status -ne "PASS") { Fail "Initial repository integrity did not PASS" }
if ($repo1.repository.schema_version -ne "apts-mission-repository-v1") { Fail "Repository schema mismatch on mission read" }
if ([int]$repo1.record_counts.global_missions -ne 1) { Fail "Expected one global_missions row" }
if ([int]$repo1.record_counts.mission_envelopes -ne 1) { Fail "Expected one mission_envelopes row" }
if ([int]$repo1.record_counts.mission_states -ne 1) { Fail "Expected one mission_states row" }
if ([int]$repo1.record_counts.mission_state_transitions -ne 0) { Fail "Fresh mission must have zero transition-ledger rows" }
if ($repo1.persistence_manifest.current_state.state -ne "CREATED" -or [int]$repo1.persistence_manifest.current_state.state_version -ne 1) { Fail "Fresh persisted state must be CREATED/v1" }
$hash1 = [string]$repo1.repository_sha256
if ($hash1.Length -ne 64) { Fail "repository_sha256 must be a SHA-256 hex digest" }
Pass "Initial repository reconstructed and hash-bound: $hash1"

Write-Host "`n[5] Durable state transition changes repository revision"
$transition = @{
    expected_state_version = 1
    to_state = "PIP_BOUND"
    actor = "stage3.1.7-acceptance"
    reason_code = "PERSISTENCE_ACCEPTANCE_PIP_BOUND"
    reason = "Stage 3.1.7 persistence revision proof"
    evidence_refs = @()
    metadata = @{ acceptance = "stage3.1.7" }
}
try {
    $transitionResult = Post-Json "$MissionBaseUrl/api/missions/$missionId/state/transitions" $transition
} catch {
    Fail "State transition failed: $($_.Exception.Message)"
}
$repo2 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
$hash2 = [string]$repo2.repository_sha256
if ($hash2 -eq $hash1) { Fail "Repository hash did not change after durable state mutation" }
if ([int]$repo2.record_counts.mission_state_transitions -ne 1) { Fail "Expected one durable state transition" }
if ($repo2.persistence_manifest.current_state.state -ne "PIP_BOUND" -or [int]$repo2.persistence_manifest.current_state.state_version -ne 2) { Fail "Persisted current state is not PIP_BOUND/v2" }
Pass "State ledger + current projection are persistently reconstructable"

Write-Host "`n[6] Durable Scope/RoE/Constraint version store + head"
$startAt = (Get-Date).ToUniversalTime().AddMinutes(-5).ToString("yyyy-MM-ddTHH:mm:ssZ")
$endAt = (Get-Date).ToUniversalTime().AddHours(4).ToString("yyyy-MM-ddTHH:mm:ssZ")
$scopePayload = @{
    expected_contract_version = 0
    idempotency_key = "stage317-scope-$token"
    actor = "stage3.1.7-acceptance"
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
    reason = "Stage 3.1.7 durable scope"
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.7" }
}
try {
    $scopeResult = Post-Json "$MissionBaseUrl/api/missions/$missionId/scope-contract" $scopePayload
} catch {
    Fail "Scope contract persistence failed: $($_.Exception.Message)"
}
$repo3 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
$hash3 = [string]$repo3.repository_sha256
if ($hash3 -eq $hash2) { Fail "Repository hash did not change after durable Scope mutation" }
if ([int]$repo3.record_counts.mission_scope_contract_heads -ne 1 -or [int]$repo3.record_counts.mission_scope_contract_versions -ne 1) { Fail "Scope head/version rows not reconstructed" }
if ([int]$repo3.persistence_manifest.scope_contract_store.head.current_version -ne 1) { Fail "Scope repository head is not v1" }
if ($repo3.persistence_manifest.scope_contract_store.head.current_snapshot_id -ne $scopeResult.snapshot_id) { Fail "Scope head does not point to current snapshot" }
Pass "Scope version store and mutable head are consistent"

Write-Host "`n[7] Deterministic repository hash on unchanged durable state"
$repo4 = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
if ([string]$repo4.repository_sha256 -ne $hash3) { Fail "Unchanged durable state produced a different repository hash" }
if ($repo4.integrity_status -ne "PASS") { Fail "Repeated reconstruction did not PASS integrity" }
Pass "Repeated reconstruction preserves repository_sha256"

Write-Host "`n[8] Focused durable restart/reconstruction proof"
$focused = & python -m pytest -q tests/test_stage3_1_7_mission_persistence_repository_model.py -k "new_service_instance_recovers_same_durable_repository_without_memory_clone" 2>&1
$focused | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) { Fail "Focused durable restart/reconstruction test failed" }
if (($focused -join "`n") -notmatch "1 passed") { Fail "Focused restart proof did not report 1 passed" }
Pass "Independent service/repository reconstruction from durable DB"

Write-Host "`n[9] Final repository integrity / safety boundary"
$finalRepo = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/repository"
$failedChecks = @($finalRepo.integrity_checks | Where-Object { $_.status -ne "PASS" })
if ($failedChecks.Count -ne 0) { Fail "One or more repository integrity checks failed" }
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority boundary changed" }
if ($finalHealth.dispatch_enabled -ne $false -or $finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Target execution authority changed" }
Pass "Persistence remains infrastructure; Governance/target authority boundary preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.7 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "MissionId        : $missionId"
Write-Host "Repository SHA256: $($finalRepo.repository_sha256)"
Write-Host "=============================================================================="
exit 0
