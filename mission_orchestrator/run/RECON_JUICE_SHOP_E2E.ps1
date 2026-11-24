[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$MissionId,
    [string]$ReconRunId,
    [string]$ActionId,
    [string]$ExpectedTarget = 'http://localhost:3000/',
    [string]$Operator = 'operator-admin-01',
    [string]$MissionRoot = 'D:\mission_orchestrator',
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $MissionRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
$runner = Join-Path $MissionRoot 'run\recon_collector_bridge.py'
if (-not (Test-Path $runner)) { throw 'Install the Recon collector bridge first.' }
$pentest = 'http://127.0.0.1:8790'
$stage6 = 'http://127.0.0.1:8791'
function Get-Json([string]$uri) {
    try { return Invoke-RestMethod -Uri $uri -Method Get -TimeoutSec 15 -ErrorAction Stop }
    catch { throw "Service/API unavailable at $uri : $_" }
}
Write-Host '===== APTS Recon → Stage 6 → Recon iteration =====' -ForegroundColor Cyan
$pentestHealth = Get-Json "$pentest/health"
$stage6Health = Get-Json "$stage6/health"
if ($pentestHealth.status -ne 'ok' -or $stage6Health.status -ne 'ok') {
    throw 'Pentest or Stage 6 health is degraded. No collector dispatch.'
}
$stage6Contract = Get-Json "$stage6/api/contracts/recon-execution-result"
Write-Host ('Pentest: ' + $pentestHealth.status + ' | Stage 6: ' + $stage6Health.status)
Write-Host ('Stage 6 Recon result contract: ' + $stage6Contract.status)
Write-Host 'NOTE: tool adapter is bounded TCP_CONNECT_SCAN (one TCP connection), not an HTTP vulnerability crawler.'
if ([string]::IsNullOrWhiteSpace($ReconRunId) -or [string]::IsNullOrWhiteSpace($ActionId)) {
    Write-Host 'Discovering stored Recon Action Requests (NO target/network execution performed)...' -ForegroundColor Yellow
    $runs = Get-Json "$pentest/api/pentest/reconnaissance-runs?mission_id=$([uri]::EscapeDataString($MissionId))&limit=100"
    $rows = @(
        foreach ($run in @($runs.reconnaissance_runs)) {
            foreach ($action in @($run.output.action_requests)) {
                [pscustomobject]@{
                    ReconRunId=$run.recon_run_id
                    ActionId=$action.action_id
                    Technique=$action.technique
                    Target=$action.target_ref.target_value
                    RunStatus=$run.run_status
                }
            }
        }
    )
    if ($rows.Count -gt 0) { $rows | Format-Table -AutoSize | Out-Host }
    else { Write-Host '[BLOCKED] No persisted Action Request for this mission. First run Recon in Pentest Workspace with explicit TCP_CONNECT_SCAN RoE.' }
    Write-Host '[INFO] Select -ReconRunId and -ActionId from the table; nothing has been executed.'
    return
}
$artifactDir = Join-Path $MissionRoot 'evidence\recon_collector_e2e'
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$output = Join-Path $artifactDir "recon_juice_shop_$timestamp.json"
$cmd = @(
    $runner, '--mission-id',$MissionId, '--recon-run-id',$ReconRunId,
    '--action-id',$ActionId, '--expect-target',$ExpectedTarget,
    '--operator',$Operator, '--pentest-api',$pentest, '--execution-api',$stage6,
    '--output',$output, '--timeout','120'
)
if ($Execute) {
    Write-Host 'LIVE EXECUTION: this requests actual Stage 6 authorization and one governed TCP_CONNECT_SCAN.' -ForegroundColor Yellow
    Write-Host 'Only proceed for OWASP Juice Shop in an expressly authorized lab scope.'
    $cmd += @('--execute','--ack-authorized-lab')
} else {
    Write-Host 'PREFLIGHT ONLY: no gateway submission, no collector target I/O.' -ForegroundColor Yellow
}
& $python @cmd
if ($LASTEXITCODE -ne 0) { throw "E2E did not PASS (exit $LASTEXITCODE). Inspect GSS, lifecycle, RoE, adapter policy, and Stage 6 logs." }
$result = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
if ($Execute) {
    if ($result.status -ne 'COMPLETED' -or -not $result.evidence_manifest_sha256 -or -not $result.child_recon_run_id) {
        throw 'E2E result lacks mandatory sealed evidence/Recon iteration fields.'
    }
    $source = Get-Json "$stage6/api/execution/recon-action-requests/$([uri]::EscapeDataString($ActionId))/results"
    if ($source.latest_result.evidence.capture_status -ne 'SEALED' -or
        $source.latest_result.evidence.manifest_sha256 -ne $result.evidence_manifest_sha256) {
        throw 'E2E evidence manifest does not match authoritative Stage 6 read model.'
    }
    $child = Get-Json "$pentest/api/pentest/reconnaissance-runs/$([uri]::EscapeDataString($result.child_recon_run_id))"
    if ($child.run.source_action_id -ne $ActionId -or
        $child.run.source_result_sha256 -ne $result.result_sha256 -or
        $child.run.parent_recon_run_id -ne $ReconRunId) {
        throw 'E2E child Recon run lineage does not match the verified Stage 6 result.'
    }
    Write-Host ('[PASS] Stage 6 sealed evidence + Recon iteration. Report: ' + $output) -ForegroundColor Green
} else {
    Write-Host ('[PASS] Non-executing preflight. Report: ' + $output) -ForegroundColor Green
}
