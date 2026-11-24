param(
    [Parameter(Mandatory = $true)]
    [string]$MissionId,

    [string]$BaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Stage 2.9.3 Mission Lineage Reconstruction Acceptance ==="
Write-Host "BaseUrl   = $BaseUrl"
Write-Host "MissionId = $MissionId"

$health = Invoke-RestMethod "$BaseUrl/health"
if ($health.status -ne "ok") {
    throw "Health check failed: status=$($health.status)"
}
if ($health.control_version -ne "hybrid-event-driven-2.14-mission-lineage-reconstruction") {
    throw "Unexpected control_version: $($health.control_version)"
}

$encodedMissionId = [uri]::EscapeDataString($MissionId)
$probe = Invoke-RestMethod "$BaseUrl/api/cti/missions/$encodedMissionId/lineage"

if ($probe.status -ne "completed") {
    throw "Mission lineage reconstruction did not complete: status=$($probe.status)"
}
if ($probe.mission_id -ne $MissionId) {
    throw "Envelope mission_id mismatch: expected=$MissionId actual=$($probe.mission_id)"
}
if ($probe.lineage.projection_schema_version -ne "cti-lineage-projection-v1") {
    throw "Unexpected projection schema: $($probe.lineage.projection_schema_version)"
}
if ($probe.lineage.projection_scope -ne "MISSION") {
    throw "Unexpected projection scope: $($probe.lineage.projection_scope)"
}
if ($probe.lineage.identity.mission_id -ne $MissionId) {
    throw "Projection identity.mission_id mismatch"
}
if ($probe.lineage.projection_metadata.governance_correlation_status -ne "NOT_EVALUATED_STAGE_2_9_4") {
    throw "Stage 2.9.4 boundary violated: $($probe.lineage.projection_metadata.governance_correlation_status)"
}
if ($probe.lineage.projection_metadata.integrity_classification_status -ne "NOT_EVALUATED_STAGE_2_9_5") {
    throw "Stage 2.9.5 boundary violated: $($probe.lineage.projection_metadata.integrity_classification_status)"
}
if ($probe.lineage.structural_facts.classification -ne "STRUCTURAL_FACTS_ONLY_STAGE_2_9_3") {
    throw "Unexpected structural fact classification marker"
}

# Every returned Task projection must still be the canonical Stage 2.9.1 TASK read-model.
foreach ($taskLineage in @($probe.lineage.task_lineages)) {
    if ($taskLineage.projection_schema_version -ne "cti-lineage-projection-v1") {
        throw "Task projection schema mismatch for $($taskLineage.identity.task_id)"
    }
    if ($taskLineage.projection_scope -ne "TASK") {
        throw "Task projection scope mismatch for $($taskLineage.identity.task_id)"
    }
    if ($taskLineage.identity.mission_id -ne $MissionId) {
        throw "Task mission identity mismatch for $($taskLineage.identity.task_id)"
    }
}

# Known intra-mission causal edges must be parent-before-child in the reconstructed order.
$order = @($probe.lineage.causal_order_event_ids)
$position = @{}
for ($i = 0; $i -lt $order.Count; $i++) {
    $position[$order[$i]] = $i
}
foreach ($edge in @($probe.lineage.causal_edges)) {
    if ($edge.cause_in_projection -eq $true) {
        if (-not $position.ContainsKey($edge.cause_event_id)) {
            throw "Known cause missing from causal order: $($edge.cause_event_id)"
        }
        if (-not $position.ContainsKey($edge.effect_event_id)) {
            throw "Effect missing from causal order: $($edge.effect_event_id)"
        }
        if ($position[$edge.cause_event_id] -ge $position[$edge.effect_event_id]) {
            throw "Causal order violation in reconstruction: $($edge.cause_event_id) -> $($edge.effect_event_id)"
        }
    }
}

Write-Host ""
Write-Host "--- Mission lineage summary ---"
Write-Host "Task count          = $($probe.lineage.projection_metadata.task_count)"
Write-Host "Event count         = $($probe.lineage.projection_metadata.event_count)"
Write-Host "Causal edge count   = $($probe.lineage.projection_metadata.causal_edge_count)"
Write-Host "Root event count    = $($probe.lineage.projection_metadata.root_event_count)"
Write-Host "Projection quality  = $($probe.lineage.projection_metadata.quality)"
Write-Host "Mission status      = $($probe.lineage.lifecycle.mission_status)"
Write-Host "All tasks terminal  = $($probe.lineage.lifecycle.all_tasks_terminal)"
Write-Host ""
$probe | ConvertTo-Json -Depth 60

$missingMissionId = "mission-stage293-not-found-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
$encodedMissingMissionId = [uri]::EscapeDataString($missingMissionId)
$notFoundObserved = $false
try {
    Invoke-RestMethod "$BaseUrl/api/cti/missions/$encodedMissingMissionId/lineage" | Out-Null
} catch {
    $statusCode = $null
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    if ($statusCode -eq 404) {
        $notFoundObserved = $true
    } else {
        throw
    }
}

if (-not $notFoundObserved) {
    throw "Expected HTTP 404 for missing mission lineage"
}

Write-Host ""
Write-Host "STAGE_2_9_3_HTTP_ACCEPTANCE_PASS"
