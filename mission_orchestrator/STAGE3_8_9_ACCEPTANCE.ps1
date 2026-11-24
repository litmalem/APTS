param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780',
    [string]$MissionId = ''
)
$ErrorActionPreference = 'Stop'
function Fail([string]$Reason) { Write-Host "STAGE 3.8.9 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red; exit 1 }
function Pass([string]$Reason) { Write-Host "[PASS] $Reason" -ForegroundColor Green }
Set-Location $PSScriptRoot

try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.control_version -ne 'stage3.8.9-forensic-query-evidence-bundle-reconstruction-api') { Fail 'runtime control not active; install overlay and restart service' }
if ($health.mission_repository_migration_level -ne 53 -or
    $health.forensic_query_evidence_bundle_database_migration_level -ne 53) { Fail 'migration level mismatch' }
if ($health.forensic_query_evidence_bundle_schema_version -ne 'apts-forensic-query-evidence-bundle-reconstruction-v1' -or
    $health.forensic_query_evidence_bundle_read_only -ne $true -or
    $health.forensic_query_evidence_bundle_deterministic -ne $true -or
    $health.forensic_query_evidence_bundle_new_durable_store_added -ne $false) { Fail 'forensic contract inactive' }
Pass 'runtime contract active'

try { $contract = Invoke-RestMethod "$MissionBaseUrl/api/observability/forensic-contract" } catch { Fail "forensic contract route unavailable: $($_.Exception.Message)" }
if ($contract.definition.schema_version -ne 'apts-forensic-query-evidence-bundle-reconstruction-v1' -or
    $contract.definition.runtime_side_effects -ne $false -or
    $contract.definition.external_attestation -ne $false -or
    $contract.definition.atomic_database_snapshot -ne $false) { Fail 'forensic contract mismatch' }
Pass 'forensic contract route'

if ($MissionId) {
    $safeMissionId = [uri]::EscapeDataString($MissionId)
    $missionUrl = "$MissionBaseUrl/api/missions/$safeMissionId"
    try {
        $before = Invoke-RestMethod "$missionUrl/events"
        $bundle = Invoke-RestMethod "$missionUrl/forensic-evidence-bundle"
        $reconstruction = Invoke-RestMethod "$missionUrl/forensic-reconstruction"
        $query = Invoke-RestMethod "$missionUrl/forensic-query?scope=events"
        $after = Invoke-RestMethod "$missionUrl/events"
    } catch { Fail "Mission forensic route unavailable: $($_.Exception.Message)" }
    if ($bundle.integrity_status -ne 'PASS' -or $bundle.bundle.status -ne 'VERIFIED' -or
        $bundle.bundle.mission_id -ne $MissionId -or
        $bundle.bundle.diagnostics.status -ne 'PASS' -or
        $bundle.bundle.record_counts.mission_events -ne $before.event_count -or
        $reconstruction.result.status -ne 'VERIFIED' -or
        $reconstruction.result.reconstruction.event_count -ne $before.event_count -or
        $query.result.status -ne 'VERIFIED' -or
        $query.result.result.events.Count -ne $before.event_count -or
        $before.event_count -ne $after.event_count -or
        $before.events[-1].canonical_sha256 -ne $after.events[-1].canonical_sha256) { Fail 'Mission forensic or read-only invariants failed' }
    Pass "verified Mission evidence and reconstruction: $MissionId"
}

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1427 tests collected') { Fail 'canonical inventory must contain 1427 tests' }
Pass '1427 tests collected'

$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch '(?m)^1427 passed') { Fail 'full regression failed' }
Pass 'full regression'

$focused = (& python -m pytest -q tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch '(?m)^10 passed') { Fail 'focused regression failed' }
Pass '10 focused tests'
Write-Host 'STAGE 3.8.9 ACCEPTANCE: PASS' -ForegroundColor Green
