param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780",
    [string]$GovernanceBaseUrl = "http://127.0.0.1:8770"
)

$ErrorActionPreference = "Stop"

function Pass([string]$Message) { Write-Host "[PASS] $Message" -ForegroundColor Green }
function Fail([string]$Message) { Write-Host "[FAIL] $Message" -ForegroundColor Red; exit 1 }

function Get-HttpStatusForPost([string]$Uri, [string]$JsonBody) {
    try {
        $response = Invoke-WebRequest -Method Post -Uri $Uri -ContentType "application/json" -Body $JsonBody -UseBasicParsing
        return [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        throw
    }
}

function Get-GovernanceCorrelation([string]$MissionId) {
    $response = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/correlation/missions/$MissionId"
    if ($response.status -ne "completed" -or $null -eq $response.correlation_snapshot) {
        Fail "Governance correlation endpoint returned an invalid transport envelope"
    }
    return $response.correlation_snapshot
}

function New-ScopeBody(
    [string]$IdempotencyKey,
    [int]$ExpectedVersion,
    [int]$MaxActions,
    [int]$MaximumConcurrency,
    [string]$StartAt,
    [string]$EndAt
) {
    $obj = @{
        expected_contract_version = $ExpectedVersion
        idempotency_key = $IdempotencyKey
        actor = "stage3.1.4-acceptance"
        scope = @{
            targets = @(
                @{
                    target_type = "CIDR"
                    target_value = "127.0.0.0/8"
                    environment = "LAB"
                }
            )
            excluded_targets = @(
                @{
                    target_type = "IP"
                    target_value = "127.0.0.254"
                    environment = "LAB"
                }
            )
            network_ranges = @("127.0.0.0/8")
            domains = @("lab.example.test")
            services = @(
                @{
                    name = "https"
                    protocol = "TCP"
                    port = 443
                    target_ref = "lab.example.test"
                }
            )
        }
        roe = @{
            allowed_action_classes = @("TARGET_RECON", "VULNERABILITY_VALIDATION")
            prohibited_action_classes = @("DESTRUCTIVE_ACTION", "CREDENTIAL_USE")
            allowed_time_window = @{
                start_at = $StartAt
                end_at = $EndAt
            }
            maximum_concurrency = $MaximumConcurrency
            destructive_actions_allowed = $false
            credential_usage_allowed = $false
            persistence_allowed = $false
            human_approval_required_for = @("VULNERABILITY_VALIDATION")
        }
        constraints = @{
            max_actions = $MaxActions
            max_duration = 1800
            risk_threshold = "MODERATE"
            resource_budget = @{
                max_network_requests = 500
                max_parallel_targets = 2
            }
            data_handling_policy = @{
                classification = "INTERNAL"
                retention_days = 7
                export_allowed = $false
            }
        }
        reason = "Stage 3.1.4 acceptance canonical mission boundary"
        metadata = @{
            environment = "LAB"
            acceptance = "stage3.1.4"
        }
    }
    return ($obj | ConvertTo-Json -Depth 30)
}

function New-BindingBody(
    [string]$IdempotencyKey,
    [int]$ExpectedVersion,
    [string]$Name
) {
    $obj = @{
        expected_binding_version = $ExpectedVersion
        idempotency_key = $IdempotencyKey
        actor = "stage3.1.4-acceptance"
        policy_set_id = "default-policy"
        name = $Name
        capabilities = @(
            @{
                capability_id = "pentest.recon"
                subject_component = "PENTEST-A01"
                action_class = "TARGET_RECON"
                action_name = "recon"
                authorization_mode = "REQUIRED"
                resource_types = @("IP", "HOST", "DOMAIN")
                max_risk_level = "MODERATE"
                requires_human_approval = $false
            },
            @{
                capability_id = "pentest.validate"
                subject_component = "PENTEST-A02"
                action_class = "VULNERABILITY_VALIDATION"
                action_name = "validate"
                authorization_mode = "REQUIRED"
                resource_types = @("IP", "HOST", "DOMAIN")
                max_risk_level = "MODERATE"
                requires_human_approval = $true
            }
        )
        reason = "Bind exact canonical mission scope to authoritative aptsGSS"
        metadata = @{
            environment = "LAB"
            acceptance = "stage3.1.4"
        }
    }
    return ($obj | ConvertTo-Json -Depth 30)
}

function New-AuthorizationBody(
    [string]$IdempotencyKey,
    [string]$CapabilityId,
    [string]$ResourceValue
) {
    $obj = @{
        idempotency_key = $IdempotencyKey
        capability_id = $CapabilityId
        resource_type = "IP"
        resource_value = $ResourceValue
        context = @{
            environment = "LAB"
            reversible = $true
            blast_radius = 1
        }
        evidence_refs = @("evidence://stage3.1.4/acceptance/recon")
        requested_by = "stage3.1.4-acceptance"
        metadata = @{
            acceptance = "stage3.1.4"
        }
    }
    return ($obj | ConvertTo-Json -Depth 20)
}

Write-Host "=============================================================================="
Write-Host "Stage 3.1.4 - Governance & Authorization Binding Contract Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"
Write-Host "Governance           : $GovernanceBaseUrl"

Write-Host "`n[1] Full local regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Regression failed" }
Pass "Stage 3.1.1 + 3.1.2 + 3.1.3 + 3.1.4 regression"

Write-Host "`n[2] Mission Orchestrator health / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.component_id -ne "APTS-MO01") { Fail "Unexpected Mission Orchestrator component_id" }
if ($health.control_version -ne "stage3.1.4-governance-authorization-binding-contract") { Fail "Unexpected Stage-3.1.4 control_version" }
if ($health.supported_controls -notcontains "stage3.1.3-mission-scope-roe-constraint-contract") { Fail "Stage 3.1.3 disappeared from supported_controls" }
if ($health.governance_binding_enabled -ne $true) { Fail "Governance binding must be enabled in Stage 3.1.4" }
if ($health.governance_binding_mode -ne "CAPABILITY_BASED_DEFAULT_DENY_FAIL_CLOSED") { Fail "Unexpected Governance binding mode" }
if ($health.decision_provenance_mode -ne "AUTHORITATIVE_POLICYDECISION_IMMUTABLE_BINDING") { Fail "Unexpected decision provenance mode" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Mission Orchestrator must not become authorization authority" }
if ($health.governance_authority -ne "aptsGSS" -or $health.governance_authority_component -ne "GOV-PLANE") { Fail "Unexpected Governance authority identity" }
if ($health.pre_dispatch_revalidation_required -ne $true) { Fail "Pre-dispatch revalidation must remain mandatory" }
if ($health.dispatch_enabled -ne $false) { Fail "Stage 3.1.4 must not enable dispatch" }
if ($health.target_actuation -ne $false) { Fail "Stage 3.1.4 must not enable target actuation" }
Pass "Capability binding enabled while external Governance and execution boundaries remain intact"

Write-Host "`n[3] Authoritative Governance preflight"
$govHealth = Invoke-RestMethod "$GovernanceBaseUrl/health"
if ($govHealth.component_id -ne "GOV-PLANE") { Fail "Unexpected Governance component_id" }
if ($govHealth.health_status -eq "UNHEALTHY" -or $govHealth.readiness_status -eq "NOT_READY") {
    Fail "Governance is not ready (health=$($govHealth.health_status), readiness=$($govHealth.readiness_status))"
}
$emergency = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/emergency-stop"
if ($emergency.status -ne "completed" -or $null -eq $emergency.emergency_state) { Fail "Cannot read Governance emergency-stop state" }
if ([bool]$emergency.emergency_state.active) {
    Fail "Governance emergency stop is ACTIVE. Resolve it administratively; acceptance will not release a safety control."
}
Pass "GOV-PLANE is reachable and emergency stop is not active"

$token = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmss-fff")
$now = [DateTimeOffset]::UtcNow
$startAt = $now.AddMinutes(-5).ToString("o")
$endAt = $now.AddHours(2).ToString("o")

$missionBody = @{
    idempotency_key = "stage314-mission-$token"
    source_system = "POWERSHELL_ACCEPTANCE"
    created_by = "stage3.1.4-acceptance"
    client_request_id = "client-$token"
    mission_kind = "AUTONOMOUS_PENTEST"
    objective = @{
        type = "SECURITY_VALIDATION"
        target_ref = "lab-target-01"
    }
    success_criteria = @(
        @{ metric = "authorized_goal_complete"; expected = $true }
    )
    budgets = @{
        time_seconds = 1800
        max_actions = 20
        risk_ceiling = "MODERATE"
    }
    required_subsystems = @("CTI", "PENTEST")
    metadata = @{ environment = "LAB"; acceptance = "stage3.1.4" }
} | ConvertTo-Json -Depth 20

Write-Host "`n[4] Create canonical mission"
$created = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions" -ContentType "application/json" -Body $missionBody
$missionId = $created.canonical_identity.mission_id
$envelopeHash = $created.envelope.integrity.canonical_sha256
if (-not $missionId.StartsWith("mission-gmo-")) { Fail "Invalid canonical mission id" }
$stateBefore = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
if ($stateBefore.mission_state.state -ne "CREATED" -or $stateBefore.mission_state.state_version -ne 1) { Fail "Mission did not start in CREATED/v1" }
Pass "Mission created: $missionId"

Write-Host "`n[5] Create Stage-3.1.3 canonical Scope/RoE/Constraint v1"
$scopeV1Body = New-ScopeBody "stage314-scope-v1-$token" 0 20 2 $startAt $endAt
$scopeV1 = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/scope-contract" -ContentType "application/json" -Body $scopeV1Body
if ($scopeV1.contract_version -ne 1) { Fail "Expected scope contract v1" }
$scopeV1Snapshot = $scopeV1.snapshot_id
$scopeV1Hash = $scopeV1.canonical_sha256
if ($scopeV1Hash.Length -ne 64) { Fail "Invalid canonical scope hash" }
Pass "Canonical scope v1 created: $scopeV1Snapshot"

Write-Host "`n[6] Create capability-based Governance binding v1"
$bindingV1Body = New-BindingBody "stage314-bind-v1-$token" 0 "Stage 3.1.4 acceptance binding v1"
$bindingV1 = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/governance-binding" -ContentType "application/json" -Body $bindingV1Body
if ($bindingV1.status -ne "bound" -or $bindingV1.binding_version -ne 1) { Fail "Invalid Governance binding v1 response" }
if ($bindingV1.binding_current_for_scope -ne $true -or $bindingV1.binding_status -ne "CURRENT") { Fail "Binding v1 must be current for scope v1" }
if (-not $bindingV1.mission_governance_binding_id.StartsWith("mgbind-")) { Fail "Invalid mission_governance_binding_id" }
if ($bindingV1.binding.canonical_scope_binding.mission_scope_snapshot_id -ne $scopeV1Snapshot) { Fail "Binding does not reference exact canonical scope snapshot" }
if ($bindingV1.binding.canonical_scope_binding.mission_scope_sha256 -ne $scopeV1Hash) { Fail "Binding does not reference exact canonical scope hash" }
if ($bindingV1.binding.governance_authority.authorization_authority -ne "aptsGSS") { Fail "Binding authority is not aptsGSS" }
if ($bindingV1.binding.governance_authority.authorization_authority_component -ne "GOV-PLANE") { Fail "Binding authority component is not GOV-PLANE" }
if ($bindingV1.binding.semantics.binding_mode -ne "CAPABILITY_BASED") { Fail "Binding mode mismatch" }
if ($bindingV1.binding.semantics.default_effect -ne "DENY" -or $bindingV1.binding.semantics.fail_closed -ne $true) { Fail "Default-deny/fail-closed semantics missing" }
if ($bindingV1.binding.semantics.dispatch_enabled -ne $false -or $bindingV1.binding.semantics.target_actuation -ne $false) { Fail "Binding unexpectedly enabled execution" }
$govScopeIdV1 = $bindingV1.binding.governance_authority.governance_scope_contract_id
if (-not $govScopeIdV1.StartsWith("scope-")) { Fail "Invalid authoritative Governance scope id" }
Pass "Canonical scope snapshot bound to authoritative Governance scope: $govScopeIdV1"

Write-Host "`n[7] Verify authoritative projected scope and capability constraints"
$govScopeEnvelope = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/scope-contracts/$govScopeIdV1"
if ($govScopeEnvelope.status -ne "completed" -or $null -eq $govScopeEnvelope.scope_contract) { Fail "Invalid Governance scope response envelope" }
$govScope = $govScopeEnvelope.scope_contract
if ($govScope.mission_id -ne $missionId -or $govScope.status -ne "ACTIVE") { Fail "Authoritative Governance scope identity/status mismatch" }
if ($govScope.policy_set_id -ne "default-policy") { Fail "Unexpected Governance policy_set_id" }
if ($govScope.contract_hash -ne $bindingV1.binding.governance_authority.governance_scope_contract_hash) { Fail "External Governance scope hash differs from local immutable binding" }
$reconConstraint = @($govScope.action_constraints | Where-Object { $_.action_class -eq "TARGET_RECON" -and $_.action_name -eq "recon" })
$validateConstraint = @($govScope.action_constraints | Where-Object { $_.action_class -eq "VULNERABILITY_VALIDATION" -and $_.action_name -eq "validate" })
$hardDeny = @($govScope.action_constraints | Where-Object { $_.action_class -eq "DESTRUCTIVE_ACTION" -and $_.effect -eq "DENY" })
if ($reconConstraint.Count -ne 1 -or $reconConstraint[0].effect -ne "ALLOW") { Fail "TARGET_RECON capability was not projected as ALLOW" }
if ($validateConstraint.Count -ne 1 -or $validateConstraint[0].effect -ne "REVIEW" -or -not [bool]$validateConstraint[0].requires_approval) { Fail "VULNERABILITY_VALIDATION approval semantics were not preserved" }
if ($hardDeny.Count -lt 1) { Fail "Canonical DESTRUCTIVE_ACTION hard deny was not projected" }
if ($govScope.metadata.mission_scope_snapshot_id -ne $scopeV1Snapshot -or $govScope.metadata.mission_scope_sha256 -ne $scopeV1Hash) { Fail "Governance scope metadata lost canonical snapshot provenance" }
Pass "Authoritative scope preserves capabilities, approval, hard deny, and canonical provenance"

Write-Host "`n[8] Governance binding idempotency / no duplicate external scope"
$corrBeforeReplay = Get-GovernanceCorrelation $missionId
$scopeCountBeforeReplay = [int]$corrBeforeReplay.counts.scope_contracts
$bindingReplay = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/governance-binding" -ContentType "application/json" -Body $bindingV1Body
$corrAfterReplay = Get-GovernanceCorrelation $missionId
if ($bindingReplay.idempotent_replay -ne $true) { Fail "Identical binding retry must be idempotent replay" }
if ($bindingReplay.binding_snapshot_id -ne $bindingV1.binding_snapshot_id) { Fail "Binding replay changed immutable snapshot" }
if ($bindingReplay.binding.governance_authority.governance_scope_contract_id -ne $govScopeIdV1) { Fail "Binding replay changed authoritative Governance scope" }
if ([int]$corrAfterReplay.counts.scope_contracts -ne $scopeCountBeforeReplay) { Fail "Binding replay created duplicate Governance scope" }
Pass "Binding retry reuses the immutable local/external binding"

Write-Host "`n[9] Default deny before external Governance evaluation"
$corrBeforeDeny = Get-GovernanceCorrelation $missionId
$decisionsBeforeDeny = [int]$corrBeforeDeny.counts.policy_decisions
$requestsBeforeDeny = [int]$corrBeforeDeny.counts.authorization_requests

$unknownBody = New-AuthorizationBody "stage314-auth-unknown-$token" "pentest.not-bound" "127.0.0.1"
$unknownStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/authorization-bindings" $unknownBody
if ($unknownStatus -ne 403) { Fail "Unknown capability must fail closed with HTTP 403 (actual=$unknownStatus)" }

$excludedBody = New-AuthorizationBody "stage314-auth-excluded-$token" "pentest.recon" "127.0.0.254"
$excludedStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/authorization-bindings" $excludedBody
if ($excludedStatus -ne 403) { Fail "Explicitly excluded target must fail closed with HTTP 403 (actual=$excludedStatus)" }

$outsideBody = New-AuthorizationBody "stage314-auth-outside-$token" "pentest.recon" "10.10.10.10"
$outsideStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/authorization-bindings" $outsideBody
if ($outsideStatus -ne 403) { Fail "Out-of-scope target must fail closed with HTTP 403 (actual=$outsideStatus)" }

$corrAfterDeny = Get-GovernanceCorrelation $missionId
if ([int]$corrAfterDeny.counts.policy_decisions -ne $decisionsBeforeDeny) { Fail "Local default-deny path incorrectly created an external PolicyDecision" }
if ([int]$corrAfterDeny.counts.authorization_requests -ne $requestsBeforeDeny) { Fail "Local default-deny path incorrectly created an external authorization request" }
Pass "Unknown/excluded/out-of-scope requests are denied locally with zero Governance side effects"

Write-Host "`n[10] Authoritative ALLOW and immutable PolicyDecision provenance"
$authBody = New-AuthorizationBody "stage314-auth-allow-$token" "pentest.recon" "127.0.0.1"
$auth = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/authorization-bindings" -ContentType "application/json" -Body $authBody
if ($auth.status -ne "completed") { Fail "Authorization binding response is not completed" }
if ($auth.authorization_granted -ne $true) { Fail "Expected authoritative TARGET_RECON ALLOW in LAB scope" }
if ($auth.governance_status -ne "AUTHORIZED") { Fail "Expected governance_status=AUTHORIZED" }
if ($auth.execution_authorized -ne $false) { Fail "Stage 3.1.4 ALLOW must not become execution authorization" }
$authBinding = $auth.authorization_binding
if ($authBinding.pre_dispatch_revalidation_required -ne $true) { Fail "Pre-dispatch revalidation marker missing" }
if ($authBinding.dispatch_enabled -ne $false -or $authBinding.target_actuation -ne $false) { Fail "Authorization binding enabled dispatch/actuation" }
$prov = $authBinding.decision_provenance
if (-not $prov.authorization_request_id.StartsWith("greq-")) { Fail "Missing authoritative authorization request id" }
if (-not $prov.policy_decision_id.StartsWith("gdec-")) { Fail "Missing authoritative policy decision id" }
if ($prov.policy_decision_hash.Length -ne 64) { Fail "Invalid PolicyDecision hash" }
if ($prov.decision -ne "ALLOW") { Fail "Expected PolicyDecision ALLOW" }
if ($prov.policy_set_id -ne "default-policy" -or [int]$prov.policy_version -lt 1) { Fail "Policy provenance is incomplete" }
if ($prov.scope_contract_id -ne $govScopeIdV1 -or [int]$prov.scope_version -ne [int]$bindingV1.binding.governance_authority.governance_scope_version) { Fail "PolicyDecision does not bind to the exact authoritative scope" }
if ($prov.authorization_authority -ne "aptsGSS" -or $prov.authorization_authority_component -ne "GOV-PLANE") { Fail "PolicyDecision authority provenance mismatch" }
$decisionEnvelope = Invoke-RestMethod "$GovernanceBaseUrl/api/governance/decisions/$($prov.policy_decision_id)"
if ($decisionEnvelope.policy_decision.decision_hash -ne $prov.policy_decision_hash) { Fail "Local PolicyDecision hash differs from authoritative readback" }
if ($decisionEnvelope.policy_decision.request_id -ne $prov.authorization_request_id) { Fail "Local authorization request id differs from authoritative readback" }
Pass "Authoritative ALLOW provenance captured without execution authority"

Write-Host "`n[11] Authorization idempotency / no duplicate PolicyDecision"
$corrBeforeAuthReplay = Get-GovernanceCorrelation $missionId
$decisionCountBeforeReplay = [int]$corrBeforeAuthReplay.counts.policy_decisions
$authReplay = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/authorization-bindings" -ContentType "application/json" -Body $authBody
$corrAfterAuthReplay = Get-GovernanceCorrelation $missionId
if ($authReplay.idempotent_replay -ne $true) { Fail "Identical authorization retry must be idempotent replay" }
if ($authReplay.authorization_binding_id -ne $auth.authorization_binding_id) { Fail "Authorization replay changed local binding identity" }
if ($authReplay.authorization_binding.decision_provenance.policy_decision_id -ne $prov.policy_decision_id) { Fail "Authorization replay changed PolicyDecision identity" }
if ([int]$corrAfterAuthReplay.counts.policy_decisions -ne $decisionCountBeforeReplay) { Fail "Authorization replay created duplicate PolicyDecision" }
Pass "Authorization retry reuses one authoritative PolicyDecision"

Write-Host "`n[12] Stage-3.1.4 does not mutate envelope, mission state, or canonical scope v1"
$envelopeAfterAuth = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/envelope"
$stateAfterAuth = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
$scopeAfterAuth = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/scope-contract"
if ($envelopeAfterAuth.envelope.integrity.canonical_sha256 -ne $envelopeHash) { Fail "Governance binding mutated immutable mission envelope" }
if ($stateAfterAuth.mission_state.state -ne "CREATED" -or $stateAfterAuth.mission_state.state_version -ne 1) { Fail "Governance binding/authorization mutated mission state" }
if ($scopeAfterAuth.snapshot_id -ne $scopeV1Snapshot -or $scopeAfterAuth.canonical_sha256 -ne $scopeV1Hash) { Fail "Governance binding/authorization mutated canonical scope v1" }
Pass "Stage-3.1.1/3.1.2/3.1.3 canonical artifacts remain unchanged"

Write-Host "`n[13] Canonical scope revision makes old Governance binding stale"
$scopeV2Body = New-ScopeBody "stage314-scope-v2-$token" 1 10 1 $startAt $endAt
$scopeV2 = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/scope-contract" -ContentType "application/json" -Body $scopeV2Body
if ($scopeV2.contract_version -ne 2) { Fail "Expected canonical scope v2" }
$currentBindingAfterScopeChange = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/governance-binding"
if ($currentBindingAfterScopeChange.binding_status -ne "STALE_SCOPE" -or $currentBindingAfterScopeChange.binding_current_for_scope -ne $false) { Fail "Old Governance binding was not marked stale after scope revision" }
$corrBeforeStaleAuth = Get-GovernanceCorrelation $missionId
$staleDecisionCount = [int]$corrBeforeStaleAuth.counts.policy_decisions
$staleAuthBody = New-AuthorizationBody "stage314-auth-stale-$token" "pentest.recon" "127.0.0.1"
$staleStatus = Get-HttpStatusForPost "$MissionBaseUrl/api/missions/$missionId/authorization-bindings" $staleAuthBody
if ($staleStatus -ne 409) { Fail "Authorization through stale binding must return HTTP 409 (actual=$staleStatus)" }
$corrAfterStaleAuth = Get-GovernanceCorrelation $missionId
if ([int]$corrAfterStaleAuth.counts.policy_decisions -ne $staleDecisionCount) { Fail "Stale binding path created an external PolicyDecision" }
Pass "Scope revision invalidates old binding before Governance evaluation"

Write-Host "`n[14] Rebind revised scope as append-only Governance binding v2"
$bindingV2Body = New-BindingBody "stage314-bind-v2-$token" 1 "Stage 3.1.4 acceptance binding v2"
$bindingV2 = Invoke-RestMethod -Method Post -Uri "$MissionBaseUrl/api/missions/$missionId/governance-binding" -ContentType "application/json" -Body $bindingV2Body
if ($bindingV2.binding_version -ne 2 -or $bindingV2.binding_status -ne "CURRENT") { Fail "Expected current Governance binding v2" }
if ($bindingV2.mission_governance_binding_id -ne $bindingV1.mission_governance_binding_id) { Fail "Governance binding revision changed stable binding identity" }
if ($bindingV2.binding_snapshot_id -eq $bindingV1.binding_snapshot_id) { Fail "Governance binding v2 reused v1 immutable snapshot id" }
if ($bindingV2.binding.canonical_scope_binding.mission_scope_snapshot_id -ne $scopeV2.snapshot_id) { Fail "Governance binding v2 is not bound to canonical scope v2" }
if ($bindingV2.binding.governance_authority.governance_scope_contract_id -eq $govScopeIdV1) { Fail "Rebinding revised scope unexpectedly reused old external Governance scope" }
$bindingHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/governance-binding/history"
if ($bindingHistory.version_count -ne 2 -or $bindingHistory.current_binding_version -ne 2 -or $bindingHistory.current_binding_for_scope -ne $true) { Fail "Governance binding append-only history is invalid" }
if ($bindingHistory.versions[0].binding_version -ne 1 -or $bindingHistory.versions[1].binding_version -ne 2) { Fail "Governance binding history version sequence is invalid" }
Pass "Revised canonical scope has a new authoritative binding while preserving v1 history"

Write-Host "`n[15] Final provenance/read-model checks"
$authHistory = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/authorization-bindings/history"
if ($authHistory.authorization_binding_count -ne 1) { Fail "Expected exactly one persisted authorization decision binding" }
if ($authHistory.authorization_bindings[0].authorization_binding.decision_provenance.policy_decision_id -ne $prov.policy_decision_id) { Fail "Authorization history lost PolicyDecision provenance" }
$finalState = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/state"
$finalEnvelope = Invoke-RestMethod "$MissionBaseUrl/api/missions/$missionId/envelope"
if ($finalState.mission_state.state -ne "CREATED" -or $finalState.mission_state.state_version -ne 1) { Fail "Stage 3.1.4 changed mission lifecycle state" }
if ($finalEnvelope.envelope.integrity.canonical_sha256 -ne $envelopeHash) { Fail "Stage 3.1.4 changed immutable mission envelope" }
Pass "Decision history is durable and Stage 3.1.4 still has no lifecycle/dispatch side effect"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.1.4 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "MissionId        : $missionId"
Write-Host "Scope v1         : $scopeV1Snapshot"
Write-Host "Governance scope : $govScopeIdV1"
Write-Host "PolicyDecision   : $($prov.policy_decision_id)"
Write-Host "Binding current  : v$($bindingV2.binding_version)"
Write-Host "Dispatch enabled : $($health.dispatch_enabled)"
Write-Host "=============================================================================="
