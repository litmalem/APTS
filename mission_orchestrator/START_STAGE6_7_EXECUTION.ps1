param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8791,
    [string]$GovernanceUrl = "",
    [string]$CredentialLeasesFile = "",
    [string]$ExecutionDb = "",
    [string]$MissionDb = "",
    [string]$PentestDb = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Starting Stage 6.7 VEP Construction & Integrity on http://${BindHost}:$Port"
Write-Host "Stop the previous Execution process and back up its database before upgrading."
Write-Host "Execution migration 7; Mission 53 / Pentest 16 remain read-only."
$runnerArgs = @("run\execution_vep.py", "--host", $BindHost, "--port", "$Port")
if ($GovernanceUrl) { $runnerArgs += @("--governance-url", $GovernanceUrl) }
if ($CredentialLeasesFile) { $runnerArgs += @("--credential-leases-file", $CredentialLeasesFile) }
if ($ExecutionDb) { $runnerArgs += @("--execution-db", $ExecutionDb) }
if ($MissionDb) { $runnerArgs += @("--mission-db", $MissionDb) }
if ($PentestDb) { $runnerArgs += @("--pentest-db", $PentestDb) }
python @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Stage 6.7 execution subsystem exited with code $LASTEXITCODE" }
