param(
    [string]$MissionId = ""
)

$ErrorActionPreference = "Stop"
$cti = "http://127.0.0.1:8765"
$gov = "http://127.0.0.1:8770"

Write-Host "=== Stage 2.9.6 Health / Diagnostics Acceptance ===" -ForegroundColor Cyan

$ctiHealth = Invoke-RestMethod "$cti/health"
$govHealth = Invoke-RestMethod "$gov/health"
$ctiDiag = Invoke-RestMethod "$cti/api/cti/diagnostics?deep=true"
$govDiag = Invoke-RestMethod "$gov/api/governance/diagnostics?deep=true"

Write-Host "`n--- VulnDesk health ---" -ForegroundColor Yellow
$ctiHealth | ConvertTo-Json -Depth 20
Write-Host "`n--- VulnDesk deep diagnostics ---" -ForegroundColor Yellow
$ctiDiag | ConvertTo-Json -Depth 30
Write-Host "`n--- Governance health ---" -ForegroundColor Yellow
$govHealth | ConvertTo-Json -Depth 20
Write-Host "`n--- Governance deep diagnostics ---" -ForegroundColor Yellow
$govDiag | ConvertTo-Json -Depth 30

if ($ctiHealth.control_version -ne "hybrid-event-driven-2.17-health-diagnostics") {
    throw "Unexpected VulnDesk control_version: $($ctiHealth.control_version)"
}
if (-not $ctiHealth.readiness_status) { throw "VulnDesk readiness_status missing" }
if (-not $govHealth.readiness_status) { throw "Governance readiness_status missing" }
if ($ctiDiag.diagnostics.schema_version -ne "cti-health-diagnostics-v1") {
    throw "Unexpected CTI diagnostics schema"
}
if ($govDiag.diagnostics.schema_version -ne "governance-health-diagnostics-v1") {
    throw "Unexpected Governance diagnostics schema"
}

if ($MissionId.Trim()) {
    Write-Host "`n--- Mission diagnostics: $MissionId ---" -ForegroundColor Yellow
    $missionDiag = Invoke-RestMethod "$cti/api/cti/missions/$MissionId/diagnostics"
    $missionDiag | ConvertTo-Json -Depth 40
    if ($missionDiag.diagnostics.mission_id -ne $MissionId) {
        throw "Mission diagnostic identity mismatch"
    }
}

Write-Host "`nStage 2.9.6 API acceptance completed." -ForegroundColor Green
