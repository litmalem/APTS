param(
    [Parameter(Mandatory=$true)][string]$PipId,
    [Parameter(Mandatory=$true)][string]$PolicyDecisionId,
    [string]$MissionId = 'mission-gmo-7e856bbd-8160-4103-9ad8-8f4ad5378253',
    [string]$RouteDecisionId = 'rdec-60a00956-b9e7-4776-aff6-d4c675240a5d',
    [string]$RequestedBy = 'operator-admin-01',
    [string]$MissionUrl = 'http://127.0.0.1:8780',
    [string]$PentestUrl = 'http://127.0.0.1:8790'
)
$ErrorActionPreference='Stop'
$body = @{
    route_decision_id = $RouteDecisionId
    requested_by = $RequestedBy
    stage43_cti = @{ pip_id=$PipId; policy_decision_id=$PolicyDecisionId }
}
$result = Invoke-RestMethod -Uri "$MissionUrl/api/missions/$MissionId/pentest-handoff" -Method Post `
    -Body ($body | ConvertTo-Json -Depth 30) -ContentType 'application/json' -TimeoutSec 120
$result | ConvertTo-Json -Depth 18
if (-not $result.stage43_materialized) { throw 'Stage 4.3 has not materialized; inspect GSS and CTI prerequisites.' }
$options = Invoke-RestMethod -Uri "$PentestUrl/api/pentest/ui/orchestration-options" -TimeoutSec 15
$task = $result.pentest_task.record.pentest_task_id
if (-not ($options.pending_tasks | Where-Object { $_.task_summary.pentest_task_id -eq $task })) {
    throw 'Pentest task not visible in pending tasks. Check APTS_PENTEST_DB used by Mission and Pentest.'
}
Write-Host 'STAGE 4.3 PASS. Pentest task is pending orchestration; no target action executed.'
