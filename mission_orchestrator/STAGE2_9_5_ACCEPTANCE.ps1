param(
    [Parameter(Mandatory=$true)]
    [string]$MissionId,
    [string]$VulnDeskBaseUrl = "http://127.0.0.1:8765",
    [string]$GovernanceBaseUrl = "http://127.0.0.1:8770",
    [switch]$DiagnosticOnly
)

$ErrorActionPreference = "Stop"

Write-Host "=== Stage 2.9.5 Integrity / Violation Probe Acceptance ==="
Write-Host "Mission: $MissionId"

$govHealth = Invoke-RestMethod "$GovernanceBaseUrl/health"
if ($govHealth.governance_correlation_probe_mode -ne "MISSION_SCOPED_AUTHORITATIVE_READ_ONLY") {
    throw "aptsGSS Stage 2.9.4 authoritative correlation read model is not active."
}
Write-Host "[PASS] aptsGSS authoritative correlation read model active"

$ctiHealth = Invoke-RestMethod "$VulnDeskBaseUrl/health"
if ($ctiHealth.control_version -ne "hybrid-event-driven-2.16-integrity-violation-probe") {
    throw "Unexpected VulnDesk control_version: $($ctiHealth.control_version)"
}
if ($ctiHealth.integrity_probe_mode -ne "READ_ONLY_CANONICAL_LINEAGE_PLUS_AUTHORITATIVE_CORRELATION") {
    throw "Unexpected integrity_probe_mode: $($ctiHealth.integrity_probe_mode)"
}
Write-Host "[PASS] VulnDesk Stage 2.9.5 control active"

$escapedMission = [System.Uri]::EscapeDataString($MissionId)

# Prove the Stage 2.9.4 authority source remains reachable.
$gov = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/correlation/missions/$escapedMission"
if ($gov.status -ne "completed") {
    throw "Governance correlation endpoint did not complete."
}
if ($gov.correlation_snapshot.mission_id -ne $MissionId) {
    throw "Governance snapshot mission_id mismatch."
}
Write-Host "[PASS] authoritative aptsGSS mission snapshot retrieved"

# Existing lineage endpoint must now be enriched by Stage 2.9.5.
$lineageResponse = Invoke-RestMethod "$VulnDeskBaseUrl/api/cti/missions/$escapedMission/lineage"
if ($lineageResponse.status -ne "completed") {
    throw "VulnDesk mission lineage endpoint did not complete."
}
$lineage = $lineageResponse.lineage
if ($null -eq $lineage.governance_correlation) {
    throw "governance_correlation section is missing from mission lineage."
}
if ($null -eq $lineage.integrity_probe) {
    throw "integrity_probe section is missing from mission lineage."
}
if ($lineage.integrity_probe.schema_version -ne "cti-integrity-probe-v1") {
    throw "Unexpected integrity probe schema: $($lineage.integrity_probe.schema_version)"
}
if ($lineage.integrity_probe.classification -ne "LINEAGE_INTEGRITY_VIOLATION_CLASSIFICATION_STAGE_2_9_5") {
    throw "Unexpected Stage 2.9.5 classification."
}
if ($lineage.projection_metadata.integrity_classification_status -ne $lineage.integrity_probe.status) {
    throw "Mission projection metadata integrity status does not match integrity probe status."
}
Write-Host "[PASS] mission lineage enriched with Stage 2.9.5 classification"

# Dedicated Stage 2.9.5 mission endpoint must agree with the enriched lineage.
$missionProbe = Invoke-RestMethod "$VulnDeskBaseUrl/api/cti/missions/$escapedMission/integrity"
if ($missionProbe.status -ne "completed") {
    throw "Mission integrity endpoint did not complete."
}
$integrity = $missionProbe.integrity
if ($integrity.status -ne $lineage.integrity_probe.status) {
    throw "Dedicated mission integrity endpoint disagrees with lineage integrity status."
}
if ([int]$integrity.violation_count -ne [int]$lineage.integrity_probe.violation_count) {
    throw "Dedicated mission integrity endpoint disagrees with lineage violation count."
}
Write-Host "[PASS] dedicated mission integrity endpoint agrees with lineage"

# Probe every task using the dedicated Task endpoint.
foreach ($taskLineage in @($lineage.task_lineages)) {
    $taskId = [string]$taskLineage.identity.task_id
    if ([string]::IsNullOrWhiteSpace($taskId)) {
        throw "Mission lineage contains a TaskContract without task_id."
    }
    $escapedTask = [System.Uri]::EscapeDataString($taskId)
    $taskProbe = Invoke-RestMethod "$VulnDeskBaseUrl/api/cti/tasks/$escapedTask/integrity"
    if ($taskProbe.status -ne "completed") {
        throw "Task integrity endpoint failed for $taskId."
    }
    if ($taskProbe.integrity.schema_version -ne "cti-integrity-probe-v1") {
        throw "Unexpected task integrity schema for $taskId."
    }
    Write-Host "  Task $taskId => $($taskProbe.integrity.status), violations=$($taskProbe.integrity.violation_count)"
}
Write-Host "[PASS] Task integrity endpoints reachable for all mission TaskContracts"

Write-Host ""
Write-Host "Integrity summary:"
$integrity.summary | ConvertTo-Json -Depth 20
Write-Host ""
Write-Host "Severity counts:"
$integrity.severity_counts | ConvertTo-Json -Depth 20
Write-Host ""
Write-Host "Violation code counts:"
$integrity.violation_code_counts | ConvertTo-Json -Depth 20
Write-Host ""

if ($integrity.violation_count -gt 0) {
    Write-Host "Detected violations:"
    $integrity.violations | ConvertTo-Json -Depth 50
}
if (-not $integrity.verification_complete) {
    Write-Host "Verification reasons:"
    $integrity.verification_reasons | ConvertTo-Json -Depth 20
}

if (-not $DiagnosticOnly) {
    if ($integrity.status -ne "PASS") {
        throw "Stage 2.9.5 acceptance requires PASS; observed $($integrity.status). Use -DiagnosticOnly only for investigation."
    }
    if ([int]$integrity.violation_count -ne 0) {
        throw "Stage 2.9.5 acceptance requires violation_count=0."
    }
    if (-not [bool]$integrity.verification_complete) {
        throw "Stage 2.9.5 acceptance requires verification_complete=true."
    }
}

Write-Host "[PASS] Stage 2.9.5 Integrity / Violation Probe acceptance completed"
