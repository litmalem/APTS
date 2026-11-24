param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.8 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.4.8-retry-fallback-reassignment-conflict-control"
$expectedSchema = "apts-canonical-delegation-retry-fallback-reassignment-conflict-control-v1"
$expectedMode = "CONTROL_PLANE_RETRY_FALLBACK_REASSIGNMENT_CONFLICT_CONTROL_NO_DISPATCH"

Write-Host "=============================================================================="
Write-Host "Stage 3.4.8 - Retry, Fallback, Reassignment & Conflict Control Acceptance"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.4.8 source is not active on port 8780" }
Pass "Stage 3.4.8 runtime control is active"

Write-Host "`n[1] Python compile"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Full Stage 3.1-3.4.8 regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
Pass "Full regression passed"

Write-Host "`n[3] Focused Stage-3.4.8 contract proof"
python -m pytest -q tests\test_stage3_4_8_retry_fallback_reassignment_conflict_control.py
if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.4.8 proof failed" }
Pass "Focused retry, fallback, reassignment, conflict, idempotency, persistence, lineage, and integrity tests passed"

Write-Host "`n[4] Health / persistence / upstream ownership binding"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Runtime control version drifted" }
if ([int]$health.mission_repository_migration_level -ne 25) { Fail "Repository migration level is not 25" }
if ([int]$health.delegation_recovery_control_database_migration_level -ne 25) { Fail "Stage-3.4.8 migration declaration is not 25" }
if ($health.delegation_recovery_control_persistence_store -ne "mission_delegation_recovery_controls") { Fail "Unexpected Stage-3.4.8 persistence store" }
if ($health.delegation_recovery_control_schema_version -ne $expectedSchema) { Fail "Unexpected Stage-3.4.8 schema version" }
if ($health.delegation_recovery_control_mode -ne $expectedMode) { Fail "Unexpected Stage-3.4.8 control mode" }
if ($health.delegation_recovery_control_requires_stage347_ownership_receipt -ne $true) { Fail "Stage-3.4.7 ownership prerequisite is not enforced" }
if ([int]$health.delegation_recovery_control_max_retry_attempts -ne 3) { Fail "Retry budget is not exactly 3" }
Pass "Canonical Stage-3.4.8 persistence and ownership-chain prerequisites are active"

Write-Host "`n[5] Retry / fallback / reassignment policy"
if ($health.delegation_recovery_control_fallback_source -ne "IMMUTABLE_STAGE344_RANKED_ELIGIBLE_CANDIDATES_ONLY") { Fail "Fallback source is not immutable Stage-3.4.4 ranking" }
if ($health.delegation_recovery_control_caller_selected_fallback_forbidden -ne $true) { Fail "Caller-selected fallback is not forbidden" }
if ($health.delegation_recovery_control_retry_retains_current_owner -ne $true) { Fail "Retry does not retain current owner" }
if ($health.delegation_recovery_control_ownership_transfer_performed -ne $false) { Fail "Stage 3.4.8 incorrectly transfers ownership" }
if ($health.delegation_recovery_control_optimistic_conflict_control -ne "EXPECTED_CONTROL_COUNT_PLUS_TRANSACTIONAL_SEQUENCE_GUARD") { Fail "Unexpected optimistic conflict-control mode" }
Pass "Bounded retry, deterministic fallback source, no ownership transfer, and CAS conflict control are active"

Write-Host "`n[6] Negative runtime dispatch / execution boundary"
if ($health.delegation_recovery_control_runtime_endpoint_resolution_performed -ne $false) { Fail "Runtime endpoint resolution leaked into Stage 3.4.8" }
if ($health.delegation_recovery_control_runtime_health_probe_performed -ne $false) { Fail "Runtime health probing leaked into Stage 3.4.8" }
if ($health.delegation_recovery_control_resource_assignment_performed -ne $false) { Fail "Resource assignment leaked into Stage 3.4.8" }
if ($health.delegation_recovery_control_external_network_io_performed -ne $false) { Fail "External network I/O leaked into Stage 3.4.8" }
if ($health.delegation_recovery_control_governance_query_performed -ne $false) { Fail "A new Governance query leaked into Stage 3.4.8" }
if ($health.delegation_recovery_control_dispatch_performed -ne $false) { Fail "Dispatch leaked into Stage 3.4.8" }
if ($health.delegation_recovery_control_execution_authorized -ne $false) { Fail "Execution authorization leaked into Stage 3.4.8" }
if ($health.delegation_recovery_control_pre_dispatch_governance_revalidation_required -ne $true) { Fail "Pre-dispatch Governance revalidation invariant is absent" }
if ($health.task_routing_dispatch_performed -ne $false) { Fail "Aggregate dispatch state is not false" }
if ($health.task_routing_target_actuation -ne $false) { Fail "Target actuation leaked into Stage 3.4.8" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
Pass "Stage 3.4.8 remains control-plane only with no dispatch, execution, or target actuation"

Write-Host "`n[7] Stage-3.4.6 / Stage-3.4.7 immutability boundary"
if ([int]$health.task_delegation_database_migration_level -ne 23) { Fail "Stage-3.4.6 migration declaration drifted" }
if ($health.task_delegation_persistence_store -ne "mission_task_delegations") { Fail "Stage-3.4.6 source store drifted" }
if ([int]$health.delegation_delivery_database_migration_level -ne 24) { Fail "Stage-3.4.7 migration declaration drifted" }
if ($health.delegation_delivery_persistence_store -ne "mission_delegation_deliveries") { Fail "Stage-3.4.7 source store drifted" }
if ($health.delegation_delivery_handoff_transmitted -ne $true) { Fail "Stage-3.4.7 transmitted state drifted" }
if ($health.delegation_delivery_handoff_acknowledged -ne $true) { Fail "Stage-3.4.7 acknowledgement state drifted" }
if ($health.delegation_delivery_ownership_accepted -ne $true) { Fail "Stage-3.4.7 ownership state drifted" }
if ($health.task_delegation_handoff_transmitted -ne $false) { Fail "Stage-3.4.6 immutable handoff source was mutated" }
if ($health.task_delegation_handoff_acknowledged -ne $false) { Fail "Stage-3.4.6 immutable source was mutated by acknowledgement" }
if ($health.task_delegation_ownership_accepted -ne $false) { Fail "Stage-3.4.6 immutable source was mutated by ownership" }
Pass "Stage 3.4.8 is append-only and preserves Stage-3.4.6/3.4.7 evidence boundaries"

Write-Host "`n[8] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 25) { Fail "Final migration level drifted" }
if ([int]$finalHealth.delegation_recovery_control_max_retry_attempts -ne 3) { Fail "Final retry budget drifted" }
if ($finalHealth.delegation_recovery_control_ownership_transfer_performed -ne $false) { Fail "Final ownership-transfer boundary drifted" }
if ($finalHealth.delegation_recovery_control_dispatch_performed -ne $false -or $finalHealth.delegation_recovery_control_execution_authorized -ne $false) {
    Fail "Final dispatch/execution boundary drifted"
}
if ($finalHealth.delegation_recovery_control_pre_dispatch_governance_revalidation_required -ne $true) {
    Fail "Final pre-dispatch Governance revalidation invariant drifted"
}
Pass "Stage 3.4.8 closure contract preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.8 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
