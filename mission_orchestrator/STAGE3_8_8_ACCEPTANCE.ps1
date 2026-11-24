param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780',
    [string]$MissionId = ''
)
$ErrorActionPreference = 'Stop'
function Fail([string]$Reason) { Write-Host "STAGE 3.8.8 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red; exit 1 }
function Pass([string]$Reason) { Write-Host "[PASS] $Reason" -ForegroundColor Green }
Set-Location $PSScriptRoot

try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.control_version -ne 'stage3.8.8-observability-metrics-health-operator-diagnostics') { Fail 'runtime control not active; apply patch and restart service' }
if ($health.mission_repository_migration_level -ne 53) { Fail 'migration level mismatch' }
if ($health.observability_metrics_health_schema_version -ne 'apts-observability-metrics-health-operator-diagnostics-v1') { Fail 'metrics/health schema mismatch' }
if ($health.observability_metrics_health_read_only -ne $true -or
    $health.observability_metrics_health_deterministic -ne $true -or
    $health.observability_metrics_health_new_durable_store_added -ne $false -or
    $health.observability_metrics_health_scope -ne 'OBSERVABILITY_DATA_QUALITY_ONLY') { Fail 'metrics/health invariants inactive' }
Pass 'runtime contract active'

try { $contract = Invoke-RestMethod "$MissionBaseUrl/api/observability/metrics-health-contract" } catch { Fail "metrics/health contract route unavailable: $($_.Exception.Message)" }
if ($contract.definition.schema_version -ne 'apts-observability-metrics-health-operator-diagnostics-v1' -or
    $contract.definition.untrusted_metrics_mode -ne 'WITHHELD_NULL_NOT_ZERO' -or
    $contract.definition.runtime_side_effects -ne $false) { Fail 'metrics/health contract mismatch' }
Pass 'metrics/health contract route'

if ($MissionId) {
    try {
        $safeMissionId = [uri]::EscapeDataString($MissionId)
        $result = Invoke-RestMethod "$MissionBaseUrl/api/missions/$safeMissionId/observability-metrics-health"
    } catch { Fail "Mission metrics/health route unavailable: $($_.Exception.Message)" }
    $report = $result.report
    if ($result.integrity_status -ne 'PASS' -or $report.mission_id -ne $MissionId -or
        $report.schema_version -ne 'apts-observability-metrics-health-operator-diagnostics-v1' -or
        $report.observability_health.status -notin @('HEALTHY','DEGRADED','UNKNOWN') -or
        $report.operator_diagnostics.finding_count -ne $report.operator_diagnostics.items.Count -or
        ($report.observability_health.status -eq 'HEALTHY' -and $report.metrics.status -ne 'AVAILABLE') -or
        ($report.observability_health.status -ne 'HEALTHY' -and
            ($report.metrics.status -ne 'WITHHELD' -or $null -ne $report.metrics.event_count))) { Fail 'Mission report invalid' }
    Pass "Mission metrics/health route: $($report.observability_health.status)"
}

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1417 tests collected') { Fail 'canonical inventory must contain 1417 tests' }
Pass '1417 tests collected'

$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch '(?m)^1417 passed') { Fail 'full regression failed' }
Pass 'full regression'

$focused = (& python -m pytest -q tests/test_stage3_8_8_observability_metrics_health_operator_diagnostics.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch '(?m)^9 passed') { Fail 'focused regression failed' }
Pass '9 focused tests'
Write-Host 'STAGE 3.8.8 ACCEPTANCE: PASS' -ForegroundColor Green
