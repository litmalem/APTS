param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790",
    [string]$ExecutionUrl = "http://127.0.0.1:8791",
    [string]$GovernanceUrl = "",
    [string]$LiveAuthorizationId = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $GovernanceUrl) {
    $GovernanceUrl = $env:APTS_EXECUTION_GOVERNANCE_URL
    if (-not $GovernanceUrl) { $GovernanceUrl = $env:MISSION_GOVERNANCE_BASE_URL }
    if (-not $GovernanceUrl) { $GovernanceUrl = "http://127.0.0.1:8770" }
}
$ExpectedControl = "stage6.2-authoritative-execution-authorization"
$ExpectedSchema = "apts-stage6.2-authoritative-execution-authorization-v1"
$ExpectedInventory = 2229
$ExpectedFocused = 111
$ExpectedChecks = @("SCOPE","ROE","POLICY","RISK","EXPIRY","REVOCATION","TARGET","TECHNIQUE")
function Assert-RejectedPost([string]$Uri,[string]$Body,[int]$Code) {
    $rejected = $false
    try {
        Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $Body -UseBasicParsing -TimeoutSec 15 | Out-Null
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq $Code) { $rejected=$true } else { throw }
    }
    if (-not $rejected) { throw "Expected HTTP ${Code}: $Uri" }
}
function Verify-RemoteJson([string]$RawJson,[string]$Member,[string]$Verifier) {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage62-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($path,$RawJson,(New-Object System.Text.UTF8Encoding($false)))
        python -c "import json,sys; from execution_subsystem import authorization_contract as c; value=json.load(open(sys.argv[1],encoding='utf-8-sig'))[sys.argv[2]]; sys.exit(0 if getattr(c,sys.argv[3])(value) else 1)" $path $Member $Verifier
        if ($LASTEXITCODE -ne 0) { throw "Remote $Verifier failed exact integrity verification" }
    } finally { if (Test-Path $path) { Remove-Item $path -Force } }
}
Write-Host "=============================================================================="
Write-Host "Stage 6.2 - Authoritative Execution Authorization"
Write-Host "=============================================================================="
Write-Host "`n[0] Current Mission / Pentest / Governance preflight"
$mission=Invoke-RestMethod "$MissionUrl/health" -TimeoutSec 15
if ($mission.control_version -ne "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate") { throw "Mission control mismatch" }
if ([int]$mission.mission_repository_migration_level -ne 53) { throw "Mission migration must remain 53" }
$pentest=Invoke-RestMethod "$PentestUrl/health" -TimeoutSec 15
if ($pentest.control_version -ne "stage5.10-agentic-pentest-acceptance-regression-gate" -or [int]$pentest.pentest_repository_migration_level -ne 16) { throw "Pentest Stage 5.10/migration 16 mismatch" }
$gss=Invoke-RestMethod "$GovernanceUrl/health" -TimeoutSec 15
if ($gss.status -ne "ok" -or $gss.component_id -ne "GOV-PLANE") { throw "Authoritative Governance health/identity mismatch" }
Write-Host "[PASS] Mission 53; Pentest 16; external GOV-PLANE reachable"
Write-Host "`n[1] Stage 6.2 runtime identity / atomic migration / boundaries"
$web=Invoke-WebRequest "$ExecutionUrl/health" -UseBasicParsing -TimeoutSec 15
$health=$web.Content | ConvertFrom-Json
if ($web.Headers["Server"] -notmatch "APTSExecutionSubsystem/6\.2" -or $health.control_version -ne $ExpectedControl -or $health.status -ne "ok") { throw "Stage 6.2 source is not active" }
if ([int]$health.execution_repository_migration_level -ne 2) { throw "Execution migration must be 2" }
if ([int]$health.pentest_repository_migration_level -ne 16 -or [int]$health.mission_repository_migration_level -ne 53) { throw "Upstream migration drift" }
if ($health.stage6_2_schema_version -ne $ExpectedSchema -or $health.gss_attestation_schema_version -ne "apts-gss-execution-revalidation-v1") { throw "Authorization protocol mismatch" }
if ($health.authoritative_execution_authorization_gate_enabled -ne $true -or $health.authorization_authority -ne "EXTERNAL_APTS_GSS") { throw "External authorization gate is inactive" }
if ($health.mission_source_read_only -ne $true -or $health.pentest_source_read_only -ne $true) { throw "Current sources must be read-only" }
if ($health.next_stage -ne "6.3" -or $health.runtime_self_certification -ne $false) { throw "Acceptance/next stage boundary mismatch" }
foreach ($flag in @("authorization_minted_locally","authorization_is_dispatch","dispatch_performed","tool_invocation_performed","target_network_io_performed","target_actuation","action_result_created","new_target_evidence_created","specialist_raw_target_access")) {
    if ($health.$flag -ne $false) { throw "Unexpected target execution boundary: $flag" }
}
Write-Host "[PASS] Fresh external authorization gate; gateway remains closed"
Write-Host "`n[2] Exact Stage 6.1 predecessor / Stage 6.2 contract"
$contractWeb=Invoke-WebRequest "$ExecutionUrl/api/execution/execution-authorization-contract" -UseBasicParsing -TimeoutSec 15
$response=$contractWeb.Content | ConvertFrom-Json
$prior=Invoke-RestMethod "$ExecutionUrl/api/execution/execution-request-contract" -TimeoutSec 15
if ($response.control_version -ne $ExpectedControl -or $response.read_only -ne $true -or $response.runtime_self_certification -ne $false) { throw "Authorization contract route mismatch" }
if ($response.contract.predecessor.contract_sha256 -ne $prior.contract.integrity.canonical_sha256) { throw "Stage 6.1 predecessor hash changed" }
if ($response.contract.integrity.canonical_sha256 -ne $health.stage6_2_contract_sha256) { throw "Health/contract hash mismatch" }
if (($response.contract.required_checks -join ",") -ne ($ExpectedChecks -join ",")) { throw "All eight checks are mandatory" }
Verify-RemoteJson $contractWeb.Content "contract" "verify_execution_authorization_contract"
Write-Host "[PASS] Exact SHA-bound authorization contract"
Write-Host "`n[3] Reject caller-supplied ALLOW / executable paths"
Assert-RejectedPost "$ExecutionUrl/api/execution/authorizations" '{"decision":"ALLOW"}' 400
foreach ($route in @("dispatches","results","tool-invocations")) { Assert-RejectedPost "$ExecutionUrl/api/execution/$route" '{}' 409 }
Assert-RejectedPost "$PentestUrl/api/execution/dispatches" '{}' 409
Write-Host "[PASS] No caller authority, raw tool access or target actuation"
Write-Host "`n[4] Compilation / exact canonical inventory"
python -m compileall -q mission_orchestrator pentest_subsystem execution_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Compilation failed" }
$collection=python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0 -or ($collection | Select-Object -Last 1) -notmatch "^$ExpectedInventory tests collected") { throw "Expected $ExpectedInventory tests" }
Write-Host "[PASS] $ExpectedInventory tests collected"
Write-Host "`n[5] Focused authoritative gate and real loopback HTTP proof"
python -m pytest -q tests/test_stage6_2_authoritative_execution_authorization.py
if ($LASTEXITCODE -ne 0) { throw "Stage 6.2 focused regression failed" }
Write-Host "[PASS] $ExpectedFocused focused tests"
Write-Host "`n[6] Stage 5.9 -> 5.10 -> 6.1 -> 6.2 continuity"
python -m pytest -q tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py tests/test_stage6_1_canonical_execution_request_contract.py tests/test_stage6_2_authoritative_execution_authorization.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5/6 continuity failed" }
Write-Host "`n[7] Full historical regression - FINAL SOURCE PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }
if ($LiveAuthorizationId) {
    Write-Host "`n[8] Existing live external revalidation record (read-only)"
    $liveWeb=Invoke-WebRequest "$ExecutionUrl/api/execution/authorizations/$LiveAuthorizationId" -UseBasicParsing -TimeoutSec 15
    $live=$liveWeb.Content | ConvertFrom-Json
    Verify-RemoteJson $liveWeb.Content "record" "verify_authorization_record"
    if ($live.authorization_current -ne $false -or $live.execution_authorized -ne $false) { throw "Historical read must not authorize execution" }
    Write-Host "[PASS] Live PolicyDecision bound to execution/evaluation/context/nonce"
} else {
    Write-Host "Live GSS attestation: NOT EXERCISED; source tests use isolated loopback authority."
    Write-Host "Use -LiveAuthorizationId eauth-... after a real revalidation to verify its stored evidence."
}
Write-Host "`nSTAGE 6.2 ACCEPTANCE: PASS"
Write-Host "Scope: source activation + $ExpectedInventory regression tests + GSS health; live attestation only if ID supplied."
Write-Host "Request remains AWAITING_AUTHORIZATION; separate append-only ALLOW / DENY / REVIEW audit records."
Write-Host "Next: Stage 6.3 - Controlled Execution Gateway"
