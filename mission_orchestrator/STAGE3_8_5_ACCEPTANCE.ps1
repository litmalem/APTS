param([string]$MissionBaseUrl = 'http://127.0.0.1:8780')
$ErrorActionPreference = 'Stop'
function Fail([string]$Reason) { Write-Host "STAGE 3.8.5 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red; exit 1 }
function Pass([string]$Reason) { Write-Host "[PASS] $Reason" -ForegroundColor Green }
Set-Location $PSScriptRoot
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.control_version -ne 'stage3.8.5-decision-governance-evidence-trace') { Fail 'runtime control not active; install package and restart service' }
if ($health.mission_repository_migration_level -ne 53) { Fail 'migration level mismatch' }
if ($health.decision_governance_evidence_trace_schema_version -ne 'apts-decision-governance-evidence-trace-v1') { Fail 'trace schema mismatch' }
if ($health.decision_governance_evidence_trace_read_only -ne $true -or $health.decision_governance_evidence_trace_deterministic -ne $true -or $health.decision_governance_evidence_trace_new_durable_store_added -ne $false) { Fail 'trace invariants inactive' }
Pass 'runtime contract active'
& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'
$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1392 tests collected') { Fail 'canonical inventory must contain 1392 tests' }
Pass '1392 tests collected'
$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch '(?m)^1392 passed') { Fail 'full regression failed' }
Pass 'full regression'
$focused = (& python -m pytest -q tests/test_stage3_8_5_decision_governance_evidence_trace.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch '(?m)^3 passed') { Fail 'focused regression failed' }
Pass '3 focused tests'
Write-Host 'STAGE 3.8.5 ACCEPTANCE: PASS' -ForegroundColor Green
