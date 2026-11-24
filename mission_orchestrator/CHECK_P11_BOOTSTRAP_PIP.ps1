param(
    [Parameter(Mandatory=$true)][string]$PipId,
    [string]$CtiUrl = 'http://127.0.0.1:8765'
)
$ErrorActionPreference = 'Stop'
$uri = "$($CtiUrl.TrimEnd('/'))/api/cti/pip/$([uri]::EscapeDataString($PipId))"
$data = Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 20
if ($data.status -ne 'completed' -or $null -eq $data.pip) { throw 'CTI PIP unavailable' }
$p = $data.pip
$a = $p.artifact
$now = (Get-Date).ToUniversalTime()
$issued = [datetimeoffset]::Parse($a.created_at)
$remaining = [math]::Floor(3600 - ($now - $issued.UtcDateTime).TotalSeconds)
$gates = @($p.validation_results)
$asset = @($a.intelligence.asset_profiles)
$results = [pscustomobject]@{
    PipId = $p.pip_id
    MissionId = $p.mission_id
    Readiness = $p.readiness
    PublishedReadiness = $p.published_readiness
    Immutable = $p.immutable
    HardGatesPassed = $a.quality.hard_gate_passed
    GateCount = $gates.Count
    GateFailures = @($gates | Where-Object { $_.passed -ne $true }).Count
    AssetProfiles = $asset.Count
    Correlations = @($a.intelligence.vulnerability_correlations).Count
    RiskPriorities = @($a.intelligence.risk_priorities).Count
    SHA256 = $p.canonical_sha256
    IssuedUTC = $issued.UtcDateTime.ToString('o')
    FreshnessSecondsRemaining = $remaining
}
$results | Format-List
$asset | Select-Object asset_profile_id,mission_id,asset_id,verification_status,confidence,observed_at,evidence_refs,observed_attributes | Format-List
Write-Host 'READ-ONLY CTI metadata check. Does not recompute SHA, query GSS, or grant bootstrap eligibility.'
Write-Host 'Authoritative eligibility and GSS revalidation occur during Stage 4.3 materialization.'
