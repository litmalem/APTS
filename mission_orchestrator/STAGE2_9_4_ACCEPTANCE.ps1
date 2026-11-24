param(
    [Parameter(Mandatory=$true)]
    [string]$MissionId,
    [string]$VulnDeskBaseUrl = "http://127.0.0.1:8765",
    [string]$GovernanceBaseUrl = "http://127.0.0.1:8770",
    [switch]$RequireFullyCorrelated
)

$ErrorActionPreference = "Stop"

Write-Host "=== Stage 2.9.4 Cross-Subsystem Governance Correlation Acceptance ==="
Write-Host "Mission: $MissionId"

$govHealth = Invoke-RestMethod "$GovernanceBaseUrl/health"
if ($govHealth.governance_correlation_probe_mode -ne "MISSION_SCOPED_AUTHORITATIVE_READ_ONLY") {
    throw "aptsGSS Stage 2.9.4 correlation probe mode is not active."
}
Write-Host "[PASS] aptsGSS correlation read model active"

$ctiHealth = Invoke-RestMethod "$VulnDeskBaseUrl/health"
if ($ctiHealth.control_version -ne "hybrid-event-driven-2.15-cross-subsystem-governance-correlation") {
    throw "Unexpected VulnDesk control_version: $($ctiHealth.control_version)"
}
Write-Host "[PASS] VulnDesk control version 2.15 active"

$escapedMission = [System.Uri]::EscapeDataString($MissionId)
$gov = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/correlation/missions/$escapedMission"
if ($gov.status -ne "completed") {
    throw "Governance correlation endpoint did not complete."
}
if ($gov.correlation_snapshot.mission_id -ne $MissionId) {
    throw "Governance snapshot mission_id mismatch."
}
Write-Host "[PASS] authoritative aptsGSS mission snapshot retrieved"

$probe = Invoke-RestMethod "$VulnDeskBaseUrl/api/cti/missions/$escapedMission/lineage"
if ($probe.status -ne "completed") {
    throw "VulnDesk mission lineage probe did not complete."
}
$corr = $probe.lineage.governance_correlation
if ($null -eq $corr) {
    throw "governance_correlation section is missing."
}
if ($corr.classification -ne "CORRELATION_FACTS_ONLY_STAGE_2_9_4") {
    throw "Unexpected Stage 2.9.4 classification boundary."
}
if ($corr.integrity_classification_status -ne "NOT_EVALUATED_STAGE_2_9_5") {
    throw "Stage 2.9.5 boundary was not preserved."
}
if ($probe.lineage.projection_metadata.governance_correlation_status -eq "NOT_EVALUATED_STAGE_2_9_4") {
    throw "Mission lineage was not correlated."
}
if ($RequireFullyCorrelated -and $corr.status -ne "CORRELATED") {
    $corr | ConvertTo-Json -Depth 50
    throw "Correlation is not fully CORRELATED: $($corr.status)"
}

Write-Host "[PASS] Stage 2.9.4 correlation executed with status: $($corr.status)"
Write-Host ""
Write-Host "Correlation facts:"
$corr.correlation_facts | ConvertTo-Json -Depth 20
Write-Host ""
Write-Host "Authoritative snapshot counts:"
$gov.correlation_snapshot.counts | ConvertTo-Json -Depth 20
Write-Host ""
Write-Host "=== ACCEPTANCE COMPLETE ==="
