param(
    [string]$GovernanceUrl = "http://127.0.0.1:8770",
    [switch]$SourceOnly,
    [string]$DatabaseConfig = "",
    [string]$SchemaDump = "",
    [string]$Output = "evidence/gss_approval_fix"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$acceptanceArgs = @("scripts/gss_approval_acceptance.py", "--output", $Output)
if (-not $SourceOnly) { $acceptanceArgs += @("--governance-url", $GovernanceUrl) }
if ($DatabaseConfig) { $acceptanceArgs += @("--database-config", $DatabaseConfig) }
if ($SchemaDump) { $acceptanceArgs += @("--schema-dump", $SchemaDump) }
python @acceptanceArgs
if ($LASTEXITCODE -ne 0) { throw "GSS human approval acceptance failed; inspect $Output/acceptance_summary.json" }
