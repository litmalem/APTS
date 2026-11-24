param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790",
    [string]$ExecutionUrl = "http://127.0.0.1:8791"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedPentestControl = "stage5.10-agentic-pentest-acceptance-regression-gate"
$ExpectedControl = "stage6.1-canonical-execution-request-contract"
$ExpectedSchema = "apts-stage6.1-canonical-execution-request-contract-v1"
$ExpectedRequestSchema = "apts-execution-request-v1"
$ExpectedEnvelopeSchema = "apts-canonical-action-envelope-v1"
$ExpectedPentestMigration = 16
$ExpectedExecutionMigration = 1
$ExpectedInventory = 2118
$ExpectedFields = @("execution_id", "mission_id", "task_id", "pentest_id", "proposing_agent", "action", "target", "parameters", "evidence_basis", "authorization_requirement")
$ExpectedChecks = @("SCOPE", "ROE", "POLICY", "RISK", "EXPIRY", "REVOCATION", "TARGET", "TECHNIQUE")
$DisabledFlags = @("request_is_authorization", "authorization_minted", "execution_authorized", "dispatch_performed", "tool_invocation_performed", "external_network_io_performed", "target_actuation", "action_result_created", "new_target_evidence_created")

function Assert-ClosedPost([string]$Uri) {
    $rejected = $false
    try {
        Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body '{}' -UseBasicParsing -TimeoutSec 15 | Out-Null
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
            $rejected = $true
        } else {
            throw
        }
    }
    if (-not $rejected) { throw "Expected fail-closed HTTP 409: $Uri" }
}

Write-Host "=============================================================================="
Write-Host "Stage 6.1 - Canonical Execution Request Contract"
Write-Host "=============================================================================="

Write-Host "`n[0] Global Mission Orchestrator / Stage 5.10 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health" -TimeoutSec 15
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Global Mission Orchestrator control mismatch" }
$pentest = Invoke-RestMethod "$PentestUrl/health" -TimeoutSec 15
if ($pentest.control_version -ne $ExpectedPentestControl) { throw "Pentest Stage 5.10 baseline mismatch" }
if ([int]$pentest.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration must remain 16" }
if ($pentest.stage5_10_runtime_self_certification -ne $false) { throw "Stage 5 may not self-certify" }
Write-Host "[PASS] Stage 3.9.10 global root and Stage 5.10 Pentest control retained"

Write-Host "`n[1] Stage 6.1 isolated runtime activation"
$healthWeb = Invoke-WebRequest "$ExecutionUrl/health" -UseBasicParsing -TimeoutSec 15
if ($healthWeb.Headers["Server"] -notmatch "APTSExecutionSubsystem/6\.1") { throw "Execution server version mismatch" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.status -ne "ok" -or $health.control_version -ne $ExpectedControl) { throw "Stage 6.1 runtime is not ready" }
if ([int]$health.execution_repository_migration_level -ne $ExpectedExecutionMigration) { throw "Execution migration mismatch" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Execution source migration mismatch" }
if ($health.stage6_1_schema_version -ne $ExpectedSchema) { throw "Stage 6.1 contract schema mismatch" }
if ($health.stage6_1_request_schema_version -ne $ExpectedRequestSchema) { throw "ExecutionRequest schema mismatch" }
if ($health.stage6_1_envelope_schema_version -ne $ExpectedEnvelopeSchema) { throw "Action envelope schema mismatch" }
if ($health.stage6_1_predecessor_control -ne $ExpectedPentestControl) { throw "Stage 6.1 predecessor mismatch" }
if ($health.proposal_source_ready -ne $true -or $health.pentest_source_read_only -ne $true) { throw "Read-only proposal source not active" }
if ($health.execution_request_creation_enabled -ne $true) { throw "Canonical request creation not active" }
foreach ($flag in $DisabledFlags) {
    if ($health.$flag -ne $false) { throw "Unexpected execution authority: $flag" }
}
if ($health.next_stage -ne "6.2") { throw "Stage 6.2 handoff mismatch" }
Write-Host "[PASS] Execution migration 1; Pentest migration 16; request intake only"

Write-Host "`n[2] Canonical schema / action envelope / Stage 5 root binding"
$response = Invoke-RestMethod "$ExecutionUrl/api/execution/execution-request-contract" -TimeoutSec 15
$closure = Invoke-RestMethod "$PentestUrl/api/pentest/agentic-pentest-acceptance-gate-contract" -TimeoutSec 15
if ($response.control_version -ne $ExpectedControl -or $response.read_only -ne $true) { throw "Execution contract route mismatch" }
if ($response.runtime_self_certification -ne $false) { throw "Execution runtime may not self-certify" }
if ($response.contract.predecessor.contract_sha256 -ne $closure.contract.integrity.canonical_sha256) { throw "Stage 5 closure hash is not bound exactly" }
if ($response.contract.integrity.canonical_sha256 -ne $health.stage6_1_contract_sha256) { throw "Contract / runtime hash mismatch" }
if (($response.contract.required_execution_request_fields -join ",") -ne ($ExpectedFields -join ",")) { throw "ExecutionRequest roadmap fields mismatch" }
if (($response.contract.required_authorization_checks -join ",") -ne ($ExpectedChecks -join ",")) { throw "Required Stage 6.2 checks mismatch" }
if ($response.contract.request_status -ne "AWAITING_AUTHORIZATION") { throw "Request status must remain awaiting authorization" }
if ($response.contract.deliverables.execution_request_schema -ne $true -or $response.contract.deliverables.canonical_action_envelope -ne $true) { throw "Stage 6.1 deliverable missing" }
$contractPath = Join-Path ([System.IO.Path]::GetTempPath()) ("apts-stage61-contract-" + [guid]::NewGuid().ToString() + ".json")
try {
    $contractJson = $response.contract | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText($contractPath, $contractJson, (New-Object System.Text.UTF8Encoding($false)))
    python -c "import json,sys; from execution_subsystem.execution_contract import verify_execution_request_contract; c=json.load(open(sys.argv[1],encoding='utf-8-sig')); sys.exit(0 if verify_execution_request_contract(c) else 1)" $contractPath
    if ($LASTEXITCODE -ne 0) { throw "Remote contract failed exact canonical integrity verification" }
} finally {
    if (Test-Path $contractPath) { Remove-Item $contractPath -Force }
}
Write-Host "[PASS] Exact SHA-bound contract; all 10 fields and 8 authorization requirements"

Write-Host "`n[3] Negative authorization / dispatch / result / raw-tool boundaries"
Assert-ClosedPost "$PentestUrl/api/execution/dispatches"
foreach ($route in @("dispatches", "authorizations", "results", "tool-invocations")) {
    Assert-ClosedPost "$ExecutionUrl/api/execution/$route"
}
Write-Host "[PASS] Stage 6.1 and specialists cannot execute targets or mint authorization"

Write-Host "`n[4] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem execution_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[5] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "Expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[6] Focused Stage 6.1 request / integrity / idempotency / restart / API regression"
python -m pytest -q tests/test_stage6_1_canonical_execution_request_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 6.1 focused regression failed" }

Write-Host "`n[7] Stage 5.9 -> Stage 5.10 -> Stage 6.1 continuity"
python -m pytest -q `
    tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py `
    tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py `
    tests/test_stage6_1_canonical_execution_request_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 5 -> Stage 6 request continuity failed" }

Write-Host "`n[8] Critical global-root / scope / lineage / specialist / request regression"
python -m pytest -q `
    tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
    tests/test_stage4_8_governance_scope_roe_enforcement.py `
    tests/test_stage4_9_evidence_finding_lineage_foundation.py `
    tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
    tests/test_stage5_6_exploitation_agent.py `
    tests/test_stage5_8_cross_agent_feedback_shared_state_replanning.py `
    tests/test_stage5_9_governance_bound_multi_agent_pentest_e2e.py `
    tests/test_stage5_10_agentic_pentest_acceptance_regression_gate.py `
    tests/test_stage6_1_canonical_execution_request_contract.py
if ($LASTEXITCODE -ne 0) { throw "Critical Stage 6.1 regression failed" }

Write-Host "`n[9] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "STAGE 6.1 ACCEPTANCE: PASS"
Write-Host "Control            : $ExpectedControl"
Write-Host "Execution migration: $ExpectedExecutionMigration"
Write-Host "Pentest migration  : $ExpectedPentestMigration (unchanged)"
Write-Host "Inventory          : $ExpectedInventory"
Write-Host "Deliverables       : ExecutionRequest schema + canonical action envelope"
Write-Host "Request status     : AWAITING_AUTHORIZATION"
Write-Host "Boundary           : read-only Pentest source; no authorization/dispatch/tool/target/result authority"
Write-Host "Next               : Stage 6.2 - Authoritative Execution Authorization"
Write-Host "=============================================================================="
