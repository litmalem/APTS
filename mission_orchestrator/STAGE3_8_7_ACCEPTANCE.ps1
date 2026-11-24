param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780',
    [string]$MissionId = ''
)
$ErrorActionPreference = 'Stop'
function Fail([string]$Reason) { Write-Host "STAGE 3.8.7 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red; exit 1 }
function Pass([string]$Reason) { Write-Host "[PASS] $Reason" -ForegroundColor Green }
Set-Location $PSScriptRoot

try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.control_version -ne 'stage3.8.7-integrity-gap-consistency-diagnostics') { Fail 'runtime control not active; apply patch and restart service' }
if ($health.mission_repository_migration_level -ne 53) { Fail 'migration level mismatch' }
if ($health.integrity_gap_consistency_diagnostics_schema_version -ne 'apts-integrity-gap-consistency-diagnostics-v1') { Fail 'diagnostics schema mismatch' }
if ($health.integrity_gap_consistency_diagnostics_read_only -ne $true -or
    $health.integrity_gap_consistency_diagnostics_deterministic -ne $true -or
    $health.integrity_gap_consistency_diagnostics_new_durable_store_added -ne $false) { Fail 'diagnostics invariants inactive' }
Pass 'runtime contract active'

try { $contract = Invoke-RestMethod "$MissionBaseUrl/api/observability/diagnostics-contract" } catch { Fail "diagnostics contract route unavailable: $($_.Exception.Message)" }
if ($contract.definition.schema_version -ne 'apts-integrity-gap-consistency-diagnostics-v1' -or
    $contract.definition.mode -ne 'DETERMINISTIC_READ_ONLY_INTEGRITY_GAP_CONSISTENCY_DIAGNOSTICS' -or
    $contract.definition.runtime_side_effects -ne $false) { Fail 'diagnostics contract mismatch' }
Pass 'diagnostics contract route'

if ($MissionId) {
    try {
        $safeMissionId = [uri]::EscapeDataString($MissionId)
        $result = Invoke-RestMethod "$MissionBaseUrl/api/missions/$safeMissionId/observability-diagnostics"
    } catch { Fail "Mission diagnostics route unavailable: $($_.Exception.Message)" }
    if ($result.integrity_status -ne 'PASS' -or
        $result.diagnostics.mission_id -ne $MissionId -or
        $result.diagnostics.schema_version -ne 'apts-integrity-gap-consistency-diagnostics-v1' -or
        $result.diagnostics.finding_count -ne $result.diagnostics.findings.Count -or
        $result.diagnostics.status -notin @('PASS', 'FINDINGS', 'INDETERMINATE')) { Fail 'Mission diagnostics report invalid' }
    Pass "Mission diagnostics route: $($result.diagnostics.status)"
}

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1408 tests collected') { Fail 'canonical inventory must contain 1408 tests' }
Pass '1408 tests collected'

$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch '(?m)^1408 passed') { Fail 'full regression failed' }
Pass 'full regression'

$focused = (& python -m pytest -q tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch '(?m)^11 passed') { Fail 'focused regression failed' }
Pass '11 focused tests'
Write-Host 'STAGE 3.8.7 ACCEPTANCE: PASS' -ForegroundColor Green
