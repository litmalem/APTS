param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8780,
    [string]$CtiFeedbackDb = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Starting Mission with the Stage 6.9 CTI feedback consumer on http://${BindHost}:$Port"
Write-Host "Stop the previous Mission process before restarting. Mission migration remains 53."
$runnerArgs = @("run\run_mission_orchestrator.py", "--host", $BindHost, "--port", "$Port")
if ($CtiFeedbackDb) { $runnerArgs += @("--cti-feedback-db", $CtiFeedbackDb) }
python @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Mission exited with code $LASTEXITCODE" }
