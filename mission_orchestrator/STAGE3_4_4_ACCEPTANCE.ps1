param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.4 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

Write-Host "=============================================================================="
Write-Host "Stage 3.4.4 - Deterministic Route Selection & Decision Record Acceptance"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try {
    $preflightHealth = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator is not reachable at $MissionBaseUrl. Start/restart it from D:\mission_orchestrator before acceptance."
}
$expectedControl = "stage3.4.4-deterministic-route-selection-decision-record"
$observedControl = [string]$preflightHealth.control_version
Write-Host "      observed control_version : $observedControl"
Write-Host "      expected control_version : $expectedControl"
if ($preflightHealth.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($observedControl -ne $expectedControl) {
    Fail "Stage 3.4.4 source is not the active runtime on port 8780 (observed '$observedControl'). Stop the listener on port 8780 and restart Mission Orchestrator from D:\mission_orchestrator, then rerun acceptance."
}
Pass "Stage 3.4.4 runtime control is active before regression"

Write-Host "`n[1] Python compile + full regression"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Full regression suite failed" }
Pass "Stage 3.1.1 through 3.4.4 full regression passed"

Write-Host "`n[2] Health / deterministic-selection contract / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne "stage3.4.4-deterministic-route-selection-decision-record") { Fail "Stage 3.4.4 control drifted after regression (observed: $($health.control_version))" }
if ([int]$health.mission_repository_migration_level -ne 21) { Fail "Repository migration level is not 21" }
if ([int]$health.task_routing_intent_database_migration_level -ne 19) { Fail "Stage-3.4.2 routing-intent migration declaration is not 19" }
if ([int]$health.task_routing_eligibility_database_migration_level -ne 20) { Fail "Stage-3.4.3 eligibility migration declaration is not 20" }
if ([int]$health.task_route_selection_database_migration_level -ne 21) { Fail "Stage-3.4.4 route-selection migration declaration is not 21" }
if ($health.task_route_selection_policy -ne "STAGE343_ELIGIBLE_CANONICAL_TUPLE_ASC_V1") { Fail "Unexpected deterministic route-selection policy" }
if ($health.task_route_selection_eligible_candidate_source -ne "STAGE343_ELIGIBLE_CANDIDATES_ONLY") { Fail "Route selection is not restricted to Stage-3.4.3 eligible candidates" }
if ($health.task_routing_route_ranking_performed -ne $true) { Fail "Deterministic route ranking is not active" }
if ($health.task_routing_route_selection_performed -ne $true) { Fail "Route-selection decision is not active" }
if ($health.task_route_selection_selected_route_is_logical_only -ne $true) { Fail "Selected route is not declared logical-only" }
if ($health.task_route_selection_selection_is_authorization -ne $false) { Fail "Route selection was incorrectly promoted to authorization" }
if ($health.task_route_selection_selection_is_runtime_availability -ne $false) { Fail "Route selection was incorrectly equated with runtime availability" }
if ($health.task_routing_runtime_endpoint_resolution_performed -ne $false) { Fail "Runtime endpoint resolution leaked into Stage 3.4.4" }
if ($health.task_routing_runtime_health_probe_performed -ne $false) { Fail "Runtime health probing leaked into Stage 3.4.4" }
if ($health.task_routing_resource_assignment_performed -ne $false) { Fail "Resource assignment leaked into Stage 3.4.4" }
if ($health.task_routing_governance_query_performed -ne $false) { Fail "Stage 3.4.4 unexpectedly queried Governance" }
if ($health.task_routing_authorization_granted -ne $false) { Fail "Stage 3.4.4 granted authorization" }
if ($health.task_routing_delegation_performed -ne $false) { Fail "Delegation leaked into Stage 3.4.4" }
if ($health.task_routing_dispatch_performed -ne $false) { Fail "Dispatch leaked into Stage 3.4.4" }
if ($health.task_routing_target_action_dispatch_enabled -ne $false) { Fail "Target-action dispatch became enabled" }
if ($health.task_routing_target_actuation -ne $false) { Fail "Target actuation became enabled" }
if ($health.task_routing_version_vector_extension_performed -ne $false) { Fail "Stage 3.4.4 unexpectedly extended the Mission version vector" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
Pass "Stage 3.4.4 active; migration=21; deterministic logical selection enabled; Governance/delegation/execution boundaries preserved"

Write-Host "`n[3] Canonical upstream routing sources"
$registry = Invoke-RestMethod "$MissionBaseUrl/api/subsystem-registry"
if ($registry.status -ne "completed") { Fail "Canonical subsystem registry is unavailable" }
if ([int]$registry.registry.counts.subsystems -ne 2) { Fail "Canonical subsystem count is not 2" }
if ([int]$registry.registry.counts.capabilities -ne 4) { Fail "Canonical capability count is not 4" }
if ($registry.runtime_endpoint_binding_performed -ne $false) { Fail "Registry read bound runtime endpoint" }
if ($registry.runtime_health_probe_performed -ne $false) { Fail "Registry read probed subsystem health" }
Pass "Canonical CTI/PENTEST registry remains available without runtime endpoint/health side effects"

Write-Host "`n[4] Focused Stage-3.4.4 contract proof"
python -m pytest -q tests\test_stage3_4_4_deterministic_route_selection_decision_record.py
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.4.4 focused contract proof failed" }
Pass "Deterministic ranking/selection, no-route semantics, idempotency, persistence, integrity, lineage, API, and authority boundaries passed"

Write-Host "`n[5] Stage-3.4 cumulative contract proof"
python -m pytest -q tests\test_stage3_4_1_canonical_subsystem_registry_capability_contract.py tests\test_stage3_4_2_task_routing_intent_candidate_resolution.py tests\test_stage3_4_3_routing_eligibility_compatibility_gate.py tests\test_stage3_4_4_deterministic_route_selection_decision_record.py
if ($LASTEXITCODE -ne 0) { Fail "Stage-3.4 cumulative contract proof failed" }
Pass "Stage 3.4.1 through 3.4.4 cumulative routing contract passed"

Write-Host "`n[6] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne "stage3.4.4-deterministic-route-selection-decision-record") { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 21) { Fail "Final migration level drifted" }
if ($finalHealth.task_routing_route_ranking_performed -ne $true -or $finalHealth.task_routing_route_selection_performed -ne $true) { Fail "Route-selection control became inactive" }
if ($finalHealth.task_route_selection_selected_route_is_logical_only -ne $true) { Fail "Logical-route-only invariant drifted" }
if ($finalHealth.task_routing_governance_query_performed -ne $false -or $finalHealth.task_routing_authorization_granted -ne $false) { Fail "Governance authority boundary drifted" }
if ($finalHealth.task_routing_delegation_performed -ne $false -or $finalHealth.task_routing_dispatch_performed -ne $false) { Fail "Delegation/dispatch boundary drifted" }
if ($finalHealth.task_routing_runtime_endpoint_resolution_performed -ne $false -or $finalHealth.task_routing_runtime_health_probe_performed -ne $false) { Fail "Runtime availability boundary drifted" }
if ($finalHealth.task_routing_target_actuation -ne $false) { Fail "Execution boundary drifted" }
Pass "Stage 3.4.4 closure contract preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.4 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
