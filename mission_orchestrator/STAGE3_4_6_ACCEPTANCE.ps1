param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.6 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.4.6-canonical-delegation-contract-handoff-envelope"

Write-Host "=============================================================================="
Write-Host "Stage 3.4.6 - Canonical Delegation Contract & Handoff Envelope Acceptance"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.4.6 source is not active on port 8780" }
Pass "Stage 3.4.6 runtime control is active"

Write-Host "`n[1] Python compile"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Full Stage 3.1-3.4.6 regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
Pass "Full regression passed"

Write-Host "`n[3] Focused Stage-3.4.6 contract proof"
python -m pytest -q tests\test_stage3_4_6_canonical_delegation_contract_handoff_envelope.py
if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.4.6 proof failed" }
Pass "Focused delegation, handoff, idempotency, persistence, lineage, and integrity tests passed"

Write-Host "`n[4] Health / persistence / authority boundary"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ($health.control_version -ne $expectedControl) { Fail "Runtime control version drifted" }
if ([int]$health.mission_repository_migration_level -ne 23) { Fail "Repository migration level is not 23" }
if ([int]$health.task_delegation_database_migration_level -ne 23) { Fail "Stage-3.4.6 migration declaration is not 23" }
if ($health.task_delegation_persistence_store -ne "mission_task_delegations") { Fail "Unexpected Stage-3.4.6 persistence store" }
if ($health.delegation_contract_schema_version -ne "apts-canonical-delegation-contract-v1") { Fail "Unexpected delegation contract schema" }
if ($health.delegation_handoff_envelope_schema_version -ne "apts-canonical-delegation-handoff-envelope-v1") { Fail "Unexpected handoff envelope schema" }
if ($health.task_delegation_mode -ne "AUTHORIZED_LOGICAL_DELEGATION_WITH_IMMUTABLE_HANDOFF_ENVELOPE_NO_DISPATCH") { Fail "Unexpected Stage-3.4.6 delegation mode" }
if ($health.task_delegation_handoff_mode -ne "IMMUTABLE_CONTEXT_HANDOFF_MATERIALIZED_NOT_TRANSMITTED") { Fail "Unexpected Stage-3.4.6 handoff mode" }
if ($health.task_delegation_requires_stage345_authorized_decision -ne $true) { Fail "Stage-3.4.5 AUTHORIZED prerequisite is not enforced" }
if ($health.task_delegation_recipient_derived_from_stage344_route -ne $true) { Fail "Recipient is not declared as Stage-3.4.4-derived" }
if ($health.task_delegation_work_context_derived_from_planned_task_and_scope -ne $true) { Fail "Work context is not canonical-source derived" }
if ($health.task_delegation_delegation_performed -ne $true) { Fail "Logical delegation is not active" }
if ($health.task_delegation_handoff_envelope_materialized -ne $true) { Fail "Handoff envelope is not materialized" }
if ($health.task_routing_delegation_performed -ne $true) { Fail "Aggregate routing state does not expose Stage-3.4.6 delegation" }
Pass "Canonical delegation and persistence contract is active"

Write-Host "`n[5] Negative dispatch / execution boundary"
if ($health.task_delegation_handoff_transmitted -ne $false) { Fail "Handoff transmission leaked into Stage 3.4.6" }
if ($health.task_delegation_handoff_acknowledged -ne $false) { Fail "Handoff ACK leaked into Stage 3.4.6" }
if ($health.task_delegation_ownership_accepted -ne $false) { Fail "Recipient ownership acceptance leaked into Stage 3.4.6" }
if ($health.task_delegation_runtime_endpoint_resolution_performed -ne $false) { Fail "Runtime endpoint resolution leaked into Stage 3.4.6" }
if ($health.task_delegation_runtime_health_probe_performed -ne $false) { Fail "Runtime health probing leaked into Stage 3.4.6" }
if ($health.task_delegation_resource_assignment_performed -ne $false) { Fail "Resource assignment leaked into Stage 3.4.6" }
if ($health.task_delegation_dispatch_performed -ne $false) { Fail "Dispatch leaked into Stage 3.4.6" }
if ($health.task_delegation_execution_authorized -ne $false) { Fail "Execution authorization leaked into Stage 3.4.6" }
if ($health.task_delegation_governance_query_performed -ne $false) { Fail "A new Governance query leaked into Stage 3.4.6" }
if ($health.task_delegation_authorization_reused_as_execution_grant -ne $false) { Fail "Stage-3.4.5 authorization was incorrectly reused as an execution grant" }
if ($health.task_delegation_pre_dispatch_governance_revalidation_required -ne $true) { Fail "Pre-dispatch Governance revalidation invariant is absent" }
if ($health.task_routing_dispatch_performed -ne $false) { Fail "Aggregate dispatch state is not false" }
if ($health.task_routing_target_actuation -ne $false) { Fail "Target actuation leaked into Stage 3.4.6" }
if ($health.governance_authorization_authority -ne "EXTERNAL_APTS_GSS") { Fail "Governance authorization authority changed" }
Pass "Materialization remains distinct from transmission, ownership, dispatch, and execution"

Write-Host "`n[6] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 23) { Fail "Final migration level drifted" }
if ($finalHealth.task_delegation_delegation_performed -ne $true) { Fail "Final delegation state drifted" }
if ($finalHealth.task_delegation_handoff_envelope_materialized -ne $true) { Fail "Final handoff materialization state drifted" }
if ($finalHealth.task_delegation_handoff_transmitted -ne $false -or $finalHealth.task_delegation_dispatch_performed -ne $false -or $finalHealth.task_delegation_execution_authorized -ne $false) {
    Fail "Final handoff/dispatch/execution boundary drifted"
}
if ($finalHealth.task_delegation_pre_dispatch_governance_revalidation_required -ne $true) {
    Fail "Final pre-dispatch Governance revalidation invariant drifted"
}
Pass "Stage 3.4.6 closure contract preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.6 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
