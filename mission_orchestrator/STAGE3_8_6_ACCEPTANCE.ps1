param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780',
    [string]$MissionId = ''
)
$ErrorActionPreference = 'Stop'
function Fail([string]$Reason) { Write-Host "STAGE 3.8.6 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red; exit 1 }
function Pass([string]$Reason) { Write-Host "[PASS] $Reason" -ForegroundColor Green }
Set-Location $PSScriptRoot

try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.control_version -ne 'stage3.8.6-deterministic-mission-timeline-reconstruction') { Fail 'runtime control not active; install patch and restart service' }
if ($health.mission_repository_migration_level -ne 53) { Fail 'migration level mismatch' }
if ($health.deterministic_mission_timeline_schema_version -ne 'apts-deterministic-mission-timeline-v1') { Fail 'timeline schema mismatch' }
if ($health.deterministic_mission_timeline_read_only -ne $true -or
    $health.deterministic_mission_timeline_deterministic -ne $true -or
    $health.deterministic_mission_timeline_new_durable_store_added -ne $false) { Fail 'timeline invariants inactive' }
Pass 'runtime contract active'

try { $contract = Invoke-RestMethod "$MissionBaseUrl/api/observability/timeline-contract" } catch { Fail "timeline contract route unavailable: $($_.Exception.Message)" }
if ($contract.definition.schema_version -ne 'apts-deterministic-mission-timeline-v1' -or
    $contract.definition.ordering -ne 'VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER' -or
    $contract.definition.runtime_side_effects -ne $false) { Fail 'timeline contract route mismatch' }
Pass 'timeline contract route'

if ($MissionId) {
    try {
        $safeMissionId = [uri]::EscapeDataString($MissionId)
        $timelineResult = Invoke-RestMethod "$MissionBaseUrl/api/missions/$safeMissionId/observability-timeline"
    } catch { Fail "Mission timeline route unavailable: $($_.Exception.Message)" }
    if ($timelineResult.integrity_status -ne 'PASS' -or
        $timelineResult.timeline.event_count -ne $timelineResult.timeline.entries.Count -or
        $timelineResult.timeline.ordering -ne 'VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER') { Fail 'Mission timeline integrity or event count mismatch' }
    Pass 'existing Mission timeline route'
}

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1397 tests collected') { Fail 'canonical inventory must contain 1397 tests' }
Pass '1397 tests collected'

$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch '(?m)^1397 passed') { Fail 'full regression failed' }
Pass 'full regression'

$focused = (& python -m pytest -q tests/test_stage3_8_6_deterministic_mission_timeline_reconstruction.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch '(?m)^5 passed') { Fail 'focused regression failed' }
Pass '5 focused tests'
Write-Host 'STAGE 3.8.6 ACCEPTANCE: PASS' -ForegroundColor Green
