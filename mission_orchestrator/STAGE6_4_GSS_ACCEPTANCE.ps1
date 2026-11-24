param([string]$GovernanceUrl = "http://127.0.0.1:8770")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Stage 6.4 - GOV-PLANE Execution Revalidation Compatibility"
$health=Invoke-RestMethod "$GovernanceUrl/health" -TimeoutSec 15
if ($health.status -ne "ok" -or $health.component_id -ne "GOV-PLANE" -or $health.execution_revalidation_schema_version -ne "apts-gss-execution-revalidation-v1") { throw "GSS execution protocol is not active" }
if (($health.execution_revalidation_checks -join ",") -ne "SCOPE,ROE,POLICY,RISK,EXPIRY,REVOCATION,TARGET,TECHNIQUE") { throw "GSS mandatory checks mismatch" }
python scripts/gss_approval_acceptance.py --governance-url $GovernanceUrl
if ($LASTEXITCODE -ne 0) { throw "Updated GSS source / human approval acceptance failed" }
Write-Host "STAGE 6.4 GSS SOURCE / PROTOCOL ACCEPTANCE: PASS"
Write-Host "This gate checks source, tests, and live protocol health; no user mission is authorized or dispatched."
