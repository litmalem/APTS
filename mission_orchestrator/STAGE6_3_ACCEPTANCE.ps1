param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790",
    [string]$ExecutionUrl = "http://127.0.0.1:8791",
    [string]$GovernanceUrl = "",
    [string]$LiveGatewayId = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not $GovernanceUrl) {
    $GovernanceUrl = $env:APTS_EXECUTION_GOVERNANCE_URL
    if (-not $GovernanceUrl) { $GovernanceUrl = $env:MISSION_GOVERNANCE_BASE_URL }
    if (-not $GovernanceUrl) { $GovernanceUrl = "http://127.0.0.1:8770" }
}
$ExpectedControl = "stage6.3-controlled-execution-gateway"
$ExpectedSchema = "apts-stage6.3-controlled-execution-gateway-v1"
$ExpectedInventory = 2340
$ExpectedFocused = 111
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
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage63-" + [guid]::NewGuid().ToString() + ".json")
    try {
        [System.IO.File]::WriteAllText($path,$RawJson,(New-Object System.Text.UTF8Encoding($false)))
        python -c "import json,sys; from execution_subsystem import gateway_contract as c; value=json.load(open(sys.argv[1],encoding='utf-8-sig'))[sys.argv[2]]; sys.exit(0 if getattr(c,sys.argv[3])(value) else 1)" $path $Member $Verifier
        if ($LASTEXITCODE -ne 0) { throw "Remote $Verifier failed exact verification" }
    } finally { if (Test-Path $path) { Remove-Item $path -Force } }
}
Write-Host "=============================================================================="
Write-Host "Stage 6.3 - Controlled Execution Gateway"
Write-Host "=============================================================================="
Write-Host "`n[0] Current Mission / Pentest / Governance preflight"
$mission=Invoke-RestMethod "$MissionUrl/health" -TimeoutSec 15
if ($mission.control_version -ne "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate" -or [int]$mission.mission_repository_migration_level -ne 53) { throw "Mission control/migration 53 mismatch" }
$pentest=Invoke-RestMethod "$PentestUrl/health" -TimeoutSec 15
if ($pentest.control_version -ne "stage5.10-agentic-pentest-acceptance-regression-gate" -or [int]$pentest.pentest_repository_migration_level -ne 16) { throw "Pentest Stage 5.10/migration 16 mismatch" }
$gss=Invoke-RestMethod "$GovernanceUrl/health" -TimeoutSec 15
if ($gss.status -ne "ok" -or $gss.component_id -ne "GOV-PLANE") { throw "External Governance health/identity mismatch" }
Write-Host "[PASS] Mission 53; Pentest 16; external GOV-PLANE reachable"
Write-Host "`n[1] Stage 6.3 runtime / atomic migration / gateway boundary"
$web=Invoke-WebRequest "$ExecutionUrl/health" -UseBasicParsing -TimeoutSec 15
$health=$web.Content | ConvertFrom-Json
if ($web.Headers["Server"] -notmatch "APTSExecutionSubsystem/6\.3" -or $health.control_version -ne $ExpectedControl -or $health.status -ne "ok") { throw "Stage 6.3 source is not active" }
if ([int]$health.execution_repository_migration_level -ne 3) { throw "Execution migration must be 3" }
if ([int]$health.mission_repository_migration_level -ne 53 -or [int]$health.pentest_repository_migration_level -ne 16) { throw "Upstream migration drift" }
if ($health.stage6_3_schema_version -ne $ExpectedSchema) { throw "Gateway schema mismatch" }
if ($health.controlled_execution_gateway_enabled -ne $true -or $health.central_execution_policy_enforcement_enabled -ne $true -or $health.gateway_admission_enabled -ne $true) { throw "Central gateway admission is inactive" }
if ($health.authorization_authority -ne "EXTERNAL_APTS_GSS" -or $health.authoritative_execution_authorization_gate_enabled -ne $true -or $health.gss_attestation_schema_version -ne "apts-gss-execution-revalidation-v1") { throw "Authoritative revalidation protocol mismatch" }
if ($health.mission_source_read_only -ne $true -or $health.pentest_source_read_only -ne $true) { throw "Sources must remain read-only" }
if ([int]$health.registered_adapter_count -ne 0 -or $health.target_dispatch_enabled -ne $false -or $health.gateway_admission_is_dispatch_authority -ne $false) { throw "Stage 6.4 adapter boundary violated" }
if ($health.fresh_revalidation_required_before_target_dispatch -ne $true -or $health.next_stage -ne "6.4" -or $health.runtime_self_certification -ne $false) { throw "Gateway freshness/acceptance boundary mismatch" }
foreach ($flag in @("authorization_minted_locally","dispatch_performed","tool_invocation_performed","target_network_io_performed","target_actuation","action_result_created","new_target_evidence_created","specialist_raw_target_access")) {
    if ($health.$flag -ne $false) { throw "Unexpected target execution boundary: $flag" }
}
Write-Host "[PASS] Central gateway admission enabled; no specialist raw target access"
Write-Host "`n[2] Exact Stage 6.2 predecessor / Stage 6.3 contract"
$contractWeb=Invoke-WebRequest "$ExecutionUrl/api/execution/execution-gateway-contract" -UseBasicParsing -TimeoutSec 15
$response=$contractWeb.Content | ConvertFrom-Json
$prior=Invoke-RestMethod "$ExecutionUrl/api/execution/execution-authorization-contract" -TimeoutSec 15
if ($response.control_version -ne $ExpectedControl -or $response.read_only -ne $true -or $response.runtime_self_certification -ne $false) { throw "Gateway contract route mismatch" }
if ($response.contract.predecessor.contract_sha256 -ne $prior.contract.integrity.canonical_sha256 -or $response.contract.predecessor.control -ne "stage6.2-authoritative-execution-authorization") { throw "Stage 6.2 predecessor hash changed" }
if ($response.contract.integrity.canonical_sha256 -ne $health.stage6_3_contract_sha256) { throw "Health/contract hash mismatch" }
Verify-RemoteJson $contractWeb.Content "contract" "verify_execution_gateway_contract"
Write-Host "[PASS] Exact SHA-bound controlled gateway contract"
Write-Host "`n[3] Reject caller ALLOW / raw tool / executable overrides"
Assert-RejectedPost "$ExecutionUrl/api/execution/gateway/submissions" '{"decision":"ALLOW"}' 400
Assert-RejectedPost "$ExecutionUrl/api/execution/authorizations" '{"decision":"ALLOW"}' 400
foreach ($route in @("dispatches","results","tool-invocations")) { Assert-RejectedPost "$ExecutionUrl/api/execution/$route" '{}' 409 }
Assert-RejectedPost "$PentestUrl/api/execution/dispatches" '{}' 409
Write-Host "[PASS] No caller authority or direct target/tool bypass"
Write-Host "`n[4] Compilation / exact canonical inventory"
python -m compileall -q mission_orchestrator pentest_subsystem execution_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Compilation failed" }
$collection=python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0 -or ($collection | Select-Object -Last 1) -notmatch "^$ExpectedInventory tests collected") { throw "Expected $ExpectedInventory tests" }
Write-Host "[PASS] $ExpectedInventory tests collected"
Write-Host "`n[5] Focused gateway policy / concurrency / crash / real loopback GSS proof"
python -m pytest -q tests/test_stage6_3_controlled_execution_gateway.py
if ($LASTEXITCODE -ne 0) { throw "Stage 6.3 focused regression failed" }
Write-Host "[PASS] $ExpectedFocused focused tests"
Write-Host "`n[6] Stage 5.9 -> 5.10 -> 6.1 -> 6.2 -> 6.3 continuity"
python -m pytest -q tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py tests/test_stage6_1_canonical_execution_request_contract.py tests/test_stage6_2_authoritative_execution_authorization.py tests/test_stage6_3_controlled_execution_gateway.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5/6 continuity failed" }
Write-Host "`n[7] Full historical regression - FINAL SOURCE PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }
if ($LiveGatewayId) {
    Write-Host "`n[8] Existing live gateway submission (read-only)"
    $liveWeb=Invoke-WebRequest "$ExecutionUrl/api/execution/gateway/submissions/$LiveGatewayId" -UseBasicParsing -TimeoutSec 15
    $live=$liveWeb.Content | ConvertFrom-Json
    Verify-RemoteJson $liveWeb.Content "record" "verify_gateway_record"
    if ($live.gateway_admitted -ne $false -or $live.authorization_current -ne $false -or $live.execution_authorized -ne $false -or $live.usable_for_dispatch -ne $false) { throw "Historical read must not admit or dispatch" }
    Write-Host "[PASS] Captured live gateway audit and exact external authorization binding"
} else {
    Write-Host "Live GSS gateway admission: NOT EXERCISED; tests use isolated authority."
    Write-Host "Use -LiveGatewayId egate-... after a real submission to verify its stored evidence."
}
Write-Host "`nSTAGE 6.3 ACCEPTANCE: PASS"
Write-Host "Scope: source/runtime activation + $ExpectedInventory regression tests + GSS health; live admission only if ID supplied."
Write-Host "Gateway admissions are audit only; no target dispatch or runtime adapter controls are claimed."
Write-Host "Next: Stage 6.4 - Authorized Tool Adapters & Sandboxing"
