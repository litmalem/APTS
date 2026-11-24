param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.10 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.4.10-routing-delegation-acceptance-regression-gate"
$expectedServer = "APTSMissionOrchestrator/3.4.10"
$expectedGateSchema = "apts-mission-stage3.4-routing-delegation-acceptance-gate-v1"
$expectedGateMode = "FULL_REGRESSION_PLUS_CANONICAL_INTEGRATION_AND_LIVE_RUNTIME_BOUNDARY_PROBES"
$expectedGateBaseline = "STAGE_3_4_1_THROUGH_3_4_9"
$expectedMigrationLevel = 26

$requiredStage34Controls = @(
    "stage3.4.1-canonical-subsystem-registry-capability-contract",
    "stage3.4.2-task-routing-intent-candidate-resolution",
    "stage3.4.3-routing-eligibility-compatibility-gate",
    "stage3.4.4-deterministic-route-selection-decision-record",
    "stage3.4.5-governance-bound-delegation-authorization",
    "stage3.4.6-canonical-delegation-contract-handoff-envelope",
    "stage3.4.7-delegation-delivery-acknowledgement-ownership",
    "stage3.4.8-retry-fallback-reassignment-conflict-control",
    "stage3.4.9-routing-delegation-event-lineage-replay-recovery"
)

Write-Host "=============================================================================="
Write-Host "Stage 3.4.10 - Routing & Delegation Acceptance / Regression Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try {
    $health = Invoke-RestMethod "$MissionBaseUrl/health"
} catch {
    Fail "Mission Orchestrator is not reachable at $MissionBaseUrl"
}
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if ($health.status -ne "ok") { Fail "Mission Orchestrator health is not ok" }
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.4.10 source is not active on port 8780" }
Pass "Stage 3.4.10 runtime control is active"

Write-Host "`n[1] Python compile"
Push-Location $PSScriptRoot
try {
    python -m compileall -q mission_orchestrator tests
    if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
} finally {
    Pop-Location
}
Pass "Python compilation passed"

Write-Host "`n[2] Full Stage 3.1-3.4.10 regression"
Push-Location $PSScriptRoot
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
} finally {
    Pop-Location
}
Pass "Full regression passed"

Write-Host "`n[3] Focused Stage-3.4.10 closure proof"
Push-Location $PSScriptRoot
try {
    python -m pytest -q tests\test_stage3_4_10_routing_delegation_acceptance_regression_gate.py
    if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.4.10 proof failed" }
} finally {
    Pop-Location
}
Pass "Focused Stage-3.4.10 closure, end-to-end, restart, integrity, and authority-boundary proof passed"

Write-Host "`n[4] Runtime closure metadata"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel) { Fail "Repository migration level is not 26" }
if ($health.stage3_4_routing_delegation_acceptance_gate_schema_version -ne $expectedGateSchema) { Fail "Unexpected Stage-3.4 acceptance gate schema" }
if ($health.stage3_4_routing_delegation_acceptance_gate_mode -ne $expectedGateMode) { Fail "Unexpected Stage-3.4 acceptance gate mode" }
if ($health.stage3_4_routing_delegation_acceptance_gate_baseline -ne $expectedGateBaseline) { Fail "Unexpected Stage-3.4 acceptance gate baseline" }
if ($health.stage3_4_routing_delegation_acceptance_gate_runtime_change_mode -ne "NO_NEW_RUNTIME_AUTHORITY_OR_EXECUTION_CAPABILITY") { Fail "Runtime-change boundary drifted" }
if ($health.stage3_4_routing_delegation_acceptance_gate_database_change_mode -ne "NO_NEW_DATABASE_MIGRATION") { Fail "Database-change boundary drifted" }
if ([int]$health.stage3_4_routing_delegation_acceptance_gate_expected_migration_level -ne 26) { Fail "Acceptance gate expected migration level drifted" }
if ($health.stage3_4_routing_delegation_acceptance_gate_declared_only -ne $true) { Fail "Closure gate must remain declarative" }
if ($health.stage3_4_routing_delegation_acceptance_gate_runtime_self_certification -ne $false) { Fail "Runtime must not self-certify PASS" }
if ($health.stage3_4_routing_delegation_acceptance_gate_external_execution_required -ne $true) { Fail "External acceptance execution requirement missing" }
Pass "Stage-3.4.10 closure metadata is active and declarative"

Write-Host "`n[5] Supported-control closure ordering"
$tail = @($health.supported_controls | Select-Object -Last 10)
$expectedTail = @($requiredStage34Controls + $expectedControl)
if ($tail.Count -ne 10) { Fail "Stage-3.4 supported-control tail cardinality is not 10" }
for ($i = 0; $i -lt $expectedTail.Count; $i++) {
    if ($tail[$i] -ne $expectedTail[$i]) {
        Fail "Stage-3.4 supported-control ordering mismatch at index $i : expected $($expectedTail[$i]), observed $($tail[$i])"
    }
}
Pass "Stage 3.4.1 through 3.4.10 control lineage is complete and ordered"

Write-Host "`n[6] Stage-3.4.1-3.4.4 routing chain boundary"
if ($health.subsystem_registry_runtime_endpoint_binding_performed -ne $false) { Fail "Registry unexpectedly performed runtime endpoint binding" }
if ($health.subsystem_registry_runtime_health_probe_performed -ne $false) { Fail "Registry unexpectedly performed runtime health probing" }
if ($health.task_routing_candidate_is_eligibility_decision -ne $false) { Fail "Candidate resolution was elevated into eligibility" }
if ($health.task_routing_eligibility_is_authorization -ne $false) { Fail "Eligibility was elevated into authorization" }
if ($health.task_route_selection_selection_is_authorization -ne $false) { Fail "Route selection was elevated into authorization" }
if ($health.task_route_selection_selected_route_is_logical_only -ne $true) { Fail "Selected route is no longer declared logical-only" }
if ($health.task_route_selection_selection_is_runtime_availability -ne $false) { Fail "Route selection was elevated into runtime availability" }
Pass "Registry -> candidate -> eligibility -> deterministic route remains logical/control-plane only"

Write-Host "`n[7] Stage-3.4.5 Governance-bound authorization boundary"
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority drifted" }
if ($health.delegation_authorization_governance_query_enabled -ne $true) { Fail "Stage-3.4.5 Governance decision query is not enabled" }
if ($health.delegation_authorization_is_delegation -ne $false) { Fail "Authorization was elevated into delegation" }
if ($health.task_delegation_authorization_reused_as_execution_grant -ne $false) { Fail "Delegation authorization was reused as execution grant" }
Pass "Governance remains the authoritative delegation decision source; authorization is not execution"

Write-Host "`n[8] Stage-3.4.6-3.4.8 handoff / ownership / recovery boundary"
if ($health.task_delegation_handoff_envelope_materialized -ne $true) { Fail "Canonical handoff envelope is not materialized" }
if ($health.task_delegation_dispatch_performed -ne $false -or $health.task_delegation_execution_authorized -ne $false) { Fail "Stage-3.4.6 leaked dispatch/execution authority" }
if ($health.delegation_delivery_handoff_transmitted -ne $true -or $health.delegation_delivery_handoff_acknowledged -ne $true -or $health.delegation_delivery_ownership_accepted -ne $true) { Fail "Stage-3.4.7 delivery/ACK/ownership contract drifted" }
if ($health.delegation_delivery_dispatch_performed -ne $false -or $health.delegation_delivery_execution_authorized -ne $false) { Fail "Stage-3.4.7 leaked dispatch/execution authority" }
if ($health.delegation_recovery_control_ownership_transfer_performed -ne $false) { Fail "Stage-3.4.8 unexpectedly transferred ownership" }
if ($health.delegation_recovery_control_dispatch_performed -ne $false -or $health.delegation_recovery_control_execution_authorized -ne $false) { Fail "Stage-3.4.8 leaked dispatch/execution authority" }
Pass "Delegation materialization, ACK/ownership, and recovery-control boundaries remain non-executing"

Write-Host "`n[9] Stage-3.4.9 replay / recovery closure boundary"
if ([int]$health.routing_delegation_recovery_database_migration_level -ne 26) { Fail "Stage-3.4.9 migration declaration drifted" }
if ($health.routing_delegation_recovery_persistence_store -ne "mission_routing_delegation_recovery_checkpoints") { Fail "Stage-3.4.9 persistence store drifted" }
if ($health.routing_delegation_replay_read_only -ne $true -or $health.routing_delegation_replay_side_effects_performed -ne $false) { Fail "Stage-3.4.9 replay read-only invariant drifted" }
if ($health.routing_delegation_recovery_reconstructs_from_durable_repository -ne $true) { Fail "Stage-3.4.9 recovery no longer reconstructs from durable repository" }
if ($health.routing_delegation_recovery_external_network_io_performed -ne $false -or $health.routing_delegation_recovery_governance_query_performed -ne $false) { Fail "Stage-3.4.9 recovery performed forbidden external read/query" }
if ($health.routing_delegation_recovery_is_authorization -ne $false -or $health.routing_delegation_recovery_is_routing -ne $false -or $health.routing_delegation_recovery_is_redelivery -ne $false -or $health.routing_delegation_recovery_is_ownership_transfer -ne $false) { Fail "Stage-3.4.9 recovery authority boundary drifted" }
Pass "Replay remains read-only and recovery remains deterministic durable reconstruction only"

Write-Host "`n[10] Stage-3.4.10 no-new-authority / no-new-persistence proof"
if ($health.stage3_4_routing_delegation_acceptance_gate_new_route_selection_authority_added -ne $false) { Fail "Stage 3.4.10 added route-selection authority" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_governance_authorization_authority_added -ne $false) { Fail "Stage 3.4.10 added Governance authorization authority" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_delegation_authority_added -ne $false) { Fail "Stage 3.4.10 added delegation authority" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_ownership_transfer_authority_added -ne $false) { Fail "Stage 3.4.10 added ownership-transfer authority" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_task_dispatch_added -ne $false) { Fail "Stage 3.4.10 added task dispatch" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_target_action_dispatch_added -ne $false) { Fail "Stage 3.4.10 added target action dispatch" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_target_actuation_added -ne $false) { Fail "Stage 3.4.10 added target actuation" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_external_network_io_added -ne $false) { Fail "Stage 3.4.10 added external network I/O" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_durable_store_added -ne $false) { Fail "Stage 3.4.10 added a durable store" }
if ($health.stage3_4_routing_delegation_acceptance_gate_new_database_migration_added -ne $false) { Fail "Stage 3.4.10 added a database migration" }
Pass "Stage 3.4.10 is a pure acceptance/regression closure gate"

Write-Host "`n[11] Final no target execution expansion invariant"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
$forbiddenTrueFields = @(
    "task_routing_dispatch_performed",
    "task_routing_target_action_dispatch_enabled",
    "task_routing_target_actuation",
    "task_delegation_dispatch_performed",
    "task_delegation_execution_authorized",
    "delegation_delivery_dispatch_performed",
    "delegation_delivery_execution_authorized",
    "delegation_recovery_control_dispatch_performed",
    "delegation_recovery_control_execution_authorized",
    "routing_delegation_recovery_dispatch_performed",
    "routing_delegation_recovery_execution_authorized",
    "routing_delegation_recovery_target_action_dispatch_enabled",
    "routing_delegation_recovery_target_actuation"
)
foreach ($field in $forbiddenTrueFields) {
    if ($finalHealth.$field -ne $false) { Fail "Final execution boundary drifted: $field" }
}
Pass "Stage 3.4 closes with no task dispatch, target-action dispatch, execution grant, or target actuation expansion"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.10 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Control Version      : $($finalHealth.control_version)"
Write-Host "Repository Migration : $($finalHealth.mission_repository_migration_level)"
Write-Host "Stage-3.4 Baseline   : $($finalHealth.stage3_4_routing_delegation_acceptance_gate_baseline)"
Write-Host "Governance Authority : $($finalHealth.governance_authorization_authority)"
Write-Host "Replay Read Only     : $($finalHealth.routing_delegation_replay_read_only)"
Write-Host "Target Dispatch      : $($finalHealth.routing_delegation_recovery_target_action_dispatch_enabled)"
Write-Host "Target Actuation     : $($finalHealth.routing_delegation_recovery_target_actuation)"
Write-Host "=============================================================================="
exit 0
