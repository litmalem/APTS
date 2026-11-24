param(
    [Parameter(Mandatory = $true)]
    [string]$TaskId,

    [string]$BaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Stage 2.9.2 Task Lineage Probe Acceptance ==="
Write-Host "BaseUrl = $BaseUrl"
Write-Host "TaskId  = $TaskId"

$health = Invoke-RestMethod "$BaseUrl/health"
if ($health.status -ne "ok") {
    throw "Health check failed: status=$($health.status)"
}
if ($health.control_version -ne "hybrid-event-driven-2.13-task-lineage-probe") {
    throw "Unexpected control_version: $($health.control_version)"
}

$encodedTaskId = [uri]::EscapeDataString($TaskId)
$probe = Invoke-RestMethod "$BaseUrl/api/cti/tasks/$encodedTaskId/lineage"

if ($probe.status -ne "completed") {
    throw "Probe did not complete: status=$($probe.status)"
}
if ($probe.task_id -ne $TaskId) {
    throw "Envelope task_id mismatch: expected=$TaskId actual=$($probe.task_id)"
}
if ($probe.lineage.projection_schema_version -ne "cti-lineage-projection-v1") {
    throw "Unexpected projection schema: $($probe.lineage.projection_schema_version)"
}
if ($probe.lineage.projection_scope -ne "TASK") {
    throw "Unexpected projection scope: $($probe.lineage.projection_scope)"
}
if ($probe.lineage.identity.task_id -ne $TaskId) {
    throw "Projection identity.task_id mismatch: expected=$TaskId actual=$($probe.lineage.identity.task_id)"
}
if ($probe.lineage.governance_binding.correlation_status -ne "NOT_EVALUATED_STAGE_2_9_4") {
    throw "Stage boundary violated: correlation_status=$($probe.lineage.governance_binding.correlation_status)"
}

Write-Host ""
Write-Host "--- Canonical projection summary ---"
$probe | ConvertTo-Json -Depth 50

$missingTaskId = "task-stage292-not-found-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
$encodedMissingTaskId = [uri]::EscapeDataString($missingTaskId)
$notFoundObserved = $false
try {
    Invoke-RestMethod "$BaseUrl/api/cti/tasks/$encodedMissingTaskId/lineage" | Out-Null
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
    throw "Expected HTTP 404 for missing task lineage probe"
}

Write-Host ""
Write-Host "STAGE_2_9_2_HTTP_ACCEPTANCE_PASS"
