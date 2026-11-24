param(
    [string]$BindHost = "127.0.0.1", [int]$Port = 8791,
    [string]$GovernanceUrl = "", [string]$CredentialLeasesFile = "",
    [string]$ExecutionDb = "", [string]$MissionDb = "", [string]$PentestDb = "", [string]$CtiFeedbackDb = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Starting APTS Stage 6.10 on http://${BindHost}:$Port"
Write-Host "Stop the previous Execution process before starting. Migration remains Execution 9 / CTI 1."
$runnerArgs = @("run\execution_apts_acceptance.py", "--host", $BindHost, "--port", "$Port")
if ($GovernanceUrl) { $runnerArgs += @("--governance-url", $GovernanceUrl) }
if ($CredentialLeasesFile) { $runnerArgs += @("--credential-leases-file", $CredentialLeasesFile) }
if ($ExecutionDb) { $runnerArgs += @("--execution-db", $ExecutionDb) }
if ($MissionDb) { $runnerArgs += @("--mission-db", $MissionDb) }
if ($PentestDb) { $runnerArgs += @("--pentest-db", $PentestDb) }
if ($CtiFeedbackDb) { $runnerArgs += @("--cti-feedback-db", $CtiFeedbackDb) }
python @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Stage 6.10 Execution exited with code $LASTEXITCODE" }
