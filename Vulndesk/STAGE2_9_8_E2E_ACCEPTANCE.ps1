[CmdletBinding()]
param(
    [string]$CtiBaseUrl = "http://127.0.0.1:8765",
    [string]$GovernanceBaseUrl = "http://127.0.0.1:8770",
    [string]$TargetUrl = "http://127.0.0.1:3000",
    [string]$CtiSource = "mitre-attack",
    [string]$MissionId = "",
    [switch]$ReuseExistingMission,
    [int]$MissionTimeoutSeconds = 120,
    [int]$CorrelationTimeoutSeconds = 45,
    [int]$OutboxTimeoutSeconds = 45,
    [int]$PollIntervalSeconds = 2,
    [int]$RestTimeoutSeconds = 15,
    [string]$EvidenceRoot = ".\stage2_9_8_evidence",
    [string]$ExpectedArchitectureVersion = "2026-08-harmonized",
    [string]$ExpectedControlVersion = "hybrid-event-driven-2.17-health-diagnostics",
    [string]$PythonExe = "python",
    [switch]$SkipRegression,
    [switch]$SkipFullRegression
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$script:Checks = New-Object System.Collections.Generic.List[object]
$script:EvidenceDir = $null
$script:FinalStatus = "FAIL"
$script:StartedAt = (Get-Date).ToUniversalTime()

function Write-Section {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
}

function Add-Check {
    param(
        [string]$Stage,
        [string]$Name,
        [string]$Status,
        [string]$Detail,
        [bool]$Mandatory = $true
    )

    $item = [pscustomobject]@{
        stage     = $Stage
        name      = $Name
        status    = $Status
        mandatory = $Mandatory
        detail    = $Detail
    }
    $script:Checks.Add($item) | Out-Null

    $color = "Gray"
    if ($Status -eq "PASS") { $color = "Green" }
    elseif ($Status -eq "FAIL") { $color = "Red" }
    elseif ($Status -eq "WARN") { $color = "Yellow" }
    elseif ($Status -eq "SKIP") { $color = "DarkYellow" }

    Write-Host ("[{0}] [{1}] {2} - {3}" -f $Status, $Stage, $Name, $Detail) -ForegroundColor $color
}

function Require-Check {
    param(
        [string]$Stage,
        [string]$Name,
        [bool]$Condition,
        [string]$PassDetail,
        [string]$FailDetail
    )

    if ($Condition) {
        Add-Check -Stage $Stage -Name $Name -Status "PASS" -Detail $PassDetail -Mandatory $true
        return
    }

    Add-Check -Stage $Stage -Name $Name -Status "FAIL" -Detail $FailDetail -Mandatory $true
    throw "Mandatory acceptance check failed: [$Stage] $Name :: $FailDetail"
}

function Test-HasText {
    param($Value)
    if ($null -eq $Value) { return $false }
    return -not [string]::IsNullOrWhiteSpace([string]$Value)
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Save-Json {
    param(
        [string]$Name,
        $Object
    )
    if (-not $script:EvidenceDir) { return }
    $path = Join-Path $script:EvidenceDir $Name
    $Object | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $path -Encoding UTF8
}

function Save-Text {
    param(
        [string]$Name,
        [string[]]$Lines
    )
    if (-not $script:EvidenceDir) { return }
    $path = Join-Path $script:EvidenceDir $Name
    $Lines | Set-Content -LiteralPath $path -Encoding UTF8
}

function Invoke-ApiGet {
    param([string]$Uri)
    return Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec $RestTimeoutSeconds
}

function Invoke-ApiPostJson {
    param(
        [string]$Uri,
        $Body
    )
    $json = $Body | ConvertTo-Json -Depth 50
    return Invoke-RestMethod `
        -Method Post `
        -Uri $Uri `
        -ContentType "application/json" `
        -Body $json `
        -TimeoutSec $RestTimeoutSeconds
}

function Get-Sha256Hex {
    param([string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hash = $sha.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-SemanticHash {
    param($Object)
    $json = $Object | ConvertTo-Json -Depth 50 -Compress
    return Get-Sha256Hex -Text $json
}

function Invoke-Regression {
    if ($SkipRegression) {
        Add-Check -Stage "REGRESSION" -Name "VulnDesk regression" -Status "SKIP" -Detail "Skipped by -SkipRegression." -Mandatory $false
        return
    }

    Write-Section "Local regression gate"

    $requiredTestFiles = @(
        ".\tests\test_health_diagnostics_stage2_9_6.py",
        ".\tests\test_integrity_violation_probe_stage2_9_5.py",
        ".\tests\test_cross_subsystem_lineage_stage2_8_8.py"
    )

    foreach ($testFile in $requiredTestFiles) {
        Require-Check `
            -Stage "REGRESSION" `
            -Name ("Test file present: {0}" -f $testFile) `
            -Condition (Test-Path -LiteralPath $testFile) `
            -PassDetail "Found." `
            -FailDetail "Run this script from the VulnDesk repository root (normally D:\vulndesk)."
    }

    $compileTarget = ".\cti_services\cti_subsystem_orchestrator.py"
    Require-Check `
        -Stage "REGRESSION" `
        -Name "Orchestrator source present" `
        -Condition (Test-Path -LiteralPath $compileTarget) `
        -PassDetail $compileTarget `
        -FailDetail "Missing $compileTarget"

    $compileLog = Join-Path $script:EvidenceDir "01_py_compile.log"
    $compileOutput = @(& $PythonExe -m py_compile $compileTarget 2>&1)
    $compileRc = $LASTEXITCODE
    $compileOutput | Set-Content -LiteralPath $compileLog -Encoding UTF8
    Require-Check `
        -Stage "REGRESSION" `
        -Name "Python compile" `
        -Condition ($compileRc -eq 0) `
        -PassDetail "cti_subsystem_orchestrator.py compiles." `
        -FailDetail ("py_compile exit code {0}. See {1}" -f $compileRc, $compileLog)

    $focusedLog = Join-Path $script:EvidenceDir "02_focused_pytest.log"
    $focusedOutput = @(& $PythonExe -m pytest -q $requiredTestFiles 2>&1)
    $focusedRc = $LASTEXITCODE
    $focusedOutput | Set-Content -LiteralPath $focusedLog -Encoding UTF8
    Require-Check `
        -Stage "REGRESSION" `
        -Name "Focused Stage 2.8.8/2.9.5/2.9.6 regression" `
        -Condition ($focusedRc -eq 0) `
        -PassDetail "Focused regression passed." `
        -FailDetail ("pytest exit code {0}. See {1}" -f $focusedRc, $focusedLog)

    if ($SkipFullRegression) {
        Add-Check -Stage "REGRESSION" -Name "Full VulnDesk pytest suite" -Status "SKIP" -Detail "Skipped by -SkipFullRegression." -Mandatory $false
        return
    }

    $fullLog = Join-Path $script:EvidenceDir "03_full_pytest.log"
    $fullOutput = @(& $PythonExe -m pytest -q 2>&1)
    $fullRc = $LASTEXITCODE
    $fullOutput | Set-Content -LiteralPath $fullLog -Encoding UTF8
    Require-Check `
        -Stage "REGRESSION" `
        -Name "Full VulnDesk pytest suite" `
        -Condition ($fullRc -eq 0) `
        -PassDetail "Full regression passed." `
        -FailDetail ("pytest exit code {0}. See {1}" -f $fullRc, $fullLog)
}

function Get-RuntimeSnapshot {
    $ctiHealth = Invoke-ApiGet -Uri ("{0}/health" -f $CtiBaseUrl)
    $ctiDiag = Invoke-ApiGet -Uri ("{0}/api/cti/diagnostics?deep=true" -f $CtiBaseUrl)
    $govHealth = Invoke-ApiGet -Uri ("{0}/health" -f $GovernanceBaseUrl)
    $govDiag = Invoke-ApiGet -Uri ("{0}/api/governance/diagnostics?deep=true" -f $GovernanceBaseUrl)
    $outbox = Invoke-ApiGet -Uri ("{0}/api/governance/outbox/status?limit=200" -f $GovernanceBaseUrl)

    return [pscustomobject]@{
        cti_health = $ctiHealth
        cti_diagnostics = $ctiDiag
        governance_health = $govHealth
        governance_diagnostics = $govDiag
        governance_outbox = $outbox
    }
}

function Assert-RuntimeReady {
    param(
        $Snapshot,
        [string]$Prefix
    )

    Require-Check -Stage "2.9.6" -Name "$Prefix CTI /health status" `
        -Condition ($Snapshot.cti_health.status -eq "ok") `
        -PassDetail "CTI runtime status=ok." `
        -FailDetail ("CTI runtime status={0}" -f $Snapshot.cti_health.status)

    Require-Check -Stage "2.9.6" -Name "$Prefix CTI architecture version" `
        -Condition ($Snapshot.cti_health.architecture_version -eq $ExpectedArchitectureVersion) `
        -PassDetail ("architecture_version={0}" -f $Snapshot.cti_health.architecture_version) `
        -FailDetail ("Expected {0}; got {1}" -f $ExpectedArchitectureVersion, $Snapshot.cti_health.architecture_version)

    Require-Check -Stage "2.9.6" -Name "$Prefix CTI control version" `
        -Condition ($Snapshot.cti_health.control_version -eq $ExpectedControlVersion) `
        -PassDetail ("control_version={0}" -f $Snapshot.cti_health.control_version) `
        -FailDetail ("Expected {0}; got {1}. Override with -ExpectedControlVersion only if the runtime was intentionally version-bumped." -f $ExpectedControlVersion, $Snapshot.cti_health.control_version)

    Require-Check -Stage "2.9.6" -Name "$Prefix CTI readiness" `
        -Condition ($Snapshot.cti_diagnostics.diagnostics.readiness_status -eq "READY") `
        -PassDetail "CTI deep diagnostics readiness=READY." `
        -FailDetail ("CTI readiness={0}" -f $Snapshot.cti_diagnostics.diagnostics.readiness_status)

    Require-Check -Stage "2.9.6" -Name "$Prefix CTI mandatory diagnostics" `
        -Condition ([int]$Snapshot.cti_diagnostics.diagnostics.summary.mandatory_fail_count -eq 0) `
        -PassDetail "CTI mandatory_fail_count=0." `
        -FailDetail ("CTI mandatory_fail_count={0}" -f $Snapshot.cti_diagnostics.diagnostics.summary.mandatory_fail_count)

    Require-Check -Stage "2.9.6" -Name "$Prefix governance /health" `
        -Condition (($Snapshot.governance_health.status -eq "ok") -or ($Snapshot.governance_health.status -eq "healthy")) `
        -PassDetail ("Governance status={0}." -f $Snapshot.governance_health.status) `
        -FailDetail ("Governance status={0}" -f $Snapshot.governance_health.status)

    Require-Check -Stage "2.9.6" -Name "$Prefix governance readiness" `
        -Condition ($Snapshot.governance_diagnostics.diagnostics.readiness_status -eq "READY") `
        -PassDetail "Governance deep diagnostics readiness=READY." `
        -FailDetail ("Governance readiness={0}" -f $Snapshot.governance_diagnostics.diagnostics.readiness_status)

    Require-Check -Stage "2.9.6" -Name "$Prefix governance mandatory diagnostics" `
        -Condition ([int]$Snapshot.governance_diagnostics.diagnostics.summary.mandatory_fail_count -eq 0) `
        -PassDetail "Governance mandatory_fail_count=0." `
        -FailDetail ("Governance mandatory_fail_count={0}" -f $Snapshot.governance_diagnostics.diagnostics.summary.mandatory_fail_count)

    Require-Check -Stage "2.9.6" -Name "$Prefix governance outbox pending" `
        -Condition ([int]$Snapshot.governance_outbox.stats.pending -eq 0) `
        -PassDetail "pending=0." `
        -FailDetail ("pending={0}" -f $Snapshot.governance_outbox.stats.pending)

    Require-Check -Stage "2.9.6" -Name "$Prefix governance outbox failed" `
        -Condition ([int]$Snapshot.governance_outbox.stats.failed -eq 0) `
        -PassDetail "failed=0." `
        -FailDetail ("failed={0}" -f $Snapshot.governance_outbox.stats.failed)
}

function Wait-MissionTerminal {
    param([string]$Id)
    $deadline = (Get-Date).AddSeconds($MissionTimeoutSeconds)
    $last = $null

    while ((Get-Date) -lt $deadline) {
        $last = Invoke-ApiGet -Uri ("{0}/api/cti/missions/{1}" -f $CtiBaseUrl, [uri]::EscapeDataString($Id))
        $status = [string]$last.mission.status
        Write-Host ("Mission {0}: {1}" -f $Id, $status) -ForegroundColor DarkGray

        if ($status -eq "COMPLETED") { return $last }
        if (@("FAILED", "BLOCKED", "REVOKED", "CANCELLED") -contains $status) { return $last }
        Start-Sleep -Seconds $PollIntervalSeconds
    }

    return $last
}

function Wait-Correlation {
    param([string]$Id)
    $deadline = (Get-Date).AddSeconds($CorrelationTimeoutSeconds)
    $last = $null

    while ((Get-Date) -lt $deadline) {
        $last = Invoke-ApiGet -Uri ("{0}/api/cti/missions/{1}/lineage" -f $CtiBaseUrl, [uri]::EscapeDataString($Id))
        $status = [string]$last.lineage.governance_correlation.status
        if ($status -eq "CORRELATED") { return $last }
        Start-Sleep -Seconds $PollIntervalSeconds
    }

    return $last
}

function Wait-OutboxSettled {
    $deadline = (Get-Date).AddSeconds($OutboxTimeoutSeconds)
    $last = $null

    while ((Get-Date) -lt $deadline) {
        $last = Invoke-ApiGet -Uri ("{0}/api/governance/outbox/status?limit=200" -f $GovernanceBaseUrl)
        if (([int]$last.stats.pending -eq 0) -and ([int]$last.stats.failed -eq 0)) {
            return $last
        }
        Start-Sleep -Seconds $PollIntervalSeconds
    }

    return $last
}

function Get-MissionSemanticView {
    param($LineageResponse)
    $facts = $LineageResponse.lineage.governance_correlation.correlation_facts
    $meta = $LineageResponse.lineage.projection_metadata
    return [ordered]@{
        mission_id = $LineageResponse.lineage.mission_id
        quality = $meta.quality
        task_count = $meta.task_count
        event_count = $meta.event_count
        causal_edge_count = $meta.causal_edge_count
        decision_trace_count = $meta.decision_trace_count
        audit_record_count = $meta.audit_record_count
        governance_correlation_status = $LineageResponse.lineage.governance_correlation.status
        governed_task_count = $facts.governed_task_count
        correlated_governed_task_count = $facts.correlated_governed_task_count
        missing_required_reference_count = $facts.missing_required_reference_count
        field_mismatch_count = $facts.field_mismatch_count
        missing_external_event_count = $facts.missing_external_event_count
        coverage_complete = $facts.coverage_complete
    }
}

function Get-IntegritySemanticView {
    param($IntegrityResponse)
    $i = $IntegrityResponse.integrity
    return [ordered]@{
        mission_id = $i.mission_id
        status = $i.status
        read_only = $i.read_only
        verification_complete = $i.verification_complete
        violation_count = $i.violation_count
        task_count = $i.summary.task_count
        clean_task_count = $i.summary.clean_task_count
        violated_task_count = $i.summary.violated_task_count
        unverifiable_task_count = $i.summary.unverifiable_task_count
    }
}

function Get-TaskSemanticView {
    param($TaskLineageResponse)
    $l = $TaskLineageResponse.lineage
    return [ordered]@{
        mission_id = $l.identity.mission_id
        task_id = $l.identity.task_id
        projection_scope = $l.projection_scope
        authorization_mode = $l.task_contract.authorization_mode
        policy_decision_id = $l.task_contract.policy_decision_id
        authorization_request_id = $l.task_contract.authorization_request_id
        scope_contract_id = $l.task_contract.scope_contract_id
        pre_dispatch_revalidation_id = $l.task_contract.pre_dispatch_revalidation_id
        pre_dispatch_revalidation_status = $l.task_contract.pre_dispatch_revalidation_status
        committed_event_id = $l.lifecycle.committed_event_id
        authorization_revalidated_event_id = $l.lifecycle.authorization_revalidated_event_id
        dispatched_event_id = $l.lifecycle.dispatched_event_id
        terminal_event_id = $l.lifecycle.terminal_event_id
        terminal_event_type = $l.lifecycle.terminal_event_type
    }
}

try {
    if (-not $MissionId) {
        $MissionId = "mission-stage298-e2e-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    }

    $script:EvidenceDir = Join-Path $EvidenceRoot $MissionId
    Ensure-Directory -Path $script:EvidenceDir

    Write-Section "Stage 2.9.8 - End-to-End Acceptance"
    Write-Host ("MissionId       : {0}" -f $MissionId)
    Write-Host ("CTI runtime     : {0}" -f $CtiBaseUrl)
    Write-Host ("Governance      : {0}" -f $GovernanceBaseUrl)
    Write-Host ("Evidence folder : {0}" -f $script:EvidenceDir)

    Invoke-Regression

    Write-Section "Preflight health / diagnostics"
    $preflight = Get-RuntimeSnapshot
    Save-Json -Name "10_preflight_runtime_snapshot.json" -Object $preflight
    Assert-RuntimeReady -Snapshot $preflight -Prefix "Preflight"

    $scopeContractId = $null

    if ($ReuseExistingMission) {
        Add-Check -Stage "2.9.8" -Name "Mission creation" -Status "SKIP" -Detail "Reusing existing mission $MissionId." -Mandatory $false
    }
    else {
        Write-Section "Create governed E2E scope"
        $scopeBody = [ordered]@{
            mission_id = $MissionId
            name = "Stage 2.9.8 End-to-End Acceptance"
            policy_set_id = "default-policy"
            created_by = "operator-stage298"
            approved_by = "operator-stage298"
            targets = @()
            sources = @(
                [ordered]@{
                    source_id = $CtiSource
                    source_type = "CTI"
                    allowed = $true
                    constraints = [ordered]@{
                        read_only = $true
                    }
                }
            )
            action_constraints = @(
                [ordered]@{
                    action_class = "CTI_SOURCE_READ"
                    action_name = "*"
                    effect = "ALLOW"
                    max_risk_level = "LOW"
                    requires_approval = $false
                    constraints = [ordered]@{
                        read_only = $true
                        target_actuation = $false
                        max_pages = 1
                    }
                }
            )
            metadata = [ordered]@{
                stage = "2.9.8"
                purpose = "end-to-end-acceptance"
                acceptance_profile = "governed-read-only-cti"
            }
        }
        Save-Json -Name "20_scope_request.json" -Object $scopeBody
        $scopeResponse = Invoke-ApiPostJson -Uri ("{0}/api/governance/scope-contracts" -f $GovernanceBaseUrl) -Body $scopeBody
        Save-Json -Name "21_scope_response.json" -Object $scopeResponse
        $scopeContractId = [string]$scopeResponse.scope_contract.scope_contract_id

        Require-Check -Stage "2.9.8" -Name "ScopeContract created" `
            -Condition (Test-HasText $scopeContractId) `
            -PassDetail ("scope_contract_id={0}" -f $scopeContractId) `
            -FailDetail "Governance did not return scope_contract.scope_contract_id."

        Require-Check -Stage "2.9.8" -Name "Scope mission binding" `
            -Condition ([string]$scopeResponse.scope_contract.mission_id -eq $MissionId) `
            -PassDetail "ScopeContract is bound to the canonical E2E mission identity." `
            -FailDetail ("Scope mission_id={0}; expected {1}" -f $scopeResponse.scope_contract.mission_id, $MissionId)

        Require-Check -Stage "2.9.8" -Name "Scope active" `
            -Condition ([string]$scopeResponse.scope_contract.status -eq "ACTIVE") `
            -PassDetail "ScopeContract status=ACTIVE." `
            -FailDetail ("ScopeContract status={0}" -f $scopeResponse.scope_contract.status)

        Write-Section "Start governed CTI mission"
        $missionBody = [ordered]@{
            target_url = $TargetUrl
            scope_contract_id = $scopeContractId
            policy_context = [ordered]@{
                policy_version = "1"
                environment = "LAB"
                scope_allowed = $true
                allowed_cti_sources = @($CtiSource)
                scope_contract_id = $scopeContractId
                governance_authority = "aptsGSS"
            }
            auto_acquire_cti = $true
            cti_acquisition_max_actions = 1
            asset_scope = @($TargetUrl)
            cti_source_set = @($CtiSource)
            mission_id = $MissionId
            allow_degraded_acquisition = $false
            intelligence_requirements = @(
                "asset_profile",
                "cpe_resolution",
                "vulnerability_applicability",
                "attack_mapping",
                "threat_context",
                "risk_priority",
                "pip"
            )
        }
        Save-Json -Name "22_mission_start_request.json" -Object $missionBody
        $startResponse = Invoke-ApiPostJson -Uri ("{0}/api/cti/missions/start" -f $CtiBaseUrl) -Body $missionBody
        Save-Json -Name "23_mission_start_response.json" -Object $startResponse

        Require-Check -Stage "2.9.8" -Name "Mission accepted" `
            -Condition ([string]$startResponse.status -eq "accepted") `
            -PassDetail "Mission start status=accepted." `
            -FailDetail ("Mission start status={0}" -f $startResponse.status)

        Require-Check -Stage "2.9.8" -Name "Canonical mission identity preserved" `
            -Condition ([string]$startResponse.mission_id -eq $MissionId) `
            -PassDetail $MissionId `
            -FailDetail ("Requested {0}; returned {1}" -f $MissionId, $startResponse.mission_id)
    }

    Write-Section "Wait for mission completion"
    $missionStatus = Wait-MissionTerminal -Id $MissionId
    Save-Json -Name "30_mission_status.json" -Object $missionStatus

    Require-Check -Stage "2.9.8" -Name "Mission completed" `
        -Condition (($null -ne $missionStatus) -and ([string]$missionStatus.mission.status -eq "COMPLETED")) `
        -PassDetail "mission.status=COMPLETED." `
        -FailDetail ("Mission did not reach COMPLETED within {0}s. Last status={1}" -f $MissionTimeoutSeconds, $(if ($null -eq $missionStatus) { "<none>" } else { [string]$missionStatus.mission.status }))

    Require-Check -Stage "2.9.8" -Name "Mission last_error empty" `
        -Condition (-not (Test-HasText $missionStatus.mission.last_error)) `
        -PassDetail "last_error is empty." `
        -FailDetail ("last_error={0}" -f $missionStatus.mission.last_error)

    if (-not $ReuseExistingMission) {
        Require-Check -Stage "2.9.8" -Name "Bounded acquisition action count" `
            -Condition ([int]$missionStatus.mission.acquisition_actions -eq 1) `
            -PassDetail "acquisition_actions=1." `
            -FailDetail ("acquisition_actions={0}" -f $missionStatus.mission.acquisition_actions)

        Require-Check -Stage "2.9.8" -Name "Expected CTI source used" `
            -Condition (@($missionStatus.mission.acquisition_sources) -contains $CtiSource) `
            -PassDetail ("acquisition_sources contains {0}." -f $CtiSource) `
            -FailDetail ("acquisition_sources={0}" -f (@($missionStatus.mission.acquisition_sources) -join ","))
    }

    Write-Section "Mission reconstruction and governance correlation"
    $lineage = Wait-Correlation -Id $MissionId
    Save-Json -Name "40_mission_lineage.json" -Object $lineage

    Require-Check -Stage "2.9.3" -Name "Mission lineage projection scope" `
        -Condition ([string]$lineage.lineage.projection_scope -eq "MISSION") `
        -PassDetail "projection_scope=MISSION." `
        -FailDetail ("projection_scope={0}" -f $lineage.lineage.projection_scope)

    Require-Check -Stage "2.9.1" -Name "Canonical projection quality" `
        -Condition ([string]$lineage.lineage.projection_metadata.quality -eq "CANONICAL_V2") `
        -PassDetail "projection_metadata.quality=CANONICAL_V2." `
        -FailDetail ("quality={0}" -f $lineage.lineage.projection_metadata.quality)

    Require-Check -Stage "2.9.3" -Name "Mission has reconstructed tasks" `
        -Condition ([int]$lineage.lineage.projection_metadata.task_count -gt 0) `
        -PassDetail ("task_count={0}." -f $lineage.lineage.projection_metadata.task_count) `
        -FailDetail "task_count must be > 0."

    Require-Check -Stage "2.9.3" -Name "Mission has causal edges" `
        -Condition ([int]$lineage.lineage.projection_metadata.causal_edge_count -gt 0) `
        -PassDetail ("causal_edge_count={0}." -f $lineage.lineage.projection_metadata.causal_edge_count) `
        -FailDetail "causal_edge_count must be > 0."

    Require-Check -Stage "2.9.4" -Name "Cross-subsystem governance correlation" `
        -Condition ([string]$lineage.lineage.governance_correlation.status -eq "CORRELATED") `
        -PassDetail "governance_correlation.status=CORRELATED." `
        -FailDetail ("status={0}" -f $lineage.lineage.governance_correlation.status)

    $facts = $lineage.lineage.governance_correlation.correlation_facts
    Require-Check -Stage "2.9.4" -Name "Governed task coverage exists" `
        -Condition ([int]$facts.governed_task_count -ge 1) `
        -PassDetail ("governed_task_count={0}." -f $facts.governed_task_count) `
        -FailDetail "Expected at least one governed task in the E2E mission."

    Require-Check -Stage "2.9.4" -Name "All governed tasks correlated" `
        -Condition ([int]$facts.correlated_governed_task_count -eq [int]$facts.governed_task_count) `
        -PassDetail ("correlated={0}/{1}." -f $facts.correlated_governed_task_count, $facts.governed_task_count) `
        -FailDetail ("correlated={0}; governed={1}" -f $facts.correlated_governed_task_count, $facts.governed_task_count)

    Require-Check -Stage "2.9.4" -Name "No missing governance references" `
        -Condition ([int]$facts.missing_required_reference_count -eq 0) `
        -PassDetail "missing_required_reference_count=0." `
        -FailDetail ("missing_required_reference_count={0}" -f $facts.missing_required_reference_count)

    Require-Check -Stage "2.9.4" -Name "No governance field mismatch" `
        -Condition ([int]$facts.field_mismatch_count -eq 0) `
        -PassDetail "field_mismatch_count=0." `
        -FailDetail ("field_mismatch_count={0}" -f $facts.field_mismatch_count)

    Require-Check -Stage "2.9.4" -Name "No missing external governance events" `
        -Condition ([int]$facts.missing_external_event_count -eq 0) `
        -PassDetail "missing_external_event_count=0." `
        -FailDetail ("missing_external_event_count={0}" -f $facts.missing_external_event_count)

    Require-Check -Stage "2.9.4" -Name "Governance coverage complete" `
        -Condition ([bool]$facts.coverage_complete) `
        -PassDetail "coverage_complete=true." `
        -FailDetail "coverage_complete=false."

    Write-Section "Integrity / violation probe"
    $integrity = Invoke-ApiGet -Uri ("{0}/api/cti/missions/{1}/integrity" -f $CtiBaseUrl, [uri]::EscapeDataString($MissionId))
    Save-Json -Name "50_mission_integrity.json" -Object $integrity

    Require-Check -Stage "2.9.5" -Name "Mission integrity PASS" `
        -Condition ([string]$integrity.integrity.status -eq "PASS") `
        -PassDetail "integrity.status=PASS." `
        -FailDetail ("integrity.status={0}" -f $integrity.integrity.status)

    Require-Check -Stage "2.9.5" -Name "Integrity verification complete" `
        -Condition ([bool]$integrity.integrity.verification_complete) `
        -PassDetail "verification_complete=true." `
        -FailDetail "verification_complete=false."

    Require-Check -Stage "2.9.5" -Name "Zero integrity violations" `
        -Condition ([int]$integrity.integrity.violation_count -eq 0) `
        -PassDetail "violation_count=0." `
        -FailDetail ("violation_count={0}" -f $integrity.integrity.violation_count)

    Require-Check -Stage "2.9.5" -Name "Zero violated tasks" `
        -Condition ([int]$integrity.integrity.summary.violated_task_count -eq 0) `
        -PassDetail "violated_task_count=0." `
        -FailDetail ("violated_task_count={0}" -f $integrity.integrity.summary.violated_task_count)

    Require-Check -Stage "2.9.5" -Name "Zero unverifiable tasks" `
        -Condition ([int]$integrity.integrity.summary.unverifiable_task_count -eq 0) `
        -PassDetail "unverifiable_task_count=0." `
        -FailDetail ("unverifiable_task_count={0}" -f $integrity.integrity.summary.unverifiable_task_count)

    $governedIntegrityTasks = @($integrity.integrity.task_integrity | Where-Object { $_.required_authority -eq $true })
    Require-Check -Stage "2.9.5" -Name "Governed integrity task identifiable" `
        -Condition ($governedIntegrityTasks.Count -ge 1) `
        -PassDetail ("governed task count={0}." -f $governedIntegrityTasks.Count) `
        -FailDetail "No task_integrity entry with required_authority=true."

    $governedTaskId = [string]$governedIntegrityTasks[0].task_id

    Write-Section "Task lineage probe for governed task"
    $taskLineage = Invoke-ApiGet -Uri ("{0}/api/cti/tasks/{1}/lineage" -f $CtiBaseUrl, [uri]::EscapeDataString($governedTaskId))
    Save-Json -Name "60_governed_task_lineage.json" -Object $taskLineage

    Require-Check -Stage "2.9.2" -Name "Task lineage projection" `
        -Condition (([string]$taskLineage.lineage.projection_scope -eq "TASK") -and ([string]$taskLineage.lineage.identity.task_id -eq $governedTaskId)) `
        -PassDetail ("projection_scope=TASK; task_id={0}." -f $governedTaskId) `
        -FailDetail "Task lineage identity/projection scope mismatch."

    Require-Check -Stage "2.9.2" -Name "Governed authorization mode" `
        -Condition ([string]$taskLineage.lineage.task_contract.authorization_mode -eq "REQUIRED") `
        -PassDetail "authorization_mode=REQUIRED." `
        -FailDetail ("authorization_mode={0}" -f $taskLineage.lineage.task_contract.authorization_mode)

    Require-Check -Stage "2.9.2" -Name "PolicyDecision binding present" `
        -Condition (Test-HasText $taskLineage.lineage.task_contract.policy_decision_id) `
        -PassDetail ("policy_decision_id={0}." -f $taskLineage.lineage.task_contract.policy_decision_id) `
        -FailDetail "policy_decision_id is missing."

    Require-Check -Stage "2.9.2" -Name "AuthorizationRequest binding present" `
        -Condition (Test-HasText $taskLineage.lineage.task_contract.authorization_request_id) `
        -PassDetail ("authorization_request_id={0}." -f $taskLineage.lineage.task_contract.authorization_request_id) `
        -FailDetail "authorization_request_id is missing."

    Require-Check -Stage "2.9.2" -Name "Pre-dispatch revalidation valid" `
        -Condition ([string]$taskLineage.lineage.task_contract.pre_dispatch_revalidation_status -eq "VALID") `
        -PassDetail "pre_dispatch_revalidation_status=VALID." `
        -FailDetail ("pre_dispatch_revalidation_status={0}" -f $taskLineage.lineage.task_contract.pre_dispatch_revalidation_status)

    if (-not $ReuseExistingMission) {
        Require-Check -Stage "2.9.2" -Name "Task bound to E2E ScopeContract" `
            -Condition ([string]$taskLineage.lineage.task_contract.scope_contract_id -eq $scopeContractId) `
            -PassDetail ("scope_contract_id={0}." -f $scopeContractId) `
            -FailDetail ("Task scope={0}; expected={1}" -f $taskLineage.lineage.task_contract.scope_contract_id, $scopeContractId)
    }

    $life = $taskLineage.lineage.lifecycle
    Require-Check -Stage "2.9.1" -Name "Committed event captured" `
        -Condition (Test-HasText $life.committed_event_id) `
        -PassDetail ("committed_event_id={0}." -f $life.committed_event_id) `
        -FailDetail "committed_event_id missing."

    Require-Check -Stage "2.9.1" -Name "Authorization revalidation event captured" `
        -Condition (Test-HasText $life.authorization_revalidated_event_id) `
        -PassDetail ("authorization_revalidated_event_id={0}." -f $life.authorization_revalidated_event_id) `
        -FailDetail "authorization_revalidated_event_id missing."

    Require-Check -Stage "2.9.1" -Name "Dispatch event captured" `
        -Condition (Test-HasText $life.dispatched_event_id) `
        -PassDetail ("dispatched_event_id={0}." -f $life.dispatched_event_id) `
        -FailDetail "dispatched_event_id missing."

    Require-Check -Stage "2.9.1" -Name "Terminal event captured" `
        -Condition (Test-HasText $life.terminal_event_id) `
        -PassDetail ("terminal_event_id={0}; terminal_event_type={1}." -f $life.terminal_event_id, $life.terminal_event_type) `
        -FailDetail "terminal_event_id missing."

    $taskEvents = @($taskLineage.lineage.events)
    $committedEvent = @($taskEvents | Where-Object { $_.event_id -eq $life.committed_event_id }) | Select-Object -First 1
    $revalidatedEvent = @($taskEvents | Where-Object { $_.event_id -eq $life.authorization_revalidated_event_id }) | Select-Object -First 1
    $dispatchedEvent = @($taskEvents | Where-Object { $_.event_id -eq $life.dispatched_event_id }) | Select-Object -First 1
    $terminalEvent = @($taskEvents | Where-Object { $_.event_id -eq $life.terminal_event_id }) | Select-Object -First 1

    Require-Check -Stage "2.9.1" -Name "Canonical causal chain: commit -> revalidate" `
        -Condition (($null -ne $committedEvent) -and ($null -ne $revalidatedEvent) -and ([string]$revalidatedEvent.causation_event_id -eq [string]$life.committed_event_id)) `
        -PassDetail "TASK_AUTHORIZATION_REVALIDATED causally follows TASK_COMMITTED." `
        -FailDetail "Revalidation event does not causally bind to committed event."

    Require-Check -Stage "2.9.1" -Name "Canonical causal chain: revalidate -> dispatch" `
        -Condition (($null -ne $dispatchedEvent) -and ([string]$dispatchedEvent.causation_event_id -eq [string]$life.authorization_revalidated_event_id)) `
        -PassDetail "TASK_DISPATCHED causally follows authorization revalidation." `
        -FailDetail "Dispatch event does not causally bind to authorization revalidation."

    Require-Check -Stage "2.9.1" -Name "Terminal event participates in causal chain" `
        -Condition (($null -ne $terminalEvent) -and (Test-HasText $terminalEvent.causation_event_id)) `
        -PassDetail ("terminal causation_event_id={0}." -f $terminalEvent.causation_event_id) `
        -FailDetail "Terminal event is not causally linked."

    Write-Section "Mission diagnostics"
    $missionDiagnostics = Invoke-ApiGet -Uri ("{0}/api/cti/missions/{1}/diagnostics" -f $CtiBaseUrl, [uri]::EscapeDataString($MissionId))
    Save-Json -Name "70_mission_diagnostics.json" -Object $missionDiagnostics

    Require-Check -Stage "2.9.6" -Name "Mission diagnostics HEALTHY" `
        -Condition ([string]$missionDiagnostics.diagnostics.status -eq "HEALTHY") `
        -PassDetail "diagnostics.status=HEALTHY." `
        -FailDetail ("diagnostics.status={0}" -f $missionDiagnostics.diagnostics.status)

    Require-Check -Stage "2.9.6" -Name "Mission diagnostics canonical projection" `
        -Condition ([string]$missionDiagnostics.diagnostics.projection_quality -eq "CANONICAL_V2") `
        -PassDetail "projection_quality=CANONICAL_V2." `
        -FailDetail ("projection_quality={0}" -f $missionDiagnostics.diagnostics.projection_quality)

    Require-Check -Stage "2.9.6" -Name "Mission diagnostics governance correlated" `
        -Condition ([string]$missionDiagnostics.diagnostics.governance_correlation_status -eq "CORRELATED") `
        -PassDetail "governance_correlation_status=CORRELATED." `
        -FailDetail ("governance_correlation_status={0}" -f $missionDiagnostics.diagnostics.governance_correlation_status)

    Require-Check -Stage "2.9.6" -Name "Mission diagnostics integrity PASS" `
        -Condition (([string]$missionDiagnostics.diagnostics.integrity_status -eq "PASS") -and ([int]$missionDiagnostics.diagnostics.integrity_violation_count -eq 0)) `
        -PassDetail "integrity_status=PASS; integrity_violation_count=0." `
        -FailDetail ("integrity_status={0}; violation_count={1}" -f $missionDiagnostics.diagnostics.integrity_status, $missionDiagnostics.diagnostics.integrity_violation_count)

    Require-Check -Stage "2.9.6" -Name "Mission diagnostics no issues" `
        -Condition (@($missionDiagnostics.diagnostics.issues).Count -eq 0) `
        -PassDetail "issues=[]" `
        -FailDetail ("issues count={0}" -f @($missionDiagnostics.diagnostics.issues).Count)

    Write-Section "Read-only / idempotent probe verification"
    $missionLineageAgain = Invoke-ApiGet -Uri ("{0}/api/cti/missions/{1}/lineage" -f $CtiBaseUrl, [uri]::EscapeDataString($MissionId))
    $integrityAgain = Invoke-ApiGet -Uri ("{0}/api/cti/missions/{1}/integrity" -f $CtiBaseUrl, [uri]::EscapeDataString($MissionId))
    $taskLineageAgain = Invoke-ApiGet -Uri ("{0}/api/cti/tasks/{1}/lineage" -f $CtiBaseUrl, [uri]::EscapeDataString($governedTaskId))

    $missionHash1 = Get-SemanticHash -Object (Get-MissionSemanticView -LineageResponse $lineage)
    $missionHash2 = Get-SemanticHash -Object (Get-MissionSemanticView -LineageResponse $missionLineageAgain)
    $integrityHash1 = Get-SemanticHash -Object (Get-IntegritySemanticView -IntegrityResponse $integrity)
    $integrityHash2 = Get-SemanticHash -Object (Get-IntegritySemanticView -IntegrityResponse $integrityAgain)
    $taskHash1 = Get-SemanticHash -Object (Get-TaskSemanticView -TaskLineageResponse $taskLineage)
    $taskHash2 = Get-SemanticHash -Object (Get-TaskSemanticView -TaskLineageResponse $taskLineageAgain)

    $hashEvidence = [ordered]@{
        mission_lineage_hash_first = $missionHash1
        mission_lineage_hash_second = $missionHash2
        mission_integrity_hash_first = $integrityHash1
        mission_integrity_hash_second = $integrityHash2
        task_lineage_hash_first = $taskHash1
        task_lineage_hash_second = $taskHash2
    }
    Save-Json -Name "80_read_only_probe_hashes.json" -Object $hashEvidence

    Require-Check -Stage "2.9.3" -Name "Mission lineage read-only semantic stability" `
        -Condition ($missionHash1 -eq $missionHash2) `
        -PassDetail ("semantic_hash={0}." -f $missionHash1) `
        -FailDetail ("first={0}; second={1}" -f $missionHash1, $missionHash2)

    Require-Check -Stage "2.9.5" -Name "Integrity probe read-only semantic stability" `
        -Condition ($integrityHash1 -eq $integrityHash2) `
        -PassDetail ("semantic_hash={0}." -f $integrityHash1) `
        -FailDetail ("first={0}; second={1}" -f $integrityHash1, $integrityHash2)

    Require-Check -Stage "2.9.2" -Name "Task lineage read-only semantic stability" `
        -Condition ($taskHash1 -eq $taskHash2) `
        -PassDetail ("semantic_hash={0}." -f $taskHash1) `
        -FailDetail ("first={0}; second={1}" -f $taskHash1, $taskHash2)

    Write-Section "Postflight outbox and runtime readiness"
    $settledOutbox = Wait-OutboxSettled
    Save-Json -Name "90_governance_outbox_postflight.json" -Object $settledOutbox
    Require-Check -Stage "2.9.4" -Name "Governance outbox settled" `
        -Condition (($null -ne $settledOutbox) -and ([int]$settledOutbox.stats.pending -eq 0) -and ([int]$settledOutbox.stats.failed -eq 0)) `
        -PassDetail ("pending=0; failed=0; delivered={0}/{1}." -f $settledOutbox.stats.delivered, $settledOutbox.stats.total) `
        -FailDetail ("pending={0}; failed={1}" -f $settledOutbox.stats.pending, $settledOutbox.stats.failed)

    $postflight = Get-RuntimeSnapshot
    Save-Json -Name "91_postflight_runtime_snapshot.json" -Object $postflight
    Assert-RuntimeReady -Snapshot $postflight -Prefix "Postflight"

    Add-Check -Stage "2.9.7" -Name "Optional GUI" -Status "SKIP" -Detail "Stage 2.9.7 is optional and is not a prerequisite for CLI/API E2E closure." -Mandatory $false

    $script:FinalStatus = "PASS"
}
catch {
    $err = $_
    Write-Host ""
    Write-Host ("Stage 2.9.8 aborted: {0}" -f $err.Exception.Message) -ForegroundColor Red
    Add-Check -Stage "2.9.8" -Name "Unhandled acceptance exception" -Status "FAIL" -Detail $err.Exception.Message -Mandatory $true
    if ($script:EvidenceDir) {
        Save-Text -Name "99_exception.txt" -Lines @(
            $err.Exception.ToString(),
            "",
            $err.ScriptStackTrace
        )
    }
    $script:FinalStatus = "FAIL"
}
finally {
    $finishedAt = (Get-Date).ToUniversalTime()
    $mandatoryFailures = @($script:Checks | Where-Object { $_.mandatory -and $_.status -eq "FAIL" }).Count
    $passCount = @($script:Checks | Where-Object { $_.status -eq "PASS" }).Count
    $failCount = @($script:Checks | Where-Object { $_.status -eq "FAIL" }).Count
    $warnCount = @($script:Checks | Where-Object { $_.status -eq "WARN" }).Count
    $skipCount = @($script:Checks | Where-Object { $_.status -eq "SKIP" }).Count

    if ($mandatoryFailures -gt 0) { $script:FinalStatus = "FAIL" }

    $summary = [ordered]@{
        schema_version = "stage2-9-8-e2e-acceptance-v1"
        stage = "2.9.8"
        title = "End-to-End Acceptance"
        status = $script:FinalStatus
        mission_id = $MissionId
        started_at_utc = $script:StartedAt.ToString("o")
        finished_at_utc = $finishedAt.ToString("o")
        duration_seconds = [math]::Round(($finishedAt - $script:StartedAt).TotalSeconds, 3)
        expected_architecture_version = $ExpectedArchitectureVersion
        expected_control_version = $ExpectedControlVersion
        check_count = $script:Checks.Count
        pass_count = $passCount
        fail_count = $failCount
        warn_count = $warnCount
        skip_count = $skipCount
        mandatory_fail_count = $mandatoryFailures
        checks = @($script:Checks)
    }

    if ($script:EvidenceDir) {
        Save-Json -Name "99_acceptance_summary.json" -Object $summary
    }

    Write-Section "Stage 2.9.8 final result"
    Write-Host ("STATUS                 : {0}" -f $script:FinalStatus) -ForegroundColor $(if ($script:FinalStatus -eq "PASS") { "Green" } else { "Red" })
    Write-Host ("MISSION_ID             : {0}" -f $MissionId)
    Write-Host ("CHECKS                 : {0}" -f $script:Checks.Count)
    Write-Host ("PASS / FAIL / WARN/SKIP: {0} / {1} / {2}/{3}" -f $passCount, $failCount, $warnCount, $skipCount)
    Write-Host ("MANDATORY_FAIL         : {0}" -f $mandatoryFailures)
    if ($script:EvidenceDir) {
        Write-Host ("EVIDENCE               : {0}" -f $script:EvidenceDir)
    }

    if ($script:FinalStatus -eq "PASS") {
        Write-Host ""
        Write-Host "[PASS] TAHAP 2.9.8 END-TO-END ACCEPTANCE CLOSED." -ForegroundColor Green
        exit 0
    }
    else {
        Write-Host ""
        Write-Host "[FAIL] TAHAP 2.9.8 END-TO-END ACCEPTANCE NOT CLOSED." -ForegroundColor Red
        exit 1
    }
}
