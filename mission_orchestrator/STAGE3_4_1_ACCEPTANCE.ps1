param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.1 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

Write-Host "=============================================================================="
Write-Host "Stage 3.4.1 - Canonical Subsystem Registry & Capability Contract Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[1] Python compile + full regression"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Regression suite failed" }
Pass "Stage 3.1.1 through 3.4.1 regression suite passed"

Write-Host "`n[2] Health / registry contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne "stage3.4.1-canonical-subsystem-registry-capability-contract") { Fail "Stage 3.4.1 control is not active" }
if ([int]$health.mission_repository_migration_level -ne 18) { Fail "Repository migration level is not 18" }
if ([int]$health.subsystem_registry_database_migration_level -ne 18) { Fail "Registry migration declaration is not 18" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authority changed" }
if ($health.subsystem_registry_runtime_endpoint_binding_performed -ne $false) { Fail "Stage 3.4.1 unexpectedly bound runtime endpoints" }
if ($health.subsystem_registry_runtime_health_probe_performed -ne $false) { Fail "Stage 3.4.1 unexpectedly probed subsystem health" }
if ($health.subsystem_registry_candidate_resolution_performed -ne $false) { Fail "Stage 3.4.2 candidate resolution leaked into Stage 3.4.1" }
if ($health.subsystem_registry_route_selection_performed -ne $false) { Fail "Route selection leaked into Stage 3.4.1" }
if ($health.subsystem_registry_delegation_performed -ne $false) { Fail "Delegation leaked into Stage 3.4.1" }
if ($health.subsystem_registry_governance_query_performed -ne $false) { Fail "Registry read unexpectedly queried Governance" }
if ($health.target_action_dispatch_enabled -ne $false) { Fail "Target-action dispatch became enabled" }
if ($health.target_actuation -ne $false) { Fail "Target actuation became enabled" }
if (@($health.canonical_registered_subsystems).Count -ne 2) { Fail "Canonical subsystem count is not 2" }
if (@($health.canonical_registered_subsystems) -notcontains "CTI") { Fail "CTI is not canonically registered" }
if (@($health.canonical_registered_subsystems) -notcontains "PENTEST") { Fail "PENTEST is not canonically registered" }
if (@($health.supported_routing_subsystems).Count -ne 1 -or @($health.supported_routing_subsystems)[0] -ne "CTI") { Fail "Historical Stage-3.1.5 routing scope was widened" }
Pass "Stage 3.4.1 active; migration=18; registry present; Governance/execution boundaries preserved"

Write-Host "`n[3] Canonical registry definition + durable snapshot"
$definition = Invoke-RestMethod "$MissionBaseUrl/api/subsystem-registry-definition"
$registry1 = Invoke-RestMethod "$MissionBaseUrl/api/subsystem-registry"
$registry2 = Invoke-RestMethod "$MissionBaseUrl/api/subsystem-registry"
if ($definition.status -ne "completed" -or $registry1.status -ne "completed") { Fail "Registry read model did not complete" }
if ([int]$definition.definition.subsystem_count -ne 2) { Fail "Registry definition subsystem count is not 2" }
if ([int]$definition.definition.capability_count -ne 4) { Fail "Registry definition capability count is not 4" }
if ($definition.definition.canonical_sha256 -ne $definition.persisted_registry_sha256) { Fail "Definition hash does not bind to persisted registry" }
if ($registry1.registry.integrity.canonical_sha256 -ne $registry2.registry.integrity.canonical_sha256) { Fail "Repeated registry reads are not deterministic" }
if ($registry1.registry.integrity.canonical_sha256 -ne $definition.persisted_registry_sha256) { Fail "Persisted registry hash drift" }
if ($registry1.runtime_endpoint_binding_performed -ne $false -or $registry1.runtime_health_probe_performed -ne $false) { Fail "Registry GET performed runtime binding/probe" }
if ($registry1.route_selection_performed -ne $false -or $registry1.delegation_performed -ne $false) { Fail "Registry GET performed route/delegation" }
if ($registry1.governance_query_performed -ne $false) { Fail "Registry GET queried Governance" }
Pass "Registry definition and persisted immutable snapshot are hash-bound and deterministic"

Write-Host "`n[4] Canonical subsystem + capability read models"
$subsystems = Invoke-RestMethod "$MissionBaseUrl/api/subsystems"
$cti = Invoke-RestMethod "$MissionBaseUrl/api/subsystems/CTI"
$pentest = Invoke-RestMethod "$MissionBaseUrl/api/subsystems/PENTEST"
$ctiCaps = Invoke-RestMethod "$MissionBaseUrl/api/subsystems/CTI/capabilities"
$pentestCaps = Invoke-RestMethod "$MissionBaseUrl/api/subsystems/PENTEST/capabilities"
$ctiRead = Invoke-RestMethod "$MissionBaseUrl/api/subsystems/CTI/capabilities/cti.read.context"
if ([int]$subsystems.count -ne 2) { Fail "Subsystem read model count is not 2" }
if ($cti.subsystem.identity.subsystem_id -ne "CTI") { Fail "CTI canonical identity mismatch" }
if ($pentest.subsystem.identity.subsystem_id -ne "PENTEST") { Fail "PENTEST canonical identity mismatch" }
if ([int]$ctiCaps.count -ne 2) { Fail "CTI capability count is not 2" }
if ([int]$pentestCaps.count -ne 2) { Fail "PENTEST capability count is not 2" }
if ($ctiRead.capability.identity.capability_id -ne "cti.read.context") { Fail "Exact capability lookup mismatch" }
if ($ctiRead.capability_is_authorization -ne $false) { Fail "Capability was incorrectly treated as authorization" }
if ($ctiRead.route_selection_performed -ne $false -or $ctiRead.delegation_performed -ne $false) { Fail "Capability GET performed routing/delegation" }
Pass "CTI/PENTEST canonical identities and four declared capabilities exposed without delegation"

Write-Host "`n[5] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.4.1-canonical-subsystem-registry-capability-contract") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 18) { Fail "Final migration level drifted" }
if ($finalHealth.target_action_dispatch_enabled -ne $false -or $finalHealth.target_actuation -ne $false) { Fail "Execution boundary drifted" }
Pass "Stage 3.4.1 closure contract preserved after live registry probes"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
