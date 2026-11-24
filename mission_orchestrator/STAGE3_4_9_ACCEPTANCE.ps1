param(
    [string]$MissionBaseUrl = "http://127.0.0.1:8780"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n=============================================================================="
    Write-Host "STAGE 3.4.9 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "=============================================================================="
    exit 1
}

function Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

$expectedControl = "stage3.4.9-routing-delegation-event-lineage-replay-recovery"
$expectedLineageSchema = "apts-routing-delegation-event-lineage-v1"
$expectedReplaySchema = "apts-routing-delegation-event-replay-v1"
$expectedRecoverySchema = "apts-routing-delegation-recovery-checkpoint-v1"
$expectedLineageMode = "CANONICAL_ROUTING_DELEGATION_EVENT_SUBCHAIN_WITH_ARTIFACT_CAUSATION_BINDINGS"
$expectedReplayMode = "READ_ONLY_DETERMINISTIC_ORDERED_ROUTING_DELEGATION_REPLAY_NO_SIDE_EFFECTS"
$expectedRecoveryMode = "DURABLE_ROUTING_DELEGATION_ARTIFACT_RECONSTRUCTION_NO_REROUTE_NO_REDELIVERY_NO_EXTERNAL_READS"

Write-Host "=============================================================================="
Write-Host "Stage 3.4.9 - Routing/Delegation Event Lineage, Replay & Recovery Acceptance"
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
if ($health.control_version -ne $expectedControl) { Fail "Stage 3.4.9 source is not active on port 8780" }
Pass "Stage 3.4.9 runtime control is active"

Write-Host "`n[1] Python compile"
python -m compileall -q mission_orchestrator tests
if ($LASTEXITCODE -ne 0) { Fail "Python compile failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Full Stage 3.1-3.4.9 regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Full regression failed" }
Pass "Full regression passed"

Write-Host "`n[3] Focused Stage-3.4.9 contract proof"
python -m pytest -q tests\test_stage3_4_9_routing_delegation_event_lineage_replay_recovery.py
if ($LASTEXITCODE -ne 0) { Fail "Focused Stage-3.4.9 proof failed" }
Pass "Focused lineage, replay, recovery, persistence, restart, idempotency, and tamper tests passed"

Write-Host "`n[4] Canonical lineage / replay / recovery contracts"
$health = Invoke-RestMethod "$MissionBaseUrl/health"
if ([int]$health.mission_repository_migration_level -ne 26) { Fail "Repository migration level is not 26" }
if ([int]$health.routing_delegation_recovery_database_migration_level -ne 26) { Fail "Stage-3.4.9 migration declaration is not 26" }
if ($health.routing_delegation_recovery_persistence_store -ne "mission_routing_delegation_recovery_checkpoints") { Fail "Unexpected Stage-3.4.9 persistence store" }
if ($health.routing_delegation_event_lineage_schema_version -ne $expectedLineageSchema) { Fail "Unexpected lineage schema version" }
if ($health.routing_delegation_event_replay_schema_version -ne $expectedReplaySchema) { Fail "Unexpected replay schema version" }
if ($health.routing_delegation_recovery_checkpoint_schema_version -ne $expectedRecoverySchema) { Fail "Unexpected recovery schema version" }
if ($health.routing_delegation_event_lineage_mode -ne $expectedLineageMode) { Fail "Unexpected lineage mode" }
if ($health.routing_delegation_event_replay_mode -ne $expectedReplayMode) { Fail "Unexpected replay mode" }
if ($health.routing_delegation_recovery_mode -ne $expectedRecoveryMode) { Fail "Unexpected recovery mode" }
if ($health.routing_delegation_recovery_requires_stage347_ownership_receipt -ne $true) { Fail "Stage-3.4.7 ownership prerequisite is not enforced" }
if ($health.routing_delegation_recovery_includes_stage348_control_chain -ne $true) { Fail "Stage-3.4.8 recovery-control chain is not included" }
Pass "Canonical Stage-3.4.9 lineage/replay/recovery contracts are active"

Write-Host "`n[5] Read-only replay and durable-recovery boundary"
if ($health.routing_delegation_replay_read_only -ne $true) { Fail "Replay is not read-only" }
if ($health.routing_delegation_replay_side_effects_performed -ne $false) { Fail "Replay reports side effects" }
if ($health.routing_delegation_recovery_reconstructs_from_durable_repository -ne $true) { Fail "Recovery is not durable-repository reconstruction" }
if ($health.routing_delegation_recovery_external_network_io_performed -ne $false) { Fail "External network I/O leaked into recovery" }
if ($health.routing_delegation_recovery_governance_query_performed -ne $false) { Fail "Governance query leaked into recovery" }
Pass "Replay is read-only and recovery reconstructs from durable local evidence only"

Write-Host "`n[6] Negative authorization / routing / delivery / execution boundary"
if ($health.routing_delegation_replay_is_execution -ne $false) { Fail "Replay was elevated into execution" }
if ($health.routing_delegation_recovery_is_authorization -ne $false) { Fail "Recovery was elevated into authorization" }
if ($health.routing_delegation_recovery_is_routing -ne $false) { Fail "Recovery was elevated into routing" }
if ($health.routing_delegation_recovery_is_redelivery -ne $false) { Fail "Recovery was elevated into redelivery" }
if ($health.routing_delegation_recovery_is_ownership_transfer -ne $false) { Fail "Recovery was elevated into ownership transfer" }
if ($health.routing_delegation_recovery_dispatch_performed -ne $false) { Fail "Dispatch leaked into Stage 3.4.9" }
if ($health.routing_delegation_recovery_execution_authorized -ne $false) { Fail "Execution authorization leaked into Stage 3.4.9" }
if ($health.routing_delegation_recovery_target_action_dispatch_enabled -ne $false) { Fail "Target-action dispatch leaked into Stage 3.4.9" }
if ($health.routing_delegation_recovery_target_actuation -ne $false) { Fail "Target actuation leaked into Stage 3.4.9" }
Pass "REPLAY != EXECUTION and RECOVERY remains non-authoritative/non-executing"

Write-Host "`n[7] Upstream Stage-3.4.8 boundary remains intact"
if ([int]$health.delegation_recovery_control_database_migration_level -ne 25) { Fail "Stage-3.4.8 migration declaration drifted" }
if ($health.delegation_recovery_control_persistence_store -ne "mission_delegation_recovery_controls") { Fail "Stage-3.4.8 persistence store drifted" }
if ($health.delegation_recovery_control_ownership_transfer_performed -ne $false) { Fail "Stage-3.4.8 ownership-transfer boundary drifted" }
if ($health.delegation_recovery_control_dispatch_performed -ne $false) { Fail "Stage-3.4.8 dispatch boundary drifted" }
if ($health.delegation_recovery_control_execution_authorized -ne $false) { Fail "Stage-3.4.8 execution boundary drifted" }
Pass "Stage 3.4.9 preserves Stage-3.4.8 and prior immutable authority boundaries"

Write-Host "`n[8] Final closure check"
$finalHealth = Invoke-RestMethod "$MissionBaseUrl/health"
if ($finalHealth.control_version -ne $expectedControl) { Fail "Final control version drifted" }
if ([int]$finalHealth.mission_repository_migration_level -ne 26) { Fail "Final migration level drifted" }
if ($finalHealth.routing_delegation_replay_read_only -ne $true) { Fail "Final read-only replay invariant drifted" }
if ($finalHealth.routing_delegation_recovery_dispatch_performed -ne $false -or $finalHealth.routing_delegation_recovery_execution_authorized -ne $false) {
    Fail "Final dispatch/execution boundary drifted"
}
Pass "Stage 3.4.9 closure contract preserved"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.4.9 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
