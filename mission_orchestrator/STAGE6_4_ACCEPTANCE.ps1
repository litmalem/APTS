param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790",
    [string]$ExecutionUrl = "http://127.0.0.1:8791",
    [string]$GovernanceUrl = "",
    [string]$LiveInvocationId = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $GovernanceUrl) {
    $GovernanceUrl = $env:APTS_EXECUTION_GOVERNANCE_URL
    if (-not $GovernanceUrl) { $GovernanceUrl = $env:MISSION_GOVERNANCE_BASE_URL }
    if (-not $GovernanceUrl) { $GovernanceUrl = "http://127.0.0.1:8770" }
}
$ExpectedControl = "stage6.4-authorized-tool-adapters-sandboxing"
$ExpectedInventory = 2469
$ExpectedFocused = 129
function Assert-RejectedPost([string]$Uri,[string]$Body,[int]$Code) {
    $rejected = $false
    try { Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $Body -UseBasicParsing -TimeoutSec 15 | Out-Null }
    catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq $Code) { $rejected=$true } else { throw }
    }
    if (-not $rejected) { throw "Expected HTTP ${Code}: $Uri" }
}
function Verify-RemoteJson([string]$RawJson,[string]$Member,[string]$Verifier) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage64-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($path,$RawJson,(New-Object System.Text.UTF8Encoding($false)))
        python -c "import json,sys; from execution_subsystem import adapter_contract as c; value=json.load(open(sys.argv[1],encoding='utf-8-sig'))[sys.argv[2]]; sys.exit(0 if getattr(c,sys.argv[3])(value) else 1)" $path $Member $Verifier
        if ($LASTEXITCODE -ne 0) { throw "Remote $Verifier failed exact verification" }
    } finally { if (Test-Path $path) { Remove-Item $path -Force } }
}
Write-Host "=============================================================================="
Write-Host "Stage 6.4 - Authorized Tool Adapters & Sandboxing"
Write-Host "=============================================================================="
Write-Host "`n[0] Mission / Pentest / authoritative GSS protocol preflight"
$mission=Invoke-RestMethod "$MissionUrl/health" -TimeoutSec 15
if ($mission.control_version -ne "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate" -or [int]$mission.mission_repository_migration_level -ne 53) { throw "Mission control / migration 53 mismatch" }
$pentest=Invoke-RestMethod "$PentestUrl/health" -TimeoutSec 15
if ($pentest.control_version -ne "stage5.10-agentic-pentest-acceptance-regression-gate" -or [int]$pentest.pentest_repository_migration_level -ne 16) { throw "Pentest Stage 5.10 / migration 16 mismatch" }
$gss=Invoke-RestMethod "$GovernanceUrl/health" -TimeoutSec 15
if ($gss.status -ne "ok" -or $gss.component_id -ne "GOV-PLANE" -or $gss.execution_revalidation_schema_version -ne "apts-gss-execution-revalidation-v1") { throw "GSS protocol unavailable. Install aptsGSS Stage 6.4 patch and restart GSS." }
if (($gss.execution_revalidation_checks -join ",") -ne "SCOPE,ROE,POLICY,RISK,EXPIRY,REVOCATION,TARGET,TECHNIQUE") { throw "GSS checks mismatch" }
Write-Host "[PASS] Mission 53 / Pentest 16 / GOV-PLANE execution attestation"
Write-Host "`n[1] Stage 6.4 runtime / migration / adapter boundary"
$web=Invoke-WebRequest "$ExecutionUrl/health" -UseBasicParsing -TimeoutSec 15
$health=$web.Content | ConvertFrom-Json
if ($web.Headers["Server"] -notmatch "APTSExecutionSubsystem/6\.4" -or $health.control_version -ne $ExpectedControl -or $health.status -ne "ok") { throw "Stage 6.4 runtime is not active" }
if ([int]$health.execution_repository_migration_level -ne 4 -or [int]$health.registered_adapter_count -ne 5 -or $health.next_stage -ne "6.5") { throw "Stage 6.4 migration / registry / next-stage mismatch" }
if ($health.authorized_tool_adapters_enabled -ne $true -or $health.target_dispatch_enabled -ne $true -or $health.sandbox_ready_required_before_target_io -ne $true) { throw "Authorized adapter path inactive" }
if ($health.sandbox_profile -ne "FIXED_WORKER_BROKER_V1" -or $health.worker_raw_target_access -ne $false -or $health.arbitrary_code_supported -ne $false) { throw "Sandbox boundary mismatch" }
if ($health.specialist_raw_target_access -ne $false -or $health.authorization_minted_locally -ne $false -or $health.mission_source_read_only -ne $true -or $health.pentest_source_read_only -ne $true) { throw "Authority or source isolation violation" }
if ($health.gateway_admission_is_dispatch_authority -ne $false -or $health.fresh_revalidation_required_before_target_dispatch -ne $true -or $health.runtime_self_certification -ne $false) { throw "Dispatch freshness mismatch" }
Write-Host "[PASS] Five fixed adapters; fresh GSS before target I/O; read-only upstream sources"
Write-Host "`n[2] Exact Stage 6.3 predecessor / Stage 6.4 contract"
$contractWeb=Invoke-WebRequest "$ExecutionUrl/api/execution/tool-adapters-contract" -UseBasicParsing -TimeoutSec 15
$contract=$contractWeb.Content | ConvertFrom-Json
$predecessor=Invoke-RestMethod "$ExecutionUrl/api/execution/execution-gateway-contract" -TimeoutSec 15
if ($contract.contract.predecessor.control -ne "stage6.3-controlled-execution-gateway" -or $contract.contract.predecessor.contract_sha256 -ne $predecessor.contract.integrity.canonical_sha256 -or $contract.contract.integrity.canonical_sha256 -ne $health.stage6_4_contract_sha256) { throw "Contract / predecessor binding mismatch" }
Verify-RemoteJson $contractWeb.Content "contract" "verify_adapter_contract"
Write-Host "[PASS] Exact SHA-bound adapter and sandbox contract"
Write-Host "`n[3] Caller ALLOW / command / raw execution rejection"
Assert-RejectedPost "$ExecutionUrl/api/execution/gateway/tool-invocations" '{"decision":"ALLOW"}' 400
Assert-RejectedPost "$ExecutionUrl/api/execution/gateway/tool-invocations" '{"command":"run"}' 400
foreach ($route in @("dispatches","results","tool-invocations")) { Assert-RejectedPost "$ExecutionUrl/api/execution/$route" '{}' 409 }
Assert-RejectedPost "$PentestUrl/api/execution/dispatches" '{}' 409
Write-Host "[PASS] No specialist command / tool / target bypass"
Write-Host "`n[4] Native sandbox proof (synthetic bytes, no target action)"
python run\execution_sandbox_probe.py
if ($LASTEXITCODE -ne 0) { throw "Native sandbox unavailable; adapter execution must remain fail-closed" }
Write-Host "[PASS] Native resource limits and fixed worker readiness"
Write-Host "`n[5] Compilation / exact test inventory"
python -m compileall -q mission_orchestrator pentest_subsystem execution_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Compilation failed" }
$collection=python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0 -or ($collection | Select-Object -Last 1) -notmatch "^$ExpectedInventory tests collected") { throw "Expected $ExpectedInventory tests" }
Write-Host "[PASS] $ExpectedInventory tests collected"
Write-Host "`n[6] Focused adapters / sandbox / quotas / concurrency / crash / real loopback proof"
python -m pytest -q tests/test_stage6_4_authorized_tool_adapters_sandboxing.py
if ($LASTEXITCODE -ne 0) { throw "Stage 6.4 focused tests failed" }
Write-Host "[PASS] $ExpectedFocused focused tests"
Write-Host "`n[7] Stage 5.9 -> 5.10 -> 6.1 -> 6.2 -> 6.3 -> 6.4 continuity"
python -m pytest -q tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py tests/test_stage6_1_canonical_execution_request_contract.py tests/test_stage6_2_authoritative_execution_authorization.py tests/test_stage6_3_controlled_execution_gateway.py tests/test_stage6_4_authorized_tool_adapters_sandboxing.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5/6 continuity failed" }
Write-Host "`n[8] Full historical regression - FINAL SOURCE PASS / FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }
if ($LiveInvocationId) {
    Write-Host "`n[9] Existing live invocation audit (read-only)"
    $liveWeb=Invoke-WebRequest "$ExecutionUrl/api/execution/gateway/tool-invocations/$LiveInvocationId" -UseBasicParsing -TimeoutSec 15
    $live=$liveWeb.Content | ConvertFrom-Json
    Verify-RemoteJson $liveWeb.Content "record" "verify_adapter_claim"
    if ($live.result) { Verify-RemoteJson $liveWeb.Content "result" "verify_adapter_result" }
    if ($live.execution_authorized -ne $false -or $live.usable_for_dispatch -ne $false -or $live.target_network_io_performed -ne $false) { throw "Historical audit cannot authorize or perform target I/O" }
    Write-Host "[PASS] Captured live invocation audit; historical read performs no target action"
} else {
    Write-Host "Live user-mission execution: NOT EXERCISED. Tests use isolated sources, GSS authority, and loopback targets."
}
Write-Host "`nSTAGE 6.4 ACCEPTANCE: PASS"
Write-Host "Scope: runtime activation + native sandbox + $ExpectedInventory regression tests + GSS protocol health"
Write-Host "Next: Stage 6.5 - Execution Runtime Control"
