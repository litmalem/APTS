param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8791
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Starting APTS Execution Subsystem Stage 6.1 on http://${BindHost}:$Port"
Write-Host "Mode: canonical request intake; authorization and dispatch are disabled"
Write-Host "Pentest proposal source: APTS_PENTEST_DB or data\pentest_subsystem.db (read-only)"
Write-Host "Execution requests: APTS_EXECUTION_DB or data\execution_subsystem.db"
python run\execution_subsystem.py --host $BindHost --port $Port
if ($LASTEXITCODE -ne 0) { throw "Execution Subsystem exited with code $LASTEXITCODE" }
