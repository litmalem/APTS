param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790",
    [string]$ExecutionUrl = "http://127.0.0.1:8791",
    [string]$GovernanceUrl = "",
    [string]$LiveAttemptId = "",
    [string]$LiveVepId = "",
    [string]$LivePostActionId = "",
    [int]$RegressionWorkers = 4
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if ($LiveVepId -and -not $LiveAttemptId) { throw "LiveVepId requires the exact LiveAttemptId" }
if ($LivePostActionId -and -not $LiveAttemptId) { throw "LivePostActionId requires the exact LiveAttemptId" }
if (-not $GovernanceUrl) {
    $GovernanceUrl = $env:APTS_EXECUTION_GOVERNANCE_URL
    if (-not $GovernanceUrl) { $GovernanceUrl = $env:MISSION_GOVERNANCE_BASE_URL }
    if (-not $GovernanceUrl) { $GovernanceUrl = "http://127.0.0.1:8770" }
}
$ExpectedControl = "stage6.8-cleanup-rollback-post-action-verification"
$ExpectedInventory = 2793
$ExpectedFocused = 92
function Assert-RejectedPost([string]$Uri, [string]$Body, [int]$Code) {
    $rejected = $false
    try { Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $Body -UseBasicParsing -TimeoutSec 15 | Out-Null }
    catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq $Code) { $rejected = $true } else { throw }
    }
    if (-not $rejected) { throw "Expected HTTP ${Code}: $Uri" }
}
function Verify-RemoteContract([string]$RawJson, [string]$Module, [string]$Verifier) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage68-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($path, $RawJson, (New-Object System.Text.UTF8Encoding($false)))
        python -c "import importlib,json,sys; c=importlib.import_module('execution_subsystem.'+sys.argv[2]); value=json.load(open(sys.argv[1],encoding='utf-8-sig'))['contract']; sys.exit(0 if getattr(c,sys.argv[3])(value) else 1)" $path $Module $Verifier
        if ($LASTEXITCODE -ne 0) { throw "Remote $Verifier failed exact verification" }
    } finally { if (Test-Path $path) { Remove-Item $path -Force } }
}
Write-Host "=============================================================================="
Write-Host "Stage 6.8 - Cleanup, Rollback & Post-Action Verification"
Write-Host "=============================================================================="
Write-Host "`n[0] Mission / Pentest / authoritative GSS preflight"
$mission = Invoke-RestMethod "$MissionUrl/health" -TimeoutSec 15
if ($mission.control_version -ne "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate" -or [int]$mission.mission_repository_migration_level -ne 53) { throw "Mission / migration 53 mismatch" }
$pentest = Invoke-RestMethod "$PentestUrl/health" -TimeoutSec 15
if ($pentest.control_version -ne "stage5.10-agentic-pentest-acceptance-regression-gate" -or [int]$pentest.pentest_repository_migration_level -ne 16) { throw "Pentest / migration 16 mismatch" }
$gss = Invoke-RestMethod "$GovernanceUrl/health" -TimeoutSec 15
if ($gss.status -ne "ok" -or $gss.component_id -ne "GOV-PLANE" -or $gss.execution_revalidation_schema_version -ne "apts-gss-execution-revalidation-v1") { throw "GSS execution attestation protocol unavailable" }
if (($gss.execution_revalidation_checks -join ",") -ne "SCOPE,ROE,POLICY,RISK,EXPIRY,REVOCATION,TARGET,TECHNIQUE") { throw "GSS checks mismatch" }
Write-Host "[PASS] Mission 53 / Pentest 16 / external GOV-PLANE"
Write-Host "`n[1] Runtime owner / migration / isolation"
$web = Invoke-WebRequest "$ExecutionUrl/health" -UseBasicParsing -TimeoutSec 15
$health = $web.Content | ConvertFrom-Json
if ($web.Headers["Server"] -notmatch "APTSExecutionSubsystem/6\.8" -or $health.control_version -ne $ExpectedControl -or $health.status -ne "ok") { throw "Stage 6.8 runtime inactive" }
if ([int]$health.execution_repository_migration_level -ne 8 -or $health.next_stage -ne "6.9" -or [int]$health.registered_adapter_count -ne 5) { throw "Stage 6.8 migration / registry mismatch" }
if ($health.execution_runtime_control_enabled -ne $true -or $health.runtime_owner_exclusive -ne $true -or [int]$health.runtime_persistence_failures -ne 0) { throw "Runtime owner or persistence degraded" }
if ($health.runtime_completion_fence_enabled -ne $true -or [double]$health.runtime_authorization_quiescence_seconds -ne 2.0) { throw "Runtime completion fence inactive; restart Execution after installing Hotfix 1" }
if ($health.automatic_retry_enabled -ne $false -or $health.caller_heartbeat_supported -ne $false -or $health.legacy_adapter_synchronous_dispatch_enabled -ne $false) { throw "Runtime control bypass" }
if ($health.specialist_raw_target_access -ne $false -or $health.authorization_minted_locally -ne $false -or $health.worker_raw_target_access -ne $false -or $health.arbitrary_code_supported -ne $false) { throw "Execution isolation violation" }
if ($health.mission_source_read_only -ne $true -or $health.pentest_source_read_only -ne $true -or $health.runtime_self_certification -ne $false) { throw "Upstream authority boundary mismatch" }
Write-Host "[PASS] Exclusive runtime owner; durable lifecycle; read-only upstream sources"
Write-Host "`n[2] Exact Stage 6.7 predecessor / Stage 6.8 cleanup contract"
$contractWeb = Invoke-WebRequest "$ExecutionUrl/api/execution/cleanup-rollback-post-action-verification-contract" -UseBasicParsing -TimeoutSec 15
$contract = $contractWeb.Content | ConvertFrom-Json
$predecessorWeb = Invoke-WebRequest "$ExecutionUrl/api/execution/vep-construction-integrity-contract" -UseBasicParsing -TimeoutSec 15
$predecessor = $predecessorWeb.Content | ConvertFrom-Json
if ($contract.contract.predecessor.control -ne "stage6.7-vep-construction-integrity" -or $contract.contract.predecessor.contract_sha256 -ne $predecessor.contract.integrity.canonical_sha256 -or $contract.contract.integrity.canonical_sha256 -ne $health.stage6_8_contract_sha256) { throw "VEP predecessor hash mismatch" }
Verify-RemoteContract $contractWeb.Content "cleanup_contract" "verify_cleanup_contract"
Verify-RemoteContract $predecessorWeb.Content "vep_contract" "verify_vep_contract"
if ($health.cleanup_workflow_enabled -ne $true -or $health.local_resource_rollback_enabled -ne $true -or $health.durable_local_credential_revocation_enabled -ne $true -or $health.post_action_verification_enabled -ne $true) { throw "Stage 6.8 cleanup controls unavailable" }
if ($health.post_action_report_append_only -ne $true -or $health.post_action_additional_target_io -ne $false -or $health.caller_cleanup_attestation_supported -ne $false -or $health.target_rollback_supported -ne $false -or $health.issuer_credential_revocation_supported -ne $false -or $health.cleanup_legacy_backfill_supported -ne $false) { throw "Stage 6.8 cleanup authority or evidence boundary mismatch" }
Write-Host "[PASS] Exact SHA-bound cleanup contract; local closure and evidence limits"
Write-Host "`n[3] Caller ALLOW / command / fabricated VEP / evidence rejection"
Assert-RejectedPost "$ExecutionUrl/api/execution/runtime/attempts" '{"decision":"ALLOW"}' 400
Assert-RejectedPost "$ExecutionUrl/api/execution/veps" '{"decision":"ALLOW","finding_id":"FAKE"}' 400
Assert-RejectedPost "$ExecutionUrl/api/execution/veps" '{"command":"run","evidence":"FAKE"}' 400
foreach ($route in @("heartbeats","results","transitions")) { Assert-RejectedPost "$ExecutionUrl/api/execution/runtime/$route" '{}' 409 }
foreach ($route in @("dispatches","results","tool-invocations","evidence","artifacts/upload","veps/upload")) { Assert-RejectedPost "$ExecutionUrl/api/execution/$route" '{"decision":"ALLOW","stdout":"FAKE"}' 409 }
Assert-RejectedPost "$PentestUrl/api/execution/dispatches" '{}' 409
if ($health.artifact_evidence_capture_enabled -ne $true -or $health.terminal_evidence_atomic -ne $true -or $health.caller_evidence_upload_supported -ne $false) { throw "Evidence ownership or atomicity boundary mismatch" }
if ($health.vep_construction_enabled -ne $true -or $health.vep_repository_append_only -ne $true -or $health.vep_terminal_capture_required -ne $true -or $health.vep_offline_export_enabled -ne $true) { throw "VEP construction or persistence boundary mismatch" }
if ($health.vep_caller_summary_supported -ne $false -or $health.vep_construction_additional_target_io -ne $false -or $health.vep_automatic_vulnerability_confirmation -ne $false -or $health.vep_pentest_writes -ne $false -or $health.vep_cleanup_verification_enabled -ne $true -or $health.vep_cti_feedback_enabled -ne $false) { throw "VEP authority or evidence semantics violation" }
Assert-RejectedPost "$ExecutionUrl/api/execution/post-actions" '{"decision":"ALLOW","cleanup_verified":true}' 400
Assert-RejectedPost "$ExecutionUrl/api/execution/post-actions" '{"command":"remove","path":"FAKE"}' 400
foreach ($route in @("post-actions/upload","cleanup/rollback","cleanup/credentials/revoke")) { Assert-RejectedPost "$ExecutionUrl/api/execution/$route" '{}' 409 }
Write-Host "[PASS] Server-owned post-action workflow; no caller proof, paths or commands"
Write-Host "`n[4] Native sandbox (synthetic bytes; no target action)"
python run\execution_sandbox_probe.py
if ($LASTEXITCODE -ne 0) { throw "Native sandbox unavailable" }
Write-Host "[PASS] Native resource limits and fixed worker readiness"
Write-Host "`n[5] Compilation / exact canonical inventory"
python -m compileall -q mission_orchestrator pentest_subsystem execution_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Compilation failed" }
$collection = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0 -or ($collection | Select-Object -Last 1) -notmatch "^$ExpectedInventory tests collected") { throw "Expected $ExpectedInventory canonical tests" }
Write-Host "[PASS] $ExpectedInventory tests collected"
Write-Host "`n[6] Local cleanup / rollback / leases / closure / atomicity / real crash recovery"
python -m pytest -q tests/test_stage6_8_cleanup_rollback_post_action_verification.py tests/test_stage6_8_runtime_completion_fence.py
if ($LASTEXITCODE -ne 0) { throw "Stage 6.8 focused tests failed" }
Write-Host "[PASS] $ExpectedFocused focused tests"
Write-Host "`n[7] Stage 5.9 -> 6.8 continuity"
python -m pytest -q tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py tests/test_stage6_1_canonical_execution_request_contract.py tests/test_stage6_2_authoritative_execution_authorization.py tests/test_stage6_3_controlled_execution_gateway.py tests/test_stage6_4_authorized_tool_adapters_sandboxing.py tests/test_stage6_5_execution_runtime_control.py tests/test_stage6_6_artifact_evidence_capture.py tests/test_stage6_7_vep_construction_integrity.py tests/test_stage6_8_cleanup_rollback_post_action_verification.py tests/test_stage6_8_runtime_completion_fence.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5/6 continuity failed" }
Write-Host "`n[8] Full canonical regression - exact per-test JUnit coverage"
python run\stage6_8_regression.py --workers $RegressionWorkers --expected-tests $ExpectedInventory --output evidence/stage6_8/local_acceptance
if ($LASTEXITCODE -ne 0) { throw "Full canonical regression failed" }
if ($LiveAttemptId) {
    Write-Host "`n[9] Existing live terminal capture audit (read-only)"
    $captureWeb = Invoke-WebRequest "$ExecutionUrl/api/execution/evidence/attempts/$LiveAttemptId" -UseBasicParsing -TimeoutSec 15
    $capture = $captureWeb.Content | ConvertFrom-Json
    if ($capture.sealed -ne $true) { throw "Live audit requires an existing terminal Stage 6.6 capture" }
    $artifactResponses = @()
    foreach ($artifact in $capture.artifacts) {
        $artifactResponses += Invoke-RestMethod "$ExecutionUrl/api/execution/artifacts/$($artifact.artifact_id)?attempt_id=$LiveAttemptId" -TimeoutSec 15
    }
    $capturePath = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage68-capture-" + [guid]::NewGuid().ToString() + ".json")
    $artifactPath = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage68-artifacts-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($capturePath, $captureWeb.Content, (New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllText($artifactPath, (ConvertTo-Json -InputObject @($artifactResponses) -Depth 100), (New-Object System.Text.UTF8Encoding($false)))
        python run\stage6_6_audit.py --capture-file $capturePath --artifacts-file $artifactPath
        if ($LASTEXITCODE -ne 0) { throw "Live evidence audit failed" }
    } finally {
        if (Test-Path $capturePath) { Remove-Item $capturePath -Force }
        if (Test-Path $artifactPath) { Remove-Item $artifactPath -Force }
    }
}
if ($LiveVepId) {
    Write-Host "`n[10] Existing live VEP audit and offline byte verification (read-only)"
    $verified = Invoke-RestMethod "$ExecutionUrl/api/execution/veps/$LiveVepId/verify?attempt_id=$LiveAttemptId" -TimeoutSec 15
    if ($verified.status -ne "VERIFIED" -or $verified.execution_authorized -ne $false -or $verified.vulnerability_confirmed -ne $false) { throw "Live VEP verification failed" }
    $exportPath = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage68-export-" + [guid]::NewGuid().ToString() + ".json")
    try {
        Invoke-WebRequest "$ExecutionUrl/api/execution/veps/$LiveVepId/export?attempt_id=$LiveAttemptId" -UseBasicParsing -OutFile $exportPath -TimeoutSec 15
        python run\stage6_7_audit.py --export-file $exportPath
        if ($LASTEXITCODE -ne 0) { throw "Live VEP offline byte audit failed" }
    } finally { if (Test-Path $exportPath) { Remove-Item $exportPath -Force } }
    Write-Host "[PASS] Existing VEP / source snapshots / event chain / manifest / artifact bytes"
} else {
    Write-Host "Live user VEP: NOT EXERCISED. Proof uses isolated schemas, authority HTTP, native workers, and loopback targets."
}
if ($LivePostActionId) {
    Write-Host "`n[11] Existing live post-action report audit (read-only)"
    $verified = Invoke-RestMethod "$ExecutionUrl/api/execution/post-actions/$LivePostActionId/verify?attempt_id=$LiveAttemptId" -TimeoutSec 15
    if ($verified.verification_status -ne "VERIFIED_INTERNAL_LINEAGE" -or $verified.execution_authorized -ne $false -or $verified.target_state_verified -ne $false) { throw "Live post-action verification failed" }
    $exportPath = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage68-cleanup-" + [guid]::NewGuid().ToString() + ".json")
    try {
        Invoke-WebRequest "$ExecutionUrl/api/execution/post-actions/$LivePostActionId/export?attempt_id=$LiveAttemptId" -UseBasicParsing -OutFile $exportPath -TimeoutSec 15
        python run\stage6_8_audit.py --export-file $exportPath
        if ($LASTEXITCODE -ne 0) { throw "Live post-action offline audit failed" }
    } finally { if (Test-Path $exportPath) { Remove-Item $exportPath -Force } }
    Write-Host "[PASS] Existing post-action internal lineage; closure state: $($verified.status)"
}
Write-Host "`nSTAGE 6.8 ACCEPTANCE: PASS"
Write-Host "Next: Stage 6.9 - Closed-Loop CTI <-> Pentest Integration"
