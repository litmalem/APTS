param(
    [string]$MissionBaseUrl = 'http://127.0.0.1:8780',
    [string]$MissionId = ''
)
$ErrorActionPreference = 'Stop'
function Fail([string]$Reason) { Write-Host "STAGE 3.8.10 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red; exit 1 }
function Pass([string]$Reason) { Write-Host "[PASS] $Reason" -ForegroundColor Green }
Set-Location $PSScriptRoot

Write-Host "=============================================================================="
Write-Host "Stage 3.8.10 - Observe / Reconstruct Acceptance & Regression Gate"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.control_version -ne 'stage3.8.10-observe-reconstruct-acceptance-regression-gate') { Fail 'runtime control not active; install overlay and restart service' }
if ($health.mission_repository_migration_level -ne 53 -or
    $health.stage3_8_observe_reconstruct_acceptance_gate_expected_migration_level -ne 53 -or
    $health.forensic_query_evidence_bundle_database_migration_level -ne 53) { Fail 'migration level mismatch' }
if ($health.stage3_8_observe_reconstruct_acceptance_gate_declared_only -ne $true -or
    $health.stage3_8_observe_reconstruct_acceptance_gate_runtime_self_certification -ne $false -or
    $health.stage3_8_observe_reconstruct_acceptance_gate_external_execution_required -ne $true) { Fail 'closure contract metadata mismatch' }
foreach($field in @(
    'stage3_8_observe_reconstruct_acceptance_gate_new_observability_identity_authority_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_event_ingestion_authority_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_lineage_authority_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_live_state_authority_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_decision_authority_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_reconstruction_authority_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_repair_authority_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_governance_query_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_runtime_query_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_external_network_io_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_telemetry_export_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_mission_state_transition_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_routing_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_delegation_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_dispatch_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_execution_attempt_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_target_actuation_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_durable_store_added',
    'stage3_8_observe_reconstruct_acceptance_gate_new_database_migration_added',
    'stage3_8_observe_reconstruct_acceptance_gate_closure_gate_is_observability_source',
    'stage3_8_observe_reconstruct_acceptance_gate_closure_gate_is_reconstruction_execution',
    'stage3_8_observe_reconstruct_acceptance_gate_closure_gate_is_forensic_attestation',
    'stage3_8_observe_reconstruct_acceptance_gate_closure_gate_is_integrity_repair',
    'stage3_8_observe_reconstruct_acceptance_gate_closure_gate_is_runtime_control',
    'stage3_8_observe_reconstruct_acceptance_gate_closure_gate_is_governance_authority',
    'stage3_8_observe_reconstruct_acceptance_gate_closure_gate_is_dispatch_authority',
    'stage3_8_observe_reconstruct_acceptance_gate_stage389_verified_bundle_is_external_attestation',
    'stage3_8_observe_reconstruct_acceptance_gate_stage389_reconstruction_is_runtime_resumption',
    'stage3_8_observe_reconstruct_acceptance_gate_stage389_reconstruction_is_mission_reexecution'
)) {
    if ($health.$field -ne $false) { Fail "authority/boundary field must be false: $field" }
}
if ($health.supported_controls[-2] -ne 'stage3.8.9-forensic-query-evidence-bundle-reconstruction-api' -or
    $health.supported_controls[-1] -ne 'stage3.8.10-observe-reconstruct-acceptance-regression-gate') { Fail 'supported control chain mismatch' }
Pass 'runtime closure contract active'

try { $contract = Invoke-RestMethod "$MissionBaseUrl/api/observability/forensic-contract" } catch { Fail "forensic contract route unavailable: $($_.Exception.Message)" }
if ($contract.definition.schema_version -ne 'apts-forensic-query-evidence-bundle-reconstruction-v1' -or
    $contract.definition.runtime_side_effects -ne $false -or
    $contract.definition.external_attestation -ne $false -or
    $contract.definition.atomic_database_snapshot -ne $false) { Fail 'Stage 3.8.9 forensic contract mismatch' }
Pass 'Stage 3.8.9 forensic contract preserved'

if ($MissionId) {
    $safeMissionId = [uri]::EscapeDataString($MissionId)
    $missionUrl = "$MissionBaseUrl/api/missions/$safeMissionId"
    try {
        $before = Invoke-RestMethod "$missionUrl/events"
        $bundle1 = Invoke-RestMethod "$missionUrl/forensic-evidence-bundle"
        $reconstruction1 = Invoke-RestMethod "$missionUrl/forensic-reconstruction"
        $query = Invoke-RestMethod "$missionUrl/forensic-query?scope=events"
        $bundle2 = Invoke-RestMethod "$missionUrl/forensic-evidence-bundle"
        $reconstruction2 = Invoke-RestMethod "$missionUrl/forensic-reconstruction"
        $after = Invoke-RestMethod "$missionUrl/events"
    } catch { Fail "Mission observe/reconstruct probe unavailable: $($_.Exception.Message)" }
    if ($bundle1.integrity_status -ne 'PASS' -or $bundle1.bundle.status -ne 'VERIFIED' -or
        $bundle1.bundle.mission_id -ne $MissionId -or $bundle1.bundle.diagnostics.status -ne 'PASS' -or
        $bundle1.bundle.record_counts.mission_events -ne $before.event_count -or
        $reconstruction1.result.status -ne 'VERIFIED' -or
        $reconstruction1.result.reconstruction.event_count -ne $before.event_count -or
        $query.result.status -ne 'VERIFIED' -or $query.result.result.events.Count -ne $before.event_count -or
        $bundle1.bundle.integrity.canonical_sha256 -ne $bundle2.bundle.integrity.canonical_sha256 -or
        $reconstruction1.result.integrity.canonical_sha256 -ne $reconstruction2.result.integrity.canonical_sha256 -or
        $before.event_count -ne $after.event_count -or
        $before.events[-1].canonical_sha256 -ne $after.events[-1].canonical_sha256) { Fail 'observe/reconstruct consistency, determinism, or read-only invariant failed' }
    Pass "verified cross-view observe/reconstruct Mission: $MissionId"
}

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1431 tests collected') { Fail 'canonical inventory must contain 1431 tests' }
Pass '1431 tests collected'

$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch '(?m)^1431 passed') { Fail 'full regression failed' }
Pass 'full regression'

$focused = (& python -m pytest -q tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch '(?m)^4 passed') { Fail 'focused Stage 3.8.10 regression failed' }
Pass '4 focused Stage 3.8.10 tests'

Write-Host "=============================================================================="
Write-Host 'STAGE 3.8.10 ACCEPTANCE: PASS' -ForegroundColor Green
Write-Host 'Stage 3.8 closed: trace -> normalize -> causal graph -> live projection -> decision evidence -> timeline -> diagnostics -> metrics/health -> forensic query/reconstruction -> acceptance.'
Write-Host 'Repository migration level: 53 (unchanged); new durable store: NONE; new migration: NONE.'
Write-Host 'Stage 3.8.10 is declaration-only and adds no observation, reconstruction, repair, governance, dispatch, execution, or target authority.'
Write-Host "=============================================================================="
