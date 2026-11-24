param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790",
    [string]$ExecutionUrl = "http://127.0.0.1:8791",
    [string]$GovernanceUrl = "",
    [string]$LiveAttemptId = "",
    [int]$RegressionWorkers = 4
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $GovernanceUrl) {
    $GovernanceUrl = $env:APTS_EXECUTION_GOVERNANCE_URL
    if (-not $GovernanceUrl) { $GovernanceUrl = $env:MISSION_GOVERNANCE_BASE_URL }
    if (-not $GovernanceUrl) { $GovernanceUrl = "http://127.0.0.1:8770" }
}
$ExpectedControl = "stage6.6-artifact-evidence-capture"
$ExpectedInventory = 2603
$ExpectedFocused = 64
function Assert-RejectedPost([string]$Uri, [string]$Body, [int]$Code) {
    $rejected = $false
    try { Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $Body -UseBasicParsing -TimeoutSec 15 | Out-Null }
    catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq $Code) { $rejected = $true } else { throw }
    }
    if (-not $rejected) { throw "Expected HTTP ${Code}: $Uri" }
}
function Verify-RemoteJson([string]$RawJson, [string]$Member, [string]$Verifier) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage65-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($path, $RawJson, (New-Object System.Text.UTF8Encoding($false)))
        python -c "import json,sys; from execution_subsystem import evidence_contract as c; value=json.load(open(sys.argv[1],encoding='utf-8-sig'))[sys.argv[2]]; sys.exit(0 if getattr(c,sys.argv[3])(value) else 1)" $path $Member $Verifier
        if ($LASTEXITCODE -ne 0) { throw "Remote $Verifier failed exact verification" }
    } finally { if (Test-Path $path) { Remove-Item $path -Force } }
}
function Verify-RemoteAttempt([string]$RawJson) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage65-audit-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($path, $RawJson, (New-Object System.Text.UTF8Encoding($false)))
        $code = @'
import json,sys
from execution_subsystem.runtime_contract import verify_attempt,verify_event
x=json.load(open(sys.argv[1],encoding='utf-8-sig')); events=x['events']
assert verify_attempt(x['record']) and events and all(verify_event(e) for e in events)
assert [e['event_sequence'] for e in events]==list(range(1,len(events)+1))
assert [e['previous_event_sha256'] for e in events]==[None]+[e['integrity']['canonical_sha256'] for e in events[:-1]]
assert [e['state_before'] for e in events]==[None]+[e['state_after'] for e in events[:-1]]
assert all(e['attempt_id']==x['attempt_id'] and e['attempt_sha256']==x['record']['integrity']['canonical_sha256'] for e in events)
assert x['head_sha256']==events[-1]['integrity']['canonical_sha256'] and x['state']==events[-1]['state_after']
assert x['execution_authorized'] is False and x['usable_for_dispatch'] is False and x['target_network_io_performed'] is False
'@
        python -c $code $path
        if ($LASTEXITCODE -ne 0) { throw "Live attempt audit failed exact verification" }
    } finally { if (Test-Path $path) { Remove-Item $path -Force } }
}
Write-Host "=============================================================================="
Write-Host "Stage 6.6 - Artifact & Evidence Capture"
Write-Host "=============================================================================="
Write-Host "`n[0] Mission / Pentest / authoritative GSS preflight"
$mission = Invoke-RestMethod "$MissionUrl/health" -TimeoutSec 15
if ($mission.control_version -ne "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate" -or [int]$mission.mission_repository_migration_level -ne 53) { throw "Mission / migration 53 mismatch" }
$pentest = Invoke-RestMethod "$PentestUrl/health" -TimeoutSec 15
if ($pentest.control_version -ne "stage5.10-agentic-pentest-acceptance-regression-gate" -or [int]$pentest.pentest_repository_migration_level -ne 16) { throw "Pentest / migration 16 mismatch" }
$gss = Invoke-RestMethod "$GovernanceUrl/health" -TimeoutSec 15
if ($gss.status -ne "ok" -or $gss.component_id -ne "GOV-PLANE" -or $gss.execution_revalidation_schema_version -ne "apts-gss-execution-revalidation-v1") { throw "GSS Stage 6.4 execution attestation protocol unavailable" }
if (($gss.execution_revalidation_checks -join ",") -ne "SCOPE,ROE,POLICY,RISK,EXPIRY,REVOCATION,TARGET,TECHNIQUE") { throw "GSS checks mismatch" }
Write-Host "[PASS] Mission 53 / Pentest 16 / external GOV-PLANE"
Write-Host "`n[1] Runtime owner / migration / isolation"
$web = Invoke-WebRequest "$ExecutionUrl/health" -UseBasicParsing -TimeoutSec 15
$health = $web.Content | ConvertFrom-Json
if ($web.Headers["Server"] -notmatch "APTSExecutionSubsystem/6\.6" -or $health.control_version -ne $ExpectedControl -or $health.status -ne "ok") { throw "Stage 6.6 runtime inactive" }
if ([int]$health.execution_repository_migration_level -ne 6 -or $health.next_stage -ne "6.7" -or [int]$health.registered_adapter_count -ne 5) { throw "Stage 6.6 migration / registry mismatch" }
if ($health.execution_runtime_control_enabled -ne $true -or $health.runtime_owner_exclusive -ne $true -or [int]$health.runtime_persistence_failures -ne 0) { throw "Runtime owner or persistence degraded" }
if ($health.automatic_retry_enabled -ne $false -or $health.caller_heartbeat_supported -ne $false -or $health.legacy_adapter_synchronous_dispatch_enabled -ne $false) { throw "Runtime control bypass" }
if ($health.specialist_raw_target_access -ne $false -or $health.authorization_minted_locally -ne $false -or $health.worker_raw_target_access -ne $false -or $health.arbitrary_code_supported -ne $false) { throw "Execution isolation violation" }
if ($health.mission_source_read_only -ne $true -or $health.pentest_source_read_only -ne $true -or $health.runtime_self_certification -ne $false) { throw "Upstream authority boundary mismatch" }
Write-Host "[PASS] Exclusive runtime owner; durable lifecycle; read-only upstream sources"
Write-Host "`n[2] Exact Stage 6.5 predecessor / Stage 6.6 contract"
$contractWeb = Invoke-WebRequest "$ExecutionUrl/api/execution/artifact-evidence-contract" -UseBasicParsing -TimeoutSec 15
$contract = $contractWeb.Content | ConvertFrom-Json
$predecessor = Invoke-RestMethod "$ExecutionUrl/api/execution/execution-runtime-contract" -TimeoutSec 15
if ($contract.contract.predecessor.control -ne "stage6.5-execution-runtime-control" -or $contract.contract.predecessor.contract_sha256 -ne $predecessor.contract.integrity.canonical_sha256 -or $contract.contract.integrity.canonical_sha256 -ne $health.stage6_6_contract_sha256) { throw "Runtime predecessor hash mismatch" }
Verify-RemoteJson $contractWeb.Content "contract" "verify_evidence_contract"
Write-Host "[PASS] Exact SHA-bound evidence capture contract"
Write-Host "`n[3] Caller ALLOW / command / fabricated heartbeat, result, and evidence rejection"
Assert-RejectedPost "$ExecutionUrl/api/execution/runtime/attempts" '{"decision":"ALLOW"}' 400
Assert-RejectedPost "$ExecutionUrl/api/execution/runtime/attempts" '{"command":"run"}' 400
foreach ($route in @("heartbeats","results","transitions")) { Assert-RejectedPost "$ExecutionUrl/api/execution/runtime/$route" '{}' 409 }
foreach ($route in @("dispatches","results","tool-invocations")) { Assert-RejectedPost "$ExecutionUrl/api/execution/$route" '{}' 409 }
Assert-RejectedPost "$PentestUrl/api/execution/dispatches" '{}' 409
foreach ($route in @("evidence", "artifacts", "artifacts/upload")) { Assert-RejectedPost "$ExecutionUrl/api/execution/$route" '{"decision":"ALLOW","stdout":"FAKE"}' 409 }
if ($health.artifact_evidence_capture_enabled -ne $true -or $health.terminal_evidence_atomic -ne $true -or $health.artifact_repository_append_only -ne $true -or $health.caller_evidence_upload_supported -ne $false -or $health.evidence_capture_additional_target_io -ne $false) { throw "Evidence ownership or atomicity boundary mismatch" }
Write-Host "[PASS] No caller state, tool authority, or evidence upload"
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
Write-Host "`n[6] Capture / blob hashes / redaction / atomicity / quotas / real crash recovery"
python -m pytest -q tests/test_stage6_6_artifact_evidence_capture.py
if ($LASTEXITCODE -ne 0) { throw "Stage 6.6 focused tests failed" }
Write-Host "[PASS] $ExpectedFocused focused tests"
Write-Host "`n[7] Stage 5.9 -> 6.6 continuity"
python -m pytest -q tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py tests/test_stage6_1_canonical_execution_request_contract.py tests/test_stage6_2_authoritative_execution_authorization.py tests/test_stage6_3_controlled_execution_gateway.py tests/test_stage6_4_authorized_tool_adapters_sandboxing.py tests/test_stage6_5_execution_runtime_control.py tests/test_stage6_6_artifact_evidence_capture.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5/6 continuity failed" }
Write-Host "`n[8] Full canonical regression - exact per-test JUnit coverage"
python run\stage6_6_regression.py --workers $RegressionWorkers --expected-tests $ExpectedInventory --output evidence/stage6_6/local_acceptance
if ($LASTEXITCODE -ne 0) { throw "Full canonical regression failed" }
if ($LiveAttemptId) {
    Write-Host "`n[9] Existing live attempt audit (read-only)"
    $liveWeb = Invoke-WebRequest "$ExecutionUrl/api/execution/runtime/attempts/$LiveAttemptId" -UseBasicParsing -TimeoutSec 15
    Verify-RemoteAttempt $liveWeb.Content
    $captureWeb = Invoke-WebRequest "$ExecutionUrl/api/execution/evidence/attempts/$LiveAttemptId" -UseBasicParsing -TimeoutSec 15
    $capture = $captureWeb.Content | ConvertFrom-Json
    $artifactResponses = @()
    foreach ($artifact in $capture.artifacts) {
        $artifactResponses += Invoke-RestMethod "$ExecutionUrl/api/execution/artifacts/$($artifact.artifact_id)?attempt_id=$LiveAttemptId" -TimeoutSec 15
    }
    $capturePath = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage66-capture-" + [guid]::NewGuid().ToString() + ".json")
    $artifactPath = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage66-artifacts-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($capturePath, $captureWeb.Content, (New-Object System.Text.UTF8Encoding($false)))
        $artifactJson = ConvertTo-Json -InputObject @($artifactResponses) -Depth 100
        [System.IO.File]::WriteAllText($artifactPath, $artifactJson, (New-Object System.Text.UTF8Encoding($false)))
        python run\stage6_6_audit.py --capture-file $capturePath --artifacts-file $artifactPath
        if ($LASTEXITCODE -ne 0) { throw "Live evidence / artifact byte audit failed" }
    } finally {
        if (Test-Path $capturePath) { Remove-Item $capturePath -Force }
        if (Test-Path $artifactPath) { Remove-Item $artifactPath -Force }
    }
    Write-Host "[PASS] Existing attempt identity / event chain / evidence / artifact bytes"
} else {
    Write-Host "Live user-mission execution: NOT EXERCISED. Proof uses isolated schemas, authority HTTP, native workers, and loopback targets."
}
Write-Host "`nSTAGE 6.6 ACCEPTANCE: PASS"
Write-Host "Next: Stage 6.7 - VEP Construction & Integrity"
