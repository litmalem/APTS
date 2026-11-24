param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8791,
    [string]$GovernanceUrl = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Starting APTS Execution Gateway Stage 6.3 on http://${BindHost}:$Port"
Write-Host "Fresh external authorization and central admission policy enabled"
Write-Host "Mission 53 / Pentest 16 remain read-only; Execution upgrades atomically to migration 3"
Write-Host "Admission is audit only. Target dispatch requires Stage 6.4 adapters and fresh revalidation"
if ($GovernanceUrl) {
    python run\execution_gateway.py --host $BindHost --port $Port --governance-url $GovernanceUrl
} else {
    python run\execution_gateway.py --host $BindHost --port $Port
}
if ($LASTEXITCODE -ne 0) { throw "Stage 6.3 execution gateway exited with code $LASTEXITCODE" }
