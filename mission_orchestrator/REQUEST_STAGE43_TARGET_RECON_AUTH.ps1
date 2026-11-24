param(
    [string]$MissionId = 'mission-gmo-7e856bbd-8160-4103-9ad8-8f4ad5378253',
    [Parameter(Mandatory=$true)][string]$ScopeContractId,
    [string]$TargetUrl = 'http://localhost:3000/',
    [string]$RequestedBy = 'operator-admin-01',
    [string]$GssUrl = 'http://127.0.0.1:8770'
)
$ErrorActionPreference='Stop'
if ($TargetUrl -notmatch '^http://(localhost|127\.0\.0\.1):3000/$') {
    throw 'Only the configured OWASP Juice Shop LAB target http://localhost:3000/ or http://127.0.0.1:3000/ is supported by this helper.'
}
$body = @{
    mission_id=$MissionId
    scope_contract_id=$ScopeContractId
    subject_component='PENTEST-SUB01'
    action_class='TARGET_RECON'
    action_name='recon'
    resource_type='URL'
    resource_value=$TargetUrl
    context=@{ authorization_purpose='STAGE43_TARGET_RECON'; target_actuation_requested=$false }
    evidence_refs=@("mission://$MissionId/pentest-stage43")
    requested_by=$RequestedBy
}
$resp = Invoke-RestMethod -Uri "$GssUrl/api/governance/authorization/evaluate" -Method POST `
    -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 12) -TimeoutSec 40
$resp.policy_decision | Select-Object decision_id, decision, decision_status, scope_contract_id, scope_version, reason_codes |
    ConvertTo-Json -Depth 8
if ($resp.policy_decision.decision -ne 'ALLOW') {
    throw 'GSS has not authorized TARGET_RECON. Check RoE/policy/human approval. Do not materialize the Pentest task.'
}
Write-Host 'GSS returned ALLOW, subject to Stage 4.3 revalidation. This script did not contact the target.'
