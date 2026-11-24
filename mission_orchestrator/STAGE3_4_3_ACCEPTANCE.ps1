param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.3 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

Write-Host "=============================================================================="
Write-Host "Stage 3.4.3 - Routing Eligibility & Compatibility Gate Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[1] Python compile + full regression"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Full regression suite failed" }
Pass "Stage 3.1.1 through 3.4.3 full regression passed"

Write-Host "`n[2] Health / eligibility-compatibility contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne "stage3.4.3-routing-eligibility-compatibility-gate") { Fail "Stage 3.4.3 control is not active" }
if ([int]$health.mission_repository_migration_level -ne 20) { Fail "Repository migration level is not 20" }
if ([int]$health.task_routing_intent_database_migration_level -ne 19) { Fail "Stage-3.4.2 routing-intent migration declaration is not 19" }
if ([int]$health.task_routing_eligibility_database_migration_level -ne 20) { Fail "Stage-3.4.3 eligibility migration declaration is not 20" }
if ($health.task_routing_candidate_resolution_performed -ne $true) { Fail "Stage-3.4.2 candidate resolution is not active" }
if ($health.task_routing_eligibility_gate_performed -ne $true) { Fail "Stage-3.4.3 eligibility gate is not active" }
if ($health.task_routing_eligibility_static_contract_only -ne $true) { Fail "Eligibility gate is not declared static-contract-only" }
if ($health.task_routing_eligible_candidate_is_selected_route -ne $false) { Fail "Eligible candidate was incorrectly promoted to selected route" }
if ($health.task_routing_eligibility_is_authorization -ne $false) { Fail "Eligibility was incorrectly promoted to authorization" }
if ($health.task_routing_eligibility_is_runtime_availability -ne $false) { Fail "Eligibility was incorrectly equated with runtime availability" }
if ($health.task_routing_route_selection_performed -ne $false) { Fail "Stage 3.4.4 route selection leaked into Stage 3.4.3" }
if ($health.task_routing_route_ranking_performed -ne $false) { Fail "Route ranking leaked into Stage 3.4.3" }
if ($health.task_routing_runtime_endpoint_resolution_performed -ne $false) { Fail "Runtime endpoint resolution leaked into Stage 3.4.3" }
if ($health.task_routing_runtime_health_probe_performed -ne $false) { Fail "Runtime health probing leaked into Stage 3.4.3" }
if ($health.task_routing_resource_assignment_performed -ne $false) { Fail "Resource assignment leaked into Stage 3.4.3" }
if ($health.task_routing_governance_query_performed -ne $false) { Fail "Stage 3.4.3 unexpectedly queried Governance" }
if ($health.task_routing_authorization_granted -ne $false) { Fail "Stage 3.4.3 granted authorization" }
if ($health.task_routing_delegation_performed -ne $false) { Fail "Delegation leaked into Stage 3.4.3" }
if ($health.task_routing_dispatch_performed -ne $false) { Fail "Dispatch leaked into Stage 3.4.3" }
if ($health.task_routing_target_action_dispatch_enabled -ne $false) { Fail "Target-action dispatch became enabled" }
if ($health.task_routing_target_actuation -ne $false) { Fail "Target actuation became enabled" }
if ($health.task_routing_version_vector_extension_performed -ne $false) { Fail "Stage 3.4.3 unexpectedly extended the Mission version vector" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
Pass "Stage 3.4.3 active; migration=20; static eligibility/compatibility enabled; selection/Governance/delegation/execution boundaries preserved"

Write-Host "`n[3] Canonical Stage-3.4.1 registry source"
$registry = Invoke-RestMethod "$MissionBaseUrl/api/subsystem-registry"
if ($registry.status -ne "completed") { Fail "Canonical subsystem registry is unavailable" }
if ([int]$registry.registry.counts.subsystems -ne 2) { Fail "Canonical subsystem count is not 2" }
if ([int]$registry.registry.counts.capabilities -ne 4) { Fail "Canonical capability count is not 4" }
if ($registry.runtime_endpoint_binding_performed -ne $false) { Fail "Registry read bound runtime endpoint" }
if ($registry.runtime_health_probe_performed -ne $false) { Fail "Registry read probed subsystem health" }
Pass "Canonical CTI/PENTEST registry is available without runtime endpoint/health side effects"

Write-Host "`n[4] Focused Stage-3.4.3 contract proof"
python -m pytest -q tests\test_stage3_4_3_routing_eligibility_compatibility_gate.py
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.4.3 focused contract proof failed" }
Pass "Static eligibility, compatibility, fail-closed behavior, idempotency, persistence, integrity, lineage, and API contract passed"

Write-Host "`n[5] Stage-3.4 cumulative contract proof"
python -m pytest -q tests\test_stage3_4_1_canonical_subsystem_registry_capability_contract.py tests\test_stage3_4_2_task_routing_intent_candidate_resolution.py tests\test_stage3_4_3_routing_eligibility_compatibility_gate.py
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.4 cumulative contract proof failed" }
Pass "Stage 3.4.1 through 3.4.3 cumulative routing contract passed"

Write-Host "`n[6] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.4.3-routing-eligibility-compatibility-gate") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 20) { Fail "Final migration level drifted" }
if ($finalHealth.task_routing_eligibility_gate_performed -ne $true) { Fail "Eligibility gate became inactive" }
if ($finalHealth.task_routing_route_selection_performed -ne $false -or $finalHealth.task_routing_route_ranking_performed -ne $false) { Fail "Route-selection boundary drifted" }
if ($finalHealth.task_routing_governance_query_performed -ne $false -or $finalHealth.task_routing_authorization_granted -ne $false) { Fail "Governance authority boundary drifted" }
if ($finalHealth.task_routing_delegation_performed -ne $false -or $finalHealth.task_routing_dispatch_performed -ne $false) { Fail "Delegation/dispatch boundary drifted" }
if ($finalHealth.task_routing_target_actuation -ne $false) { Fail "Execution boundary drifted" }
Pass "Stage 3.4.3 closure contract preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.3 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
