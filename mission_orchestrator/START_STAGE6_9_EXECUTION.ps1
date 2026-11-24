param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8791,
    [string]$GovernanceUrl = "",
    [string]$CredentialLeasesFile = "",
    [string]$ExecutionDb = "",
    [string]$MissionDb = "",
    [string]$PentestDb = "",
    [string]$CtiFeedbackDb = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Starting Stage 6.9 Closed-Loop CTI / Pentest Integration on http://${BindHost}:$Port"
Write-Host "Stop the previous Execution process and back up its database before upgrading."
Write-Host "Execution migration 9; CTI feedback migration 1; Mission owns its guarded feedback intake."
$runnerArgs = @("run\execution_cti_feedback.py", "--host", $BindHost, "--port", "$Port")
if ($GovernanceUrl) { $runnerArgs += @("--governance-url", $GovernanceUrl) }
if ($CredentialLeasesFile) { $runnerArgs += @("--credential-leases-file", $CredentialLeasesFile) }
if ($ExecutionDb) { $runnerArgs += @("--execution-db", $ExecutionDb) }
if ($MissionDb) { $runnerArgs += @("--mission-db", $MissionDb) }
if ($PentestDb) { $runnerArgs += @("--pentest-db", $PentestDb) }
if ($CtiFeedbackDb) { $runnerArgs += @("--cti-feedback-db", $CtiFeedbackDb) }
python @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Stage 6.9 execution subsystem exited with code $LASTEXITCODE" }
