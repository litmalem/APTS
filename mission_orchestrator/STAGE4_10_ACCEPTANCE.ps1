param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedControl = "stage4.10-pentest-foundation-acceptance-gate"
$ExpectedPredecessor = "stage4.9-evidence-finding-lineage-foundation"
$ExpectedPentestMigration = 7
$ExpectedInventory = 1799
$ExpectedSchema = "apts-stage4.10-pentest-foundation-acceptance-gate-v1"
$ExpectedOutput = "PENTEST_SUBSYSTEM_PLATFORM"
$ExpectedNextStage = "5.1"
$ExpectedDimensions = @(
    "PERSISTENCE",
    "RESTART",
    "REPLAY",
    "IDEMPOTENCY",
    "DUPLICATE_PIP",
    "STALE_PIP",
    "INVALID_SCOPE",
    "DENIED_ACTION",
    "STOP_KILL",
    "EVENT_ORDERING",
    "CROSS_SUBSYSTEM_LINEAGE"
)

Write-Host "=============================================================================="
Write-Host "Stage 4.10 - Pentest Foundation Acceptance Gate"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
Write-Host "[PASS] Stage 3.9.10 remains authoritative"

Write-Host "`n[1] Stage 4.10 runtime activation preflight"
$healthWeb = Invoke-WebRequest "$PentestUrl/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSPentestSubsystem/4\.10") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest migration mismatch" }
if ($health.stage4_10_schema_version -ne $ExpectedSchema) { throw "Stage 4.10 schema inactive" }
if ($health.stage4_10_predecessor_control -ne $ExpectedPredecessor) { throw "Stage 4.10 predecessor mismatch" }
if ([int]$health.stage4_10_expected_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 4.10 expected migration mismatch" }
if (-not $health.stage4_10_declared_only) { throw "Stage 4.10 closure gate must be declared-only" }
if ($health.stage4_10_runtime_self_certification) { throw "Stage 4.10 runtime self-certification must remain disabled" }
if (-not $health.stage4_10_external_acceptance_execution_required) { throw "external acceptance execution is not required" }
if (-not $health.stage4_10_full_historical_regression_required) { throw "full historical regression is not required" }
if (@($health.stage4_10_required_stage4_controls).Count -ne 9) { throw "Stage 4 control count mismatch" }
if (@($health.stage4_10_required_acceptance_dimensions).Count -ne 11) { throw "Stage 4.10 acceptance dimension count mismatch" }
if (($health.stage4_10_required_acceptance_dimensions -join ",") -ne ($ExpectedDimensions -join ",")) { throw "Stage 4.10 acceptance dimensions mismatch" }
if ($health.stage4_10_new_database_migration_added -or $health.stage4_10_new_durable_store_added) { throw "unexpected Stage 4.10 persistence expansion" }
if ($health.stage4_10_new_authorization_authority_added -or $health.stage4_10_new_execution_authority_added -or $health.stage4_10_new_tool_authority_added) { throw "unexpected Stage 4.10 authority expansion" }
if ($health.stage4_10_policydecision_minting_performed -or $health.stage4_10_execution_intake_performed -or $health.stage4_10_tool_invocation_performed -or $health.stage4_10_external_network_io_performed -or $health.stage4_10_target_actuation) { throw "unexpected Stage 4.10 side effect" }
if (-not $health.stage4_9_lineage_projection_enabled -or -not $health.stage4_9_append_only_persistence_enabled) { throw "Stage 4.9 qualified foundation not preserved" }
if ($health.stage4_10_stage_output -ne $ExpectedOutput) { throw "Stage 4 output mismatch" }
if ($health.stage4_10_next_stage -ne $ExpectedNextStage) { throw "Stage 4.10 next-stage mismatch" }
Write-Host "[PASS] Stage 4.10 active, migration 7 unchanged, closure gate is declarative"

Write-Host "`n[2] Canonical Stage 4.10 acceptance contract"
$gate = Invoke-RestMethod "$PentestUrl/api/pentest/foundation-acceptance-gate-contract"
if ($gate.control_version -ne $ExpectedControl) { throw "acceptance contract route mismatch" }
if ($gate.definition.schema_version -ne $ExpectedSchema) { throw "acceptance contract schema mismatch" }
if ($gate.definition.predecessor_control -ne $ExpectedPredecessor) { throw "acceptance contract predecessor mismatch" }
if ([int]$gate.definition.expected_repository_migration_level -ne $ExpectedPentestMigration) { throw "acceptance contract migration mismatch" }
if ([int]$gate.definition.required_stage4_control_count -ne 9) { throw "required Stage 4 control count mismatch" }
if ([int]$gate.definition.required_acceptance_dimension_count -ne 11) { throw "required acceptance dimension count mismatch" }
if (($gate.definition.required_acceptance_dimensions -join ",") -ne ($ExpectedDimensions -join ",")) { throw "roadmap acceptance dimensions mismatch" }
if (-not $gate.definition.declared_only -or $gate.definition.runtime_self_certification) { throw "acceptance gate closure semantics mismatch" }
if (-not $gate.definition.external_acceptance_execution_required -or -not $gate.definition.full_historical_regression_required) { throw "acceptance execution requirements mismatch" }
if ($gate.definition.new_database_migration_added -or $gate.definition.new_durable_store_added -or $gate.definition.new_runtime_authority_added -or $gate.definition.target_actuation) { throw "acceptance contract boundary expansion detected" }
if ($gate.definition.stage_output -ne $ExpectedOutput) { throw "acceptance contract Stage 4 output mismatch" }
if ($gate.definition.next_stage -ne $ExpectedNextStage) { throw "acceptance contract next-stage mismatch" }
if (-not $gate.read_only) { throw "acceptance contract route must be read-only" }
if ($gate.runtime_self_certification) { throw "acceptance route incorrectly self-certifies" }
Write-Host "[PASS] SHA-bound Pentest foundation acceptance contract"

Write-Host "`n[3] Execution-intake negative boundary"
$rejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $rejected = $true } else { throw }
}
if (-not $rejected) { throw "Stage 4.10 execution intake was not rejected" }
Write-Host "[PASS] execution intake remains fail-closed; Stage 6 retains controlled execution authority"

Write-Host "`n[4] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[5] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[6] Focused Stage 4.10 regression"
python -m pytest -q tests/test_stage4_10_pentest_foundation_acceptance_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.10 focused regression failed" }

Write-Host "`n[7] Stage 4.1 -> 4.10 qualification chain"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py `
  tests/test_stage4_7_capability_registry_tool_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1-4.10 qualification chain failed" }

Write-Host "`n[8] Explicit Stage 4.10 roadmap acceptance dimensions"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py::test_01_canonical_boundary_binds_stage3910_and_registered_pentest_subsystem `
  tests/test_stage4_2_pip_ingestion_validation_binding.py::test_08_freshness_rejects_future_expired_and_invalid_intervals `
  tests/test_stage4_3_pentest_mission_task_contract.py::test_14_repository_create_is_idempotent_for_exact_same_task_and_binding `
  tests/test_stage4_4_pentest_lifecycle_state.py::test_19_failed_and_aborted_remain_fail_safe_exits_even_if_task_content_is_corrupted `
  tests/test_stage4_4_pentest_lifecycle_state.py::test_20_transition_replay_is_idempotent_and_identity_reuse_conflicts `
  tests/test_stage4_5_pentest_event_runtime_contract.py::test_13_event_stream_sequence_and_hash_chain_verify `
  tests/test_stage4_5_pentest_event_runtime_contract.py::test_19_startup_reconciliation_recovers_missing_latest_event `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py::test_09_exact_start_replay_is_idempotent `
  tests/test_stage4_8_governance_scope_roe_enforcement.py::test_06_target_outside_allowlist_fails_closed `
  tests/test_stage4_8_governance_scope_roe_enforcement.py::test_09_prohibited_action_class_is_ineligible `
  tests/test_stage4_8_governance_scope_roe_enforcement.py::test_14_stop_signal_blocks_further_eligibility `
  tests/test_stage4_8_governance_scope_roe_enforcement.py::test_17_exact_replay_is_idempotent_and_does_not_duplicate_audit_record `
  tests/test_stage4_8_governance_scope_roe_enforcement.py::test_19_restart_preserves_and_verifies_decision `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py::test_15_full_canonical_chain_reconstructs_single_head_and_all_type_counts `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py::test_17_exact_replay_is_idempotent_and_preserves_sequence `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py::test_22_restart_preserves_records_and_projection `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.10 roadmap acceptance-dimension regression failed" }

Write-Host "`n[9] Critical Stage 3 -> Stage 4 lineage / governance / closure regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_8_governance_scope_roe_enforcement.py `
  tests/test_stage4_9_evidence_finding_lineage_foundation.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py
if ($LASTEXITCODE -ne 0) { throw "critical Stage 3 -> Stage 4 regression failed" }

Write-Host "`n[10] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.10 Pentest Foundation Acceptance Gate"
Write-Host "control_version   : $ExpectedControl"
Write-Host "pentest migration : $ExpectedPentestMigration (unchanged)"
Write-Host "inventory         : $ExpectedInventory"
Write-Host "acceptance dims   : persistence / restart / replay / idempotency / duplicate PIP / stale PIP / invalid scope / denied action / stop-kill / event ordering / cross-subsystem lineage"
Write-Host "gate authority    : external acceptance harness; runtime self-certification disabled"
Write-Host "boundary          : no new persistence / authorization / execution / tool / network / target authority"
Write-Host "STAGE 4 OUTPUT    : PENTEST SUBSYSTEM PLATFORM"
Write-Host "next              : Stage 5.1 - Full Agentic Pentest Workflow Orchestrator"
Write-Host "=============================================================================="
