param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8791,
    [string]$GovernanceUrl = "",
    [string]$CredentialLeasesFile = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Starting Stage 6.4 Authorized Tool Adapters & Sandboxing on http://${BindHost}:$Port"
Write-Host "Execution database upgrades atomically to migration 4; Mission 53 / Pentest 16 remain read-only"
Write-Host "Only server-registered primitives can run after fresh external GSS revalidation"
$runnerArgs = @("run\execution_adapters.py", "--host", $BindHost, "--port", "$Port")
if ($GovernanceUrl) { $runnerArgs += @("--governance-url", $GovernanceUrl) }
if ($CredentialLeasesFile) { $runnerArgs += @("--credential-leases-file", $CredentialLeasesFile) }
python @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Stage 6.4 execution subsystem exited with code $LASTEXITCODE" }
