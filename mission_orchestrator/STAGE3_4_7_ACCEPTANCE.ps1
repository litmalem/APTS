param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.7 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.4.7-delegation-delivery-acknowledgement-ownership"

Write-Host "=============================================================================="
Write-Host "Stage 3.4.7 - Delegation Delivery, Acknowledgement & Ownership Acceptance"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.4.7 source is not active on port 8780" }
Pass "Stage 3.4.7 runtime control is active"

Write-Host "`n[1] Python compile"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Full Stage 3.1-3.4.7 regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
Pass "Full regression passed"

Write-Host "`n[3] Focused Stage-3.4.7 contract proof"
python -m pytest -q tests\test_stage3_4_7_delegation_delivery_acknowledgement_ownership.py
if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.4.7 proof failed" }
Pass "Focused delivery, ACK, ownership, idempotency, persistence, lineage, and integrity tests passed"

Write-Host "`n[4] Health / persistence / upstream binding"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Runtime control version drifted" }
if ([int]$health.mission_repository_migration_level -ne 24) { Fail "Repository migration level is not 24" }
if ([int]$health.delegation_delivery_database_migration_level -ne 24) { Fail "Stage-3.4.7 migration declaration is not 24" }
if ($health.delegation_delivery_persistence_store -ne "mission_delegation_deliveries") { Fail "Unexpected Stage-3.4.7 persistence store" }
if ($health.delegation_delivery_schema_version -ne "apts-canonical-delegation-delivery-acknowledgement-ownership-v1") { Fail "Unexpected Stage-3.4.7 receipt schema" }
if ($health.delegation_delivery_mode -ne "CONTROL_PLANE_HANDOFF_DELIVERY_WITH_RECIPIENT_ACK_AND_OWNERSHIP_ACCEPTANCE_NO_DISPATCH") { Fail "Unexpected Stage-3.4.7 delivery mode" }
if ($health.delegation_delivery_channel -ne "CANONICAL_RECIPIENT_CONTROL_PLANE_INBOX") { Fail "Unexpected Stage-3.4.7 delivery channel" }
if ($health.delegation_delivery_requires_stage346_immutable_delegation -ne $true) { Fail "Stage-3.4.6 immutable delegation prerequisite is not enforced" }
if ($health.delegation_delivery_recipient_must_match_canonical_handoff -ne $true) { Fail "Canonical recipient-match invariant is absent" }
Pass "Canonical delivery/ACK/ownership persistence contract is active"

Write-Host "`n[5] Positive delivery / acknowledgement / ownership semantics"
if ($health.delegation_delivery_handoff_transmitted -ne $true) { Fail "Handoff transmission state is not active" }
if ($health.delegation_delivery_handoff_acknowledged -ne $true) { Fail "Handoff acknowledgement state is not active" }
if ($health.delegation_delivery_ownership_accepted -ne $true) { Fail "Ownership acceptance state is not active" }
if ($health.task_routing_handoff_transmitted -ne $true) { Fail "Aggregate routing state does not expose handoff transmission" }
if ($health.task_routing_handoff_acknowledged -ne $true) { Fail "Aggregate routing state does not expose handoff acknowledgement" }
if ($health.task_routing_ownership_accepted -ne $true) { Fail "Aggregate routing state does not expose ownership acceptance" }
Pass "Delivery, acknowledgement, and control-plane ownership acceptance are active"

Write-Host "`n[6] Negative runtime dispatch / execution boundary"
if ($health.delegation_delivery_runtime_endpoint_resolution_performed -ne $false) { Fail "Runtime endpoint resolution leaked into Stage 3.4.7" }
if ($health.delegation_delivery_runtime_health_probe_performed -ne $false) { Fail "Runtime health probing leaked into Stage 3.4.7" }
if ($health.delegation_delivery_resource_assignment_performed -ne $false) { Fail "Resource assignment leaked into Stage 3.4.7" }
if ($health.delegation_delivery_external_network_io_performed -ne $false) { Fail "External network I/O leaked into Stage 3.4.7" }
if ($health.delegation_delivery_dispatch_performed -ne $false) { Fail "Dispatch leaked into Stage 3.4.7" }
if ($health.delegation_delivery_execution_authorized -ne $false) { Fail "Execution authorization leaked into Stage 3.4.7" }
if ($health.delegation_delivery_governance_query_performed -ne $false) { Fail "A new Governance query leaked into Stage 3.4.7" }
if ($health.delegation_delivery_authorization_reused_as_execution_grant -ne $false) { Fail "Pre-delegation authorization was incorrectly reused as execution grant" }
if ($health.delegation_delivery_pre_dispatch_governance_revalidation_required -ne $true) { Fail "Pre-dispatch Governance revalidation invariant is absent" }
if ($health.task_routing_dispatch_performed -ne $false) { Fail "Aggregate dispatch state is not false" }
if ($health.task_routing_target_actuation -ne $false) { Fail "Target actuation leaked into Stage 3.4.7" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
Pass "Ownership remains distinct from dispatch, execution authority, and target actuation"

Write-Host "`n[7] Stage-3.4.6 source immutability semantics"
if ([int]$health.task_delegation_database_migration_level -ne 23) { Fail "Stage-3.4.6 migration declaration drifted" }
if ($health.task_delegation_persistence_store -ne "mission_task_delegations") { Fail "Stage-3.4.6 source store drifted" }
if ($health.task_delegation_handoff_envelope_materialized -ne $true) { Fail "Stage-3.4.6 handoff materialization drifted" }
if ($health.task_delegation_handoff_transmitted -ne $false) { Fail "Stage-3.4.6 immutable contract was semantically mutated" }
if ($health.task_delegation_handoff_acknowledged -ne $false) { Fail "Stage-3.4.6 immutable contract was semantically mutated by ACK" }
if ($health.task_delegation_ownership_accepted -ne $false) { Fail "Stage-3.4.6 immutable contract was semantically mutated by ownership" }
Pass "Stage 3.4.7 is append-only and preserves Stage-3.4.6 immutability"

Write-Host "`n[8] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 24) { Fail "Final migration level drifted" }
if ($finalHealth.delegation_delivery_handoff_transmitted -ne $true -or $finalHealth.delegation_delivery_handoff_acknowledged -ne $true -or $finalHealth.delegation_delivery_ownership_accepted -ne $true) {
    Fail "Final delivery/ACK/ownership state drifted"
}
if ($finalHealth.delegation_delivery_dispatch_performed -ne $false -or $finalHealth.delegation_delivery_execution_authorized -ne $false) {
    Fail "Final dispatch/execution boundary drifted"
}
if ($finalHealth.delegation_delivery_pre_dispatch_governance_revalidation_required -ne $true) {
    Fail "Final pre-dispatch Governance revalidation invariant drifted"
}
Pass "Stage 3.4.7 closure contract preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.7 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
