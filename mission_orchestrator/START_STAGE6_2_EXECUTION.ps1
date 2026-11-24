param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8791,
    [string]$GovernanceUrl = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Starting APTS Execution Subsystem Stage 6.2 on http://${BindHost}:$Port"
Write-Host "Authoritative revalidation enabled; gateway/tool/target actuation require Stage 6.3+"
Write-Host "Sources: current Mission migration 53 and Pentest migration 16, both read-only"
Write-Host "Execution store upgrades atomically from migration 1 to 2"
if ($GovernanceUrl) {
    python run\execution_authorization.py --host $BindHost --port $Port --governance-url $GovernanceUrl
} else {
    python run\execution_authorization.py --host $BindHost --port $Port
}
if ($LASTEXITCODE -ne 0) { throw "Stage 6.2 execution service exited with code $LASTEXITCODE" }
