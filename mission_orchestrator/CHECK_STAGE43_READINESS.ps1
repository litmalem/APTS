param(
    [string]$MissionId = 'mission-gmo-7e856bbd-8160-4103-9ad8-8f4ad5378253',
    [string]$PentestUrl = 'http://127.0.0.1:8790',
    [string]$CtiUrl = 'http://127.0.0.1:8765',
    [string]$GssUrl = 'http://127.0.0.1:8770'
)
$ErrorActionPreference='Stop'
$h = Invoke-RestMethod "$PentestUrl/api/pentest/ui/mission-handoffs?mission_id=$MissionId" -TimeoutSec 15
Write-Host ('Pending handoffs: ' + @($h.handoffs).Count)
foreach ($entry in @($h.handoffs)) {
    Write-Host ('- ' + $entry.handoff_id + ' (upstream task: ' + $entry.upstream_task_id + ')')
}
try {
    $cti = Invoke-RestMethod "$CtiUrl/api/cti/missions/$MissionId" -TimeoutSec 10
    Write-Host ('CTI mission latest_pip_id: ' + $cti.mission.latest_pip_id)
    Write-Host ('CTI mission pip_readiness: ' + $cti.mission.pip_readiness)
} catch { Write-Host ('CTI mission/PIP discovery unavailable: ' + $_.Exception.Message) }
try {
    $gs = Invoke-RestMethod "$GssUrl/api/governance/correlation/missions/$MissionId" -TimeoutSec 15
    $snap = $gs.correlation_snapshot
    Write-Host 'GSS TARGET_RECON decisions (read-only):'
    foreach ($decision in @($snap.policy_decisions)) {
        if ($decision.decision -eq 'ALLOW') {
            $req = @($snap.authorization_requests | Where-Object { $_.request_id -eq $decision.request_id }) | Select-Object -First 1
            if ($req.action_class -eq 'TARGET_RECON') {
                Write-Host ('- ' + $decision.decision_id + ' / scope ' + $decision.scope_contract_id + ' / resource ' + $req.resource_value)
            }
        }
    }
} catch { Write-Host ('GSS correlation unavailable: ' + $_.Exception.Message) }
Write-Host 'No authorization, task, tool action, or target I/O performed by this read-only check.'
