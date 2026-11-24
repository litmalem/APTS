param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8780,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Url = "http://${HostAddress}:${Port}/ui/"
Write-Host "APTS Phase-2 Guarded Human Interaction Mission Console" -ForegroundColor Cyan
Write-Host "Mission API : http://${HostAddress}:${Port}" -ForegroundColor DarkCyan
Write-Host "Console     : $Url" -ForegroundColor Green
Write-Host "Mode        : GUARDED HUMAN INTERACTION" -ForegroundColor Yellow
Write-Host "Governance  : VISIBILITY ONLY; approval/authorization remains external" -ForegroundColor DarkYellow

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($Target)
        Start-Sleep -Seconds 2
        Start-Process $Target
    } -ArgumentList $Url | Out-Null
}

& $Python ".\run\run_mission_orchestrator.py" --host $HostAddress --port $Port
